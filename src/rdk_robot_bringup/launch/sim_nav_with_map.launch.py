"""
sim_nav_with_map.launch.py — 仿真：Gazebo + 指定静态地图 + AMCL定位 + Nav2 导航
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
    nav2_bringup_share = get_package_share_directory('nav2_bringup')
    
    # 默认使用我们刚自动生成的楼道 world 文件
    default_world = os.path.join(pkg_share, 'worlds', 'hallway.world')
    default_urdf = os.path.join(pkg_share, 'urdf', 'rdk_robot_gazebo.urdf')
    # 默认使用实机建好的静态地图
    default_map = os.path.join('/home/ranger/rdkrobot_ws/maps', 'my_map.yaml') 
    default_nav2_params = os.path.join(pkg_share, 'config', 'nav2_sim_params.yaml')

    world = LaunchConfiguration('world')
    urdf_path = LaunchConfiguration('urdf_path')
    map_yaml_file = LaunchConfiguration('map')
    nav2_params_file = LaunchConfiguration('nav2_params_file')

    declare_world = DeclareLaunchArgument(
        'world', default_value=default_world, description='Gazebo world file'
    )
    declare_urdf = DeclareLaunchArgument(
        'urdf_path', default_value=default_urdf, description='Gazebo URDF path'
    )
    declare_map = DeclareLaunchArgument(
        'map', default_value=default_map, description='Full path to map yaml file to load'
    )
    declare_nav2_params = DeclareLaunchArgument(
        'nav2_params_file', default_value=default_nav2_params, description='Nav2 parameter file'
    )

    # 1. 启动 Gazebo 和机器人模型
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

    # 2. 启动 Nav2 Bringup (包含 map_server, amcl, bt_navigator, planner, controller 等)
    nav2_bringup_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_share, 'launch', 'bringup_launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'map': map_yaml_file,
            'params_file': nav2_params_file,
        }.items(),
    )

    # 3. 启动 RViz 以便用户能看到地图并给定初始位姿
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', os.path.join(nav2_bringup_share, 'rviz', 'nav2_default_view.rviz')],
        parameters=[{'use_sim_time': True}],
        output='screen'
    )

    # 4. 启动自动定位脚本（撒粒子 + 原地打转）
    auto_localize_node = Node(
        package='rdk_robot_bringup',
        executable='auto_localize',
        name='auto_localize',
        output='screen',
        parameters=[{'use_sim_time': True}]
    )

    ld = LaunchDescription()
    ld.add_action(declare_world)
    ld.add_action(declare_urdf)
    ld.add_action(declare_map)
    ld.add_action(declare_nav2_params)
    
    ld.add_action(sim_bringup)
    # 延迟 5 秒启动导航，等待 Gazebo 完全启动
    ld.add_action(TimerAction(period=5.0, actions=[nav2_bringup_cmd]))
    # 延迟 7 秒启动 RViz
    ld.add_action(TimerAction(period=7.0, actions=[rviz_node]))
    # 延迟 12 秒启动自动全局定位（等待 AMCL 完全启动）
    ld.add_action(TimerAction(period=12.0, actions=[auto_localize_node]))
    
    return ld
