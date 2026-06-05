import json
import math
import os
import time
import threading
from typing import Dict, Optional

import rclpy
import tf2_ros
import yaml
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String

from rdk_voice_assistant.intent_parser import DEFAULT_PLACE_ALIASES, Intent, parse_intent


class VoiceAssistantNode(Node):
    """Bridge text or ASR results into robot task interfaces."""

    def __init__(self) -> None:
        super().__init__('voice_assistant_node')

        self.declare_parameter('command_text_topic', '/voice/command_text')
        self.declare_parameter('intent_topic', '/voice/intent')
        self.declare_parameter('reply_text_topic', '/assistant/reply_text')
        self.declare_parameter('robot_task_topic', '/voice/robot_task')
        self.declare_parameter('safety_command_topic', '/voice/safety_command')
        self.declare_parameter('navigate_action_name', '/navigate_to_pose')
        self.declare_parameter('enable_navigation', False)
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('places_file', '')
        self.declare_parameter('chat_fallback_reply', True)
        self.declare_parameter('base_frame', 'base_link')

        self.command_text_topic = self.get_parameter(
            'command_text_topic').get_parameter_value().string_value
        self.intent_topic = self.get_parameter(
            'intent_topic').get_parameter_value().string_value
        self.reply_text_topic = self.get_parameter(
            'reply_text_topic').get_parameter_value().string_value
        self.robot_task_topic = self.get_parameter(
            'robot_task_topic').get_parameter_value().string_value
        self.safety_command_topic = self.get_parameter(
            'safety_command_topic').get_parameter_value().string_value
        self.navigate_action_name = self.get_parameter(
            'navigate_action_name').get_parameter_value().string_value
        self.enable_navigation = self.get_parameter(
            'enable_navigation').get_parameter_value().bool_value
        self.chat_fallback_reply = self.get_parameter(
            'chat_fallback_reply').get_parameter_value().bool_value
        self.map_frame = self.get_parameter(
            'map_frame').get_parameter_value().string_value
        self.base_frame = self.get_parameter(
            'base_frame').get_parameter_value().string_value

        self.places = self._load_places()
        self.place_aliases = self._build_place_aliases()

        self.intent_pub = self.create_publisher(String, self.intent_topic, 10)
        self.reply_pub = self.create_publisher(String, self.reply_text_topic, 10)
        self.robot_task_pub = self.create_publisher(String, self.robot_task_topic, 10)
        self.safety_pub = self.create_publisher(String, self.safety_command_topic, 10)
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.nav_client = ActionClient(self, NavigateToPose, self.navigate_action_name)

        # Cache variables for Sound Source Localization
        self.last_source_angle: Optional[float] = None
        self.last_source_confidence: Optional[float] = None
        self.last_source_time: float = 0.0
        self.current_yaw: float = 0.0
        self.last_odom_pose: Optional[object] = None

        # Cache variables for Lidar scan and cooperative movement cancellation
        self.last_scan: Optional[LaserScan] = None
        self.last_scan_time: float = 0.0
        self.current_movement_id: int = 0

        # TF Listener
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.create_subscription(
            LaserScan,
            '/scan',
            self._on_scan,
            10,
        )

        self.create_subscription(
            String,
            self.command_text_topic,
            self._on_command_text,
            10,
        )

        self.create_subscription(
            String,
            '/voice/api_command_text',
            self._on_command_text,
            10,
        )

        self.create_subscription(
            String,
            '/voice/source_event',
            self._on_source_event,
            10,
        )

        self.create_subscription(
            String,
            '/voice/source_event_sim',
            self._on_source_event,
            10,
        )

        self.create_subscription(
            Odometry,
            '/odom',
            self._on_odom,
            10,
        )

        self.create_subscription(
            String,
            '/voice/record_place_cmd',
            self._on_record_place_cmd,
            10,
        )

        self.get_logger().info(
            f'Voice assistant ready. Send text to {self.command_text_topic}. '
            f'Navigation enabled: {self.enable_navigation}'
        )

    def _on_command_text(self, msg: String) -> None:
        text = msg.data.strip()
        intent = parse_intent(text, self.place_aliases)
        self._publish_intent(intent)

        if intent.name == 'go_to':
            self._handle_go_to(intent)
        elif intent.name == 'start_patrol':
            self._publish_task({'task': 'start_patrol', 'source': 'voice'})
            self._say('好的，我开始巡查。')
        elif intent.name == 'look_at_sound':
            self._handle_look_at_sound()
        elif intent.name == 'sound_localization':
            self._handle_sound_localization()
        elif intent.name == 'come_here':
            self._handle_come_here()
        elif intent.name == 'record_place':
            self._handle_record_place(intent)
        elif intent.name == 'stop':
            self.current_movement_id += 1
            stop_twist = Twist()
            self.cmd_vel_pub.publish(stop_twist)
            self._publish_safety_command('stop')
            self._say('好的，我已经发送停止指令。')
        elif intent.name == 'status':
            self._publish_task({'task': 'report_status', 'source': 'voice'})
            self._say('我正在查询当前状态。')
        elif intent.name == 'empty':
            self._say('我没有听清楚，请再说一遍。')
        else:
            self._publish_task({
                'task': 'chat',
                'source': 'voice',
                'text': intent.raw_text,
            })
            if self.chat_fallback_reply:
                self._say('这个问题我先记录下来，后面可以接入大模型来回答。')

    def _handle_go_to(self, intent: Intent) -> None:
        place = intent.place
        if not place:
            self._say('我还不知道要去哪里。')
            return

        place_info = self.places.get(place)
        if not place_info:
            self._publish_task({
                'task': 'go_to',
                'source': 'voice',
                'place': place,
                'status': 'missing_place_config',
            })
            self._say(f'我识别到了地点 {place}，但还没有配置它的坐标。')
            return

        self._publish_task({
            'task': 'go_to',
            'source': 'voice',
            'place': place,
            'target': place_info,
        })

        display_name = place_info.get('name', place)
        if not self.enable_navigation:
            self._say(
                f'好的，我识别到要去{display_name}。'
                '导航接口已经预留，当前还没有真正发送目标点。'
            )
            return

        self._send_nav_goal(place, place_info)
        self._say(f'好的，我正在前往{display_name}。')

    def _send_nav_goal(self, place: str, place_info: Dict[str, float]) -> None:
        if not self.nav_client.wait_for_server(timeout_sec=1.0):
            self.get_logger().warn(f'Nav2 action server not available: {self.navigate_action_name}')
            self._say('导航服务暂时不可用。')
            return

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = self._make_pose(place_info)
        self.nav_client.send_goal_async(goal_msg)
        self.get_logger().info(f'Sent navigation goal for {place}: {place_info}')

    def _make_pose(self, place_info: Dict[str, float]) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = self.map_frame
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = float(place_info.get('x', 0.0))
        pose.pose.position.y = float(place_info.get('y', 0.0))
        pose.pose.position.z = 0.0

        yaw = float(place_info.get('yaw', 0.0))
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def _load_places(self) -> Dict[str, Dict[str, float]]:
        places_file = self.get_parameter('places_file').get_parameter_value().string_value
        if not places_file:
            return {}

        if not os.path.exists(places_file):
            self.get_logger().warn(f'Places file not found: {places_file}')
            return {}

        with open(places_file, 'r', encoding='utf-8') as file:
            data = yaml.safe_load(file) or {}

        places = data.get('places', {})
        if not isinstance(places, dict):
            self.get_logger().warn('Invalid places.yaml: "places" must be a mapping.')
            return {}

        return places

    def _build_place_aliases(self) -> Dict[str, str]:
        aliases = dict(DEFAULT_PLACE_ALIASES)
        for place_id, place_info in self.places.items():
            name = place_info.get('name')
            if name:
                aliases[str(name)] = str(place_id)
            for alias in place_info.get('aliases', []):
                aliases[str(alias)] = str(place_id)
        return aliases

    def _publish_intent(self, intent: Intent) -> None:
        payload = {
            'intent': intent.name,
            'text': intent.raw_text,
            'place': intent.place,
            'confidence': intent.confidence,
        }
        self._publish_json(self.intent_pub, payload)
        self.get_logger().info(f'Intent: {json.dumps(payload, ensure_ascii=False)}')

    def _publish_task(self, payload: Dict[str, object]) -> None:
        self._publish_json(self.robot_task_pub, payload)

    def _publish_safety_command(self, command: str) -> None:
        self.safety_pub.publish(String(data=command))

    def _say(self, text: str) -> None:
        self.reply_pub.publish(String(data=text))
        self.get_logger().info(f'Reply: {text}')

    @staticmethod
    def _publish_json(pub, payload: Dict[str, object]) -> None:
        pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))

    def _on_source_event(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self.last_source_angle = float(data['angle_deg'])
            self.last_source_confidence = float(data['confidence'])
            self.last_source_time = float(data.get('timestamp', time.time()))
            self.get_logger().info(f"Cached last sound source angle: {self.last_source_angle:.1f}°")
        except Exception as e:
            self.get_logger().error(f"Failed to parse source event: {e}")

    def _handle_look_at_sound(self) -> None:
        if self.last_source_angle is None:
            self._say("我还没有检测到声音的方向。")
            return

        # Check if the cached sound event is too old (e.g. older than 30 seconds)
        if time.time() - self.last_source_time > 30.0:
            self._say("之前的声源记录已经过期，请重新发出声音。")
            return

        self._say(f"正在看向声音方向，角度是 {self.last_source_angle:.1f} 度。")
        self._publish_task({
            'task': 'look_at_sound',
            'source': 'voice',
            'angle_deg': self.last_source_angle,
            'confidence': self.last_source_confidence
        })

        # Cancel previous movements by incrementing ID
        self.current_movement_id += 1
        my_id = self.current_movement_id

        # Execute base rotation fallback
        self._rotate_to_angle(self.last_source_angle, my_id)

    def _handle_sound_localization(self) -> None:
        self._say("好的，声源定位功能已开启。")
        self._publish_task({
            'task': 'sound_localization',
            'source': 'voice',
            'active': True
        })

    def _on_odom(self, msg: Odometry) -> None:
        self.last_odom_pose = msg.pose.pose
        q = msg.pose.pose.orientation
        # Convert quaternion to yaw angle
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        self.current_yaw = math.atan2(siny_cosp, cosy_cosp)

    def _on_scan(self, msg: LaserScan) -> None:
        self.last_scan = msg
        self.last_scan_time = time.time()

    def _get_front_distance(self) -> float:
        if self.last_scan is None:
            return float('inf')
        if time.time() - self.last_scan_time > 2.0:
            return float('inf')

        scan = self.last_scan
        angle_min = scan.angle_min
        angle_increment = scan.angle_increment
        ranges = scan.ranges

        valid_ranges = []
        for i, dist in enumerate(ranges):
            angle = angle_min + i * angle_increment
            # Normalize angle to [-pi, pi]
            angle = (angle + math.pi) % (2.0 * math.pi) - math.pi

            # Check if within +-15 degrees cone in front
            if abs(angle) <= math.radians(15.0):
                if math.isfinite(dist) and dist > 0.05:
                    valid_ranges.append(dist)

        if not valid_ranges:
            return float('inf')
        return min(valid_ranges)

    def _rotate_to_angle(self, angle_deg: float, my_id: int) -> None:
        # Calculate target absolute yaw based on current yaw and relative source angle
        yaw_rel = math.radians(angle_deg)
        target_yaw = self.current_yaw + yaw_rel
        # Normalize target yaw to [-pi, pi]
        target_yaw = (target_yaw + math.pi) % (2.0 * math.pi) - math.pi

        self.get_logger().info(
            f"Rotating towards sound: target yaw {math.degrees(target_yaw):.1f}° "
            f"(relative {angle_deg:.1f}°, current {math.degrees(self.current_yaw):.1f}°)"
        )

        def run():
            pub = self.cmd_vel_pub
            twist = Twist()
            # Sleep a tiny bit to let the TTS finish speaking or avoid conflicts
            time.sleep(0.5)
            
            kp = 0.8        # Proportional gain for yaw rotation
            max_speed = 0.6 # Maximum angular speed (rad/s)
            min_speed = 0.15# Minimum angular speed to overcome static friction (rad/s)
            tolerance = 0.03# Tolerance range (~1.7 degrees)
            
            while rclpy.ok():
                if self.current_movement_id != my_id:
                    self.get_logger().info(f"Rotation ID {my_id} cancelled.")
                    return

                # Calculate shortest angular error
                error = target_yaw - self.current_yaw
                error = (error + math.pi) % (2.0 * math.pi) - math.pi
                
                if abs(error) < tolerance:
                    break
                    
                # Proportional speed calculation
                speed = kp * error
                # Limit speed range
                if speed > 0:
                    speed = max(min_speed, min(max_speed, speed))
                else:
                    speed = min(-min_speed, max(-max_speed, speed))
                    
                twist.angular.z = speed
                pub.publish(twist)
                time.sleep(0.05)
            
            # Stop rotation
            twist.angular.z = 0.0
            pub.publish(twist)
            self.get_logger().info("Closed-loop rotation to sound completed.")

        threading.Thread(target=run, daemon=True).start()

    def _handle_come_here(self) -> None:
        if self.last_source_angle is None:
            self._say("我还没有检测到声音的方向。请对我说话。")
            return
        if time.time() - self.last_source_time > 30.0:
            self._say("声源方向记录已过期，请重新呼唤我。")
            return

        self.current_movement_id += 1
        my_id = self.current_movement_id

        self._say("收到，我这就过来。")
        threading.Thread(
            target=self._execute_come_here,
            args=(my_id, self.last_source_angle),
            daemon=True
        ).start()

    def _execute_come_here(self, my_id: int, relative_angle: float) -> None:
        self.get_logger().info(f"Starting 'come_here' execution thread, ID={my_id}")
        
        # Phase 1: Rotate towards the sound source
        yaw_rel = math.radians(relative_angle)
        target_yaw = self.current_yaw + yaw_rel
        target_yaw = (target_yaw + math.pi) % (2.0 * math.pi) - math.pi

        self.get_logger().info(
            f"Rotation phase: target yaw {math.degrees(target_yaw):.1f}° "
            f"(relative {relative_angle:.1f}°, current {math.degrees(self.current_yaw):.1f}°)"
        )

        kp_yaw = 0.8        # Proportional gain for yaw rotation
        max_yaw_speed = 0.5 # Maximum angular speed (rad/s)
        min_yaw_speed = 0.15# Minimum angular speed to overcome static friction (rad/s)
        yaw_tolerance = 0.05# Tolerance range (~2.8 degrees)
        
        pub = self.cmd_vel_pub
        twist = Twist()
        time.sleep(0.5)  # Wait for speech to start

        while rclpy.ok():
            if self.current_movement_id != my_id:
                self.get_logger().info(f"Movement ID {my_id} cancelled during rotation.")
                return

            error = target_yaw - self.current_yaw
            error = (error + math.pi) % (2.0 * math.pi) - math.pi

            if abs(error) < yaw_tolerance:
                self.get_logger().info("Rotation phase completed.")
                break

            speed = kp_yaw * error
            if speed > 0:
                speed = max(min_yaw_speed, min(max_yaw_speed, speed))
            else:
                speed = min(-min_yaw_speed, max(-max_yaw_speed, speed))

            twist.angular.z = speed
            twist.linear.x = 0.0
            pub.publish(twist)
            time.sleep(0.05)

        # Stop rotation
        twist.angular.z = 0.0
        pub.publish(twist)
        time.sleep(0.5)  # Wait to stabilize

        # Phase 2: Move forward using Lidar distance
        kp_dist = 0.4          # Proportional gain for distance
        max_linear_speed = 0.2 # Maximum linear speed (m/s)
        min_linear_speed = 0.08# Minimum linear speed to overcome static friction (m/s)
        target_dist = 0.8      # Target stop distance (meters)
        min_safety_dist = 0.35 # Stop immediately if closer than this (meters)
        max_detect_dist = 4.0  # Max distance to consider target (meters)

        self.get_logger().info("Forward phase: moving towards speaker using Lidar guidance.")

        while rclpy.ok():
            if self.current_movement_id != my_id:
                self.get_logger().info(f"Movement ID {my_id} cancelled during forward motion.")
                return

            dist = self._get_front_distance()

            # If Lidar data is missing or invalid
            if dist == float('inf'):
                self.get_logger().warn("Lidar distance is invalid or stale, stopping for safety.")
                twist.linear.x = 0.0
                pub.publish(twist)
                time.sleep(0.2)
                continue

            # If too close (safety stop)
            if dist < min_safety_dist:
                self.get_logger().warn(f"Obstacle too close ({dist:.2f}m < {min_safety_dist}m), emergency stop.")
                twist.linear.x = 0.0
                pub.publish(twist)
                self._say("太近了，安全停止。")
                return

            # If target distance reached
            if dist <= target_dist:
                self.get_logger().info(f"Target distance reached ({dist:.2f}m <= {target_dist}m). Stopping.")
                twist.linear.x = 0.0
                pub.publish(twist)
                self._say("我到啦！")
                return

            # If target is too far or lost
            if dist > max_detect_dist:
                self.get_logger().warn(f"Target distance too far or lost ({dist:.2f}m > {max_detect_dist}m). Stopping.")
                twist.linear.x = 0.0
                pub.publish(twist)
                self._say("你太远了，我找不到你。")
                return

            # Proportional velocity control
            error_dist = dist - target_dist
            speed = kp_dist * error_dist
            speed = max(min_linear_speed, min(max_linear_speed, speed))

            twist.linear.x = speed
            twist.angular.z = 0.0
            pub.publish(twist)
            time.sleep(0.05)

    def _handle_record_place(self, intent: Intent) -> None:
        display_name = intent.place
        if not display_name:
            self._say("未识别到地点的名称。")
            return

        x, y, yaw = None, None, None
        used_odom = False

        # 1. Try to get transform from map to base_frame using TF
        try:
            now = rclpy.time.Time()
            trans = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.base_frame,
                now,
                timeout=rclpy.duration.Duration(seconds=1.0)
            )
            x = trans.transform.translation.x
            y = trans.transform.translation.y
            q = trans.transform.rotation
            siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
            yaw = math.atan2(siny_cosp, cosy_cosp)
            self.get_logger().info(f"Retrieved robot pose via TF ({self.map_frame} -> {self.base_frame}): x={x:.3f}, y={y:.3f}, yaw={yaw:.3f}")
        except Exception as e:
            self.get_logger().warn(f"TF lookup failed: {e}. Falling back to last received /odom...")

        # 2. If TF fails, try fallback to odom message cache
        if x is None and self.last_odom_pose is not None:
            pos = self.last_odom_pose.position
            x = pos.x
            y = pos.y
            q = self.last_odom_pose.orientation
            siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
            yaw = math.atan2(siny_cosp, cosy_cosp)
            used_odom = True
            self.get_logger().info(f"Retrieved robot pose via /odom callback: x={x:.3f}, y={y:.3f}, yaw={yaw:.3f}")

        # 3. If both failed
        if x is None:
            self._say("无法获取定位坐标，请确认导航系统或里程计已正常启动。")
            return

        # 4. Save to YAML
        success = self._save_place(display_name, x, y, yaw)
        if success:
            if used_odom:
                self._say(f"定位系统未就绪，已使用里程计坐标将当前位置记录为{display_name}。")
            else:
                self._say(f"好的，我已经把当前位置记录为{display_name}。")
        else:
            self._say("保存位置文件失败，请检查文件写入权限。")

    def _on_record_place_cmd(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            display_name = data.get('name')
            if not display_name:
                self.get_logger().error("Record place command missing 'name' field.")
                return

            x = data.get('x')
            y = data.get('y')
            yaw = data.get('yaw')

            # If coordinates are provided, save them directly
            if x is not None and y is not None and yaw is not None:
                self.get_logger().info(f"API command requested direct coordinate save for '{display_name}': x={x}, y={y}, yaw={yaw}")
                success = self._save_place(display_name, float(x), float(y), float(yaw))
                if success:
                    self._say(f"好的，已更新{display_name}的坐标。")
                else:
                    self._say("保存位置文件失败。")
                return

            # Otherwise, perform dynamic record (query TF/Odom)
            self.get_logger().info(f"API command requested dynamic record for '{display_name}'. Querying coordinates...")
            intent = Intent(name='record_place', raw_text='', place=display_name)
            self._handle_record_place(intent)
        except Exception as e:
            self.get_logger().error(f"Failed to process record place command: {e}")

    def _save_place(self, display_name: str, x: float, y: float, yaw: float) -> bool:
        places_file = self.get_parameter('places_file').get_parameter_value().string_value
        if not places_file:
            self.get_logger().error("places_file parameter is empty, cannot save location.")
            return False

        try:
            # Ensure the directory exists
            dir_path = os.path.dirname(places_file)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)

            data = {}
            if os.path.exists(places_file):
                with open(places_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}

            if 'places' not in data:
                data['places'] = {}

            places = data['places']

            # Find if this place already exists (by name or aliases match)
            existing_key = None
            for key, info in places.items():
                if info.get('name') == display_name or display_name in info.get('aliases', []):
                    existing_key = key
                    break

            if existing_key:
                places[existing_key]['x'] = round(float(x), 3)
                places[existing_key]['y'] = round(float(y), 3)
                places[existing_key]['yaw'] = round(float(yaw), 3)
                self.get_logger().info(f"Updated existing place '{existing_key}' (name: '{display_name}') in places.yaml.")
            else:
                # Find a unique key
                key_idx = 1
                while f"place_{key_idx}" in places:
                    key_idx += 1
                new_key = f"place_{key_idx}"
                places[new_key] = {
                    'name': display_name,
                    'aliases': [],
                    'x': round(float(x), 3),
                    'y': round(float(y), 3),
                    'yaw': round(float(yaw), 3)
                }
                self.get_logger().info(f"Created new place '{new_key}' (name: '{display_name}') in places.yaml.")

            # Write back atomically using temporary file + rename replacement
            temp_file = places_file + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
            os.replace(temp_file, places_file)

            # Refresh internal lookups
            self.places = self._load_places()
            self.place_aliases = self._build_place_aliases()
            return True
        except Exception as e:
            self.get_logger().error(f"Error saving place to file {places_file}: {e}")
            # Clean up temp file if it exists
            try:
                temp_file = places_file + ".tmp"
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
            return False


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = VoiceAssistantNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
