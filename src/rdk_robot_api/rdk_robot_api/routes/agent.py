import os
import subprocess
from fastapi import APIRouter, HTTPException

from .. import manager as m
from ..config import robot_config

router = APIRouter(prefix="/api/v1/agent", tags=["Agent"])

@router.post("/start")
def start_microros_agent():
    """启动 micro-ROS 串口代理 (Docker)"""
    res = os.system("docker ps --filter name=microros_agent | grep microros_agent >/dev/null 2>&1")
    if res == 0:
        return {"status": "success", "message": "micro-ROS agent is already running."}
        
    os.system("docker kill microros_agent >/dev/null 2>&1 || true")
    os.system("docker rm microros_agent >/dev/null 2>&1 || true")
    
    agent_cfg = robot_config.get("agent", {})
    serial_port = agent_cfg.get("serial_port", "/dev/ttyACM0")
    baud_rate = str(agent_cfg.get("baud_rate", 921600))
    
    cmd = [
        "docker", "run", "--name", "microros_agent", "--rm",
        "-v", "/dev:/dev", "--privileged",
        "microros/micro-ros-agent:humble",
        "serial", "--dev", serial_port, "-b", baud_rate
    ]
    try:
        m.agent_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        return {"status": "success", "message": f"micro-ROS agent started successfully on {serial_port}."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start micro-ROS agent: {e}")

@router.post("/stop")
def stop_microros_agent():
    """停止 micro-ROS 串口代理"""
    try:
        os.system("docker kill microros_agent >/dev/null 2>&1 || true")
        if m.agent_process:
            m.terminate_process_group(m.agent_process)
            m.agent_process = None
        return {"status": "success", "message": "micro-ROS agent stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop micro-ROS agent: {e}")

@router.get("/status")
def get_microros_agent_status():
    """获取 micro-ROS 代理的运行状态"""
    res = os.system("docker ps --filter name=microros_agent | grep microros_agent >/dev/null 2>&1")
    running = (res == 0)
    return {"running": running}
