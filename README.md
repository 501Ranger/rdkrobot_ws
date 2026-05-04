# RDK Robot Workspace (上位机)

这是一个基于 ROS 2 的建图与导航上位机工程，集成了雷达驱动、自主探索建图以及 Nav2 导航堆栈，运行在 RDK X5 板卡上面。本项目基于 ROS 2 Humble。

对应的下位机 (ESP32) 驱动代码请参考：[esp32-micro-ros-driver](https://github.com/501Ranger/esp32-micro-ros-driver)

## 📁 项目结构

```text
rdkrobot_ws/src/
├── rdk_robot_bringup/     # 核心启动包：包含 URDF 模型、Launch 脚本和配置文件（Nav2, Slam Toolbox）。
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

#### 启动导航 (Navigation)
```bash
# 启动 Nav2 导航
ros2 launch rdk_robot_bringup navigation.launch.py
```

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

## ⚙️ 配置说明
- **Nav2 参数**: `src/rdk_robot_bringup/config/nav2_params.yaml`
- **SLAM 参数**: `src/rdk_robot_bringup/config/mapper_params_online_async.yaml`
- **URDF 模型**: `src/rdk_robot_bringup/urdf/`

## 🛠️ 开发规范
- **代码风格**: 遵循 ROS 2 C++ (Ament Lint) 和 Python (PEP8) 规范。
- **Launch 文件**: 优先使用 Python 编写 Launch 脚本。
- **坐标系**: 遵循 REP-105 标准（`map` -> `odom` -> `base_link` -> `laser_link`）。