// ==============================================================================
//  RDK Robot 语音助手 Web 交互控制 JS
// ==============================================================================

let lastVoicePlacesRefreshAt = 0;

// 当 DOM 载入完成时进行初始化
document.addEventListener("DOMContentLoaded", () => {
    initVoiceModule();
});

// 初始化语音模块
function initVoiceModule() {
    // 1. 绑定声源定位模拟器滑动条显示数值
    const angleInput = document.getElementById("ssl-angle-input");
    const angleVal = document.getElementById("ssl-angle-val");
    if (angleInput && angleVal) {
        angleInput.addEventListener("input", () => {
            angleVal.innerText = `${angleInput.value}°`;
        });
    }

    const confInput = document.getElementById("ssl-confidence-input");
    const confVal = document.getElementById("ssl-confidence-val");
    if (confInput && confVal) {
        confInput.addEventListener("input", () => {
            const val = (parseFloat(confInput.value) / 100).toFixed(2);
            confVal.innerText = val;
        });
    }

    // 2. 绑定动作按钮事件
    // A. 模拟语音指令发送
    const btnCmdSend = document.getElementById("btn-voice-command-send");
    if (btnCmdSend) {
        btnCmdSend.addEventListener("click", () => {
            const input = document.getElementById("voice-command-input");
            const text = input ? input.value.trim() : "";
            if (!text) {
                showToast("请输入模拟指令文本", "error");
                return;
            }
            injectVoiceCommand(text);
        });
    }

    // B. 测试语音播报 (TTS)
    const btnTtsSend = document.getElementById("btn-voice-tts-send");
    if (btnTtsSend) {
        btnTtsSend.addEventListener("click", () => {
            const input = document.getElementById("voice-tts-input");
            const text = input ? input.value.trim() : "";
            if (!text) {
                showToast("请输入播报测试文本", "error");
                return;
            }
            triggerTTS(text);
        });
    }

    // C. 模拟声源定位事件
    const btnSslSim = document.getElementById("btn-ssl-simulate");
    if (btnSslSim) {
        btnSslSim.addEventListener("click", () => {
            const angle = parseFloat(angleInput.value);
            const confidence = parseFloat(confInput.value) / 100;
            simulateSoundSource(angle, confidence);
        });
    }

    // D. 刷新地标导航配置
    const btnPlacesRefresh = document.getElementById("btn-voice-places-refresh");
    if (btnPlacesRefresh) {
        btnPlacesRefresh.addEventListener("click", refreshVoicePlaces);
    }

    // E. 保存地标物理坐标
    const btnPlaceSave = document.getElementById("btn-voice-place-save");
    if (btnPlaceSave) {
        btnPlaceSave.addEventListener("click", saveVoicePlace);
    }

    // 3. 首次拉取地标列表
    refreshVoicePlaces();
}

// 模拟输入指令文本
function injectVoiceCommand(text) {
    showToast("正在模拟注入语音指令...", "info");
    fetch(`${API_BASE}/api/v1/voice/command/inject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text })
    })
    .then(res => {
        if (!res.ok) throw new Error("指令注入失败");
        return res.json();
    })
    .then(data => {
        showToast(`成功注入语音指令: "${text}"`, "success");
        const input = document.getElementById("voice-command-input");
        if (input) input.value = "";
    })
    .catch(err => {
        showToast(err.message, "error");
    });
}

// 模拟触发 TTS 播报
function triggerTTS(text) {
    showToast("正在发送 TTS 语音播报...", "info");
    fetch(`${API_BASE}/api/v1/voice/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text })
    })
    .then(res => {
        if (!res.ok) throw new Error("发送播报失败");
        return res.json();
    })
    .then(data => {
        showToast("TTS 播报指令已发送！", "success");
        const input = document.getElementById("voice-tts-input");
        if (input) input.value = "";
    })
    .catch(err => {
        showToast(err.message, "error");
    });
}

// 模拟发送声源定位事件
function simulateSoundSource(angle, confidence) {
    showToast(`正在发送声源事件: 角度 ${angle}°, 置信度 ${confidence}...`, "info");
    fetch(`${API_BASE}/api/v1/voice/source_event/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ angle: angle, confidence: confidence })
    })
    .then(res => {
        if (!res.ok) throw new Error("模拟声源事件失败");
        return res.json();
    })
    .then(data => {
        showToast(`声源定位模拟事件发送成功!`, "success");
    })
    .catch(err => {
        showToast(err.message, "error");
    });
}

// 刷新语音地标配置列表
function refreshVoicePlaces() {
    const tbody = document.getElementById("voice-places-table-body");
    if (!tbody) return;

    fetch(`${API_BASE}/api/v1/voice/places`)
    .then(res => {
        if (!res.ok) throw new Error("加载地标配置失败");
        return res.json();
    })
    .then(data => {
        tbody.innerHTML = "";
        const places = data.places || {};
        const keys = Object.keys(places);

        if (keys.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 12px; color: var(--text-muted);">暂无已配置的语音地标，请在下方添加。</td></tr>`;
            return;
        }

        keys.forEach(key => {
            const p = places[key];
            const name = p.name || key;
            const aliases = p.aliases ? p.aliases.join(", ") : "--";
            const x = p.x !== undefined ? p.x.toFixed(3) : "--";
            const y = p.y !== undefined ? p.y.toFixed(3) : "--";
            const yaw = p.yaw !== undefined ? p.yaw.toFixed(3) : "--";

            const tr = document.createElement("tr");
            tr.style.cursor = "pointer";
            tr.style.transition = "background 0.2s";
            tr.innerHTML = `
                <td style="padding: 6px 10px; font-weight: 500; color: var(--text-primary);">${name}</td>
                <td style="padding: 6px 10px; color: var(--text-secondary);">${aliases}</td>
                <td style="padding: 6px 10px; font-family: monospace; color: var(--accent-cyan);">${x}</td>
                <td style="padding: 6px 10px; font-family: monospace; color: var(--accent-cyan);">${y}</td>
                <td style="padding: 6px 10px; font-family: monospace; color: var(--text-secondary);">${yaw}</td>
            `;

            // 点击表格行自动回填表单，方便修改
            tr.addEventListener("click", () => {
                const nameInput = document.getElementById("voice-place-name");
                const xInput = document.getElementById("voice-place-x");
                const yInput = document.getElementById("voice-place-y");
                const yawInput = document.getElementById("voice-place-yaw");

                if (nameInput) nameInput.value = name;
                if (xInput && p.x !== undefined) xInput.value = p.x;
                if (yInput && p.y !== undefined) yInput.value = p.y;
                if (yawInput && p.yaw !== undefined) yawInput.value = p.yaw;

                showToast(`已回填地标: "${name}"`, "info");
            });

            // 悬停样式
            tr.addEventListener("mouseenter", () => { tr.style.background = "rgba(255, 255, 255, 0.03)"; });
            tr.addEventListener("mouseleave", () => { tr.style.background = "transparent"; });

            tbody.appendChild(tr);
        });
    })
    .catch(err => {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 12px; color: var(--accent-red);">${err.message}</td></tr>`;
    });
}

// 保存语音地标
function saveVoicePlace() {
    const nameInput = document.getElementById("voice-place-name");
    const xInput = document.getElementById("voice-place-x");
    const yInput = document.getElementById("voice-place-y");
    const yawInput = document.getElementById("voice-place-yaw");

    const name = nameInput ? nameInput.value.trim() : "";
    const x = xInput ? parseFloat(xInput.value) : NaN;
    const y = yInput ? parseFloat(yInput.value) : NaN;
    const yaw = yawInput ? parseFloat(yawInput.value) : 0.0;

    if (!name) {
        showToast("地标名称不能为空", "error");
        return;
    }
    if (isNaN(x) || isNaN(y)) {
        showToast("X 和 Y 物理坐标必须为有效数值", "error");
        return;
    }

    showToast(`正在保存地标 "${name}" 坐标...`, "info");
    fetch(`${API_BASE}/api/v1/voice/places`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, x: x, y: y, yaw: yaw })
    })
    .then(res => {
        if (!res.ok) throw new Error("保存地标失败");
        return res.json();
    })
    .then(data => {
        showToast(`地标 "${name}" 坐标保存成功！`, "success");
        // 清空表单
        if (nameInput) nameInput.value = "";
        if (xInput) xInput.value = "";
        if (yInput) yInput.value = "";
        if (yawInput) yawInput.value = "0.00";
        // 刷新列表
        refreshVoicePlaces();
    })
    .catch(err => {
        showToast(err.message, "error");
    });
}

// 全局回调函数，用于 WebSocket 遥测数据更新时同步 UI
function updateVoiceUI(status) {
    if (!status) return;

    // 最新识别指令
    const cmdEl = document.getElementById("voice-status-cmd");
    if (cmdEl) cmdEl.innerText = status.latest_command_text || "--";

    // 指令来源
    const srcEl = document.getElementById("voice-status-src");
    if (srcEl) {
        srcEl.innerText = status.latest_command_source ? status.latest_command_source.toUpperCase() : "--";
    }

    // 指令更新时间
    const timeEl = document.getElementById("voice-status-time");
    if (timeEl) {
        timeEl.innerText = status.updated_at && status.updated_at > 0
            ? new Date(status.updated_at * 1000).toLocaleTimeString()
            : "--";
    }

    // TTS 回复文本
    const ttsEl = document.getElementById("voice-status-tts");
    if (ttsEl) ttsEl.innerText = status.latest_tts_text || "--";

    // 声源定位测角
    const angleEl = document.getElementById("voice-status-angle");
    if (angleEl) {
        const val = status.source_angle !== undefined ? status.source_angle.toFixed(1) : "0.0";
        angleEl.innerText = `${val}°`;
    }

    // 声源定位置信度
    const confEl = document.getElementById("voice-status-conf");
    if (confEl) {
        const val = status.source_confidence !== undefined ? status.source_confidence.toFixed(2) : "0.00";
        confEl.innerText = val;
    }
    // 语音指令可能在 ROS 节点内直接更新 places.yaml，状态推送时做节流刷新。
    const placesTable = document.getElementById("voice-places-table-body");
    const now = Date.now();
    if (placesTable && now - lastVoicePlacesRefreshAt > 2000) {
        lastVoicePlacesRefreshAt = now;
        refreshVoicePlaces();
    }

}

// 暴露到全局 window 作用域，以便 websocket.js 能够跨文件调用
window.updateVoiceUI = updateVoiceUI;
