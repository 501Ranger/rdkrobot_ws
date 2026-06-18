import os
import signal
import subprocess
import time
import asyncio
import logging
import sys
import datetime
from typing import List
from fastapi import WebSocket

from .utils import check_docker_container

# 全局重大系统日志队列
system_logs = [{"time": datetime.datetime.now().strftime("%H:%M:%S"), "level": "INFO", "message": "API 服务日志终端初始化成功"}]

def add_system_log(level: str, message: str):
    """添加一条重大系统日志"""
    now = datetime.datetime.now().strftime("%H:%M:%S")
    system_logs.append({"time": now, "level": level, "message": message})
    if len(system_logs) > 20:
        system_logs.pop(0)


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
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for connection in disconnected:
            self.disconnect(connection)

manager = ConnectionManager()

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

# 进程管理器容器
class ProcessManager:
    def __init__(self):
        self._processes = {
            "slam": None,
            "explore": None,
            "localization": None,
            "nav2": None,
            "sim": None,
            "agent": None,
            "base": None,
            "lidar": None,
            "joy": None
        }

    def get_process(self, name: str):
        p = self._processes.get(name)
        if p is not None:
            if p.poll() is not None:
                exit_code = p.poll()
                from . import ros_node as rn
                if rn.ros_node:
                    rn.ros_node.get_logger().warn(f"Process [{name}] exited with code {exit_code}")
                add_system_log("ERROR", f"进程 [{name}] 异常退出，退出码: {exit_code}")
                self._processes[name] = None
        return self._processes.get(name)

    def set_process(self, name: str, process):
        self._processes[name] = process
        if process is not None:
            add_system_log("INFO", f"成功启动 [{name}] 服务进程")

    def stop(self, name: str):
        p = self._processes.get(name)
        if p:
            terminate_process_group(p)
            self._processes[name] = None
            add_system_log("WARNING", f"已安全关闭 [{name}] 服务进程")


process_manager = ProcessManager()

# 定时巡逻触发事件广播标志
scheduled_patrol_triggered = False

# 巡逻过程中到达具体航点及完成巡逻的事件状态
waypoint_reached_index = 0
patrol_completed_triggered = False
patrol_interrupted_reason = ""
hardware_manually_stopped = False

async def broadcast_status_loop():
    from . import ros_node as rn # 延迟导入，防止循环引用
    while True:
        if rn.ros_node:
            try:
                # 线程安全地一次性提取所有实时数据包
                status_dict = rn.ros_node.get_robot_status_data()

                current_time = time.time()
                mcu_online = (current_time - status_dict["last_battery_time"] < 3.0) or \
                             (current_time - status_dict["last_odom_time"] < 3.0)
                
                slam_running = (process_manager.get_process("slam") is not None)
                explore_running = (process_manager.get_process("explore") is not None)
                
                # 检测 micro-ROS 代理是否在运行 (使用 1.5 秒缓存 check)
                agent_running = check_docker_container("microros_agent") or (process_manager.get_process("agent") is not None)
                
                sim_running = (process_manager.get_process("sim") is not None)
                base_running = (process_manager.get_process("base") is not None)
                lidar_running = (process_manager.get_process("lidar") is not None)
                joy_running = (process_manager.get_process("joy") is not None)
                
                global scheduled_patrol_triggered, waypoint_reached_index, patrol_completed_triggered, patrol_interrupted_reason
                
                triggered = scheduled_patrol_triggered
                if triggered:
                    scheduled_patrol_triggered = False

                reached_idx = waypoint_reached_index
                if reached_idx > 0:
                    waypoint_reached_index = 0

                completed_triggered = patrol_completed_triggered
                if completed_triggered:
                    patrol_completed_triggered = False

                interrupted_reason = patrol_interrupted_reason
                if interrupted_reason:
                    patrol_interrupted_reason = ""

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
                    "realtime_map": status_dict["realtime_map"],
                    "system_logs": system_logs
                }
                await manager.broadcast(status_data)
            except Exception as e:
                logging.exception("Exception in status broadcast loop")
        await asyncio.sleep(0.1) # 10Hz 频率广播

# 模块属性拦截代理 (黑魔法向下兼容)
class ManagerModule(sys.modules[__name__].__class__):
    @property
    def slam_process(self):
        return process_manager.get_process("slam")
    @slam_process.setter
    def slam_process(self, val):
        process_manager.set_process("slam", val)

    @property
    def explore_process(self):
        return process_manager.get_process("explore")
    @explore_process.setter
    def explore_process(self, val):
        process_manager.set_process("explore", val)

    @property
    def loc_process(self):
        return process_manager.get_process("localization")
    @loc_process.setter
    def loc_process(self, val):
        process_manager.set_process("localization", val)

    @property
    def nav2_process(self):
        return process_manager.get_process("nav2")
    @nav2_process.setter
    def nav2_process(self, val):
        process_manager.set_process("nav2", val)

    @property
    def sim_process(self):
        return process_manager.get_process("sim")
    @sim_process.setter
    def sim_process(self, val):
        process_manager.set_process("sim", val)

    @property
    def agent_process(self):
        return process_manager.get_process("agent")
    @agent_process.setter
    def agent_process(self, val):
        process_manager.set_process("agent", val)

    @property
    def base_process(self):
        return process_manager.get_process("base")
    @base_process.setter
    def base_process(self, val):
        process_manager.set_process("base", val)

    @property
    def lidar_process(self):
        return process_manager.get_process("lidar")
    @lidar_process.setter
    def lidar_process(self, val):
        process_manager.set_process("lidar", val)

    @property
    def joy_process(self):
        return process_manager.get_process("joy")
    @joy_process.setter
    def joy_process(self, val):
        process_manager.set_process("joy", val)

sys.modules[__name__].__class__ = ManagerModule
