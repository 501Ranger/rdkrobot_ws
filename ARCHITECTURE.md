# ARCHITECTURE.md - 项目架构与结构说明

本项目是运行在 RDK X5 嵌入式板卡上的智能小车上位机系统，基于 **ROS 2 Humble** 与 **FastAPI HMI 网页控制舱** 构建。

---

## 📁 1. 目录结构与功能模块
工作空间根目录为 `/home/ranger/rdkrobot_ws`，核心源码位于 `src/` 目录下：

```text
rdkrobot_ws/
├── src/
│   ├── rdk_robot_bringup/     # 核心启动包
│   │   ├── config/            # 包含 Nav2、Slam Toolbox 等参数配置文件
│   │   ├── urdf/              # 小车物理及碰撞 URDF 模型
│   │   ├── worlds/            # Gazebo 仿真 3D 物理场景
│   │   └── launch/            # 仿真与真实小车建图/导航的一键启动脚本
│   │
│   ├── rdk_robot_api/         # Python API 服务与 HMI 静态网页包
│   │   ├── config/            # 统一参数配置文件 robot_params.yaml
│   │   ├── static/            # 网页 HMI 静态资源层 (HTML, CSS, JS)
│   │   └── rdk_robot_api/     # API 服务逻辑子包 (模块化重构)
│   │       ├── main.py        # 服务主入口 (路由注册与子进程清理)
│   │       ├── scheduler.py   # 定时巡逻持久化调度器
│   │       ├── config.py      # 路径与 yaml 全局配置加载器
│   │       ├── models.py      # Pydantic 统一数据请求载荷模型
│   │       ├── manager.py     # 进程管理器与 WebSocket 广播逻辑
│   │       ├── ros_node.py    # RobotApiNode 节点类 (ActionClient 封装)
│   │       └── routes/        # RESTful 业务接口分路由子包
│   │           ├── system.py  # 主机环境与 CPU 架构 API
│   │           ├── robot.py   # 状态与 WebSocket 广播 API
│   │           ├── sim.py     # Gazebo 仿真启停控制 API
│   │           ├── agent.py   # micro-ROS 串口代理 API
│   │           ├── patrol.py  # 巡逻指令与定时任务 API
│   │           ├── nav.py     # 坐标/语义导航与多点路径预览 API
│   │           ├── slam.py    # SLAM 建图控制及联动 API
│   │           ├── explore.py # 前沿边界自主探索建图 API
│   │           └── maps.py    # 地图列表、预览及 POI 语义点管理 API
│   │
│   ├── rdk_robot_core/        # 核心 C++ 节点（TF 广播与巡逻控制）
│   ├── rdk_robot_apps/        # 高层 Python 应用（自动全局定位脚本等）
│   ├── LSLIDAR_X_ROS2/        # 镭神激光雷达 N10P 驱动包
│   └── m-explore-ros2/        # 自主前沿边界探索建图包 (explore_lite)
│
├── scripts/                   # 地图转换、交叉编译、以及实机一键更新部署拉取脚本
├── maps/                      # 历史保存的 2D 栅格地图数据库 (.yaml, .pgm)
└── install/                   # 编译生成的 ROS 2 部署空间
```

---

## ⚙️ 2. 参数统一收归规范
为了避免参数零散和硬编码，所有硬件、接口与串口配置全部归拢于统一的 YAML 配置文件：
- **配置文件**：[robot_params.yaml](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/config/robot_params.yaml)
- **参数控制范围**：
  - micro-ROS 串口代理的串口名称及通信波特率。
  - 镭神激光雷达的串口设备名、雷达 IP、帧率频率、Frame ID 及发布话题。
  - ROS 2 雷达驱动节点在 launch 时会动态读取并 override 覆盖该配置文件的值。

---

## 🔌 3. ROS 2 与 FastAPI 桥接逻辑 (RobotApiNode)
HMI 服务端在后台维护一个 ROS 2 守护线程，运行中介节点 `RobotApiNode`：

### 订阅的 ROS 2 话题
- `/battery_state` (`sensor_msgs/msg/BatteryState`) -> 获取小车当前电压与电量。
- `/amcl_pose` (`geometry_msgs/msg/PoseWithCovarianceStamped`) -> 获取小车在地图 `map` 坐标系下的估计位姿，优先作为 HMI 地图中的机器人定位源。
- `/odom` (`nav_msgs/msg/Odometry`) -> 里程计位姿坐标。在 AMCL 未启动或 1.0 秒无定位更新时，自动退避使用里程计坐标绘制移动迹线。
- `/auto_localize/status` (`std_msgs/msg/Bool`) -> 重定位状态（空闲、重定位中等）。
- `/plan` (`nav_msgs/msg/Path`) -> Nav2 规划出的全局路径折线，后台自动进行降采样提取（最大 150 个点以优化传输带宽）。

### 发布的 ROS 2 话题
- `/patrol/cmd` (`std_msgs/msg/String`) -> 下发巡逻控制指令。
- `/patrol/set_waypoints` (`geometry_msgs/PoseArray`) -> 批量下发规划的航点数组。
- `/cmd_vel` (`geometry_msgs/Twist`) -> 下发底盘运动速度指令（线速度与角速度），高频响应游戏手柄操控。

### 调用的 ROS 2 Action 动作
- `navigate_to_pose` (`nav2_msgs/action/NavigateToPose`) -> 驱动机器人前往目标点。
- `compute_path_to_pose` (`nav2_msgs/action/ComputePathToPose`) -> 异步请求 Nav2 分段规划高精度的物理避障轨迹，供前端实现算路预览。

---

## 🖥️ 4. 网页控制舱 (Web HMI) 通信与交互架构
控制舱采用 Glassmorphism 现代玻璃拟态风格设计，支持**深色科幻风**与**高雅亮白风**双向切换。

### 4.1 状态通信双轨容错机制
为了保证不同局域网及反代环境下通信的 100% 连通性，采用双轨推送架构：
1. **高频 WebSocket (10Hz)**：建立于 `/ws/status`，后台协程每 100ms 广播一次合并后的状态包（包含位姿、电量、以及 SLAM/Explore/Agent/Sim 各进程运行状态）。同时，它升级为双向信道，支持接收前端 15Hz 高频发送的 `{ "type": "teleop", "linear_x": ..., "angular_z": ... }` 游戏手柄遥控指令。
2. **容错 HTTP 轮询**：若 WebSocket 连接连续握手失败 3 次，前端自动无缝降级为 1.5 秒/次的 HTTP 轮询模式，访问后端统一的 `/api/v1/robot/status` API，保障页面状态与交互绝不卡死。

### 4.2 SVG 多轨地图绘制 (SVG Overlay)
在自适应地图图片上层覆盖了一个 `pointer-events: none` 的 SVG 画布，进行物理到像素坐标的实时换算：
- **实时轨迹线（绿色虚线）**：收集小车历史轨迹（位移超 3cm 记录一次），右上角支持一键开启/隐藏（👣）与一键清空（🧹）。
- **Nav2 全局规划路径（紫色实线）**：展示 Nav2 实时的全局路线，导航结束/中止时自动双向清空。
- **航线规划路径（青色实线及编号标记）**：在地图上点击取点生成的航点序列。支持向后端 `/api/v1/nav/preview` 请求基于 Nav2 的真实避障规划，以青色曲线精细绘制；若 Nav2 算路服务不可用，则自动降级为传统直线连接。
- **滑屏拖拽防误触**：移动端单指拖拽平移地图时，若位移大于 5 像素，松开时会自动屏蔽点击取点事件，防止误触导航。
- **深色/浅色主题双轨切换**：Header 支持 🌙/☀️ 切换键，浅色皮肤具备精美白色毛玻璃质感，主题选择信息由 LocalStorage 持久化存储。
- **XBOX 蓝牙手柄遥控**：支持标准 XBOX 协议蓝牙手柄，通过网页端使能控制，配有高频防抖中位刹车限流算法，以及摇杆偏移可视化十字坐标指示盘。
