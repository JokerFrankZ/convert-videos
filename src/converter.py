from __future__ import annotations

import json
import os
import shutil
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


DEFAULT_EXPORT_FORMATS: tuple[str, ...] = ("gif", "apng")
VALID_EXPORT_FORMATS = {"gif", "apng", "png_sequence"}

VALID_SCALE_MODES = {"center_crop", "stretch", "force_aspect"}
DEFAULT_SCALE_MODE = "center_crop"


class InvalidExportFormat(ConverterError):
    """Raised when an unknown export format is requested."""


class InvalidScaleMode(ConverterError):
    """Raised when an unknown scale mode is requested."""


FORMAT_EXTENSIONS = {
    "gif": ".gif",
    "apng": ".png",
}

FORMAT_SUBDIRS = {
    "gif": "gif",
    "apng": "apng",
    "png_sequence": "png_sequence",
}

FORMAT_STAGE_LABELS = {
    "gif": "GIF 转换",
    "apng": "APNG 转换",
    "png_sequence": "PNG 序列导出",
}

FORMAT_LOG_PREFIX = {
    "gif": "正在生成 GIF",
    "apng": "正在生成 APNG",
    "png_sequence": "正在导出 PNG 序列",
}


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
    source_format: Optional[str] = None  # 源文件格式: "video", "gif", "apng", "image_sequence"
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
    width: int = 320
    height: int = 180
    fps: float = 12.0
    quality: str = "balanced"
    scale_mode: str = DEFAULT_SCALE_MODE
    signals: ControlSignals | None = None
    export_formats: tuple[str, ...] = DEFAULT_EXPORT_FORMATS


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


def probe_animated_image_metadata(
    image_path: Path,
) -> Tuple[int, int, float, Optional[int], Optional[int]]:
    """Probe GIF/APNG metadata using ffprobe. Returns width, height, fps, total frames, duration ms."""

    ffprobe_path = get_ffprobe_executable()

    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,nb_frames,duration",
        "-of",
        "json",
        str(image_path),
    ]

    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if process.returncode != 0:
        message = process.stderr.strip() or f"无法读取 {image_path.suffix} 信息"
        raise ConverterError(message)

    try:
        data = json.loads(process.stdout)
        stream = data["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])

        rate = stream.get("r_frame_rate", "10/1")
        fraction = Fraction(rate)
        if fraction.denominator == 0:
            raise ZeroDivisionError
        fps = float(fraction)

        nb_frames = stream.get("nb_frames")
        if nb_frames and str(nb_frames).replace(".", "").isdigit():
            total_frames = int(float(nb_frames))
        else:
            total_frames = None

        duration = stream.get("duration")
        duration_ms = None
        if duration:
            try:
                duration_ms = int(float(duration) * 1000)
            except (ValueError, TypeError):
                pass

    except (
        KeyError,
        IndexError,
        ValueError,
        ZeroDivisionError,
        json.JSONDecodeError,
    ) as exc:
        raise ConverterError(f"解析 {image_path.suffix} 信息失败") from exc

    if total_frames is None and duration_ms is not None:
        total_frames = max(1, int(fps * duration_ms / 1000))

    if width <= 0 or height <= 0 or fps <= 0:
        raise ConverterError("获取到的图片参数无效")

    return width, height, fps, total_frames, duration_ms


def _gif_filter(width: int, height: int, fps: float, scale_mode: str = "center_crop") -> str:
    """Generate FFmpeg filter based on scale mode.

    scale_mode options:
    - center_crop: 居中裁切适配 (Center and crop to fit)
    - stretch: 拉伸适配 (Stretch to fit)
    - force_aspect: 强制保持原始宽高比 (Force original aspect ratio)
    """
    if scale_mode == "center_crop":
        # 放大到至少一边填满目标尺寸，然后居中裁切
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps}"
        )
    elif scale_mode == "stretch":
        # 拉伸到目标尺寸，不保持宽高比
        return f"scale={width}:{height},fps={fps}"
    elif scale_mode == "force_aspect":
        # 保持宽高比，缩放到目标尺寸内，可能产生黑边
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}"
        )
    else:
        raise InvalidScaleMode(f"不支持的裁切模式：{scale_mode}")


def _calculate_apng_params(
    width: int, height: int, fps: float, frame_estimate: Optional[int], target_size_mb: float = 2.0
) -> tuple[float, Optional[int]]:
    """根据目标大小计算最佳的 APNG 参数（不改变尺寸）

    返回: (调整后的帧率, 限制的最大帧数)
    """
    if not frame_estimate or frame_estimate <= 0:
        return fps, None

    # 粗略估算: 每帧 PNG 大小约为 宽*高*压缩率 bytes
    # APNG 的压缩率通常在 0.3-0.8 之间,这里用 0.5 作为估算
    compression_ratio = 0.5
    bytes_per_pixel = compression_ratio
    target_size_bytes = target_size_mb * 1024 * 1024

    # 当前配置下的预估大小
    estimated_size = width * height * bytes_per_pixel * frame_estimate

    if estimated_size <= target_size_bytes:
        return fps, None

    # 策略 1: 降低帧率 (最多降低到 6 fps,保证基本流畅度)
    min_fps = 6.0
    adjusted_fps = fps
    adjusted_frames = frame_estimate

    while adjusted_fps > min_fps and estimated_size > target_size_bytes:
        adjusted_fps = max(min_fps, adjusted_fps * 0.8)
        adjusted_frames = int(frame_estimate * (adjusted_fps / fps))
        estimated_size = width * height * bytes_per_pixel * adjusted_frames

    if estimated_size <= target_size_bytes:
        return adjusted_fps, None

    # 策略 2: 限制最大帧数
    max_frames = int(target_size_bytes / (width * height * bytes_per_pixel))
    if max_frames < adjusted_frames:
        adjusted_frames = max(30, max_frames)  # 至少保留 30 帧

    return adjusted_fps, adjusted_frames


def _gif_quality_filter(base_filter: str, quality: str) -> str:
    presets = {
        "low": base_filter,
        "medium": (
            f"{base_filter},split[s0][s1];[s0]palettegen=max_colors=256[p];"
            "[s1][p]paletteuse"
        ),
        "balanced": (
            f"{base_filter},split[s0][s1];[s0]palettegen="
            "max_colors=192:stats_mode=single[p];[s1][p]paletteuse="
            "dither=bayer:bayer_scale=3"
        ),
        "high": (
            f"{base_filter},split[s0][s1];[s0]palettegen="
            "max_colors=256:stats_mode=single:reserve_transparent=0[p];"
            "[s1][p]paletteuse=dither=bayer:bayer_scale=2"
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

    if output_dir.name.lower() == "output":
        target_output_dir = output_dir
    else:
        target_output_dir = output_dir / "output"
        target_output_dir.mkdir(parents=True, exist_ok=True)

    tasks = list(request.tasks)
    if not tasks:
        raise ConverterError("未选择任何待转换任务")

    raw_formats = request.export_formats or DEFAULT_EXPORT_FORMATS
    export_formats = list(dict.fromkeys(raw_formats))
    if not export_formats:
        export_formats = list(DEFAULT_EXPORT_FORMATS)

    invalid_formats = [fmt for fmt in export_formats if fmt not in VALID_EXPORT_FORMATS]
    if invalid_formats:
        raise InvalidExportFormat(
            "不支持的导出格式：" + ", ".join(sorted(set(invalid_formats)))
        )

    format_dirs: dict[str, Path] = {}
    for fmt in export_formats:
        subdir = FORMAT_SUBDIRS.get(fmt, fmt)
        fmt_dir = target_output_dir / subdir
        fmt_dir.mkdir(parents=True, exist_ok=True)
        format_dirs[fmt] = fmt_dir

    def display_path(path: Path) -> str:
        try:
            return str(path.relative_to(target_output_dir))
        except ValueError:
            return str(path)

    scale_mode = request.scale_mode
    if scale_mode not in VALID_SCALE_MODES:
        raise InvalidScaleMode(
            f"不支持的裁切模式：{scale_mode}，有效选项为：{', '.join(sorted(VALID_SCALE_MODES))}"
        )

    base_filter = _gif_filter(request.width, request.height, request.fps, scale_mode)
    palette_filter = _gif_quality_filter(base_filter, request.quality)

    signals = request.signals
    if signals:
        signals.pause_event.set()
    total_tasks = len(tasks)

    prep_base = 0.05
    formats_extent = 0.90
    format_count = len(export_formats)
    format_extent = formats_extent / format_count if format_count else 0.0

    for index, task in enumerate(tasks, start=1):
        if signals and signals.cancel_event.is_set():
            raise ConversionCancelled

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

        if format_count == 0:
            emit_abs(1.0, "完成")
            continue

        for fmt_index, fmt in enumerate(export_formats):
            stage_base = prep_base + format_extent * fmt_index
            stage_label = FORMAT_STAGE_LABELS[fmt]
            log_prefix = FORMAT_LOG_PREFIX[fmt]
            fmt_dir = format_dirs[fmt]

            if fmt in {"gif", "apng"}:
                suffix = FORMAT_EXTENSIONS[fmt]
                output_path = fmt_dir / f"{task.output_stem}{suffix}"

                # 为 APNG 计算优化后的参数
                if fmt == "apng":
                    apng_fps, max_frames = _calculate_apng_params(
                        request.width, request.height, request.fps, frame_estimate
                    )
                    apng_filter = _gif_filter(request.width, request.height, apng_fps)

                    command: list[str] = [
                        str(ffmpeg_path),
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        *input_args,
                    ]

                    # 如果需要限制帧数,添加帧数限制
                    if max_frames:
                        command.extend(["-frames:v", str(max_frames)])

                    command.extend([
                        "-vf",
                        apng_filter,
                        "-f", "apng",
                        "-plays", "0",  # 无限循环
                        "-compression_level", "9",  # 最高压缩级别
                        "-pred", "mixed",  # PNG 预测模式,有助于压缩
                        "-progress",
                        "pipe:1",
                        "-nostats",
                        str(output_path),
                    ])

                    # 如果参数被调整,在日志中提示
                    if apng_fps != request.fps or max_frames:
                        adjustments = []
                        if apng_fps != request.fps:
                            adjustments.append(f"帧率: {apng_fps:.1f}")
                        if max_frames:
                            adjustments.append(f"最大帧数: {max_frames}")
                        if log:
                            log(f"⚠️ 为控制文件大小在 2MB 以内,已自动调整 APNG 参数: {', '.join(adjustments)}")
                else:
                    # GIF 导出保持原样
                    command: list[str] = [
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
                        str(output_path),
                    ]

                log_target = output_path
            elif fmt == "png_sequence":
                sequence_root = fmt_dir / task.output_stem
                if sequence_root.exists():
                    shutil.rmtree(sequence_root)
                sequence_root.mkdir(parents=True, exist_ok=True)
                pattern_path = sequence_root / f"{task.output_stem}_%04d.png"

                command = [
                    str(ffmpeg_path),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    *input_args,
                    "-vf",
                    base_filter,
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    str(pattern_path),
                ]

                log_target = sequence_root
            else:  # pragma: no cover - guarded by validation
                raise InvalidExportFormat(f"不支持的导出格式：{fmt}")

            if log:
                log(f"{log_prefix}：{display_path(log_target)}")

            return_code, stderr_output = _run_ffmpeg_with_progress(
                command,
                emit=emit_abs,
                stage_label=stage_label,
                base=stage_base,
                extent=format_extent,
                frame_estimate=frame_estimate,
                duration_ms=duration_ms,
                signals=signals,
            )

            if return_code != 0:
                detail = stderr_output or "未知错误"
                if fmt == "gif":
                    message = f"转换 GIF 失败（{task.display_name}）：{detail}"
                elif fmt == "apng":
                    message = f"转换 APNG 失败（{task.display_name}）：{detail}"
                else:
                    message = f"导出 PNG 序列失败（{task.display_name}）：{detail}"
                raise ConverterError(message)

        emit_abs(1.0, "完成")
