# 视频转换桌面应用

该项目提供一个使用 PySide6 构建的桌面应用，将 MP4 文件批量转换为 GIF 与 APNG。应用内置 ffmpeg，可打包为 Windows 与 macOS 的可执行程序，用户开箱即用。

## 功能概览
- 支持多文件选择与批量转换
- 输出尺寸、帧率、质量可自定义
- 转换日志实时输出
- GIF 与 APNG 双格式输出

## 获取 ffmpeg

请将对应平台的 ffmpeg/ffprobe 可执行文件放入以下目录：

- Windows: `resources/ffmpeg/windows/ffmpeg.exe`、`ffprobe.exe`、`ffplay.exe`
- macOS: `resources/ffmpeg/macos/ffmpeg`、`ffprobe`

## 安装与运行

```bash
make install
make run
```

## 打包

### Windows 可执行文件

```bash
make build-win
```

### macOS 可执行文件

```bash
make build-mac
```

打包产物位于 `dist/` 目录。若在 macOS 上使用，请执行一次 `chmod +x` 以确保 ffmpeg 可执行。

## 清理

```bash
make clean
```

