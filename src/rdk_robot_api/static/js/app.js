// API 基础路径（自动适配当前主机的 IP 和端口）
const API_BASE = window.location.origin;

// 全局状态变量
let mapList = [];
let currentMap = null;
let pollInterval = null;
let statusInterval = null;
let currentPose = null;

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

    // 3. 初始化蓝牙游戏手柄
    initGamepad();

    // 4. 检测系统环境是否为 ARM 以展示或隐藏仿真控制
    checkSystemInfo();

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
    } else if (navStatus === "FAILED") {
        navStatusEl.style.color = "var(--accent-red)";
    } else {
        navStatusEl.style.color = "var(--accent-orange)";
    }

    // 更新电量
    updateBatteryDisplay(data.battery_percentage);
    
    // 更新重定位状态
    updateLocalizeStatusDisplay(data.is_localizing);

    // 更新下位机在线状态
    updateMcuStatus(data.mcu_online);

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

    // 更新 micro-ROS 代理按钮状态
    updateAgentButtonStates(data.agent_running);

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
            body: JSON.stringify({ cmd: "start" })
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
    
    // 显示加载态
    const placeholder = document.getElementById("map-placeholder");
    const loader = document.getElementById("map-loading");
    const img = document.getElementById("map-image");
    const innerContainer = document.getElementById("map-inner-container");
    
    placeholder.classList.add("hidden");
    innerContainer.classList.add("hidden");
    loader.classList.remove("hidden");

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
            
            // 拉取这个地图的 POI 列表
            refreshPoiList(mapName);
        })
        .catch(err => {
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

    // 检查当前点击模式
    const clickMode = document.querySelector('input[name="map-click-mode"]:checked')?.value || "nav";
    if (clickMode === "waypoint") {
        addWaypointToList(worldX, worldY, 0.0);
    } else {
        // 单点导航模式：填入输入框并高亮提示
        document.getElementById("poi-x").value = worldX.toFixed(3);
        document.getElementById("poi-y").value = worldY.toFixed(3);
        document.getElementById("poi-yaw").value = "0.000"; // 默认朝向设为 0.000
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
    .then(data => showToast("语义导航已成功触发", "success"))
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
    .then(data => showToast("物理导航已成功下发", "success"))
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
    // A. 刷新与加载地图
    document.getElementById("btn-refresh-maps").addEventListener("click", refreshMapList);
    document.getElementById("btn-load-map").addEventListener("click", loadSelectedMap);
    
    // B. 地图点击取点
    document.getElementById("map-image").addEventListener("click", handleMapClick);

    // C. SLAM 建图控制
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
            .then(() => showToast("🚨 当前导航已被紧急中止！", "error"));
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

    // I. 地图缩放拖动交互
    setupMapInteraction();

    // J. 仿真交互控制
    const btnStartSim = document.getElementById("btn-start-sim");
    const btnStopSim = document.getElementById("btn-stop-sim");
    if (btnStartSim) {
        btnStartSim.addEventListener("click", () => {
            showToast("正在启动 Gazebo 仿真...", "info");
            fetch(`${API_BASE}/api/v1/sim/start`, { method: "POST" })
                .then(res => res.json())
                .then(data => showToast("Gazebo 仿真启动成功", "success"))
                .catch(() => showToast("启动 Gazebo 失败", "error"));
        });
    }
    if (btnStopSim) {
        btnStopSim.addEventListener("click", () => {
            showToast("正在关闭 Gazebo 仿真...", "info");
            fetch(`${API_BASE}/api/v1/sim/stop`, { method: "POST" })
                .then(res => res.json())
                .then(data => showToast("Gazebo 仿真已成功关闭", "success"))
                .catch(() => showToast("关闭 Gazebo 失败", "error"));
        });
    }

    // K. micro-ROS 代理交互控制
    const btnStartAgent = document.getElementById("btn-start-agent");
    const btnStopAgent = document.getElementById("btn-stop-agent");
    if (btnStartAgent) {
        btnStartAgent.addEventListener("click", () => {
            showToast("正在启动 micro-ROS 代理...", "info");
            fetch(`${API_BASE}/api/v1/agent/start`, { method: "POST" })
                .then(res => res.json())
                .then(data => {
                    showToast("micro-ROS 代理启动成功", "success");
                    updateAgentButtonStates(true);
                })
                .catch(() => showToast("启动 micro-ROS 代理失败", "error"));
        });
    }
    if (btnStopAgent) {
        btnStopAgent.addEventListener("click", () => {
            showToast("正在关闭 micro-ROS 代理...", "info");
            fetch(`${API_BASE}/api/v1/agent/stop`, { method: "POST" })
                .then(res => res.json())
                .then(data => {
                    showToast("micro-ROS 代理已成功关闭", "success");
                    updateAgentButtonStates(false);
                })
                .catch(() => showToast("关闭 micro-ROS 代理失败", "error"));
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
// 11. 蓝牙游戏手柄遥控交互 (Gamepad Bluetooth HMI)
// ==========================================

let gamepadIndex = null;
let gamepadEnabled = false;
let gamepadLoopActive = false;
let zeroSpeedSentCount = 0;

function initGamepad() {
    window.addEventListener("gamepadconnected", (e) => {
        console.log("Gamepad connected:", e.gamepad.index, e.gamepad.id);
        gamepadIndex = e.gamepad.index;
        updateGamepadUIStatus(e.gamepad);
        startGamepadLoop();
    });

    window.addEventListener("gamepaddisconnected", (e) => {
        if (gamepadIndex === e.gamepad.index) {
            console.log("Gamepad disconnected:", e.gamepad.index);
            gamepadIndex = null;
            updateGamepadUIStatus(null);
            stopGamepadLoop();
        }
    });

    const enableSwitch = document.getElementById("gamepad-enable-switch");
    if (enableSwitch) {
        enableSwitch.addEventListener("change", (e) => {
            gamepadEnabled = e.target.checked;
            const visualizer = document.querySelector(".gamepad-joystick-visualizer");
            
            if (gamepadEnabled) {
                if (gamepadIndex !== null) {
                    if (visualizer) visualizer.classList.add("joystick-active");
                    showToast("🎮 手柄遥控已开启，请操纵手柄摇杆", "success");
                    
                    // 如果使能了手柄，安全起见把网页端遥控自动关闭
                    const webTeleopSwitch = document.getElementById("web-teleop-enable-switch");
                    if (webTeleopSwitch && webTeleopSwitch.checked) {
                        webTeleopSwitch.checked = false;
                        webTeleopSwitch.dispatchEvent(new Event("change"));
                    }
                } else {
                    enableSwitch.checked = false;
                    gamepadEnabled = false;
                    showToast("⚠️ 未检测到已连手柄！请连接手柄并按键激活。", "error");
                }
            } else {
                if (visualizer) visualizer.classList.remove("joystick-active");
                showToast("🎮 手柄遥控已安全关闭", "info");
                sendGamepadTeleopCommand(0.0, 0.0);
            }
        });
    }

    // 自动扫描手柄
    setInterval(() => {
        if (gamepadIndex !== null) return;
        const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
        for (let i = 0; i < gamepads.length; i++) {
            if (gamepads[i]) {
                console.log("Auto-detected gamepad slot", i, gamepads[i].id);
                gamepadIndex = gamepads[i].index;
                updateGamepadUIStatus(gamepads[i]);
                startGamepadLoop();
                break;
            }
        }
    }, 1000);
}

function updateGamepadUIStatus(gamepad) {
    const badge = document.getElementById("gamepad-status-badge");
    const infoRow = document.getElementById("gamepad-info-row");
    const modelSpan = document.getElementById("gamepad-model");
    const pulse = document.getElementById("gamepad-pulse");
    const visualizer = document.querySelector(".gamepad-joystick-visualizer");

    if (gamepad) {
        if (badge) {
            badge.innerText = "已连接";
            badge.className = "status-badge online";
        }
        if (infoRow) infoRow.classList.remove("hidden");
        if (modelSpan) {
            modelSpan.innerText = gamepad.id.split(" (Vendor:")[0];
        }
        if (pulse) {
            pulse.className = "pulse-dot active success";
        }
    } else {
        if (badge) {
            badge.innerText = "未连接";
            badge.className = "status-badge offline";
        }
        if (infoRow) infoRow.classList.add("hidden");
        if (pulse) {
            pulse.className = "pulse-dot";
        }
        if (visualizer) {
            visualizer.classList.remove("joystick-active");
        }
        const enableSwitch = document.getElementById("gamepad-enable-switch");
        if (enableSwitch) {
            enableSwitch.checked = false;
        }
        gamepadEnabled = false;
        updateJoystickPointerVisual(0.0, 0.0);
    }
}

function startGamepadLoop() {
    if (!gamepadLoopActive) {
        gamepadLoopActive = true;
        requestAnimationFrame(gamepadTelemetryLoop);
    }
}

function stopGamepadLoop() {
    gamepadLoopActive = false;
}

let teleopFrameCounter = 0;
function gamepadTelemetryLoop() {
    if (gamepadIndex === null) {
        gamepadLoopActive = false;
        return;
    }

    const gamepad = navigator.getGamepads()[gamepadIndex];
    if (gamepad) {
        // Xbox 映射：
        // 左摇杆上下 (axes[1]) -> 前进后退。向上推为负，向下为正，故取反
        let rawLinear = -gamepad.axes[1];
        
        // 转向优先使用右摇杆左右 (axes[2]/axes[3])，若无则使用左摇杆左右 (axes[0])
        let rawAngular = 0.0;
        if (typeof gamepad.axes[3] !== 'undefined' && Math.abs(gamepad.axes[3]) > 0.05) {
            rawAngular = -gamepad.axes[3];
        } else if (typeof gamepad.axes[2] !== 'undefined' && Math.abs(gamepad.axes[2]) > 0.05) {
            rawAngular = -gamepad.axes[2];
        } else if (typeof gamepad.axes[0] !== 'undefined') {
            rawAngular = -gamepad.axes[0];
        }

        // 摇杆死区 deadzone
        const deadzone = 0.15;
        let linear = Math.abs(rawLinear) < deadzone ? 0.0 : rawLinear;
        let angular = Math.abs(rawAngular) < deadzone ? 0.0 : rawAngular;

        // 物理上限约束映射：线速度最大 0.45 m/s，角速度最大 1.20 rad/s
        const maxLinear = 0.45;
        const maxAngular = 1.20;
        
        let linearX = linear * maxLinear;
        let angularZ = angular * maxAngular;

        // 实时更新手柄十字摇杆偏移
        updateJoystickPointerVisual(linear, -angular);

        if (gamepadEnabled) {
            teleopFrameCounter++;
            // 限流 15Hz (60fps / 4)
            if (teleopFrameCounter % 4 === 0) {
                sendGamepadTeleopCommand(linearX, angularZ);
            }
        }
    }

    if (gamepadLoopActive) {
        requestAnimationFrame(gamepadTelemetryLoop);
    }
}

function updateJoystickPointerVisual(linear, angular) {
    const pointer = document.getElementById("joystick-pointer");
    if (!pointer) return;

    const maxOffset = 30; // 30px
    const offsetX = angular * maxOffset;
    const offsetY = -linear * maxOffset;

    pointer.style.transform = `translate(calc(-50% + ${offsetX.toFixed(1)}px), calc(-50% + ${offsetY.toFixed(1)}px))`;
}

function sendGamepadTeleopCommand(linearX, angularZ) {
    // 零速限流刹车确认：如果连续下发零速，发够 3 次零速度后即行停止，节约通道带宽
    if (linearX === 0.0 && angularZ === 0.0) {
        if (zeroSpeedSentCount >= 3) {
            return;
        }
        zeroSpeedSentCount++;
    } else {
        zeroSpeedSentCount = 0;
    }

    console.log(`[Teleop CMD] 速度发送: x=${linearX.toFixed(3)}, z=${angularZ.toFixed(3)}`);

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            type: "teleop",
            linear_x: parseFloat(linearX.toFixed(3)),
            angular_z: parseFloat(angularZ.toFixed(3))
        }));
    } else {
        console.warn(`[Teleop CMD] WebSocket 未就绪。底盘状态: ${socket ? socket.readyState : 'null'}`);
    }
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
        angularZ = rawAngular * 1.20;
    } else {
        // 2. 否则执行键盘按键遥控值
        let keyLinear = 0.0;
        let keyAngular = 0.0;

        if (pressedKeys.w || pressedKeys.ArrowUp) keyLinear += 1.0;
        if (pressedKeys.s || pressedKeys.ArrowDown) keyLinear -= 1.0;
        if (pressedKeys.a || pressedKeys.ArrowLeft) keyAngular += 1.0;
        if (pressedKeys.d || pressedKeys.ArrowRight) keyAngular -= 1.0;

        linearX = keyLinear * 0.45;
        angularZ = keyAngular * 1.20;
    }

    // 限幅裁剪约束
    linearX = Math.min(Math.max(linearX, -0.45), 0.45);
    angularZ = Math.min(Math.max(angularZ, -1.20), 1.20);

    webTeleopFrameCounter++;
    // 限流 15Hz (每 4 帧下发一次)
    if (webTeleopFrameCounter % 4 === 0) {
        sendGamepadTeleopCommand(linearX, angularZ);
    }

    if (webTeleopLoopActive) {
        requestAnimationFrame(webTeleopLoop);
    }
}
