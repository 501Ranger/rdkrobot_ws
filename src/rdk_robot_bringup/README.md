# rdk_robot_bringup

`rdk_robot_bringup` 是 RDK Robot 机器人系统的**核心启动与配置包**。它包含了物理及碰撞 URDF 模型、Gazebo 仿真场景、Nav2/SLAM 配置文件，以及用于一键拉起建图、导航、仿真和可视化调试的 launch 脚本。

---

## 📁 1. 目录结构

```text
rdk_robot_bringup/
├── config/            # Slam Toolbox、Nav2、RViz2 的参数与视图配置文件
├── launch/            # 12 个 Launch 启动脚本（分实机、仿真、调试三类）
├── models/            # 仿真环境所需的 3D 网格与物理材质模型
├── urdf/              # 机器人的物理 URDF 文件与仿真专用 URDF 文件
├── worlds/            # Gazebo 仿真 3D 物理场景文件 (.world)
├── package.xml        # 功能包依赖描述文件
└── CMakeLists.txt     # CMake 编译脚本
```

---

## 🚀 2. Launch 启动脚本功能与用法

包内共提供了 12 个 python 版的 ROS 2 Launch 启动脚本，按照使用场景可划分为：**实机运行**、**物理仿真**、与**可视化调试**三类。

### 2.1 实机运行系列 (Real Robot Launch)

这些脚本运行在 RDK X5 嵌入式小车板卡上，用以控制真实机器人的传感器与运动。
*(注意：在使用真实机器人导航/建图前，请确保在另一终端运行了 micro-ROS 串口代理。)*

#### ① 基础底盘启动 `bringup_base.launch.py`
*   **功能**：拉起真实小车底盘的基础节点状态。包含物理 URDF 模型发布 (`robot_state_publisher`)、关节发布 (`joint_state_publisher`)、巡逻控制状态机 (`patrol_node`)，以及用于发布 `odom -> base_footprint` 坐标变换的 `odom_tf_broadcaster`（在 C++ 节点中实现，用系统时钟替换下位机时间戳以防止时钟不同步）。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup bringup_base.launch.py
    ```

#### ② 静态建图 `slam.launch.py`
*   **功能**：启动 `slam_toolbox` 的 `async_slam_toolbox_node` 节点，基于雷达 `/scan` 和里程计进行异步 2D 栅格地图构建。
*   **特点**：脚本内预设了多线程数限制（`OMP_NUM_THREADS=4` 等），有效降低 RDK X5 嵌入式板卡的 CPU 占用率。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup slam.launch.py
    ```

#### ③ 动态建图与导航 `slam_nav.launch.py`
*   **功能**：一键拉起**实机边建图边导航**（无需提前加载地图）。
*   **启动时序**：
    *   **T = 0s**：拉起 `bringup_base.launch.py` 底盘基础节点，拉起雷达驱动。
    *   **T = 3s**：延迟 3 秒启动 `slam.launch.py` 异步建图（等待雷达和 TF 链就绪）。
    *   **T = 15s**：延迟 15 秒拉起 `navigation.launch.py` 导航栈（等待 SLAM 发布稳定的 `map -> odom` 的 TF 树）。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup slam_nav.launch.py
    ```

#### ④ 静态定位 `localization.launch.py`
*   **功能**：根据已保存的静态地图进行 AMCL 蒙特卡洛定位。
*   **参数**：`map`（指定要加载的 `.yaml` 栅格地图文件路径，默认使用本包自带地图）。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup localization.launch.py map:=/path/to/your_map.yaml
    ```

#### ⑤ 加载地图导航 `nav_with_map.launch.py`
*   **功能**：一键拉起**实机加载已有地图进行定位与导航**的主力控制脚本。
*   **启动时序**：
    *   **T = 0s**：启动底盘基础节点与雷达驱动。
    *   **T = 5s**：延迟 5 秒通过 `nav2_bringup` 加载地图，拉起 AMCL 定位与 Nav2 导航模块。
    *   **T = 12s**：（可选）自动拉起全局重定位节点 `auto_localize` 进行粒子散布与原地旋转校准。
*   **常用参数**：
    *   `map`：地图文件绝对路径。
    *   `auto_localize`：是否自动进行重定位打转（默认 `false`，实机运行请确保安全）。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup nav_with_map.launch.py map:=/home/ranger/rdkrobot_ws/maps/my_map.yaml
    ```

#### ⑥ 自主探索建图 `auto_mapping.launch.py`
*   **功能**：拉起实机自主边界探索建图。利用 `explore_lite` (m-explore) 前沿探索算法分析 SLAM 未知边界，自动发布巡航点指引小车完成全自动建图。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup auto_mapping.launch.py
    ```

---

### 2.2 仿真运行系列 (Simulation Launch)

这些脚本在 Gazebo 仿真环境下运行，无需连接真实小车硬件（自动开启 `use_sim_time:=true`）。

#### ⑦ 仿真物理世界拉起 `gazebo_bringup.launch.py`
*   **功能**：启动 Gazebo 物理仿真环境，在指定的 World 场景中生成并加载机器人的 3D 网格物理模型，并运行 `patrol_node` 巡逻状态机。
*   **参数**：
    *   `world`：仿真世界文件（默认为 TurtleBot3 World 场景）。
    *   `urdf_path`：仿真专用 URDF 路径。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup gazebo_bringup.launch.py
    ```

#### ⑧ 仿真边建图边导航 `sim_slam_nav.launch.py`
*   **功能**：在 Gazebo 中一键拉起机器人的边建图、边避障导航工作流。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup sim_slam_nav.launch.py
    ```

#### ⑨ 仿真加载地图导航 `sim_nav_with_map.launch.py`
*   **功能**：在 Gazebo 中一键拉起加载静态地图进行 AMCL 定位、自动启动 RViz2 可视化界面、并自动运行全局重定位 `auto_localize` 脚本。
*   **参数**：`map`（加载的地图文件路径）、`world`（仿真世界文件）。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup sim_nav_with_map.launch.py map:=/home/ranger/rdkrobot_ws/maps/string.yaml
    ```

#### ⑩ 仿真自主边界探索 `sim_auto_mapping.launch.py`
*   **功能**：在 Gazebo 仿真场景下，一键拉起前沿边界自主建图（联合仿真底盘、SLAM 建图、explore_lite 自动导航算路以及 RViz2 视图）。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup sim_auto_mapping.launch.py
    ```

---

### 2.3 调试辅助系列 (Debug & Tools)

#### ⑪ 单独导航模块拉起 `navigation.launch.py`
*   **功能**：仅启动 Nav2 的核心导航组件（如控制器、规划器、行为树导航等），但不包含地图服务器和 AMCL。用于 SLAM 动态建图过程下的路径规划与避障。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup navigation.launch.py
    ```

#### ⑫ 可视化监控启动 `bringup_rviz.launch.py`
*   **功能**：在本地开发 PC 终端或 VNC 桌面中启动预配置好的 RViz2。加载了雷达 scan、实时地图 map、机器人模型 TF、AMCL 粒子云以及全局/局部路径的可视化插件，方便直观监控和给定初始位姿点。
*   **用法**：
    ```bash
    ros2 launch rdk_robot_bringup bringup_rviz.launch.py
    ```
