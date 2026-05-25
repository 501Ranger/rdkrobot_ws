"""
nav_with_map.launch.py — 真实机器人：根据已保存地图进行 AMCL 定位 + Nav2 导航

启动顺序：
  T=0s   bringup_base（robot_state_publisher / joint_state_publisher / odom_tf_broadcaster）
  T=0s   lslidar N10P 雷达驱动
  T=5s   Nav2 Bringup（包含 map_server, amcl, bt_navigator, planner, controller 等，等待 TF 链就绪）
  T=12s  (可选) 自动全局定位脚本（撒粒子 + 原地打转）

使用前请先在另一终端启动 micro-ROS agent：
  ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyUSB0
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory("rdk_robot_bringup")
    bringup_launch_dir = os.path.join(pkg_share, "launch")
    lslidar_launch_dir = os.path.join(
        get_package_share_directory("lslidar_driver"), "launch"
    )
    nav2_bringup_share = get_package_share_directory("nav2_bringup")

    # 默认使用实机建好的静态地图
    default_map = os.path.join(pkg_share, "maps", "my_map.yaml")
    default_nav2_params = os.path.join(pkg_share, "config", "nav2_params.yaml")

    map_yaml_file = LaunchConfiguration("map")
    nav2_params_file = LaunchConfiguration("nav2_params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")
    auto_localize = LaunchConfiguration("auto_localize")

    declare_map = DeclareLaunchArgument(
        "map",
        default_value=default_map,
        description="Full path to map yaml file to load",
    )
    declare_nav2_params = DeclareLaunchArgument(
        "nav2_params_file",
        default_value=default_nav2_params,
        description="Nav2 parameter file",
    )
    declare_use_sim_time = DeclareLaunchArgument(
        "use_sim_time",
        default_value="false",
        description="Use simulation (Gazebo) clock if true",
    )
    declare_auto_localize = DeclareLaunchArgument(
        "auto_localize",
        default_value="false",
        description="Whether to run auto localization (dangerous on real robot!)",
    )

    # 1. 启动实机底盘
    bringup_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, "bringup_base.launch.py")
        ),
    )

    # 2. 启动 lslidar N10P 雷达驱动
    lidar_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(lslidar_launch_dir, "lsn10p_launch.py")
        ),
    )

    # 3. 启动 Nav2 Bringup (包含 map_server, amcl, bt_navigator, planner, controller 等)
    nav2_bringup_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_share, "launch", "bringup_launch.py")
        ),
        launch_arguments={
            "use_sim_time": use_sim_time,
            "map": map_yaml_file,
            "params_file": nav2_params_file,
        }.items(),
    )

    # 5. 启动自动定位脚本（撒粒子 + 原地打转，默认为 false，安全第一）
    auto_localize_node = Node(
        package="rdk_robot_apps",
        executable="auto_localize",
        name="auto_localize",
        output="screen",
        parameters=[{"use_sim_time": use_sim_time}],
        condition=IfCondition(auto_localize),
    )

    ld = LaunchDescription()

    # 声明参数
    ld.add_action(declare_map)
    ld.add_action(declare_nav2_params)
    ld.add_action(declare_use_sim_time)
    ld.add_action(declare_auto_localize)

    # 启动基本硬件驱动
    ld.add_action(bringup_cmd)
    ld.add_action(lidar_cmd)

    # 延迟 5 秒启动导航（等待硬件 TF 链完全稳定）
    ld.add_action(TimerAction(period=5.0, actions=[nav2_bringup_cmd]))

    # 延迟 12 秒启动自动全局定位（如果开启，等待 AMCL 完全启动）
    ld.add_action(TimerAction(period=12.0, actions=[auto_localize_node]))

    return ld
