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
    refreshTaskLogs();
    
    // 6. 初始化子标签页（巡逻的 POI / 航线规划 Tabs）与 WebSocket 实时推送
    initTabs();
    initWebSocket();

    // 7. 绑定所有交互按键的事件监听
    setupEventListeners();
});


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

    // K. 电源交互控制 (系统一键关机)
    const btnShutdown = document.getElementById("btn-shutdown-system");
    if (btnShutdown) {
        btnShutdown.addEventListener("click", () => {
            const confirmed = confirm("⚠️ 警告：确定要关闭上位机系统吗？\n\n关机后网页控制舱将断开连接，且必须通过重新插拔小车电源或操作物理电源按键才能重新开机。");
            if (!confirmed) return;
            
            showToast("正在下发关机指令...", "info");
            showLoading("正在安全关闭系统，网页控制舱即将断开。请在 10 秒后安全拔掉电源...");
            
            fetch(`${API_BASE}/api/v1/system/shutdown`, { method: "POST" })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "success") {
                        showToast("关机指令已成功下发", "success");
                        showLoading("系统正在关机中... 连接即将断开，请在 10 秒后安全拔掉电源。");
                    } else {
                        hideLoading();
                        showToast("关机失败: " + data.message, "error");
                    }
                })
                .catch(err => {
                    // 关机导致网络连接立刻断开是正常现象，直接给予成功关机的视觉引导
                    showLoading("系统正在关机中（网络已断开）... 请在 10 秒后安全拔掉电源。");
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

    // Q. 任务历史日志事件绑定
    document.querySelectorAll(".custom-dropdown").forEach(dropdown => {
        const trigger = dropdown.querySelector(".custom-dropdown-trigger");
        const menu = dropdown.querySelector(".custom-dropdown-menu");
        
        if (trigger && menu) {
            trigger.addEventListener("click", (e) => {
                e.stopPropagation();
                // 关闭其它可能展开的下拉框
                document.querySelectorAll(".custom-dropdown").forEach(other => {
                    if (other !== dropdown) {
                        other.classList.remove("open");
                        const otherMenu = other.querySelector(".custom-dropdown-menu");
                        if (otherMenu) otherMenu.style.display = "none";
                    }
                });
                
                // 切换当前菜单状态
                const isOpen = dropdown.classList.contains("open");
                if (isOpen) {
                    dropdown.classList.remove("open");
                    menu.style.display = "none";
                } else {
                    dropdown.classList.add("open");
                    menu.style.display = "block";
                }
            });
        }

        dropdown.querySelectorAll(".custom-dropdown-item").forEach(item => {
            item.addEventListener("click", (e) => {
                e.stopPropagation();
                
                // 移除同一列表内的其它 active 样式，并为当前点击项设置 active
                dropdown.querySelectorAll(".custom-dropdown-item").forEach(i => i.classList.remove("active"));
                item.classList.add("active");
                
                // 取值并写回 DOM data-value 属性，更新触发器显示文本
                const val = item.getAttribute("data-value") || "";
                dropdown.setAttribute("data-value", val);
                if (trigger) {
                    const labelSpan = trigger.querySelector(".selected-value");
                    if (labelSpan) labelSpan.innerText = item.innerText;
                }
                
                // 收起菜单
                dropdown.classList.remove("open");
                if (menu) menu.style.display = "none";
                
                // 自动联动重新加载列表
                if (typeof window.refreshTaskLogs === "function") {
                    window.refreshTaskLogs();
                }
            });
        });
    });

    // 绑定全局点击事件，当点击页面其它无关联区域时，自动收起全部下拉菜单
    document.addEventListener("click", () => {
        document.querySelectorAll(".custom-dropdown").forEach(dropdown => {
            dropdown.classList.remove("open");
            const menu = dropdown.querySelector(".custom-dropdown-menu");
            if (menu) menu.style.display = "none";
        });
    });

    const btnClearLogs = document.getElementById("btn-clear-logs");
    if (btnClearLogs) {
        btnClearLogs.addEventListener("click", clearAllTaskLogs);
    }
}

// ==========================================
// 8. 动态更新自定义下拉框的选项 (通用辅助函数)
// ==========================================
function updateCustomDropdownOptions(dropdownId, options, defaultValue = "") {
    const dropdown = document.getElementById(dropdownId);
    if (!dropdown) return;
    
    const menu = dropdown.querySelector(".custom-dropdown-menu");
    const trigger = dropdown.querySelector(".custom-dropdown-trigger");
    if (!menu || !trigger) return;
    
    menu.innerHTML = "";
    
    // 如果没有选项，显示为空选项
    if (!options || options.length === 0) {
        const li = document.createElement("li");
        li.className = "custom-dropdown-item active";
        li.setAttribute("data-value", "");
        li.style.cssText = "padding: 8px 12px; font-size: 0.8rem; cursor: pointer; color: var(--text-primary); transition: background 0.2s;";
        li.innerText = "-- 无可用选项 --";
        menu.appendChild(li);
        
        dropdown.setAttribute("data-value", "");
        const labelSpan = trigger.querySelector(".selected-value");
        if (labelSpan) labelSpan.innerText = "-- 无可用选项 --";
        return;
    }
    
    let activeVal = defaultValue;
    
    options.forEach(opt => {
        const li = document.createElement("li");
        li.className = "custom-dropdown-item";
        if (opt.value === activeVal) {
            li.classList.add("active");
        }
        li.setAttribute("data-value", opt.value);
        li.style.cssText = "padding: 8px 12px; font-size: 0.8rem; cursor: pointer; color: var(--text-primary); transition: background 0.2s;";
        li.innerText = opt.text;
        
        li.addEventListener("click", (e) => {
            e.stopPropagation();
            menu.querySelectorAll(".custom-dropdown-item").forEach(i => i.classList.remove("active"));
            li.classList.add("active");
            
            dropdown.setAttribute("data-value", opt.value);
            const labelSpan = trigger.querySelector(".selected-value");
            if (labelSpan) labelSpan.innerText = opt.text;
            
            // 关闭菜单
            dropdown.classList.remove("open");
            menu.style.display = "none";
            
            // 触发自定义的 change 事件或者回调函数
            const changeEvent = new CustomEvent("change", { detail: { value: opt.value } });
            dropdown.dispatchEvent(changeEvent);
        });
        
        menu.appendChild(li);
    });
    
    // 恢复默认选定显示
    const activeItem = menu.querySelector(`.custom-dropdown-item[data-value="${activeVal}"]`) || menu.querySelector(".custom-dropdown-item");
    if (activeItem) {
        menu.querySelectorAll(".custom-dropdown-item").forEach(i => i.classList.remove("active"));
        activeItem.classList.add("active");
        
        const finalVal = activeItem.getAttribute("data-value");
        dropdown.setAttribute("data-value", finalVal);
        const labelSpan = trigger.querySelector(".selected-value");
        if (labelSpan) labelSpan.innerText = activeItem.innerText;
    }
}

window.updateCustomDropdownOptions = updateCustomDropdownOptions;

// 弹窗提示函数 (Toast Overlay)

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
            const verLabel = document.getElementById("system-version-label");
            if (verLabel && data.version) {
                verLabel.innerText = "v" + data.version;
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
            // 辅助函数：更新圆形进度条颜色、发光与数值
            function updateCircularProgress(value, ringId, valId) {
                const ring = document.getElementById(ringId);
                const valText = document.getElementById(valId);
                if (!ring || !valText) return;
                
                valText.innerText = `${value.toFixed(1)}%`;
                
                const offset = 239 - (239 * value / 100);
                ring.style.strokeDashoffset = offset;
                
                let colorVar, glowVar;
                if (value <= 60.0) {
                    colorVar = "var(--accent-cyan)";
                    glowVar = "var(--accent-cyan-glow)";
                } else if (value <= 85.0) {
                    colorVar = "var(--accent-orange)";
                    glowVar = "var(--accent-orange-glow)";
                } else {
                    colorVar = "var(--accent-red)";
                    glowVar = "var(--accent-red-glow)";
                }
                
                ring.style.stroke = colorVar;
                ring.style.filter = `drop-shadow(0 0 5px ${glowVar})`;
                valText.style.color = colorVar;
            }

            // 1. 更新 CPU 占用 (圆形进度)
            updateCircularProgress(data.cpu, "status-cpu-ring", "status-cpu-val");

            // 2. 更新 内存占用 (圆形进度)
            updateCircularProgress(data.memory, "status-mem-ring", "status-mem-val");

            // 3. 更新 内核温度
            const tempVal = document.getElementById("status-temp-val");
            if (tempVal) {
                tempVal.innerText = `${data.temperature.toFixed(1)} ℃`;
                if (data.temperature <= 55) {
                    tempVal.style.color = "var(--accent-cyan)";
                } else if (data.temperature <= 75) {
                    tempVal.style.color = "var(--accent-orange)";
                } else {
                    tempVal.style.color = "var(--accent-red)";
                }
            }

            // 4. 更新 网络上传/下载速度
            function formatNetSpeed(kbps) {
                if (kbps < 1024) {
                    return `${kbps.toFixed(1)} KB/s`;
                } else {
                    const mbps = kbps / 1024;
                    return `${mbps.toFixed(1)} MB/s`;
                }
            }

            const netDownVal = document.getElementById("status-net-down-val");
            const netUpVal = document.getElementById("status-net-up-val");
            if (netDownVal) netDownVal.innerText = formatNetSpeed(data.net_down || 0);
            if (netUpVal) netUpVal.innerText = formatNetSpeed(data.net_up || 0);
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

