#!/bin/bash

# 确保脚本遇到错误时立即退出
set -e

# 获取工作空间根目录
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_DIR}"

echo "=================================================="
echo "    开始 RDK X5 ROS 2 工作空间 ARM64 交叉编译"
echo "=================================================="

# 1. 注册 QEMU 仿真环境支持，用于运行 arm64v8 架构的容器
echo ">>> [1/5] 注册 QEMU 多架构运行支持..."
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes

# 2. 准备依赖安装的缓存上下文：只拷贝 package.xml 文件
echo ">>> [2/5] 提取工作空间 package.xml 依赖配置文件..."
python3 -c "
import os, shutil
src_dir = 'src'
dst_dir = 'build_arm64_temp_src/src'
if os.path.exists('build_arm64_temp_src'):
    shutil.rmtree('build_arm64_temp_src')
for root, dirs, files in os.walk(src_dir):
    if 'package.xml' in files:
        rel = os.path.relpath(root, src_dir)
        target = os.path.join(dst_dir, rel) if rel != '.' else dst_dir
        os.makedirs(target, exist_ok=True)
        shutil.copy(os.path.join(root, 'package.xml'), os.path.join(target, 'package.xml'))
"

# 3. 构建包含所有必要 arm64 依赖的编译容器
if docker image inspect rdk_robot_build:arm64 >/dev/null 2>&1; then
    echo ">>> [3/5] 检测到本地已存在 rdk_robot_build:arm64 镜像，跳过构建步骤以避免网络请求。"
    # 清理提取的临时目录（虽然没用到构建，但清理掉好一些）
    rm -rf build_arm64_temp_src
else
    echo ">>> [3/5] 构建 Docker 编译环境镜像 (rdk_robot_build:arm64)..."
    docker build --platform linux/arm64 -f Dockerfile.arm64 -t rdk_robot_build:arm64 .
    # 清理依赖提取的临时目录
    rm -rf build_arm64_temp_src
fi

# 4. 启动容器进行 ARM64 编译
echo ">>> [4/5] 启动 Docker 容器进行 ARM64 编译 (colcon build)..."
echo "⚠️  注意: 为防止 QEMU 模拟多线程编译发生段错误(Segfault)，我们将限制使用单线程顺序编译..."
docker run --rm \
  -v "${WORKSPACE_DIR}":/workspace \
  -w /workspace \
  rdk_robot_build:arm64 \
  bash -c "source /opt/ros/humble/setup.bash && export MAKEFLAGS=-j1 && colcon build --build-base build_arm64 --install-base install_arm64 --parallel-workers 1 --cmake-args -DCMAKE_BUILD_TYPE=None -DCMAKE_CXX_FLAGS='-O1' -DCMAKE_C_FLAGS='-O1' -DBUILD_TESTING=OFF"

# 5. 将编译产物的属主和属组修改回宿主机当前用户，避免权限冲突
echo ">>> [5/5] 正在修复编译产物权限为宿主机用户..."
docker run --rm \
  -v "${WORKSPACE_DIR}":/workspace \
  rdk_robot_build:arm64 \
  bash -c "[ -d /workspace/build_arm64 ] && chown -R $(id -u):$(id -g) /workspace/build_arm64; [ -d /workspace/install_arm64 ] && chown -R $(id -u):$(id -g) /workspace/install_arm64"

echo "=================================================="
echo "          ARM64 编译完成！"
echo "  编译产物已生成至: install_arm64/"
echo "=================================================="
