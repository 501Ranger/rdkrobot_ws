import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    package_name = 'rdk_robot_bringup'
    pkg_share = get_package_share_directory(package_name)
    gazebo_share = get_package_share_directory('gazebo_ros')

    default_urdf = os.path.join(pkg_share, 'urdf', 'rdk_robot_gazebo.urdf')
    default_world = os.path.join(gazebo_share, 'worlds', 'empty.world')

    urdf_path = LaunchConfiguration('urdf_path')
    world = LaunchConfiguration('world')
    use_sim_time = LaunchConfiguration('use_sim_time')

    declare_urdf = DeclareLaunchArgument(
        'urdf_path',
        default_value=default_urdf,
        description='Absolute path to robot URDF file for Gazebo simulation',
    )

    declare_world = DeclareLaunchArgument(
        'world',
        default_value=default_world,
        description='Gazebo world file',
    )

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation clock',
    )

    gazebo_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(gazebo_share, 'launch', 'gazebo.launch.py')
        ),
        launch_arguments={'world': world}.items(),
    )

    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': ParameterValue(Command(['cat ', urdf_path]), value_type=str),
            'use_sim_time': use_sim_time,
        }],
    )

    spawn_entity_node = Node(
        package='gazebo_ros',
        executable='spawn_entity.py',
        arguments=['-entity', 'rdk_robot', '-topic', 'robot_description', '-x', '0.0', '-y', '0.0', '-z', '0.05'],
        output='screen',
    )

    return LaunchDescription([
        declare_urdf,
        declare_world,
        declare_use_sim_time,
        gazebo_launch,
        robot_state_publisher_node,
        spawn_entity_node,
    ])
