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
    // 1. 初始化拉取数据
    refreshMapList();
    refreshScheduleList();
    
    // 2. 开启状态查询轮询 (1秒一次实时数据看板)
    startTelemetryPolling();
    // 3. 开启高层节点（SLAM、探索）的状态轮询 (3秒一次)
    startNodeStatusPolling();

    // 4. 绑定事件监听
    setupEventListeners();
});

// ==========================================
// 1. 状态轮询逻辑 (Status Polling)
// ==========================================

function startTelemetryPolling() {
    if (pollInterval) clearInterval(pollInterval);
    
    const poll = () => {
        fetch(`${API_BASE}/api/v1/robot/status`)
            .then(res => {
                if (!res.ok) throw new Error("Offline");
                return res.json();
            })
            .then(data => {
                updateConnectionStatus(true);
                
                // 更新位姿
                document.getElementById("pose-x").innerText = `${data.pose.x.toFixed(3)} m`;
                document.getElementById("pose-y").innerText = `${data.pose.y.toFixed(3)} m`;
                
                // 弧度转角度
                const deg = (data.pose.yaw * 180 / Math.PI).toFixed(1);
                document.getElementById("pose-yaw").innerText = `${deg}°`;
                
                // 导航状态
                const navStatusEl = document.getElementById("nav-status");
                const navStatus = data.nav_status ? data.nav_status.toUpperCase() : "IDLE";
                navStatusEl.innerText = navStatus;
                
                // 改变状态文字颜色
                navStatusEl.className = "tel-val status-text";
                if (navStatus === "NAVIGATING") {
                    navStatusEl.style.color = "#00d8ff"; // 蓝色
                } else if (navStatus === "REACHED") {
                    navStatusEl.style.color = "#10b981"; // 绿色
                } else if (navStatus === "FAILED") {
                    navStatusEl.style.color = "#ef4444"; // 红色
                } else {
                    navStatusEl.style.color = "#f59e0b"; // 橙色
                }

                // 更新电量
                updateBatteryDisplay(data.battery_percentage);
                
                // 更新小车在地图上的位置
                currentPose = data.pose;
                updateRobotMarkerOnMap(currentPose);
                
                // 更新重定位状态
                updateLocalizeStatusDisplay(data.is_localizing);
            })
            .catch(err => {
                updateConnectionStatus(false);
            });
    };

    poll(); // 先执行一次
    pollInterval = setInterval(poll, 1000);
}

function startNodeStatusPolling() {
    if (statusInterval) clearInterval(statusInterval);
    
    const checkStatuses = () => {
        // A. 查询 SLAM 状态
        fetch(`${API_BASE}/api/v1/slam/status`)
            .then(res => res.json())
            .then(data => {
                const btnStart = document.getElementById("btn-start-slam");
                const btnStop = document.getElementById("btn-stop-slam");
                if (data.running) {
                    btnStart.classList.add("hidden");
                    btnStop.classList.remove("hidden");
                } else {
                    btnStart.classList.remove("hidden");
                    btnStop.classList.add("hidden");
                }
            }).catch(() => {});

        // B. 查询自主探索状态
        fetch(`${API_BASE}/api/v1/explore/status`)
            .then(res => res.json())
            .then(data => {
                const btnStart = document.getElementById("btn-start-explore");
                const btnStop = document.getElementById("btn-stop-explore");
                if (data.running) {
                    btnStart.classList.add("hidden");
                    btnStop.classList.remove("hidden");
                } else {
                    btnStart.classList.remove("hidden");
                    btnStop.classList.add("hidden");
                }
            }).catch(() => {});
    };

    checkStatuses();
    statusInterval = setInterval(checkStatuses, 3000);
}

function updateConnectionStatus(isOnline) {
    const badge = document.getElementById("connection-status");
    if (isOnline) {
        badge.innerText = "在线";
        badge.className = "status-badge online";
    } else {
        badge.innerText = "断开";
        badge.className = "status-badge offline";
        // 重置看板参数
        document.getElementById("pose-x").innerText = "-- m";
        document.getElementById("pose-y").innerText = "-- m";
        document.getElementById("pose-yaw").innerText = "--°";
        document.getElementById("nav-status").innerText = "UNKNOWN";
        document.getElementById("nav-status").style.color = "#6b7280";
        updateBatteryDisplay(0);
        document.getElementById("robot-marker").classList.add("hidden");
        updateLocalizeStatusDisplay(false);
        currentPose = null;
    }
}

function updateBatteryDisplay(percentage) {
    const bar = document.getElementById("battery-bar");
    const txt = document.getElementById("battery-text");
    
    bar.style.width = `${percentage}%`;
    txt.innerText = `${percentage.toFixed(0)}%`;
    
    // 根据电量级别改变颜色
    if (percentage > 50) {
        bar.style.backgroundColor = "#10b981"; // 绿色
    } else if (percentage > 20) {
        bar.style.backgroundColor = "#f59e0b"; // 橙色
    } else {
        bar.style.backgroundColor = "#ef4444"; // 红色
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
            
            // 保存当前选中的值，刷新后尽量恢复
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

    // 调用 API 动态切图
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

    // 网页显示的图像尺寸和图片本身的天然尺寸
    const displayWidth = rect.width;
    const displayHeight = rect.height;
    const naturalWidth = img.naturalWidth;
    const naturalHeight = img.naturalHeight;

    // 换算成图片的实际物理像素坐标
    const pixelX = clickX * (naturalWidth / displayWidth);
    const pixelY = clickY * (naturalHeight / displayHeight);

    // 读取 YAML 的元数据
    const resolution = currentMap.resolution; // 米/像素
    const originX = currentMap.origin[0];     // 图像左下角的 ROS X 物理坐标
    const originY = currentMap.origin[1];     // 图像左下角的 ROS Y 物理坐标

    // ⚠️ 转换公式：ROS 的原点在图像的 左下角 (Bottom-Left)
    // 像素的 Y 轴是从上往下增长，而 ROS 物理 Y 轴是从下往上增长
    const worldX = originX + (pixelX * resolution);
    const worldY = originY + ((naturalHeight - pixelY) * resolution);

    // 填入输入框
    document.getElementById("poi-x").value = worldX.toFixed(3);
    document.getElementById("poi-y").value = worldY.toFixed(3);
    document.getElementById("poi-yaw").value = "0.000"; // 默认朝向设为 0
    
    showToast(`提取坐标成功: X=${worldX.toFixed(3)}, Y=${worldY.toFixed(3)}`, "success");
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
            // 检查重名并覆盖
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
            // 重置表单名称
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
    // A. 刷新地图列表
    document.getElementById("btn-refresh-maps").addEventListener("click", refreshMapList);
    
    // B. 加载选中地图
    document.getElementById("btn-load-map").addEventListener("click", loadSelectedMap);
    
    // C. 地图点击取点
    document.getElementById("map-image").addEventListener("click", handleMapClick);

    // D. SLAM 建图控制
    document.getElementById("btn-start-slam").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/slam/start`, { method: "POST" })
            .then(res => res.json())
            .then(data => {
                showToast("已下发开启 SLAM 指令", "success");
                startNodeStatusPolling();
            });
    });
    
    document.getElementById("btn-stop-slam").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/slam/stop`, { method: "POST" })
            .then(res => res.json())
            .then(data => {
                showToast("已下发停止 SLAM 指令", "success");
                startNodeStatusPolling();
            });
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
        })
        .catch(() => showToast("保存地图失败，确认 SLAM 是否开启", "error"));
    });

    // E. 自主探索控制
    document.getElementById("btn-start-explore").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/explore/start`, { method: "POST" })
            .then(res => res.json())
            .then(data => {
                showToast("自主探索建图已开启", "success");
                startNodeStatusPolling();
            });
    });

    document.getElementById("btn-stop-explore").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/explore/stop`, { method: "POST" })
            .then(res => res.json())
            .then(data => {
                showToast("自主探索建图已关闭", "success");
                startNodeStatusPolling();
            });
    });

    // F. 标定保存与导航
    document.getElementById("btn-save-poi").addEventListener("click", saveCurrentPoi);
    document.getElementById("btn-navigate-coords").addEventListener("click", navigateByInputCoords);
    document.getElementById("btn-nav-cancel").addEventListener("click", () => {
        fetch(`${API_BASE}/api/v1/nav/cancel`, { method: "POST" })
            .then(res => res.json())
            .then(() => showToast("🚨 当前导航已被紧急中止！", "error"));
    });

    // G. 巡逻按键
    document.getElementById("btn-patrol-start").addEventListener("click", () => sendPatrolCmd("start"));
    document.getElementById("btn-patrol-pause").addEventListener("click", () => sendPatrolCmd("pause"));
    document.getElementById("btn-patrol-resume").addEventListener("click", () => sendPatrolCmd("resume"));
    document.getElementById("btn-patrol-stop").addEventListener("click", () => sendPatrolCmd("stop"));

    // H. 定时任务添加
    document.getElementById("btn-add-schedule").addEventListener("click", addSchedule);

    // I. 重定位触发
    document.getElementById("btn-auto-localize").addEventListener("click", triggerAutoLocalize);

    // J. 地图缩放平移交互
    setupMapInteraction();
}

// 弹窗提示函数
function showToast(message, type = "info") {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    
    // 设置类型样式
    toast.className = "toast";
    if (type === "success") toast.classList.add("success");
    if (type === "error") toast.classList.add("error");
    
    // 渐显
    toast.classList.remove("hidden");
    toast.style.opacity = "1";
    toast.style.transform = "translateX(-50%) translateY(0)";

    // 3秒后渐隐
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
        const deg = -pose.yaw * 180 / Math.PI;
        // 计算逆缩放比例，保持小车标识视觉大小恒定（防止地图放大时小车也跟着变大）
        const invScale = 1.0 / zoomScale;
        marker.style.transform = `translate(-50%, -50%) scale(${invScale}) rotate(${deg}deg)`;
    } else {
        marker.classList.add("hidden");
    }
}

function updateLocalizeStatusDisplay(isLocalizing) {
    const pulse = document.getElementById("localize-pulse");
    const text = document.getElementById("lbl-auto-localize-status");
    
    if (!text || !pulse) return;

    if (isLocalizing) {
        pulse.className = "pulse-dot active warning";
        text.innerText = "重定位中...";
        text.style.color = "var(--accent-orange)";
    } else if (currentMap) {
        pulse.className = "pulse-dot active success";
        text.innerText = "定位就绪";
        text.style.color = "var(--accent-green)";
    } else {
        pulse.className = "pulse-dot active danger";
        text.innerText = "定位未初始化";
        text.style.color = "var(--accent-red)";
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
        if (e.button !== 0) return; // 仅允许左键拖拽
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
    
    // 缩放按钮绑定
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
    // 地图缩放变化时，若小车在线，同步更新其逆向缩放比例以保持大小恒定
    if (currentPose) {
        updateRobotMarkerOnMap(currentPose);
    }
}
