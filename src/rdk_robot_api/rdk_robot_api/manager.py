import os
import signal
import subprocess
import time
import asyncio
from typing import List
from fastapi import WebSocket

# WebSocket 连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# 全局子进程控制变量
slam_process = None
explore_process = None
loc_process = None
nav2_process = None
sim_process = None
agent_process = None
base_process = None
lidar_process = None

# 定时巡逻触发事件广播标志
scheduled_patrol_triggered = False

# 巡逻过程中到达具体航点及完成巡逻的事件状态
waypoint_reached_index = 0
patrol_completed_triggered = False

def terminate_process_group(process):
    """安全中止进程及其全部子进程组"""
    if not process or process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait()
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()

async def broadcast_status_loop():
    from . import ros_node as rn # 延迟导入，防止循环引用
    from . import manager as m
    while True:
        if rn.ros_node:
            try:
                current_time = time.time()
                mcu_online = (current_time - rn.ros_node.last_battery_time < 3.0) or \
                             (current_time - rn.ros_node.last_odom_time < 3.0)
                
                slam_running = (m.slam_process is not None) and (m.slam_process.poll() is None)
                explore_running = (m.explore_process is not None) and (m.explore_process.poll() is None)
                
                # 检测 micro-ROS 代理是否在运行
                agent_res = os.system("docker ps --filter name=microros_agent | grep microros_agent >/dev/null 2>&1")
                agent_running = (agent_res == 0) or ((m.agent_process is not None) and (m.agent_process.poll() is None))
                
                sim_running = (m.sim_process is not None) and (m.sim_process.poll() is None)
                base_running = (m.base_process is not None) and (m.base_process.poll() is None)
                lidar_running = (m.lidar_process is not None) and (m.lidar_process.poll() is None)
                
                triggered = m.scheduled_patrol_triggered
                if triggered:
                    m.scheduled_patrol_triggered = False

                reached_idx = m.waypoint_reached_index
                if reached_idx > 0:
                    m.waypoint_reached_index = 0

                completed_triggered = m.patrol_completed_triggered
                if completed_triggered:
                    m.patrol_completed_triggered = False

                status_data = {
                    "battery_percentage": round(rn.ros_node.battery_pct, 1),
                    "pose": rn.ros_node.robot_pose,
                    "is_localizing": rn.ros_node.is_localizing,
                    "nav_status": rn.ros_node.nav_status,
                    "mcu_online": mcu_online,
                    "slam_running": slam_running,
                    "explore_running": explore_running,
                    "agent_running": agent_running,
                    "sim_running": sim_running,
                    "base_running": base_running,
                    "lidar_running": lidar_running,
                    "nav2_plan": rn.ros_node.nav2_path,
                    "scheduled_patrol_triggered": triggered,
                    "waypoint_reached": reached_idx,
                    "patrol_completed": completed_triggered
                }
                await manager.broadcast(status_data)
            except Exception:
                pass
        await asyncio.sleep(0.1) # 10Hz 频率广播
