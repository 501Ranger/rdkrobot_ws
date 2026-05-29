import os
import time
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse

from .. import ros_node as rn
from .. import manager as m
from ..config import static_dir

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
            # 维持连接与接收心跳/任何客户端消息
            await websocket.receive_text()
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
        "nav2_plan": rn.ros_node.nav2_path
    }
