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

