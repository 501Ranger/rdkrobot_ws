#!/usr/bin/python3
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():

    driver_dir = os.path.join(get_package_share_directory('lslidar_driver'), 'params','lidar_uart_ros2', 'lsn10p.yaml')

    driver_node = Node(package='lslidar_driver',
                                executable='lslidar_driver_node',
                                name='lslidar_driver_node',
                                output='screen',
                                emulate_tty=True,
                                parameters=[driver_dir],
                                arguments=['--ros-args', '--log-level', 'warn'],
                                )

    return LaunchDescription([
        driver_node,
    ])
