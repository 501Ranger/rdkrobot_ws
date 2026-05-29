import threading
import uvicorn
import signal
import os
import rclpy
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import static_dir
from .scheduler import PatrolScheduler
from . import ros_node as rn
from . import manager as m
from .routes import system, robot, sim, agent, patrol, nav, slam, explore, maps

app = FastAPI(title="RDK Robot API Service", version="3.0.0")

# 启用 CORS 跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(m.broadcast_status_loop())

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
        rn.ros_node.publish_patrol_cmd("start")

def main():
    # 注册 SIGTERM 信号处理器，确保收到 SIGTERM 时能运行 finally 块清理进程组
    signal.signal(signal.SIGTERM, sigterm_handler)
    
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
        os.system("docker kill microros_agent >/dev/null 2>&1 || true")

if __name__ == "__main__":
    main()
