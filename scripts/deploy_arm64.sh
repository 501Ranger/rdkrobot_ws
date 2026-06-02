#!/bin/bash

# 遇到错误立即退出
set -e

# 获取工作空间根目录
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_DIR}"

LOCAL_INSTALL_DIR="install_arm64"
CONFIG_FILE="${WORKSPACE_DIR}/.deploy_config"

# 检查本地编译产物目录是否存在
if [ ! -d "${LOCAL_INSTALL_DIR}" ]; then
    echo "❌ 错误: 未找到本地编译产物目录 '${LOCAL_INSTALL_DIR}'。"
    echo "👉 请先执行以下命令在宿主机进行编译："
    echo "   ./scripts/build_arm64.sh"
    exit 1
fi

# 参数解析：清除/重置配置
if [ "$1" == "--reset" ] || [ "$1" == "-r" ]; then
    if [ -f "${CONFIG_FILE}" ]; then
        rm -f "${CONFIG_FILE}"
        echo "🧹 已清除保存的默认部署配置。"
    else
        echo "💡 未检测到已保存的默认配置，无需清除。"
    fi
    exit 0
fi

# 1. 尝试从本地配置文件中加载配置
RDK_IP=""
RDK_USER="sunrise"
RDK_DIR="~/rdkrobot_ws/install"

if [ -f "${CONFIG_FILE}" ]; then
    # 读取配置
    source "${CONFIG_FILE}"
    echo "=================================================="
    echo "💾 加载已保存的默认部署配置："
    echo "   板卡 IP:    ${RDK_IP}"
    echo "   SSH 用户:   ${RDK_USER}"
    echo "   目标路径:   ${RDK_DIR}"
    echo "   (若需重置，请运行: ./scripts/deploy_arm64.sh --reset)"
    echo "=================================================="
fi

# 2. 如果配置中没有 RDK_IP，则进入交互式引导输入
if [ -z "${RDK_IP}" ]; then
    RDK_IP_DEFAULT="172.20.10.4"
    echo "=================================================="
    echo "            RDK X5 一键部署配置引导"
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
    
    # 交互询问是否保存为默认配置
    echo -n "是否将以上配置保存为默认设置，下次直接一键完成？[Y/n]: "
    read save_choice
    if [ "${save_choice}" != "n" ] && [ "${save_choice}" != "N" ]; then
        cat << EOF > "${CONFIG_FILE}"
RDK_IP="${RDK_IP}"
RDK_USER="${RDK_USER}"
RDK_DIR="${RDK_DIR}"
EOF
        echo "💾 配置已成功保存至 .deploy_config，并已加入 .gitignore 中进行保护。"
    fi
fi

# 3. 自适应免密 SSH 连接检测与自动公钥配置
echo "🔍 正在检测与小车的免密 SSH 连接状态..."
# PasswordAuthentication=no 确保如果没配免密直接返回失败，不进入密码挂起输入
if ssh -o PasswordAuthentication=no -o ConnectTimeout=3 "${RDK_USER}@${RDK_IP}" "true" &>/dev/null; then
    echo "🔓 免密状态: 已就绪，将全自动免密部署！"
else
    echo "🔒 免密状态: 未配置，当前连接板卡需要手动输入密码。"
    echo -n "是否现在一键配置 SSH 免密公钥登录，避免以后输入密码？[Y/n]: "
    read setup_key
    if [ "${setup_key}" != "n" ] && [ "${setup_key}" != "N" ]; then
        # 宿主机如未生成密钥对，则自动生成
        if [ ! -f ~/.ssh/id_rsa.pub ]; then
            echo "🔑 未检测到本地 SSH 密钥，正在生成 RSA 密钥对..."
            # -N "" 为空密码，-f 指定路径
            ssh-keygen -t rsa -N "" -f ~/.ssh/id_rsa
        fi
        
        echo "🚀 正在安装公钥到 RDK X5 板卡..."
        echo "👉 请在下方输入一次板卡 SSH 登录密码以完成配对："
        if command -v ssh-copy-id &> /dev/null; then
            ssh-copy-id -i ~/.ssh/id_rsa.pub "${RDK_USER}@${RDK_IP}"
        else
            # 兼容无 ssh-copy-id 命令的宿主机系统
            cat ~/.ssh/id_rsa.pub | ssh "${RDK_USER}@${RDK_IP}" "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
        fi
        
        # 验证是否配置成功
        if ssh -o PasswordAuthentication=no -o ConnectTimeout=3 "${RDK_USER}@${RDK_IP}" "true" &>/dev/null; then
            echo "✨ 恭喜！SSH 免密登录配置成功！"
        else
            echo "⚠️  配对验证失败，本次部署仍需输入密码。建议检查板卡 SSH 权限。"
        fi
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
