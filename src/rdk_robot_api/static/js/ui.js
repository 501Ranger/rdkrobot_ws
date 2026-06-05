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

