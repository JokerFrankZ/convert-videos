from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from converter import (
    ConversionRequest,
    ConverterError,
    convert_files,
    probe_video_metadata,
)


QUALITY_OPTIONS = [
    ("低", "low"),
    ("中等", "medium"),
    ("高", "high"),
    ("超高", "ultra"),
]

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mpg", ".mpeg"}


class ConversionWorker(QThread):
    progress_signal = Signal(str)
    log_signal = Signal(str)
    error_signal = Signal(str)
    finished_signal = Signal()

    def __init__(self, request: ConversionRequest):
        super().__init__()
        self._request = request

    def run(self) -> None:  # pragma: no cover - UI thread
        try:
            convert_files(
                self._request,
                progress=self.progress_signal.emit,
                log=self.log_signal.emit,
            )
        except ConverterError as exc:
            self.error_signal.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error_signal.emit(str(exc))
        finally:
            self.finished_signal.emit()


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("视频转换器")
        self.resize(800, 600)

        self._files_list = QListWidget()
        self._output_edit = QLineEdit()
        self._width_edit = QLineEdit()
        self._height_edit = QLineEdit()
        self._fps_edit = QLineEdit()
        self._quality_combo = QComboBox()
        for label, value in QUALITY_OPTIONS:
            self._quality_combo.addItem(label, userData=value)
        self._quality_combo.setCurrentIndex(1)  # 默认“中等”
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)

        self._add_files_btn = QPushButton("添加视频")
        self._add_folder_btn = QPushButton("添加文件夹")
        self._clear_files_btn = QPushButton("清空")
        self._browse_output_btn = QPushButton("选择输出目录")
        self._start_btn = QPushButton("开始转换")
        self._start_btn.setEnabled(False)

        self._worker: ConversionWorker | None = None
        self._file_set: set[Path] = set()
        self._defaults_applied = False

        self._setup_ui()
        self._bind_events()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        files_group = QGroupBox("视频文件")
        files_layout = QVBoxLayout()
        files_button_layout = QHBoxLayout()
        files_button_layout.addWidget(self._add_files_btn)
        files_button_layout.addWidget(self._add_folder_btn)
        files_button_layout.addWidget(self._clear_files_btn)

        files_layout.addLayout(files_button_layout)
        files_layout.addWidget(self._files_list)
        files_group.setLayout(files_layout)

        settings_group = QGroupBox("参数设置")
        settings_layout = QGridLayout()
        settings_layout.addWidget(QLabel("输出目录"), 0, 0)
        settings_layout.addWidget(self._output_edit, 0, 1)
        settings_layout.addWidget(self._browse_output_btn, 0, 2)
        settings_layout.addWidget(QLabel("宽度"), 1, 0)
        settings_layout.addWidget(self._width_edit, 1, 1)
        settings_layout.addWidget(QLabel("高度"), 1, 2)
        settings_layout.addWidget(self._height_edit, 1, 3)
        settings_layout.addWidget(QLabel("帧率"), 2, 0)
        settings_layout.addWidget(self._fps_edit, 2, 1)
        settings_layout.addWidget(QLabel("质量"), 2, 2)
        settings_layout.addWidget(self._quality_combo, 2, 3)
        settings_group.setLayout(settings_layout)

        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        log_layout.addWidget(self._log_view)
        log_group.setLayout(log_layout)

        main_layout.addWidget(files_group)
        main_layout.addWidget(settings_group)
        main_layout.addWidget(log_group)
        main_layout.addWidget(self._start_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _bind_events(self) -> None:
        self._add_files_btn.clicked.connect(self._on_add_files)  # type: ignore[arg-type]
        self._add_folder_btn.clicked.connect(self._on_add_folder)  # type: ignore[arg-type]
        self._clear_files_btn.clicked.connect(self._on_clear_files)  # type: ignore[arg-type]
        self._browse_output_btn.clicked.connect(self._on_browse_output)  # type: ignore[arg-type]
        self._start_btn.clicked.connect(self._on_start)  # type: ignore[arg-type]

    def _on_add_files(self) -> None:  # pragma: no cover - UI
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 MP4 文件",
            "",
            "视频文件 (*.mp4 *.mov *.m4v *.mpg *.mpeg)",
        )

        self._add_paths(Path(path) for path in paths)

    def _on_clear_files(self) -> None:
        self._files_list.clear()
        self._file_set.clear()
        self._defaults_applied = False
        self._width_edit.clear()
        self._height_edit.clear()
        self._fps_edit.clear()
        self._update_start_state()

    def _on_browse_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if directory:
            self._output_edit.setText(directory)
            self._update_start_state()

    def _on_add_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择视频所在文件夹")
        if not directory:
            return

        folder_path = Path(directory)
        paths = (path for path in folder_path.rglob("*") if path.is_file())
        video_paths = [p for p in paths if p.suffix.lower() in VIDEO_EXTENSIONS]

        if not video_paths:
            QMessageBox.information(
                self, "提示", "选定的文件夹中没有找到支持的视频文件"
            )
            return

        self._add_paths(video_paths)

    def _update_start_state(self) -> None:
        has_files = self._files_list.count() > 0
        has_output = bool(self._output_edit.text())
        self._start_btn.setEnabled(has_files and has_output and self._worker is None)

    def _append_log(self, message: str) -> None:
        self._log_view.append(message)
        self._log_view.moveCursor(QTextCursor.End)

    def _on_start(self) -> None:
        try:
            request = self._build_request()
        except ConverterError as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return

        self._log_view.clear()
        self._append_log("开始转换...")
        self._start_btn.setEnabled(False)

        self._worker = ConversionWorker(request)
        self._worker.progress_signal.connect(self._append_log)
        self._worker.log_signal.connect(self._append_log)
        self._worker.error_signal.connect(self._on_error)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    def _on_error(self, message: str) -> None:
        self._append_log(f"❌ {message}")
        QMessageBox.critical(self, "转换失败", message)

    def _on_finished(self) -> None:
        self._append_log("✅ 转换完成")
        self._worker = None
        self._update_start_state()

    def _build_request(self) -> ConversionRequest:
        files = [
            Path(self._files_list.item(index).text())
            for index in range(self._files_list.count())
        ]

        output_dir = Path(self._output_edit.text()).expanduser()
        if not output_dir:
            raise ConverterError("请指定输出目录")

        try:
            width = int(self._width_edit.text())
            height = int(self._height_edit.text())
            fps = float(self._fps_edit.text())
        except ValueError as exc:
            raise ConverterError("宽度、高度、帧率必须是数字") from exc

        if width <= 0 or height <= 0 or fps <= 0:
            raise ConverterError("宽度、高度、帧率必须大于 0")

        quality = self._quality_combo.currentData()

        return ConversionRequest(
            input_files=files,
            output_dir=output_dir,
            width=width,
            height=height,
            fps=fps,
            quality=quality,
        )

    def _add_paths(self, paths: Iterable[Path]) -> None:
        new_paths = []
        for path in paths:
            normalized = path.resolve()
            if normalized in self._file_set:
                continue
            if not normalized.exists():
                continue
            if normalized.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            self._file_set.add(normalized)
            new_paths.append(normalized)

        if not new_paths:
            self._append_log("未添加新的视频文件")
            return

        for path in sorted(new_paths):
            item = QListWidgetItem(str(path))
            item.setToolTip(str(path))
            self._files_list.addItem(item)

        self._update_start_state()
        self._apply_defaults_if_needed()
        self._append_log(f"已添加 {len(new_paths)} 个视频文件")

    def _apply_defaults_if_needed(self) -> None:
        if self._defaults_applied or self._files_list.count() == 0:
            return

        first_path = Path(self._files_list.item(0).text())
        try:
            width, height, fps = probe_video_metadata(first_path)
        except ConverterError as exc:
            self._append_log(f"⚠️ 无法读取 {first_path.name} 的参数：{exc}")
            return

        self._width_edit.setText(str(width))
        self._height_edit.setText(str(height))
        self._fps_edit.setText(f"{fps:.3f}".rstrip("0").rstrip("."))
        self._defaults_applied = True

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        if not self._output_edit.text():
            default_output = self._default_output_directory()
            self._output_edit.setText(str(default_output))
            self._update_start_state()

    def _default_output_directory(self) -> Path:
        home = Path.home()
        downloads = home / "Downloads"
        if downloads.exists():
            return downloads
        if sys.platform.startswith("win"):
            from ctypes import windll, wintypes, create_unicode_buffer

            CSIDL_PERSONAL = 0x0005
            SHGFP_TYPE_CURRENT = 0
            buf = create_unicode_buffer(wintypes.MAX_PATH)
            result = windll.shell32.SHGetFolderPathW(
                None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf
            )
            if result == 0:
                documents = Path(buf.value)
                candidate = documents.parent / "Downloads"
                if candidate.exists():
                    return candidate
        return home


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
