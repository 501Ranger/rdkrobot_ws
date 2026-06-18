import json
import queue
import re
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

# Import Phase 2 helpers
from rdk_voice_assistant.voice_utils import (
    normalize_text,
    match_wake_word,
    should_drop_command
)
from rdk_voice_assistant.vad import VadCalibrator


class LocalSttNode(Node):
    """Offline microphone speech recognition supporting both Vosk and Sherpa-ONNX (SenseVoice)."""

    def __init__(self) -> None:
        super().__init__('local_stt_node')

        self.declare_parameter('command_text_topic', '/voice/command_text')
        self.declare_parameter('partial_text_topic', '/voice/partial_text')
        self.declare_parameter('reply_text_topic', '/assistant/reply_text')
        self.declare_parameter('dialog_control_topic', '/voice/dialog_control')
        self.declare_parameter('model_path', '')
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('block_size', 2000)
        self.declare_parameter('device', '')
        self.declare_parameter('language', 'zh-cn')
        self.declare_parameter('publish_partial', True)
        self.declare_parameter('require_wake_word', True)
        self.declare_parameter(
            'wake_words',
            '小智,小智小智,小志,小致,小治,小直,小知,晓智,小只,小枝,小支,小汁,肖智,机器人',
        )
        self.declare_parameter('remove_wake_word', True)
        self.declare_parameter('noise_threshold', 150)
        self.declare_parameter('silence_timeout_sec', 0.8)
        self.declare_parameter('wake_window_sec', 10.0)
        self.declare_parameter('tts_guard_sec', 1.2)
        self.declare_parameter('calibration_chunks', 12)
        self.declare_parameter('vad_threshold_scale', 1.35)
        self.declare_parameter('min_utterance_sec', 0.35)
        self.declare_parameter('max_speech_sec', 8.0)
        self.declare_parameter('command_cooldown_sec', 0.7)
        self.declare_parameter('duplicate_window_sec', 2.5)
        self.declare_parameter('max_audio_queue_chunks', 80)
        self.declare_parameter('min_text_length', 2)
        self.declare_parameter('bypass_words', '开,关,停,去,走')
        self.declare_parameter('enable_noise_filter', True)
        self.declare_parameter('noise_blacklist', 'yeah,ok,yes,no,oh,eh,ah,um,uh,hi,hello,哦,呃,啊,呀,吧,哈,嗯')
        self.declare_parameter('english_word_whitelist', 'go,stop,dock,map,slam')

        # Sherpa-ONNX SenseVoice ASR configurations
        self.declare_parameter('asr_engine', 'sherpa-onnx')
        self.declare_parameter('sherpa_onnx_asr_model', '~/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx')
        self.declare_parameter('sherpa_onnx_asr_tokens', '~/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt')
        self.declare_parameter('sherpa_onnx_asr_num_threads', 2)

        # Sherpa-ONNX Streaming Zipformer ASR configurations
        self.declare_parameter('sherpa_onnx_streaming_encoder', '~/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23/encoder-epoch-99-avg-1.int8.onnx')
        self.declare_parameter('sherpa_onnx_streaming_decoder', '~/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23/decoder-epoch-99-avg-1.int8.onnx')
        self.declare_parameter('sherpa_onnx_streaming_joiner', '~/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23/joiner-epoch-99-avg-1.int8.onnx')
        self.declare_parameter('sherpa_onnx_streaming_tokens', '~/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23/tokens.txt')

        # Xiaomi MiMo ASR configurations
        self.declare_parameter('mimo_api_key', '')
        self.declare_parameter('mimo_base_url', 'https://api.xiaomimimo.com/v1')
        self.declare_parameter('mimo_language', 'auto')

        self.command_pub = self.create_publisher(
            String,
            self.get_parameter('command_text_topic').value,
            10,
        )
        self.partial_pub = self.create_publisher(
            String,
            str(self.get_parameter('partial_text_topic').value),
            10,
        )
        self.reply_pub = self.create_publisher(
            String,
            str(self.get_parameter('reply_text_topic').value),
            10,
        )
        self.dialog_control_pub = self.create_publisher(
            String,
            str(self.get_parameter('dialog_control_topic').value),
            10,
        )

        self.tts_finished_time = 0.0
        self.tts_active = False
        self.create_subscription(
            Bool,
            '/voice/tts_active',
            self._on_tts_active,
            10,
        )

        self.calibrated_threshold = float(self.get_parameter('noise_threshold').value)
        self.calibration_rms = []
        self.recalibrate_flag = False
        self.calibration_lock = threading.Lock()

        self.status_pub = self.create_publisher(
            String,
            '/voice/stt_status',
            10,
        )

        self.create_subscription(
            Bool,
            '/voice/recalibrate_vad',
            self._on_recalibrate_vad,
            10,
        )

        # Initialize Calibrator helper
        noise_threshold = float(self.get_parameter('noise_threshold').value)
        vad_scale = float(self.get_parameter('vad_threshold_scale').value)
        cal_chunks = int(self.get_parameter('calibration_chunks').value)
        self.calibrator = VadCalibrator(cal_chunks, noise_threshold, vad_scale)

        # Dynamic Wake Window variables
        self.wake_active = False
        self.wake_timer: Optional[threading.Timer] = None
        self.wake_window_sec = float(self.get_parameter('wake_window_sec').value)
        self.last_command_text = ''
        self.last_command_time = 0.0

        # Select ASR engine worker thread
        asr_engine = str(self.get_parameter('asr_engine').value).lower()
        max_queue_chunks = max(4, int(self.get_parameter('max_audio_queue_chunks').value))
        self.audio_queue = queue.Queue(maxsize=max_queue_chunks)
        self.stop_event = threading.Event()

        if asr_engine == 'mimo' or asr_engine == 'mimo-v2.5-asr':
            self.worker = threading.Thread(target=self._run_mimo_asr, daemon=True)
            self.get_logger().info('Local STT node started with VAD & Dynamic Wake Window. Engine: Xiaomi MiMo V2.5 ASR')
        elif asr_engine == 'sherpa-onnx' or asr_engine == 'sherpa_onnx':
            self.worker = threading.Thread(target=self._run_sherpa_onnx_asr, daemon=True)
            self.get_logger().info('Local STT node started with VAD & Dynamic Wake Window. Engine: Sherpa-ONNX (SenseVoice)')
        elif asr_engine == 'sherpa-onnx-streaming' or asr_engine == 'sherpa_onnx_streaming':
            self.worker = threading.Thread(target=self._run_sherpa_onnx_streaming_asr, daemon=True)
            self.get_logger().info('Local STT node started with VAD & Dynamic Wake Window. Engine: Sherpa-ONNX-Streaming (Zipformer)')
        else:
            self.worker = threading.Thread(target=self._run_vosk, daemon=True)
            self.get_logger().info('Local STT node started with VAD & Dynamic Wake Window. Engine: Vosk')

        self.worker.start()

    def _resolve_path(self, path_str: str) -> Path:
        if not path_str:
            return Path()
        path = Path(path_str)
        if path.is_absolute():
            return path
        if path_str.startswith('~'):
            return path.expanduser()
        return Path.home() / path

    def destroy_node(self):
        self.stop_event.set()
        if self.wake_timer:
            self.wake_timer.cancel()
        if self.worker.is_alive():
            self.worker.join(timeout=2.0)
        return super().destroy_node()

    def _on_recalibrate_vad(self, msg: Bool) -> None:
        self.get_logger().info('Received request to recalibrate VAD noise threshold.')
        with self.calibration_lock:
            self.calibration_rms = []
            self.recalibrate_flag = True

    def _publish_stt_status(self, status: str, detail: str = '', rms: float = 0.0, threshold: float = 0.0) -> None:
        try:
            payload = {
                'status': status,
                'detail': detail,
                'rms': float(rms),
                'threshold': float(threshold),
                'wake_active': bool(self.wake_active),
                'tts_active': bool(self.tts_active)
            }
            self.status_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
        except Exception as e:
            self.get_logger().error(f'Failed to publish STT status: {e}')


    def _enqueue_audio(self, item) -> None:
        try:
            self.audio_queue.put_nowait(item)
            return
        except queue.Full:
            pass

        try:
            self.audio_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self.audio_queue.put_nowait(item)
        except queue.Full:
            pass

    def _clear_audio_queue(self) -> None:
        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                return

    def _calibration_chunk_count(self) -> int:
        return self.calibrator.calibration_chunks

    def _compute_vad_threshold(self, calibration_rms, noise_threshold: float):
        return self.calibrator.compute_threshold(calibration_rms)

    def _should_drop_command(self, text: str) -> bool:
        cooldown_sec = float(self.get_parameter('command_cooldown_sec').value)
        duplicate_window_sec = float(self.get_parameter('duplicate_window_sec').value)
        return should_drop_command(
            text,
            self.last_command_text,
            self.last_command_time,
            cooldown_sec,
            duplicate_window_sec,
            logger=self.get_logger()
        )

    def _run_mimo_asr(self) -> None:
        try:
            import io
            import base64
            import wave
            import requests
            import sounddevice as sd
        except ImportError as exc:
            self.get_logger().error(
                f'Missing dependencies for MiMo ASR. Please install requests and sounddevice: {exc}'
            )
            self._publish_stt_status('error', f'Import failed: {exc}', 0.0, self.calibrated_threshold)
            return

        api_key = str(self.get_parameter('mimo_api_key').value).strip()
        if not api_key:
            import os
            api_key = os.environ.get('MIMO_API_KEY', '').strip()
        if not api_key:
            # Auto-extract API key from llm_dialog.yaml
            try:
                import yaml
                from ament_index_python.packages import get_package_share_directory
                pkg_dir = Path(get_package_share_directory('rdk_voice_assistant'))
                llm_config_path = pkg_dir / 'config' / 'llm_dialog.yaml'
                if not llm_config_path.exists():
                    llm_config_path = pkg_dir / 'config' / 'llm_dialog.example.yaml'
                if llm_config_path.exists():
                    with open(llm_config_path, 'r', encoding='utf-8') as f:
                        cfg = yaml.safe_load(f)
                        api_key = cfg.get('llm_dialog_node', {}).get('ros__parameters', {}).get('api_key', '').strip()
            except Exception as e:
                self.get_logger().warn(f"Failed to auto-load key from llm_dialog.yaml: {e}")

        mimo_base_url = str(self.get_parameter('mimo_base_url').value).strip()
        mimo_language = str(self.get_parameter('mimo_language').value).strip()
        sample_rate = int(self.get_parameter('sample_rate').value)
        block_size = int(self.get_parameter('block_size').value)
        device = self._parse_device(str(self.get_parameter('device').value))

        noise_threshold = int(self.get_parameter('noise_threshold').value)
        silence_timeout_sec = float(self.get_parameter('silence_timeout_sec').value)

        block_duration = block_size / sample_rate
        max_silent_blocks = max(1, int(silence_timeout_sec / block_duration))
        max_buffer_samples = int(float(self.get_parameter('max_speech_sec').value) * sample_rate)
        min_utterance_samples = int(float(self.get_parameter('min_utterance_sec').value) * sample_rate)
        calibration_chunks = self._calibration_chunk_count()

        audio_buffer = []
        buffer_samples = 0
        in_speech = False
        silent_block_count = 0

        def callback(indata, frames, time, status):
            if status:
                self.get_logger().warn(str(status))
            # Calculate RMS energy of this audio chunk
            rms = np.sqrt(np.mean(indata**2)) * 32768.0 if len(indata) > 0 else 0.0
            self._enqueue_audio((indata.copy(), rms))

        # Check recalibrate flag
        with self.calibration_lock:
            self.calibration_rms = []
            self.calibrated_threshold = float(noise_threshold)
            self.recalibrate_flag = False

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=device,
                dtype='float32',
                channels=1,
                callback=callback,
            ):
                self.get_logger().info(
                    f'Microphone opened (MiMo ASR). sample_rate={sample_rate}, device={device or "default"}, '
                    f'block_size={block_size} (VAD period={block_duration*1000:.1f}ms)'
                )
                while not self.stop_event.is_set():
                    try:
                        data_tuple = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    chunk, rms = data_tuple

                    # Check for recalibration request
                    with self.calibration_lock:
                        if self.recalibrate_flag:
                            self.recalibrate_flag = False
                            self.calibration_rms = []
                            audio_buffer = []
                            buffer_samples = 0
                            in_speech = False
                            silent_block_count = 0
                            self._publish_stt_status('calibrating', 'Recalibrating VAD noise threshold...', rms, self.calibrated_threshold)

                    # If TTS is active, keep the recording buffer clean and empty
                    if self.tts_active:
                        audio_buffer = []
                        buffer_samples = 0
                        in_speech = False
                        silent_block_count = 0
                        self._publish_stt_status('sleeping', 'Ignored: TTS Active', rms, self.calibrated_threshold)
                        continue

                    # VAD Auto-Calibration (first 1.5 seconds)
                    with self.calibration_lock:
                        cal_len = len(self.calibration_rms)
                    if cal_len < calibration_chunks:
                        with self.calibration_lock:
                            self.calibration_rms.append(rms)
                            cal_len = len(self.calibration_rms)
                            if cal_len == calibration_chunks:
                                self.calibrated_threshold, ambient_rms, spread = self._compute_vad_threshold(
                                    self.calibration_rms,
                                    float(noise_threshold),
                                )
                                self.get_logger().info(
                                    f'VAD Auto-Calibration Complete. Ambient RMS: {ambient_rms:.1f}. '
                                    f'Adaptive Threshold set to: {self.calibrated_threshold:.1f}. Spread: {spread:.2f}'
                                )
                        self._publish_stt_status('calibrating', 'Calibrating VAD noise threshold...', rms, self.calibrated_threshold)
                        continue

                    # Noise gate VAD
                    if rms < self.calibrated_threshold:
                        silent_block_count += 1
                        if in_speech:
                            audio_buffer.append(chunk)
                            buffer_samples += len(chunk)
                    else:
                        silent_block_count = 0
                        in_speech = True
                        audio_buffer.append(chunk)
                        buffer_samples += len(chunk)

                    # Determine status and publish real-time info
                    if in_speech:
                        status = 'recording'
                        detail = 'Speaking...'
                    elif self.wake_active or not bool(self.get_parameter('require_wake_word').value):
                        status = 'listening'
                        detail = 'Listening...'
                    else:
                        status = 'sleeping'
                        detail = 'Waiting for wake word'
                    self._publish_stt_status(status, detail, rms, self.calibrated_threshold)

                    # Silence timeout reached during speech: trigger MiMo transcription!
                    if in_speech and (
                        silent_block_count >= max_silent_blocks
                        or buffer_samples >= max_buffer_samples
                    ):
                        if buffer_samples < min_utterance_samples:
                            audio_buffer = []
                            buffer_samples = 0
                            in_speech = False
                            silent_block_count = 0
                            continue
                        full_audio = np.concatenate(audio_buffer, axis=0).flatten()
                        audio_buffer = []
                        buffer_samples = 0
                        in_speech = False
                        silent_block_count = 0

                        # Start transcription thread to avoid blocking the audio queue processing
                        threading.Thread(
                            target=self._transcribe_mimo,
                            args=(full_audio, sample_rate, api_key, mimo_base_url, mimo_language),
                            daemon=True
                        ).start()
        except Exception as exc:
            self.get_logger().error(f'MiMo STT stream loop failed: {exc}')

    def _transcribe_mimo(self, audio_data: np.ndarray, sample_rate: int, api_key: str, base_url: str, language: str) -> None:
        try:
            import io
            import base64
            import wave
            import requests

            if not api_key:
                self.get_logger().error("MiMo API Key is empty. Please set MIMO_API_KEY environment variable.")
                self._publish_stt_status('error', 'API Key missing', 0.0, self.calibrated_threshold)
                return

            self._publish_stt_status('decoding', 'MiMo decoding audio segment...', 0.0, self.calibrated_threshold)

            # Convert numpy float32 to int16 PCM WAV bytes
            pcm16 = (audio_data * 32767.0).clip(-32768, 32767).astype(np.int16)
            wav_io = io.BytesIO()
            with wave.open(wav_io, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm16.tobytes())
            
            wav_bytes = wav_io.getvalue()
            audio_base64 = base64.b64encode(wav_bytes).decode('utf-8')
            audio_data_url = f"data:audio/wav;base64,{audio_base64}"

            # Prepare API request payload
            headers = {
                "api-key": api_key,
                "Content-Type": "application/json"
            }
            payload = {
                "model": "mimo-v2.5-asr",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": audio_data_url
                                }
                            }
                        ]
                    }
                ],
                "asr_options": {
                    "language": language
                }
            }

            url = f"{base_url.rstrip('/')}/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=8.0)
            if response.status_code != 200:
                self.get_logger().error(f"MiMo ASR API error (HTTP {response.status_code}): {response.text}")
                self._publish_stt_status('error', f'API Error {response.status_code}', 0.0, self.calibrated_threshold)
                return

            res_json = response.json()
            text = res_json['choices'][0]['message']['content'].strip()
            text = re.sub(r'<\|.*?\|>', '', text).strip()
            
            self._handle_final_text(text)
        except Exception as e:
            self.get_logger().error(f"MiMo transcription failed: {e}")
            self._publish_stt_status('error', f"Transcription failed: {e}", 0.0, self.calibrated_threshold)

    def _run_sherpa_onnx_asr(self) -> None:
        try:
            import sherpa_onnx
            import sounddevice as sd
        except ImportError as exc:
            self.get_logger().error(
                'Missing sherpa-onnx or sounddevice. Install with: '
                'python3 -m pip install sherpa-onnx sounddevice'
            )
            self.get_logger().error(str(exc))
            return

        model_path = str(self._resolve_path(self.get_parameter('sherpa_onnx_asr_model').value))
        tokens_path = str(self._resolve_path(self.get_parameter('sherpa_onnx_asr_tokens').value))
        num_threads = int(self.get_parameter('sherpa_onnx_asr_num_threads').value)
        sample_rate = int(self.get_parameter('sample_rate').value)
        block_size = int(self.get_parameter('block_size').value)
        device = self._parse_device(str(self.get_parameter('device').value))

        noise_threshold = int(self.get_parameter('noise_threshold').value)
        silence_timeout_sec = float(self.get_parameter('silence_timeout_sec').value)

        block_duration = block_size / sample_rate
        max_silent_blocks = max(1, int(silence_timeout_sec / block_duration))
        max_buffer_samples = int(float(self.get_parameter('max_speech_sec').value) * sample_rate)
        min_utterance_samples = int(float(self.get_parameter('min_utterance_sec').value) * sample_rate)
        calibration_chunks = self._calibration_chunk_count()

        if not Path(model_path).exists():
            self.get_logger().error(
                f'SenseVoice model not found at: {model_path}. '
                'Download the sherpa-onnx-sense-voice model and place it correctly.'
            )
            return

        self.get_logger().info(f'Loading SenseVoice ASR model: {model_path}')
        try:
            # Correct structural configuration matching the verified from_sense_voice API
            recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model_path,
                tokens=tokens_path,
                num_threads=num_threads,
                use_itn=True
            )
            self.get_logger().info('SenseVoice offline recognizer loaded successfully.')
        except Exception as exc:
            self.get_logger().error(f'Failed to initialize SenseVoice: {exc}')
            return

        audio_buffer = []
        buffer_samples = 0
        in_speech = False
        silent_block_count = 0

        def callback(indata, frames, time, status):
            if status:
                self.get_logger().warn(str(status))
            # Calculate RMS energy of this audio chunk
            rms = np.sqrt(np.mean(indata**2)) * 32768.0 if len(indata) > 0 else 0.0
            self._enqueue_audio((indata.copy(), rms))

        # Check recalibrate flag
        with self.calibration_lock:
            self.calibration_rms = []
            self.calibrated_threshold = float(noise_threshold)
            self.recalibrate_flag = False

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=device,
                dtype='float32',
                channels=1,
                callback=callback,
            ):
                self.get_logger().info(
                    f'Microphone opened (Sherpa-ONNX). sample_rate={sample_rate}, device={device or "default"}, '
                    f'block_size={block_size} (VAD period={block_duration*1000:.1f}ms)'
                )
                while not self.stop_event.is_set():
                    try:
                        data_tuple = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    chunk, rms = data_tuple

                    # Check for recalibration request
                    with self.calibration_lock:
                        if self.recalibrate_flag:
                            self.recalibrate_flag = False
                            self.calibration_rms = []
                            audio_buffer = []
                            buffer_samples = 0
                            in_speech = False
                            silent_block_count = 0
                            self._publish_stt_status('calibrating', 'Recalibrating VAD noise threshold...', rms, self.calibrated_threshold)

                    # If TTS is active, keep the recording buffer clean and empty
                    if self.tts_active:
                        audio_buffer = []
                        buffer_samples = 0
                        in_speech = False
                        silent_block_count = 0
                        self._publish_stt_status('sleeping', 'Ignored: TTS Active', rms, self.calibrated_threshold)
                        continue

                    # VAD Auto-Calibration (first 1.5 seconds)
                    with self.calibration_lock:
                        cal_len = len(self.calibration_rms)
                    if cal_len < calibration_chunks:
                        with self.calibration_lock:
                            self.calibration_rms.append(rms)
                            cal_len = len(self.calibration_rms)
                            if cal_len == calibration_chunks:
                                self.calibrated_threshold, ambient_rms, spread = self._compute_vad_threshold(
                                    self.calibration_rms,
                                    float(noise_threshold),
                                )
                                self.get_logger().info(
                                    f'VAD Auto-Calibration Complete. Ambient RMS: {ambient_rms:.1f}. '
                                    f'Adaptive Threshold set to: {self.calibrated_threshold:.1f}. Spread: {spread:.2f}'
                                )
                        self._publish_stt_status('calibrating', 'Calibrating VAD noise threshold...', rms, self.calibrated_threshold)
                        continue

                    # Noise gate VAD
                    if rms < self.calibrated_threshold:
                        silent_block_count += 1
                        if in_speech:
                            audio_buffer.append(chunk)
                            buffer_samples += len(chunk)
                    else:
                        silent_block_count = 0
                        in_speech = True
                        audio_buffer.append(chunk)
                        buffer_samples += len(chunk)

                    # Determine status and publish real-time info
                    if in_speech:
                        status = 'recording'
                        detail = 'Speaking...'
                    elif self.wake_active or not bool(self.get_parameter('require_wake_word').value):
                        status = 'listening'
                        detail = 'Listening...'
                    else:
                        status = 'sleeping'
                        detail = 'Waiting for wake word'
                    self._publish_stt_status(status, detail, rms, self.calibrated_threshold)

                    # Silence timeout reached during speech: trigger SenseVoice transcription!
                    if in_speech and (
                        silent_block_count >= max_silent_blocks
                        or buffer_samples >= max_buffer_samples
                    ):
                        if buffer_samples < min_utterance_samples:
                            audio_buffer = []
                            buffer_samples = 0
                            in_speech = False
                            silent_block_count = 0
                            continue
                        full_audio = np.concatenate(audio_buffer, axis=0).flatten()
                        audio_buffer = []
                        buffer_samples = 0
                        in_speech = False
                        silent_block_count = 0

                        try:
                            self._publish_stt_status('decoding', 'SenseVoice decoding audio segment...', 0.0, self.calibrated_threshold)
                            stream = recognizer.create_stream()
                            stream.accept_waveform(sample_rate, full_audio)
                            recognizer.decode_stream(stream)
                            text = stream.result.text.strip()
                            # Clean SenseVoice specific system tags like <|zh|>, <|happy|>, etc.
                            text = re.sub(r'<\|.*?\|>', '', text).strip()
                            self._handle_final_text(text)
                        except Exception as e:
                            self.get_logger().error(f'SenseVoice decoding failed: {e}')
                            self._publish_stt_status('error', f'SenseVoice decoding failed: {e}', 0.0, self.calibrated_threshold)
        except Exception as exc:
            self.get_logger().error(f'SenseVoice STT stream loop failed: {exc}')

    def _run_sherpa_onnx_streaming_asr(self) -> None:
        try:
            import sherpa_onnx
            import sounddevice as sd
        except ImportError as exc:
            self.get_logger().error(
                'Missing sherpa-onnx or sounddevice. Install with: '
                'python3 -m pip install sherpa-onnx sounddevice'
            )
            self.get_logger().error(str(exc))
            return

        encoder_path = str(self._resolve_path(self.get_parameter('sherpa_onnx_streaming_encoder').value))
        decoder_path = str(self._resolve_path(self.get_parameter('sherpa_onnx_streaming_decoder').value))
        joiner_path = str(self._resolve_path(self.get_parameter('sherpa_onnx_streaming_joiner').value))
        tokens_path = str(self._resolve_path(self.get_parameter('sherpa_onnx_streaming_tokens').value))
        num_threads = int(self.get_parameter('sherpa_onnx_asr_num_threads').value)
        sample_rate = int(self.get_parameter('sample_rate').value)
        block_size = int(self.get_parameter('block_size').value)
        device = self._parse_device(str(self.get_parameter('device').value))

        noise_threshold = int(self.get_parameter('noise_threshold').value)
        silence_timeout_sec = float(self.get_parameter('silence_timeout_sec').value)

        block_duration = block_size / sample_rate
        max_silent_blocks = max(1, int(silence_timeout_sec / block_duration))
        max_speech_blocks = max(1, int(float(self.get_parameter('max_speech_sec').value) / block_duration))
        min_speech_blocks = max(1, int(float(self.get_parameter('min_utterance_sec').value) / block_duration))
        calibration_chunks = self._calibration_chunk_count()

        # Validate paths
        for path_name, p in [('encoder', encoder_path), ('decoder', decoder_path),
                             ('joiner', joiner_path), ('tokens', tokens_path)]:
            if not Path(p).exists():
                self.get_logger().error(f'Zipformer streaming ASR file not found at {path_name}: {p}')
                return

        self.get_logger().info(f'Loading Zipformer streaming model from: {Path(encoder_path).parent}')
        try:
            recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=tokens_path,
                encoder=encoder_path,
                decoder=decoder_path,
                joiner=joiner_path,
                num_threads=num_threads,
                sample_rate=sample_rate,
                feature_dim=80,
                decoding_method='greedy_search',
            )
            self.get_logger().info('Zipformer streaming recognizer loaded successfully.')
        except Exception as exc:
            self.get_logger().error(f'Failed to initialize Zipformer streaming: {exc}')
            return

        in_speech = False
        silent_block_count = 0
        speech_block_count = 0
        stream = None
        last_partial_text = ""

        def callback(indata, frames, time, status):
            if status:
                self.get_logger().warn(str(status))
            # Calculate RMS energy of this audio chunk in float64 to avoid overflow
            rms = np.sqrt(np.mean(indata**2)) * 32768.0 if len(indata) > 0 else 0.0
            self._enqueue_audio((indata.copy(), rms))

        # Check recalibrate flag
        with self.calibration_lock:
            self.calibration_rms = []
            self.calibrated_threshold = float(noise_threshold)
            self.recalibrate_flag = False

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=device,
                dtype='float32',
                channels=1,
                callback=callback,
            ):
                self.get_logger().info(
                    f'Microphone opened (Sherpa-ONNX-Streaming). sample_rate={sample_rate}, device={device or "default"}, '
                    f'block_size={block_size} (VAD period={block_duration*1000:.1f}ms)'
                )
                while not self.stop_event.is_set():
                    try:
                        data_tuple = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    chunk, rms = data_tuple

                    # Check for recalibration request
                    with self.calibration_lock:
                        if self.recalibrate_flag:
                            self.recalibrate_flag = False
                            self.calibration_rms = []
                            in_speech = False
                            silent_block_count = 0
                            speech_block_count = 0
                            stream = None
                            last_partial_text = ""
                            self._publish_stt_status('calibrating', 'Recalibrating VAD noise threshold...', rms, self.calibrated_threshold)

                    # If TTS is active, keep the streaming recognizer clean and empty
                    if self.tts_active:
                        in_speech = False
                        silent_block_count = 0
                        speech_block_count = 0
                        stream = None
                        last_partial_text = ""
                        self._publish_stt_status('sleeping', 'Ignored: TTS Active', rms, self.calibrated_threshold)
                        continue

                    # VAD Auto-Calibration (first 1.5 seconds)
                    with self.calibration_lock:
                        cal_len = len(self.calibration_rms)
                    if cal_len < calibration_chunks:
                        with self.calibration_lock:
                            self.calibration_rms.append(rms)
                            cal_len = len(self.calibration_rms)
                            if cal_len == calibration_chunks:
                                self.calibrated_threshold, ambient_rms, spread = self._compute_vad_threshold(
                                    self.calibration_rms,
                                    float(noise_threshold),
                                )
                                self.get_logger().info(
                                    f'VAD Auto-Calibration Complete. Ambient RMS: {ambient_rms:.1f}. '
                                    f'Adaptive Threshold set to: {self.calibrated_threshold:.1f}. Spread: {spread:.2f}'
                                )
                        self._publish_stt_status('calibrating', 'Calibrating VAD noise threshold...', rms, self.calibrated_threshold)
                        continue

                    if rms < self.calibrated_threshold:
                        silent_block_count += 1
                    else:
                        silent_block_count = 0
                        if not in_speech and not self.tts_active:
                            in_speech = True
                            speech_block_count = 0
                            stream = recognizer.create_stream()
                            last_partial_text = ""

                    # Determine status and publish real-time info
                    if in_speech:
                        status = 'recording'
                        detail = 'Speaking...'
                    elif self.wake_active or not bool(self.get_parameter('require_wake_word').value):
                        status = 'listening'
                        detail = 'Listening...'
                    else:
                        status = 'sleeping'
                        detail = 'Waiting for wake word'
                    self._publish_stt_status(status, detail, rms, self.calibrated_threshold)

                    if in_speech and stream is not None:
                        speech_block_count += 1
                        stream.accept_waveform(sample_rate, chunk.flatten())
                        while recognizer.is_ready(stream):
                            recognizer.decode_stream(stream)
                        partial_text = recognizer.get_result(stream).strip()
                        if partial_text and partial_text != last_partial_text:
                            last_partial_text = partial_text
                            cleaned_partial = partial_text
                            wake_word = self._match_wake_word(partial_text)
                            if wake_word and bool(self.get_parameter('remove_wake_word').value):
                                cleaned_partial = partial_text.replace(wake_word, '', 1).strip()
                            if cleaned_partial or self.wake_active:
                                self.partial_pub.publish(String(data=cleaned_partial))

                    if in_speech and (
                        silent_block_count >= max_silent_blocks
                        or speech_block_count >= max_speech_blocks
                    ):
                        in_speech = False
                        silent_block_count = 0
                        if stream is not None:
                            if speech_block_count >= min_speech_blocks:
                                self._publish_stt_status('decoding', 'Finalizing speech segment...', 0.0, self.calibrated_threshold)
                                final_text = recognizer.get_result(stream).strip()
                                self._handle_final_text(final_text)
                            stream = None
                            speech_block_count = 0
                            last_partial_text = ""
        except Exception as exc:
            self.get_logger().error(f'Zipformer streaming STT stream loop failed: {exc}')

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

        # 1. Parameter loading and calculations
        model_path = str(self._resolve_path(self.get_parameter('model_path').value))
        sample_rate = int(self.get_parameter('sample_rate').value)
        block_size = int(self.get_parameter('block_size').value)
        device = self._parse_device(str(self.get_parameter('device').value))
        noise_threshold = int(self.get_parameter('noise_threshold').value)
        silence_timeout_sec = float(self.get_parameter('silence_timeout_sec').value)

        block_duration = block_size / sample_rate
        max_silent_blocks = max(1, int(silence_timeout_sec / block_duration))
        max_speech_blocks = max(1, int(float(self.get_parameter('max_speech_sec').value) / block_duration))
        min_speech_blocks = max(1, int(float(self.get_parameter('min_utterance_sec').value) / block_duration))
        calibration_chunks = self._calibration_chunk_count()

        # 2. Check and load Vosk model and recognizer
        if not Path(model_path).exists():
            self.get_logger().error(f'Vosk model not found at: {model_path}')
            self._publish_stt_status('error', f'Vosk model not found at: {model_path}')
            return

        self.get_logger().info(f'Loading Vosk ASR model: {model_path}')
        self._publish_stt_status('loading')
        try:
            model = Model(model_path)
            recognizer = KaldiRecognizer(model, sample_rate)
            self.get_logger().info('Vosk recognizer loaded successfully.')
            self._publish_stt_status('ready')
        except Exception as exc:
            self.get_logger().error(f'Failed to initialize Vosk: {exc}')
            self._publish_stt_status('error', '', f'Load failed: {exc}')
            return

        # 3. Initialize loop state variables to avoid UnboundLocalError
        in_speech = False
        silent_block_count = 0
        speech_block_count = 0

        # 4. Define audio recording callback function
        def callback(indata, frames, time, status):
            if status:
                self.get_logger().warn(str(status))
            # Vosk RawInputStream expects int16 bytes, compute RMS
            data_np = np.frombuffer(indata, dtype=np.int16)
            rms = np.sqrt(np.mean(data_np.astype(np.float32)**2)) if len(data_np) > 0 else 0.0
            self._enqueue_audio((indata, rms))

        # Check recalibrate flag
        with self.calibration_lock:
            self.calibration_rms = []
            self.calibrated_threshold = float(noise_threshold)
            self.recalibrate_flag = False

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
                    f'Microphone opened. sample_rate={sample_rate}, device={device or "default"}, '
                    f'block_size={block_size} (VAD period={block_duration*1000:.1f}ms)'
                )
                while not self.stop_event.is_set():
                    try:
                        data_tuple = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    chunk, rms = data_tuple

                    # Check for recalibration request
                    with self.calibration_lock:
                        if self.recalibrate_flag:
                            self.recalibrate_flag = False
                            self.calibration_rms = []
                            in_speech = False
                            silent_block_count = 0
                            speech_block_count = 0
                            recognizer.Reset()
                            self._publish_stt_status('calibrating', 'Recalibrating VAD noise threshold...', rms, self.calibrated_threshold)

                    # If TTS is active, keep the recording buffer clean and empty
                    if self.tts_active:
                        in_speech = False
                        silent_block_count = 0
                        speech_block_count = 0
                        recognizer.Reset()
                        self._publish_stt_status('sleeping', 'Ignored: TTS Active', rms, self.calibrated_threshold)
                        continue

                    # VAD Auto-Calibration (first 1.5 seconds)
                    with self.calibration_lock:
                        cal_len = len(self.calibration_rms)
                    if cal_len < calibration_chunks:
                        with self.calibration_lock:
                            self.calibration_rms.append(rms)
                            cal_len = len(self.calibration_rms)
                            if cal_len == calibration_chunks:
                                self.calibrated_threshold, ambient_rms, spread = self._compute_vad_threshold(
                                    self.calibration_rms,
                                    float(noise_threshold),
                                )
                                self.get_logger().info(
                                    f'VAD Auto-Calibration Complete. Ambient RMS: {ambient_rms:.1f}. '
                                    f'Adaptive Threshold set to: {self.calibrated_threshold:.1f}. Spread: {spread:.2f}'
                                )
                        self._publish_stt_status('calibrating', 'Calibrating VAD noise threshold...', rms, self.calibrated_threshold)
                        continue

                    # Noise gate VAD
                    if rms < self.calibrated_threshold:
                        silent_block_count += 1
                        # Feed pure silent bytes to Vosk to assist its internal silence detector
                        processed_chunk = bytes(len(chunk))
                    else:
                        silent_block_count = 0
                        in_speech = True
                        speech_block_count += 1
                        processed_chunk = chunk

                    # Determine status and publish real-time info
                    if in_speech:
                        status = 'recording'
                        detail = 'Speaking...'
                    elif self.wake_active or not bool(self.get_parameter('require_wake_word').value):
                        status = 'listening'
                        detail = 'Listening...'
                    else:
                        status = 'sleeping'
                        detail = 'Waiting for wake word'
                    self._publish_stt_status(status, detail, rms, self.calibrated_threshold)

                    # Silence timeout reached during speech: force segment the sentence immediately!
                    if in_speech and (
                        silent_block_count >= max_silent_blocks
                        or speech_block_count >= max_speech_blocks
                    ):
                        self._publish_stt_status('decoding', 'Vosk decoding audio segment...', 0.0, self.calibrated_threshold)
                        # Feed zero-buffer to trigger AcceptWaveform
                        recognizer.AcceptWaveform(bytes(block_size * 2))
                        text = self._extract_text(recognizer.Result(), key='text')
                        if speech_block_count >= min_speech_blocks:
                            self._handle_final_text(text)
                        in_speech = False
                        silent_block_count = 0
                        speech_block_count = 0
                        continue

                    if recognizer.AcceptWaveform(processed_chunk):
                        self._publish_stt_status('decoding', 'Vosk decoding audio segment...', 0.0, self.calibrated_threshold)
                        text = self._extract_text(recognizer.Result(), key='text')
                        self._handle_final_text(text)
                        in_speech = False
                        silent_block_count = 0
                        speech_block_count = 0
                    elif bool(self.get_parameter('publish_partial').value):
                        text = self._extract_text(recognizer.PartialResult(), key='partial')
                        if text:
                            # Strip wake word in partial display to keep dashboard neat
                            cleaned_partial = text
                            wake_word = self._match_wake_word(text)
                            if wake_word and bool(self.get_parameter('remove_wake_word').value):
                                cleaned_partial = text.replace(wake_word, '', 1).strip()
                            if cleaned_partial or self.wake_active:
                                self.partial_pub.publish(String(data=cleaned_partial))
        except Exception as exc:
            self.get_logger().error(f'Local STT failed: {exc}')

    def _on_tts_active(self, msg: Bool) -> None:
        if self.tts_active and not msg.data:
            # Transitioned from True to False: record finished timestamp
            self.tts_finished_time = time.time()
        self.tts_active = msg.data
        if self.tts_active:
            self._clear_audio_queue()

    def _handle_final_text(self, text: str) -> None:
        if self.tts_active:
            self.get_logger().info(f'Discarded STT text during active TTS playback: {text}')
            self._publish_stt_status('ignored_tts_active', text, 0.0, self.calibrated_threshold)
            return

        # Trailing guard window (e.g. 1.2 seconds) to prevent self-hearing of echoes/tail audio
        time_since_tts = time.time() - self.tts_finished_time
        tts_guard_sec = float(self.get_parameter('tts_guard_sec').value)
        if time_since_tts < tts_guard_sec:
            self.get_logger().info(
                f'Discarded STT text during trailing TTS guard window ({time_since_tts:.2f}s < {tts_guard_sec:.2f}s): {text}'
            )
            self._publish_stt_status('ignored_tts_active', text, 0.0, self.calibrated_threshold)
            return

        text = self._normalize_text(text)
        if not text:
            return

        require_wake_word = bool(self.get_parameter('require_wake_word').value)
        remove_wake_word = bool(self.get_parameter('remove_wake_word').value)
        wake_word = self._match_wake_word(text)

        if require_wake_word:
            if wake_word:
                # Woken up by wake word! Activate dialog window
                self._wakeup()
                self._publish_stt_status('wake_detected', f'Matched wake word: {wake_word}', 0.0, self.calibrated_threshold)
                if remove_wake_word:
                    text = text.replace(wake_word, '', 1).strip()

                # If they ONLY said the wake word, e.g. "小智", give vocal feedback
                if not text:
                    self.get_logger().info('Wake word detected. Cancelling stale dialog and replying welcome...')
                    self.dialog_control_pub.publish(String(data='wake'))
                    self.reply_pub.publish(String(data='__CLEAR__'))
                    self.reply_pub.publish(String(data='我在'))
                    return
            else:
                # No wake word: only allow if we are inside the active wake window
                if not self.wake_active:
                    self.get_logger().debug(f'Ignored speech without wake word while asleep: {text}')
                    self._publish_stt_status('ignored_no_wake_word', text, 0.0, self.calibrated_threshold)
                    return
                else:
                    # We are in the active window: refresh the timer!
                    self._reset_wake_timer()
        else:
            # Wake word not required, but if they said it, we strip it
            if wake_word and remove_wake_word:
                text = text.replace(wake_word, '', 1).strip()

        if not text:
            return

        # Multi-level noise and hallucination filtering
        enable_noise_filter = bool(self.get_parameter('enable_noise_filter').value)
        if enable_noise_filter:
            clean_text = text.lower().strip('.,!? ')
            
            # 1. 黑名单语气词过滤 (Blacklist)
            noise_blacklist_str = str(self.get_parameter('noise_blacklist').value)
            noise_blacklist = [w.strip().lower() for w in noise_blacklist_str.split(',') if w.strip()]
            if clean_text in noise_blacklist:
                self.get_logger().info(f'Discarded STT noise/hallucination word: {text}')
                self._publish_stt_status('ignored_too_short', text, 0.0, self.calibrated_threshold)
                return

            # 2. 单个未授权英文单词过滤 (Single English Word)
            import re
            if re.match(r'^[a-zA-Z]+$', clean_text):
                whitelist_str = str(self.get_parameter('english_word_whitelist').value)
                english_word_whitelist = [w.strip().lower() for w in whitelist_str.split(',') if w.strip()]
                if clean_text not in english_word_whitelist:
                    self.get_logger().info(f'Discarded single English noise word: {text}')
                    self._publish_stt_status('ignored_too_short', text, 0.0, self.calibrated_threshold)
                    return

        # Short text filtering (noise reduction)
        min_len = int(self.get_parameter('min_text_length').value)
        if len(text) < min_len:
            bypass_words_str = str(self.get_parameter('bypass_words').value)
            bypass_list = [w.strip() for w in bypass_words_str.split(',') if w.strip()]
            if text not in bypass_list:
                self.get_logger().info(f'Discarded STT text due to short length filter (len={len(text)} < {min_len}): {text}')
                self._publish_stt_status('ignored_too_short', text, 0.0, self.calibrated_threshold)
                return

        if self._should_drop_command(text):
            self._publish_stt_status('ignored_duplicate', text, 0.0, self.calibrated_threshold)
            return

        self.command_pub.publish(String(data=text))
        self.last_command_text = text
        self.last_command_time = time.time()
        self._publish_stt_status('final_text', text, 0.0, self.calibrated_threshold)
        self.get_logger().info(f'STT final (Active={self.wake_active}): {text}')

    def _wakeup(self) -> None:
        self.wake_active = True
        self.get_logger().info('System WOKEN UP. Dynamic Wake Window active.')
        if self.wake_timer:
            self.wake_timer.cancel()
        self.wake_timer = threading.Timer(self.wake_window_sec, self._sleep)
        self.wake_timer.start()

    def _reset_wake_timer(self) -> None:
        self.get_logger().info('Speech detected inside Wake Window. Refreshing active timer.')
        if self.wake_timer:
            self.wake_timer.cancel()
        self.wake_timer = threading.Timer(self.wake_window_sec, self._sleep)
        self.wake_timer.start()

    def _sleep(self) -> None:
        self.wake_active = False
        self.get_logger().info('Active Wake Window expired. Going back to sleep...')

    def _match_wake_word(self, text: str) -> Optional[str]:
        wake_words = str(self.get_parameter('wake_words').value)
        return match_wake_word(text, wake_words)

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
        return normalize_text(text)


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = LocalSttNode()
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
