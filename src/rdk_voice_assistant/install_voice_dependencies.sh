#!/bin/bash
# ==============================================================================
#  RDK Robot 语音模块依赖一键检测与安装脚本
#  功能:
#    1. 检测并验证 ROS 2 Humble 环境。
#    2. 检查并安装语音模块特有的系统库依赖（libportaudio2, alsa-utils, espeak 等）。
#    3. 自动使用 rosdep 分析并安装 rdk_voice_assistant 的 ROS 2 依赖。
#    4. 检测并安装 python 语音依赖包 (vosk, sounddevice, sherpa-onnx 等)。
# ==============================================================================

set -e

# 获取工作空间根目录
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${WORKSPACE_DIR}"

echo "=================================================="
echo "    开始 RDK Robot 语音助手依赖一键检测与安装"
echo "=================================================="

# 1. 检测 ROS 2 环境
if ! command -v ros2 &> /dev/null; then
    echo "❌ 错误: 未能在系统中检测到 ROS 2 环境。"
    echo "💡 请确保您已安装 ROS 2 Humble，并在当前终端激活了环境 (source /opt/ros/humble/setup.bash)。"
    exit 1
else
    echo "✅ 检测到 ROS 2 环境 (版本: ${ROS_DISTRO:-humble})"
fi

# 2. 检查并安装语音模块底层系统库依赖
# libportaudio2: sounddevice 底层音频 I/O
# alsa-utils: ALSA 播放录音工具
# libasound2-dev: ALSA 开发库
# espeak: pyttsx3 离线 TTS 引擎底层依赖
SYSTEM_PACKAGES=(
    python3-pip
    libportaudio2
    alsa-utils
    libasound2-dev
    espeak
)

PACKAGES_TO_INSTALL=()
for pkg in "${SYSTEM_PACKAGES[@]}"; do
    if dpkg -s "$pkg" &>/dev/null; then
        echo "✅ 系统包 '$pkg' 已安装"
    else
        echo "⚠️  系统包 '$pkg' 未安装，加入待安装列表"
        PACKAGES_TO_INSTALL+=("$pkg")
    fi
done

if [ ${#PACKAGES_TO_INSTALL[@]} -ne 0 ]; then
    echo ">>> 正在安装缺失的系统音频库依赖: ${PACKAGES_TO_INSTALL[*]}..."
    sudo apt-get update
    sudo apt-get install -y "${PACKAGES_TO_INSTALL[@]}"
else
    echo "✅ 所有系统音频和工具依赖包均已就绪"
fi

# 3. 初始化并更新 rosdep
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
    echo ">>> 初始化 rosdep..."
    sudo rosdep init || true
fi
echo ">>> 更新 rosdep 本地数据库..."
rosdep update || true

# 4. 自动解析语音助手包并安装 ROS 依赖
echo ">>> 正在通过 rosdep 检查并安装语音包的 ROS 依赖项..."
# 使用当前脚本目录作为查找起点
rosdep install -i --from-path . --rosdistro humble -y

# 5. 检测并安装 Python 语音依赖
PYTHON_REQ_FILE="requirements-local-voice.txt"
echo ">>> 正在检测 Python 语音依赖库..."
if [ -f "$PYTHON_REQ_FILE" ]; then
    # 通过 Python 执行快速 import 检测，无报错则代表全量依赖已安装
    if python3 -c "import vosk, sounddevice, pyttsx3, numpy, sherpa_onnx, edge_tts, aiohttp" &>/dev/null; then
        echo "✅ Python 语音依赖库已完整，跳过 pip 安装步骤"
    else
        echo "⚠️  检测到有缺失的 Python 语音依赖库，正在运行 pip 安装..."
        pip3 install -r "$PYTHON_REQ_FILE"
    fi
else
    echo "⚠️  未能在当前目录下找到 '${PYTHON_REQ_FILE}'"
fi

echo "=================================================="
echo "🎉 语音助手模块所有依赖检测与安装完成！"
echo "=================================================="
