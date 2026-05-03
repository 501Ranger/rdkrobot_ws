# RDK Robot ROS 2 Workspace

这是一个基于 ROS 2 的建图与导航上位机工程，集成了雷达驱动、自主探索建图以及 Nav2 导航堆栈，运行在RDK X5板卡上面。

## 项目结构
- `src/rdk_robot_bringup`: 核心启动包，包含 URDF 模型、Launch 脚本和配置文件（Nav2, Slam Toolbox）。
- `src/m-explore-ros2`: 自主探索包，用于实现自动边界探索建图。
- `src/LSLIDAR_X_ROS2`: 镭神（LSLIDAR）系列激光雷达驱动。

## 常用命令

### 编译与环境设置
```bash
# 编译整个工作空间
colcon build --symlink-install

# 激活环境
source install/setup.bash
```

### 启动建图 (SLAM)
```bash
# 启动基础驱动 + 激光雷达 + SLAM
ros2 launch rdk_robot_bringup slam.launch.py

# 启动包含所有组件的 SLAM
ros2 launch rdk_robot_bringup slam_all_in_one.launch.py
```

### 启动导航 (Navigation)
```bash
# 启动 Nav2 导航
ros2 launch rdk_robot_bringup navigation.launch.py
```

### 自动化/仿真
```bash
# 启动仿真环境下的自主建图
ros2 launch rdk_robot_bringup auto_mapping_sim.launch.py

# 启动 Gazebo 仿真环境
ros2 launch rdk_robot_bringup gazebo_bringup.launch.py
```

## 配置说明
- **Nav2 参数**: `src/rdk_robot_bringup/config/nav2_params.yaml`
- **SLAM 参数**: `src/rdk_robot_bringup/config/mapper_params_online_async.yaml`
- **URDF 模型**: `src/rdk_robot_bringup/urdf/`

## 开发规范
- **代码风格**: 遵循 ROS 2 C++ (Ament Lint) 和 Python (PEP8) 规范。
- **Launch 文件**: 优先使用 Python 编写 Launch 脚本。
- **坐标系**: 遵循 REP-105 标准（`map` -> `odom` -> `base_link` -> `laser_link`）。



