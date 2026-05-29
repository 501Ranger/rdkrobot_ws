#!/usr/bin/python3
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import LifecycleNode
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument

import lifecycle_msgs.msg
import os

def generate_launch_description():
    import yaml

    driver_dir = os.path.join(get_package_share_directory('lslidar_driver'), 'params','lidar_uart_ros2', 'lsn10p.yaml')

    # Load unified robot parameters if available
    config_params = {}
    try:
        api_share = get_package_share_directory('rdk_robot_api')
        config_path = os.path.join(api_share, 'config', 'robot_params.yaml')
    except Exception:
        config_path = '/home/ranger/rdkrobot_ws/src/rdk_robot_api/config/robot_params.yaml'

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)
                if config_data and 'lidar' in config_data:
                    l_cfg = config_data['lidar']
                    config_params = {
                        'serial_port_': l_cfg.get('serial_port', '/dev/ttyUSB0'),
                        'device_ip': l_cfg.get('device_ip', '192.168.1.200'),
                        'device_ip_difop': l_cfg.get('device_ip_difop', '192.168.1.102'),
                        'frame_id': l_cfg.get('frame_id', 'laser_frame'),
                        'scan_topic': l_cfg.get('scan_topic', '/scan'),
                    }
        except Exception as e:
            print(f"Error loading unified parameters in Lidar launch: {e}")
                     
    driver_node = LifecycleNode(package='lslidar_driver',
                                executable='lslidar_driver_node',
                                name='lslidar_driver_node',		#设置激光数据topic名称
                                output='screen',
                                emulate_tty=True,
                                namespace='',
                                parameters=[driver_dir, config_params],
                                )

    return LaunchDescription([
        driver_node,
    ])

