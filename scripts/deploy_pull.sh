#!/bin/bash

# 遇到错误立即停止
set -e

# 确保在工作空间根目录下执行
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_DIR}"

echo "=================================================="
echo "    RDK X5 智能小车 一键部署更新拉取脚本"
echo "=================================================="

# 1. 自动分析并提取仓库所有者和仓库名 (支持 SSH 和 HTTPS 格式)
REPO_URL=$(git config --get remote.origin.url || true)
if [[ $REPO_URL =~ github.com[:/]([^/]+/[^.]+)(\.git)? ]]; then
    REPO_PATH="${BASH_REMATCH[1]}"
    echo "📦 识别到云端 GitHub 仓库: ${REPO_PATH}"
else
    REPO_PATH="501Ranger/rdkrobot_ws"
    echo "⚠️  未能通过 git 自动提取仓库路径，使用默认值: ${REPO_PATH}"
fi

# 2. 鉴权判断与下载
# 允许通过环境变量或脚本第一个参数传入 GITHUB_TOKEN
TOKEN=${1:-$GITHUB_TOKEN}

echo "⬇️  正在下载最新发布版本 (install_arm64.tar.gz)..."

if [ -n "$TOKEN" ]; then
    echo "🗝️ 检测到鉴权令牌，将以【私有仓库】授权模式下载..."
    # 1. 获取最新 release 信息，并找到 install_arm64.tar.gz 的 asset_id
    echo ">>> 获取最新 Release 资产 ID..."
    RELEASE_JSON=$(curl -H "Authorization: token $TOKEN" -s "https://api.github.com/repos/${REPO_PATH}/releases/latest")
    
    # 检查 API 是否报错 (例如 token 无效或网络不通)
    if echo "$RELEASE_JSON" | grep -q "message.*Bad credentials"; then
        echo "❌ 错误: 传入的 GITHUB_TOKEN 无效或过期，请检查 Token 权限。"
        exit 1
    fi
    
    ASSET_ID=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    asset = next(a for a in data.get('assets', []) if a['name'] == 'install_arm64.tar.gz')
    print(asset['id'])
except Exception as e:
    print('ERROR', file=sys.stderr)
" 2>/dev/null || echo "")

    if [ "$ASSET_ID" = "" ] || [ "$ASSET_ID" = "ERROR" ]; then
        echo "❌ 错误: 未能在最新 Release 中找到 'install_arm64.tar.gz' 资产，请确认 GitHub Action 是否编译完成并发布成功。"
        exit 1
    fi

    # 2. 调用 GitHub API 流式下载资产二进制包
    echo ">>> 开始下载资产 (ID: ${ASSET_ID})..."
    curl -L \
      -H "Authorization: token $TOKEN" \
      -H "Accept: application/octet-stream" \
      -o install_arm64.tar.gz \
      "https://api.github.com/repos/${REPO_PATH}/releases/assets/${ASSET_ID}"
else
    echo "🌍 未提供授权令牌，将以【公开仓库】匿名模式拉取..."
    # 匿名拉取 latest tag 下的发布文件
    DOWNLOAD_URL="https://github.com/${REPO_PATH}/releases/download/latest/install_arm64.tar.gz"
    
    # 尝试下载
    HTTP_CODE=$(curl -L -w "%{http_code}" -o install_arm64.tar.gz "${DOWNLOAD_URL}")
    if [ "$HTTP_CODE" -ne 200 ]; then
        echo "❌ 错误: 地产包下载失败 (HTTP 状态码: ${HTTP_CODE})。"
        echo "💡 如果该仓库是私有仓库，请在执行脚本时附带你的个人访问令牌，如: ./scripts/deploy_pull.sh <你的_GITHUB_TOKEN>"
        rm -f install_arm64.tar.gz
        exit 1
    fi
fi

echo "✅ 资产下载成功！开始部署更新..."

# 3. 备份旧的 install 部署包
BACKUP_DIR="install_backup_$(date +%Y%m%d_%H%M%S)"
if [ -d "install" ]; then
    echo "📁 正在备份原有编译环境至: ${BACKUP_DIR}..."
    mv install "${BACKUP_DIR}"
fi

# 4. 解压最新的编译产物
echo "📦 正在解压新二进制安装包..."
tar -xzf install_arm64.tar.gz

# 5. 对齐重命名
echo "⚙️  重命名 install_arm64 部署目录为运行空间 install..."
mv install_arm64 install

# 6. 清理下载包缓存
rm -f install_arm64.tar.gz

# 7. 重启 api_server 后端进程
echo "🔄 尝试重启 FastAPI 控制舱服务..."
if pkill -f api_server_node || pkill -f api_server || pkill -f "python3.*api_server"; then
    echo "⚡ 已成功终止旧的 api_server 进程，它将在后台守护进程中自动重启运行新代码。"
else
    echo "💡 提示: 未检测到正在运行的旧 api_server 进程。"
    echo "   如果您的小车上未配置守护程序，您可以通过以下命令手动拉起服务:"
    echo "   source /opt/ros/humble/setup.bash && source install/setup.bash && ros2 run rdk_robot_api api_server"
fi

echo "=================================================="
echo "        🎉 小车一键更新部署成功！"
echo "=================================================="
