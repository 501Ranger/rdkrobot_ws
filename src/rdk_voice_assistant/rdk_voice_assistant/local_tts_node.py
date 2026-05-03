import queue
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class LocalTtsNode(Node):
    """Offline TTS node for assistant replies."""

    def __init__(self) -> None:
        super().__init__('local_tts_node')

        self.declare_parameter('reply_text_topic', '/assistant/reply_text')
        self.declare_parameter('engine', 'pyttsx3')
        self.declare_parameter('rate', 170)
        self.declare_parameter('volume', 1.0)
        self.declare_parameter('voice', '')
        self.declare_parameter('language', 'zh')
        self.declare_parameter('espeak_executable', 'espeak-ng')
        self.declare_parameter('piper_executable', 'piper')
        self.declare_parameter('piper_model_path', '')
        self.declare_parameter('audio_player', 'aplay')
        self.declare_parameter('print_text', True)

        self.text_queue: queue.Queue[str] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        self.worker.start()

        self.create_subscription(
            String,
            self.get_parameter('reply_text_topic').value,
            self._on_reply_text,
            10,
        )

        self.get_logger().info(
            f'Local TTS node started. Engine: {self.get_parameter("engine").value}'
        )

    def destroy_node(self):
        self.stop_event.set()
        self.text_queue.put('')
        if self.worker.is_alive():
            self.worker.join(timeout=2.0)
        return super().destroy_node()

    def _on_reply_text(self, msg: String) -> None:
        text = msg.data.strip()
        if text:
            self.text_queue.put(text)

    def _run_worker(self) -> None:
        engine = str(self.get_parameter('engine').value).lower()

        if engine == 'pyttsx3':
            self._run_pyttsx3_worker()
            return

        while not self.stop_event.is_set():
            try:
                text = self.text_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if not text:
                continue
            self._print_if_enabled(text)
            if engine == 'espeak':
                self._speak_with_espeak(text)
            elif engine == 'piper':
                self._speak_with_piper(text)
            elif engine == 'print':
                continue
            else:
                self.get_logger().error(f'Unsupported TTS engine: {engine}')

    def _run_pyttsx3_worker(self) -> None:
        try:
            import pyttsx3
        except ImportError as exc:
            self.get_logger().error(
                'Missing pyttsx3. Install with: python3 -m pip install pyttsx3'
            )
            self.get_logger().error(str(exc))
            return

        engine = pyttsx3.init()
        engine.setProperty('rate', int(self.get_parameter('rate').value))
        engine.setProperty('volume', float(self.get_parameter('volume').value))

        voice = str(self.get_parameter('voice').value)
        if voice:
            engine.setProperty('voice', voice)

        while not self.stop_event.is_set():
            try:
                text = self.text_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if not text:
                continue
            self._print_if_enabled(text)
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                self.get_logger().error(f'pyttsx3 failed: {exc}')

    def _speak_with_espeak(self, text: str) -> None:
        executable = str(self.get_parameter('espeak_executable').value)
        language = str(self.get_parameter('language').value)
        rate = str(self.get_parameter('rate').value)
        command = [executable, '-v', language, '-s', rate, text]
        self._run_command(command, 'espeak-ng')

    def _speak_with_piper(self, text: str) -> None:
        executable = str(self.get_parameter('piper_executable').value)
        model_path = str(self.get_parameter('piper_model_path').value)
        audio_player = str(self.get_parameter('audio_player').value)

        if not model_path:
            self.get_logger().error('piper_model_path is empty.')
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / 'reply.wav'
            piper_command = [
                executable,
                '--model',
                model_path,
                '--output_file',
                str(wav_path),
            ]
            try:
                subprocess.run(
                    piper_command,
                    input=text,
                    text=True,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                self._run_command([audio_player, str(wav_path)], audio_player)
            except subprocess.CalledProcessError as exc:
                self.get_logger().error(f'Piper failed: {exc.stderr}')

    def _run_command(self, command: list, name: str) -> None:
        try:
            subprocess.run(command, check=True)
        except FileNotFoundError:
            self.get_logger().error(f'{name} executable not found: {command[0]}')
        except subprocess.CalledProcessError as exc:
            self.get_logger().error(f'{name} exited with code {exc.returncode}')

    def _print_if_enabled(self, text: str) -> None:
        if bool(self.get_parameter('print_text').value):
            self.get_logger().info(f'TTS: {text}')


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = LocalTtsNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
