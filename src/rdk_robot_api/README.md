# rdk_robot_api

`rdk_robot_api` 是一个基于 `ament_python` 构建的 ROS 2 功能包。它在后台维护一个 ROS 2 守护线程节点 `RobotApiNode`，并通过 **FastAPI** 框架提供了一套用于辅助交互与状态监控的 HMI（人机交互）Web 服务。

---

## 📁 1. 功能包定位与结构

该包将下位机硬件层、Nav2 导航层以及 SLAM 建图层的 ROS 2 物理接口，封装为友好的 HTTP RESTful API 和高频双向 WebSocket 接口，并挂载了 Web 端的静态 HMI 网页资源。

```text
rdk_robot_api/
├── config/            # 统一参数配置文件 (robot_params.yaml)
├── launch/            # ROS 2 Launch 启动脚本
├── rdk_robot_api/     # Python 源码目录
│   ├── main.py        # 服务主入口 (Uvicorn 启动与子进程清理)
│   ├── ros_node.py    # RobotApiNode 中介节点
│   ├── manager.py     # 进程管理器与 WebSocket 广播逻辑
│   ├── models.py      # Pydantic 数据模型
│   └── routes/        # RESTful 业务子路由
├── static/            # Web 端 HMI 静态资源 (HTML, CSS, JS)
├── package.xml        # ROS 2 包描述文件
├── setup.py           # 编译脚本
└── setup.cfg          # 编译配置文件
```

---

## ⚙️ 2. ROS 2 接口规格 (RobotApiNode)

`RobotApiNode` 节点作为 FastAPI 服务与 ROS 2 系统的“数据桥梁”，具体接口规格如下：

### 2.1 订阅的话题 (Topics Subscribed)

| 话题名称 | 消息类型 | 功能说明 |
| :--- | :--- | :--- |
| `/battery_state` | `sensor_msgs/msg/BatteryState` | 监听小车电压与电量比例 |
| `/odom` | `nav_msgs/msg/Odometry` | 里程计位姿，在 AMCL 未启动或超时无更新时用作备用位姿源 |
| `/amcl_pose` | `geometry_msgs/msg/PoseWithCovarianceStamped` | AMCL 定位估计位姿，优先作为机器人的主位姿源 |
| `/auto_localize/status` | `std_msgs/msg/Bool` | 监听全局重定位节点状态（如：重定位中/空闲） |
| `/plan` | `nav_msgs/msg/Path` | Nav2 规划出的全局路径折线（在节点中自动降采样限制在 150 点以内） |
| `/patrol/feedback` | `std_msgs/msg/String` | 监听底层巡逻状态机的反馈（例如到达航点、巡逻完成、巡逻中断） |

### 2.2 发布的话题 (Topics Published)

| 话题名称 | 消息类型 | 功能说明 |
| :--- | :--- | :--- |
| `/patrol/cmd` | `std_msgs/msg/String` | 发布巡逻控制指令（例如 `start_once` 等） |
| `/patrol/set_waypoints` | `geometry_msgs/msg/PoseArray` | 批量下发规划的多巡逻航点数组 |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | 发布底盘运动控制指令（用于 Web 手柄或键盘遥控） |
| `/initialpose` | `geometry_msgs/msg/PoseWithCovarianceStamped` | 发布初始估计位姿，用以激活 AMCL 粒子群或指示初始位置 |

### 2.3 调用的服务客户端 (Service Clients)

| 服务名称 | 服务类型 | 功能说明 |
| :--- | :--- | :--- |
| `/trigger_auto_localize` | `std_srvs/srv/Trigger` | 请求触发机器人的全局重定位程序 |
| `/map_server/load_map` | `nav2_msgs/srv/LoadMap` | 请求重新加载并应用修改后的静态栅格地图文件 |
| `/{node_name}/change_state` | `lifecycle_msgs/srv/ChangeState` | 修改指定 Lifecycle 节点的状态（用于启动或关闭底层传感器与服务） |
| `/lifecycle_manager_localization/manage_nodes` | `nav2_msgs/srv/ManageLifecycleNodes` | 控制定位生命周期管理器的节点状态 |

### 2.4 调用的动作客户端 (Action Clients)

| 动作名称 | 动作类型 | 功能说明 |
| :--- | :--- | :--- |
| `navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | 下发单点导航任务，异步驱动机器人前往目标点 |
| `compute_path_to_pose` | `nav2_msgs/action/ComputePathToPose` | 请求 Nav2 规划出一条到目标点的物理避障轨迹，供前端展示路径预览 |

---

## 🌐 3. Web API 与 通信协议

### 3.1 HTTP RESTful API 路由结构

后端通过模块化路由提供以下功能接口：

*   **系统状态接口 (`routes/system.py`)**：
    *   `GET /api/v1/system/info`：获取主机 CPU 架构、内存占用等系统级信息。
*   **机器人状态与流程控制 (`routes/robot.py`)**：
    *   `GET /api/v1/robot/status`：获取当前机器人状态（在 WebSocket 断开时降级轮询此接口）。
    *   `POST /api/v1/robot/hardware/init`：一键初始化底层硬件接口（串口代理、雷达、驱动等）。
    *   `POST /api/v1/robot/hardware/shutdown`：一键停止底层硬件及传感器进程。
*   **仿真启停 (`routes/sim.py`)**：
    *   `POST /api/v1/sim/start` 与 `/api/v1/sim/stop`：控制 Gazebo 仿真环境进程的开启与关闭。
*   **Agent 控制 (`routes/agent.py`)**：
    *   `POST /api/v1/agent/start` 与 `/api/v1/agent/stop`：控制 micro-ROS Agent 容器/进程的启停。
*   **巡逻控制 (`routes/patrol.py`)**：
    *   `POST /api/v1/patrol/cmd`：下发巡逻指令。
    *   `POST /api/v1/patrol/schedule`：配置并启停自动巡逻的定时调度器。
*   **导航与建图控制 (`routes/nav.py`, `routes/slam.py`, `routes/explore.py`)**：
    *   提供单点导航、多航点执行、自主前沿探索、SLAM 建图启动等控制接口。
*   **地图数据库管理 (`routes/maps.py`)**：
    *   实现地图列表获取、静态图片预览、虚拟墙/涂鸦保存、地图裁剪合成、重载 Nav2 地图等 API。

### 3.2 WebSocket 状态推送服务 (`/ws/status`)

后端提供 10Hz 频率的高频状态推送，包含位姿、电压、进程状态等合成数据：

```json
{
  "pose": { "x": 0.12, "y": -0.45, "yaw": 1.57 },
  "battery": 12.4,
  "hardware_status": {
    "agent_running": true,
    "lidar_running": true,
    "slam_running": false,
    "nav_running": true
  },
  "nav_status": "navigating",
  "nav_path": [
    { "x": 0.12, "y": -0.45 },
    ...
  ]
}
```

此外，WebSocket 还支持接收前端以 15Hz 发送的高频遥控指令：
```json
{
  "type": "teleop",
  "linear_x": 0.2,
  "angular_z": -0.5
}
```

---

## 🛠️ 4. 编译与独立运行

在板卡或开发环境中，你可以使用 `colcon` 对本包进行单独编译和运行。

### 4.1 独立编译
```bash
# 仅编译 rdk_robot_api 功能包
colcon build --packages-select rdk_robot_api --symlink-install
```

### 4.2 环境激活
```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
```

### 4.3 启动服务节点
使用 Launch 文件启动：
```bash
ros2 launch rdk_robot_api api.launch.py
```
该命令会自动拉起 `RobotApiNode` 节点以及 FastAPI Web 服务。
