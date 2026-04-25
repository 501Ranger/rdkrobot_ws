import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    
    config_file = os.path.join(
        get_package_share_directory('rdk_robot_bringup'),
        'config',
        'mapper_params_online_async.yaml'
    )

    return LaunchDescription([
        SetEnvironmentVariable('OMP_NUM_THREADS', '4'),
        SetEnvironmentVariable('OPENBLAS_NUM_THREADS', '1'),
        SetEnvironmentVariable('MKL_NUM_THREADS', '1'),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use simulation/Gazebo clock'
        ),
        # 这里启动的 async_slam_toolbox_node 就是 slam_toolbox 原生的高性能 C++ 节点
        Node(
            parameters=[
              config_file,
              {'use_sim_time': use_sim_time}
            ],
            package='slam_toolbox',
            executable='async_slam_toolbox_node',
            name='slam_toolbox',
            output='screen',
            arguments=['--ros-args', '--log-level', 'warn']
        )
    ])
