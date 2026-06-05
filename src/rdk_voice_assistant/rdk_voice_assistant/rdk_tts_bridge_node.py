import json
import threading
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String


class RdkTtsBridgeNode(Node):
    """Bridge assistant replies into the RDK official TTS text topic and publish estimated states."""

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
        self.active_pub = self.create_publisher(Bool, '/voice/tts_active', 10)
        self.tts_status_pub = self.create_publisher(String, '/voice/tts_status', 10)

        self.tts_timer: Optional[threading.Timer] = None
        self.lock = threading.Lock()

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

    def destroy_node(self):
        with self.lock:
            if self.tts_timer:
                self.tts_timer.cancel()
        return super().destroy_node()

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

        # Publish active states and status JSON
        self.active_pub.publish(Bool(data=True))
        self._publish_tts_status('speaking', text)

        # Estimate duration: e.g. 4 Chinese characters per second, min 1.2s
        duration = max(1.2, len(text) / 4.0)

        with self.lock:
            if self.tts_timer:
                self.tts_timer.cancel()
            self.tts_timer = threading.Timer(duration, self._on_tts_finished)
            self.tts_timer.start()

    def _on_tts_finished(self) -> None:
        self.active_pub.publish(Bool(data=False))
        self._publish_tts_status('idle')

    def _publish_tts_status(self, state: str, text: str = '', error: str = '') -> None:
        try:
            payload = {
                'state': state,
                'engine': 'official-rdk',
                'text': text,
                'error': error,
                'queue_len': 0
            }
            self.tts_status_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
        except Exception as e:
            self.get_logger().error(f'Failed to publish TTS status: {e}')


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
