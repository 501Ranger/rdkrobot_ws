"""
slam_nav.launch.py — 真实机器人：SLAM 建图 + Nav2 导航

启动顺序：
  T=0s   bringup_base（robot_state_publisher / joint_state_publisher / odom_tf_broadcaster）
  T=0s   lslidar N10P 雷达驱动
  T=3s   SLAM Toolbox（等待 TF 链就绪）
  T=15s  Nav2 导航栈（等待 SLAM 发布稳定的 map->odom TF）

使用前请先在另一终端启动 micro-ROS agent：
  ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyUSB0
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    bringup_launch_dir = os.path.join(
        get_package_share_directory('rdk_robot_bringup'), 'launch'
    )
    lslidar_launch_dir = os.path.join(
        get_package_share_directory('lslidar_driver'), 'launch'
    )

    bringup_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'bringup_base.launch.py')
        ),
    )

    lidar_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(lslidar_launch_dir, 'lsn10p_launch.py')
        ),
    )

    slam_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'slam.launch.py')
        ),
    )

    nav2_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'navigation.launch.py')
        ),
    )

    ld = LaunchDescription()
    ld.add_action(bringup_cmd)
    ld.add_action(lidar_cmd)
    ld.add_action(TimerAction(period=3.0, actions=[slam_cmd]))
    ld.add_action(TimerAction(period=15.0, actions=[nav2_cmd]))
    return ld
