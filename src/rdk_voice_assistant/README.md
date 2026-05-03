# rdk_voice_assistant

ROS2 voice assistant bridge for the home companion robot project.

The package accepts text or local speech commands, parses simple Chinese
intents, publishes assistant replies, and reserves patrol, safety, TTS, STT, and
Nav2 integration interfaces.

## Interfaces

- Subscribe: `/voice/command_text` (`std_msgs/String`)
- Publish: `/voice/intent` (`std_msgs/String`, JSON)
- Publish: `/assistant/reply_text` (`std_msgs/String`)
- Publish: `/voice/robot_task` (`std_msgs/String`, JSON)
- Publish: `/voice/safety_command` (`std_msgs/String`)
- Publish: `/voice/partial_text` (`std_msgs/String`, optional STT partial text)
- Optional action client: `/navigate_to_pose` (`nav2_msgs/action/NavigateToPose`)

## Text Command Test

```bash
colcon build --symlink-install --packages-select rdk_voice_assistant
source install/setup.bash
ros2 launch rdk_voice_assistant voice_assistant.launch.py
```

In another terminal:

```bash
ros2 topic pub --once /voice/command_text std_msgs/msg/String "{data: '去客厅'}"
ros2 topic echo /assistant/reply_text
ros2 topic echo /voice/intent
```

Navigation is disabled by default. After the real map coordinates are filled in
`config/places.yaml`, enable it with:

```bash
ros2 launch rdk_voice_assistant voice_assistant.launch.py enable_navigation:=true
```

## RDK Official Voice Path

The recommended RDK path is:

```text
sensevoice_ros2
↓
/asr_text
↓
rdk_asr_bridge_node
↓
/voice/command_text
↓
voice_assistant_node
↓
/assistant/reply_text
↓
rdk_tts_bridge_node
↓
/tts_text
↓
hobot_tts
```

The bridge nodes keep the internal assistant interface stable. If the official
ASR/TTS topic names or payloads change later, update only
`config/rdk_official_voice.yaml`.

Install the official TTS package and model on RDK:

```bash
sudo apt update
sudo apt install tros-humble-hobot-tts
source /opt/tros/humble/setup.bash
wget http://archive.d-robotics.cc/tts-model/tts_model.tar.gz
sudo tar -xf tts_model.tar.gz -C /opt/tros/${TROS_DISTRO}/lib/hobot_tts/
```

Install and configure the official ASR package according to the current RDK
TROS version. RDK X5 TROS releases include `sensevoice_ros2` configuration
support in recent versions.

Build this assistant package:

```bash
cd ~/rdkrobot_ws
colcon build --symlink-install --packages-select rdk_voice_assistant
source install/setup.bash
```

Start only the assistant plus official bridge nodes:

```bash
ros2 launch rdk_voice_assistant rdk_official_voice.launch.py
```

Start the bridge and also try to start official RDK TTS/ASR nodes from the same
launch file:

```bash
ros2 launch rdk_voice_assistant rdk_official_voice.launch.py \
  start_sensevoice:=true \
  start_hobot_tts:=true
```

If the official executable names differ on your image, override them:

```bash
ros2 launch rdk_voice_assistant rdk_official_voice.launch.py \
  start_sensevoice:=true \
  sensevoice_package:=sensevoice_ros2 \
  sensevoice_executable:=sensevoice_ros2 \
  start_hobot_tts:=true \
  hobot_tts_package:=hobot_tts \
  hobot_tts_executable:=hobot_tts
```

Bridge-only tests without official ASR/TTS:

```bash
ros2 launch rdk_voice_assistant rdk_official_voice.launch.py
ros2 topic pub --once /asr_text std_msgs/msg/String "{data: '去客厅'}"
ros2 topic echo /tts_text
```

Useful debug topics:

```bash
ros2 topic echo /asr_text
ros2 topic echo /voice/command_text
ros2 topic echo /voice/intent
ros2 topic echo /assistant/reply_text
ros2 topic echo /tts_text
```

### RDK Bridge Tuning

- `official_asr_text_topic`: official ASR output topic. Default `/asr_text`.
- `official_tts_text_topic`: official TTS input topic. Default `/tts_text`.
- `json_text_key`: set this if the ASR node outputs JSON text instead of plain
  text.
- `require_wake_word`: set to `true` before demos to reduce accidental commands.
- `wake_words`: comma-separated words, for example `小智,机器人`.
- `max_text_length`: trims overly long replies before sending them to TTS.

Example wake-word setup in `config/rdk_official_voice.yaml`:

```yaml
rdk_asr_bridge_node:
  ros__parameters:
    require_wake_word: true
    wake_words: 小智,机器人
```

## Local Fallback STT and TTS

Local STT uses Vosk. Local TTS supports `pyttsx3`, `espeak`, `piper`, and
`print`. This path is kept as a fallback when the official RDK packages or
models are not ready yet.

Install runtime dependencies on the robot or Ubuntu ROS2 machine:

```bash
sudo apt update
sudo apt install -y python3-pip portaudio19-dev espeak-ng alsa-utils
python3 -m pip install -r src/rdk_voice_assistant/requirements-local-voice.txt
```

Download a local Chinese Vosk model, unzip it on the robot, and remember the
folder path. Example model folder name:

```text
vosk-model-small-cn-0.22
```

Start the full local voice chain:

```bash
colcon build --symlink-install --packages-select rdk_voice_assistant
source install/setup.bash
ros2 launch rdk_voice_assistant local_voice.launch.py model_path:=/path/to/vosk-model-small-cn-0.22
```

Say one of these commands near the microphone:

```text
去客厅
去门口
开始巡查
停止
回起点
你是谁
```

Useful debug terminals:

```bash
ros2 topic echo /voice/command_text
ros2 topic echo /voice/intent
ros2 topic echo /assistant/reply_text
ros2 topic echo /voice/robot_task
```

TTS-only test:

```bash
ros2 run rdk_voice_assistant local_tts_node --ros-args -p engine:=pyttsx3
ros2 topic pub --once /assistant/reply_text std_msgs/msg/String "{data: '你好，我是家庭陪伴机器人'}"
```

STT-only test:

```bash
ros2 run rdk_voice_assistant local_stt_node --ros-args -p model_path:=/path/to/vosk-model-small-cn-0.22
ros2 topic echo /voice/command_text
```

If `pyttsx3` has no Chinese voice, try espeak:

```bash
ros2 launch rdk_voice_assistant local_voice.launch.py model_path:=/path/to/vosk-model-small-cn-0.22 tts_engine:=espeak
```

For silent debugging without speaker output:

```bash
ros2 launch rdk_voice_assistant local_voice.launch.py model_path:=/path/to/vosk-model-small-cn-0.22 tts_engine:=print
```

## Tuning

- `sample_rate`: keep `16000` for Vosk models unless the model says otherwise.
- `block_size`: lower values reduce latency but may increase CPU usage. Try
  `4000`, `8000`, and `12000`.
- `require_wake_word`: set to `true` before demos to reduce accidental commands.
- `wake_words`: comma-separated words, for example `小智,机器人`.
- `publish_partial`: set to `true` while debugging recognition latency.
- `rate`: TTS speaking speed. Try `150` to `190`.
- `voice`: pyttsx3 voice id. Leave empty first, then tune after listing system
  voices.

Example wake-word setup:

```bash
ros2 launch rdk_voice_assistant local_voice.launch.py \
  model_path:=/path/to/vosk-model-small-cn-0.22 \
  start_stt:=true \
  start_tts:=true
```

Then edit `config/local_voice.yaml`:

```yaml
require_wake_word: true
wake_words: 小智,机器人
```
