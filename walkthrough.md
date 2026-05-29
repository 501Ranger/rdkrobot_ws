# 🚀 RDK Robot 项目重构、新功能及 CI/CD 交付说明书

本说明书向您呈现本次重构与新功能的完整交接，包含：
1. **API 服务子路由重构**
2. **多点导航路径精细预览**
3. **深浅色毛玻璃主题切换**
4. **云端交叉编译发布 (CI/CD)**
5. **小车端一键拉取更新部署脚本**

---

## 🎨 1. 新增与修改的文件变动明细

本次任务累计交付以下核心文件变动：

### 🛠️ 1.1 API 拆分重构 (rdk_robot_api/rdk_robot_api/)
- [NEW] [config.py](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/rdk_robot_api/config.py) — 统一参数加载器。
- [NEW] [models.py](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/rdk_robot_api/models.py) — 统一 Pydantic 载荷数据结构。
- [NEW] [manager.py](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/rdk_robot_api/manager.py) — 后台进程生命周期管理及 10Hz 状态广播。
- [NEW] [ros_node.py](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/rdk_robot_api/ros_node.py) — 桥接节点（新增 `ComputePathToPose` 动作客户端支持）。
- [NEW] `routes/` 业务分路路由子包目录（含 `__init__.py`）：
  - `system.py` — 系统环境 API。
  - `robot.py` — 状态、Web 舱主页和 WebSocket 传输 API。
  - `sim.py` — 仿真控制 API。
  - `agent.py` — micro-ROS 代理控制 API.
  - `patrol.py` — 巡逻下发与定时调度 API。
  - `nav.py` — 一般导航及**新增 `/api/v1/nav/preview` 分段算路路径预览端点**。
  - `slam.py` — SLAM 启停及 8s 后台延迟联动拉起 Nav2。
  - `explore.py` — 自主前沿边界探索建图 API。
  - `maps.py` — 地图管理与 POI 语义标定 API。
- [MODIFY] [main.py](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/rdk_robot_api/main.py) — 作为入口，汇聚中间件，挂载并注册路由，启动后台自旋线程。
- [MODIFY] [setup.py](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/setup.py) — 改用 `find_packages` 自动识别子包进行打包发布。

### 🖥️ 1.2 HMI 前端界面 (static/)
- [MODIFY] [index.html](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/static/index.html) — 右上角增加 `btn-theme-toggle` 圆形切换按钮。
- [MODIFY] [style.css](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/static/css/style.css) — 增加 `:root[data-theme="light"]` 全套配色，实现高雅亮白半透明毛玻璃质感，配备 hover 缩放及 $30^\circ$ 旋转动效。
- [MODIFY] [app.js](file:///home/ranger/rdkrobot_ws/src/rdk_robot_api/static/js/app.js) — 初始化与切换主题逻辑，并在 `drawPlannedPath()` 中实现 **400ms 算路防抖** 与 **直线段双轨容错降级**。

### ⛓️ 1.3 CI/CD 工作流与实机部署 (新引入)
- [NEW] [.github/workflows/build_and_release.yml](file:///home/ranger/rdkrobot_ws/.github/workflows/build_and_release.yml) — GitHub Actions 工作流。在 `push` 到 `main` 时，自动在云端通过 Docker & QEMU 交叉编译生成小车 ARM64 二进制 `install_arm64` 包，打包后滚动覆盖发布到 GitHub Release 的 `latest` 标签下。
- [NEW] [scripts/deploy_pull.sh](file:///home/ranger/rdkrobot_ws/scripts/deploy_pull.sh) — 小车端一键部署脚本。可自动从 Git 提取路径，支持**公开**与**私有**仓库（传入 PAT），自动拉取最新 Release 包解压、备份旧目录，并发送信号安全热重启 `api_server`。
- [MODIFY] [ARCHITECTURE.md](file:///home/ranger/rdkrobot_ws/ARCHITECTURE.md) — 目录结构及桥接逻辑文档对齐更新。

---

## 📡 2. 详细使用指南：云端编译与小车一键更新部署

本方案采用 **“云端打包发布 (GitHub Release) $\rightarrow$ 小车端手动拉取安装包 (deploy_pull.sh)”** 模式，即使小车在 push 时处于关机状态，也能保证流水线完美运行，且下载包轻量，对局域网带宽极度友好。

### 步骤 A：云端权限配置（仅需配置一次）
1. 依次进入 GitHub 仓库的 `Settings -> Actions -> General`。
2. 找到 `Workflow permissions`（工作流权限）。
3. 勾选 **`Read and write permissions`** 并保存。

---

### 步骤 B：日常开发编译与发布流程
1. 在您的开发电脑上（跑仿真或做改动）：
   ```bash
   git add .
   git commit -m "feat: 完善多点避障路径预览与主题切换"
   git push origin main
   ```
2. 此时前往 GitHub 仓库的 `Actions` 选项卡，可以看到正在自动运行 `ARM64 Build & Rolling Release` 工作流。
3. 运行完成后，云端会自动生成一个 Tag 叫 `latest` 的 Release 页面，里面挂载了编译好的 `install_arm64.tar.gz` 资产。

---

### 步骤 C：实机一键更新步骤（小车端操作）
1. 启动小车并连接 Wi-Fi / 手机热点。
2. 登录小车终端，进入工作空间根目录 `/home/ranger/rdkrobot_ws`。
3. **如果该代码仓库是公开的**，直接运行脚本：
   ```bash
   ./scripts/deploy_pull.sh
   ```
4. **如果该代码仓库是私有仓库**，你需要带上你的 GitHub 个人访问令牌 (Personal Access Token, PAT) 进行鉴权下载：
   ```bash
   ./scripts/deploy_pull.sh <您的_GITHUB_TOKEN>
   ```
   *(或者通过环境变量执行 `GITHUB_TOKEN=ghp_xxx ./scripts/deploy_pull.sh`)*
5. 脚本会自动：
   - 自动备份本地原有的 `install/` 目录为 `install_backup_日期时间/`。
   - 解压并将其替换为新版二进制编译包。
   - 自动查找并重启小车上的 `api_server` 后端进程。
