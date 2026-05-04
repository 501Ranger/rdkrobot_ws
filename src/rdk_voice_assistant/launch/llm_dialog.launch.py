import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('rdk_voice_assistant')
    default_llm_config = os.path.join(pkg_dir, 'config', 'llm_dialog.yaml')
    if not os.path.exists(default_llm_config):
        default_llm_config = os.path.join(pkg_dir, 'config', 'llm_dialog.example.yaml')

    assistant_config = LaunchConfiguration('assistant_config')
    llm_config = LaunchConfiguration('llm_config')
    places_file = LaunchConfiguration('places_file')
    enable_navigation = LaunchConfiguration('enable_navigation')
    use_sim_time = LaunchConfiguration('use_sim_time')

    return LaunchDescription([
        DeclareLaunchArgument(
            'assistant_config',
            default_value=os.path.join(pkg_dir, 'config', 'voice_assistant.yaml'),
        ),
        DeclareLaunchArgument(
            'llm_config',
            default_value=default_llm_config,
        ),
        DeclareLaunchArgument(
            'places_file',
            default_value=os.path.join(pkg_dir, 'config', 'places.yaml'),
        ),
        DeclareLaunchArgument('enable_navigation', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        Node(
            package='rdk_voice_assistant',
            executable='voice_assistant_node',
            name='voice_assistant_node',
            output='screen',
            parameters=[
                assistant_config,
                {
                    'places_file': places_file,
                    'enable_navigation': enable_navigation,
                    'chat_fallback_reply': False,
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
        Node(
            package='rdk_voice_assistant',
            executable='llm_dialog_node',
            name='llm_dialog_node',
            output='screen',
            parameters=[llm_config, {'use_sim_time': use_sim_time}],
        ),
    ])
