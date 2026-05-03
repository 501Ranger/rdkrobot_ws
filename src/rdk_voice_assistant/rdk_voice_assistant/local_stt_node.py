import json
import queue
import threading
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class LocalSttNode(Node):
    """Offline microphone speech recognition using Vosk."""

    def __init__(self) -> None:
        super().__init__('local_stt_node')

        self.declare_parameter('command_text_topic', '/voice/command_text')
        self.declare_parameter('partial_text_topic', '/voice/partial_text')
        self.declare_parameter('model_path', '')
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('block_size', 8000)
        self.declare_parameter('device', '')
        self.declare_parameter('language', 'zh-cn')
        self.declare_parameter('publish_partial', False)
        self.declare_parameter('require_wake_word', False)
        self.declare_parameter('wake_words', '小智,小智小智,机器人')
        self.declare_parameter('remove_wake_word', True)

        self.command_pub = self.create_publisher(
            String,
            self.get_parameter('command_text_topic').value,
            10,
        )
        self.partial_pub = self.create_publisher(
            String,
            self.get_parameter('partial_text_topic').value,
            10,
        )

        self.audio_queue: queue.Queue[bytes] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run_vosk, daemon=True)
        self.worker.start()

        self.get_logger().info('Local STT node started. Engine: Vosk')

    def destroy_node(self):
        self.stop_event.set()
        if self.worker.is_alive():
            self.worker.join(timeout=2.0)
        return super().destroy_node()

    def _run_vosk(self) -> None:
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except ImportError as exc:
            self.get_logger().error(
                'Missing local STT dependencies. Install with: '
                'python3 -m pip install vosk sounddevice'
            )
            self.get_logger().error(str(exc))
            return

        model_path = str(self.get_parameter('model_path').value)
        if not model_path:
            self.get_logger().error(
                'Vosk model_path is empty. Download a Chinese Vosk model and '
                'launch with model_path:=/path/to/vosk-model-small-cn-0.22'
            )
            return

        sample_rate = int(self.get_parameter('sample_rate').value)
        block_size = int(self.get_parameter('block_size').value)
        device = self._parse_device(str(self.get_parameter('device').value))

        self.get_logger().info(f'Loading Vosk model: {model_path}')
        model = Model(model_path)
        recognizer = KaldiRecognizer(model, sample_rate)
        recognizer.SetWords(False)

        def callback(indata, frames, time, status):
            if status:
                self.get_logger().warn(str(status))
            self.audio_queue.put(bytes(indata))

        try:
            with sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=device,
                dtype='int16',
                channels=1,
                callback=callback,
            ):
                self.get_logger().info(
                    f'Microphone opened. sample_rate={sample_rate}, device={device or "default"}'
                )
                while not self.stop_event.is_set():
                    try:
                        data = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    if recognizer.AcceptWaveform(data):
                        text = self._extract_text(recognizer.Result(), key='text')
                        self._handle_final_text(text)
                    elif bool(self.get_parameter('publish_partial').value):
                        text = self._extract_text(recognizer.PartialResult(), key='partial')
                        if text:
                            self.partial_pub.publish(String(data=text))
        except Exception as exc:
            self.get_logger().error(f'Local STT failed: {exc}')

    def _handle_final_text(self, text: str) -> None:
        text = self._normalize_text(text)
        if not text:
            return

        require_wake_word = bool(self.get_parameter('require_wake_word').value)
        remove_wake_word = bool(self.get_parameter('remove_wake_word').value)
        wake_word = self._match_wake_word(text)

        if require_wake_word and not wake_word:
            self.get_logger().debug(f'Ignored without wake word: {text}')
            return

        if wake_word and remove_wake_word:
            text = text.replace(wake_word, '', 1).strip()

        if not text:
            return

        self.command_pub.publish(String(data=text))
        self.get_logger().info(f'STT final: {text}')

    def _match_wake_word(self, text: str) -> Optional[str]:
        wake_words = str(self.get_parameter('wake_words').value)
        for word in [item.strip() for item in wake_words.split(',') if item.strip()]:
            if word in text:
                return word
        return None

    @staticmethod
    def _parse_device(device: str):
        device = device.strip()
        if not device:
            return None
        if device.isdigit():
            return int(device)
        return device

    @staticmethod
    def _extract_text(result_json: str, key: str) -> str:
        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            return ''
        return str(result.get(key, '')).strip()

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.replace(' ', '').replace('，', '').replace('。', '').strip()


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = LocalSttNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
