// API 基础路径（自动适配当前主机的 IP 和端口）
const API_BASE = window.location.origin;

// 全局状态变量
let mapList = [];
let currentMap = null;
let pollInterval = null;
let statusInterval = null;
let currentPose = null;
let currentGoal = null; // 当前导航目标点 {x, y}
let isEstimatingPose = false;
let estimatePoseVal = { x: 0.0, y: 0.0, yaw: 0.0 };
let lastNavStatus = "IDLE";
let bannerTimeout = null;
let isRealtimeMapActive = false;

// 全局加载指示器控制
function showLoading(text = "系统正在工作，请稍候...") {
    const overlay = document.getElementById("loading-overlay");
    const label = document.getElementById("loading-text");
    if (overlay && label) {
        label.innerText = text;
        overlay.style.display = "flex";
    }
}

function hideLoading() {
    const overlay = document.getElementById("loading-overlay");
    if (overlay) {
        overlay.style.display = "none";
    }
}

// 全局通知条幅控制器
function showNotificationBanner(message, type = "patrol", duration = 5000) {
    const banner = document.getElementById("notification-banner");
    if (!banner) return;
    
    const iconEl = banner.querySelector(".banner-icon");
    const messageEl = banner.querySelector(".banner-message");
    
    if (type === "patrol") {
        iconEl.innerText = "⏱️";
        banner.className = "notification-banner patrol show";
    } else if (type === "success") {
        iconEl.innerText = "🏁";
        banner.className = "notification-banner success show";
    } else if (type === "error") {
        iconEl.innerText = "⚠️";
        banner.className = "notification-banner error show";
    } else {
        iconEl.innerText = "🔔";
        banner.className = "notification-banner show";
    }
    
    messageEl.innerText = message;
    
    if (bannerTimeout) {
        clearTimeout(bannerTimeout);
    }
    
    bannerTimeout = setTimeout(() => {
        banner.classList.remove("show");
    }, duration);
}

// 地图缩放与平移交互状态
let zoomScale = 1.0;
let panX = 0;
let panY = 0;
let isDragging = false;
let hasDragged = false;
let startX = 0;
let startY = 0;
let dragStartX = 0;
let dragStartY = 0;

// DOM 载入完成后的初始化
document.addEventListener("DOMContentLoaded", () => {
    // 0. 初始化页面配色主题
    initTheme();
    
    // 1. 初始化侧边栏 Tab 切换视图
    initSidebarTabs();
    
    // 2. 初始化网页端虚拟摇杆与键盘控制
    initVirtualJoystick();
    initKeyboardTeleop();

    // 3. 初始化主机蓝牙手柄管理
    initHostGamepad();

    // 4. 检测系统环境是否为 ARM 以展示或隐藏仿真控制并刷新平台型号
    checkSystemInfo();

    // 4.1 开启上位机系统性能实时监视轮询并获取一次可用串口列表
    startSystemStatusPolling();
    refreshAvailableSerialPorts();

    // 5. 初始化拉取各接口数据
    refreshMapList();
    refreshScheduleList();
    refreshMapGallery();
    
    // 6. 初始化子标签页（巡逻的 POI / 航线规划 Tabs）与 WebSocket 实时推送
    initTabs();
    initWebSocket();

    // 7. 绑定所有交互按键的事件监听
    setupEventListeners();
});

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

// ==========================================
// 1.1 侧边栏主标签页导航视图切换 (Sidebar Navigation)
// ==========================================
function initSidebarTabs() {
    const navItems = document.querySelectorAll(".nav-item");
    const viewPanes = document.querySelectorAll(".view-pane");

    // 获取本地记忆的激活视图，默认为 cockpit
    const savedView = localStorage.getItem("active-view-pane") || "view-cockpit";

    // 渲染初始化激活状态
    navItems.forEach(item => {
        const viewName = item.getAttribute("data-view");
        if (viewName === savedView) {
            item.classList.add("active");
        } else {
            item.classList.remove("active");
        }
    });

    viewPanes.forEach(pane => {
        if (pane.id === savedView) {
            pane.classList.remove("hidden");
        } else {
            pane.classList.add("hidden");
        }
    });

    // 绑定导航事件
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetView = item.getAttribute("data-view");
            if (!targetView) return;

            navItems.forEach(i => i.classList.remove("active"));
            item.classList.add("active");

            viewPanes.forEach(pane => {
                if (pane.id === targetView) {
                    pane.classList.remove("hidden");
                } else {
                    pane.classList.add("hidden");
                }
            });

            localStorage.setItem("active-view-pane", targetView);
            showToast(`已切入面板: ${item.querySelector('.nav-text').innerText}`, "success");
        });
    });
}

function addWaypointToList(x, y, yaw) {
    waypointList.push({ x, y, yaw });
    renderWaypointList();
    showToast(`添加航点成功: WP${waypointList.length} (${x.toFixed(2)}, ${y.toFixed(2)})`, "success");
}

function renderWaypointList() {
    const listEl = document.getElementById("waypoint-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    
    if (waypointList.length === 0) {
        listEl.innerHTML = '<li class="empty-list-text">暂无航点，请在上方切换“添加航点”并在地图上点击</li>';
        drawPlannedPath();
        return;
    }
    
    waypointList.forEach((wp, index) => {
        const li = document.createElement("li");
        li.className = "waypoint-item";
        li.setAttribute("draggable", "true");
        li.setAttribute("data-index", index);
        
        li.innerHTML = `
            <span class="wp-index">${index + 1}</span>
            <span class="wp-coords">X: ${wp.x.toFixed(3)} | Y: ${wp.y.toFixed(3)} | Yaw: ${wp.yaw.toFixed(2)}</span>
            <div class="wp-actions">
                <button class="btn-move-wp btn-move-up" title="上移" ${index === 0 ? 'disabled' : ''}>▲</button>
                <button class="btn-move-wp btn-move-down" title="下移" ${index === waypointList.length - 1 ? 'disabled' : ''}>▼</button>
                <button class="btn-remove-wp" title="删除当前点">&times;</button>
            </div>
        `;
        
        // 上下排序点击事件
        const btnUp = li.querySelector(".btn-move-up");
        const btnDown = li.querySelector(".btn-move-down");
        if (btnUp) {
            btnUp.addEventListener("click", (e) => {
                e.stopPropagation();
                moveWaypoint(index, -1);
            });
        }
        if (btnDown) {
            btnDown.addEventListener("click", (e) => {
                e.stopPropagation();
                moveWaypoint(index, 1);
            });
        }
        
        // 删除事件
        li.querySelector(".btn-remove-wp").addEventListener("click", (e) => {
            e.stopPropagation();
            removeWaypoint(index);
        });
        
        // 拖拽排序事件监听 (原生 DND)
        li.addEventListener("dragstart", handleDragStart);
        li.addEventListener("dragover", handleDragOver);
        li.addEventListener("drop", handleDrop);
        li.addEventListener("dragend", handleDragEnd);
        
        listEl.appendChild(li);
    });
    
    drawPlannedPath();
}

function removeWaypoint(index) {
    waypointList.splice(index, 1);
    renderWaypointList();
}

function moveWaypoint(index, direction) {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= waypointList.length) return;
    const temp = waypointList[index];
    waypointList[index] = waypointList[targetIndex];
    waypointList[targetIndex] = temp;
    renderWaypointList();
}

function handleDragStart(e) {
    this.classList.add("dragging");
    dragSourceElement = this;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/html", this.innerHTML);
}

function handleDragOver(e) {
    if (e.preventDefault) {
        e.preventDefault();
    }
    e.dataTransfer.dropEffect = "move";
    return false;
}

function handleDrop(e) {
    e.stopPropagation();
    
    if (dragSourceElement !== this) {
        const fromIndex = parseInt(dragSourceElement.getAttribute("data-index"), 10);
        const toIndex = parseInt(this.getAttribute("data-index"), 10);
        
        // 重整航点顺序数组
        const temp = waypointList[fromIndex];
        waypointList.splice(fromIndex, 1);
        waypointList.splice(toIndex, 0, temp);
        
        renderWaypointList();
    }
    return false;
}

function handleDragEnd(e) {
    this.classList.remove("dragging");
    const items = document.querySelectorAll(".waypoint-item");
    items.forEach(item => item.classList.remove("dragging"));
}

function startWaypointPatrol() {
    if (waypointList.length === 0) {
        showToast("航点列表不能为空，请先添加航点", "error");
        return;
    }
    
    showToast("正在下发路径规划点位并启动巡逻...", "info");
    
    fetch(`${API_BASE}/api/v1/patrol/task`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ waypoints: waypointList })
    })
    .then(res => {
        if (!res.ok) throw new Error("下发路径失败");
        return res.json();
    })
    .then(() => {
        return fetch(`${API_BASE}/api/v1/patrol/cmd`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cmd: "start_once" })
        });
    })
    .then(res => {
        if (!res.ok) throw new Error("启动巡逻失败");
        return res.json();
    })
    .then(() => {
        showToast("多点巡逻启动成功！机器人已出发！", "success");
    })
    .catch(err => {
        showToast(err.message || "启动巡逻失败，请检查服务状态", "error");
    });
}

function refreshMapGallery() {
    const galleryEl = document.getElementById("map-gallery");
    if (!galleryEl) return;
    
    fetch(`${API_BASE}/api/v1/maps`)
        .then(res => res.json())
        .then(data => {
            galleryEl.innerHTML = "";
            if (data.length === 0) {
                galleryEl.innerHTML = '<div class="empty-list-text">暂无历史地图，请在“建图与图库”中建图并保存</div>';
                return;
            }
            
            data.forEach(map => {
                const card = document.createElement("div");
                card.className = "gallery-map-card";
                
                const imageUrl = `${API_BASE}/api/v1/maps/${map.name}/image`;
                const dateStr = map.created_at || '未知时间';
                const resolutionStr = map.resolution ? `${map.resolution.toFixed(3)} m/px` : '未知';
                
                card.innerHTML = `
                    <div class="gallery-map-preview">
                        <img src="${imageUrl}" alt="${map.name}" onerror="this.src='/static/css/images/map_fallback.png';">
                    </div>
                    <div class="gallery-map-info">
                        <div class="gallery-map-name" title="${map.name}">${map.name}</div>
                        <div class="gallery-map-meta">📅 创建: ${dateStr}</div>
                        <div class="gallery-map-meta">📏 分辨率: ${resolutionStr}</div>
                        <div class="gallery-map-actions">
                            <button class="btn btn-primary btn-load-gallery-map">加载</button>
                            <button class="btn btn-danger btn-delete-gallery-map">删除</button>
                        </div>
                    </div>
                `;
                
                card.querySelector(".btn-load-gallery-map").addEventListener("click", () => {
                    const select = document.getElementById("map-select");
                    select.value = map.name;
                    loadSelectedMap();
                    showToast(`正在从图库加载地图 '${map.name}'...`, "info");
                });
                
                card.querySelector(".btn-delete-gallery-map").addEventListener("click", () => {
                    if (confirm(`⚠️ 警告: 您确定要永久删除地图 '${map.name}' 的所有文件吗？此操作无法撤销！`)) {
                        deleteGalleryMap(map.name);
                    }
                });
                
                galleryEl.appendChild(card);
            });
        })
        .catch(() => {
            galleryEl.innerHTML = '<div class="empty-list-text">加载图库失败，请检查网络</div>';
        });
}

function deleteGalleryMap(mapName) {
    fetch(`${API_BASE}/api/v1/maps/${mapName}`, {
        method: "DELETE"
    })
    .then(res => {
        if (!res.ok) throw new Error();
        return res.json();
    })
    .then(() => {
        showToast(`地图 '${mapName}' 已成功删除`, "success");
        refreshMapList();
        refreshMapGallery();
    })
    .catch(() => {
        showToast(`删除地图 '${mapName}' 失败`, "error");
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

// ==========================================
// 2. 地图文件与管理逻辑 (Map Management)
// ==========================================

function refreshMapList() {
    fetch(`${API_BASE}/api/v1/maps`)
        .then(res => res.json())
        .then(data => {
            mapList = data;
            const select = document.getElementById("map-select");
            
            // 刷新后恢复之前选择的值
            const prevVal = select.value;
            select.innerHTML = '<option value="">-- 请选择地图 --</option>';
            
            data.forEach(map => {
                const opt = document.createElement("option");
                opt.value = map.name;
                opt.innerText = `${map.name} (${map.created_at || '未知时间'})`;
                select.appendChild(opt);
            });

            if (prevVal && data.some(m => m.name === prevVal)) {
                select.value = prevVal;
            }
        })
        .catch(() => showToast("获取地图列表失败", "error"));
}

function loadSelectedMap() {
    const mapName = document.getElementById("map-select").value;
    if (!mapName) {
        showToast("请先选择一个地图", "error");
        return;
    }

    currentMap = mapList.find(m => m.name === mapName);
    isRealtimeMapActive = false; // 切换为静态地图，解除实时地图标志
    
    // 显示加载态
    const placeholder = document.getElementById("map-placeholder");
    const loader = document.getElementById("map-loading");
    const img = document.getElementById("map-image");
    const innerContainer = document.getElementById("map-inner-container");
    
    placeholder.classList.add("hidden");
    innerContainer.classList.add("hidden");
    loader.classList.remove("hidden");

    showLoading(`正在载入地图 '${mapName}' 并启动定位服务...`);

    // 调用后端 API 加载地图至导航系统
    fetch(`${API_BASE}/api/v1/maps/${mapName}/load`, { method: "POST" })
        .then(res => {
            if (!res.ok) return res.json().then(err => { throw new Error(err.detail || "加载失败") });
            return res.json();
        })
        .then(data => {
            showToast(`地图 '${mapName}' 载入导航系统`, "success");
            
            // 拉取预览图
            img.src = `${API_BASE}/api/v1/maps/${mapName}/image?t=${new Date().getTime()}`;
            img.onload = () => {
                loader.classList.add("hidden");
                innerContainer.classList.remove("hidden");
                hideLoading();
                // 重置缩放与平移状态
                zoomScale = 1.0;
                panX = 0;
                panY = 0;
                updateMapTransform();
                
                // 重置小车历史轨迹并清空显示
                robotTrajectory = [];
                drawTrajectory();
                drawPlannedPath();
            };
            img.onerror = () => {
                hideLoading();
                showToast("获取地图底图失败", "error");
            };
            
            // 拉取这个地图的 POI 列表
            refreshPoiList(mapName);
        })
        .catch(err => {
            hideLoading();
            showToast(err.message, "error");
            loader.classList.add("hidden");
            innerContainer.classList.add("hidden");
            placeholder.classList.remove("hidden");
            currentMap = null;
        });
}

// ==========================================
// 3. 地图坐标映射算法 (Coordinate Mapping)
// ==========================================

function handleMapClick(e) {
    if (!currentMap || hasDragged) return;
    
    const img = document.getElementById("map-image");
    const rect = img.getBoundingClientRect();
    // 鼠标点击图上的像素坐标 (从左上角起算)
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;

    // 网页显示的图像尺寸和图片本身的实际物理分辨率
    const displayWidth = rect.width;
    const displayHeight = rect.height;
    const naturalWidth = img.naturalWidth;
    const naturalHeight = img.naturalHeight;

    // 换算成图片的实际像素坐标
    const pixelX = clickX * (naturalWidth / displayWidth);
    const pixelY = clickY * (naturalHeight / displayHeight);

    // 读取 YAML 的元数据
    const resolution = currentMap.resolution; // 米/像素
    const originX = currentMap.origin[0];     // 图像左下角的 ROS X 物理坐标
    const originY = currentMap.origin[1];     // 图像左下角的 ROS Y 物理坐标

    // ⚠️ 转换公式：ROS 原点在图像的左下角 (Bottom-Left)
    // 像素的 Y 轴是从上往下增长，而 ROS 物理 Y 轴是从下往上增长
    const worldX = originX + (pixelX * resolution);
    const worldY = originY + ((naturalHeight - pixelY) * resolution);

    if (isEstimatingPose) {
        document.getElementById("est-x").value = worldX.toFixed(3);
        document.getElementById("est-y").value = worldY.toFixed(3);
        estimatePoseVal.x = worldX;
        estimatePoseVal.y = worldY;
        showEstimateMarker(worldX, worldY);
        showToast(`已标定估算位置：X=${worldX.toFixed(3)}, Y=${worldY.toFixed(3)}`, "info");
        return;
    }

    // 检查当前点击模式
    const clickMode = document.querySelector('input[name="map-click-mode"]:checked')?.value || "nav";
    if (clickMode === "waypoint") {
        addWaypointToList(worldX, worldY, 0.0);
    } else {
        // 单点导航模式：填入输入框并高亮提示
        document.getElementById("poi-x").value = worldX.toFixed(3);
        document.getElementById("poi-y").value = worldY.toFixed(3);
        document.getElementById("poi-yaw").value = "0.000"; // 默认朝向设为 0.000
        showGoalMarker(worldX, worldY); // 选点后立即展示标记点！
        showToast(`提取坐标成功: X=${worldX.toFixed(3)}, Y=${worldY.toFixed(3)}`, "success");
    }
}

// ==========================================
// 4. 语义点 POI 管理 (POI Management)
// ==========================================

function refreshPoiList(mapName) {
    fetch(`${API_BASE}/api/v1/maps/${mapName}/pois`)
        .then(res => res.json())
        .then(data => {
            const list = document.getElementById("poi-list");
            list.innerHTML = "";
            
            if (data.length === 0) {
                list.innerHTML = '<li class="empty-list-text">暂无已存标记点</li>';
                return;
            }

            data.forEach(poi => {
                const li = document.createElement("li");
                li.className = "poi-item";
                li.innerHTML = `
                    <div class="poi-info">
                        <span class="poi-title">${poi.name}</span>
                        <span class="poi-coord-lbl">X:${poi.x.toFixed(2)} Y:${poi.y.toFixed(2)} Yaw:${poi.yaw.toFixed(2)}</span>
                    </div>
                    <button class="btn-go" onclick="navigateByPoiName('${poi.name}')">去这里</button>
                `;
                list.appendChild(li);
            });
        }).catch(() => {});
}

function saveCurrentPoi() {
    if (!currentMap) {
        showToast("请先选择并加载地图", "error");
        return;
    }
    const name = document.getElementById("poi-name").value.trim();
    const x = parseFloat(document.getElementById("poi-x").value);
    const y = parseFloat(document.getElementById("poi-y").value);
    const yaw = parseFloat(document.getElementById("poi-yaw").value);

    if (!name || isNaN(x) || isNaN(y) || isNaN(yaw)) {
        showToast("请完整填写标记点名称及坐标参数", "error");
        return;
    }

    const mapName = currentMap.name;

    // 先拉取已有的，追加后保存
    fetch(`${API_BASE}/api/v1/maps/${mapName}/pois`)
        .then(res => res.json())
        .then(pois => {
            const filtered = pois.filter(p => p.name !== name);
            filtered.push({ name, x, y, yaw });
            
            return fetch(`${API_BASE}/api/v1/maps/${mapName}/pois`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(filtered)
            });
        })
        .then(res => res.json())
        .then(() => {
            showToast(`标记点 '${name}' 已保存`, "success");
            document.getElementById("poi-name").value = "";
            refreshPoiList(mapName);
        })
        .catch(() => showToast("保存标记点失败", "error"));
}

// ==========================================
// 5. 导航与巡逻触发 (Navigation & Patrol)
// ==========================================

function navigateByPoiName(poiName) {
    showToast(`请求去往语义点: ${poiName}...`);
    fetch(`${API_BASE}/api/v1/nav/go`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ poi_name: poiName })
    })
    .then(res => {
        if (!res.ok) return res.json().then(err => { throw new Error(err.detail || "导航失败") });
        return res.json();
    })
    .then(data => {
        showToast("语义导航已成功触发", "success");
        // 语义点名称导航：从 POI 列表中查找坐标以显示目标点标记
        if (currentMap) {
            fetch(`${API_BASE}/api/v1/maps/${currentMap.name}/pois`)
                .then(r => r.json())
                .then(pois => {
                    const poi = pois.find(p => p.name === poiName);
                    if (poi) showGoalMarker(poi.x, poi.y);
                }).catch(() => {});
        }
    })
    .catch(err => showToast(err.message, "error"));
}

function navigateByInputCoords() {
    const x = parseFloat(document.getElementById("poi-x").value);
    const y = parseFloat(document.getElementById("poi-y").value);
    const yaw = parseFloat(document.getElementById("poi-yaw").value);

    if (isNaN(x) || isNaN(y) || isNaN(yaw)) {
        showToast("请先填入有效的坐标参数 (可在图上点击提取)", "error");
        return;
    }

    showToast(`发送坐标导航: X=${x.toFixed(2)}, Y=${y.toFixed(2)}`);
    fetch(`${API_BASE}/api/v1/nav/go`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, yaw })
    })
    .then(res => {
        if (!res.ok) return res.json().then(err => { throw new Error(err.detail || "导航失败") });
        return res.json();
    })
    .then(data => {
        showToast("物理导航已成功下发", "success");
        showGoalMarker(x, y); // 在地图上显示目标点标记
    })
    .catch(err => showToast(err.message, "error"));
}

function sendPatrolCmd(cmd) {
    fetch(`${API_BASE}/api/v1/patrol/cmd`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cmd })
    })
    .then(res => res.json())
    .then(data => {
        showToast(`下发巡逻指令: ${cmd.toUpperCase()}`, "success");
    }).catch(() => showToast("下发巡逻命令失败", "error"));
}

// ==========================================
// 6. 定时计划管理 (Patrol Scheduler)
// ==========================================

function refreshScheduleList() {
    fetch(`${API_BASE}/api/v1/patrol/schedules`)
        .then(res => res.json())
        .then(data => {
            const list = document.getElementById("schedule-list");
            list.innerHTML = "";
            
            if (data.length === 0) {
                list.innerHTML = '<li class="empty-list-text">暂无定时任务</li>';
                return;
            }

            data.forEach(item => {
                const li = document.createElement("li");
                li.className = "schedule-item";
                li.innerHTML = `
                    <div>
                        <span class="time-lbl">⏰ ${item.time}</span>
                        <span class="repeat-lbl">${item.repeat === 'daily' ? '每天' : item.repeat}</span>
                    </div>
                    <button class="btn-del" onclick="deleteSchedule('${item.id}')">删除</button>
                `;
                list.appendChild(li);
            });
        }).catch(() => {});
}

function addSchedule() {
    const timeVal = document.getElementById("input-schedule-time").value;
    if (!timeVal) {
        showToast("请先选择时间", "error");
        return;
    }
    
    fetch(`${API_BASE}/api/v1/patrol/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ time: timeVal, repeat: "daily" })
    })
    .then(res => {
        if (!res.ok) throw new Error();
        return res.json();
    })
    .then(() => {
        showToast(`成功添加每天 ${timeVal} 巡逻计划`, "success");
        refreshScheduleList();
    })
    .catch(() => showToast("添加定时任务失败，请检查格式", "error"));
}

function deleteSchedule(id) {
    fetch(`${API_BASE}/api/v1/patrol/schedule/${id}`, { method: "DELETE" })
        .then(res => res.json())
        .then(() => {
            showToast("定时巡逻任务已删除", "success");
            refreshScheduleList();
        }).catch(() => showToast("删除失败", "error"));
}

// ==========================================
// 7. 事件绑定与辅助函数 (Events & Helpers)
// ==========================================

function setupEventListeners() {
    // 0. 串口文本框聚焦时自动重新扫描并刷新可用列表
    const inputAgentPort = document.getElementById("input-agent-port");
    const inputLidarPort = document.getElementById("input-lidar-port");
    if (inputAgentPort) {
        inputAgentPort.addEventListener("focus", refreshAvailableSerialPorts);
    }
    if (inputLidarPort) {
        inputLidarPort.addEventListener("focus", refreshAvailableSerialPorts);
    }

    // A. 刷新与加载地图
    document.getElementById("btn-refresh-maps").addEventListener("click", refreshMapList);
    document.getElementById("btn-load-map").addEventListener("click", loadSelectedMap);
    
    // B. 地图点击取点
    document.getElementById("map-image").addEventListener("click", handleMapClick);

    // C. SLAM 建图控制
    const btnInitHardware = document.getElementById("btn-init-hardware");
    if (btnInitHardware) {
        btnInitHardware.addEventListener("click", () => {
            const agentPort = document.getElementById("input-agent-port")?.value?.trim() || "";
            const lidarPort = document.getElementById("input-lidar-port")?.value?.trim() || "";
            showToast("正在一键初始化实机硬件，启动底盘与雷达...", "info");
            showLoading("正在一键初始化实机硬件，启动底盘与雷达...");
            fetch(`${API_BASE}/api/v1/robot/hardware/init`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ agent_port: agentPort, lidar_port: lidarPort })
            })
                .then(res => res.json())
                .then(data => {
                    hideLoading();
                    if (data.status === "success") {
                        showToast("实机硬件初始化成功，已拉起底层节点！", "success");
                    } else {
                        showToast("初始化失败：" + data.details.join(", "), "error");
                    }
                })
                .catch(() => {
                    hideLoading();
                    showToast("下发硬件初始化命令失败", "error");
                });
        });
    }

    const btnStopHardware = document.getElementById("btn-stop-hardware");
    if (btnStopHardware) {
        btnStopHardware.addEventListener("click", () => {
            showToast("正在停用实机底层硬件驱动...", "info");
            showLoading("正在停用实机底层硬件驱动...");
            fetch(`${API_BASE}/api/v1/robot/hardware/stop`, { method: "POST" })
                .then(res => res.json())
                .then(data => {
                    hideLoading();
                    if (data.status === "success") {
                        showToast("实机底层硬件驱动已全部停用", "success");
                    } else {
                        showToast("停用失败：" + data.details.join(", "), "error");
                    }
                })
                .catch(() => {
                    hideLoading();
                    showToast("下发停用命令失败", "error");
                });
        });
    }

    document.getElementById("btn-start-slam").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/slam/start`, { method: "POST" })
            .then(res => res.json())
            .then(data => showToast("已下发开启 SLAM 指令", "success"))
            .catch(() => showToast("下发 SLAM 命令失败", "error"));
    });
    
    document.getElementById("btn-stop-slam").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/slam/stop`, { method: "POST" })
            .then(res => res.json())
            .then(data => showToast("已下发停止 SLAM 指令", "success"))
            .catch(() => showToast("下发停止 SLAM 命令失败", "error"));
    });

    document.getElementById("btn-save-map").addEventListener("click", () => {
        const mapName = document.getElementById("input-map-name").value.trim();
        if (!mapName) {
            showToast("请输入保存的地图名称", "error");
            return;
        }
        showToast("正在保存地图，请稍候...");
        fetch(`${API_BASE}/api/v1/slam/save`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ map_name: mapName })
        })
        .then(res => {
            if (!res.ok) throw new Error();
            return res.json();
        })
        .then(data => {
            showToast(`地图 '${mapName}' 保存成功！`, "success");
            document.getElementById("input-map-name").value = "";
            refreshMapList();
            refreshMapGallery();
        })
        .catch(() => showToast("保存地图失败，确认 SLAM 是否开启", "error"));
    });

    // D. 自主探索控制
    document.getElementById("btn-start-explore").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/explore/start`, { method: "POST" })
            .then(res => res.json())
            .then(data => showToast("自主探索建图已开启", "success"))
            .catch(() => showToast("启动自主探索失败", "error"));
    });

    document.getElementById("btn-stop-explore").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/explore/stop`, { method: "POST" })
            .then(res => res.json())
            .then(data => showToast("自主探索建图已关闭", "success"))
            .catch(() => showToast("关闭自主探索失败", "error"));
    });

    // E. 标定保存与坐标前往
    document.getElementById("btn-save-poi").addEventListener("click", saveCurrentPoi);
    document.getElementById("btn-navigate-coords").addEventListener("click", navigateByInputCoords);
    document.getElementById("btn-nav-cancel").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/nav/cancel`, { method: "POST" })
            .then(res => res.json())
            .then(() => {
                showToast("🚨 当前导航已被紧急中止！", "error");
                hideGoalMarker(); // 取消导航后清除目标标记
            });
    });

    // F. 巡逻控制按键
    document.getElementById("btn-patrol-start").addEventListener("click", () => sendPatrolCmd("start"));
    document.getElementById("btn-patrol-pause").addEventListener("click", () => sendPatrolCmd("pause"));
    document.getElementById("btn-patrol-resume").addEventListener("click", () => sendPatrolCmd("resume"));
    document.getElementById("btn-patrol-stop").addEventListener("click", () => sendPatrolCmd("stop"));

    // G. 定时计划添加
    document.getElementById("btn-add-schedule").addEventListener("click", addSchedule);

    // H. 重定位触发
    document.getElementById("btn-auto-localize").addEventListener("click", triggerAutoLocalize);

    // H.2 手动指定估算位姿交互
    const btnEstimateMode = document.getElementById("btn-estimate-mode");
    const panelEstimate = document.getElementById("pose-estimate-panel");
    const btnPubEstimate = document.getElementById("btn-pub-estimate");
    const btnCancelEstimate = document.getElementById("btn-cancel-estimate");

    if (btnEstimateMode && panelEstimate) {
        btnEstimateMode.addEventListener("click", () => {
            if (!currentMap) {
                showToast("请先选择并加载地图", "error");
                return;
            }
            // 展开面板
            panelEstimate.classList.remove("hidden");
            isEstimatingPose = true;
            
            // 初始化值（默认使用小车当前位姿，方便微调）
            const defaultX = currentPose ? currentPose.x : 0.0;
            const defaultY = currentPose ? currentPose.y : 0.0;
            const defaultYaw = currentPose ? currentPose.yaw : 0.0;
            
            document.getElementById("est-x").value = defaultX.toFixed(3);
            document.getElementById("est-y").value = defaultY.toFixed(3);
            document.getElementById("est-yaw").value = defaultYaw.toFixed(3);
            
            estimatePoseVal = { x: defaultX, y: defaultY, yaw: defaultYaw };
            showEstimateMarker(defaultX, defaultY);
            
            showToast("🎯 位姿校准模式已开启，请直接在地图上点击小车当前所在位置", "info");
        });
    }

    if (btnCancelEstimate && panelEstimate) {
        btnCancelEstimate.addEventListener("click", () => {
            panelEstimate.classList.add("hidden");
            isEstimatingPose = false;
            hideEstimateMarker();
            showToast("已退出位姿校准模式", "info");
        });
    }

    if (btnPubEstimate && panelEstimate) {
        btnPubEstimate.addEventListener("click", () => {
            const x = parseFloat(document.getElementById("est-x").value);
            const y = parseFloat(document.getElementById("est-y").value);
            const yaw = parseFloat(document.getElementById("est-yaw").value);
            
            if (isNaN(x) || isNaN(y) || isNaN(yaw)) {
                showToast("位姿数据不能为空", "error");
                return;
            }
            
            showToast("正在下发估算初始位姿...", "info");
            fetch(`${API_BASE}/api/v1/nav/initialpose`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ x, y, yaw })
            })
            .then(res => {
                if (!res.ok) throw new Error("下发初始位姿失败");
                return res.json();
            })
            .then(data => {
                showToast("🎯 初始位姿覆盖下发成功！AMCL 已重置定位！", "success");
                panelEstimate.classList.add("hidden");
                isEstimatingPose = false;
                hideEstimateMarker();
            })
            .catch(err => {
                showToast(err.message, "error");
            });
        });
    }

    // I. 地图缩放拖动交互
    setupMapInteraction();

    // J. 仿真交互控制
    const btnStartSim = document.getElementById("btn-start-sim");
    const btnStopSim = document.getElementById("btn-stop-sim");
    if (btnStartSim) {
        btnStartSim.addEventListener("click", () => {
            showToast("正在启动 Gazebo 仿真...", "info");
            showLoading("正在启动 Gazebo 仿真与伴随节点，请稍候...");
            fetch(`${API_BASE}/api/v1/sim/start`, { method: "POST" })
                .then(res => res.json())
                .then(data => {
                    hideLoading();
                    showToast("Gazebo 仿真启动成功", "success");
                })
                .catch(() => {
                    hideLoading();
                    showToast("启动 Gazebo 失败", "error");
                });
        });
    }
    if (btnStopSim) {
        btnStopSim.addEventListener("click", () => {
            showToast("正在关闭 Gazebo 仿真...", "info");
            showLoading("正在关闭 Gazebo 仿真环境...");
            fetch(`${API_BASE}/api/v1/sim/stop`, { method: "POST" })
                .then(res => res.json())
                .then(data => {
                    hideLoading();
                    showToast("Gazebo 仿真已成功关闭", "success");
                })
                .catch(() => {
                    hideLoading();
                    showToast("关闭 Gazebo 失败", "error");
                });
        });
    }



    // L. 多点航线规划按键
    document.getElementById("btn-clear-waypoints").addEventListener("click", () => {
        waypointList = [];
        renderWaypointList();
        showToast("已清除规划路径中的所有点", "info");
    });
    document.getElementById("btn-start-waypoint-patrol").addEventListener("click", startWaypointPatrol);

    // M. 历史地图库刷新按键
    const btnRefreshGallery = document.getElementById("btn-refresh-gallery");
    if (btnRefreshGallery) {
        btnRefreshGallery.addEventListener("click", refreshMapGallery);
    }

    // N. 小车轨迹控制按键
    const btnToggleTraj = document.getElementById("btn-toggle-trajectory");
    if (btnToggleTraj) {
        btnToggleTraj.addEventListener("click", () => {
            showTrajectory = !showTrajectory;
            if (showTrajectory) {
                btnToggleTraj.classList.add("active-tool");
                showToast("已开启小车轨迹显示", "success");
            } else {
                btnToggleTraj.classList.remove("active-tool");
                showToast("已隐藏小车轨迹显示", "info");
            }
            drawTrajectory();
        });
    }

    const btnClearTraj = document.getElementById("btn-clear-trajectory");
    if (btnClearTraj) {
        btnClearTraj.addEventListener("click", () => {
            robotTrajectory = [];
            drawTrajectory();
            showToast("已清空小车历史轨迹", "info");
        });
    }
    
    // O. 主题切换事件
    const themeBtn = document.getElementById("btn-theme-toggle");
    if (themeBtn) {
        themeBtn.addEventListener("click", toggleTheme);
    }

    // P. 初始化地图编辑器
    initMapEditor();
}

// 弹窗提示函数 (Toast Overlay)
function showToast(message, type = "info") {
    const toast = document.getElementById("toast");
    if (!toast) return;
    toast.innerText = message;
    
    // 设置类型样式
    toast.className = "toast";
    if (type === "success") toast.classList.add("success");
    if (type === "error") toast.classList.add("error");
    
    // 渐显
    toast.classList.remove("hidden");
    toast.style.opacity = "1";
    toast.style.transform = "translateX(-50%) translateY(0)";

    // 2.5秒后渐隐
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(-50%) translateY(20px)";
        setTimeout(() => {
            toast.classList.add("hidden");
        }, 300);
    }, 2500);
}

// ==========================================
// 8. 小车在地图中的显示与定位状态更新 (Robot Marker & Localize Status)
// ==========================================

function updateRobotMarkerOnMap(pose) {
    const marker = document.getElementById("robot-marker");
    const img = document.getElementById("map-image");
    
    if (!currentMap || !pose || img.classList.contains("hidden")) {
        marker.classList.add("hidden");
        return;
    }

    const naturalWidth = img.naturalWidth;
    const naturalHeight = img.naturalHeight;
    
    if (!naturalWidth || !naturalHeight) {
        marker.classList.add("hidden");
        return;
    }

    // 更新 SVG ViewBox
    const svg = document.getElementById("map-svg-overlay");
    if (svg) {
        svg.setAttribute("viewBox", `0 0 ${naturalWidth} ${naturalHeight}`);
    }

    const resolution = currentMap.resolution; // 米/像素
    const originX = currentMap.origin[0];     // 图像左下角的 ROS X 物理坐标
    const originY = currentMap.origin[1];     // 图像左下角的 ROS Y 物理坐标

    // 转换公式：ROS X 对应像素 X，ROS Y 对应像素 Y（反向）
    const pixelX = (pose.x - originX) / resolution;
    const pixelY = naturalHeight - ((pose.y - originY) / resolution);

    // 转换为百分比，以便在自适应容器中精确定位
    const pctX = (pixelX / naturalWidth) * 100;
    const pctY = (pixelY / naturalHeight) * 100;

    // 检查小车是否在当前地图尺寸范围内
    if (pctX >= 0 && pctX <= 100 && pctY >= 0 && pctY <= 100) {
        marker.classList.remove("hidden");
        marker.style.left = `${pctX}%`;
        marker.style.top = `${pctY}%`;
        
        // 朝向角转换：ROS 的 Yaw 角弧度，在 CSS 中用度表示
        // ROS 的 Yaw 逆时针为正，而 CSS rotate 顺时针为正，所以需要取反
        // 小车 HMI 图标默认尖角朝上（12点钟），而 ROS 物理 Yaw=0 朝右（3点钟），需要加 90 度修正
        const deg = -pose.yaw * 180 / Math.PI + 90;
        // 计算逆缩放比例，保持小车标识视觉大小恒定（防止地图放大时小车也跟着变大）
        const invScale = 1.0 / zoomScale;
        marker.style.transform = `translate(-50%, -50%) scale(${invScale}) rotate(${deg}deg)`;
    } else {
        marker.classList.add("hidden");
    }

    // 记录历史轨迹点，若静止则不重复记录
    if (robotTrajectory.length === 0) {
        robotTrajectory.push({ x: pose.x, y: pose.y });
        drawTrajectory();
    } else {
        const lastPt = robotTrajectory[robotTrajectory.length - 1];
        const dist = Math.hypot(pose.x - lastPt.x, pose.y - lastPt.y);
        if (dist > 0.03) { // 移动超过 3 厘米记录一次
            robotTrajectory.push({ x: pose.x, y: pose.y });
            if (robotTrajectory.length > MAX_TRAJECTORY_POINTS) {
                robotTrajectory.shift();
            }
            drawTrajectory();
        }
    }
}

// ==========================================
// 8.1 导航目标点标记显示/隐藏 (Goal Marker)
// ==========================================

function showGoalMarker(rosX, rosY) {
    if (!currentMap) return;
    const img = document.getElementById("map-image");
    const marker = document.getElementById("goal-marker");
    const label = document.getElementById("goal-label");
    if (!img || !marker) return;

    const naturalWidth = img.naturalWidth;
    const naturalHeight = img.naturalHeight;
    if (!naturalWidth || !naturalHeight) return;

    const resolution = currentMap.resolution;
    const originX = currentMap.origin[0];
    const originY = currentMap.origin[1];

    // ROS 坐标 → 像素百分比（与 updateRobotMarkerOnMap 相同算法）
    const pixelX = (rosX - originX) / resolution;
    const pixelY = naturalHeight - ((rosY - originY) / resolution);
    const pctX = (pixelX / naturalWidth) * 100;
    const pctY = (pixelY / naturalHeight) * 100;

    if (pctX >= 0 && pctX <= 100 && pctY >= 0 && pctY <= 100) {
        currentGoal = { x: rosX, y: rosY };
        marker.style.left = `${pctX}%`;
        marker.style.top = `${pctY}%`;
        label.textContent = `(${rosX.toFixed(2)}, ${rosY.toFixed(2)})`;
        
        // 计算逆缩放比例，保持目标点标识视觉大小恒定（防止地图放大时目标点也跟着变大）
        const invScale = 1.0 / zoomScale;
        marker.style.transform = `translate(-50%, -50%) scale(${invScale})`;
        
        marker.classList.remove("hidden");
    }
}

function hideGoalMarker() {
    const marker = document.getElementById("goal-marker");
    if (marker) marker.classList.add("hidden");
    currentGoal = null;
}

function showEstimateMarker(rosX, rosY) {
    if (!currentMap) return;
    const img = document.getElementById("map-image");
    const marker = document.getElementById("estimate-marker");
    if (!img || !marker) return;

    const naturalWidth = img.naturalWidth;
    const naturalHeight = img.naturalHeight;
    if (!naturalWidth || !naturalHeight) return;

    const resolution = currentMap.resolution;
    const originX = currentMap.origin[0];
    const originY = currentMap.origin[1];

    const pixelX = (rosX - originX) / resolution;
    const pixelY = naturalHeight - ((rosY - originY) / resolution);
    const pctX = (pixelX / naturalWidth) * 100;
    const pctY = (pixelY / naturalHeight) * 100;

    if (pctX >= 0 && pctX <= 100 && pctY >= 0 && pctY <= 100) {
        marker.style.left = `${pctX}%`;
        marker.style.top = `${pctY}%`;
        
        // 计算逆缩放比例，保持目标点标识视觉大小恒定
        const invScale = 1.0 / zoomScale;
        marker.style.transform = `translate(-50%, -50%) scale(${invScale})`;
        
        marker.classList.remove("hidden");
    }
}

function hideEstimateMarker() {
    const marker = document.getElementById("estimate-marker");
    if (marker) marker.classList.add("hidden");
}


function drawTrajectory() {
    const polyline = document.getElementById("trajectory-path");
    const img = document.getElementById("map-image");
    if (!polyline || !img || !currentMap || img.classList.contains("hidden")) return;
    
    if (!showTrajectory || robotTrajectory.length === 0) {
        polyline.setAttribute("points", "");
        return;
    }
    
    const naturalHeight = img.naturalHeight;
    const resolution = currentMap.resolution;
    const originX = currentMap.origin[0];
    const originY = currentMap.origin[1];
    
    let pointsStr = "";
    robotTrajectory.forEach(pt => {
        const px = (pt.x - originX) / resolution;
        const py = naturalHeight - ((pt.y - originY) / resolution);
        pointsStr += `${px.toFixed(1)},${py.toFixed(1)} `;
    });
    polyline.setAttribute("points", pointsStr.trim());
}

let cachedPreviewPath = [];
let lastWaypointHash = "";
let previewTimer = null;

function drawPolylineFromPoints(polyline, pointsList) {
    if (!currentMap) return;
    const img = document.getElementById("map-image");
    const naturalHeight = img.naturalHeight;
    const resolution = currentMap.resolution;
    const originX = currentMap.origin[0];
    const originY = currentMap.origin[1];
    
    let pointsStr = "";
    pointsList.forEach(pt => {
        const px = (pt.x - originX) / resolution;
        const py = naturalHeight - ((pt.y - originY) / resolution);
        pointsStr += `${px.toFixed(1)},${py.toFixed(1)} `;
    });
    polyline.setAttribute("points", pointsStr.trim());
}

function triggerPathPreviewDebounced(polyline) {
    if (previewTimer) clearTimeout(previewTimer);
    
    // 立即降级：先用直线段快速连接，提供即时视觉反馈
    let straightPoints = [];
    if (currentPose) {
        straightPoints.push({ x: currentPose.x, y: currentPose.y });
    }
    waypointList.forEach(wp => straightPoints.push({ x: wp.x, y: wp.y }));
    drawPolylineFromPoints(polyline, straightPoints);
    
    // 防抖发送预览请求，避免频繁拖拽/点击时密集调用 Action 耗尽系统资源
    previewTimer = setTimeout(() => {
        fetch(`${API_BASE}/api/v1/nav/preview`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ waypoints: waypointList })
        })
        .then(res => {
            if (!res.ok) throw new Error("Preview API error");
            return res.json();
        })
        .then(data => {
            if (data.status === "success" && data.path && data.path.length > 0) {
                cachedPreviewPath = data.path;
                drawPolylineFromPoints(polyline, cachedPreviewPath);
            }
        })
        .catch(err => {
            console.warn("Nav2 path preview failed, fallback to straight line:", err);
        });
    }, 400);
}

function drawPlannedPath() {
    const polyline = document.getElementById("planned-path");
    const group = document.getElementById("waypoint-markers-group");
    const img = document.getElementById("map-image");
    if (!polyline || !group || !img || !currentMap || img.classList.contains("hidden")) return;
    
    const naturalWidth = img.naturalWidth;
    const naturalHeight = img.naturalHeight;
    const resolution = currentMap.resolution;
    const originX = currentMap.origin[0];
    const originY = currentMap.origin[1];
    
    group.innerHTML = "";
    
    if (waypointList.length === 0) {
        polyline.setAttribute("points", "");
        cachedPreviewPath = [];
        lastWaypointHash = "";
        return;
    }
    
    // 1. 绘制带有编号的航点 Marker (带有逆向缩放以防视觉变形)
    waypointList.forEach((wp, index) => {
        const px = (wp.x - originX) / resolution;
        const py = naturalHeight - ((wp.y - originY) / resolution);
        
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", px);
        circle.setAttribute("cy", py);
        const r = 8 / zoomScale;
        circle.setAttribute("r", r);
        circle.setAttribute("class", "svg-wp-marker");
        
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", px);
        text.setAttribute("y", py);
        text.setAttribute("class", "svg-wp-text");
        text.setAttribute("font-size", `${10 / zoomScale}px`);
        text.textContent = index + 1;
        
        group.appendChild(circle);
        group.appendChild(text);
    });
    
    // 2. 生成当前状态指纹哈希
    const currentHash = JSON.stringify(waypointList) + `_${currentPose?.x.toFixed(2)}_${currentPose?.y.toFixed(2)}`;
    
    // 3. 如果指纹未改变且有精细缓存，直接以缓存重绘
    if (currentHash === lastWaypointHash && cachedPreviewPath.length > 0) {
        drawPolylineFromPoints(polyline, cachedPreviewPath);
        return;
    }
    
    // 4. 指纹发生改变，触发异步防抖预览规划
    lastWaypointHash = currentHash;
    triggerPathPreviewDebounced(polyline);
}

function drawNav2Path(path) {
    const polyline = document.getElementById("nav2-path");
    const img = document.getElementById("map-image");
    if (!polyline || !img || !currentMap || img.classList.contains("hidden")) return;
    
    if (!path || path.length === 0) {
        polyline.setAttribute("points", "");
        return;
    }
    
    const naturalHeight = img.naturalHeight;
    const resolution = currentMap.resolution;
    const originX = currentMap.origin[0];
    const originY = currentMap.origin[1];
    
    let pointsStr = "";
    path.forEach(pt => {
        const px = (pt.x - originX) / resolution;
        const py = naturalHeight - ((pt.y - originY) / resolution);
        pointsStr += `${px.toFixed(1)},${py.toFixed(1)} `;
    });
    polyline.setAttribute("points", pointsStr.trim());
}

function updateLocalizeStatusDisplay(isLocalizing) {
    const pulse = document.getElementById("localize-pulse");
    const text = document.getElementById("lbl-auto-localize-status");
    
    if (!text || !pulse) return;

    if (isLocalizing) {
        pulse.className = "pulse-dot active warning";
        text.innerText = "重定位中...";
        text.style.color = "var(--accent-orange)";
        document.getElementById("dot-mcu").className = "pill-dot active warning";
    } else if (currentMap) {
        pulse.className = "pulse-dot active success";
        text.innerText = "定位就绪";
        text.style.color = "var(--accent-green)";
        document.getElementById("dot-mcu").className = "pill-dot active success";
    } else {
        pulse.className = "pulse-dot active danger";
        text.innerText = "定位未初始化";
        text.style.color = "var(--accent-red)";
        document.getElementById("dot-mcu").className = "pill-dot active danger";
    }
}

function triggerAutoLocalize() {
    showToast("开始尝试全局重定位...", "info");
    fetch(`${API_BASE}/api/v1/nav/auto-localize`, { method: "POST" })
        .then(res => {
            if (!res.ok) return res.json().then(err => { throw new Error(err.detail || "重定位服务失败") });
            return res.json();
        })
        .then(data => showToast("全局重定位指令下发成功", "success"))
        .catch(err => showToast(err.message, "error"));
}

// ==========================================
// 9. 地图缩放与拖拽平移交互 (Map Zoom & Pan)
// ==========================================

function setupMapInteraction() {
    const wrapper = document.querySelector(".map-image-wrapper");
    const innerContainer = document.getElementById("map-inner-container");
    
    if (!wrapper || !innerContainer) return;
    
    // 鼠标滚轮缩放
    wrapper.addEventListener("wheel", (e) => {
        if (!currentMap) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -0.15 : 0.15;
        zoomScale = Math.min(Math.max(zoomScale + delta, 0.4), 5.0);
        updateMapTransform();
    }, { passive: false });
    
    // 鼠标拖拽平移
    innerContainer.addEventListener("mousedown", (e) => {
        if (!currentMap) return;
        if (e.button !== 0) return; // 仅限左键
        isDragging = true;
        hasDragged = false;
        innerContainer.classList.add("dragging");
        
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        startX = e.clientX - panX;
        startY = e.clientY - panY;
        e.preventDefault();
    });
    
    window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        panX = e.clientX - startX;
        panY = e.clientY - startY;
        
        if (Math.hypot(e.clientX - dragStartX, e.clientY - dragStartY) > 5) {
            hasDragged = true;
        }
        updateMapTransform();
    });
    
    window.addEventListener("mouseup", () => {
        if (!isDragging) return;
        isDragging = false;
        innerContainer.classList.remove("dragging");
    });

    // 移动端触摸平移与防误触
    innerContainer.addEventListener("touchstart", (e) => {
        if (!currentMap) return;
        if (e.touches.length !== 1) return;
        isDragging = true;
        hasDragged = false;
        innerContainer.classList.add("dragging");
        
        const touch = e.touches[0];
        dragStartX = touch.clientX;
        dragStartY = touch.clientY;
        startX = touch.clientX - panX;
        startY = touch.clientY - panY;
    }, { passive: true });
    
    window.addEventListener("touchmove", (e) => {
        if (!isDragging) return;
        if (e.touches.length !== 1) return;
        
        const touch = e.touches[0];
        panX = touch.clientX - startX;
        panY = touch.clientY - startY;
        
        if (Math.hypot(touch.clientX - dragStartX, touch.clientY - dragStartY) > 5) {
            hasDragged = true;
        }
        updateMapTransform();
    }, { passive: true });
    
    window.addEventListener("touchend", () => {
        if (!isDragging) return;
        isDragging = false;
        innerContainer.classList.remove("dragging");
    });
    
    // 地图工具栏缩放按钮
    document.getElementById("btn-zoom-in").addEventListener("click", () => {
        if (!currentMap) return;
        zoomScale = Math.min(zoomScale + 0.25, 5.0);
        updateMapTransform();
    });
    
    document.getElementById("btn-zoom-out").addEventListener("click", () => {
        if (!currentMap) return;
        zoomScale = Math.max(zoomScale - 0.25, 0.4);
        updateMapTransform();
    });
    
    document.getElementById("btn-zoom-reset").addEventListener("click", () => {
        if (!currentMap) return;
        zoomScale = 1.0;
        panX = 0;
        panY = 0;
        updateMapTransform();
    });
}

function updateMapTransform() {
    const container = document.getElementById("map-inner-container");
    if (container) {
        container.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomScale})`;
    }
    if (currentPose) {
        updateRobotMarkerOnMap(currentPose);
    }
    if (currentGoal) {
        showGoalMarker(currentGoal.x, currentGoal.y);
    }
    if (isEstimatingPose) {
        showEstimateMarker(estimatePoseVal.x, estimatePoseVal.y);
    }
    drawPlannedPath();
}

// ==========================================
// 10. 系统信息检测与下位机状态显示 (System info & MCU status)
// ==========================================

function checkSystemInfo() {
    fetch(`${API_BASE}/api/v1/system/info`)
        .then(res => res.json())
        .then(data => {
            const simGroup = document.getElementById("simulation-group");
            const simDivider = document.getElementById("simulation-divider");
            if (data.is_arm) {
                if (simGroup) simGroup.classList.add("hidden");
                if (simDivider) simDivider.classList.add("hidden");
                console.log("Running on ARM board (RDK X5). Hiding simulation buttons.");
            } else {
                if (simGroup) simGroup.classList.remove("hidden");
                if (simDivider) simDivider.classList.remove("hidden");
                console.log("Running on non-ARM host. Showing simulation controls.");
            }
            const hwSpan = document.getElementById("system-hardware-val");
            if (hwSpan && data.hardware_platform) {
                hwSpan.innerText = data.hardware_platform;
            }
        })
        .catch(err => console.error("Failed to query system info", err));
}

function updateMcuStatus(mcuOnline) {
    const badge = document.getElementById("mcu-status");
    if (!badge) return;
    if (mcuOnline) {
        badge.innerText = "在线";
        badge.className = "status-badge online";
        document.getElementById("dot-mcu").className = "pill-dot active success";
    } else {
        badge.innerText = "离线";
        badge.className = "status-badge offline";
        document.getElementById("dot-mcu").className = "pill-dot active offline";
    }
}

function updateAgentButtonStates(running) {
    const btnStartAgent = document.getElementById("btn-start-agent");
    const btnStopAgent = document.getElementById("btn-stop-agent");
    if (btnStartAgent && btnStopAgent) {
        if (running) {
            btnStartAgent.disabled = true;
            btnStopAgent.disabled = false;
        } else {
            btnStartAgent.disabled = false;
            btnStopAgent.disabled = true;
        }
    }
}

// 配色主题控制 (Theme controls)
function initTheme() {
    const savedTheme = localStorage.getItem("theme") || "dark";
    const btn = document.getElementById("btn-theme-toggle");
    if (savedTheme === "light") {
        document.documentElement.setAttribute("data-theme", "light");
        if (btn) btn.innerText = "☀️";
    } else {
        document.documentElement.removeAttribute("data-theme");
        if (btn) btn.innerText = "🌙";
    }
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    const btn = document.getElementById("btn-theme-toggle");
    if (currentTheme === "light") {
        document.documentElement.removeAttribute("data-theme");
        localStorage.setItem("theme", "dark");
        if (btn) btn.innerText = "🌙";
        showToast("已切换至深色科技模式", "success");
    } else {
        document.documentElement.setAttribute("data-theme", "light");
        localStorage.setItem("theme", "light");
        if (btn) btn.innerText = "☀️";
        showToast("已切换至高雅浅色模式", "success");
    }
}

// ==========================================
// 11. 主机蓝牙手柄与 Joy 服务管理交互 (Host Gamepad Bluetooth Control)
// ==========================================
function initHostGamepad() {
    const btnScan = document.getElementById("btn-scan-bluetooth");
    const btnConnect = document.getElementById("btn-connect-bluetooth");
    const btnDisconnect = document.getElementById("btn-disconnect-bluetooth");
    const deviceSelect = document.getElementById("bluetooth-device-select");
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
                            deviceSelect.innerHTML = '<option value="">-- 请选择设备 --</option>';
                            const devices = data.devices || [];
                            if (devices.length === 0) {
                                showToast("附近未发现可连接的蓝牙设备，请长按手柄配对键使其闪烁", "warning");
                                return;
                            }
                            devices.forEach(dev => {
                                const opt = document.createElement("option");
                                opt.value = dev.mac;
                                opt.innerText = `${dev.name} (${dev.mac})`;
                                deviceSelect.appendChild(opt);
                            });
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
            if (!deviceSelect || !deviceSelect.value) {
                showToast("请先在下拉推荐列表中选择要连接的蓝牙设备", "warning");
                return;
            }
            const mac = deviceSelect.value;
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
            const selectMac = deviceSelect ? deviceSelect.value : "";
            
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
            } else {
                if (badge) {
                    badge.innerText = "未连接";
                    badge.className = "status-badge offline";
                }
                if (infoRow) infoRow.classList.add("hidden");
                if (pulse) pulse.className = "pulse-dot";
                
                const lockRow = document.getElementById("gamepad-lock-row");
                if (lockRow) lockRow.classList.add("hidden");
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

// ==========================================
// 地图修改修剪与设定围墙编辑器逻辑 (Map Editor)
// ==========================================
function initMapEditor() {
    const btnEditMap = document.getElementById("btn-edit-current-map");
    const modal = document.getElementById("map-editor-modal");
    const btnClose = document.getElementById("btn-close-map-editor");
    const btnCancel = document.getElementById("btn-editor-cancel");
    const btnSave = document.getElementById("btn-editor-save");
    const btnUndo = document.getElementById("btn-editor-undo");
    const btnClear = document.getElementById("btn-editor-clear");
    const toolEraser = document.getElementById("tool-eraser");
    const toolBrush = document.getElementById("tool-brush");
    const brushSizeInput = document.getElementById("editor-brush-size");
    const brushSizeVal = document.getElementById("brush-size-val");
    const canvas = document.getElementById("map-editor-canvas");

    if (!btnEditMap || !modal || !canvas) {
        console.warn("Map Editor elements not found in DOM");
        return;
    }

    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    let drawing = false;
    let brushMode = "eraser"; // "eraser" 或 "brush"
    let brushSize = 6;
    let editorUndoStack = [];
    const maxUndoSteps = 15;
    let lastX = 0;
    let lastY = 0;

    // 设置 canvas 样式背景色 (未知区域显示色)
    canvas.style.backgroundColor = '#cdcdcd';

    // 辅助函数：保存当前状态到 Undo 栈
    function saveState() {
        const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        if (editorUndoStack.length >= maxUndoSteps) {
            editorUndoStack.shift();
        }
        editorUndoStack.push(imgData);
    }

    // 辅助函数：计算 Canvas 上的相对坐标 (防拉伸)
    function getCanvasCoords(e) {
        const rect = canvas.getBoundingClientRect();
        let clientX, clientY;
        
        // 区分触控事件和鼠标事件
        if (e.touches && e.touches.length > 0) {
            clientX = e.touches[0].clientX;
            clientY = e.touches[0].clientY;
        } else {
            clientX = e.clientX;
            clientY = e.clientY;
        }
        
        const x = (clientX - rect.left) * (canvas.width / rect.width);
        const y = (clientY - rect.top) * (canvas.height / rect.height);
        return { x, y };
    }

    // 绘制线段的逻辑
    function drawSegment(x1, y1, x2, y2) {
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        
        ctx.lineWidth = brushSize;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        
        if (brushMode === "eraser") {
            ctx.strokeStyle = "rgb(255, 255, 255)"; // 橡皮擦画白色
        } else {
            ctx.strokeStyle = "rgb(18, 22, 37)"; // 画笔画黑色
        }
        
        ctx.stroke();
    }

    // A. 开启编辑器入口
    btnEditMap.addEventListener("click", () => {
        if (!currentMap || !currentMap.name) {
            showToast("请先在左侧选择并加载一张地图！", "error");
            return;
        }

        showLoading("正在拉取原图加载编辑器...");
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.src = `${API_BASE}/api/v1/maps/${currentMap.name}/image?t=${Date.now()}`;
        
        img.onload = () => {
            hideLoading();
            modal.classList.remove("hidden");
            
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;

            // 自适应等比例放大 CSS 显示尺寸逻辑 (解决小地图展示过小不便操作的问题)
            const maxDisplayWidth = Math.min(window.innerWidth * 0.9, 950);
            const maxDisplayHeight = 500; // 配合 .map-editor-workspace 高度 (550px - padding)
            let scale = Math.min(maxDisplayWidth / img.naturalWidth, maxDisplayHeight / img.naturalHeight);
            scale = Math.min(scale, 10.0); // 限制最大放大至 10 倍
            
            const displayWidth = Math.round(img.naturalWidth * scale);
            const displayHeight = Math.round(img.naturalHeight * scale);
            
            canvas.style.width = `${displayWidth}px`;
            canvas.style.height = `${displayHeight}px`;
            
            // 清空画布并绘制原图
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0);
            
            // 过滤原图：把未知灰色部分转为完全透明
            try {
                const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                const data = imgData.data;
                for (let i = 0; i < data.length; i += 4) {
                    const r = data[i];
                    const g = data[i+1];
                    const b = data[i+2];
                    // 灰度在 200 到 210 之间均判定为未知区域
                    if (r >= 200 && r <= 210 && g >= 200 && g <= 210 && b >= 200 && b <= 210) {
                        data[i+3] = 0; // 设为完全透明
                    }
                }
                ctx.putImageData(imgData, 0, 0);
            } catch (e) {
                console.error("Failed to process transparency filter on map image", e);
            }
            
            // 初始化 Undo 栈
            editorUndoStack = [];
            saveState();
            
            // 默认设置为橡皮擦模式并重置输入框
            brushMode = "eraser";
            toolEraser.classList.add("active-tool-btn");
            toolBrush.classList.remove("active-tool-btn");
            brushSizeInput.value = 6;
            brushSize = 6;
            brushSizeVal.innerText = "6 px";
        };
        
        img.onerror = () => {
            hideLoading();
            showToast("拉取地图图像失败！", "error");
        };
    });

    // B. 关闭编辑器
    function closeEditor() {
        modal.classList.add("hidden");
        editorUndoStack = [];
    }
    
    btnClose.addEventListener("click", closeEditor);
    btnCancel.addEventListener("click", closeEditor);

    // C. 工具切换
    toolEraser.addEventListener("click", () => {
        brushMode = "eraser";
        toolEraser.classList.add("active-tool-btn");
        toolBrush.classList.remove("active-tool-btn");
    });

    toolBrush.addEventListener("click", () => {
        brushMode = "brush";
        toolBrush.classList.add("active-tool-btn");
        toolEraser.classList.remove("active-tool-btn");
    });

    // D. 粗细调节
    brushSizeInput.addEventListener("input", (e) => {
        brushSize = parseInt(e.target.value);
        brushSizeVal.innerText = `${brushSize} px`;
    });

    // E. 撤销操作
    btnUndo.addEventListener("click", () => {
        if (editorUndoStack.length > 1) {
            editorUndoStack.pop(); // 弹出当前
            const lastData = editorUndoStack[editorUndoStack.length - 1];
            ctx.putImageData(lastData, 0, 0);
            showToast("已撤销上一步操作", "success");
        } else {
            showToast("已撤销到初始状态，无法继续撤销", "info");
        }
    });

    // F. 重置操作 (支持撤销)
    btnClear.addEventListener("click", () => {
        if (editorUndoStack.length > 0) {
            const initialData = editorUndoStack[0];
            ctx.putImageData(initialData, 0, 0);
            saveState();
            showToast("已重置所有修改，你仍可以通过撤销按钮找回", "info");
        }
    });

    // G. 绘图事件绑定 (鼠标)
    canvas.addEventListener("mousedown", (e) => {
        drawing = true;
        const coords = getCanvasCoords(e);
        lastX = coords.x;
        lastY = coords.y;
        drawSegment(lastX, lastY, lastX, lastY);
    });

    canvas.addEventListener("mousemove", (e) => {
        if (!drawing) return;
        const coords = getCanvasCoords(e);
        drawSegment(lastX, lastY, coords.x, coords.y);
        lastX = coords.x;
        lastY = coords.y;
    });

    const stopDrawing = () => {
        if (drawing) {
            drawing = false;
            saveState();
        }
    };

    canvas.addEventListener("mouseup", stopDrawing);
    canvas.addEventListener("mouseleave", stopDrawing);

    // H. 绘图事件绑定 (移动端触控)
    canvas.addEventListener("touchstart", (e) => {
        e.preventDefault();
        drawing = true;
        const coords = getCanvasCoords(e);
        lastX = coords.x;
        lastY = coords.y;
        drawSegment(lastX, lastY, lastX, lastY);
    }, { passive: false });

    canvas.addEventListener("touchmove", (e) => {
        e.preventDefault();
        if (!drawing) return;
        const coords = getCanvasCoords(e);
        drawSegment(lastX, lastY, coords.x, coords.y);
        lastX = coords.x;
        lastY = coords.y;
    }, { passive: false });

    canvas.addEventListener("touchend", stopDrawing);

    // I. 保存并重载地图
    btnSave.addEventListener("click", () => {
        if (!currentMap || !currentMap.name) {
            showToast("地图状态丢失，保存失败", "error");
            return;
        }

        showLoading("正在处理并保存地图，请稍候...");
        const base64Data = canvas.toDataURL("image/png");
        
        fetch(`${API_BASE}/api/v1/maps/${currentMap.name}/edit`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                image_base64: base64Data
            })
        })
        .then(res => {
            if (!res.ok) {
                return res.json().then(err => { throw new Error(err.detail || "保存失败") });
            }
            return res.json();
        })
        .then(data => {
            closeEditor();
            
            // 刷新主地图展示
            const mapImg = document.getElementById("map-image");
            if (mapImg) {
                showLoading("正在重新加载导航界面，请稍候...");
                mapImg.src = `${API_BASE}/api/v1/maps/${currentMap.name}/image?t=${Date.now()}`;
                
                mapImg.onload = () => {
                    hideLoading();
                    showToast("🎉 地图修改并重载导航成功！", "success");
                    
                    // 重置小车历史轨迹并清空显示，避免由于地图变动导致坐标轻微错位
                    robotTrajectory = [];
                    drawTrajectory();
                    drawPlannedPath();
                };
                mapImg.onerror = () => {
                    hideLoading();
                    showToast("更新地图界面失败，但地图已保存成功，请刷新网页", "warning");
                };
            } else {
                hideLoading();
                showToast("🎉 地图修改并重载导航成功！", "success");
            }
        })
        .catch(err => {
            hideLoading();
            showToast(`保存失败：${err.message}`, "error");
        });
    });
}

// ==========================================
// 5. 系统状态与串口自动刷新逻辑 (System Status & Serial Auto Refresh)
// ==========================================
function startSystemStatusPolling() {
    // 立即执行一次状态抓取
    fetchSystemStatus();
    // 启动 2 秒定时轮询并记录定时器 ID
    if (statusInterval) {
        clearInterval(statusInterval);
    }
    statusInterval = setInterval(fetchSystemStatus, 2000);
}

function fetchSystemStatus() {
    fetch(`${API_BASE}/api/v1/system/status`)
        .then(res => {
            if (!res.ok) throw new Error("获取系统状态响应异常");
            return res.json();
        })
        .then(data => {
            // 1. 更新 CPU 占用
            const cpuVal = document.getElementById("status-cpu-val");
            const cpuBar = document.getElementById("status-cpu-bar");
            if (cpuVal) cpuVal.innerText = `${data.cpu.toFixed(1)}%`;
            if (cpuBar) cpuBar.style.width = `${data.cpu}%`;

            // 2. 更新内存占用
            const memVal = document.getElementById("status-mem-val");
            const memBar = document.getElementById("status-mem-bar");
            if (memVal) memVal.innerText = `${data.memory.toFixed(1)}%`;
            if (memBar) memBar.style.width = `${data.memory}%`;

            // 3. 更新内核温度
            const tempVal = document.getElementById("status-temp-val");
            const tempBar = document.getElementById("status-temp-bar");
            if (tempVal) tempVal.innerText = `${data.temperature.toFixed(1)} ℃`;
            if (tempBar) {
                // 将温度折算成 0% 到 100% 的进度条宽度（假设正常工作温度在 0 ~ 100 ℃）
                const tempPercent = Math.max(0, Math.min(100, data.temperature));
                tempBar.style.width = `${tempPercent}%`;

                // 配色方案：温和（<=55℃）青色，预警（55℃~75℃）橙色，高温（>75℃）红色
                if (data.temperature <= 55) {
                    tempBar.style.background = "var(--accent-cyan)";
                    tempBar.style.boxShadow = "0 0 8px var(--accent-cyan-glow)";
                } else if (data.temperature <= 75) {
                    tempBar.style.background = "var(--accent-orange)";
                    tempBar.style.boxShadow = "0 0 8px var(--accent-orange-glow)";
                } else {
                    tempBar.style.background = "var(--accent-red)";
                    tempBar.style.boxShadow = "0 0 8px var(--accent-red-glow)";
                }
            }
        })
        .catch(err => {
            console.error("轮询系统状态失败:", err);
        });
}

function refreshAvailableSerialPorts() {
    fetch(`${API_BASE}/api/v1/system/serial-ports`)
        .then(res => {
            if (!res.ok) throw new Error("获取可用串口列表响应异常");
            return res.json();
        })
        .then(data => {
            const ports = data.ports || [];
            
            // 将串口路径数组组装为 option 标签 HTML 片段
            let optionsHTML = "";
            ports.forEach(port => {
                optionsHTML += `<option value="${port}"></option>`;
            });

            // 写入 micro-ROS 串口与雷达串口的 datalist 下拉推荐容器中
            const agentDatalist = document.getElementById("agent-port-list");
            const lidarDatalist = document.getElementById("lidar-port-list");
            
            if (agentDatalist) agentDatalist.innerHTML = optionsHTML;
            if (lidarDatalist) lidarDatalist.innerHTML = optionsHTML;
            
            console.log(`成功刷新串口下拉列表，找到 ${ports.length} 个可用设备。`);
        })
        .catch(err => {
            console.error("静默刷新串口设备失败:", err);
        });
}

