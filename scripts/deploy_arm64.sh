#!/bin/bash

# 遇到错误立即退出
set -e

# 获取工作空间根目录
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_DIR}"

LOCAL_INSTALL_DIR="install_arm64"

# 检查本地编译产物目录是否存在
if [ ! -d "${LOCAL_INSTALL_DIR}" ]; then
    echo "❌ 错误: 未找到本地编译产物目录 '${LOCAL_INSTALL_DIR}'。"
    echo "👉 请先执行以下命令在宿主机进行编译："
    echo "   ./scripts/build_arm64.sh"
    exit 1
fi

# 从环境变量中读取默认参数，如果不存在则使用默认值
RDK_IP="${RDK_IP:-}"
RDK_USER="${RDK_USER:-sunrise}"
RDK_DIR="${RDK_DIR:-~/rdkrobot_ws/install}"

# 如果 IP 未通过环境变量或参数传入，则进入交互式输入
if [ -z "${RDK_IP}" ]; then
    RDK_IP_DEFAULT="172.20.10.4"
    echo "=================================================="
    echo "            RDK X5 一键部署脚本"
    echo "=================================================="
    echo -n "请输入 RDK X5 板卡的 IP 地址 [默认: ${RDK_IP_DEFAULT}]: "
    read input_ip
    if [ -z "${input_ip}" ]; then
        RDK_IP="${RDK_IP_DEFAULT}"
    else
        RDK_IP="${input_ip}"
    fi
    
    echo -n "请输入板卡的 SSH 用户名 [默认: ${RDK_USER}]: "
    read input_user
    if [ -n "${input_user}" ]; then
        RDK_USER="${input_user}"
    fi
    
    echo -n "请输入板卡上的目标 install 路径 [默认: ${RDK_DIR}]: "
    read input_dir
    if [ -n "${input_dir}" ]; then
        RDK_DIR="${input_dir}"
    fi
fi

echo "=================================================="
echo "🚀 准备同步编译产物到 RDK X5 板卡..."
echo "   宿主机源目录: ${LOCAL_INSTALL_DIR}/"
echo "   目标板卡路径: ${RDK_USER}@${RDK_IP}:${RDK_DIR}"
echo "=================================================="

# 确保目标路径存在
echo ">>> 在板卡上创建目标目录..."
ssh "${RDK_USER}@${RDK_IP}" "mkdir -p \"${RDK_DIR}\""

# 检查宿主机是否安装了 rsync
if command -v rsync &> /dev/null; then
    echo ">>> 使用 rsync 增量同步（这会删除板卡上已被废弃的文件）..."
    rsync -avz --progress --delete "${LOCAL_INSTALL_DIR}/" "${RDK_USER}@${RDK_IP}:${RDK_DIR}/"
else
    echo "⚠️  未检测到 rsync，将使用 scp 进行全量复制..."
    scp -r "${LOCAL_INSTALL_DIR}/"* "${RDK_USER}@${RDK_IP}:${RDK_DIR}/"
fi

echo "=================================================="
echo "🎉 部署完成！"
echo "👉 请在 RDK X5 板卡上激活环境："
echo "   source ${RDK_DIR}/setup.bash"
echo "=================================================="
