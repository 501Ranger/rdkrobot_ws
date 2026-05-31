import os
import time
import json
import subprocess
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse

from .. import ros_node as rn
from .. import manager as m
from ..config import static_dir, robot_config, WORKSPACE_SETUP_BASH

router = APIRouter(tags=["Robot"])

@router.get("/", response_class=HTMLResponse)
def read_index():
    """返回主页 HMI 控制面板"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail=f"index.html not found in {static_dir}")

@router.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await m.manager.connect(websocket)
    try:
        while True:
            # 接收文本帧，如果是 JSON 则尝试解析为遥控数据
            text_data = await websocket.receive_text()
            if text_data in ("ping", "heartbeat"):
                continue
            try:
                data = json.loads(text_data)
                if isinstance(data, dict) and data.get("type") == "teleop":
                    linear_x = float(data.get("linear_x", 0.0))
                    angular_z = float(data.get("angular_z", 0.0))
                    print(f"[WS Teleop] 收到手柄指令: x={linear_x:.3f}, z={angular_z:.3f}, ROS节点有效={rn.ros_node is not None}")
                    if rn.ros_node:
                        rn.ros_node.publish_cmd_vel(linear_x, angular_z)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        m.manager.disconnect(websocket)
    except Exception:
        m.manager.disconnect(websocket)

@router.get("/api/v1/robot/status")
def get_robot_status():
    """获取小车电池、位姿等实时状态以及下位机在线状态，包含进程状态"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    
    current_time = time.time()
    mcu_online = (current_time - rn.ros_node.last_battery_time < 3.0) or \
                 (current_time - rn.ros_node.last_odom_time < 3.0)
                 
    slam_running = (m.slam_process is not None) and (m.slam_process.poll() is None)
    explore_running = (m.explore_process is not None) and (m.explore_process.poll() is None)
    agent_res = os.system("docker ps --filter name=microros_agent | grep microros_agent >/dev/null 2>&1")
    agent_running = (agent_res == 0) or ((m.agent_process is not None) and (m.agent_process.poll() is None))
    sim_running = (m.sim_process is not None) and (m.sim_process.poll() is None)
    base_running = (m.base_process is not None) and (m.base_process.poll() is None)
    lidar_running = (m.lidar_process is not None) and (m.lidar_process.poll() is None)

    return {
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
        "nav2_plan": rn.ros_node.nav2_path
    }

@router.post("/api/v1/robot/hardware/init")
def init_real_robot_hardware():
    """一键初始化实机底层硬件驱动（串口代理、底盘TF/状态发布、雷达驱动）"""
    status_info = []
    
    # 1. 启动 micro-ROS 串口代理
    agent_res = os.system("docker ps --filter name=microros_agent | grep microros_agent >/dev/null 2>&1")
    agent_running = (agent_res == 0) or ((m.agent_process is not None) and (m.agent_process.poll() is None))
    if not agent_running:
        os.system("docker kill microros_agent >/dev/null 2>&1 || true")
        os.system("docker rm microros_agent >/dev/null 2>&1 || true")
        agent_cfg = robot_config.get("agent", {})
        serial_port = agent_cfg.get("serial_port", "/dev/ttyACM0")
        baud_rate = str(agent_cfg.get("baud_rate", 921600))
        cmd_agent = [
            "docker", "run", "--name", "microros_agent", "--rm",
            "-v", "/dev:/dev", "--privileged",
            "microros/micro-ros-agent:humble",
            "serial", "--dev", serial_port, "-b", baud_rate
        ]
        try:
            m.agent_process = subprocess.Popen(cmd_agent, preexec_fn=os.setsid)
            status_info.append("micro-ROS agent started")
        except Exception as e:
            status_info.append(f"Failed to start micro-ROS agent: {e}")
    else:
        status_info.append("micro-ROS agent already running")

    # 2. 启动 bringup_base.launch.py
    base_running = (m.base_process is not None) and (m.base_process.poll() is None)
    if not base_running:
        cmd_base = [
            "bash", "-c",
            f"source /opt/ros/humble/setup.bash && source {WORKSPACE_SETUP_BASH} && ros2 launch rdk_robot_bringup bringup_base.launch.py"
        ]
        try:
            m.base_process = subprocess.Popen(cmd_base, preexec_fn=os.setsid)
            status_info.append("bringup_base started")
        except Exception as e:
            status_info.append(f"Failed to start bringup_base: {e}")
    else:
        status_info.append("bringup_base already running")

    # 3. 启动 lsn10p_launch.py
    lidar_running = (m.lidar_process is not None) and (m.lidar_process.poll() is None)
    if not lidar_running:
        cmd_lidar = [
            "bash", "-c",
            f"source /opt/ros/humble/setup.bash && source {WORKSPACE_SETUP_BASH} && ros2 launch lslidar_driver lsn10p_launch.py"
        ]
        try:
            m.lidar_process = subprocess.Popen(cmd_lidar, preexec_fn=os.setsid)
            status_info.append("lsn10p_lidar started")
        except Exception as e:
            status_info.append(f"Failed to start lsn10p_lidar: {e}")
    else:
        status_info.append("lsn10p_lidar already running")

    return {"status": "success", "details": status_info}

@router.post("/api/v1/robot/hardware/stop")
def stop_real_robot_hardware():
    """停止实机底层硬件驱动（串口代理、底盘TF、雷达驱动）"""
    status_info = []
    
    # 停止串口代理
    try:
        os.system("docker kill microros_agent >/dev/null 2>&1 || true")
        if m.agent_process:
            m.terminate_process_group(m.agent_process)
            m.agent_process = None
        status_info.append("micro-ROS agent stopped")
    except Exception as e:
        status_info.append(f"Failed to stop agent: {e}")
        
    # 停止 bringup_base
    try:
        if m.base_process:
            m.terminate_process_group(m.base_process)
            m.base_process = None
        status_info.append("bringup_base stopped")
    except Exception as e:
        status_info.append(f"Failed to stop bringup_base: {e}")

    # 停止雷达驱动
    try:
        if m.lidar_process:
            m.terminate_process_group(m.lidar_process)
            m.lidar_process = None
        status_info.append("lsn10p_lidar stopped")
    except Exception as e:
        status_info.append(f"Failed to stop lidar: {e}")

    return {"status": "success", "details": status_info}
