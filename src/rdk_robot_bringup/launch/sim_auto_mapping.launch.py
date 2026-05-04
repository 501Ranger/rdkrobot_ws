"""
sim_auto_mapping.launch.py — 仿真：Gazebo + SLAM + Nav2 + explore_lite 自动建图

启动顺序：
  T=0s   Gazebo 仿真器 + 机器人模型（use_sim_time=true）
  T=3s   SLAM Toolbox
  T=10s  Nav2 导航栈
  T=16s  explore_lite 自主探索
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('rdk_robot_bringup')
    bringup_launch_dir = os.path.join(pkg_share, 'launch')
    tb3_gazebo_share = get_package_share_directory('turtlebot3_gazebo')

    world = LaunchConfiguration('world')
    urdf_path = LaunchConfiguration('urdf_path')
    nav2_params_file = LaunchConfiguration('nav2_params_file')
    explore_params_file = LaunchConfiguration('explore_params_file')

    declare_world = DeclareLaunchArgument(
        'world',
        default_value=os.path.join(tb3_gazebo_share, 'worlds', 'turtlebot3_world.world'),
        description='Gazebo world file',
    )
    declare_urdf = DeclareLaunchArgument(
        'urdf_path',
        default_value=os.path.join(pkg_share, 'urdf', 'rdk_robot_gazebo.urdf'),
        description='Gazebo URDF path',
    )
    declare_nav2_params = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=os.path.join(pkg_share, 'config', 'nav2_params.yaml'),
        description='Nav2 parameter file',
    )
    declare_explore_params = DeclareLaunchArgument(
        'explore_params_file',
        default_value=os.path.join(pkg_share, 'config', 'explore.yaml'),
        description='explore_lite parameter file',
    )

    sim_bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'gazebo_bringup.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'world': world,
            'urdf_path': urdf_path,
        }.items(),
    )

    slam_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'slam.launch.py')
        ),
        launch_arguments={'use_sim_time': 'true'}.items(),
    )

    nav2_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'navigation.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'params_file': nav2_params_file,
        }.items(),
    )

    explore_cmd = Node(
        package='explore_lite',
        executable='explore',
        name='explore_node',
        output='screen',
        parameters=[explore_params_file, {'use_sim_time': True}],
    )

    ld = LaunchDescription()
    ld.add_action(declare_world)
    ld.add_action(declare_urdf)
    ld.add_action(declare_nav2_params)
    ld.add_action(declare_explore_params)
    ld.add_action(sim_bringup)
    ld.add_action(TimerAction(period=3.0, actions=[slam_cmd]))
    ld.add_action(TimerAction(period=10.0, actions=[nav2_cmd]))
    ld.add_action(TimerAction(period=16.0, actions=[explore_cmd]))
    return ld
