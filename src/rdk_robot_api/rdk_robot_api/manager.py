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
joy_process = None


# 定时巡逻触发事件广播标志
scheduled_patrol_triggered = False

# 巡逻过程中到达具体航点及完成巡逻的事件状态
waypoint_reached_index = 0
patrol_completed_triggered = False
patrol_interrupted_reason = ""

def check_and_reset_process(process, name):
    if process is not None:
        if process.poll() is not None:
            from . import ros_node as rn
            if rn.ros_node:
                rn.ros_node.get_logger().warn(f"Process [{name}] exited with code {process.poll()}")
            return None
    return process

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
    global slam_process, explore_process, loc_process, nav2_process, sim_process, agent_process, base_process, lidar_process, joy_process
    while True:
        if rn.ros_node:
            try:
                # 线程安全地一次性提取所有实时数据包
                status_dict = rn.ros_node.get_robot_status_data()

                current_time = time.time()
                mcu_online = (current_time - status_dict["last_battery_time"] < 3.0) or \
                             (current_time - status_dict["last_odom_time"] < 3.0)
                
                # 监控子进程存活并重置已退出进程
                m.slam_process = check_and_reset_process(m.slam_process, "slam")
                m.explore_process = check_and_reset_process(m.explore_process, "explore")
                m.loc_process = check_and_reset_process(m.loc_process, "localization")
                m.nav2_process = check_and_reset_process(m.nav2_process, "nav2")
                m.sim_process = check_and_reset_process(m.sim_process, "sim")
                m.agent_process = check_and_reset_process(m.agent_process, "agent")
                m.base_process = check_and_reset_process(m.base_process, "base")
                m.lidar_process = check_and_reset_process(m.lidar_process, "lidar")
                m.joy_process = check_and_reset_process(m.joy_process, "joy")

                slam_running = (m.slam_process is not None)
                explore_running = (m.explore_process is not None)
                
                # 检测 micro-ROS 代理是否在运行
                agent_res = os.system("docker ps --filter name=microros_agent | grep microros_agent >/dev/null 2>&1")
                agent_running = (agent_res == 0) or (m.agent_process is not None)
                
                sim_running = (m.sim_process is not None)
                base_running = (m.base_process is not None)
                lidar_running = (m.lidar_process is not None)
                joy_running = (m.joy_process is not None)
                
                triggered = m.scheduled_patrol_triggered
                if triggered:
                    m.scheduled_patrol_triggered = False

                reached_idx = m.waypoint_reached_index
                if reached_idx > 0:
                    m.waypoint_reached_index = 0

                completed_triggered = m.patrol_completed_triggered
                if completed_triggered:
                    m.patrol_completed_triggered = False

                interrupted_reason = m.patrol_interrupted_reason
                if interrupted_reason:
                    m.patrol_interrupted_reason = ""

                # 按需动态订阅/解绑 /map 话题以节省建图以外的计算开销
                if (slam_running or explore_running):
                    if rn.ros_node.map_sub is None:
                        from nav_msgs.msg import OccupancyGrid
                        rn.ros_node.map_sub = rn.ros_node.create_subscription(
                            OccupancyGrid, "/map", rn.ros_node.map_callback, 10
                        )
                        rn.ros_node.get_logger().info("Subscribed to /map for live SLAM rendering.")
                else:
                    if rn.ros_node.map_sub is not None:
                        rn.ros_node.destroy_subscription(rn.ros_node.map_sub)
                        rn.ros_node.map_sub = None
                        # 重置 realtime_map_data 需要在锁保护下进行
                        with rn.ros_node._lock:
                            rn.ros_node.realtime_map_data = None
                        rn.ros_node.get_logger().info("Unsubscribed from /map.")

                status_data = {
                    "battery_percentage": status_dict["battery_percentage"],
                    "pose": status_dict["pose"],
                    "is_localizing": status_dict["is_localizing"],
                    "nav_status": status_dict["nav_status"],
                    "mcu_online": mcu_online,
                    "slam_running": slam_running,
                    "explore_running": explore_running,
                    "agent_running": agent_running,
                    "sim_running": sim_running,
                    "base_running": base_running,
                    "lidar_running": lidar_running,
                    "joy_running": joy_running,
                    "joy_unlocked": status_dict.get("joy_unlocked", False),
                    "nav2_plan": status_dict["nav2_path"],
                    "scheduled_patrol_triggered": triggered,
                    "waypoint_reached": reached_idx,
                    "patrol_completed": completed_triggered,
                    "patrol_interrupted": interrupted_reason,
                    "realtime_map": status_dict["realtime_map"]
                }
                await manager.broadcast(status_data)
            except Exception:
                pass
        await asyncio.sleep(0.1) # 10Hz 频率广播
