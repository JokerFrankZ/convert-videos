from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from progress_tracker import StageProgressTracker, TaskProgressEmitter


class ConverterError(Exception):
    """Raised when a conversion cannot be completed."""


class ConversionCancelled(Exception):
    """Raised when a conversion is cancelled by the user."""


LogCallback = Callable[[str], None]


@dataclass(slots=True)
class ConversionProgress:
    task_index: int
    total_tasks: int
    task_name: str
    stage: str
    task_progress: float
    overall_progress: float


ProgressCallback = Callable[[ConversionProgress], None]


@dataclass(slots=True)
class ConversionTask:
    display_name: str
    source: Path
    output_stem: str
    is_sequence: bool = False
    sequence_pattern: Optional[str] = None
    frame_extension: Optional[str] = None
    frame_count: Optional[int] = None
    first_frame: Optional[Path] = None
    start_number: Optional[int] = None
    total_frames: Optional[int] = None
    duration_ms: Optional[int] = None


@dataclass(slots=True)
class ControlSignals:
    pause_event: threading.Event = field(default_factory=threading.Event)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _process: Optional[subprocess.Popen] = None
    cancel_reason: str | None = None

    def attach(self, process: Optional[subprocess.Popen]) -> None:
        self._process = process
        if process is None:
            self.pause_event.set()

    def request_pause(self) -> None:
        self.pause_event.clear()
        if self._process and sys.platform != "win32":
            try:
                self._process.send_signal(signal.SIGSTOP)
            except Exception:
                pass

    def request_resume(self) -> None:
        self.pause_event.set()
        if self._process and sys.platform != "win32":
            try:
                self._process.send_signal(signal.SIGCONT)
            except Exception:
                pass

    def request_cancel(self, reason: str | None = None) -> None:
        self.cancel_reason = reason or "转换已被终止"
        self.cancel_event.set()
        self.pause_event.set()
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass


@dataclass(slots=True)
class ConversionRequest:
    tasks: Iterable[ConversionTask]
    output_dir: Path
    width: int = 259
    height: int = 194
    fps: float = 10.0
    quality: str = "high"
    signals: ControlSignals | None = None


def _resource_root() -> Path:
    """Return the root path where packaged resources live."""

    if getattr(sys, "_MEIPASS", None):  # PyInstaller temporary directory
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]

    # When running from source, resources are located at project root
    return Path(__file__).resolve().parent.parent


def _get_binary_path(tool_name: str) -> Path:
    """Locate a bundled ffmpeg-related binary."""

    base_path = _resource_root() / "resources" / "ffmpeg"

    if sys.platform.startswith("win"):
        platform_dir = "windows"
        binary_name = f"{tool_name}.exe"
    elif sys.platform == "darwin":
        platform_dir = "macos"
        binary_name = tool_name
    else:
        raise ConverterError("当前平台暂不支持，请使用 Windows 或 macOS。")

    binary_path = base_path / platform_dir / binary_name

    if not binary_path.exists():
        raise ConverterError(
            f"未找到 {tool_name} 可执行文件。请将对应平台的 {tool_name} 置于 resources/ffmpeg/<platform>/ 目录下。"
        )

    if not os.access(binary_path, os.X_OK):
        try:
            binary_path.chmod(binary_path.stat().st_mode | stat.S_IEXEC)
        except PermissionError as exc:  # pragma: no cover - depends on FS
            raise ConverterError(f"无法为 {tool_name} 设置可执行权限") from exc

    return binary_path


def get_ffmpeg_executable() -> Path:
    """Locate the ffmpeg binary bundled with the application."""

    return _get_binary_path("ffmpeg")


def get_ffprobe_executable() -> Path:
    return _get_binary_path("ffprobe")


def probe_video_metadata(
    video_path: Path,
) -> Tuple[int, int, float, Optional[int], Optional[int]]:
    """Return width, height, fps, total frames, duration ms."""

    ffprobe_path = get_ffprobe_executable()

    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,nb_frames,duration_ts,time_base",
        "-of",
        "json",
        str(video_path),
    ]

    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if process.returncode != 0:
        message = process.stderr.strip() or "无法读取视频信息"
        raise ConverterError(message)

    try:
        data = json.loads(process.stdout)
        stream = data["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        rate = stream.get("r_frame_rate", "0/1")
        fraction = Fraction(rate)
        if fraction.denominator == 0:
            raise ZeroDivisionError
        fps = float(fraction)
        nb_frames = stream.get("nb_frames")
        if nb_frames and nb_frames.isdigit():
            total_frames = int(nb_frames)
        else:
            total_frames = None
        duration_ts = stream.get("duration_ts")
        time_base = stream.get("time_base")
        duration_ms = None
        if duration_ts and time_base:
            num, denom = time_base.split("/")
            duration_seconds = int(duration_ts) * (int(num) / int(denom))
            duration_ms = int(duration_seconds * 1000)
    except (
        KeyError,
        IndexError,
        ValueError,
        ZeroDivisionError,
        json.JSONDecodeError,
    ) as exc:
        raise ConverterError("解析视频信息失败") from exc

    if total_frames is None:
        count_command = [
            str(ffprobe_path),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(video_path),
        ]
        count_process = subprocess.run(
            count_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if count_process.returncode == 0:
            try:
                total_frames = int(count_process.stdout.strip())
            except ValueError:
                total_frames = None

    if total_frames is None and duration_ms is not None:
        total_frames = max(1, int(fps * duration_ms / 1000))

    if width <= 0 or height <= 0 or fps <= 0:
        raise ConverterError("获取到的视频参数无效")

    return width, height, fps, total_frames, duration_ms


def probe_image_metadata(
    image_path: Path,
) -> Tuple[int, int, Optional[int], Optional[int]]:
    from PIL import Image

    try:
        with Image.open(image_path) as img:
            width, height = img.size
    except Exception as exc:  # noqa: BLE001
        raise ConverterError(f"解析图片信息失败：{image_path.name}") from exc

    if width <= 0 or height <= 0:
        raise ConverterError("获取到的图片尺寸无效")

    return width, height, None, 150


def _gif_filter(width: int, height: int, fps: float) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps}"
    )


def _gif_quality_filter(base_filter: str, quality: str) -> str:
    presets = {
        "low": base_filter,
        "medium": (
            f"{base_filter},split[s0][s1];[s0]palettegen=max_colors=256[p];"
            "[s1][p]paletteuse"
        ),
        "high": (
            f"{base_filter},split[s0][s1];[s0]palettegen="
            "max_colors=256:stats_mode=single[p];[s1][p]paletteuse="
            "dither=bayer:bayer_scale=2"
        ),
        "ultra": (
            f"{base_filter},split[s0][s1];[s0]palettegen="
            "max_colors=256:stats_mode=full:reserve_transparent=0[p];"
            "[s1][p]paletteuse=dither=sierra2_4a"
        ),
    }

    try:
        return presets[quality]
    except KeyError as exc:  # pragma: no cover - guarded elsewhere
        raise ConverterError("质量参数必须是 low, medium, high 或 ultra") from exc


def _run_command(command: list[str]) -> Tuple[int, str]:
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return process.returncode, process.stderr.strip()


def _run_ffmpeg_with_progress(
    command: list[str],
    *,
    emit: Callable[[float, str], None] | None,
    stage_label: str,
    base: float,
    extent: float,
    frame_estimate: Optional[int],
    duration_ms: Optional[int],
    signals: ControlSignals | None = None,
) -> tuple[int, str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    if signals:
        signals.attach(process)

    tracker = StageProgressTracker(
        stage_label=stage_label,
        base=base,
        extent=extent,
        emit=emit,
    )
    cancelled = False

    try:
        tracker.emit_initial()

        if process.stdout:
            for raw_line in process.stdout:
                if signals and signals.cancel_event.is_set():
                    cancelled = True
                    process.terminate()
                    break
                while (
                    signals
                    and not signals.pause_event.is_set()
                    and not signals.cancel_event.is_set()
                ):
                    time.sleep(0.05)
                if signals and signals.cancel_event.is_set():
                    cancelled = True
                    process.terminate()
                    break

                now = time.monotonic()
                if tracker.needs_synthetic_update(now):
                    tracker.synthetic_step(
                        duration_ms=duration_ms,
                        frame_estimate=frame_estimate,
                    )

                line = raw_line.strip()
                if "=" not in line:
                    continue
                key, _, value_text = line.partition("=")

                tracker.try_update_from_ffmpeg(
                    key=key,
                    value_text=value_text,
                    frame_estimate=frame_estimate,
                    duration_ms=duration_ms,
                )
    finally:
        if process.stdout:
            process.stdout.close()

    if process.stderr:
        stderr_output = process.stderr.read()
        process.stderr.close()
    else:
        stderr_output = ""

    if signals:
        signals.attach(None)

    if cancelled:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise ConversionCancelled

    returncode = process.wait()
    tracker.finish()
    return returncode, stderr_output


def convert_files(
    request: ConversionRequest,
    progress: ProgressCallback | None = None,
    log: LogCallback | None = None,
) -> None:
    ffmpeg_path = get_ffmpeg_executable()

    output_dir = request.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    tasks = list(request.tasks)
    if not tasks:
        raise ConverterError("未选择任何待转换任务")

    base_filter = _gif_filter(request.width, request.height, request.fps)
    palette_filter = _gif_quality_filter(base_filter, request.quality)

    signals = request.signals
    if signals:
        signals.pause_event.set()
    total_tasks = len(tasks)

    for index, task in enumerate(tasks, start=1):
        if signals and signals.cancel_event.is_set():
            raise ConversionCancelled

        gif_output = output_dir / f"{task.output_stem}.gif"
        png_output = output_dir / f"{task.output_stem}.png"

        task_emitter = TaskProgressEmitter(
            task_index=index,
            total_tasks=total_tasks,
            task_name=task.display_name,
            progress_callback=progress,
            progress_factory=ConversionProgress,
            signals=signals,
            cancel_exception=ConversionCancelled,
        )

        def emit_abs(progress_value: float, stage: str) -> None:
            task_emitter.emit(progress_value, stage)

        emit_abs(0.0, "准备")

        input_args: list[str] = []
        if task.is_sequence and task.sequence_pattern:
            input_args.extend(
                [
                    "-start_number",
                    str(task.start_number or 0),
                    "-i",
                    task.sequence_pattern,
                ]
            )
            total_frames = task.frame_count
            duration_ms = task.duration_ms
        else:
            input_args.extend(["-i", str(task.source)])
            total_frames = task.total_frames
            duration_ms = task.duration_ms

        frame_estimate: Optional[int] = None
        if total_frames and total_frames > 0:
            frame_estimate = max(1, total_frames)
        elif duration_ms and duration_ms > 0:
            frame_estimate = max(1, int(request.fps * (duration_ms / 1000)))

        gif_command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *input_args,
            "-vf",
            palette_filter,
            "-progress",
            "pipe:1",
            "-nostats",
            str(gif_output),
        ]

        if log:
            log(f"正在生成 GIF：{gif_output.name}")
        gif_code, gif_stderr = _run_ffmpeg_with_progress(
            gif_command,
            emit=emit_abs,
            stage_label="GIF 转换",
            base=0.05,
            extent=0.45,
            frame_estimate=frame_estimate,
            duration_ms=duration_ms,
            signals=signals,
        )
        if gif_code != 0:
            detail = gif_stderr or "未知错误"
            raise ConverterError(f"转换 GIF 失败（{task.display_name}）：{detail}")

        emit_abs(0.55, "GIF 完成")

        apng_command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *input_args,
            "-vf",
            base_filter,
            "-f",
            "apng",
            "-progress",
            "pipe:1",
            "-nostats",
            str(png_output),
        ]

        if log:
            log(f"正在生成 APNG：{png_output.name}")
        apng_code, apng_stderr = _run_ffmpeg_with_progress(
            apng_command,
            emit=emit_abs,
            stage_label="APNG 转换",
            base=0.60,
            extent=0.35,
            frame_estimate=frame_estimate,
            duration_ms=duration_ms,
            signals=signals,
        )
        if apng_code != 0:
            detail = apng_stderr or "未知错误"
            raise ConverterError(f"转换 APNG 失败（{task.display_name}）：{detail}")

        emit_abs(1.0, "完成")
