import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_name = 'rdk_robot_bringup'
    use_sim_time = LaunchConfiguration('use_sim_time')

    urdf_file = os.path.join(
        get_package_share_directory(package_name),
        'urdf',
        'rdk_robot.urdf',
    )
    with open(urdf_file, 'r') as infp:
        robot_desc = infp.read()

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation clock and suppress the standalone odom TF relay',
    )

    odom_tf_node = Node(
        package=package_name,
        executable='odom_tf_broadcaster',
        name='odom_tf_broadcaster',
        condition=UnlessCondition(use_sim_time),
        parameters=[{
            'child_frame_id': 'base_footprint',
            'use_odom_msg_stamp': False,
            'zero_at_startup': True,
            'use_sim_time': use_sim_time,
        }],
    )

    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_desc,
            'use_sim_time': use_sim_time,
        }],
    )

    joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        parameters=[{'use_sim_time': use_sim_time}],
    )

    return LaunchDescription([
        declare_use_sim_time,
        robot_state_publisher_node,
        joint_state_publisher_node,
        odom_tf_node,
    ])
