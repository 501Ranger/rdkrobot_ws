// ==========================================
// 1. 状态轮询与 WebSocket 逻辑 (Status Polling & WS)
// ==========================================

let socket = null;
let waypointList = [];
let dragSourceElement = null;
let pollTimer = null;
let wsFailures = 0;
const MAX_WS_FAILURES = 3;
let usingWebSocket = false;
let robotTrajectory = [];
const MAX_TRAJECTORY_POINTS = 500;
let showTrajectory = true;

function initWebSocket() {
    if (socket) {
        try { socket.close(); } catch(e) {}
    }
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws/status`);

    socket.onopen = () => {
        console.log("WebSocket connected.");
        wsFailures = 0;
        usingWebSocket = true;
        updateConnectionStatus(true);
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    };

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateTelemetry(data);
        } catch (e) {
            console.error("Error parsing WebSocket JSON data:", e);
        }
    };

    socket.onclose = () => {
        console.log("WebSocket connection closed.");
        usingWebSocket = false;
        wsFailures++;
        
        if (wsFailures >= MAX_WS_FAILURES) {
            console.warn("WebSocket failed repeatedly. Falling back to HTTP polling.");
            updateConnectionStatus(false);
            startHttpPolling();
        } else {
            updateConnectionStatus(false);
            setTimeout(initWebSocket, 2000);
        }
    };

    socket.onerror = (error) => {
        console.error("WebSocket error:", error);
        socket.close();
    };
}

function startHttpPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollStatusHttp();
    pollTimer = setInterval(pollStatusHttp, 1500);
}

function pollStatusHttp() {
    if (usingWebSocket) return;
    
    fetch(`${API_BASE}/api/v1/robot/status`)
        .then(res => {
            if (!res.ok) throw new Error("HTTP status check failed");
            return res.json();
        })
        .then(data => {
            updateTelemetry(data);
            updateConnectionStatus(true);
        })
        .catch(err => {
            console.error("HTTP Status polling failed:", err);
            updateConnectionStatus(false);
        });
}

function updateTelemetry(data) {
    updateConnectionStatus(true);
    
    // 定时巡逻触发提示
    if (data.scheduled_patrol_triggered) {
        showNotificationBanner("定时巡逻计划已启动，正在执行单次顺序巡逻...", "patrol");
    }
    
    // 巡逻航点到达提示
    if (data.waypoint_reached && data.waypoint_reached > 0) {
        showNotificationBanner(`机器人已顺利到达第 ${data.waypoint_reached} 个巡逻点！`, "success");
    }
    
    // 巡逻全部完成提示
    if (data.patrol_completed) {
        showNotificationBanner("🏆 整条航线巡逻已全部顺利完成！", "success");
    }
    
    // 巡逻异常中断提示
    if (data.patrol_interrupted) {
        if (data.patrol_interrupted === "aborted") {
            showNotificationBanner("⚠️ 巡逻被迫中止：导航目标被拒绝或发生障碍失败！", "error");
        } else if (data.patrol_interrupted === "canceled") {
            showNotificationBanner("⚠️ 巡逻已取消：被新的单点导航目标抢占。", "patrol");
        } else {
            showNotificationBanner("⚠️ 巡逻任务异常终止！", "error");
        }
    }
    
    // 实时 SLAM 建图动态图像渲染
    if (data.realtime_map) {
        const realtime = data.realtime_map;
        
        // 动态绑定 currentMap 元数据以保持实时坐标映射工作正常
        currentMap = {
            name: "realtime_slam_map",
            resolution: realtime.resolution,
            origin: realtime.origin,
            width: realtime.width,
            height: realtime.height
        };
        
        // 动态更新底图数据源
        const img = document.getElementById("map-image");
        if (img) {
            img.src = `data:image/png;base64,${realtime.image_base64}`;
        }
        
        // 显式显示地图容器并隐藏空地图占位
        const placeholder = document.getElementById("map-placeholder");
        const innerContainer = document.getElementById("map-inner-container");
        if (placeholder) placeholder.classList.add("hidden");
        if (innerContainer) innerContainer.classList.remove("hidden");
        
        // 首次激活时，复位缩放与平移以便完整居中追踪，后续更新时只刷新底图以维护用户手势交互位置
        if (!isRealtimeMapActive) {
            isRealtimeMapActive = true;
            zoomScale = 1.0;
            panX = 0;
            panY = 0;
            updateMapTransform();
        }
    }
    
    // 更新位姿
    if (data.pose) {
        document.getElementById("pose-x").innerText = `${data.pose.x.toFixed(3)} m`;
        document.getElementById("pose-y").innerText = `${data.pose.y.toFixed(3)} m`;
        const deg = (data.pose.yaw * 180 / Math.PI).toFixed(1);
        document.getElementById("pose-yaw").innerText = `${deg}°`;
        
        currentPose = data.pose;
        updateRobotMarkerOnMap(currentPose);
    }
    
    // 更新 Nav2 全局规划路线
    if (data.nav2_plan) {
        drawNav2Path(data.nav2_plan);
    } else {
        drawNav2Path([]);
    }
    
    // 导航状态
    const navStatusEl = document.getElementById("nav-status");
    const navStatus = data.nav_status ? data.nav_status.toUpperCase() : "IDLE";
    navStatusEl.innerText = navStatus;
    
    // 改变状态文字颜色 (适配新的 HMI 状态配色)
    navStatusEl.className = "val status-text";
    if (navStatus === "NAVIGATING") {
        navStatusEl.style.color = "var(--accent-cyan)";
    } else if (navStatus === "REACHED") {
        navStatusEl.style.color = "var(--accent-green)";
        if (lastNavStatus === "NAVIGATING") {
            hideGoalMarker(); // 只有从导航状态到达后才清除标记
            showNotificationBanner("机器人已顺利到达目标点！", "success");
        }
    } else if (navStatus === "FAILED") {
        navStatusEl.style.color = "var(--accent-red)";
        if (lastNavStatus === "NAVIGATING") {
            hideGoalMarker(); // 只有从导航状态失败后才清除标记
        }
    } else {
        navStatusEl.style.color = "var(--accent-orange)";
        if (navStatus === "IDLE" || navStatus === "CANCELLED") {
            if (lastNavStatus === "NAVIGATING") {
                hideGoalMarker(); // 只有从导航状态取消后才清除标记
            }
        }
    }
    lastNavStatus = navStatus;

    // 更新电量
    updateBatteryDisplay(data.battery_percentage);
    
    // 更新重定位状态
    updateLocalizeStatusDisplay(data.is_localizing);

    // 更新下位机在线状态
    updateMcuStatus(data.mcu_online);

    // 更新实机一键初始化按钮状态
    const btnInitHardware = document.getElementById("btn-init-hardware");
    if (btnInitHardware) {
        if (data.base_running && data.lidar_running && data.agent_running) {
            btnInitHardware.innerText = "🔌 实机已初始化";
            btnInitHardware.className = "btn btn-success";
        } else {
            btnInitHardware.innerText = "🔌 实机一键初始化";
            btnInitHardware.className = "btn btn-warning";
        }
    }

    // 更新 SLAM 按钮状态
    const btnStartSlam = document.getElementById("btn-start-slam");
    const btnStopSlam = document.getElementById("btn-stop-slam");
    if (data.slam_running) {
        btnStartSlam.classList.add("hidden");
        btnStopSlam.classList.remove("hidden");
    } else {
        btnStartSlam.classList.remove("hidden");
        btnStopSlam.classList.add("hidden");
    }

    // 更新自主探索按钮状态
    const btnStartExplore = document.getElementById("btn-start-explore");
    const btnStopExplore = document.getElementById("btn-stop-explore");
    if (data.explore_running) {
        btnStartExplore.classList.add("hidden");
        btnStopExplore.classList.remove("hidden");
    } else {
        btnStartExplore.classList.remove("hidden");
        btnStopExplore.classList.add("hidden");
    }

    // 初始化串口文本框默认值（如果为空）
    const inputAgentPort = document.getElementById("input-agent-port");
    const inputLidarPort = document.getElementById("input-lidar-port");
    if (inputAgentPort && data.agent_port && !inputAgentPort.value) {
        inputAgentPort.value = data.agent_port;
    }
    if (inputLidarPort && data.lidar_port && !inputLidarPort.value) {
        inputLidarPort.value = data.lidar_port;
    }

    // 更新 Gazebo 仿真按钮状态
    const btnStartSim = document.getElementById("btn-start-sim");
    const btnStopSim = document.getElementById("btn-stop-sim");
    if (btnStartSim && btnStopSim) {
        if (data.sim_running) {
            btnStartSim.classList.add("hidden");
            btnStopSim.classList.remove("hidden");
        } else {
            btnStartSim.classList.remove("hidden");
            btnStopSim.classList.add("hidden");
        }
    }

    // 更新主机 Joy 驱动开关状态与手柄解锁保护使能状态
    const hostJoySwitch = document.getElementById("host-joy-enable-switch");
    if (hostJoySwitch) {
        hostJoySwitch.checked = !!data.joy_running;
    }

    const gamepadBadge = document.getElementById("gamepad-status-badge");
    const isGamepadConnected = gamepadBadge && gamepadBadge.classList.contains("online");
    const lockRow = document.getElementById("gamepad-lock-row");
    const lockBadge = document.getElementById("gamepad-lock-badge");

    if (lockRow && lockBadge) {
        if (data.joy_running && isGamepadConnected) {
            lockRow.classList.remove("hidden");
            if (data.joy_unlocked) {
                lockBadge.innerText = "已就绪 (READY)";
                lockBadge.className = "status-badge online";
            } else {
                lockBadge.innerText = "已锁定 (按 LT/RT 解锁)";
                lockBadge.className = "status-badge warning";
            }
        } else {
            lockRow.classList.add("hidden");
        }
    }

    if (data.system_logs) {
        window.lastReceivedSystemLogs = data.system_logs;
        updateSystemTerminal(data.system_logs);
    }
}

function initTabs() {
    const tabButtons = document.querySelectorAll(".tab-button");
    const tabPanes = document.querySelectorAll(".tab-pane");

    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");

            tabButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            tabPanes.forEach(pane => pane.classList.add("hidden"));
            document.getElementById(targetTab).classList.remove("hidden");
        });
    });
}


function updateConnectionStatus(isOnline) {
    const badge = document.getElementById("connection-status");
    if (isOnline) {
        badge.innerText = "在线";
        badge.className = "status-badge online";
        document.getElementById("dot-api").className = "pill-dot active success";
    } else {
        badge.innerText = "断开";
        badge.className = "status-badge offline";
        document.getElementById("dot-api").className = "pill-dot active danger";
        
        // 重置看板参数
        document.getElementById("pose-x").innerText = "-- m";
        document.getElementById("pose-y").innerText = "-- m";
        document.getElementById("pose-yaw").innerText = "--°";
        document.getElementById("nav-status").innerText = "UNKNOWN";
        document.getElementById("nav-status").style.color = "var(--text-muted)";
        updateBatteryDisplay(0);
        document.getElementById("robot-marker").classList.add("hidden");
        updateLocalizeStatusDisplay(false);
        currentPose = null;
        updateMcuStatus(false);
    }
}

function updateBatteryDisplay(percentage) {
    const bar = document.getElementById("battery-bar");
    const txt = document.getElementById("battery-text");
    
    bar.style.width = `${percentage}%`;
    txt.innerText = `${percentage.toFixed(0)}%`;
    
    // 根据电量级别改变颜色
    if (percentage > 50) {
        bar.style.backgroundColor = "var(--accent-green)";
    } else if (percentage > 20) {
        bar.style.backgroundColor = "var(--accent-orange)";
    } else {
        bar.style.backgroundColor = "var(--accent-red)";
    }
}

let logsOffset = 0;

function updateSystemTerminal(logs) {
    const contentEl = document.getElementById("terminal-content");
    if (!contentEl) return;
    
    const visibleLogs = logs.slice(logsOffset);
    
    // 如果无新日志，不做重绘
    const signature = visibleLogs.map(l => `${l.time}-${l.level}-${l.message}`).join("|");
    if (contentEl.getAttribute("data-signature") === signature) {
        return;
    }
    contentEl.setAttribute("data-signature", signature);
    
    const terminalLines = [];
    terminalLines.push(`<div style="color: var(--text-secondary); padding-bottom: 2px; border-bottom: 1px dashed rgba(255,255,255,0.03); margin-bottom: 4px;">[HMI] 终端会话已激活。正在监听系统核心重大事件...</div>`);
    
    visibleLogs.forEach(log => {
        let color = "var(--accent-cyan)";
        if (log.level === "WARNING") {
            color = "var(--accent-orange)";
        } else if (log.level === "ERROR") {
            color = "var(--accent-red)";
        }
        
        terminalLines.push(`
            <div class="terminal-line" style="display: flex; gap: 8px; font-family: monospace; font-size: 0.76rem;">
                <span style="color: var(--text-secondary); min-width: 65px; user-select: none;">[${log.time}]</span>
                <span style="color: ${color}; font-weight: bold; min-width: 55px; user-select: none;">[${log.level}]</span>
                <span style="color: var(--text-primary); word-break: break-all;">${log.message}</span>
            </div>
        `);
    });
    
    contentEl.innerHTML = terminalLines.join("");
    
    // 自动滚动到底部
    const bodyEl = document.querySelector(".terminal-body");
    if (bodyEl) {
        bodyEl.scrollTop = bodyEl.scrollHeight;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const btnClearTerminal = document.getElementById("btn-clear-terminal");
    if (btnClearTerminal) {
        btnClearTerminal.addEventListener("click", () => {
            logsOffset = window.lastReceivedSystemLogs ? window.lastReceivedSystemLogs.length : 0;
            updateSystemTerminal([]);
        });
    }
});


