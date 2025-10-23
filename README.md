# 视频转换桌面应用

一个基于 PySide6 构建的跨平台桌面应用，专为批量视频转换而设计。支持将 MP4 视频文件和图片序列转换为 GIF、APNG 和 PNG 序列格式，内置 ffmpeg 引擎，提供直观的图形界面和强大的转换功能。

## 🚀 项目概述

本项目是一个功能完整的视频转换工具，具有以下技术特点：

- **现代化 GUI**：基于 PySide6 构建，提供直观易用的用户界面
- **高性能转换**：集成 ffmpeg 引擎，确保高质量的转换效果
- **跨平台支持**：原生支持 Windows 和 macOS 系统
- **开箱即用**：内置 ffmpeg 二进制文件，无需额外安装依赖
- **批量处理**：支持多文件同时转换，提高工作效率
- **实时反馈**：提供详细的转换进度和日志信息

## ✨ 功能特性

### 核心转换功能
- **视频转换**：支持 MP4 格式视频文件批量转换
- **图片序列转换**：支持连续编号的图片序列转换为动画格式
- **多格式输出**：
  - GIF：支持多种质量级别的 GIF 动画
  - APNG：高质量的 PNG 动画格式
  - PNG 序列：导出为独立的 PNG 图片序列

### 转换参数定制
- **尺寸控制**：自定义输出宽度和高度
- **帧率调节**：灵活设置动画播放帧率
- **质量等级**：提供多种 GIF 质量选项
  - 快速：基础质量，快速转换
  - 平衡：质量与文件大小的最佳平衡
  - 高质量：优化调色板，推荐设置
  - 超高质量：最高质量输出

### 用户体验
- **拖拽支持**：直接拖拽文件到应用窗口
- **批量选择**：支持多文件同时选择和处理
- **实时进度**：显示详细的转换进度和状态
- **日志输出**：提供完整的转换日志信息
- **暂停/取消**：支持转换过程的暂停和取消操作

### 智能文件处理
- **序列检测**：自动识别连续编号的图片序列
- **格式验证**：智能验证输入文件格式
- **输出管理**：自动创建分类输出目录

## 🛠 技术架构

### 核心技术栈
- **GUI 框架**：PySide6 (Qt6 Python 绑定)
- **转换引擎**：FFmpeg
- **图像处理**：Pillow (PIL)
- **打包工具**：PyInstaller
- **构建系统**：Make + GitHub Actions

### 项目结构
```
convert-video/
├── src/                    # 源代码目录
│   ├── main.py            # 主程序入口和 GUI 界面
│   └── converter.py       # 转换引擎和核心逻辑
├── resources/             # 资源文件目录
│   └── ffmpeg/           # FFmpeg 二进制文件
│       ├── windows/      # Windows 平台二进制
│       └── macos/        # macOS 平台二进制
├── .github/              # GitHub Actions 配置
│   └── workflows/
│       └── build.yml     # 自动构建流程
├── requirements.txt      # Python 依赖列表
├── Makefile             # 构建和管理脚本
├── convert_videos.sh    # 命令行转换脚本
└── README.md           # 项目文档
```

### 核心组件说明
- **MainWindow**：主界面类，处理用户交互和界面逻辑
- **ConversionWorker**：转换工作线程，执行后台转换任务
- **ConversionRequest**：转换请求数据结构
- **ControlSignals**：转换过程控制信号（暂停/取消）
- **ProgressCallback**：进度回调机制

## 📦 安装和使用

### 环境要求
- Python 3.11+
- 支持的操作系统：Windows 10+、macOS 10.15+

### 开发环境安装
```bash
# 克隆项目
git clone <repository-url>
cd convert-video

# 安装依赖并运行
make install
make run
```

### 获取 FFmpeg 二进制文件
在运行或打包前，需要将对应平台的 ffmpeg 可执行文件放入指定目录：

**Windows 平台：**
```
resources/ffmpeg/windows/
├── ffmpeg.exe
├── ffprobe.exe
└── ffplay.exe
```

**macOS 平台：**
```
resources/ffmpeg/macos/
├── ffmpeg
└── ffprobe
```

### 应用打包

#### Windows 可执行文件
```bash
make build-win
```

#### macOS 应用包
```bash
make build-mac
```

打包完成后，可执行文件位于 `dist/` 目录中。

**注意**：在 macOS 上首次使用时，请执行以下命令确保 ffmpeg 具有执行权限：
```bash
chmod +x dist/video-converter.app/Contents/MacOS/resources/ffmpeg/macos/*
```

### 使用方法

1. **启动应用**：运行可执行文件或使用 `make run`
2. **添加文件**：
   - 点击"选择文件"按钮选择视频文件
   - 或直接拖拽文件到应用窗口
3. **设置参数**：
   - 输出目录：指定转换结果保存位置
   - 尺寸设置：设置输出宽度和高度
   - 帧率：设置动画播放帧率
   - 质量：选择 GIF 质量等级
4. **选择格式**：勾选需要的输出格式（GIF/APNG/PNG序列）
5. **开始转换**：点击"开始转换"按钮
6. **监控进度**：查看实时进度条和转换日志

## 🔧 开发指南

### 开发环境设置
```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate     # Windows

# 安装开发依赖
pip install -r requirements.txt
```

### 代码结构说明

#### 主要模块
- **main.py**：GUI 界面实现，包含主窗口类和用户交互逻辑
- **converter.py**：转换引擎，包含文件处理、ffmpeg 调用和进度跟踪

#### 关键类和函数
- `MainWindow`：主界面类
- `ConversionWorker`：转换工作线程
- `convert_files()`：核心转换函数
- `probe_video_metadata()`：视频信息探测
- `probe_image_metadata()`：图片信息探测

### 构建和测试
```bash
# 运行应用
make run

# 清理构建文件
make clean

# 本地测试打包（macOS）
make build-mac
```

### 贡献指南
1. Fork 项目仓库
2. 创建功能分支：`git checkout -b feature/new-feature`
3. 提交更改：`git commit -am 'Add new feature'`
4. 推送分支：`git push origin feature/new-feature`
5. 创建 Pull Request

## 🚀 自动化构建

项目使用 GitHub Actions 实现自动化构建和发布：

- **持续集成**：每次推送代码时自动运行构建测试
- **多平台构建**：同时构建 Windows 和 macOS 版本
- **自动发布**：标签推送时自动创建 GitHub Release

### 发布流程
1. 创建版本标签：`git tag v1.0.0`
2. 推送标签：`git push origin v1.0.0`
3. GitHub Actions 自动构建并发布

## 📝 更新日志

### 当前版本特性
- ✅ 支持 MP4 视频转换
- ✅ 支持图片序列转换
- ✅ 多格式输出（GIF/APNG/PNG序列）
- ✅ 可自定义转换参数
- ✅ 实时进度显示
- ✅ 暂停/取消功能
- ✅ 跨平台支持
- ✅ 自动化构建和发布

## 🤝 支持和反馈

如果您在使用过程中遇到问题或有改进建议，请：

1. 查看现有的 Issues
2. 创建新的 Issue 描述问题
3. 提供详细的错误信息和复现步骤

## 📄 许可证

本项目采用开源许可证，具体信息请查看 LICENSE 文件。

---

**注意**：首次运行前请确保已正确放置 ffmpeg 二进制文件到对应的平台目录中。


