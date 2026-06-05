import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    package_name = 'rdk_robot_bringup'
    pkg_share = get_package_share_directory(package_name)

    use_sim_time = LaunchConfiguration('use_sim_time')
    rviz_config = LaunchConfiguration('rviz_config')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation clock',
    )
    declare_rviz_config = DeclareLaunchArgument(
        'rviz_config',
        default_value=os.path.join(pkg_share, 'config', 'slam_view.rviz'),
        description='RViz2 configuration file',
    )

    # 获取 URDF 文件路径
    urdf_file = os.path.join(pkg_share, 'urdf', 'rdk_robot.urdf')
    with open(urdf_file, 'r') as infp:
        robot_desc = infp.read()

    # 1. Odom to TF Broadcaster (odom -> base_footprint)
    odom_tf_node = Node(
        package='rdk_robot_core',
        executable='odom_tf_broadcaster',
        name='odom_tf_broadcaster',
        parameters=[{
            'child_frame_id': 'base_footprint',
            'use_sim_time': use_sim_time,
        }]
    )

    # 2. Robot State Publisher (发布 URDF 结构到 TF)
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_desc,
            'use_sim_time': use_sim_time,
        }]
    )

    # 3. Joint State Publisher (发布轮子等关节状态)
    joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        parameters=[{'use_sim_time': use_sim_time}]
    )

    # 4. RViz2（加载预置配置文件，包含 Map/LaserScan/RobotModel/Odometry 显示）
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config],
        parameters=[{'use_sim_time': use_sim_time}]
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_rviz_config,
        robot_state_publisher_node,
        joint_state_publisher_node,
        odom_tf_node,
        rviz_node,
    ])

