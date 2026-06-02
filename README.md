# RDK Robot 建图导航机器人 (基于 ROS 2 Humble)

本项目是运行在 RDK X5 智能小车嵌入式板卡上的上位机 ROS 2 机器人系统。它以 **ROS 2 Humble** 作为核心运行框架，实现雷达驱动、物理建模、SLAM 建图、自主边界探索、Nav2 智能导航与多点巡逻。同时提供了一个轻量级的 Web 网页人机交互界面 (HMI)，作为辅助调试和状态监控工具。

对应的下位机 (ESP32) 驱动代码请参考：[esp32-micro-ros-driver](https://github.com/501Ranger/esp32-micro-ros-driver)

---

## 📁 1. 项目结构

```text
rdkrobot_ws/
├── src/                   # 源码目录
│   ├── rdk_robot_bringup/ # 核心启动包：包含 URDF 模型、Launch 脚本和配置文件（Nav2, Slam Toolbox）。
│   ├── rdk_robot_api/     # 辅助 API 包：提供 FastAPI 接口与 HMI 网页，作为辅助交互和监控工具。
│   ├── rdk_robot_core/    # 核心 C++ 节点：包含高频 TF 广播器 (odom_tf_broadcaster) 与巡逻节点 (patrol)。
│   ├── rdk_robot_apps/    # Python 应用包：包含自动全局定位脚本 (auto_localize)。
│   ├── LSLIDAR_X_ROS2/    # 镭神（LSLIDAR）系列激光雷达驱动，主要支持 n10p 等型号。
│   └── m-explore-ros2/    # 自主探索包：用于实现自动边界探索建图 (包含 explore 和 map_merge)。
├── maps/                  # 历史保存的 2D 栅格地图数据库（包含 .yaml 地图信息及自定义语义点）。
└── scripts/               # 辅助转换工具、一键依赖安装、一键交叉编译与同步部署脚本。
```

---

## 🛠️ 2. 环境准备与编译

### 2.1 依赖安装

在编译运行项目前，请确保系统已安装 ROS 2 Humble 并激活了环境变量。

项目提供了一键依赖环境检测与安装脚本，能够**自动检测本地系统包、rosdep 数据库及 Python 依赖库是否完整，并在缺失时进行增量安装**：

```bash
# 运行一键依赖检测与安装
bash scripts/install_dependencies.sh
```

### 2.2 编译工作空间

在工作空间根目录下，使用 `colcon` 进行编译。

*   **全量编译工作空间**：
    ```bash
    colcon build --symlink-install
    ```

### 2.3 环境变量激活

在每次开启新的终端或运行节点前，必须确保正确激活了 ROS 2 的系统环境变量和当前工作空间的环境变量：

```bash
# 1. 激活 ROS 2 Humble 系统环境变量
source /opt/ros/humble/setup.bash

# 2. 激活当前工作空间的编译产物环境变量
source install/setup.bash
```

### 2.4 开发机交叉编译与部署 (PC -> RDK X5)

为了方便在更高性能的主机（PC）上开发和编译，并通过网络快速同步到 RDK X5 嵌入式板卡，项目提供了交叉编译与推送部署工具链：

1. **开发机交叉编译 (PC)**：在开发机（Ubuntu/x86_64）上，可以通过 Docker 容器与 QEMU 模拟环境，编译出适用于 ARM64 架构的 ROS 2 产物，避免板卡编译性能不足的问题：
   * **智能增量编译**：`build_arm64.sh` 会自动分析 Git 工作区与 commit 变更，仅对发生改动的功能包执行增量构建（支持 `-f` 参数强制全量编译），大幅节省编译耗时。
   ```bash
   # 执行增量交叉编译脚本
   bash scripts/build_arm64.sh
   ```
   编译完成后，产物将生成在工作空间根目录下的 `install_arm64/` 中。

2. **一键推送部署到板卡 (PC -> RDK X5)**：可通过 `rsync` 增量同步（或 `scp` 全量复制）将交叉编译出的 `install_arm64/` 推送到板卡上：
   * **自动配置记忆**：首次运行会引导输入配置并持久化写入隐藏文件 `.deploy_config` ，后续运行一键读取，支持 `--reset` 重置。
   * **一键免密配对**：自适应诊断免密连接状态，引导一键安装分发 SSH 公钥，配置后实现全自动零密码部署。
   ```bash
   # 启动推送部署脚本
   bash scripts/deploy_arm64.sh
   ```

---

## 🚀 3. 运行与启动

项目的核心底盘驱动、SLAM 建图、及 Nav2 导航底座任务，均通过 `rdk_robot_bringup` 包中的一系列 Launch 启动脚本拉起。

详细的 Launch 脚本说明（包含 12 个 launch 脚本在实机运行、Gazebo 仿真及 RViz2 调试下的具体用法）请参见：👉 **[rdk_robot_bringup 启动包说明文档](src/rdk_robot_bringup/README.md)**

### 3.1 一键启动

本项目的 ROS 2 守护服务和辅助 Web 交互服务可通过以下 Launch 文件一键拉起（会自动拉起雷达、底盘、以及 FastAPI 服务）：

```bash
# 启动核心守护节点与辅助 Web 交互服务
ros2 launch rdk_robot_api api.launch.py
```

服务启动成功后，可在局域网内的电脑或移动端设备上通过浏览器访问辅助 HMI：
👉 **`http://<小车IP>:8000/`** (本地调试访问: `http://localhost:8000/`)

*   **实机底层硬件自动初始化**：在 ARM 实机环境下，API 服务在启动时会自动进行实机底层硬件初始化，实现上电即用。

---

## 🔌 4. ROS 2 物理接口与 Web API

我们将 Web 端的路由细节和 `RobotApiNode` 的 ROS 2 话题、动作、服务等具体的物理接口规格，收归在 `rdk_robot_api` 功能包中。

详细的接口规格说明请参见：👉 **[rdk_robot_api 接口与开发文档](src/rdk_robot_api/README.md)**

主要包含：
*   `RobotApiNode` 订阅的 `/odom`、`/amcl_pose`、`/plan`、`/battery_state` 等话题。
*   发布的速度控制话题 `/cmd_vel` 和初始位姿 `/initialpose`。
*   调用的 Nav2 导航动作客户端和地图加载服务客户端。
*   FastAPI 暴露的 RESTful 路由与 10Hz 状态推送 WebSocket 协议。

---

## 🖥️ 5. Web 辅助交互工具功能导览

Web 网页端作为机器人的辅助交互工具，提供了直观的图形化调试界面：

### 5.1 📍 导航与多航点任务配置
*   支持单点目标导航，实时在地图上绘制 Nav2 的规划路径。
*   支持可视化的多航点列表编辑，可以通过 ▲ / ▼ 物理按钮在移动端对航点进行排序调整，并一键发布执行连续巡逻。
*   支持保存自定义语义命名点（POI，如 `kitchen`），一键快速直达。

### 5.2 🎮 键盘与游戏手柄实时监控
*   支持标准的 XBOX 蓝牙手柄与网页虚拟摇杆，在 WebSocket 链路上以高频双向通信传输底盘控制量，配合中位防抖与限流算法，确保遥控灵敏平稳。

### 5.3 🗺️ 静态栅格地图修剪与重载
在网页地图编辑模块中，可以通过画笔直观地擦除 SLAM 扫描出的离散噪点（开辟通行区）或绘制黑色虚拟围墙（限制通行）。点击保存后，后端会自动将修改合入 `.pgm` 图形文件并调用 `map_server` 触发 Nav2 无缝重载，无需重启节点。

### 5.4 📊 系统监控、双轨日志与电源管理
*   **圆形状态仪表盘**：CPU 与内存占用以 SVG 拟态圆形进度条显示，网络上传/下载流量差分统计。
*   **双轨日志系统**：
    *   **核心系统事件终端**：开发与调试视图中集成了核心系统事件终端，通过 10Hz WebSocket 实时展示重大系统级日志。支持一键增量清屏，仅展现清空后的最新消息。
    *   **任务历史日志持久化**：后台多线程劫持单点/巡逻任务生命周期并累加行驶里程落盘持久化（上限 300 条）。前台以拟态看板实时查询日志历史、近 7 日频次直方图、成功率环图，并兼容移动窄屏滑动与流式布局。
*   **一键安全关机**：在开发面板一键下发免密关机指令，自带 1 秒优雅响应以完全确保安全关闭板卡硬件电源。