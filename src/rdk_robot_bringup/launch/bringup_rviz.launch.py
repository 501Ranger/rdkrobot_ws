import os
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    package_name = 'rdk_robot_bringup'

    # 获取 URDF 文件路径
    urdf_file = os.path.join(get_package_share_directory(package_name), 'urdf', 'rdk_robot.urdf')
    with open(urdf_file, 'r') as infp:
        robot_desc = infp.read()

    # 1. Odom to TF Broadcaster (odom -> base_footprint)
    # 注意：我把子坐标系改成了 base_footprint，这样整个机器人模型都能跟着动
    odom_tf_node = Node(
        package=package_name,
        executable='odom_tf_broadcaster',
        name='odom_tf_broadcaster',
        parameters=[{'child_frame_id': 'base_footprint'}] # 我们可以传参，或者直接在代码里改
    )

    # 2. Robot State Publisher (发布 URDF 结构到 TF)
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_desc}]
    )

    # 3. Joint State Publisher (发布轮子等关节状态)
    joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher'
    )

    # 4. RViz2
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen'
    )

    return LaunchDescription([
        robot_state_publisher_node,
        joint_state_publisher_node,
        odom_tf_node,
        rviz_node,
    ])
