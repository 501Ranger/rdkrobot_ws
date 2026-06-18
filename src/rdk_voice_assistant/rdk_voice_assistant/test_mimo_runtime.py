#!/usr/bin/env python3
import os
import io
import base64
import wave
import json
import requests
from pathlib import Path

def main():
    print("=== 开始测试小米 MiMo V2.5 ASR 和 TTS 运行时连通性 ===")
    
    # 1. 获取 API Key
    api_key = os.environ.get("MIMO_API_KEY", "").strip()
    base_url = "https://api.xiaomimimo.com/v1"
    
    if not api_key:
        print("未检测到环境变量 MIMO_API_KEY，尝试从 llm_dialog.yaml 自动读取...")
        try:
            import yaml
            pkg_dir = Path(__file__).resolve().parents[1]
            llm_config_path = pkg_dir / 'config' / 'llm_dialog.yaml'
            if not llm_config_path.exists():
                llm_config_path = pkg_dir / 'config' / 'llm_dialog.example.yaml'
            if llm_config_path.exists():
                with open(llm_config_path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f)
                    api_key = cfg.get('llm_dialog_node', {}).get('ros__parameters', {}).get('api_key', '').strip()
                    print(f"成功从 llm_dialog.yaml 读取 API Key (前几位: {api_key[:8]}...)")
        except Exception as e:
            print(f"读取 llm_dialog.yaml 失败: {e}")

    if not api_key:
        print("错误: 无法获取 API Key，请设置 MIMO_API_KEY 环境变量或配置 llm_dialog.yaml 中的 api_key！")
        return

    # 2. 测试 TTS
    print("\n--- 1. 测试 MiMo TTS 语音合成 ---")
    tts_text = "测试小米语音合成功能，正在生成音频。"
    print(f"准备合成文本: '{tts_text}'")
    
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }
    
    tts_payload = {
        "model": "mimo-v2.5-tts",
        "messages": [
            {
                "role": "user",
                "content": "Bright, bouncy tone — like you're bursting with good news you can barely hold in."
            },
            {
                "role": "assistant",
                "content": tts_text
            }
        ],
        "audio": {
            "format": "wav",
            "voice": "冰糖"
        }
    }
    
    try:
        url = f"{base_url}/chat/completions"
        print(f"向 {url} 发送请求...")
        response = requests.post(url, headers=headers, json=tts_payload, timeout=10.0)
        print(f"响应 HTTP 状态码: {response.status_code}")
        
        if response.status_code == 200:
            res_json = response.json()
            audio_base64 = res_json['choices'][0]['message']['audio']['data']
            audio_bytes = base64.b64decode(audio_base64)
            print(f"成功接收到合成音频数据，大小: {len(audio_bytes)} 字节")
            
            # 写入本地文件进行测试验证
            output_dir = Path(__file__).resolve().parents[2] / 'tmp'
            output_dir.mkdir(exist_ok=True)
            output_file = output_dir / 'test_mimo_tts.wav'
            with open(output_file, 'wb') as f:
                f.write(audio_bytes)
            print(f"音频已成功保存至: {output_file}")
        else:
            print(f"合成失败: {response.text}")
    except Exception as e:
        print(f"合成请求异常: {e}")

    # 3. 测试 ASR
    print("\n--- 2. 测试 MiMo ASR 语音识别 ---")
    print("生成测试用 1秒 极短静音音频...")
    
    # 生成 1 秒 16000Hz 16-bit 单声道静音 WAV
    sample_rate = 16000
    silent_pcm = b'\x00' * (sample_rate * 2) # 2字节每采样 (16bit)
    
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(silent_pcm)
    
    test_wav_bytes = wav_io.getvalue()
    test_audio_base64 = base64.b64encode(test_wav_bytes).decode('utf-8')
    audio_data_url = f"data:audio/wav;base64,{test_audio_base64}"
    
    asr_payload = {
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
            "language": "zh"
        }
    }
    
    try:
        url = f"{base_url}/chat/completions"
        print(f"向 {url} 发送 ASR 识别请求...")
        response = requests.post(url, headers=headers, json=asr_payload, timeout=10.0)
        print(f"响应 HTTP 状态码: {response.status_code}")
        
        if response.status_code == 200:
            res_json = response.json()
            text = res_json['choices'][0]['message']['content'].strip()
            print(f"ASR 识别结果: '{text}'")
            print("ASR 连通性测试通过！")
        else:
            print(f"识别失败: {response.text}")
    except Exception as e:
        print(f"识别请求异常: {e}")

if __name__ == "__main__":
    main()
