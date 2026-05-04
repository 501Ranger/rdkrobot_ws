import json
import os
import threading
import urllib.error
import urllib.request
from typing import Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class LlmDialogNode(Node):
    """Reply to chat tasks with an OpenAI-compatible chat completion API."""

    def __init__(self) -> None:
        super().__init__('llm_dialog_node')

        self.declare_parameter('robot_task_topic', '/voice/robot_task')
        self.declare_parameter('reply_text_topic', '/assistant/reply_text')
        self.declare_parameter('base_url', 'https://api.openai.com/v1')
        self.declare_parameter('model', 'gpt-4o-mini')
        self.declare_parameter('api_key', '')
        self.declare_parameter('api_key_env', 'LLM_API_KEY')
        self.declare_parameter('api_key_header', 'Authorization')
        self.declare_parameter('api_key_prefix', 'Bearer')
        self.declare_parameter('timeout_sec', 20.0)
        self.declare_parameter('temperature', 0.4)
        self.declare_parameter('top_p', 1.0)
        self.declare_parameter('max_tokens', 180)
        self.declare_parameter('max_tokens_param', 'max_tokens')
        self.declare_parameter('history_turns', 4)
        self.declare_parameter(
            'system_prompt',
            '你是家庭陪伴机器人语音助手。'
            '用简短、自然、适合语音播报的中文回答。'
            '如果用户要求机器人移动、停止、巡查或查询状态，不要假装已经执行，'
            '只提醒用户可以使用明确的控制指令。',
        )
        self.declare_parameter('busy_reply', '我正在思考上一个问题，请稍等一下。')
        self.declare_parameter('error_reply', '我现在连接大模型有点问题，稍后再试。')

        self.reply_pub = self.create_publisher(
            String,
            str(self.get_parameter('reply_text_topic').value),
            10,
        )
        self.create_subscription(
            String,
            str(self.get_parameter('robot_task_topic').value),
            self._on_robot_task,
            10,
        )

        self.history: List[Dict[str, str]] = []
        self.lock = threading.Lock()
        self.busy = False
        self.active_text = ''
        self.request_seq = 0

        self.get_logger().info(
            'LLM dialog node ready. Listening for chat tasks on '
            f'{self.get_parameter("robot_task_topic").value}'
        )

    def _on_robot_task(self, msg: String) -> None:
        try:
            task = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        if task.get('task') != 'chat':
            return

        text = str(task.get('text', '')).strip()
        if not text:
            return

        with self.lock:
            if self.busy:
                if text == self.active_text:
                    self.get_logger().info(
                        f'Ignore duplicate chat task while busy: {text}'
                    )
                    return
                self.get_logger().info(
                    f'Busy with chat task: {self.active_text}; rejected: {text}'
                )
                self._say(str(self.get_parameter('busy_reply').value))
                return
            self.busy = True
            self.active_text = text
            self.request_seq += 1
            request_id = self.request_seq

        self.get_logger().info(f'Start LLM request #{request_id}: {text}')
        threading.Thread(
            target=self._reply_worker,
            args=(request_id, text),
            daemon=True,
        ).start()

    def _reply_worker(self, request_id: int, text: str) -> None:
        try:
            reply = self._call_llm(text)
            if reply:
                self._remember(text, reply)
                self._say(reply)
            else:
                self._say(str(self.get_parameter('error_reply').value))
        except Exception as exc:
            self.get_logger().error(f'LLM dialog failed: {exc}')
            self._say(str(self.get_parameter('error_reply').value))
        finally:
            with self.lock:
                self.busy = False
                self.active_text = ''
            self.get_logger().info(f'Finish LLM request #{request_id}: {text}')

    def _call_llm(self, text: str) -> str:
        api_key_env = str(self.get_parameter('api_key_env').value)
        api_key = str(self.get_parameter('api_key').value).strip()
        if not api_key:
            api_key = os.environ.get(api_key_env, '').strip()
        if not api_key:
            raise RuntimeError(
                f'Missing API key. Set parameter api_key or environment variable: {api_key_env}'
            )

        base_url = str(self.get_parameter('base_url').value).rstrip('/')
        url = f'{base_url}/chat/completions'
        messages = [
            {
                'role': 'system',
                'content': str(self.get_parameter('system_prompt').value),
            },
            *self.history,
            {'role': 'user', 'content': text},
        ]
        payload = {
            'model': str(self.get_parameter('model').value),
            'messages': messages,
            'temperature': float(self.get_parameter('temperature').value),
            'top_p': float(self.get_parameter('top_p').value),
            str(self.get_parameter('max_tokens_param').value): int(
                self.get_parameter('max_tokens').value
            ),
            'stream': False,
        }

        api_key_header = str(self.get_parameter('api_key_header').value).strip()
        api_key_prefix = str(self.get_parameter('api_key_prefix').value).strip()
        api_key_value = f'{api_key_prefix} {api_key}' if api_key_prefix else api_key
        headers = {
            api_key_header: api_key_value,
            'Content-Type': 'application/json',
        }

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST',
        )

        timeout = float(self.get_parameter('timeout_sec').value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            raise RuntimeError(f'HTTP {exc.code}: {body}') from exc

        return self._extract_reply(data)

    def _remember(self, user_text: str, assistant_text: str) -> None:
        self.history.extend([
            {'role': 'user', 'content': user_text},
            {'role': 'assistant', 'content': assistant_text},
        ])
        max_items = max(0, int(self.get_parameter('history_turns').value) * 2)
        if max_items:
            self.history = self.history[-max_items:]
        else:
            self.history = []

    def _say(self, text: str) -> None:
        self.reply_pub.publish(String(data=text))
        self.get_logger().info(f'LLM reply: {text}')

    @staticmethod
    def _extract_reply(data: Dict[str, object]) -> str:
        choices = data.get('choices', [])
        if not isinstance(choices, list) or not choices:
            return ''
        first = choices[0]
        if not isinstance(first, dict):
            return ''
        message = first.get('message', {})
        if not isinstance(message, dict):
            return ''
        return str(message.get('content', '')).strip()


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = LlmDialogNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
