import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('rdk_voice_assistant')

    config_file = LaunchConfiguration('config_file')
    places_file = LaunchConfiguration('places_file')
    enable_navigation = LaunchConfiguration('enable_navigation')
    use_sim_time = LaunchConfiguration('use_sim_time')

    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=os.path.join(pkg_dir, 'config', 'voice_assistant.yaml'),
            description='Voice assistant parameter file',
        ),
        DeclareLaunchArgument(
            'places_file',
            default_value=os.path.join(pkg_dir, 'config', 'places.yaml'),
            description='Named navigation places file',
        ),
        DeclareLaunchArgument(
            'enable_navigation',
            default_value='false',
            description='Send NavigateToPose goals when true',
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use simulation clock',
        ),
        Node(
            package='rdk_voice_assistant',
            executable='voice_assistant_node',
            name='voice_assistant_node',
            output='screen',
            parameters=[
                config_file,
                {
                    'places_file': places_file,
                    'enable_navigation': enable_navigation,
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
    ])
