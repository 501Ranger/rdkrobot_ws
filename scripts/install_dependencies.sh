#!/bin/bash
# ==============================================================================
#  RDK Robot 机器人依赖一键检测与安装脚本
#  功能:
#    1. 检测并验证 ROS 2 Humble 环境。
#    2. 检查并安装缺失的系统基础依赖（如 rosdep, colcon, pip3, rsync 等）。
#    3. 自动初始化与更新 rosdep 数据库。
#    4. 自动分析 src/ 目录下所有功能包并安装缺失的 ROS 依赖。
#    5. 检测并利用 pip 安装缺失的 Python 依赖包。
# ==============================================================================

set -e

# 获取工作空间根目录
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_DIR}"

echo "=================================================="
echo "    开始 RDK Robot 机器人依赖环境一键检测与安装"
echo "=================================================="

# 1. 检测 ROS 2 环境
if ! command -v ros2 &> /dev/null; then
    echo "❌ 错误: 未能在系统中检测到 ROS 2 环境。"
    echo "💡 请确保您已安装 ROS 2 Humble，并在当前终端激活了环境 (source /opt/ros/humble/setup.bash)。"
    exit 1
else
    echo "✅ 检测到 ROS 2 环境 (版本: ${ROS_DISTRO:-humble})"
fi

# 2. 检查并安装系统核心工具包
PACKAGES_TO_INSTALL=()
for pkg in python3-rosdep python3-colcon-common-extensions python3-pip rsync curl; do
    if dpkg -s "$pkg" &>/dev/null; then
        echo "✅ 系统包 '$pkg' 已安装"
    else
        echo "⚠️  系统包 '$pkg' 未安装，加入待安装列表"
        PACKAGES_TO_INSTALL+=("$pkg")
    fi
done

if [ ${#PACKAGES_TO_INSTALL[@]} -ne 0 ]; then
    echo ">>> 正在安装缺失的系统依赖: ${PACKAGES_TO_INSTALL[*]}..."
    sudo apt-get update
    sudo apt-get install -y "${PACKAGES_TO_INSTALL[@]}"
else
    echo "✅ 所有系统打包工具均已就绪"
fi

# 3. 初始化并更新 rosdep
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
    echo ">>> 初始化 rosdep..."
    sudo rosdep init || true
fi
echo ">>> 更新 rosdep 本地数据库..."
rosdep update || true

# 4. 自动解析工作空间并使用 rosdep 安装依赖
echo ">>> 正在检查并安装工作空间的 ROS 依赖项..."
# rosdep install 本身支持幂等，已安装的包会自动跳过
rosdep install -i --from-path src --rosdistro humble -y

# 5. 检测并安装 Python Web 依赖
PYTHON_REQ_FILE="src/rdk_robot_api/requirements.txt"
echo ">>> 正在检测 Python 依赖库..."
if [ -f "$PYTHON_REQ_FILE" ]; then
    # 通过 Python 执行快速 import 检测，无报错则代表全量依赖已安装
    if python3 -c "import fastapi, uvicorn, cv2, yaml, pydantic" &>/dev/null; then
        echo "✅ Python 依赖库已完整，跳过 pip 安装步骤"
    else
        echo "⚠️  检测到有缺失的 Python 依赖库，正在运行 pip 安装..."
        pip3 install -r "$PYTHON_REQ_FILE"
    fi
else
    echo "⚠️  未能在 '${PYTHON_REQ_FILE}' 找到 Python 依赖描述文件"
fi

echo "=================================================="
echo "🎉 所有的环境依赖检查与安装完成！"
echo "=================================================="
