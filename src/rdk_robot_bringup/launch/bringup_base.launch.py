import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    package_name = 'rdk_robot_bringup'

    urdf_file = os.path.join(
        get_package_share_directory(package_name),
        'urdf',
        'rdk_robot.urdf',
    )
    with open(urdf_file, 'r') as infp:
        robot_desc = infp.read()

    odom_tf_node = Node(
        package=package_name,
        executable='odom_tf_broadcaster',
        name='odom_tf_broadcaster',
        parameters=[{'child_frame_id': 'base_footprint'}],
    )

    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_desc}],
    )

    joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
    )

    return LaunchDescription([
        robot_state_publisher_node,
        joint_state_publisher_node,
        odom_tf_node,
    ])
