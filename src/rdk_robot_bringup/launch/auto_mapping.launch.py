import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

def generate_launch_description():
    # 1. 机器人基础节点，不在板卡上启动 RViz
    bringup_launch_dir = os.path.join(get_package_share_directory('rdk_robot_bringup'), 'launch')
    bringup_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(bringup_launch_dir, 'bringup_base.launch.py'))
    )

    # 2. 激光雷达
    lslidar_launch_dir = os.path.join(get_package_share_directory('lslidar_driver'), 'launch')
    lidar_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(lslidar_launch_dir, 'lsn10p_launch.py'))
    )

    # 3. SLAM 建图节点
    slam_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(bringup_launch_dir, 'slam.launch.py'))
    )

    # 4. 导航节点 (Nav2)
    nav2_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(bringup_launch_dir, 'navigation.launch.py'))
    )

    # 5. explore_lite 自主探索节点
    explore_config = os.path.join(
        get_package_share_directory('rdk_robot_bringup'),
        'config',
        'explore.yaml'
    )
    explore_cmd = Node(
        package='explore_lite',
        executable='explore',
        name='explore_node',
        output='screen',
        parameters=[explore_config]
    )

    # 合并启动
    ld = LaunchDescription()
    ld.add_action(bringup_cmd)
    ld.add_action(lidar_cmd)
    ld.add_action(slam_cmd)
    ld.add_action(nav2_cmd)
    ld.add_action(explore_cmd)

    return ld
