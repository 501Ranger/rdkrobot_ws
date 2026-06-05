import asyncio
import json
import threading
from typing import Optional, Set

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
from aiohttp import web

# Embedded premium Glassmorphic Voice Debug Dashboard HTML interface
HTML_CONTENT = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RDK Voice Assistant - 语音控制与诊断台</title>
    <style>
        :root {
            --bg-color: #080b11;
            --panel-bg: rgba(15, 23, 42, 0.65);
            --border-color: rgba(255, 255, 255, 0.07);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-primary: #6366f1;
            --accent-cyan: #06b6d4;
            --accent-pink: #ec4899;
            
            --status-idle: #10b981;
            --status-calibrating: #6366f1;
            --status-listening: #3b82f6;
            --status-recording: #ec4899;
            --status-decoding: #f59e0b;
            --status-error: #ef4444;
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
            background-image: 
                radial-gradient(at 10% 10%, rgba(99, 102, 241, 0.12) 0px, transparent 45%),
                radial-gradient(at 90% 90%, rgba(6, 182, 212, 0.12) 0px, transparent 45%);
        }

        .container {
            width: 95%;
            max-width: 1280px;
            height: 90vh;
            background: var(--panel-bg);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Top Header */
        .header {
            padding: 16px 28px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(10, 15, 30, 0.4);
        }

        .brand h1 {
            font-size: 1.15rem;
            font-weight: 700;
            letter-spacing: 0.5px;
            background: linear-gradient(to right, #f8fafc, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .brand p {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 2px;
        }

        .header-status {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .conn-pill {
            padding: 4px 12px;
            border-radius: 99px;
            font-size: 0.75rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
            background: rgba(239, 68, 68, 0.1);
            color: #ef4444;
            border: 1px solid rgba(239, 68, 68, 0.2);
            transition: all 0.3s ease;
        }

        .conn-pill.online {
            background: rgba(16, 185, 129, 0.1);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.2);
        }

        .conn-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background-color: currentColor;
            box-shadow: 0 0 6px currentColor;
        }

        /* Dashboard Grid Layout */
        .grid {
            flex: 1;
            display: flex;
            overflow: hidden;
        }

        /* Left Side: Diagnostics & VAD Analytics */
        .left-col {
            width: 380px;
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            padding: 24px;
            gap: 20px;
            overflow-y: auto;
            background: rgba(10, 15, 30, 0.15);
        }

        .left-col::-webkit-scrollbar {
            width: 4px;
        }

        .left-col::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 99px;
        }

        .section-title {
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--text-secondary);
            margin-bottom: 10px;
        }

        .info-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 16px;
        }

        /* VAD Level Visualizer */
        .vad-visualizer {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .level-meter-container {
            position: relative;
            height: 24px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 8px;
            border: 1px solid var(--border-color);
            overflow: hidden;
            width: 100%;
        }

        .level-meter-fill {
            height: 100%;
            width: 0%;
            background: linear-gradient(to right, var(--accent-cyan), #3b82f6);
            box-shadow: 0 0 10px rgba(6, 182, 212, 0.3);
            transition: width 0.1s cubic-bezier(0.1, 0.8, 0.3, 1);
        }

        .level-meter-threshold {
            position: absolute;
            top: 0;
            left: 0%;
            width: 3px;
            height: 100%;
            background-color: #ef4444;
            box-shadow: 0 0 8px #ef4444;
            transition: left 0.3s ease;
        }

        .vad-values {
            display: flex;
            justify-content: space-between;
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        .vad-values span strong {
            color: var(--text-primary);
        }

        /* State Cards Grid */
        .state-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .state-card {
            padding: 14px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            background: rgba(255, 255, 255, 0.01);
            text-align: center;
            display: flex;
            flex-direction: column;
            gap: 6px;
            transition: all 0.3s ease;
        }

        .state-card .label {
            font-size: 0.7rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            font-weight: 500;
        }

        .state-card .val {
            font-size: 0.95rem;
            font-weight: 700;
        }

        .state-card.active-green {
            background: rgba(16, 185, 129, 0.08);
            border-color: rgba(16, 185, 129, 0.2);
            color: #10b981;
            box-shadow: 0 0 12px rgba(16, 185, 129, 0.1);
        }

        .state-card.active-pink {
            background: rgba(236, 72, 153, 0.08);
            border-color: rgba(236, 72, 153, 0.2);
            color: var(--accent-pink);
            box-shadow: 0 0 12px rgba(236, 72, 153, 0.1);
        }

        /* Sound Source Localization Radar */
        .radar-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 16px;
            gap: 12px;
            position: relative;
        }

        .radar-ring {
            width: 140px;
            height: 140px;
            border-radius: 50%;
            border: 2px dashed rgba(6, 182, 212, 0.3);
            position: relative;
            background: radial-gradient(circle, rgba(6, 182, 212, 0.03) 0%, rgba(8, 11, 17, 0.8) 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s ease;
        }

        .radar-ring::before {
            content: '';
            position: absolute;
            width: 70px;
            height: 70px;
            border-radius: 50%;
            border: 1px solid rgba(6, 182, 212, 0.15);
        }

        .radar-cross-h {
            position: absolute;
            width: 100%;
            height: 1px;
            background: rgba(255, 255, 255, 0.07);
        }

        .radar-cross-v {
            position: absolute;
            width: 1px;
            height: 100%;
            background: rgba(255, 255, 255, 0.07);
        }

        .radar-degree-label {
            position: absolute;
            font-size: 0.65rem;
            color: var(--text-secondary);
            font-weight: 600;
        }
        .lbl-n { top: 4px; }
        .lbl-e { right: 8px; }
        .lbl-s { bottom: 4px; }
        .lbl-w { left: 8px; }

        .radar-needle {
            position: absolute;
            width: 2px;
            height: 70px;
            background: linear-gradient(to top, transparent, var(--accent-cyan));
            transform-origin: bottom center;
            bottom: 50%;
            left: calc(50% - 1px);
            transform: rotate(0deg);
            transition: transform 0.8s cubic-bezier(0.25, 1, 0.5, 1);
            filter: drop-shadow(0 0 4px var(--accent-cyan));
        }

        .radar-blip {
            position: absolute;
            width: 8px;
            height: 8px;
            background-color: var(--accent-pink);
            border-radius: 50%;
            box-shadow: 0 0 12px var(--accent-pink);
            opacity: 0;
            transition: all 0.8s cubic-bezier(0.25, 1, 0.5, 1);
        }

        .radar-text {
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-align: center;
        }

        .radar-text strong {
            color: var(--text-primary);
        }

        /* System Info table */
        .sys-info-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
        }

        .sys-info-table td {
            padding: 6px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
        }

        .sys-info-table td:first-child {
            color: var(--text-secondary);
        }

        .sys-info-table td:last-child {
            text-align: right;
            font-weight: 600;
        }

        /* Right Side: Logging, Live Feeds, and Controls */
        .right-col {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Console Event Feed */
        .feed-container {
            flex: 1;
            padding: 24px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 12px;
            scroll-behavior: smooth;
        }

        .feed-container::-webkit-scrollbar {
            width: 6px;
        }

        .feed-container::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 99px;
        }

        .log-entry {
            display: flex;
            font-size: 0.85rem;
            line-height: 1.4;
            padding: 8px 12px;
            background: rgba(255, 255, 255, 0.02);
            border-radius: 8px;
            border: 1px solid var(--border-color);
            animation: slide-in-log 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }

        @keyframes slide-in-log {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .log-time {
            color: var(--text-secondary);
            font-family: monospace;
            margin-right: 12px;
            width: 75px;
            flex-shrink: 0;
        }

        .log-tag {
            padding: 1px 6px;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 700;
            margin-right: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            flex-shrink: 0;
            display: inline-block;
            height: fit-content;
        }

        .tag-stt { background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.3); }
        .tag-tts { background: rgba(236, 72, 153, 0.15); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3); }
        .tag-cmd { background: rgba(6, 182, 212, 0.15); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.3); }
        .tag-system { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3); }
        .tag-err { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }

        .log-text {
            color: var(--text-primary);
            word-break: break-all;
        }

        .log-text span.secondary {
            color: var(--text-secondary);
            font-style: italic;
        }

        /* Transcription Live Preview */
        .live-asr-bar {
            padding: 12px 28px;
            background: rgba(6, 182, 212, 0.05);
            border-top: 1px solid var(--border-color);
            border-bottom: 1px solid var(--border-color);
            min-height: 48px;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .pulse-light {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--accent-cyan);
            animation: pulse-glow 1.5s infinite;
        }

        @keyframes pulse-glow {
            0% { transform: scale(1); opacity: 0.4; box-shadow: 0 0 0 rgba(6, 182, 212, 0); }
            50% { transform: scale(1.2); opacity: 1; box-shadow: 0 0 10px rgba(6, 182, 212, 0.6); }
            100% { transform: scale(1); opacity: 0.4; box-shadow: 0 0 0 rgba(6, 182, 212, 0); }
        }

        .asr-preview-text {
            font-size: 0.88rem;
            color: var(--accent-cyan);
            font-style: italic;
            font-weight: 500;
        }

        /* Control Panel */
        .controls-section {
            padding: 20px 24px;
            background: rgba(10, 15, 30, 0.4);
            border-top: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .btn {
            padding: 10px 16px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            background: rgba(255, 255, 255, 0.03);
            color: var(--text-primary);
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            outline: none;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn:hover {
            background: rgba(255, 255, 255, 0.08);
            border-color: rgba(255, 255, 255, 0.15);
            transform: translateY(-1px);
        }

        .btn:active {
            transform: translateY(0);
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--accent-primary), #4f46e5);
            border: none;
        }

        .btn-primary:hover {
            box-shadow: 0 0 15px rgba(99, 102, 241, 0.4);
            background: linear-gradient(135deg, #4f46e5, #4338ca);
        }

        .btn-danger {
            background: rgba(239, 68, 68, 0.1);
            color: #f87171;
            border-color: rgba(239, 68, 68, 0.2);
        }

        .btn-danger:hover {
            background: rgba(239, 68, 68, 0.2);
            border-color: rgba(239, 68, 68, 0.4);
        }

        /* Interactive Command Forms */
        .forms-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }

        .input-group {
            display: flex;
            position: relative;
            align-items: center;
        }

        .input-field {
            flex: 1;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 10px 14px;
            font-size: 0.85rem;
            color: var(--text-primary);
            outline: none;
            transition: all 0.2s ease;
            font-family: inherit;
        }

        .input-field:focus {
            background: rgba(255, 255, 255, 0.04);
            border-color: var(--accent-cyan);
            box-shadow: 0 0 10px rgba(6, 182, 212, 0.15);
        }

        .input-btn {
            position: absolute;
            right: 8px;
            padding: 6px 12px;
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .input-btn:hover {
            background: rgba(255, 255, 255, 0.15);
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Top Header -->
        <div class="header">
            <div class="brand">
                <h1>RDK 智能语音诊断控制台</h1>
                <p>WSL2 ROS2 离线语音与声源定位雷达调试终端</p>
            </div>
            <div class="header-status">
                <div class="conn-pill" id="conn-pill">
                    <span class="conn-dot"></span>
                    <span id="conn-text">连接中...</span>
                </div>
            </div>
        </div>

        <!-- Main Body -->
        <div class="grid">
            <!-- Left Panel: Metrics -->
            <div class="left-col">
                <div class="vad-visualizer">
                    <h2 class="section-title">VAD 麦克风能量监控</h2>
                    <div class="info-card">
                        <div class="level-meter-container">
                            <div class="level-meter-fill" id="vad-fill"></div>
                            <div class="level-meter-threshold" id="vad-threshold-line" style="left: 0%"></div>
                        </div>
                        <div class="vad-values" style="margin-top: 10px;">
                            <span>实时 RMS: <strong id="val-rms">0.0</strong></span>
                            <span>门限 Threshold: <strong id="val-threshold">0.0</strong></span>
                        </div>
                    </div>
                </div>

                <div>
                    <h2 class="section-title">语音节点状态</h2>
                    <div class="state-grid">
                        <div class="state-card" id="card-wake">
                            <span class="label">唤醒状态</span>
                            <span class="val" id="text-wake">休眠中</span>
                        </div>
                        <div class="state-card" id="card-speaking">
                            <span class="label">播报状态</span>
                            <span class="val" id="text-speaking">静音中</span>
                        </div>
                    </div>
                </div>

                <div>
                    <h2 class="section-title">声源定位雷达 (DOA)</h2>
                    <div class="radar-container">
                        <div class="radar-ring">
                            <div class="radar-cross-h"></div>
                            <div class="radar-cross-v"></div>
                            <span class="radar-degree-label lbl-n">0°</span>
                            <span class="radar-degree-label lbl-e">90°</span>
                            <span class="radar-degree-label lbl-s">180°</span>
                            <span class="radar-degree-label lbl-w">270°</span>
                            <div class="radar-needle" id="radar-needle"></div>
                            <div class="radar-blip" id="radar-blip"></div>
                        </div>
                        <div class="radar-text">
                            声源角度: <strong id="radar-angle">--</strong>° &nbsp; 置信度: <strong id="radar-conf">--</strong>
                        </div>
                    </div>
                </div>

                <div>
                    <h2 class="section-title">系统参数 (ROS 2)</h2>
                    <div class="info-card">
                        <table class="sys-info-table">
                            <tr>
                                <td>STT 诊断话题</td>
                                <td>/voice/stt_status</td>
                            </tr>
                            <tr>
                                <td>TTS 诊断话题</td>
                                <td>/voice/tts_status</td>
                            </tr>
                            <tr>
                                <td>ASR 引擎</td>
                                <td id="info-asr">未知</td>
                            </tr>
                            <tr>
                                <td>TTS 引擎</td>
                                <td id="info-tts">未知</td>
                            </tr>
                            <tr>
                                <td>待播队列</td>
                                <td id="info-queue-len">0</td>
                            </tr>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Right Panel: Logging & Controls -->
            <div class="right-col">
                <!-- Log feed -->
                <div class="feed-container" id="feed-container">
                    <div class="log-entry">
                        <div class="log-time" id="time-init">--:--:--</div>
                        <div class="log-tag tag-system">系统</div>
                        <div class="log-text">诊断控制台初始化完成。等待 WebSocket 建立连接...</div>
                    </div>
                </div>

                <!-- Live ASR Preview Bar -->
                <div class="live-asr-bar" id="live-asr-bar" style="display: none;">
                    <div class="pulse-light"></div>
                    <div class="asr-preview-text" id="asr-preview-text">正在聆听...</div>
                </div>

                <!-- Controls Panel -->
                <div class="controls-section">
                    <h2 class="section-title">控制中心</h2>
                    <div class="btn-group">
                        <button class="btn btn-primary" onclick="recalibrateVAD()">
                            <span>⚡</span>
                            <span>重新校准 VAD 噪声门限</span>
                        </button>
                        <button class="btn btn-danger" onclick="clearTTSQueue()">
                            <span>🗑️</span>
                            <span>清除 TTS 播报队列</span>
                        </button>
                    </div>

                    <label class="section-title" style="display: block; margin-top: 4px; margin-bottom: 2px;">模拟声源事件触发 (DOA)</label>
                    <div class="btn-group">
                        <button class="btn" style="border-color: rgba(6, 182, 212, 0.3); color: var(--accent-cyan);" onclick="triggerMockDOA(0)">
                            <span>🧭 0° (前方)</span>
                        </button>
                        <button class="btn" style="border-color: rgba(6, 182, 212, 0.3); color: var(--accent-cyan);" onclick="triggerMockDOA(90)">
                            <span>🧭 90° (左侧)</span>
                        </button>
                        <button class="btn" style="border-color: rgba(6, 182, 212, 0.3); color: var(--accent-cyan);" onclick="triggerMockDOA(180)">
                            <span>🧭 180° (后方)</span>
                        </button>
                        <button class="btn" style="border-color: rgba(6, 182, 212, 0.3); color: var(--accent-cyan);" onclick="triggerMockDOA(270)">
                            <span>🧭 270° (右侧)</span>
                        </button>
                        <button class="btn" style="border-color: rgba(236, 72, 153, 0.3); color: var(--accent-pink);" onclick="triggerMockDOA(Math.floor(Math.random()*360))">
                            <span>🎲 随机角度</span>
                        </button>
                    </div>

                    <div class="forms-row">
                        <form onsubmit="sendManualCommand(event)">
                            <label class="section-title" style="display: block; margin-bottom: 6px;">手动发送文字指令</label>
                            <div class="input-group">
                                <input type="text" class="input-field" id="input-command" placeholder="模拟说一句话，如：小智，看向声音方向..." autocomplete="off" />
                                <button type="submit" class="input-btn">发送</button>
                            </div>
                        </form>
                        <form onsubmit="testSpeech(event)">
                            <label class="section-title" style="display: block; margin-bottom: 6px;">测试播报文本 (TTS)</label>
                            <div class="input-group">
                                <input type="text" class="input-field" id="input-tts" placeholder="输入要让机器人播报的文字..." autocomplete="off" />
                                <button type="submit" class="input-btn">播放</button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let ws;
        const feed = document.getElementById('feed-container');
        const levelFill = document.getElementById('vad-fill');
        const thresholdLine = document.getElementById('vad-threshold-line');
        const valRms = document.getElementById('val-rms');
        const valThreshold = document.getElementById('val-threshold');
        const cardWake = document.getElementById('card-wake');
        const textWake = document.getElementById('text-wake');
        const cardSpeaking = document.getElementById('card-speaking');
        const textSpeaking = document.getElementById('text-speaking');
        const connPill = document.getElementById('conn-pill');
        const connText = document.getElementById('conn-text');
        
        const infoAsr = document.getElementById('info-asr');
        const infoTts = document.getElementById('info-tts');
        const infoQueueLen = document.getElementById('info-queue-len');
        
        const liveAsrBar = document.getElementById('live-asr-bar');
        const asrPreviewText = document.getElementById('asr-preview-text');

        // Set initial timestamp
        document.getElementById('time-init').textContent = getTimestamp();

        function getTimestamp() {
            const now = new Date();
            return now.toTimeString().split(' ')[0];
        }

        function appendLog(tag, content, isError = false) {
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            
            const time = document.createElement('div');
            time.className = 'log-time';
            time.textContent = getTimestamp();
            
            const tagSpan = document.createElement('span');
            tagSpan.className = `log-tag tag-${tag}`;
            tagSpan.textContent = tag === 'stt' ? 'ASR诊断' : tag === 'tts' ? 'TTS播报' : tag === 'cmd' ? '文字命令' : tag === 'err' ? '异常' : '系统';
            
            const textSpan = document.createElement('div');
            textSpan.className = 'log-text';
            textSpan.innerHTML = content;
            
            entry.appendChild(time);
            entry.appendChild(tagSpan);
            entry.appendChild(textSpan);
            
            feed.appendChild(entry);
            feed.scrollTop = feed.scrollHeight;
        }

        function connectWebSocket() {
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${proto}//${window.location.host}/ws`;
            
            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                connPill.className = 'conn-pill online';
                connText.textContent = '连接在线';
                appendLog('system', '与 ROS 2 诊断网桥建立 WebSocket 连接。');
            };

            ws.onclose = () => {
                connPill.className = 'conn-pill';
                connText.textContent = '断开重连...';
                appendLog('err', '与诊断网桥的连接断开，正在尝试重连...');
                setTimeout(connectWebSocket, 3000);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    handleSocketMessage(data);
                } catch (e) {
                    console.error('解析 WebSocket 数据包出错:', e);
                }
            };
        }

        function handleSocketMessage(packet) {
            if (packet.type === 'stt_status') {
                const info = packet.data;
                // Live VAD Meter
                updateVADMeter(info.rms, info.threshold);
                
                // Wake/TTS states
                updateWakeState(info.wake_active);
                updateSpeakingState(info.tts_active);
                
                // Logs for transitions
                if (info.status === 'calibrating') {
                    appendLog('system', `<span class="secondary">${info.detail} (RMS: ${info.rms.toFixed(0)})</span>`);
                } else if (info.status === 'wake_detected') {
                    appendLog('stt', `<strong>${info.detail}</strong> - 唤醒词激活！`);
                } else if (info.status === 'decoding') {
                    appendLog('stt', `<span class="secondary">${info.detail}</span>`);
                } else if (info.status === 'ignored_no_wake_word') {
                    appendLog('stt', `丢弃音频: 缺少唤醒词 -> "<span class="secondary">${info.detail}</span>"`);
                } else if (info.status === 'ignored_tts_active') {
                    appendLog('stt', `丢弃音频: 机器人正在播报 -> "<span class="secondary">${info.detail}</span>"`);
                } else if (info.status === 'ignored_duplicate') {
                    appendLog('stt', `丢弃音频: 重复/过载命令 -> "<span class="secondary">${info.detail}</span>"`);
                }
            }
            else if (packet.type === 'tts_status') {
                const info = packet.data;
                infoTts.textContent = info.engine;
                infoQueueLen.textContent = info.queue_len;
                
                if (info.state === 'speaking') {
                    appendLog('tts', `正在合成播报: "<strong>${info.text}</strong>"`);
                    updateSpeakingState(true);
                } else if (info.state === 'ready') {
                    appendLog('tts', `<span class="secondary">新文本进入队列: "${info.text}" (当前排队: ${info.queue_len})</span>`);
                } else if (info.state === 'error') {
                    appendLog('err', `TTS 播报出错: ${info.error}`);
                } else if (info.state === 'idle') {
                    updateSpeakingState(false);
                }
            }
            else if (packet.type === 'command_text') {
                appendLog('cmd', `<strong>语音最终识别命令</strong>: "<span style="color: var(--accent-cyan); font-weight: bold;">${packet.text}</span>"`);
                liveAsrBar.style.display = 'none';
            }
            else if (packet.type === 'partial_text') {
                if (packet.text && packet.text.trim() !== '') {
                    liveAsrBar.style.display = 'flex';
                    asrPreviewText.textContent = `实时识别中: "${packet.text}"`;
                } else {
                    liveAsrBar.style.display = 'none';
                }
            }
            else if (packet.type === 'reply_text') {
                // Background reply logging
            }
            else if (packet.type === 'source_event') {
                const info = packet.data;
                const angle = info.angle_deg;
                const confidence = info.confidence;
                
                // Update radar text labels
                document.getElementById('radar-angle').textContent = angle.toFixed(1);
                document.getElementById('radar-conf').textContent = confidence.toFixed(2);
                
                // Rotate radar needle
                const needle = document.getElementById('radar-needle');
                needle.style.transform = `rotate(${angle}deg)`;
                
                // Position blip on the outer circle at the specified angle
                const blip = document.getElementById('radar-blip');
                const radius = 60; // radius of the path
                const angleRad = (angle * Math.PI) / 180.0;
                const x = Math.sin(angleRad) * radius;
                const y = -Math.cos(angleRad) * radius;
                
                blip.style.left = `calc(50% + ${x}px - 4px)`;
                blip.style.top = `calc(50% + ${y}px - 4px)`;
                blip.style.opacity = '1';
                
                appendLog('system', `<strong>声源事件监测</strong> - 角度: ${angle.toFixed(1)}°, 置信度: ${confidence.toFixed(2)}`);
                
                // Slowly fade out the blip after 2.5 seconds
                setTimeout(() => {
                    blip.style.opacity = '0.3';
                }, 2500);
            }
        }

        function updateVADMeter(rms, threshold) {
            valRms.textContent = rms.toFixed(1);
            valThreshold.textContent = threshold.toFixed(1);
            
            // Map 0-40000 range logically to 0-100% width
            const rmsPercent = Math.min(100, Math.max(0, (rms / 25000.0) * 100));
            const threshPercent = Math.min(99, Math.max(0, (threshold / 25000.0) * 100));
            
            levelFill.style.width = `${rmsPercent}%`;
            thresholdLine.style.left = `${threshPercent}%`;
            
            if (rms > threshold) {
                levelFill.style.background = 'linear-gradient(to right, #ec4899, #ef4444)';
            } else {
                levelFill.style.background = 'linear-gradient(to right, var(--accent-cyan), #3b82f6)';
            }
        }

        function updateWakeState(active) {
            if (active) {
                cardWake.className = 'state-card active-green';
                textWake.textContent = '激活中';
            } else {
                cardWake.className = 'state-card';
                textWake.textContent = '休眠中';
            }
        }

        function updateSpeakingState(active) {
            if (active) {
                cardSpeaking.className = 'state-card active-pink';
                textSpeaking.textContent = '播报中';
            } else {
                cardSpeaking.className = 'state-card';
                textSpeaking.textContent = '静音中';
            }
        }

        function recalibrateVAD() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'recalibrate' }));
                appendLog('system', '发送请求：重新校准 VAD 噪声门限门槛值。请保持环境安静 1.5 秒...');
            }
        }

        function clearTTSQueue() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'tts_test', text: '__CLEAR__' }));
                appendLog('system', '已发送清空 TTS 播报队列指令。');
            }
        }

        function triggerMockDOA(angle) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'trigger_loc', angle: angle }));
                appendLog('system', `触发模拟声源事件，角度: ${angle}°`);
            }
        }

        function sendManualCommand(e) {
            e.preventDefault();
            const input = document.getElementById('input-command');
            const text = input.value.trim();
            if (!text) return;
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'user_send', text: text }));
                appendLog('cmd', `手动模拟发送文本命令: "${text}"`);
                input.value = '';
            }
        }

        function testSpeech(e) {
            e.preventDefault();
            const input = document.getElementById('input-tts');
            const text = input.value.trim();
            if (!text) return;
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'tts_test', text: text }));
                appendLog('system', `触发测试语音播报: "${text}"`);
                input.value = '';
            }
        }

        connectWebSocket();
    </script>
</body>
</html>"""


class WebDialogNode(Node):
    def __init__(self) -> None:
        super().__init__('web_dialog_node')

        self.declare_parameter('port', 8080)
        self.declare_parameter('command_text_topic', '/voice/command_text')
        self.declare_parameter('partial_text_topic', '/voice/partial_text')
        self.declare_parameter('reply_text_topic', '/assistant/reply_text')
        self.declare_parameter('tts_active_topic', '/voice/tts_active')
        self.declare_parameter('robot_task_topic', '/voice/robot_task')
        self.declare_parameter('stt_status_topic', '/voice/stt_status')
        self.declare_parameter('tts_status_topic', '/voice/tts_status')

        self.port = int(self.get_parameter('port').value)
        self.command_text_topic = str(self.get_parameter('command_text_topic').value)
        self.partial_text_topic = str(self.get_parameter('partial_text_topic').value)
        self.reply_text_topic = str(self.get_parameter('reply_text_topic').value)
        self.tts_active_topic = str(self.get_parameter('tts_active_topic').value)
        self.robot_task_topic = str(self.get_parameter('robot_task_topic').value)
        self.stt_status_topic = str(self.get_parameter('stt_status_topic').value)
        self.tts_status_topic = str(self.get_parameter('tts_status_topic').value)

        # Publishers
        self.command_pub = self.create_publisher(String, self.command_text_topic, 10)
        self.reply_pub = self.create_publisher(String, self.reply_text_topic, 10)
        self.recalibrate_pub = self.create_publisher(Bool, '/voice/recalibrate_vad', 10)
        self.trigger_loc_pub = self.create_publisher(String, '/voice/trigger_localization', 10)

        # Subscribers
        self.create_subscription(String, self.command_text_topic, self._on_command_text, 10)
        self.create_subscription(String, self.partial_text_topic, self._on_partial_text, 10)
        self.create_subscription(String, self.reply_text_topic, self._on_reply_text, 10)
        self.create_subscription(Bool, self.tts_active_topic, self._on_tts_active, 10)
        self.create_subscription(String, self.robot_task_topic, self._on_robot_task, 10)
        self.create_subscription(String, self.stt_status_topic, self._on_stt_status, 10)
        self.create_subscription(String, self.tts_status_topic, self._on_tts_status, 10)
        self.create_subscription(String, '/voice/source_event', self._on_source_event, 10)

        self.get_logger().info(f'Web Dialog Node initialized. Target Port: {self.port}')
        self.ws_clients: Set[web.WebSocketResponse] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def _broadcast_to_web(self, data: dict) -> None:
        if not self.ws_clients or not self.loop:
            return
        asyncio.run_coroutine_threadsafe(self._async_broadcast(data), self.loop)

    async def _async_broadcast(self, data: dict) -> None:
        if not self.ws_clients:
            return
        payload = json.dumps(data, ensure_ascii=False)
        disconnected = []
        for ws in self.ws_clients:
            try:
                await ws.send_str(payload)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.ws_clients.discard(ws)

    def _on_command_text(self, msg: String) -> None:
        self._broadcast_to_web({'type': 'command_text', 'text': msg.data})

    def _on_partial_text(self, msg: String) -> None:
        self._broadcast_to_web({'type': 'partial_text', 'text': msg.data})

    def _on_reply_text(self, msg: String) -> None:
        self._broadcast_to_web({'type': 'reply_text', 'text': msg.data})

    def _on_tts_active(self, msg: Bool) -> None:
        pass

    def _on_robot_task(self, msg: String) -> None:
        pass

    def _on_stt_status(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self._broadcast_to_web({'type': 'stt_status', 'data': data})
        except Exception:
            pass

    def _on_tts_status(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self._broadcast_to_web({'type': 'tts_status', 'data': data})
        except Exception:
            pass

    def _on_source_event(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self._broadcast_to_web({'type': 'source_event', 'data': data})
        except Exception:
            pass


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=HTML_CONTENT, content_type='text/html')


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    node: WebDialogNode = request.app['node']
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    node.ws_clients.add(ws)
    node.get_logger().info('WebSocket client connected.')

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get('type')
                    if msg_type == 'user_send':
                        text = str(data.get('text', '')).strip()
                        if text:
                            node.get_logger().info(f'Web UI sent manual command: {text}')
                            node.command_pub.publish(String(data=text))
                    elif msg_type == 'tts_test':
                        text = str(data.get('text', '')).strip()
                        if text:
                            node.get_logger().info(f'Web UI requested TTS test: {text}')
                            node.reply_pub.publish(String(data=text))
                    elif msg_type == 'recalibrate':
                        node.get_logger().info('Web UI triggered VAD noise recalibration request.')
                        node.recalibrate_pub.publish(Bool(data=True))
                    elif msg_type == 'trigger_loc':
                        angle = data.get('angle')
                        node.get_logger().info(f'Web UI triggered mock sound direction at {angle}°')
                        node.trigger_loc_pub.publish(String(data=str(angle)))
                except Exception as e:
                    node.get_logger().error(f'Error parsing WS packet: {e}')
            elif msg.type == web.WSMsgType.ERROR:
                node.get_logger().error(f'WebSocket error: {ws.exception()}')
    finally:
        node.ws_clients.discard(ws)
        node.get_logger().info('WebSocket client disconnected.')

    return ws


async def start_web_server(node: WebDialogNode) -> web.TCPSite:
    app = web.Application()
    app['node'] = node
    app.router.add_get('/', handle_index)
    app.router.add_get('/ws', handle_ws)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', node.port)
    await site.start()
    node.get_logger().info(f'Web Dashboard server listening on http://localhost:{node.port}')
    return site


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = WebDialogNode()

    # Create event loop for handling WebSocket connections asynchronously
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    node.set_loop(loop)

    # Spin ROS2 in a background thread to prevent blocking
    ros_thread = threading.Thread(
        target=rclpy.spin,
        args=(node,),
        daemon=True
    )
    ros_thread.start()

    # Start Aiohttp inside the asyncio loop
    loop.run_until_complete(start_web_server(node))
    
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        node.get_logger().info('Shutting down Web Dialog Node...')
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
