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

    # 增加大模型与 Web 对话服务参数及默认配置文件路径
    default_llm_config = os.path.join(pkg_dir, 'config', 'llm_dialog.yaml')
    if not os.path.exists(default_llm_config):
        default_llm_config = os.path.join(pkg_dir, 'config', 'llm_dialog.example.yaml')

    llm_config = LaunchConfiguration('llm_config')
    local_voice_config = LaunchConfiguration('local_voice_config')

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
        DeclareLaunchArgument(
            'llm_config',
            default_value=default_llm_config,
            description='LLM dialog config file',
        ),
        DeclareLaunchArgument(
            'local_voice_config',
            default_value=os.path.join(pkg_dir, 'config', 'local_voice.yaml'),
            description='Local voice/web dialog config file',
        ),
        
        # 1. 语音控制中心节点
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

        # 2. 大语言模型对话节点 (仿真/Web 交互核心)
        Node(
            package='rdk_voice_assistant',
            executable='llm_dialog_node',
            name='llm_dialog_node',
            output='screen',
            parameters=[
                llm_config,
                {
                    'use_sim_time': use_sim_time,
                },
            ],
        ),

        # 3. Web/API 对话桥接节点 (仿真/Web 交互核心)
        Node(
            package='rdk_voice_assistant',
            executable='web_dialog_node',
            name='web_dialog_node',
            output='screen',
            parameters=[
                local_voice_config,
                {
                    'use_sim_time': use_sim_time,
                },
            ],
        ),
    ])
