from __future__ import annotations

import time
from typing import Callable, Optional, Type, TypeVar


ProgressEmitter = Callable[[float, str], None]
ProgressFactory = TypeVar("ProgressFactory")


class StageProgressTracker:
    """Handle ffmpeg 进度输出的阶段性计算与节流"""

    def __init__(
        self,
        *,
        stage_label: str,
        base: float,
        extent: float,
        emit: Optional[ProgressEmitter],
    ) -> None:
        self._emit_callback = emit
        self.stage_label = stage_label
        self.base = base
        self.extent = extent

        now = time.monotonic()
        self.stage_ratio = 0.0
        self.last_emit_ratio = -1.0
        self.last_emit_time = now
        self.last_real_ratio = 0.0
        self.last_real_time = now
        self.stage_start = now

    def emit_initial(self) -> None:
        if self._emit_callback:
            self._emit_callback(
                self.base,
                f"{self.stage_label} 0.0% (全局 {self.base * 100:.1f}%)",
            )

    def needs_synthetic_update(self, now: float, threshold: float = 0.3) -> bool:
        return now - self.last_real_time >= threshold

    def synthetic_step(
        self,
        *,
        duration_ms: Optional[int],
        frame_estimate: Optional[int],
    ) -> None:
        target = self.stage_ratio
        elapsed = time.monotonic() - self.stage_start
        if duration_ms and duration_ms > 0:
            target = max(target, min(1.0, elapsed / (duration_ms / 1000)))
        elif frame_estimate and frame_estimate > 0:
            average = max(10.0, frame_estimate)
            target = max(
                target,
                min(1.0, elapsed / max(0.5, frame_estimate / average)),
            )
        else:
            target = min(1.0, self.stage_ratio + 0.01)

        if target > self.stage_ratio:
            self.stage_ratio = target
            self._emit(
                self.stage_ratio,
                f"{self.stage_label} 估算 {self.stage_ratio * 100:.1f}%",
                force=True,
            )

    def try_update_from_ffmpeg(
        self,
        *,
        key: str,
        value_text: str,
        frame_estimate: Optional[int],
        duration_ms: Optional[int],
    ) -> bool:
        ratio_update: Optional[float] = None
        text = value_text.strip()

        if frame_estimate and frame_estimate > 0 and key == "frame":
            try:
                current = int(text)
            except ValueError:
                current = None
            if current is not None:
                ratio_update = current / frame_estimate
        elif duration_ms and duration_ms > 0 and key in {"out_time_ms", "out_time_us"}:
            try:
                scale = 1 if key == "out_time_ms" else 1000
                current_ms = int(text) / scale
            except ValueError:
                current_ms = None
            if current_ms is not None:
                ratio_update = current_ms / duration_ms
        elif duration_ms and duration_ms > 0 and key == "out_time":
            try:
                h, m, s = text.split(":")
                seconds = int(h) * 3600 + int(m) * 60 + float(s)
                ratio_update = (seconds * 1000) / duration_ms
            except ValueError:
                ratio_update = None
        elif key == "progress" and text == "end":
            ratio_update = 1.0

        if ratio_update is None:
            return False

        ratio_update = max(ratio_update, self.last_real_ratio)
        ratio_update = min(1.0, ratio_update)
        self.stage_ratio = ratio_update
        self.last_real_ratio = ratio_update
        self.last_real_time = time.monotonic()
        self._emit(
            self.stage_ratio,
            f"{self.stage_label} {self.stage_ratio * 100:.1f}% (全局 {(self.base + self.stage_ratio * self.extent) * 100:.1f}%)",
        )
        return True

    def finish(self) -> None:
        self._emit(
            1.0,
            f"{self.stage_label} 100.0% (全局 {(self.base + self.extent) * 100:.1f}%)",
            force=True,
        )

    def _emit(self, ratio: float, description: str, *, force: bool = False) -> None:
        if not self._emit_callback:
            return

        ratio = max(0.0, min(1.0, ratio))
        now = time.monotonic()
        if (
            force
            or ratio - self.last_emit_ratio >= 0.001
            or now - self.last_emit_time >= 0.2
            or ratio >= 1.0
        ):
            global_ratio = self.base + ratio * self.extent
            self._emit_callback(global_ratio, description)
            self.last_emit_ratio = ratio
            self.last_emit_time = now


class TaskProgressEmitter:
    """负责转换任务的整体进度透传"""

    def __init__(
        self,
        *,
        task_index: int,
        total_tasks: int,
        task_name: str,
        progress_callback: Optional[Callable[[ProgressFactory], None]],
        progress_factory: Callable[..., ProgressFactory],
        signals: Optional[object],
        cancel_exception: Type[BaseException],
    ) -> None:
        self._task_index = task_index
        self._total_tasks = total_tasks
        self._task_name = task_name
        self._progress_callback = progress_callback
        self._progress_factory = progress_factory
        self._signals = signals
        self._cancel_exception = cancel_exception

    def emit(self, progress_value: float, stage: str) -> None:
        clamped = max(0.0, min(1.0, progress_value))
        signals = self._signals

        if signals is not None:
            while (
                not signals.pause_event.is_set() and not signals.cancel_event.is_set()
            ):
                time.sleep(0.05)
            if signals.cancel_event.is_set():
                raise self._cancel_exception

        if not self._progress_callback:
            return

        overall = min(1.0, ((self._task_index - 1) + clamped) / self._total_tasks)
        progress = self._progress_factory(
            task_index=self._task_index,
            total_tasks=self._total_tasks,
            task_name=self._task_name,
            stage=stage,
            task_progress=clamped,
            overall_progress=overall,
        )
        self._progress_callback(progress)
