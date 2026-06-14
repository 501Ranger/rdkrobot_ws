"""
sim_all_in_one.launch.py — 仿真全家桶一键启动脚本
功能：
  1. 启动 Gazebo 仿真小车（可选 SLAM 模式或 Map 导航模式）
  2. 启动 语音控制中心 + 大模型对话 (LLM) + Web 对话桥接服务
  3. 启动 HMI 网页控制舱后端 API 服务器

运行指令（建图模式，默认）：
  ros2 launch rdk_robot_bringup sim_all_in_one.launch.py mode:=slam

运行指令（导航模式，加载已有地图）：
  ros2 launch rdk_robot_bringup sim_all_in_one.launch.py mode:=nav map:=/home/linrain/rdkrobot_ws/maps/gazebo.yaml
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch.conditions import IfCondition
from launch_ros.actions import Node


def generate_launch_description():
    pkg_bringup = get_package_share_directory('rdk_robot_bringup')
    pkg_voice = get_package_share_directory('rdk_voice_assistant')
    pkg_api = get_package_share_directory('rdk_robot_api')
    
    tb3_gazebo_share = get_package_share_directory('turtlebot3_gazebo')

    # 获取参数
    mode = LaunchConfiguration('mode')
    map_file = LaunchConfiguration('map')
    world = LaunchConfiguration('world')
    urdf_path = LaunchConfiguration('urdf_path')
    nav2_params_file = LaunchConfiguration('nav2_params_file')

    # 声明启动参数
    declare_mode = DeclareLaunchArgument(
        'mode',
        default_value='slam',
        description='启动模式: slam (建图模式) 或 nav (载入静态地图导航模式)',
    )
    declare_map = DeclareLaunchArgument(
        'map',
        default_value='/home/linrain/rdkrobot_ws/maps/gazebo.yaml',
        description='导航模式下加载的地图 YAML 文件绝对路径',
    )
    declare_world = DeclareLaunchArgument(
        'world',
        default_value=os.path.join(tb3_gazebo_share, 'worlds', 'turtlebot3_world.world'),
        description='Gazebo world file',
    )
    declare_urdf = DeclareLaunchArgument(
        'urdf_path',
        default_value=os.path.join(pkg_bringup, 'urdf', 'rdk_robot_gazebo.urdf'),
        description='Gazebo URDF path',
    )
    declare_nav2_params = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=os.path.join(pkg_bringup, 'config', 'nav2_params.yaml'),
        description='Nav2 parameter file',
    )

    # ==================== 1. 底盘与导航组件定义 ====================

    # [建图模式]：一键启动 仿真世界 + SLAM 建图 + 无 MapServer 导航
    sim_slam_nav_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'sim_slam_nav.launch.py')
        ),
        launch_arguments={
            'world': world,
            'urdf_path': urdf_path,
            'nav2_params_file': nav2_params_file,
        }.items(),
        condition=IfCondition(PythonExpression(["'", mode, "' == 'slam'"]))
    )

    # [导航模式]：仅仅启动 Gazebo 仿真世界与机器人描述
    sim_only_bringup_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'gazebo_bringup.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'world': world,
            'urdf_path': urdf_path,
        }.items(),
        condition=IfCondition(PythonExpression(["'", mode, "' == 'nav'"]))
    )

    # [导航模式]：加载定位与导航节点 (包含 map_server 载入静态地图 + AMCL)
    localization_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'localization.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'map': map_file,
            'params_file': nav2_params_file,
        }.items(),
        condition=IfCondition(PythonExpression(["'", mode, "' == 'nav'"]))
    )

    # ==================== 2. 语音控制与大模型服务 ====================
    voice_assistant_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_voice, 'launch', 'local_voice.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'enable_navigation': 'true',
        }.items(),
    )

    # ==================== 3. 网页 HMI 后端 API 服务器 ====================
    api_server_node = Node(
        package='rdk_robot_api',
        executable='api_server',
        name='api_server_node',
        output='screen',
        parameters=[{'use_sim_time': True}]
    )

    # ==================== 4. 组装 LaunchDescription ====================
    ld = LaunchDescription()
    
    # 添加声明参数
    ld.add_action(declare_mode)
    ld.add_action(declare_map)
    ld.add_action(declare_world)
    ld.add_action(declare_urdf)
    ld.add_action(declare_nav2_params)
    
    # 启动基本环境
    ld.add_action(sim_slam_nav_cmd)  # 仅在 mode:=slam 时生效
    ld.add_action(sim_only_bringup_cmd)  # 仅在 mode:=nav 时生效
    ld.add_action(api_server_node)  # 网页 API 服务器始终启动
    
    # 延迟 4.0 秒启动定位服务 (仅在 mode:=nav 时生效，保证 Gazebo 充分就绪)
    ld.add_action(TimerAction(period=4.0, actions=[localization_cmd]))
    
    # 延迟 7.0 秒启动语音服务 (等待 TF 树和定位服务稳定)
    ld.add_action(TimerAction(period=7.0, actions=[voice_assistant_cmd]))

    return ld
