import time
import math
import threading
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from rclpy.action import ActionClient
from std_msgs.msg import String, Bool
from geometry_msgs.msg import PoseArray, Pose, Twist, PoseWithCovarianceStamped
from std_srvs.srv import Trigger
from sensor_msgs.msg import BatteryState, Joy
from nav_msgs.msg import Odometry, Path, OccupancyGrid
from nav2_msgs.srv import LoadMap, ManageLifecycleNodes
from nav2_msgs.action import NavigateToPose, ComputePathToPose
from lifecycle_msgs.srv import ChangeState
from std_msgs.msg import Header

from .models import WaypointPayload
from concurrent.futures import ThreadPoolExecutor

# 全局 ROS 2 节点对象
ros_node = None

def quaternion_to_yaw(ori) -> float:
    """将 geometry_msgs/Quaternion 四元数转换为 Yaw 偏航角(弧度)"""
    siny_cosp = 2.0 * (ori.w * ori.z + ori.x * ori.y)
    cosy_cosp = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
    return math.atan2(siny_cosp, cosy_cosp)

from .log_manager import LogManager

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
        # 语音相关发布者
        self.voice_api_command_pub = self.create_publisher(String, "/voice/api_command_text", 10)
        self.voice_reply_pub = self.create_publisher(String, "/assistant/reply_text", 10)
        self.voice_source_sim_pub = self.create_publisher(String, "/voice/source_event_sim", 10)
        self.voice_record_cmd_pub = self.create_publisher(String, "/voice/record_place_cmd", 10)

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
        # 语音相关订阅者
        self.voice_command_sub = self.create_subscription(
            String, "/voice/command_text", self.voice_command_callback, 10
        )
        self.voice_api_command_sub = self.create_subscription(
            String, "/voice/api_command_text", self.voice_api_command_callback, 10
        )
        self.voice_reply_sub = self.create_subscription(
            String, "/assistant/reply_text", self.voice_reply_callback, 10
        )
        self.voice_source_sub = self.create_subscription(
            String, "/voice/source_event", self.voice_source_callback, 10
        )
        self.patrol_feedback_sub = self.create_subscription(
            String, "/patrol/feedback", self.patrol_feedback_callback, 10
        )
        
        # 主机手柄订阅与标志位（包含上线 10 帧抑制防抖及单次解锁状态）
        self._joy_actively_controlling = False
        self._joy_unlocked = True
        self._last_joy_time = 0.0
        self._joy_suppress_frames = 0
        self.joy_sub = self.create_subscription(
            Joy, "/joy", self.joy_callback, 10
        )

        # 服务客户端
        self.localize_cli = self.create_client(Trigger, "/trigger_auto_localize")
        self.load_map_cli = self.create_client(LoadMap, "/map_server/load_map")

        # 导航 Action 客户端
        self.nav_action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.compute_path_client = ActionClient(self, ComputePathToPose, 'compute_path_to_pose')

        # 内部缓存状态
        self._lock = threading.Lock()
        self.battery_pct = 0.0
        self.robot_pose = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        self.is_localizing = False
        self.nav2_path = []
        self.map_sub = None
        self.realtime_map_data = None

        # 语音相关缓存状态
        self.latest_command_text = ""
        self.latest_command_source = ""
        self.latest_tts_text = ""
        self.latest_source_angle = 0.0
        self.latest_source_confidence = 0.0
        self.latest_voice_update_time = 0.0
        
        # 导航相关变量
        self.current_nav_goal_handle = None
        self.latest_goal_id = 0
        self.nav_status = "idle"  # "idle", "navigating", "reached", "failed", "canceled"

        # 下位机在线检测时间戳与定位更新时间戳
        self.last_battery_time = 0.0
        self.last_odom_time = 0.0
        self.last_amcl_time = 0.0

        # 地图处理防抖与独立线程池
        self.last_map_process_time = 0.0
        self.map_thread_pool = ThreadPoolExecutor(max_workers=1)

        # 导航与巡逻日志累计变量
        self._current_task_log = None
        self._last_log_pose = None

    def get_robot_status_data(self) -> dict:
        with self._lock:
            return {
                "battery_percentage": round(self.battery_pct, 1),
                "pose": dict(self.robot_pose),
                "is_localizing": self.is_localizing,
                "nav_status": self.nav_status,
                "nav2_path": list(self.nav2_path),
                "last_battery_time": self.last_battery_time,
                "last_odom_time": self.last_odom_time,
                "last_amcl_time": self.last_amcl_time,
                "realtime_map": self.realtime_map_data,
                "joy_unlocked": self._joy_unlocked,
                "voice_status": {
                    "latest_command_text": self.latest_command_text,
                    "latest_command_source": self.latest_command_source,
                    "latest_tts_text": self.latest_tts_text,
                    "source_angle": self.latest_source_angle,
                    "source_confidence": self.latest_source_confidence,
                    "updated_at": self.latest_voice_update_time
                }
            }

    def battery_callback(self, msg: BatteryState):
        with self._lock:
            self.battery_pct = msg.percentage * 100.0 if msg.percentage <= 1.0 else msg.percentage
            self.last_battery_time = time.time()

    def odom_callback(self, msg: Odometry):
        with self._lock:
            self.last_odom_time = time.time()
            
            # 仅在最近 1.0 秒内无 AMCL 定位数据时，才回退使用里程计（例如 SLAM 建图或未定位状态下）
            if time.time() - self.last_amcl_time > 1.0:
                pos = msg.pose.pose.position
                ori = msg.pose.pose.orientation
                yaw = quaternion_to_yaw(ori)
                
                self.robot_pose = {
                    "x": pos.x,
                    "y": pos.y,
                    "yaw": yaw
                }
                self._accumulate_distance()

    def amcl_pose_callback(self, msg: PoseWithCovarianceStamped):
        with self._lock:
            pos = msg.pose.pose.position
            ori = msg.pose.pose.orientation
            yaw = quaternion_to_yaw(ori)
            
            self.robot_pose = {
                "x": pos.x,
                "y": pos.y,
                "yaw": yaw
            }
            self.last_amcl_time = time.time()
            self._accumulate_distance()

    def _accumulate_distance(self):
        """内部累计里程估算，应在 lock 锁保护下调用"""
        if self._current_task_log:
            current_pos = self.robot_pose
            if self._last_log_pose:
                dx = current_pos["x"] - self._last_log_pose["x"]
                dy = current_pos["y"] - self._last_log_pose["y"]
                dist = math.sqrt(dx*dx + dy*dy)
                if dist > 0.02:  # 门限过滤
                    self._current_task_log["distance"] += dist
                    self._last_log_pose = dict(current_pos)
            else:
                self._last_log_pose = dict(current_pos)

    def localize_status_callback(self, msg: Bool):
        with self._lock:
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
            with self._lock:
                if self._current_task_log and self._current_task_log["type"] == "patrol":
                    duration = time.time() - self._current_task_log["start_time"]
                    distance = self._current_task_log["distance"]
                    start_pose = self._current_task_log["start_pose"]
                    end_pose = dict(self.robot_pose)
                    threading.Thread(
                        target=LogManager.add_log,
                        args=("patrol", "reached", duration, distance, start_pose, end_pose),
                        daemon=True
                    ).start()
                    self._current_task_log = None
                    self._last_log_pose = None
        elif data_str.startswith("interrupted_"):
            reason = "failed"
            try:
                reason = data_str.split("_")[1]
                m.patrol_interrupted_reason = reason
            except Exception as e:
                self.get_logger().error(f"Failed to parse interrupt reason from feedback '{data_str}': {e}")
            with self._lock:
                if self._current_task_log and self._current_task_log["type"] == "patrol":
                    duration = time.time() - self._current_task_log["start_time"]
                    distance = self._current_task_log["distance"]
                    start_pose = self._current_task_log["start_pose"]
                    end_pose = dict(self.robot_pose)
                    log_status = "canceled" if reason == "canceled" else "failed"
                    threading.Thread(
                        target=LogManager.add_log,
                        args=("patrol", log_status, duration, distance, start_pose, end_pose),
                        daemon=True
                    ).start()
                    self._current_task_log = None
                    self._last_log_pose = None

    def map_callback(self, msg: OccupancyGrid):
        # 1Hz 节流限制，避免高频占用
        current_time = time.time()
        if current_time - self.last_map_process_time < 1.0:
            return
        self.last_map_process_time = current_time
        
        # 提交到独立后台线程处理，避免阻塞 ROS spin 线程
        self.map_thread_pool.submit(self._process_map_async, msg)

    def _process_map_async(self, msg: OccupancyGrid):
        try:
            import numpy as np
            from PIL import Image
            import io
            import base64

            width = msg.info.width
            height = msg.info.height
            if width <= 0 or height <= 0:
                return

            data = np.array(msg.data, dtype=np.int8).reshape((height, width))
            rgba = np.zeros((height, width, 4), dtype=np.uint8)
            
            # 空闲 (0) -> 白色
            rgba[data == 0] = [255, 255, 255, 255]
            # 障碍 (100) -> 墨色 (18, 22, 37)
            rgba[data == 100] = [18, 22, 37, 255]
            # 未知 (-1) 保持透明

            # 翻转地图匹配左上角原点
            rgba = np.flipud(rgba)

            img = Image.fromarray(rgba, 'RGBA')
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')

            with self._lock:
                self.realtime_map_data = {
                    "width": width,
                    "height": height,
                    "resolution": msg.info.resolution,
                    "origin": [msg.info.origin.position.x, msg.info.origin.position.y],
                    "image_base64": img_str
                }
        except Exception as e:
            self.get_logger().error(f"Failed to process live SLAM map asynchronously: {e}")

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
        with self._lock:
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

        if cmd in ["start", "start_once"]:
            with self._lock:
                self._current_task_log = {
                    "type": "patrol",
                    "start_time": time.time(),
                    "distance": 0.0,
                    "start_pose": dict(self.robot_pose)
                }
                self._last_log_pose = dict(self.robot_pose)
        elif cmd == "stop":
            with self._lock:
                if self._current_task_log and self._current_task_log["type"] == "patrol":
                    duration = time.time() - self._current_task_log["start_time"]
                    distance = self._current_task_log["distance"]
                    start_pose = self._current_task_log["start_pose"]
                    end_pose = dict(self.robot_pose)
                    threading.Thread(
                        target=LogManager.add_log,
                        args=("patrol", "canceled", duration, distance, start_pose, end_pose),
                        daemon=True
                    ).start()
                    self._current_task_log = None
                    self._last_log_pose = None

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
            with self._lock:
                self.nav_status = "failed"
            return False

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        with self._lock:
            self._current_task_log = {
                "type": "single",
                "start_time": time.time(),
                "distance": 0.0,
                "start_pose": dict(self.robot_pose)
            }
            self._last_log_pose = dict(self.robot_pose)
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
        with self._lock:
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
        with self._lock:
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

            if self._current_task_log and self._current_task_log["type"] == "single":
                duration = time.time() - self._current_task_log["start_time"]
                distance = self._current_task_log["distance"]
                start_pose = self._current_task_log["start_pose"]
                end_pose = dict(self.robot_pose)
                threading.Thread(
                    target=LogManager.add_log,
                    args=("single", self.nav_status, duration, distance, start_pose, end_pose),
                    daemon=True
                ).start()
                self._current_task_log = None
                self._last_log_pose = None

            self.nav2_path = []
            self.current_nav_goal_handle = None

    def cancel_navigation_goal(self):
        with self._lock:
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

    def joy_callback(self, msg: Joy):
        """主机手柄输入回调函数"""
        # 边界与安全校验：确保 axes 数组长度足够，防止溢出挂死
        if len(msg.axes) < 4:
            return
            
        current_time = time.time()
        # 检查两次接收时间差。如果大于 10.0 秒，判断为断连重连、长时间空闲或首次上线，启动静默过滤
        if current_time - self._last_joy_time > 10.0:
            self._joy_suppress_frames = 10  # 抑制刚上线的 10 帧数据（约 0.2 秒），待手柄自检校准完毕
            self.get_logger().info("Host gamepad connected/reconnected! Activating 10-frame suppression.")
            
        self._last_joy_time = current_time
        
        # 处于静默抑制状态，直接忽略前几帧异常脉冲
        if getattr(self, "_joy_suppress_frames", 0) > 0:
            self._joy_suppress_frames -= 1
            self._joy_actively_controlling = False
            return
        
        # 左摇杆 Y 轴 (axes[1]) 控制前后运动，最大线速度限流 0.45 m/s
        joy_linear = msg.axes[1]
        
        # 右摇杆 X 轴 (axes[3]) 优先控制旋转，若接近中位则使用左摇杆 X 轴 (axes[0]) 控制，最大角速度 2.00 rad/s
        joy_angular = msg.axes[3] if abs(msg.axes[3]) > 0.05 else msg.axes[0]
        
        # 摇杆死区过滤（过滤物理漂移，设为 0.15）
        deadzone = 0.15
        if abs(joy_linear) < deadzone:
            joy_linear = 0.0
        if abs(joy_angular) < deadzone:
            joy_angular = 0.0
            
        linear_x = joy_linear * 0.45
        angular_z = joy_angular * 2.00
        
        # 如果有手柄推轴指令输入
        if linear_x != 0.0 or angular_z != 0.0:
            self.publish_cmd_vel(linear_x, angular_z)
            self._joy_actively_controlling = True
        else:
            # 当手柄摇杆回归中位（零输入），若之前处于遥控状态，则发送一次零速刹车指令，然后解除控制状态，防止干扰其他节点
            if getattr(self, "_joy_actively_controlling", False):
                self.publish_cmd_vel(0.0, 0.0)
                self._joy_actively_controlling = False

    # 语音相关回调与接口方法
    def voice_command_callback(self, msg: String):
        with self._lock:
            self.latest_command_text = msg.data
            self.latest_command_source = "stt"
            self.latest_voice_update_time = time.time()

    def voice_api_command_callback(self, msg: String):
        with self._lock:
            self.latest_command_text = msg.data
            self.latest_command_source = "api"
            self.latest_voice_update_time = time.time()

    def voice_reply_callback(self, msg: String):
        with self._lock:
            self.latest_tts_text = msg.data
            self.latest_voice_update_time = time.time()

    def voice_source_callback(self, msg: String):
        import json
        try:
            data = json.loads(msg.data)
            with self._lock:
                self.latest_source_angle = float(data.get("angle_deg", 0.0))
                self.latest_source_confidence = float(data.get("confidence", 1.0))
                self.latest_voice_update_time = time.time()
        except Exception:
            pass

    def publish_voice_api_command(self, text: str):
        msg = String()
        msg.data = text
        self.voice_api_command_pub.publish(msg)
        self.get_logger().info(f"Published voice API command: '{text}'")

    def publish_voice_reply(self, text: str):
        msg = String()
        msg.data = text
        self.voice_reply_pub.publish(msg)
        self.get_logger().info(f"Published voice reply (TTS): '{text}'")

    def publish_voice_source_sim(self, angle: float, confidence: float):
        import json
        payload = json.dumps({"angle_deg": angle, "confidence": confidence, "timestamp": time.time()})
        msg = String()
        msg.data = payload
        self.voice_source_sim_pub.publish(msg)
        self.get_logger().info(f"Published voice source simulation: '{payload}'")

    def publish_voice_record_cmd(self, name: str, x: float = None, y: float = None, yaw: float = None):
        import json
        payload_dict = {"name": name}
        if x is not None and y is not None and yaw is not None:
            payload_dict.update({"x": x, "y": y, "yaw": yaw})
        payload = json.dumps(payload_dict)
        msg = String()
        msg.data = payload
        self.voice_record_cmd_pub.publish(msg)
        self.get_logger().info(f"Published record place command: '{payload}'")

