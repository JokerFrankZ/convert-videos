#!/bin/bash

# 视频转换脚本 - 将MP4转换为GIF和APNG格式
# 作者: Claude
# 日期: $(date '+%Y-%m-%d')

# 默认参数
DEFAULT_WIDTH=259
DEFAULT_HEIGHT=194
DEFAULT_OUTPUT_DIR="./output"
DEFAULT_FPS=10
DEFAULT_QUALITY="high"

# 使用说明函数
show_usage() {
    echo "使用方法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -w, --width WIDTH      设置输出宽度 (默认: $DEFAULT_WIDTH)"
    echo "  -h, --height HEIGHT    设置输出高度 (默认: $DEFAULT_HEIGHT)"
    echo "  -o, --output DIR       设置输出目录 (默认: $DEFAULT_OUTPUT_DIR)"
    echo "  -f, --fps FPS          设置帧率 (默认: $DEFAULT_FPS)"
    echo "  -q, --quality QUALITY  设置GIF质量 [low|medium|high|ultra] (默认: $DEFAULT_QUALITY)"
    echo "  --help                 显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                     # 使用默认参数 259x194"
    echo "  $0 -w 320 -h 240      # 转换为320x240尺寸"
    echo "  $0 --width 480 --height 360 --output ./my_output"
    echo "  $0 -q ultra           # 使用超高质量GIF"
    echo ""
    echo "说明:"
    echo "  - 脚本会自动在当前目录查找所有.mp4文件"
    echo "  - 输出GIF和PNG(APNG)两种格式"
    echo "  - 文件名保持不变，只改变扩展名"
    echo "  - GIF质量级别说明:"
    echo "    * low:    快速转换，较小文件，基础质量"
    echo "    * medium: 平衡质量和大小"
    echo "    * high:   高质量，使用优化调色板 (推荐)"
    echo "    * ultra:  最高质量，最大文件"
}

# 初始化参数
width=$DEFAULT_WIDTH
height=$DEFAULT_HEIGHT
output_dir=$DEFAULT_OUTPUT_DIR
fps=$DEFAULT_FPS
quality=$DEFAULT_QUALITY

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -w|--width)
            width="$2"
            shift 2
            ;;
        -h|--height)
            height="$2"
            shift 2
            ;;
        -o|--output)
            output_dir="$2"
            shift 2
            ;;
        -f|--fps)
            fps="$2"
            shift 2
            ;;
        -q|--quality)
            quality="$2"
            shift 2
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            show_usage
            exit 1
            ;;
    esac
done

# 验证参数
if ! [[ "$width" =~ ^[0-9]+$ ]] || [ "$width" -le 0 ]; then
    echo "错误: 宽度必须是正整数"
    exit 1
fi

if ! [[ "$height" =~ ^[0-9]+$ ]] || [ "$height" -le 0 ]; then
    echo "错误: 高度必须是正整数"
    exit 1
fi

if ! [[ "$fps" =~ ^[0-9]+$ ]] || [ "$fps" -le 0 ]; then
    echo "错误: 帧率必须是正整数"
    exit 1
fi

# 验证质量参数
if [[ ! "$quality" =~ ^(low|medium|high|ultra)$ ]]; then
    echo "错误: 质量参数必须是 low, medium, high 或 ultra"
    exit 1
fi

# 检查ffmpeg是否安装
if ! command -v ffmpeg &> /dev/null; then
    echo "错误: 未找到ffmpeg，请先安装ffmpeg"
    echo "macOS: brew install ffmpeg"
    echo "Ubuntu: sudo apt install ffmpeg"
    exit 1
fi

# 检查是否有MP4文件
mp4_files=(*.mp4)
if [ ! -e "${mp4_files[0]}" ]; then
    echo "错误: 当前目录下没有找到MP4文件"
    exit 1
fi

# 显示转换信息
echo "========================================="
echo "视频转换脚本"
echo "========================================="
echo "输出尺寸: ${width}x${height}"
echo "输出目录: $output_dir"
echo "帧率: ${fps}fps"
echo "GIF质量: $quality"
echo "找到 ${#mp4_files[@]} 个MP4文件"
echo "========================================="

# 创建输出目录
mkdir -p "$output_dir"

# 根据质量级别生成GIF转换函数
get_gif_command() {
    local input_file="$1"
    local output_file="$2"
    local base_filter="scale=${width}:${height}:force_original_aspect_ratio=increase,crop=${width}:${height},fps=${fps}"

    case $quality in
        "low")
            # 基础质量，快速转换
            echo "ffmpeg -i \"$input_file\" -vf \"$base_filter\" -y \"$output_file\" -v quiet -stats"
            ;;
        "medium")
            # 中等质量，256色调色板
            echo "ffmpeg -i \"$input_file\" -vf \"$base_filter,split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse\" -y \"$output_file\" -v quiet -stats"
            ;;
        "high")
            # 高质量，优化调色板，抖动
            echo "ffmpeg -i \"$input_file\" -vf \"$base_filter,split[s0][s1];[s0]palettegen=max_colors=256:stats_mode=single[p];[s1][p]paletteuse=dither=bayer:bayer_scale=2\" -y \"$output_file\" -v quiet -stats"
            ;;
        "ultra")
            # 超高质量，最大颜色，Sierra抖动
            echo "ffmpeg -i \"$input_file\" -vf \"$base_filter,split[s0][s1];[s0]palettegen=max_colors=256:stats_mode=full:reserve_transparent=0[p];[s1][p]paletteuse=dither=sierra2_4a\" -y \"$output_file\" -v quiet -stats"
            ;;
    esac
}

# 转换为GIF格式
echo ""
echo "开始转换为GIF格式..."
for file in *.mp4; do
    if [ -f "$file" ]; then
        filename="${file%.*}"
        echo "转换 $file -> ${filename}.gif"

        # 获取并执行对应质量的转换命令
        gif_cmd=$(get_gif_command "$file" "${output_dir}/${filename}.gif")
        eval "$gif_cmd"

        if [ $? -eq 0 ]; then
            echo "✓ ${filename}.gif 转换完成"
        else
            echo "✗ ${filename}.gif 转换失败"
        fi
    fi
done

# 转换为APNG格式
echo ""
echo "开始转换为PNG(APNG)格式..."
for file in *.mp4; do
    if [ -f "$file" ]; then
        filename="${file%.*}"
        echo "转换 $file -> ${filename}.png"
        ffmpeg -i "$file" \
               -vf "scale=${width}:${height}:force_original_aspect_ratio=increase,crop=${width}:${height},fps=${fps}" \
               -f apng \
               -y "${output_dir}/${filename}.png" \
               -v quiet -stats

        if [ $? -eq 0 ]; then
            echo "✓ ${filename}.png 转换完成"
        else
            echo "✗ ${filename}.png 转换失败"
        fi
    fi
done

# 显示结果
echo ""
echo "========================================="
echo "转换完成！"
echo "========================================="
echo "输出目录: $output_dir"
echo "生成文件:"
ls -la "$output_dir" | grep -E '\.(gif|png)$' | awk '{printf "  %s (%s)\n", $9, $5}'

# 计算总文件大小
total_size=$(du -sh "$output_dir" | cut -f1)
echo "总大小: $total_size"
echo "========================================="