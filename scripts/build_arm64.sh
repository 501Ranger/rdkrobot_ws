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

# 2. 准备依赖安装的缓存上下文：拷贝除 map_merge 外所有包的 package.xml 文件
echo ">>> [2/5] 提取除 map_merge 外的 package.xml 依赖配置文件..."
python3 -c "
import os, shutil
src_dir = 'src'
dst_dir = 'build_arm64_temp_src/src'
if os.path.exists('build_arm64_temp_src'):
    shutil.rmtree('build_arm64_temp_src')
# 提取除 map_merge 以外的 package.xml，用于安装系统依赖
for root, dirs, files in os.walk(src_dir):
    if 'package.xml' in files:
        if 'map_merge' in root:
            continue
        rel = os.path.relpath(root, src_dir)
        target = os.path.join(dst_dir, rel)
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

# 解析参数
FORCE_BUILD=false
SPECIFIED_PACKAGES=()

while [[ $# -gt 0 ]]; do
  case $1 in
    -f|--force)
      FORCE_BUILD=true
      shift
      ;;
    *)
      SPECIFIED_PACKAGES+=("$1")
      shift
      ;;
  esac
done

if [ ${#SPECIFIED_PACKAGES[@]} -gt 0 ]; then
  BUILD_ARGS="--packages-select ${SPECIFIED_PACKAGES[*]}"
  echo ">>> 检测到手动指定了编译包: ${SPECIFIED_PACKAGES[*]}"
else
  # 如果没有手动指定编译包，且 install_arm64 目录为空或不存在，自动启用全量编译
  if [ ! -d "install_arm64" ] || [ -z "$(ls -A install_arm64 2>/dev/null)" ]; then
    FORCE_BUILD=true
    echo ">>> 检测到 install_arm64 目录不存在或为空，自动启用全量编译以构建所有依赖..."
  fi

  if [ "$FORCE_BUILD" = true ]; then
    BUILD_ARGS="--packages-skip multirobot_map_merge"
    echo ">>> 已启用强制全量编译..."
  else
  echo ">>> 正在分析工作空间中发生修改的 ROS 2 功能包..."
  CHANGED_PKGS=$(python3 -c "
import subprocess, os
def get_changed():
    changed = set()
    try:
        res = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], capture_output=True, text=True)
        if res.returncode != 0 or 'true' not in res.stdout.lower():
            return 'ALL'
        files = []
        s_res = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True)
        for line in s_res.stdout.strip().split('\n'):
            if line:
                parts = line.strip().split(None, 1)
                if len(parts) >= 2: files.append(parts[1])
        d_res = subprocess.run(['git', 'diff', 'HEAD~1', '--name-only'], capture_output=True, text=True)
        if d_res.returncode == 0:
            for line in d_res.stdout.strip().split('\n'):
                if line and line not in files: files.append(line)
        for f in files:
            if f.startswith('src/'):
                parts = f.split('/')
                if len(parts) >= 3:
                    pkg_dir = os.path.join(parts[0], parts[1])
                    if os.path.exists(os.path.join(pkg_dir, 'package.xml')):
                        try:
                            import xml.etree.ElementTree as ET
                            tree = ET.parse(os.path.join(pkg_dir, 'package.xml'))
                            root = tree.getroot()
                            name = root.find('name')
                            if name is not None: changed.add(name.text.strip())
                        except:
                            changed.add(parts[1])
    except:
        return 'ALL'
    return ' '.join(sorted(list(changed))) if changed else 'NONE'
print(get_changed())
")

  if [ "$CHANGED_PKGS" = "ALL" ]; then
    BUILD_ARGS="--packages-skip multirobot_map_merge"
    echo ">>> Git 状态不可达或不在仓库中，默认执行全量编译..."
  elif [ "$CHANGED_PKGS" = "NONE" ]; then
    echo "=================================================="
    echo "  💡 提示: 未检测到发生修改的功能包。"
    echo "  如果您需要强制全量编译，请使用: ./scripts/build_arm64.sh -f"
    echo "  或者直接指定特定包名进行编译: ./scripts/build_arm64.sh <包名>"
    echo "=================================================="
    exit 0
  else
    # 过滤掉不需要编译的 multirobot_map_merge
    FILTERED_PKGS=()
    for pkg in ${CHANGED_PKGS}; do
      if [ "$pkg" != "multirobot_map_merge" ]; then
        FILTERED_PKGS+=("$pkg")
      fi
    done
    if [ ${#FILTERED_PKGS[@]} -eq 0 ]; then
      echo ">>> 变动包仅为排除包，无需执行编译。"
      exit 0
    fi
    BUILD_ARGS="--packages-select ${FILTERED_PKGS[*]}"
    echo ">>> 检测到以下被修改的功能包，将执行增量编译: ${FILTERED_PKGS[*]}"
  fi
fi
fi

echo "⚠️  注意: 为防止 QEMU 模拟多线程编译发生段错误(Segfault)，我们将限制使用单线程顺序编译，并调大 QEMU 栈大小..."
docker run --rm \
  -e QEMU_STACK_SIZE=536870912 \
  -v "${WORKSPACE_DIR}":/workspace \
  -w /workspace \
  rdk_robot_build:arm64 \
  bash -c "source /opt/ros/humble/setup.bash && export MAKEFLAGS=-j1 && colcon build ${BUILD_ARGS} --build-base build_arm64 --install-base install_arm64 --parallel-workers 1 --cmake-args -DCMAKE_BUILD_TYPE=None -DCMAKE_CXX_FLAGS='-O1' -DCMAKE_C_FLAGS='-O1' -DBUILD_TESTING=OFF"

# 5. 将编译产物的属主和属组修改回宿主机当前用户，避免权限冲突
echo ">>> [5/5] 正在修复编译产物权限为宿主机用户..."
docker run --rm \
  -v "${WORKSPACE_DIR}":/workspace \
  -w /workspace \
  rdk_robot_build:arm64 \
  bash -c "[ -d /workspace/build_arm64 ] && chown -R $(id -u):$(id -g) /workspace/build_arm64; [ -d /workspace/install_arm64 ] && chown -R $(id -u):$(id -g) /workspace/install_arm64"

echo "=================================================="
echo "          ARM64 编译完成！"
echo "  编译产物已生成至: install_arm64/"
echo "=================================================="
