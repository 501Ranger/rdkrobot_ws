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
    local_voice_config = LaunchConfiguration('local_voice_config')
    places_file = LaunchConfiguration('places_file')
    model_path = LaunchConfiguration('model_path')
    tts_engine = LaunchConfiguration('tts_engine')
    start_stt = LaunchConfiguration('start_stt')
    start_tts = LaunchConfiguration('start_tts')
    enable_navigation = LaunchConfiguration('enable_navigation')
    use_sim_time = LaunchConfiguration('use_sim_time')

    return LaunchDescription([
        DeclareLaunchArgument(
            'assistant_config',
            default_value=os.path.join(pkg_dir, 'config', 'voice_assistant.yaml'),
        ),
        DeclareLaunchArgument(
            'local_voice_config',
            default_value=os.path.join(pkg_dir, 'config', 'local_voice.yaml'),
        ),
        DeclareLaunchArgument(
            'places_file',
            default_value=os.path.join(pkg_dir, 'config', 'places.yaml'),
        ),
        DeclareLaunchArgument(
            'model_path',
            default_value='',
            description='Path to local Vosk STT model',
        ),
        DeclareLaunchArgument(
            'tts_engine',
            default_value='pyttsx3',
            description='pyttsx3, espeak, piper, or print',
        ),
        DeclareLaunchArgument('start_stt', default_value='true'),
        DeclareLaunchArgument('start_tts', default_value='true'),
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
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
        Node(
            package='rdk_voice_assistant',
            executable='local_stt_node',
            name='local_stt_node',
            output='screen',
            condition=IfCondition(start_stt),
            parameters=[
                local_voice_config,
                {
                    'model_path': model_path,
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
        Node(
            package='rdk_voice_assistant',
            executable='local_tts_node',
            name='local_tts_node',
            output='screen',
            condition=IfCondition(start_tts),
            parameters=[
                local_voice_config,
                {
                    'engine': tts_engine,
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
    ])
