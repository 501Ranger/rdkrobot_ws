import os
import subprocess
from fastapi import APIRouter, HTTPException

from .. import ros_node as rn
from .. import manager as m

from ..config import WORKSPACE_SETUP_BASH

router = APIRouter(prefix="/api/v1/sim", tags=["Simulation"])

@router.post("/start")
def start_gazebo_simulation():
    """启动 Gazebo 仿真"""
    if m.sim_process and m.sim_process.poll() is None:
        return {"status": "success", "message": "Simulation is already running."}
        
    try:
        os.system("pkill -9 -f gzserver || true")
        os.system("pkill -9 -f gzclient || true")
        os.system("pkill -9 -f gazebo || true")
    except Exception as e:
        if rn.ros_node:
            rn.ros_node.get_logger().warn(f"Failed to clear old gazebo processes: {e}")
        
    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source {WORKSPACE_SETUP_BASH} && ros2 launch rdk_robot_bringup gazebo_bringup.launch.py"
    ]
    try:
        m.sim_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        return {"status": "success", "message": "Gazebo simulation started successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start Gazebo simulation: {e}")

@router.post("/stop")
def stop_gazebo_simulation():
    """停止 Gazebo 仿真"""
    if not m.sim_process or m.sim_process.poll() is not None:
        return {"status": "success", "message": "Simulation is not running."}
        
    try:
        m.terminate_process_group(m.sim_process)
        m.sim_process = None
        return {"status": "success", "message": "Gazebo simulation stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop Gazebo simulation: {e}")
