from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='rdk_robot_api',
            executable='api_server',
            name='api_server_node',
            output='screen'
        )
    ])
