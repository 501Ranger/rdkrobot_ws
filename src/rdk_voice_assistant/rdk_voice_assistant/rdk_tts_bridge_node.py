from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class RdkTtsBridgeNode(Node):
    """Bridge assistant replies into the RDK official TTS text topic."""

    def __init__(self) -> None:
        super().__init__('rdk_tts_bridge_node')

        self.declare_parameter('reply_text_topic', '/assistant/reply_text')
        self.declare_parameter('official_tts_text_topic', '/tts_text')
        self.declare_parameter('prefix', '')
        self.declare_parameter('suffix', '')
        self.declare_parameter('max_text_length', 120)
        self.declare_parameter('drop_empty', True)

        self.tts_pub = self.create_publisher(
            String,
            str(self.get_parameter('official_tts_text_topic').value),
            10,
        )
        self.create_subscription(
            String,
            str(self.get_parameter('reply_text_topic').value),
            self._on_reply_text,
            10,
        )

        self.get_logger().info(
            'RDK TTS bridge ready: '
            f'{self.get_parameter("reply_text_topic").value} -> '
            f'{self.get_parameter("official_tts_text_topic").value}'
        )

    def _on_reply_text(self, msg: String) -> None:
        text = msg.data.strip()
        if bool(self.get_parameter('drop_empty').value) and not text:
            return

        text = (
            str(self.get_parameter('prefix').value)
            + text
            + str(self.get_parameter('suffix').value)
        )

        max_text_length = int(self.get_parameter('max_text_length').value)
        if max_text_length > 0 and len(text) > max_text_length:
            text = text[:max_text_length]

        self.tts_pub.publish(String(data=text))
        self.get_logger().info(f'TTS bridge text: {text}')


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = RdkTtsBridgeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
