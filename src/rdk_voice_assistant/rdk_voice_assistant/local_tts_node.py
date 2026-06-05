import re
import hashlib
import wave
import json
import queue
import time
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

# Import Phase 2 helpers
from rdk_voice_assistant.voice_utils import remove_emojis, normalize_text
from rdk_voice_assistant.tts_queue import BoundedSpeechQueue


class LocalTtsNode(Node):
    """Offline TTS node for assistant replies supporting PyTTSx3, Edge-TTS, and Sherpa-ONNX."""

    def __init__(self) -> None:
        super().__init__('local_tts_node')

        self.declare_parameter('reply_text_topic', '/assistant/reply_text')
        self.declare_parameter('engine', 'sherpa-onnx')
        self.declare_parameter('rate', 170)
        self.declare_parameter('volume', 1.0)
        self.declare_parameter('voice', '')
        self.declare_parameter('language', 'zh')
        self.declare_parameter('espeak_executable', 'espeak-ng')
        self.declare_parameter('piper_executable', 'piper')
        self.declare_parameter('piper_model_path', '')
        self.declare_parameter('audio_player', 'aplay')
        self.declare_parameter('print_text', True)

        # Sherpa-ONNX VITS configurations
        self.declare_parameter('sherpa_onnx_model', '/home/linrain/vits-zh-aishell3/vits-aishell3.onnx')
        self.declare_parameter('sherpa_onnx_lexicon', '/home/linrain/vits-zh-aishell3/lexicon.txt')
        self.declare_parameter('sherpa_onnx_tokens', '/home/linrain/vits-zh-aishell3/tokens.txt')
        self.declare_parameter('sherpa_onnx_data_dir', '')
        self.declare_parameter('sherpa_onnx_speaker_id', 2)
        self.declare_parameter('sherpa_onnx_speed', 1.0)
        self.declare_parameter('sherpa_onnx_noise_scale', 0.667)
        self.declare_parameter('sherpa_onnx_noise_scale_w', 0.8)
        self.declare_parameter('sherpa_onnx_tts_num_threads', 2)
        self.declare_parameter('tts_cache_dir', '~/.ros/rdk_voice_assistant/tts_cache')
        self.declare_parameter('max_cache_text_length', 15)

        self.cache_dir = Path(self.get_parameter('tts_cache_dir').value).expanduser()
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.get_logger().info(f'TTS Cache directory initialized at: {self.cache_dir}')
        except Exception as e:
            self.get_logger().error(f'Failed to create cache directory {self.cache_dir}: {e}')

        self.tts_active_pub = self.create_publisher(Bool, '/voice/tts_active', 10)
        self.tts_status_pub = self.create_publisher(String, '/voice/tts_status', 10)

        self.text_queue = BoundedSpeechQueue(maxsize=5)
        self.recent_speeches = {}
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        self.worker.start()

        self.create_subscription(
            String,
            str(self.get_parameter('reply_text_topic').value),
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
            if text == '__CLEAR__':
                self.get_logger().info('Clearing TTS text queue on request.')
                self.text_queue.clear()
                self._publish_tts_status('idle')
                return
            # Clean emojis for vocalisation to prevent TTS engine from reading them out
            clean_text = remove_emojis(text)
            if clean_text:
                now = time.time()
                # Remove duplicate speeches older than 2.0 seconds
                self.recent_speeches = {k: v for k, v in self.recent_speeches.items() if now - v < 2.0}
                if clean_text in self.recent_speeches:
                    self.get_logger().info(f'Discarded duplicate TTS text: {clean_text}')
                    return
                self.recent_speeches[clean_text] = now

                # Split by clause terminators to achieve sentence-by-sentence pseudo-streaming
                sentences = re.split(r'(?<=[。！？；\n.!?;\n])\s*', clean_text)
                enqueued_any = False
                for s in sentences:
                    s = s.strip()
                    if s:
                        if self.text_queue.put(s):
                            enqueued_any = True
                        else:
                            self.get_logger().warn(f'TTS queue is full, dropping sub-sentence: {s}')
                            break
                if enqueued_any:
                    self._publish_tts_status('ready', clean_text)

    def _publish_tts_status(self, state: str, text: str = '', error: str = '') -> None:
        try:
            payload = {
                'state': state,
                'engine': str(self.get_parameter('engine').value),
                'text': text,
                'error': error,
                'queue_len': self.text_queue.qsize()
            }
            self.tts_status_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
        except Exception as e:
            self.get_logger().error(f'Failed to publish TTS status: {e}')

    def _run_worker(self) -> None:
        engine = str(self.get_parameter('engine').value).lower()

        if engine == 'pyttsx3':
            self._run_pyttsx3_worker()
            return

        if engine == 'edge-tts' or engine == 'edge_tts':
            self._run_edge_tts_worker()
            return

        if engine == 'sherpa-onnx' or engine == 'sherpa_onnx':
            self._run_sherpa_onnx_worker()
            return

        while not self.stop_event.is_set():
            try:
                text = self.text_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if not text:
                continue
            text = self._normalize_numbers(text)
            self._print_if_enabled(text)
            self.tts_active_pub.publish(Bool(data=True))
            self._publish_tts_status('speaking', text)
            try:
                if engine == 'espeak':
                    self._speak_with_espeak(text)
                elif engine == 'piper':
                    self._speak_with_piper(text)
                elif engine == 'print':
                    continue
                else:
                    self.get_logger().error(f'Unsupported TTS engine: {engine}')
                    self._publish_tts_status('error', text, f'Unsupported TTS engine: {engine}')
            except Exception as exc:
                self.get_logger().error(f'TTS execution failed: {exc}')
                self._publish_tts_status('error', text, str(exc))
            finally:
                self.tts_active_pub.publish(Bool(data=False))
                self._publish_tts_status('idle')

    def _save_wav(self, filename: Path, samples: np.ndarray, sample_rate: int) -> None:
        try:
            pcm16 = (samples * 32767).astype(np.int16)
            with wave.open(str(filename), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm16.tobytes())
            self.get_logger().info(f'Saved TTS audio to cache: {filename.name}')
        except Exception as e:
            self.get_logger().error(f'Failed to save wav cache {filename}: {e}')

    def _load_wav(self, filename: Path) -> tuple[np.ndarray, int]:
        with wave.open(str(filename), 'rb') as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sample_rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            
            if sampwidth == 2:
                data = np.frombuffer(frames, dtype=np.int16)
                samples = data.astype(np.float32) / 32767.0
            else:
                raise ValueError(f"Unsupported sample width: {sampwidth}")
            return samples, sample_rate

    def _get_cache_path(self, text: str, speaker_id: int, speed: float) -> Path:
        norm = normalize_text(text)
        key = f"{norm}_sid{speaker_id}_speed{speed}".encode('utf-8')
        h = hashlib.md5(key).hexdigest()
        prefix = re.sub(r'[^\w]', '', norm)[:6]
        filename = f"{prefix}_{h}.wav"
        return self.cache_dir / filename

    def _run_synthesis_worker(self, tts, speaker_id: int, speed: float, max_cache_len: int) -> None:
        try:
            self.get_logger().info('TTS synthesis worker thread started.')
            while not self.stop_event.is_set():
                try:
                    text = self.text_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if not text:
                    continue
                text = self._normalize_numbers(text)
                try:
                    norm = normalize_text(text)
                    cache_hit = False
                    samples, sample_rate = None, None

                    # Check if eligible for caching
                    if len(norm) > 0 and len(norm) <= max_cache_len:
                        cache_path = self._get_cache_path(text, speaker_id, speed)
                        if cache_path.exists():
                            try:
                                self.get_logger().info(f'TTS Cache HIT for: "{text}" -> loading {cache_path.name}')
                                samples, sample_rate = self._load_wav(cache_path)
                                cache_hit = True
                            except Exception as cache_err:
                                self.get_logger().error(f'Failed to load cached wav: {cache_err}')

                    if not cache_hit:
                        # Generate audio using TTS model
                        audio = tts.generate(text, sid=speaker_id, speed=speed)
                        samples = np.array(audio.samples, dtype=np.float32)
                        sample_rate = audio.sample_rate
                        
                        # Save to cache if eligible
                        if len(norm) > 0 and len(norm) <= max_cache_len:
                            cache_path = self._get_cache_path(text, speaker_id, speed)
                            # Save in background thread so it doesn't block the synthesis thread
                            threading.Thread(
                                target=self._save_wav,
                                args=(cache_path, samples, sample_rate),
                                daemon=True
                            ).start()

                    # Put to audio playback queue
                    self.audio_queue.put((samples, sample_rate, text))
                except Exception as exc:
                    self.get_logger().error(f"TTS synthesis failed for '{text}': {exc}")
                    self._publish_tts_status('error', text, str(exc))
                    if self.audio_queue.empty() and self.text_queue.is_empty():
                        self.tts_active_pub.publish(Bool(data=False))
                        self._publish_tts_status('idle')
        except Exception as thread_exc:
            self.get_logger().error(f'Fatal error in TTS synthesis thread: {thread_exc}')

    def _run_playback_worker(self) -> None:
        try:
            self.get_logger().info('TTS playback worker thread started.')
            try:
                import sounddevice as sd
                self.get_logger().info('sounddevice imported successfully in playback thread.')
            except Exception as e:
                self.get_logger().error(f'Failed to import sounddevice in playback thread: {e}')
                return

            while not self.stop_event.is_set():
                try:
                    samples, sample_rate, text = self.audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                self._print_if_enabled(text)
                self.tts_active_pub.publish(Bool(data=True))
                self._publish_tts_status('speaking', text)
                try:
                    sd.play(samples, sample_rate)
                    sd.wait()
                except Exception as exc:
                    self.get_logger().error(f'Playback execution failed: {exc}')
                finally:
                    if self.audio_queue.empty() and self.text_queue.is_empty():
                        self.tts_active_pub.publish(Bool(data=False))
                        self._publish_tts_status('idle')
        except Exception as thread_exc:
            self.get_logger().error(f'Fatal error in TTS playback thread: {thread_exc}')

    def _run_sherpa_onnx_worker(self) -> None:
        try:
            import sherpa_onnx
        except ImportError as exc:
            self.get_logger().error(
                'Missing sherpa-onnx. Install with: python3 -m pip install sherpa-onnx'
            )
            self.get_logger().error(str(exc))
            self._publish_tts_status('error', '', f'Import failed: {exc}')
            return

        # Load parameters
        model_path = str(self.get_parameter('sherpa_onnx_model').value)
        lexicon_path = str(self.get_parameter('sherpa_onnx_lexicon').value)
        tokens_path = str(self.get_parameter('sherpa_onnx_tokens').value)
        data_dir_path = str(self.get_parameter('sherpa_onnx_data_dir').value)
        speaker_id = int(self.get_parameter('sherpa_onnx_speaker_id').value)
        speed = float(self.get_parameter('sherpa_onnx_speed').value)
        noise_scale = float(self.get_parameter('sherpa_onnx_noise_scale').value)
        noise_scale_w = float(self.get_parameter('sherpa_onnx_noise_scale_w').value)
        num_threads = int(self.get_parameter('sherpa_onnx_tts_num_threads').value)
        max_cache_len = int(self.get_parameter('max_cache_text_length').value)

        # Validate paths
        if not Path(model_path).exists():
            err_msg = f'Sherpa-ONNX VITS model not found at: {model_path}'
            self.get_logger().error(err_msg)
            self._publish_tts_status('error', '', err_msg)
            return

        self.get_logger().info(f'Loading Sherpa-ONNX VITS model: {model_path} with {num_threads} threads')
        self._publish_tts_status('loading')
        try:
            model_config = sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=model_path,
                    lexicon=lexicon_path,
                    tokens=tokens_path,
                    data_dir=data_dir_path,
                    noise_scale=noise_scale,
                    noise_scale_w=noise_scale_w,
                    length_scale=1.0 / speed,
                ),
                num_threads=num_threads,
                debug=False,
            )
            config = sherpa_onnx.OfflineTtsConfig(
                model=model_config
            )
            tts = sherpa_onnx.OfflineTts(config)
            self.get_logger().info('Sherpa-ONNX VITS model loaded successfully.')
            self._publish_tts_status('ready')
        except Exception as exc:
            self.get_logger().error(f'Failed to initialize Sherpa-ONNX: {exc}')
            self._publish_tts_status('error', '', f'Load failed: {exc}')
            return

        # Initialize audio playback queue
        self.audio_queue = queue.Queue(maxsize=5)

        # Start synthesis and playback threads
        synthesis_thread = threading.Thread(
            target=self._run_synthesis_worker,
            args=(tts, speaker_id, speed, max_cache_len),
            daemon=True
        )
        playback_thread = threading.Thread(
            target=self._run_playback_worker,
            daemon=True
        )
        synthesis_thread.start()
        playback_thread.start()

        # Keep this thread alive to supervise the workers
        while not self.stop_event.is_set():
            time.sleep(0.5)

        # Wait for threads to clean up
        synthesis_thread.join(timeout=1.0)
        playback_thread.join(timeout=1.0)

    def _run_pyttsx3_worker(self) -> None:
        try:
            import pyttsx3
        except ImportError as exc:
            self.get_logger().error(
                'Missing pyttsx3. Install with: python3 -m pip install pyttsx3'
            )
            self.get_logger().error(str(exc))
            self._publish_tts_status('error', '', f'Import failed: {exc}')
            return

        self._publish_tts_status('loading')
        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', int(self.get_parameter('rate').value))
            engine.setProperty('volume', float(self.get_parameter('volume').value))

            voice = str(self.get_parameter('voice').value)
            if voice:
                engine.setProperty('voice', voice)
            self._publish_tts_status('ready')
        except Exception as exc:
            self.get_logger().error(f'pyttsx3 init failed: {exc}')
            self._publish_tts_status('error', '', f'Init failed: {exc}')
            return

        while not self.stop_event.is_set():
            try:
                text = self.text_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if not text:
                continue
            text = self._normalize_numbers(text)
            self._print_if_enabled(text)
            self.tts_active_pub.publish(Bool(data=True))
            self._publish_tts_status('speaking', text)
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                self.get_logger().error(f'pyttsx3 failed: {exc}')
                self._publish_tts_status('error', text, str(exc))
            finally:
                self.tts_active_pub.publish(Bool(data=False))
                self._publish_tts_status('idle')

    def _speak_with_espeak(self, text: str) -> None:
        text = self._normalize_numbers(text)
        executable = str(self.get_parameter('espeak_executable').value)
        language = str(self.get_parameter('language').value)
        rate = str(self.get_parameter('rate').value)
        command = [executable, '-v', language, '-s', rate, text]
        self._run_command(command, 'espeak-ng')

    def _speak_with_piper(self, text: str) -> None:
        text = self._normalize_numbers(text)
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

    @staticmethod
    def _num_to_chinese(num_str: str, read_individual: bool = False) -> str:
        chs_digits = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
        if read_individual or len(num_str) > 4:
            return ''.join(chs_digits[int(d)] for d in num_str if d.isdigit())

        try:
            val = int(num_str)
        except ValueError:
            return num_str

        if val == 0:
            return '零'
        units = ['', '十', '百', '千', '万', '十', '百', '千', '亿']
        result = []
        length = len(num_str)
        for i, char in enumerate(num_str):
            digit = int(char)
            power = length - i - 1
            if digit != 0:
                # Optimize 10-19: 15 is spoken as "十五" instead of "一十五"
                if power == 1 and digit == 1 and i == 0:
                    result.append('十')
                else:
                    result.append(chs_digits[digit] + units[power])
            else:
                if not result or result[-1] == '零':
                    continue
                if power > 0 and num_str[i+1:] != '0'*power:
                    result.append('零')
        res = ''.join(result)
        if res.endswith('零') and len(res) > 1:
            res = res[:-1]
        return res

    def _normalize_numbers(self, text: str) -> str:
        import re
        if not text:
            return text

        # Treat 4-digit years specially by spelling them digit-by-digit (e.g. 2026年 -> 二零二六)
        def repl_year(match):
            num = match.group(1)
            return self._num_to_chinese(num, read_individual=True) + match.group(2)
        text = re.sub(r'(\d{4})(年)', repl_year, text)

        # Treat regular integers by value
        def repl_val(match):
            num = match.group(0)
            return self._num_to_chinese(num)
        text = re.sub(r'\d+', repl_val, text)
        return text

    def _run_edge_tts_worker(self) -> None:
        try:
            import asyncio
            import edge_tts
        except ImportError as exc:
            self.get_logger().error('Missing edge-tts. Install with: python3 -m pip install edge-tts')
            self._publish_tts_status('error', '', f'Import failed: {exc}')
            return

        self._publish_tts_status('ready')
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _speak(text):
            voice = str(self.get_parameter('voice').value).strip()
            if not voice or not voice.startswith('zh-'):
                voice = 'zh-CN-XiaoxiaoNeural'
            with tempfile.TemporaryDirectory() as temp_dir:
                mp3_path = Path(temp_dir) / 'reply.mp3'
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(str(mp3_path))
                self._run_command(['mpg123', '-q', str(mp3_path)], 'mpg123')

        while not self.stop_event.is_set():
            try:
                text = self.text_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if not text:
                continue
            text = self._normalize_numbers(text)
            self._print_if_enabled(text)
            self.tts_active_pub.publish(Bool(data=True))
            self._publish_tts_status('speaking', text)
            try:
                loop.run_until_complete(_speak(text))
            except Exception as exc:
                self.get_logger().error(f'edge-tts failed: {exc}')
                self._publish_tts_status('error', text, str(exc))
            finally:
                self.tts_active_pub.publish(Bool(data=False))
                self._publish_tts_status('idle')


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = LocalTtsNode()
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
