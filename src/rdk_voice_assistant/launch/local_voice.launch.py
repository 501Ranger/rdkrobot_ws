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
    llm_config = LaunchConfiguration('llm_config')
    places_file = LaunchConfiguration('places_file')
    model_path = LaunchConfiguration('model_path')
    tts_engine = LaunchConfiguration('tts_engine')
    asr_engine = LaunchConfiguration('asr_engine')
    start_stt = LaunchConfiguration('start_stt')
    start_tts = LaunchConfiguration('start_tts')
    start_llm_dialog = LaunchConfiguration('start_llm_dialog')
    start_web_dialog = LaunchConfiguration('start_web_dialog')
    enable_navigation = LaunchConfiguration('enable_navigation')
    use_sim_time = LaunchConfiguration('use_sim_time')
    require_wake_word = LaunchConfiguration('require_wake_word')
    start_localization = LaunchConfiguration('start_localization')

    default_llm_config = os.path.join(pkg_dir, 'config', 'llm_dialog.yaml')
    if not os.path.exists(default_llm_config):
        default_llm_config = os.path.join(pkg_dir, 'config', 'llm_dialog.example.yaml')

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
            'llm_config',
            default_value=default_llm_config,
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
            default_value='sherpa-onnx',
            description='pyttsx3, espeak, piper, edge-tts, sherpa-onnx, or mimo',
        ),
        DeclareLaunchArgument(
            'asr_engine',
            default_value='sherpa-onnx',
            description='vosk, sherpa-onnx, sherpa-onnx-streaming, or mimo',
        ),
        DeclareLaunchArgument('start_stt', default_value='true'),
        DeclareLaunchArgument('start_tts', default_value='true'),
        DeclareLaunchArgument('start_localization', default_value='true'),
        DeclareLaunchArgument('start_llm_dialog', default_value='true'),
        DeclareLaunchArgument('start_web_dialog', default_value='true'),
        DeclareLaunchArgument('enable_navigation', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'require_wake_word',
            default_value='true',
            description='Whether to require wake word to accept voice commands',
        ),
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
                    'asr_engine': asr_engine,
                    'require_wake_word': require_wake_word,
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
        Node(
            package='rdk_voice_assistant',
            executable='sound_source_localization_node',
            name='sound_source_localization_node',
            output='screen',
            condition=IfCondition(start_localization),
            parameters=[
                local_voice_config,
                {
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
        Node(
            package='rdk_voice_assistant',
            executable='llm_dialog_node',
            name='llm_dialog_node',
            output='screen',
            condition=IfCondition(start_llm_dialog),
            parameters=[
                llm_config,
                {
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
        Node(
            package='rdk_voice_assistant',
            executable='web_dialog_node',
            name='web_dialog_node',
            output='screen',
            condition=IfCondition(start_web_dialog),
            parameters=[
                local_voice_config,
                {
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
    ])
