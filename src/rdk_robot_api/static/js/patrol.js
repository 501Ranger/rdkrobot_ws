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
// 7. 导航历史与任务日志管理 (Task Logs)
// ==========================================

function getLocalDateString(d) {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function refreshTaskLogs() {
    fetch(`${API_BASE}/api/v1/patrol/logs`)
        .then(res => {
            if (!res.ok) throw new Error("获取日志列表失败");
            return res.json();
        })
        .then(allLogs => {
            // A. 数据统计与看板更新 (基于全部日志)
            const totalTasks = allLogs.length;
            const reachedCount = allLogs.filter(l => l.status === 'reached').length;
            const successRate = totalTasks > 0 ? (reachedCount / totalTasks * 100) : 0;

            const totalTasksEl = document.getElementById("stat-total-tasks");
            if (totalTasksEl) totalTasksEl.innerText = `${totalTasks} 次`;

            const successRateEl = document.getElementById("stat-success-rate");
            if (successRateEl) successRateEl.innerText = `${successRate.toFixed(1)}%`;

            const ringEl = document.getElementById("stat-ring-progress");
            if (ringEl) {
                // 圆环周长为 176，根据成功率百分比设置偏移
                const offset = 176 - (176 * successRate / 100);
                ringEl.style.strokeDashoffset = offset;
            }

            // B. 近 7 天频次柱状图渲染 (基于全部日志)
            const days = [];
            for (let i = 6; i >= 0; i--) {
                const d = new Date();
                d.setDate(d.getDate() - i);
                days.push(getLocalDateString(d));
            }

            const dateCounts = {};
            days.forEach(day => dateCounts[day] = 0);
            allLogs.forEach(log => {
                if (log.start_time) {
                    const logDate = log.start_time.split(" ")[0];
                    if (dateCounts[logDate] !== undefined) {
                        dateCounts[logDate]++;
                    }
                }
            });

            const maxCount = Math.max(...Object.values(dateCounts));
            const chartContainer = document.querySelector(".svg-chart-container");
            if (chartContainer) {
                chartContainer.innerHTML = "";
                days.forEach(day => {
                    const count = dateCounts[day] || 0;
                    const heightPct = maxCount > 0 ? (count / maxCount) * 100 : 0;
                    
                    const dateParts = day.split("-");
                    const shortDate = dateParts.length === 3 ? `${dateParts[1]}/${dateParts[2]}` : day;

                    const bar = document.createElement("div");
                    bar.className = "chart-bar";
                    bar.style.cssText = "flex: 1; background: rgba(255,255,255,0.03); height: 100%; border-radius: 2px; position: relative; cursor: pointer; min-width: 12px;";
                    bar.title = `${day}: ${count} 次`;
                    
                    bar.innerHTML = `
                        <div class="chart-bar-fill" style="position: absolute; bottom: 12px; left: 0; right: 0; background: var(--accent-cyan); height: calc(${heightPct}% * 0.7); transition: height 0.6s cubic-bezier(0.1, 1, 0.1, 1); box-shadow: 0 0 8px var(--accent-cyan-glow); border-radius: 2px;"></div>
                        <span style="position: absolute; bottom: 0; left: 50%; transform: translateX(-50%); font-size: 0.55rem; color: var(--text-secondary); white-space: nowrap; pointer-events: none;">${shortDate}</span>
                    `;
                    chartContainer.appendChild(bar);
                });
            }

            // C. 过滤器筛选并渲染表格 (基于过滤日志)
            const typeVal = document.getElementById("dropdown-log-type")?.getAttribute("data-value") || "";
            const statusVal = document.getElementById("dropdown-log-status")?.getAttribute("data-value") || "";

            let filteredLogs = allLogs;
            if (typeVal) filteredLogs = filteredLogs.filter(l => l.type === typeVal);
            if (statusVal) filteredLogs = filteredLogs.filter(l => l.status === statusVal);

            const tableBody = document.getElementById("logs-table-body");
            if (tableBody) {
                tableBody.innerHTML = "";
                if (filteredLogs.length === 0) {
                    tableBody.innerHTML = `
                        <tr>
                            <td colspan="6" style="padding: 24px; text-align: center; color: var(--text-secondary);">暂无符合条件的历史日志</td>
                        </tr>
                    `;
                    return;
                }

                filteredLogs.forEach(log => {
                    const tr = document.createElement("tr");
                    tr.style.borderBottom = "1px solid var(--border-color)";

                    const typeText = log.type === "single" ? "📍 单点导航" : "🔁 巡逻任务";
                    
                    let durationText = "";
                    if (log.duration < 60) {
                        durationText = `${log.duration} 秒`;
                    } else {
                        const min = Math.floor(log.duration / 60);
                        const sec = Math.round(log.duration % 60);
                        durationText = `${min}分${sec}秒`;
                    }

                    let distanceText = "";
                    if (log.distance < 1000) {
                        distanceText = `${log.distance.toFixed(2)} 米`;
                    } else {
                        const km = log.distance / 1000;
                        distanceText = `${km.toFixed(2)} 公里`;
                    }

                    let statusBadge = "";
                    if (log.status === "reached") {
                        statusBadge = '<span class="status-badge online" style="padding: 2px 6px; font-size: 0.7rem; border-radius: 4px;">🏁 成功</span>';
                    } else if (log.status === "canceled") {
                        statusBadge = '<span class="status-badge offline" style="background: rgba(243,156,18,0.2); border-color: rgba(243,156,18,0.4); color: #f39c12; padding: 2px 6px; font-size: 0.7rem; border-radius: 4px;">⚠️ 取消</span>';
                    } else {
                        statusBadge = '<span class="status-badge offline" style="padding: 2px 6px; font-size: 0.7rem; border-radius: 4px;">❌ 失败</span>';
                    }

                    const deleteBtn = `<button class="btn-del" style="background: transparent; border: none; cursor: pointer; color: var(--accent-red); font-size: 0.95rem; padding: 2px 6px; display: inline-flex; align-items: center; justify-content: center; transition: transform 0.2s;" onmouseover="this.style.transform='scale(1.2)'" onmouseout="this.style.transform='scale(1)'" onclick="deleteTaskLog('${log.id}')">🗑️</button>`;

                    tr.innerHTML = `
                        <td style="padding: 10px 12px; color: var(--text-primary); font-weight: 500;">${typeText}</td>
                        <td style="padding: 10px 12px; color: var(--text-secondary); font-family: monospace;">${log.start_time}</td>
                        <td style="padding: 10px 12px; color: var(--text-secondary);">${durationText}</td>
                        <td style="padding: 10px 12px; color: var(--text-secondary);">${distanceText}</td>
                        <td style="padding: 10px 12px;">${statusBadge}</td>
                        <td style="padding: 10px 12px; text-align: center;">${deleteBtn}</td>
                    `;
                    tableBody.appendChild(tr);
                });
            }
        })
        .catch(err => {
            console.error("加载导航日志失败:", err);
        });
}

function deleteTaskLog(logId) {
    if (!confirm("确定要删除这条任务日志吗？此操作无法撤销。")) {
        return;
    }
    fetch(`${API_BASE}/api/v1/patrol/logs/${logId}`, {
        method: "DELETE"
    })
    .then(res => {
        if (!res.ok) throw new Error("删除日志失败");
        return res.json();
    })
    .then(() => {
        showToast("任务日志已删除", "success");
        refreshTaskLogs();
    })
    .catch(err => {
        showToast(err.message || "删除失败", "error");
    });
}

function clearAllTaskLogs() {
    if (!confirm("⚠️ 警告：确定要清空全部导航与巡逻任务日志吗？此操作无法恢复！")) {
        return;
    }
    fetch(`${API_BASE}/api/v1/patrol/logs`, {
        method: "DELETE"
    })
    .then(res => {
        if (!res.ok) throw new Error("清空日志失败");
        return res.json();
    })
    .then(() => {
        showToast("任务日志已全部清空", "success");
        refreshTaskLogs();
    })
    .catch(err => {
        showToast(err.message || "清空失败", "error");
    });
}

// 绑定全局以便 HTML 中可以使用 onclick
window.refreshTaskLogs = refreshTaskLogs;
window.deleteTaskLog = deleteTaskLog;
window.clearAllTaskLogs = clearAllTaskLogs;


