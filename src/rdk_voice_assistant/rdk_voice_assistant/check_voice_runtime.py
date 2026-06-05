import os
import sys
import socket
from pathlib import Path
import yaml

def check_package(package_name):
    try:
        __import__(package_name)
        print(f"  [PASS] Python package '{package_name}' is installed.")
        return True
    except ImportError:
        print(f"  [FAIL] Python package '{package_name}' is MISSING.")
        return False

def check_file(label, path):
    if not path:
        print(f"  [SKIP] {label}: path is empty.")
        return True
    p = Path(path)
    if p.exists():
        print(f"  [PASS] {label} model file exists at: {path}")
        return True
    else:
        print(f"  [FAIL] {label} model file is MISSING at: {path}")
        return False

def is_port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            print(f"  [PASS] Port {port} is free and available.")
            return True
        except socket.error:
            print(f"  [FAIL] Port {port} is ALREADY IN USE.")
            return False

def main():
    print("=" * 60)
    print("RDK Voice Assistant Pre-flight Diagnostics Checker")
    print("=" * 60)

    all_passed = True

    # 1. Check python packages
    print("\n1. Checking Python Pip Dependencies:")
    packages = ['numpy', 'sounddevice', 'sherpa_onnx', 'aiohttp', 'edge_tts']
    for pkg in packages:
        if not check_package(pkg):
            all_passed = False

    # 2. Check sound devices
    print("\n2. Checking Audio Input/Output Hardware:")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devices = [d for d in devices if d['max_input_channels'] > 0]
        output_devices = [d for d in devices if d['max_output_channels'] > 0]
        
        print(f"  Total audio devices found: {len(devices)}")
        if input_devices:
            print(f"  [PASS] Detected {len(input_devices)} input device(s) (microphones).")
        else:
            print("  [WARN] No input devices (microphones) detected. STT may fail to start.")
            
        if output_devices:
            print(f"  [PASS] Detected {len(output_devices)} output device(s) (speakers).")
        else:
            print("  [WARN] No output devices (speakers) detected. TTS may fail to play sound.")
    except Exception as e:
        print(f"  [FAIL] Error querying sounddevice hardware: {e}")
        all_passed = False

    # 3. Check configuration & model files
    print("\n3. Checking Configured ASR/TTS Offline Model Files:")
    config_path = "/home/linrain/rdkrobot_ws/src/rdk_voice_assistant/config/local_voice.yaml"
    if not os.path.exists(config_path):
        print(f"  [WARN] Configuration file not found at default path: {config_path}")
    else:
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # STT
            stt_params = config.get('local_stt_node', {}).get('ros__parameters', {})
            asr_engine = stt_params.get('asr_engine', 'sherpa-onnx')
            print(f"  Configured ASR Engine: {asr_engine}")
            
            if asr_engine == 'sherpa-onnx':
                model = stt_params.get('sherpa_onnx_asr_model', '')
                tokens = stt_params.get('sherpa_onnx_asr_tokens', '')
                if not check_file("SenseVoice ASR Model", model): all_passed = False
                if not check_file("SenseVoice ASR Tokens", tokens): all_passed = False
            elif asr_engine == 'sherpa-onnx-streaming':
                enc = stt_params.get('sherpa_onnx_streaming_encoder', '')
                dec = stt_params.get('sherpa_onnx_streaming_decoder', '')
                joi = stt_params.get('sherpa_onnx_streaming_joiner', '')
                tok = stt_params.get('sherpa_onnx_streaming_tokens', '')
                if not check_file("Zipformer ASR Encoder", enc): all_passed = False
                if not check_file("Zipformer ASR Decoder", dec): all_passed = False
                if not check_file("Zipformer ASR Joiner", joi): all_passed = False
                if not check_file("Zipformer ASR Tokens", tok): all_passed = False
            
            # TTS
            tts_params = config.get('local_tts_node', {}).get('ros__parameters', {})
            tts_engine = tts_params.get('engine', 'sherpa-onnx')
            print(f"  Configured TTS Engine: {tts_engine}")
            if tts_engine == 'sherpa-onnx':
                model = tts_params.get('sherpa_onnx_model', '')
                lexicon = tts_params.get('sherpa_onnx_lexicon', '')
                tokens = tts_params.get('sherpa_onnx_tokens', '')
                if not check_file("VITS TTS Model", model): all_passed = False
                if not check_file("VITS TTS Lexicon", lexicon): all_passed = False
                if not check_file("VITS TTS Tokens", tokens): all_passed = False
        except Exception as e:
            print(f"  [FAIL] Failed parsing local_voice.yaml: {e}")
            all_passed = False

    # 4. Check port 8080
    print("\n4. Checking Port Availability (Web Dialog Dashboard):")
    if not is_port_free(8080):
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("  [SUCCESS] All checks passed! Ready to launch.")
        print("=" * 60)
        sys.exit(0)
    else:
        print("  [CRITICAL] Some checks FAILED. Please resolve the issues listed above.")
        print("=" * 60)
        sys.exit(1)

if __name__ == '__main__':
    main()
