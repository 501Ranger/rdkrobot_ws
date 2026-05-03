import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('rdk_voice_assistant')

    assistant_config = LaunchConfiguration('assistant_config')
    rdk_voice_config = LaunchConfiguration('rdk_voice_config')
    places_file = LaunchConfiguration('places_file')
    enable_navigation = LaunchConfiguration('enable_navigation')
    use_sim_time = LaunchConfiguration('use_sim_time')
    start_asr_bridge = LaunchConfiguration('start_asr_bridge')
    start_tts_bridge = LaunchConfiguration('start_tts_bridge')
    start_sensevoice = LaunchConfiguration('start_sensevoice')
    start_hobot_tts = LaunchConfiguration('start_hobot_tts')
    sensevoice_package = LaunchConfiguration('sensevoice_package')
    sensevoice_executable = LaunchConfiguration('sensevoice_executable')
    hobot_tts_package = LaunchConfiguration('hobot_tts_package')
    hobot_tts_executable = LaunchConfiguration('hobot_tts_executable')

    return LaunchDescription([
        DeclareLaunchArgument(
            'assistant_config',
            default_value=os.path.join(pkg_dir, 'config', 'voice_assistant.yaml'),
        ),
        DeclareLaunchArgument(
            'rdk_voice_config',
            default_value=os.path.join(pkg_dir, 'config', 'rdk_official_voice.yaml'),
        ),
        DeclareLaunchArgument(
            'places_file',
            default_value=os.path.join(pkg_dir, 'config', 'places.yaml'),
        ),
        DeclareLaunchArgument('enable_navigation', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('start_asr_bridge', default_value='true'),
        DeclareLaunchArgument('start_tts_bridge', default_value='true'),
        DeclareLaunchArgument(
            'start_sensevoice',
            default_value='false',
            description='Start RDK official sensevoice node if installed and configured',
        ),
        DeclareLaunchArgument(
            'start_hobot_tts',
            default_value='false',
            description='Start RDK official hobot_tts node if installed and model is ready',
        ),
        DeclareLaunchArgument('sensevoice_package', default_value='sensevoice_ros2'),
        DeclareLaunchArgument('sensevoice_executable', default_value='sensevoice_ros2'),
        DeclareLaunchArgument('hobot_tts_package', default_value='hobot_tts'),
        DeclareLaunchArgument('hobot_tts_executable', default_value='hobot_tts'),
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
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
        Node(
            package='rdk_voice_assistant',
            executable='rdk_asr_bridge_node',
            name='rdk_asr_bridge_node',
            output='screen',
            condition=IfCondition(start_asr_bridge),
            parameters=[rdk_voice_config, {'use_sim_time': use_sim_time}],
        ),
        Node(
            package='rdk_voice_assistant',
            executable='rdk_tts_bridge_node',
            name='rdk_tts_bridge_node',
            output='screen',
            condition=IfCondition(start_tts_bridge),
            parameters=[rdk_voice_config, {'use_sim_time': use_sim_time}],
        ),
        Node(
            package=sensevoice_package,
            executable=sensevoice_executable,
            name='sensevoice_ros2',
            output='screen',
            condition=IfCondition(start_sensevoice),
            parameters=[{'use_sim_time': use_sim_time}],
        ),
        Node(
            package=hobot_tts_package,
            executable=hobot_tts_executable,
            name='hobot_tts',
            output='screen',
            condition=IfCondition(start_hobot_tts),
            parameters=[{'use_sim_time': use_sim_time}],
        ),
    ])
