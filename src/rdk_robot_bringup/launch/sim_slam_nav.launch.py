import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    bringup_launch_dir = os.path.join(get_package_share_directory('rdk_robot_bringup'), 'launch')
    gazebo_share = get_package_share_directory('gazebo_ros')

    world = LaunchConfiguration('world')
    urdf_path = LaunchConfiguration('urdf_path')
    nav2_params_file = LaunchConfiguration('nav2_params_file')

    declare_world = DeclareLaunchArgument(
        'world',
        default_value=os.path.join(gazebo_share, 'worlds', 'empty.world'),
        description='Gazebo world file',
    )
    declare_urdf = DeclareLaunchArgument(
        'urdf_path',
        default_value=os.path.join(
            get_package_share_directory('rdk_robot_bringup'),
            'urdf',
            'rdk_robot_gazebo.urdf',
        ),
        description='Gazebo URDF path',
    )
    declare_nav2_params = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=os.path.join(
            get_package_share_directory('rdk_robot_bringup'),
            'config',
            'nav2_params.yaml',
        ),
        description='Nav2 parameter file',
    )

    sim_bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'gazebo_bringup.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'world': world,
            'urdf_path': urdf_path,
        }.items(),
    )

    slam_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'slam.launch.py')
        ),
        launch_arguments={'use_sim_time': 'true'}.items(),
    )

    navigation_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_launch_dir, 'navigation.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'params_file': nav2_params_file,
        }.items(),
    )

    ld = LaunchDescription()
    ld.add_action(declare_world)
    ld.add_action(declare_urdf)
    ld.add_action(declare_nav2_params)
    ld.add_action(sim_bringup)
    ld.add_action(slam_cmd)
    # Let slam_toolbox publish a stable map before Nav2 global_costmap subscribes.
    ld.add_action(TimerAction(period=8.0, actions=[navigation_cmd]))

    return ld
