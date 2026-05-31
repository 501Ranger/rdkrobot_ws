import os
import subprocess
from fastapi import APIRouter, HTTPException
from ament_index_python.packages import get_package_share_directory

from .. import manager as m

from ..config import WORKSPACE_SETUP_BASH

router = APIRouter(prefix="/api/v1/explore", tags=["Exploration"])

@router.post("/start")
def start_autonomous_exploration():
    """启动自主探索建图"""
    if m.explore_process and m.explore_process.poll() is None:
        return {"status": "success", "message": "Autonomous exploration is already running."}
    
    try:
        bringup_share = get_package_share_directory('rdk_robot_bringup')
        explore_config = os.path.join(bringup_share, 'config', 'explore.yaml')
    except Exception:
        # 尝试通过 WORKSPACE_SETUP_BASH 的上级目录推导
        install_dir = os.path.dirname(WORKSPACE_SETUP_BASH)
        explore_config = os.path.join(install_dir, 'rdk_robot_bringup', 'share', 'rdk_robot_bringup', 'config', 'explore.yaml')
        if not os.path.exists(explore_config):
            explore_config = "/home/ranger/rdkrobot_ws/install/rdk_robot_bringup/share/rdk_robot_bringup/config/explore.yaml"

    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source {WORKSPACE_SETUP_BASH} && ros2 run explore_lite explore --ros-args --params-file {explore_config}"
    ]
    try:
        m.explore_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        return {"status": "success", "message": "Autonomous exploration started successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start exploration: {e}")

@router.post("/stop")
def stop_autonomous_exploration():
    """停止自主探索建图"""
    if not m.explore_process or m.explore_process.poll() is not None:
        return {"status": "success", "message": "Autonomous exploration is not running."}
    
    try:
        m.terminate_process_group(m.explore_process)
        m.explore_process = None
        return {"status": "success", "message": "Autonomous exploration stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop exploration: {e}")

@router.get("/status")
def get_autonomous_exploration_status():
    """获取自主探索运行状态"""
    running = (m.explore_process is not None) and (m.explore_process.poll() is None)
    return {"running": running}
