from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterable, Tuple


class ConverterError(Exception):
    """Raised when a conversion cannot be completed."""


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class ConversionRequest:
    input_files: Iterable[Path]
    output_dir: Path
    width: int = 259
    height: int = 194
    fps: float = 10.0
    quality: str = "high"


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


def probe_video_metadata(video_path: Path) -> Tuple[int, int, float]:
    """Return width, height and fps for a given video file."""

    ffprobe_path = get_ffprobe_executable()

    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate",
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
    except (
        KeyError,
        IndexError,
        ValueError,
        ZeroDivisionError,
        json.JSONDecodeError,
    ) as exc:
        raise ConverterError("解析视频信息失败") from exc

    if width <= 0 or height <= 0 or fps <= 0:
        raise ConverterError("获取到的视频参数无效")

    return width, height, fps


def _gif_filter(width: int, height: int, fps: int) -> str:
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


def convert_files(
    request: ConversionRequest,
    progress: ProgressCallback | None = None,
    log: LogCallback | None = None,
) -> None:
    ffmpeg_path = get_ffmpeg_executable()

    output_dir = request.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    files = list(request.input_files)
    if not files:
        raise ConverterError("未选择任何视频文件")

    base_filter = _gif_filter(request.width, request.height, request.fps)
    palette_filter = _gif_quality_filter(base_filter, request.quality)

    for index, input_path in enumerate(files, start=1):
        if progress:
            progress(f"开始处理 ({index}/{len(files)}): {input_path.name}")

        stem = input_path.stem
        gif_output = output_dir / f"{stem}.gif"
        png_output = output_dir / f"{stem}.png"

        gif_command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            palette_filter,
            str(gif_output),
        ]

        apng_command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            base_filter,
            "-f",
            "apng",
            str(png_output),
        ]

        if log:
            log(f"正在生成 GIF：{gif_output.name}")
        gif_code, gif_stderr = _run_command(gif_command)
        if gif_code != 0:
            detail = gif_stderr or "未知错误"
            raise ConverterError(f"转换 GIF 失败（{input_path.name}）：{detail}")

        if log:
            log(f"正在生成 APNG：{png_output.name}")
        apng_code, apng_stderr = _run_command(apng_command)
        if apng_code != 0:
            detail = apng_stderr or "未知错误"
            raise ConverterError(f"转换 APNG 失败（{input_path.name}）：{detail}")

        if progress:
            progress(f"完成: {input_path.name}")

    if progress:
        progress(f"全部完成，共转换 {len(files)} 个视频")
