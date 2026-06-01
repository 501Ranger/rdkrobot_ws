import time
import math
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from rclpy.action import ActionClient
from std_msgs.msg import String, Bool
from geometry_msgs.msg import PoseArray, Pose, Twist, PoseWithCovarianceStamped
from std_srvs.srv import Trigger
from sensor_msgs.msg import BatteryState
from nav_msgs.msg import Odometry, Path
from nav2_msgs.srv import LoadMap, ManageLifecycleNodes
from nav2_msgs.action import NavigateToPose, ComputePathToPose
from lifecycle_msgs.srv import ChangeState
from std_msgs.msg import Header

from .models import WaypointPayload

# 全局 ROS 2 节点对象
ros_node = None

class RobotApiNode(Node):
    def __init__(self):
        super().__init__("robot_api_node")

        # 自适应设置 use_sim_time 以防止仿真环境下导航时间戳校验失效
        try:
            if not self.has_parameter('use_sim_time'):
                self.declare_parameter('use_sim_time', False)
            
            use_sim_time_val = self.get_parameter('use_sim_time').value
            
            if not use_sim_time_val:
                topic_names = [name for name, _ in self.get_topic_names_and_types()]
                if "/clock" in topic_names:
                    use_sim_time_val = True
                    self.set_parameters([
                        rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)
                    ])
                    self.get_logger().info("Auto-detected /clock topic: upgraded use_sim_time to True")
                else:
                    self.get_logger().info("No /clock topic detected: keeping use_sim_time as False")
            else:
                self.get_logger().info("use_sim_time is already set to True by external configuration")
        except Exception as e:
            self.get_logger().warn(f"Failed to auto-detect use_sim_time: {e}")

        # 配置 Transient Local QoS 订阅状态
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)

        # 发布者
        self.patrol_cmd_pub = self.create_publisher(String, "/patrol/cmd", 10)
        self.waypoints_pub = self.create_publisher(PoseArray, "/patrol/set_waypoints", 10)
        self.cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        # AMCL 初始位姿发布者（Transient Local 保证 AMCL 节点即使稍后上线也能收到）
        self.initialpose_pub = self.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", 
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        )

        # 订阅者
        self.battery_sub = self.create_subscription(
            BatteryState, "/battery_state", self.battery_callback, 10
        )
        self.odom_sub = self.create_subscription(
            Odometry, "/odom", self.odom_callback, 10
        )
        self.amcl_pose_sub = self.create_subscription(
            PoseWithCovarianceStamped, "/amcl_pose", self.amcl_pose_callback, 10
        )
        self.localize_status_sub = self.create_subscription(
            Bool, "/auto_localize/status", self.localize_status_callback, qos
        )
        self.nav2_path_sub = self.create_subscription(
            Path, "/plan", self.nav2_path_callback, 10
        )
        self.patrol_feedback_sub = self.create_subscription(
            String, "/patrol/feedback", self.patrol_feedback_callback, 10
        )

        # 服务客户端
        self.localize_cli = self.create_client(Trigger, "/trigger_auto_localize")
        self.load_map_cli = self.create_client(LoadMap, "/map_server/load_map")

        # 导航 Action 客户端
        self.nav_action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.compute_path_client = ActionClient(self, ComputePathToPose, 'compute_path_to_pose')

        # 内部缓存状态
        self.battery_pct = 0.0
        self.robot_pose = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        self.is_localizing = False
        self.nav2_path = []
        
        # 导航相关变量
        self.current_nav_goal_handle = None
        self.latest_goal_id = 0
        self.nav_status = "idle"  # "idle", "navigating", "reached", "failed", "canceled"

        # 下位机在线检测时间戳与定位更新时间戳
        self.last_battery_time = 0.0
        self.last_odom_time = 0.0
        self.last_amcl_time = 0.0

    def battery_callback(self, msg: BatteryState):
        self.battery_pct = msg.percentage * 100.0 if msg.percentage <= 1.0 else msg.percentage
        self.last_battery_time = time.time()

    def odom_callback(self, msg: Odometry):
        self.last_odom_time = time.time()
        
        # 仅在最近 1.0 秒内无 AMCL 定位数据时，才回退使用里程计（例如 SLAM 建图或未定位状态下）
        if time.time() - self.last_amcl_time > 1.0:
            pos = msg.pose.pose.position
            ori = msg.pose.pose.orientation
            
            # 四元数转 yaw
            siny_cosp = 2.0 * (ori.w * ori.z + ori.x * ori.y)
            cosy_cosp = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
            yaw = math.atan2(siny_cosp, cosy_cosp)
            
            self.robot_pose = {
                "x": pos.x,
                "y": pos.y,
                "yaw": yaw
            }

    def amcl_pose_callback(self, msg: PoseWithCovarianceStamped):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        
        # 四元数转 yaw
        siny_cosp = 2.0 * (ori.w * ori.z + ori.x * ori.y)
        cosy_cosp = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        
        self.robot_pose = {
            "x": pos.x,
            "y": pos.y,
            "yaw": yaw
        }
        self.last_amcl_time = time.time()

    def localize_status_callback(self, msg: Bool):
        self.is_localizing = msg.data

    def patrol_feedback_callback(self, msg: String):
        data_str = msg.data
        self.get_logger().info(f"Received patrol feedback: '{data_str}'")
        from . import manager as m
        if data_str.startswith("reached_"):
            try:
                idx = int(data_str.split("_")[1])
                m.waypoint_reached_index = idx
            except Exception as e:
                self.get_logger().error(f"Failed to parse waypoint index from feedback '{data_str}': {e}")
        elif data_str == "completed":
            m.patrol_completed_triggered = True

    def nav2_path_callback(self, msg: Path):
        poses = msg.poses
        total_points = len(poses)
        max_points = 150
        step = max(1, total_points // max_points)
        
        path_pts = []
        for i in range(0, total_points, step):
            pos = poses[i].pose.position
            path_pts.append({
                "x": round(pos.x, 3),
                "y": round(pos.y, 3)
            })
        self.nav2_path = path_pts

    def change_lifecycle_state(self, node_name: str, transition_id: int) -> bool:
        """调用 ROS 2 Lifecycle 服务更改节点运行状态"""
        srv_name = f"/{node_name}/change_state"
        client = self.create_client(ChangeState, srv_name)
        
        self.get_logger().info(f"Waiting for lifecycle service: {srv_name}...")
        if not client.wait_for_service(timeout_sec=2.0):
            self.get_logger().error(f"Lifecycle service {srv_name} not available.")
            return False
            
        req = ChangeState.Request()
        req.transition.id = transition_id
        
        self.get_logger().info(f"Calling change_state on {node_name} with transition id {transition_id}...")
        future = client.call_async(req)
        
        # 阻塞等待结果
        start_time = time.time()
        timeout = 4.0
        while not future.done():
            time.sleep(0.1)
            if time.time() - start_time > timeout:
                self.get_logger().error(f"Timeout waiting for {node_name} state transition.")
                return False
                
        res = future.result()
        if res and res.success:
            self.get_logger().info(f"Successfully transitioned {node_name} state.")
            return True
        else:
            self.get_logger().error(f"Failed to transition {node_name} state.")
            return False

    def change_localization_manager_state(self, command_id: int) -> bool:
        """调用 lifecycle_manager_localization 服务的 manage_nodes 来暂停/恢复/重置定位节点"""
        srv_name = "/lifecycle_manager_localization/manage_nodes"
        client = self.create_client(ManageLifecycleNodes, srv_name)
        
        self.get_logger().info(f"Waiting for localization manager service: {srv_name}...")
        if not client.wait_for_service(timeout_sec=2.0):
            self.get_logger().error(f"Localization manager service {srv_name} not available.")
            return False
            
        req = ManageLifecycleNodes.Request()
        req.command = command_id
        
        self.get_logger().info(f"Calling manage_nodes with command {command_id}...")
        future = client.call_async(req)
        
        # 阻塞等待结果
        start_time = time.time()
        timeout = 4.0
        while not future.done():
            time.sleep(0.1)
            if time.time() - start_time > timeout:
                self.get_logger().error(f"Timeout waiting for localization manager state change.")
                return False
                
        res = future.result()
        if res and res.success:
            self.get_logger().info(f"Successfully changed localization manager state.")
            return True
        else:
            self.get_logger().error(f"Failed to change localization manager state.")
            return False

    def publish_initial_pose(self, x: float = 0.0, y: float = 0.0, yaw: float = 0.0):
        """
        向 /initialpose 发布位姿，使 AMCL 开始发布 map->odom TF 变换。
        默认以地图原点 (0, 0, 0) 作为初始猜测值，用户可在实际场景中重定位修正。
        """
        msg = PoseWithCovarianceStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        # 较大协方差，表明初始位姿不确定性高，AMCL 会在整个地图范围内搜索粒子
        msg.pose.covariance[0]  = 0.5   # x 方差
        msg.pose.covariance[7]  = 0.5   # y 方差
        msg.pose.covariance[35] = 0.3   # yaw 方差
        self.initialpose_pub.publish(msg)
        self.get_logger().info(f"Published initial pose to AMCL: x={x:.2f}, y={y:.2f}, yaw={yaw:.2f}")

    def publish_patrol_cmd(self, cmd: str):
        msg = String()
        msg.data = cmd
        self.patrol_cmd_pub.publish(msg)
        self.get_logger().info(f"Published patrol command: '{cmd}'")

    def publish_waypoints(self, wps: list):
        msg = PoseArray()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()

        for wp in wps:
            pose = Pose()
            pose.position.x = wp.x
            pose.position.y = wp.y
            pose.position.z = 0.0
            # yaw 转四元数
            pose.orientation.z = math.sin(wp.yaw / 2.0)
            pose.orientation.w = math.cos(wp.yaw / 2.0)
            msg.poses.append(pose)

        self.waypoints_pub.publish(msg)
        self.get_logger().info(f"Published {len(wps)} waypoints dynamically.")

    # 导航控制逻辑
    def send_navigation_goal(self, x, y, yaw):
        if not self.nav_action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("NavigateToPose action server not available!")
            self.nav_status = "failed"
            return False

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        self.latest_goal_id += 1
        goal_id = self.latest_goal_id
        self.nav_status = "navigating"
        self.get_logger().info(f"Sending navigation goal to Action Server (Goal ID: {goal_id}): x={x:.2f}, y={y:.2f}, yaw={yaw:.2f}")

        send_goal_future = self.nav_action_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(
            lambda fut, gid=goal_id: self.nav_goal_response_callback(fut, gid)
        )
        return True

    def nav_goal_response_callback(self, future, goal_id):
        if goal_id != self.latest_goal_id:
            self.get_logger().info(f"Goal response for an outdated request {goal_id} (latest is {self.latest_goal_id}). Ignoring.")
            return

        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().info("Navigation goal rejected by Action Server.")
            self.nav_status = "failed"
            return

        self.get_logger().info("Navigation goal accepted by Action Server.")
        self.current_nav_goal_handle = goal_handle

        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(
            lambda fut, gid=goal_id, gh=goal_handle: self.nav_result_callback(fut, gid, gh)
        )

    def nav_result_callback(self, future, goal_id, goal_handle):
        if goal_id != self.latest_goal_id or goal_handle != self.current_nav_goal_handle:
            self.get_logger().info(f"Received result for an inactive/superseded goal {goal_id}. Ignoring.")
            return

        result = future.result()
        status = result.status
        self.get_logger().info(f"Navigation completed with Action status code: {status} for Goal ID: {goal_id}")

        if status == 4:
            self.nav_status = "reached"
        elif status == 5:
            self.nav_status = "canceled"
        else:
            self.nav_status = "failed"

        self.nav2_path = []
        self.current_nav_goal_handle = None

    def cancel_navigation_goal(self):
        if self.current_nav_goal_handle:
            self.get_logger().info("Canceling current active navigation goal...")
            self.current_nav_goal_handle.cancel_goal_async()
            self.nav2_path = []
            return True
        return False

    def publish_cmd_vel(self, linear_x: float, angular_z: float):
        msg = Twist()
        msg.linear.x = linear_x
        msg.angular.z = angular_z
        self.cmd_vel_pub.publish(msg)
