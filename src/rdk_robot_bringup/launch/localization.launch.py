import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    pkg_share = get_package_share_directory('rdk_robot_bringup')
    nav2_bringup_share = get_package_share_directory('nav2_bringup')

    use_sim_time = LaunchConfiguration('use_sim_time')
    map_yaml_file = LaunchConfiguration('map')
    params_file = LaunchConfiguration('params_file')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation (Gazebo) clock if true',
    )

    declare_map = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg_share, 'maps', 'string.yaml'),
        description='Full path to map yaml file to load',
    )

    declare_params_file = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(pkg_share, 'config', 'nav2_sim_params.yaml'),
        description='Full path to the Nav2 parameters file to use',
    )

    # 包含 nav2_bringup 中的 bringup_launch.py
    # 它同时启动定位（map_server/amcl）与导航堆栈（planner/controller/bt_navigator 等）
    localization_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_share, 'launch', 'bringup_launch.py')
        ),
        launch_arguments={
            'use_sim_time': use_sim_time,
            'map': map_yaml_file,
            'params_file': params_file,
            'use_composition': 'False',
        }.items(),
    )

    auto_localize_node = Node(
        package='rdk_robot_apps',
        executable='auto_localize',
        name='auto_localize',
        output='screen',
        parameters=[{'use_sim_time': use_sim_time}]
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_map,
        declare_params_file,
        localization_cmd,
        auto_localize_node,
    ])
