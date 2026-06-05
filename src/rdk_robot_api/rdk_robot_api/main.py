import threading
import uvicorn
import signal
import os
import rclpy
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

from .config import static_dir, __version__
from .scheduler import PatrolScheduler
from . import ros_node as rn
from . import manager as m
from .routes import system, robot, sim, agent, patrol, nav, slam, explore, maps, voice

async def auto_detect_hardware_loop():
    """实机下位机物理串口检测与底层驱动自启动协程"""
    import asyncio
    import platform
    import os
    import logging
    from .routes.robot import init_real_robot_hardware
    from .models import HardwareInitPayload
    from .config import robot_config
    from .utils import check_docker_container
    
    # 1. 硬件平台环境过滤：PC端开发电脑直接禁用
    machine = platform.machine().lower()
    is_arm = "arm" in machine or "aarch64" in machine
    if not is_arm:
        logging.info("[AutoStart] PC environment detected (non-ARM). Auto hardware initialization disabled.")
        return
        
    logging.info("[AutoStart] ARM embedded host detected. Auto hardware detect loop started.")
    
    while True:
        await asyncio.sleep(3.0)
        
        # 2. 读取配置文件中指定的目标串口设备名
        agent_cfg = robot_config.get("agent", {})
        target_port = agent_cfg.get("serial_port", "/dev/ttyACM0")
        
        # 3. 精确检测目标物理串口文件是否存在
        port_exists = os.path.exists(target_port)
        
        if port_exists and not getattr(m, "hardware_manually_stopped", False):
            # 4. 判断硬件驱动是否未启动完整
            agent_running = check_docker_container("microros_agent") or ((m.agent_process is not None) and (m.agent_process.poll() is None))
            base_running = (m.base_process is not None) and (m.base_process.poll() is None)
            lidar_running = (m.lidar_process is not None) and (m.lidar_process.poll() is None)
            
            if not (agent_running and base_running and lidar_running):
                logging.info(f"[AutoStart] Detected port {target_port} but hardware drivers not running. Auto-initializing real robot hardware...")
                m.add_system_log("INFO", f"检测到下位机串口 {target_port}，已自动触发实机底层硬件初始化")
                try:
                    init_real_robot_hardware(HardwareInitPayload())
                except Exception as e:
                    logging.error(f"[AutoStart] Auto hardware initialization failed: {e}")
                    m.add_system_log("ERROR", f"自动触发实机底层硬件初始化失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 启动状态推送协程
    asyncio.create_task(m.broadcast_status_loop())
    # 启动实机下位机自动检测初始化协程
    asyncio.create_task(auto_detect_hardware_loop())
    yield

app = FastAPI(title="RDK Robot API Service", version=__version__, lifespan=lifespan)

# 启用 CORS 跨域请求（安全加固，仅限本地及局域网段）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.*",
        "http://10.*",
        "http://172.16.*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 针对 HMI 主页和静态文件禁用缓存中间件，解决浏览器强缓存旧 JS 代码的问题
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# 挂载静态文件目录
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir, follow_symlink=True), name="static")

# 注册 API 路由
app.include_router(system.router)
app.include_router(robot.router)
app.include_router(sim.router)
app.include_router(agent.router)
app.include_router(patrol.router)
app.include_router(nav.router)
app.include_router(slam.router)
app.include_router(explore.router)
app.include_router(maps.router)
app.include_router(voice.router)



def ros2_thread_entry():
    rclpy.init()
    rn.ros_node = rn.RobotApiNode()
    rclpy.spin(rn.ros_node)
    rn.ros_node.destroy_node()
    rclpy.shutdown()

def sigterm_handler(signum, frame):
    raise KeyboardInterrupt

def trigger_patrol_by_schedule():
    """定时任务触发的回调函数"""
    if rn.ros_node:
        rn.ros_node.get_logger().info("Scheduled event triggered! Starting patrol...")
        rn.ros_node.publish_patrol_cmd("start_once")
        
        # 激活前端 Web 顶部提示条幅通知
        from . import manager as m
        m.scheduled_patrol_triggered = True

def main():
    # 注册 SIGTERM 信号处理器，确保收到 SIGTERM 时能运行 finally 块清理进程组
    signal.signal(signal.SIGTERM, sigterm_handler)
    
    # 0. 启动前强行清理可能存在的残留进程，保证环境绝对干净
    os.system("pkill -9 -f gazebo || true")
    os.system("pkill -9 -f gzserver || true")
    os.system("pkill -9 -f gzclient || true")
    os.system("pkill -9 -f nav2_ || true")
    os.system("pkill -9 -f amcl || true")
    os.system("pkill -9 -f map_server || true")
    os.system("pkill -9 -f planner_server || true")
    os.system("pkill -9 -f controller_server || true")
    os.system("pkill -9 -f behavior_server || true")
    os.system("pkill -9 -f bt_navigator || true")
    os.system("pkill -9 -f waypoint_follower || true")
    os.system("pkill -9 -f velocity_smoother || true")
    os.system("pkill -9 -f smoother_server || true")
    os.system("pkill -9 -f lifecycle_manager || true")
    os.system("pkill -9 -f patrol_node || true")
    os.system("pkill -9 -f robot_state_publisher || true")
    os.system("pkill -9 -f spawn_entity.py || true")
    os.system("pkill -9 -f auto_localize || true")
    os.system("docker kill microros_agent >/dev/null 2>&1 || true")
    
    # 1. 启动 ROS 2 守护子线程
    ros_thread = threading.Thread(target=ros2_thread_entry, daemon=True)
    ros_thread.start()
    
    # 2. 启动定时器调度器并注入到路由中
    scheduler = PatrolScheduler(trigger_callback=trigger_patrol_by_schedule)
    scheduler.start()
    patrol.scheduler = scheduler
    
    # 3. 运行 FastAPI Uvicorn 服务 (监听 0.0.0.0:8000)
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except KeyboardInterrupt:
        pass
    finally:
        if scheduler:
            scheduler.stop()
        # 退出时彻底清理所有可能残留的后台进程组，防止僵尸进程
        m.terminate_process_group(m.slam_process)
        m.terminate_process_group(m.explore_process)
        m.terminate_process_group(m.loc_process)
        m.terminate_process_group(m.nav2_process)
        m.terminate_process_group(m.sim_process)
        m.terminate_process_group(m.agent_process)
        m.terminate_process_group(m.base_process)
        m.terminate_process_group(m.lidar_process)
        os.system("docker kill microros_agent >/dev/null 2>&1 || true")

if __name__ == "__main__":
    main()
