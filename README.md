# RDK Robot Workspace (上位机)

这是一个基于 ROS 2 的建图与导航上位机工程，集成了雷达驱动、自主探索建图以及 Nav2 导航堆栈，运行在 RDK X5 板卡上面。本项目基于 ROS 2 Humble。

对应的下位机 (ESP32) 驱动代码请参考：[esp32-micro-ros-driver](https://github.com/501Ranger/esp32-micro-ros-driver)

## 📁 项目结构

```text
rdkrobot_ws/src/
├── rdk_robot_bringup/     # 核心启动包：包含 URDF 模型、Launch 脚本和配置文件（Nav2, Slam Toolbox）。
├── rdk_robot_core/        # 核心 C++ 节点：包含高频 TF 广播器 (odom_tf_broadcaster) 与巡逻节点 (patrol)。
├── rdk_robot_apps/        # Python 应用包：包含自动全局定位脚本 (auto_localize)。
├── LSLIDAR_X_ROS2/        # 镭神（LSLIDAR）系列激光雷达驱动，主要支持 n10p 等型号。
└── m-explore-ros2/        # 自主探索包：用于实现自动边界探索建图 (包含 explore 和 map_merge)。
```

## ✨ 功能特性

*   **全方位硬件驱动：** 适配镭神 N10P 雷达并与基于 ESP32 的微型下位机 (micro-ROS) 完美协同。
*   **SLAM建图与导航：** 集成了 slam_toolbox (建图) 和 nav2 (导航)。
*   **自主探索 (Auto-mapping)：** 支持基于前沿点的自动建图和多地图融合。
*   **仿真支持：** 包含一键式的 Gazebo 仿真环境与相应的 URDF 模型。

---

## 🚀 详细使用教程

### 1. 一键安装依赖包

在编译运行项目前，请确保已经安装了 ROS2 Humble 及必要的构建工具。可通过以下命令一键安装所有缺少的 ROS 依赖项：

```bash
# 进入工作空间目录
cd ~/rdkrobot_ws

# 更新 apt 包索引
sudo apt update

# 安装常用工具（如未安装）
sudo apt install -y python3-rosdep python3-colcon-common-extensions

# 初始化并更新 rosdep (如果未初始化过)
sudo rosdep init
rosdep update

# 一键安装所有需要的依赖包
rosdep install -i --from-path src --rosdistro humble -y
```

### 2. 编译与环境设置

```bash
# 编译整个工作空间
colcon build --symlink-install

# 激活环境 (建议将其加入到 ~/.bashrc)
source install/setup.bash
```

### 3. 连接下位机 (micro-ROS)

下位机通过 micro-ROS 接入 ROS2 网络，支持串口 (USB) 和 UDP (WiFi) 两种连接方式。建议通过 Docker 运行 micro-ROS-Agent 来建立通信：

**方法 A: 通过串口/USB 连接**
```bash
docker run -it --rm -v /dev:/dev --privileged microros/micro-ros-agent:humble serial --dev /dev/ttyACM0 -b 921600 -v6
```
*(注意：请根据实际情况确认下位机串口号，如 `/dev/ttyUSB0` 或 `/dev/ttyACM0`)*

**方法 B: 通过 UDP/WiFi 连接**
```bash
docker run -it --rm --net=host microros/micro-ros-agent:humble udp4 --port 8888
```

### 4. 镭神 N10P 激光雷达配置与运行

本项目使用的雷达是**镭神 N10P**，配置文件位于：
`src/LSLIDAR_X_ROS2/src/lslidar_driver/params/lidar_uart_ros2/lsn10p.yaml`

**需要关注修改的关键参数：**
*   `serial_port_`: 必须修改为您雷达实际插入的串口号（例如 `/dev/ttyACM0` 或自定义的别名）。
*   `frame_id`: 默认为 `laser_frame`，须与 TF 树中的雷达坐标系名称一致。
*   `scan_topic`: 默认为 `/scan`。

*(提示：您可以通过运行 `sudo bash src/LSLIDAR_X_ROS2/src/wheeltec_udev.sh` 脚本来绑定串口设备别名并赋予权限。)*

**启动雷达节点：**
```bash
ros2 launch lslidar_driver lsn10p_launch.py
```
*(或使用 launch 整合文件直接随 bringup 启动)*

### 5. 常用命令 (启动与运行)

#### 启动建图 (SLAM)
```bash
# 启动基础驱动 + 激光雷达 + SLAM
ros2 launch rdk_robot_bringup slam.launch.py

# 启动包含所有组件的 SLAM
ros2 launch rdk_robot_bringup slam_all_in_one.launch.py
```

#### 保存地图 (完成建图后)
建图完成后，使用以下命令将地图保存至 `maps` 文件夹：
```bash
ros2 run nav2_map_server map_saver_cli -f ~/rdkrobot_ws/maps/my_map
```
*(这会在 `~/rdkrobot_ws/maps/` 目录下生成 `my_map.pgm` 和 `my_map.yaml` 两个文件。)*

#### 启动导航 (Navigation)

##### 方法 A: 边建图边导航 (SLAM Toolbox Online Navigation)
```bash
# 启动 SLAM (提供定位和地图更新)
ros2 launch rdk_robot_bringup slam.launch.py

# 在另一个终端启动 Nav2 导航
ros2 launch rdk_robot_bringup navigation.launch.py
```

##### 方法 B: 使用已保存的静态地图进行导航 (AMCL 定位)
*   **仿真环境 (Gazebo)**：
    ```bash
    # 启动 Gazebo 仿真 + 静态地图加载 + AMCL 定位 + Nav2 导航
    ros2 launch rdk_robot_bringup sim_nav_with_map.launch.py
    ```
    *(提示：默认加载包内的 `my_map.yaml`。若要指定其他地图路径，可传参 `map:=/path/to/your/map.yaml`)*
*   **真实机器人**：
    已将底盘启动、雷达驱动和带有静态地图加载的定位/导航集成到了 `nav_with_map.launch.py`：
    ```bash
    # 一键启动底盘驱动 + 雷达驱动 + 静态地图加载 (AMCL) + Nav2 导航
    ros2 launch rdk_robot_bringup nav_with_map.launch.py
    ```
    *(提示：默认加载包内自带的 `my_map.yaml`。若要载入其他地图，可以传参 `map:=/path/to/other_map.yaml`；若需要自动全局重定位，可以传入 `auto_localize:=true`)*

#### 自动化/仿真
> **注意**：默认仿真环境使用的是 `turtlebot3_gazebo` 中的 `turtlebot3_world.world`，请确保系统中已安装该包（例如通过 `sudo apt install ros-humble-turtlebot3-gazebo`）。

```bash
# 启动仿真环境下的自主建图 (默认加载 turtlebot3_world 场景)
ros2 launch rdk_robot_bringup sim_auto_mapping.launch.py

# 启动 Gazebo 仿真环境 + SLAM 建图 + Nav2 导航
ros2 launch rdk_robot_bringup sim_slam_nav.launch.py

# 启动 Gazebo 仿真环境
ros2 launch rdk_robot_bringup gazebo_bringup.launch.py
```

## 🖥️ 网页控制舱与 Web API 服务 (HMI Dashboard)

本项目集成了内置的 **FastAPI** 上位机服务，并在 `http://<小车IP>:8000/` 托管了响应式且功能完备的**网页控制舱 (Web Dashboard)**。

### 1. 项目结构扩展

*   `src/rdk_robot_api/`：上位机 API 服务包。
    *   `rdk_robot_api/main.py`：基于 FastAPI 的主服务节点，挂载静态文件目录，实现 ROS 2 守护线程与接口转换。
    *   `rdk_robot_api/scheduler.py`：基于 JSON 持久化存储的定时巡逻调度管理模块。
    *   `static/`：网页 HMI 静态资源，包括 HTML (`index.html`)、样式表 (`css/style.css`)、页面逻辑 (`js/app.js`)。

### 2. 核心功能特性

*   **实时数据看板**：每秒高频轮询小车的电池状态、位姿坐标 ($X, Y$ 坐标、Yaw 航向角) 以及导航当前状态（IDLE, NAVIGATING, REACHED, FAILED, CANCELED）。
*   **一键模式协调与自动重定位**：支持在网页端一键开关 SLAM 建图，一键自主探索建图，以及输入名称直接保存地图。并在加载地图后支持 `一键全局重定位` (Auto Relocalize)。
*   **交互式地图缩放与平移 (Zoom & Pan)**：
    *   **手势与滚轮**：加载地图后支持通过鼠标滚轮进行 `0.4x - 5.0x` 无缝缩放，按住鼠标左键可对地图进行任意拖动平移。
    *   **快捷工具栏**：地图右上角集成了放大 (`➕`)、缩小 (`➖`) 以及恢复原位 (`🏠`) 悬浮控制按钮。
*   **小车地图实时渲染与自适应逆缩放 (Inverse Scale)**：
    *   代表小车的绿色微动呼吸灯图标与航向角箭头会高精度实时叠加在地图上。
    *   **自适应大小**：采用 CSS 逆向缩放因子 $\frac{1}{zoomScale}$ 进行平抑，保证地图在无限放大或缩小时，小车图标始终保持恒定精美的物理大小（`22px`），避免遮挡视线。
*   **地图无缝点击取点 (坐标变换不变性)**：
    *   在地图上直接点击任意点，网页会自动利用地图原点和分辨率参数，将点击的像素坐标转换为 ROS 的物理世界坐标并填入导航表单。该映射算法完全基于视口矩形（Bounding Rect）计算，在任意缩放和平移状态下都能保证取点绝对精确！
*   **语义点 (POI) 标定与点名导航**：可以在网页端为当前地图添加或删除带名称的语义点（如 `kitchen`），并能点击列表旁的 `去这里` 触发 Nav2 动作客户端一键导航至该语义点。
*   **定时巡逻调度班表**：可视化管理每天特定时刻定时唤醒小车巡逻的班表，配置自动持久化在本地 JSON 文件中。

### 3. 一键启动与运行

确保系统依赖中安装了 `python3-pip` 并通过本地用户空间安装了 API 服务依赖的 `fastapi` 和 `uvicorn` (见 `rdk_robot_api` 配置)。然后启动接口与控制舱：

```bash
# 启动 API 服务与网页控制舱
ros2 launch rdk_robot_api api.launch.py
```

启动后，在同一局域网的电脑、手机或平板浏览器上访问：
👉 **`http://<小车IP>:8000/`** (本地访问：`http://localhost:8000/`) 即可进入控制舱。

## 📂 辅助工具与脚本 (`scripts/`)
工作空间根目录下的 `scripts/` 目录中包含了一套将 2D 栅格地图转换并导入为 Gazebo 三维仿真物理世界的工具链：

1. **[fix_gray_walls.py](scripts/fix_gray_walls.py)**：
   * **作用**：地图噪点清理与二值化。它能将 SLAM 建图或图像旋转产生的暗灰色过渡像素（灰度值 $< 200$）强制设为纯黑色（$0$，表示障碍物/墙体），使墙壁界限分明，并自动备份原图。
2. **[map2world.py](scripts/map2world.py)**：
   * **作用**：一键生成三维物理世界。它读取静态地图的 `.yaml` 和 `.pgm`，使用 OpenCV 的膨胀和闭运算连接断裂墙面并去除噪点空洞，再利用 **贪婪网格算法 (Greedy Meshing)** 将相邻墙体像素合并为大矩形方块，最终导出为 Gazebo 的 [hallway.world](src/rdk_robot_bringup/worlds/hallway.world)。
3. **[test_greedy_mesh.py](scripts/test_greedy_mesh.py)**：
   * **作用**：合并算法原型测试脚本。用于在不写入世界文件的情况下测试不同图像预处理参数下生成的矩形网格数量，用以评估性能。

### 💡 转换工作流
建图保存后，若要将地图还原为 Gazebo 仿真世界中的三维墙体，可运行：
```bash
# 1. 净化地图墙体（可选）
python3 scripts/fix_gray_walls.py

# 2. 从静态地图生成 Gazebo 世界
python3 scripts/map2world.py
```

## ⚙️ 配置说明
- **Nav2 参数**: `src/rdk_robot_bringup/config/nav2_params.yaml`
- **SLAM 参数**: `src/rdk_robot_bringup/config/mapper_params_online_async.yaml`
- **URDF 模型**: `src/rdk_robot_bringup/urdf/`

## 🖥️ 交叉编译与一键部署 (高性能主机 -> RDK X5)

当我们需要在高性能的主机（x86_64）上修改代码并编译，然后部署到 RDK X5（ARM64）板卡上时，可以使用本项目提供的基于 Docker + QEMU 的交叉编译与部署工具链。

### 1. 主机编译 (ARM64 架构)
在主机上执行以下命令进行本地 ARM64 交叉编译：
```bash
# 启动交叉编译脚本
bash scripts/build_arm64.sh
```
*提示：该脚本会自动注册 QEMU 模拟环境，通过 Docker 容器内的 `rosdep` 自动解决板卡端的依赖并进行单线程编译，编译产物输出到本地的 `install_arm64/` 中，与主机的 `install/` (x86_64) 隔离。*

### 2. 一键同步部署到 RDK X5 板卡
确保主机与 RDK X5 在同一局域网下，且板卡开启了 SSH 服务。执行以下命令同步编译产物：
```bash
# 启动部署脚本
bash scripts/deploy_arm64.sh
```
*提示：脚本会提示您输入 RDK X5 板卡的 IP 地址、SSH 用户名（默认 `sunrise`）及目标工作空间安装路径（默认 `~/rdkrobot_ws/install`），优先通过 `rsync` 增量同步编译产物（若无则退化为 `scp`）。*

### 3. 板卡端环境激活
同步完成后，在 RDK X5 板卡终端上直接激活即可运行：
```bash
source ~/rdkrobot_ws/install/setup.bash
```
*(注意：请确保板卡端也安装了机器人运行所需的系统运行时依赖，例如 `ros-humble-slam-toolbox`、`ros-humble-navigation2` 等)*

## 🛠️ 开发规范
- **代码风格**: 遵循 ROS 2 C++ (Ament Lint) 和 Python (PEP8) 规范。
- **Launch 文件**: 优先使用 Python 编写 Launch 脚本。
- **坐标系**: 遵循 REP-105 标准（`map` -> `odom` -> `base_link` -> `laser_link`）。