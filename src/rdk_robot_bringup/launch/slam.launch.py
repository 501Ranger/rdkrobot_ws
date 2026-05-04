import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')

    config_file = os.path.join(
        get_package_share_directory('rdk_robot_bringup'),
        'config',
        'mapper_params_online_async.yaml',
    )

    return LaunchDescription([
        # 限制线程数，降低 RDK X5 CPU 占用
        SetEnvironmentVariable('OMP_NUM_THREADS', '4'),
        SetEnvironmentVariable('OPENBLAS_NUM_THREADS', '1'),
        SetEnvironmentVariable('MKL_NUM_THREADS', '1'),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use simulation/Gazebo clock',
        ),
        Node(
            parameters=[
                config_file,
                {'use_sim_time': use_sim_time},
            ],
            package='slam_toolbox',
            executable='async_slam_toolbox_node',
            name='slam_toolbox',
            output='screen',
            arguments=['--ros-args', '--log-level', 'warn'],
        ),
    ])
