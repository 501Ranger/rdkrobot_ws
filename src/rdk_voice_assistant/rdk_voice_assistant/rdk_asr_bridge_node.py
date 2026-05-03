import json
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class RdkAsrBridgeNode(Node):
    """Bridge RDK official ASR text into the assistant command interface."""

    def __init__(self) -> None:
        super().__init__('rdk_asr_bridge_node')

        self.declare_parameter('official_asr_text_topic', '/asr_text')
        self.declare_parameter('command_text_topic', '/voice/command_text')
        self.declare_parameter('partial_text_topic', '/voice/partial_text')
        self.declare_parameter('publish_partial', False)
        self.declare_parameter('json_text_key', '')
        self.declare_parameter('require_wake_word', False)
        self.declare_parameter('wake_words', '小智,小智小智,机器人')
        self.declare_parameter('remove_wake_word', True)
        self.declare_parameter('drop_empty', True)

        self.command_pub = self.create_publisher(
            String,
            str(self.get_parameter('command_text_topic').value),
            10,
        )
        self.partial_pub = self.create_publisher(
            String,
            str(self.get_parameter('partial_text_topic').value),
            10,
        )

        self.create_subscription(
            String,
            str(self.get_parameter('official_asr_text_topic').value),
            self._on_asr_text,
            10,
        )

        self.get_logger().info(
            'RDK ASR bridge ready: '
            f'{self.get_parameter("official_asr_text_topic").value} -> '
            f'{self.get_parameter("command_text_topic").value}'
        )

    def _on_asr_text(self, msg: String) -> None:
        text = self._extract_text(msg.data)
        text = self._normalize_text(text)

        if bool(self.get_parameter('drop_empty').value) and not text:
            return

        require_wake_word = bool(self.get_parameter('require_wake_word').value)
        remove_wake_word = bool(self.get_parameter('remove_wake_word').value)
        wake_word = self._match_wake_word(text)

        if require_wake_word and not wake_word:
            self.get_logger().debug(f'Ignored ASR text without wake word: {text}')
            return

        if wake_word and remove_wake_word:
            text = text.replace(wake_word, '', 1).strip()

        if not text:
            return

        if bool(self.get_parameter('publish_partial').value):
            self.partial_pub.publish(String(data=text))

        self.command_pub.publish(String(data=text))
        self.get_logger().info(f'ASR bridge text: {text}')

    def _extract_text(self, data: str) -> str:
        key = str(self.get_parameter('json_text_key').value).strip()
        if not key:
            return data

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            self.get_logger().warn('json_text_key is set, but ASR payload is not JSON.')
            return data

        value = payload.get(key, '')
        return str(value)

    def _match_wake_word(self, text: str) -> Optional[str]:
        wake_words = str(self.get_parameter('wake_words').value)
        for word in [item.strip() for item in wake_words.split(',') if item.strip()]:
            if word in text:
                return word
        return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.replace(' ', '').replace('，', '').replace('。', '').strip()


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = RdkAsrBridgeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
