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
                    const dropdown = document.getElementById("dropdown-map-select");
                    if (dropdown) {
                        const menu = dropdown.querySelector(".custom-dropdown-menu");
                        const trigger = dropdown.querySelector(".custom-dropdown-trigger");
                        if (menu && trigger) {
                            const item = menu.querySelector(`.custom-dropdown-item[data-value="${map.name}"]`);
                            if (item) {
                                menu.querySelectorAll(".custom-dropdown-item").forEach(i => i.classList.remove("active"));
                                item.classList.add("active");
                                dropdown.setAttribute("data-value", map.name);
                                const labelSpan = trigger.querySelector(".selected-value");
                                if (labelSpan) labelSpan.innerText = item.innerText;
                            }
                        }
                    }
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


// ==========================================
// 2. 地图文件与管理逻辑 (Map Management)
// ==========================================

function refreshMapList() {
    fetch(`${API_BASE}/api/v1/maps`)
        .then(res => res.json())
        .then(data => {
            mapList = data;
            const dropdown = document.getElementById("dropdown-map-select");
            const prevVal = dropdown ? dropdown.getAttribute("data-value") : "";
            
            const opts = [{ value: "", text: "-- 请选择地图 --" }];
            data.forEach(map => {
                opts.push({ value: map.name, text: `${map.name} (${map.created_at || '未知时间'})` });
            });

            if (typeof window.updateCustomDropdownOptions === "function") {
                window.updateCustomDropdownOptions("dropdown-map-select", opts, prevVal);
            }
        })
        .catch(() => showToast("获取地图列表失败", "error"));
}

function loadSelectedMap() {
    const dropdown = document.getElementById("dropdown-map-select");
    const mapName = dropdown ? dropdown.getAttribute("data-value") : "";
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

