import json
import math
import os
from typing import Dict, Optional

import rclpy
import yaml
from geometry_msgs.msg import PoseStamped
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

        self.places = self._load_places()
        self.place_aliases = self._build_place_aliases()

        self.intent_pub = self.create_publisher(String, self.intent_topic, 10)
        self.reply_pub = self.create_publisher(String, self.reply_text_topic, 10)
        self.robot_task_pub = self.create_publisher(String, self.robot_task_topic, 10)
        self.safety_pub = self.create_publisher(String, self.safety_command_topic, 10)
        self.nav_client = ActionClient(self, NavigateToPose, self.navigate_action_name)

        self.create_subscription(
            String,
            self.command_text_topic,
            self._on_command_text,
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
        elif intent.name == 'stop':
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


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = VoiceAssistantNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
