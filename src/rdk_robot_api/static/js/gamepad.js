// ==========================================
// 11. 主机蓝牙手柄与 Joy 服务管理交互 (Host Gamepad Bluetooth Control)
// ==========================================
window.joyManuallyStopped = false;

function initHostGamepad() {
    const btnScan = document.getElementById("btn-scan-bluetooth");
    const btnConnect = document.getElementById("btn-connect-bluetooth");
    const btnDisconnect = document.getElementById("btn-disconnect-bluetooth");
    const deviceSelect = document.getElementById("dropdown-bluetooth-device");
    const joySwitch = document.getElementById("host-joy-enable-switch");

    // A. 初始化并启动定时拉取主机蓝牙状态
    refreshHostBluetoothStatus();
    setInterval(refreshHostBluetoothStatus, 5000); // 5秒轻量轮询

    // B. 扫描蓝牙设备
    if (btnScan) {
        btnScan.addEventListener("click", () => {
            btnScan.disabled = true;
            btnScan.innerText = "扫描中...";
            showToast("正在通过主机扫描附近的蓝牙设备，需 4 秒，请稍候...", "info");
            
            fetch(`${API_BASE}/api/v1/system/bluetooth/scan`, { method: "POST" })
                .then(res => {
                    if (!res.ok) throw new Error("扫描请求失败");
                    return res.json();
                })
                .then(data => {
                    btnScan.disabled = false;
                    btnScan.innerText = "🔍 扫描";
                    
                    if (data.status === "success") {
                        if (deviceSelect) {
                            const opts = [{ value: "", text: "-- 请选择设备 --" }];
                            const devices = data.devices || [];
                            if (devices.length === 0) {
                                showToast("附近未发现可连接的蓝牙设备，请长按手柄配对键使其闪烁", "warning");
                                if (typeof window.updateCustomDropdownOptions === "function") {
                                    window.updateCustomDropdownOptions("dropdown-bluetooth-device", opts);
                                }
                                return;
                            }
                            devices.forEach(dev => {
                                opts.push({ value: dev.mac, text: `${dev.name} (${dev.mac})` });
                            });
                            if (typeof window.updateCustomDropdownOptions === "function") {
                                window.updateCustomDropdownOptions("dropdown-bluetooth-device", opts);
                            }
                            showToast(`成功发现附近 ${devices.length} 个蓝牙设备！`, "success");
                        }
                    } else {
                        showToast(`扫描失败: ${data.message || "未知错误"}`, "error");
                    }
                })
                .catch(err => {
                    btnScan.disabled = false;
                    btnScan.innerText = "🔍 扫描";
                    showToast(`扫描发生异常: ${err.message}`, "error");
                });
        });
    }

    // C. 配对信任并连接蓝牙设备
    if (btnConnect) {
        btnConnect.addEventListener("click", () => {
            const mac = deviceSelect ? deviceSelect.getAttribute("data-value") : "";
            if (!mac) {
                showToast("请先在下拉推荐列表中选择要连接的蓝牙设备", "warning");
                return;
            }
            showLoading("正在与手柄进行配对和建立信任，请稍候...");
            
            fetch(`${API_BASE}/api/v1/system/bluetooth/connect`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mac: mac })
            })
            .then(res => {
                if (!res.ok) throw new Error("连接请求被拒绝");
                return res.json();
            })
            .then(data => {
                hideLoading();
                if (data.status === "success") {
                    showToast(data.message, "success");
                    refreshHostBluetoothStatus();
                } else {
                    showToast(`连接失败: ${data.message}`, "error");
                }
            })
            .catch(err => {
                hideLoading();
                showToast(`建立连接异常: ${err.message}`, "error");
            });
        });
    }

    // D. 断开连接并清除配对记录与信任
    if (btnDisconnect) {
        btnDisconnect.addEventListener("click", () => {
            const selectMac = deviceSelect ? deviceSelect.getAttribute("data-value") : "";
            
            // 先通过 status 获取当前连上的 mac 自动执行断开
            fetch(`${API_BASE}/api/v1/system/bluetooth/status`)
                .then(res => res.json())
                .then(data => {
                    const mac = selectMac || data.mac;
                    if (!mac) {
                        showToast("当前主机未连接手柄，且下拉列表中未选择设备", "warning");
                        return;
                    }
                    if (confirm("⚠️ 确定要断开手柄吗？这会同时清除主机的配对与信任，防止下次自动连。")) {
                        showLoading("正在断开并清理设备配对...");
                        fetch(`${API_BASE}/api/v1/system/bluetooth/disconnect`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ mac: mac })
                        })
                        .then(res => {
                            if (!res.ok) throw new Error("断开请求被拒绝");
                            return res.json();
                        })
                        .then(data => {
                            hideLoading();
                            if (data.status === "success") {
                                showToast(data.message, "success");
                                refreshHostBluetoothStatus();
                            } else {
                                showToast(`断开清理失败: ${data.message}`, "error");
                            }
                        })
                        .catch(err => {
                            hideLoading();
                            showToast(`断开清理异常: ${err.message}`, "error");
                        });
                    }
                });
        });
    }

    // E. 主机 Joy 驱动服务开关控制
    if (joySwitch) {
        joySwitch.addEventListener("change", (e) => {
            const checked = e.target.checked;
            if (!checked) {
                window.joyManuallyStopped = true;
            } else {
                window.joyManuallyStopped = false;
            }
            const apiPath = checked ? "/api/v1/robot/joy/start" : "/api/v1/robot/joy/stop";
            
            fetch(`${API_BASE}${apiPath}`, { method: "POST" })
                .then(res => {
                    if (!res.ok) return res.json().then(err => { throw new Error(err.detail || "操作失败") });
                    return res.json();
                })
                .then(data => {
                    showToast(data.detail, "success");
                })
                .catch(err => {
                    joySwitch.checked = !checked; // 恢复之前的状态
                    showToast(`主机 Joy 驱动控制失败: ${err.message}`, "error");
                });
        });
    }
}

function refreshHostBluetoothStatus() {
    const badge = document.getElementById("gamepad-status-badge");
    const infoRow = document.getElementById("gamepad-info-row");
    const modelSpan = document.getElementById("gamepad-model");
    const pulse = document.getElementById("gamepad-pulse");

    fetch(`${API_BASE}/api/v1/system/bluetooth/status`)
        .then(res => res.json())
        .then(data => {
            if (data.connected) {
                if (badge) {
                    badge.innerText = "已连接";
                    badge.className = "status-badge online";
                }
                if (infoRow) infoRow.classList.remove("hidden");
                if (modelSpan) modelSpan.innerText = `${data.name} [${data.mac}]`;
                if (pulse) pulse.className = "pulse-dot active success";
                
                // 默认开启主机 Joy 驱动服务：如果手柄已连接，但驱动并未开启且未被手动关闭，自动拉起
                const hostJoySwitch = document.getElementById("host-joy-enable-switch");
                const joyRunning = hostJoySwitch ? hostJoySwitch.checked : false;
                if (!joyRunning && !window.joyManuallyStopped) {
                    console.log("检测到手柄已连接且驱动未运行，正在自动拉起主机 Joy 驱动服务...");
                    fetch(`${API_BASE}/api/v1/robot/joy/start`, { method: "POST" })
                        .then(r => r.json())
                        .then(resData => {
                            showToast("已自动开启主机 Joy 驱动服务", "success");
                        })
                        .catch(err => console.error("自动开启主机 Joy 驱动服务失败:", err));
                }
            } else {
                if (badge) {
                    badge.innerText = "未连接";
                    badge.className = "status-badge offline";
                }
                if (infoRow) infoRow.classList.add("hidden");
                if (pulse) pulse.className = "pulse-dot";
                
                const lockRow = document.getElementById("gamepad-lock-row");
                if (lockRow) lockRow.classList.add("hidden");
                
                // 手柄断开时，重置手动关闭状态，为下次连接做好自动开启的准备
                window.joyManuallyStopped = false;
            }
        })
        .catch(err => console.error("静默获取主机蓝牙状态发生错误:", err));
}


// ==========================================
// 12. 新增：网页端虚拟摇杆 & 键盘遥控逻辑 (Web Teleop Cabin)
// ==========================================

let joystickActive = false;
let joystickX = 0;
let joystickY = 0;
const joystickMaxRadius = 38; // px

let webTeleopLoopActive = false;
let webTeleopFrameCounter = 0;

let pressedKeys = {
    w: false, a: false, s: false, d: false,
    ArrowUp: false, ArrowDown: false, ArrowLeft: false, ArrowRight: false
};

// A. 初始化网页虚拟摇杆手势
function initVirtualJoystick() {
    const base = document.getElementById("joystick-base");
    const handle = document.getElementById("joystick-handle");
    const webTeleopSwitch = document.getElementById("web-teleop-enable-switch");

    if (!base || !handle) return;

    function handleStart(e) {
        if (!webTeleopSwitch.checked) return;
        joystickActive = true;
        updateJoystickPosition(e);
        e.preventDefault();
    }

    function handleMove(e) {
        if (!joystickActive) return;
        updateJoystickPosition(e);
        e.preventDefault();
    }

    function handleEnd() {
        if (!joystickActive) return;
        joystickActive = false;
        joystickX = 0;
        joystickY = 0;
        handle.style.transform = `translate(0px, 0px)`;
    }

    function updateJoystickPosition(e) {
        const rect = base.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;

        let clientX = 0;
        let clientY = 0;
        if (e.touches && e.touches.length > 0) {
            clientX = e.touches[0].clientX;
            clientY = e.touches[0].clientY;
        } else {
            clientX = e.clientX;
            clientY = e.clientY;
        }

        const deltaX = clientX - centerX;
        const deltaY = clientY - centerY;
        const distance = Math.hypot(deltaX, deltaY);

        if (distance <= joystickMaxRadius) {
            joystickX = deltaX;
            joystickY = deltaY;
        } else {
            const angle = Math.atan2(deltaY, deltaX);
            joystickX = Math.cos(angle) * joystickMaxRadius;
            joystickY = Math.sin(angle) * joystickMaxRadius;
        }

        handle.style.transform = `translate(${joystickX.toFixed(1)}px, ${joystickY.toFixed(1)}px)`;
    }

    // 绑定事件
    base.addEventListener("mousedown", handleStart);
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleEnd);

    base.addEventListener("touchstart", handleStart, { passive: false });
    window.addEventListener("touchmove", handleMove, { passive: false });
    window.addEventListener("touchend", handleEnd);
}

// B. 初始化网页键盘监听
function initKeyboardTeleop() {
    const webTeleopSwitch = document.getElementById("web-teleop-enable-switch");
    if (!webTeleopSwitch) return;

    webTeleopSwitch.addEventListener("change", (e) => {
        const isChecked = e.target.checked;
        if (isChecked) {
            showToast("🎮 网页遥控已使能，支持虚拟摇杆与 WASD 键盘操作", "success");
            
            // 安全机制：使能网页控制时，自动将物理 Xbox 遥控关闭，防止信号冲突
            const gamepadSwitch = document.getElementById("gamepad-enable-switch");
            if (gamepadSwitch && gamepadSwitch.checked) {
                gamepadSwitch.checked = false;
                gamepadSwitch.dispatchEvent(new Event("change"));
            }
            
            startWebTeleopLoop();
        } else {
            showToast("🎮 网页遥控已关闭", "info");
            stopWebTeleopLoop();
            
            // 复位键盘按键的高亮状态
            resetKeyboardVisualKeys();
            // 刹车
            sendGamepadTeleopCommand(0.0, 0.0);
        }
    });

    window.addEventListener("keydown", (e) => {
        if (!webTeleopSwitch.checked) return;
        // 如果焦点在输入框中，不能触发键盘遥控
        if (document.activeElement && (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA" || document.activeElement.tagName === "SELECT")) {
            return;
        }

        const key = e.key.toLowerCase();
        if (e.key === "w" || e.key === "ArrowUp") {
            pressedKeys.w = true; pressedKeys.ArrowUp = true;
            highlightKey("key-w", true);
            e.preventDefault();
        } else if (e.key === "s" || e.key === "ArrowDown") {
            pressedKeys.s = true; pressedKeys.ArrowDown = true;
            highlightKey("key-s", true);
            e.preventDefault();
        } else if (e.key === "a" || e.key === "ArrowLeft") {
            pressedKeys.a = true; pressedKeys.ArrowLeft = true;
            highlightKey("key-a", true);
            e.preventDefault();
        } else if (e.key === "d" || e.key === "ArrowRight") {
            pressedKeys.d = true; pressedKeys.ArrowRight = true;
            highlightKey("key-d", true);
            e.preventDefault();
        }
    });

    window.addEventListener("keyup", (e) => {
        if (!webTeleopSwitch.checked) return;

        if (e.key === "w" || e.key === "ArrowUp") {
            pressedKeys.w = false; pressedKeys.ArrowUp = false;
            highlightKey("key-w", false);
        } else if (e.key === "s" || e.key === "ArrowDown") {
            pressedKeys.s = false; pressedKeys.ArrowDown = false;
            highlightKey("key-s", false);
        } else if (e.key === "a" || e.key === "ArrowLeft") {
            pressedKeys.a = false; pressedKeys.ArrowLeft = false;
            highlightKey("key-a", false);
        } else if (e.key === "d" || e.key === "ArrowRight") {
            pressedKeys.d = false; pressedKeys.ArrowRight = false;
            highlightKey("key-d", false);
        }
    });
}

function highlightKey(keyId, active) {
    const el = document.getElementById(keyId);
    if (!el) return;
    if (active) {
        el.classList.add("active");
    } else {
        el.classList.remove("active");
    }
}

function resetKeyboardVisualKeys() {
    pressedKeys = {
        w: false, a: false, s: false, d: false,
        ArrowUp: false, ArrowDown: false, ArrowLeft: false, ArrowRight: false
    };
    highlightKey("key-w", false);
    highlightKey("key-a", false);
    highlightKey("key-s", false);
    highlightKey("key-d", false);
}

function startWebTeleopLoop() {
    if (!webTeleopLoopActive) {
        webTeleopLoopActive = true;
        requestAnimationFrame(webTeleopLoop);
    }
}

function stopWebTeleopLoop() {
    webTeleopLoopActive = false;
}

function webTeleopLoop() {
    const webTeleopSwitch = document.getElementById("web-teleop-enable-switch");
    if (!webTeleopSwitch || !webTeleopSwitch.checked) {
        webTeleopLoopActive = false;
        return;
    }

    let linearX = 0.0;
    let angularZ = 0.0;

    // 1. 如果处于摇杆操作状态，优先执行摇杆遥控值
    if (joystickActive) {
        // joystickY 向上为负，前进为正，取反
        const rawLinear = -joystickY / joystickMaxRadius;
        // joystickX 向左为负，左转为正（逆时针 Yaw），取反
        const rawAngular = -joystickX / joystickMaxRadius;

        linearX = rawLinear * 0.45;
        angularZ = rawAngular * 2.50;
    } else {
        // 2. 否则执行键盘按键遥控值
        let keyLinear = 0.0;
        let keyAngular = 0.0;

        if (pressedKeys.w || pressedKeys.ArrowUp) keyLinear += 1.0;
        if (pressedKeys.s || pressedKeys.ArrowDown) keyLinear -= 1.0;
        if (pressedKeys.a || pressedKeys.ArrowLeft) keyAngular += 1.0;
        if (pressedKeys.d || pressedKeys.ArrowRight) keyAngular -= 1.0;

        linearX = keyLinear * 0.45;
        angularZ = keyAngular * 2.50;
    }

    // 限幅裁剪约束
    linearX = Math.min(Math.max(linearX, -0.45), 0.45);
    angularZ = Math.min(Math.max(angularZ, -2.50), 2.50);

    webTeleopFrameCounter++;
    // 限流 15Hz (每 4 帧下发一次)
    if (webTeleopFrameCounter % 4 === 0) {
        sendGamepadTeleopCommand(linearX, angularZ);
    }

    if (webTeleopLoopActive) {
        requestAnimationFrame(webTeleopLoop);
    }
}



function sendGamepadTeleopCommand(linearX, angularZ) {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            type: "teleop",
            linear_x: linearX,
            angular_z: angularZ
        }));
    } else {
        console.warn("WebSocket not open. Cannot send teleop command.");
    }
}
