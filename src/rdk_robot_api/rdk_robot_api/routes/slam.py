import os
import time
import threading
import subprocess
from fastapi import APIRouter, HTTPException
from ament_index_python.packages import get_package_share_directory

from .. import ros_node as rn
from .. import manager as m
from ..config import MAPS_DIR, WORKSPACE_SETUP_BASH
from ..models import MapSavePayload

router = APIRouter(prefix="/api/v1/slam", tags=["SLAM"])

def check_use_sim_time(node) -> bool:
    """通过检测 /clock 话题自动推断是否处于仿真环境"""
    if not node:
        return False
    try:
        topic_names_and_types = node.get_topic_names_and_types()
        for topic_name, _ in topic_names_and_types:
            if topic_name == '/clock':
                node.get_logger().info("Detected '/clock' topic. Auto-configured use_sim_time := true")
                return True
    except Exception as e:
        node.get_logger().warn(f"Failed to detect /clock topic: {e}")
    node.get_logger().info("No '/clock' topic detected. Auto-configured use_sim_time := false")
    return False

def _auto_start_nav2_after_delay(use_sim: bool, delay: float = 8.0):
    """后台线程：等待 SLAM 初始化后自动拉起 Nav2 导航栈"""
    time.sleep(delay)

    if m.slam_process is None or m.slam_process.poll() is not None:
        if rn.ros_node:
            rn.ros_node.get_logger().info("Auto-Nav2: SLAM is no longer running. Skipping Nav2 auto-start.")
        return

    if m.nav2_process and m.nav2_process.poll() is None:
        if rn.ros_node:
            rn.ros_node.get_logger().info("Auto-Nav2: Nav2 is already running. Skip.")
        return

    sim_flag = "true" if use_sim else "false"
    try:
        bringup_share = get_package_share_directory('rdk_robot_bringup')
        params_file = os.path.join(
            bringup_share, 'config',
            'nav2_sim_params.yaml' if use_sim else 'nav2_params.yaml'
        )
    except Exception:
        install_dir = os.path.dirname(WORKSPACE_SETUP_BASH)
        params_file = os.path.join(
            install_dir, 'rdk_robot_bringup', 'share', 'rdk_robot_bringup', 'config',
            'nav2_sim_params.yaml' if use_sim else 'nav2_params.yaml'
        )

    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source {WORKSPACE_SETUP_BASH} && "
        f"ros2 launch rdk_robot_bringup navigation.launch.py use_sim_time:={sim_flag} params_file:={params_file}"
    ]
    try:
        m.nav2_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        if rn.ros_node:
            rn.ros_node.get_logger().info(
                f"Auto-Nav2: Nav2 navigation stack started automatically (sim={sim_flag}, params={os.path.basename(params_file)})."
            )
    except Exception as e:
        if rn.ros_node:
            rn.ros_node.get_logger().error(f"Auto-Nav2: Failed to start Nav2: {e}")

@router.post("/start")
def start_slam_mapping():
    """启动 SLAM 建图"""
    # 1. 检查并确保定位节点（map_server/amcl）挂起，释放 /map 话题 and TF，防止冲突
    if m.loc_process and m.loc_process.poll() is None:
        rn.ros_node.get_logger().info("SLAM requested. Pausing active localization nodes...")
        rn.ros_node.change_localization_manager_state(1) # PAUSE

    # 2. 如果 SLAM 进程已经运行，直接返回
    if m.slam_process and m.slam_process.poll() is None:
        return {"status": "success", "message": "SLAM mapping is already running."}

    # 3. 仿真模式下，等待 /odom 话题就绪（最多等 12 秒）
    use_sim = check_use_sim_time(rn.ros_node)
    if use_sim:
        rn.ros_node.get_logger().info("Sim mode: waiting for /odom topic to be ready before starting SLAM...")
        odom_ready = False
        for _ in range(120):
            topic_names = [name for name, _ in rn.ros_node.get_topic_names_and_types()]
            if "/odom" in topic_names and rn.ros_node.last_odom_time > 0.0:
                odom_ready = True
                rn.ros_node.get_logger().info("/odom is active. Proceeding to start SLAM.")
                break
            time.sleep(0.1)
        if not odom_ready:
            raise HTTPException(
                status_code=503,
                detail="Timeout waiting for /odom topic. Make sure Gazebo simulation is fully running."
            )

    sim_flag = "true" if use_sim else "false"
    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source {WORKSPACE_SETUP_BASH} && ros2 launch rdk_robot_bringup slam.launch.py use_sim_time:={sim_flag}"
    ]
    try:
        m.slam_process = subprocess.Popen(cmd, preexec_fn=os.setsid)

        # SLAM 启动成功后，在后台线程中延时自动拉起 Nav2
        nav2_thread = threading.Thread(
            target=_auto_start_nav2_after_delay,
            args=(use_sim,),
            daemon=True
        )
        nav2_thread.start()

        return {"status": "success", "message": "SLAM mapping started. Nav2 will auto-start in ~8s."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start SLAM: {e}")

@router.post("/stop")
def stop_slam_mapping():
    """停止 SLAM 建图（同时联动停止 Nav2 导航栈）"""
    if not m.slam_process or m.slam_process.poll() is not None:
        return {"status": "success", "message": "SLAM mapping is not running."}

    try:
        rn.ros_node.get_logger().info("Terminating slam_toolbox process group...")
        m.terminate_process_group(m.slam_process)
        m.slam_process = None

        # 联动停止 Nav2
        if m.nav2_process and m.nav2_process.poll() is None:
            rn.ros_node.get_logger().info("Auto-stopping Nav2 navigation stack along with SLAM...")
            m.terminate_process_group(m.nav2_process)
            m.nav2_process = None

        return {"status": "success", "message": "SLAM mapping and Nav2 navigation stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop SLAM: {e}")

@router.get("/status")
def get_slam_mapping_status():
    """获取 SLAM 建图状态"""
    running = (m.slam_process is not None) and (m.slam_process.poll() is None)
    return {"running": running}

@router.post("/save")
def save_slam_map(payload: MapSavePayload):
    """保存当前 SLAM 地图"""
    if not os.path.exists(MAPS_DIR):
        os.makedirs(MAPS_DIR, exist_ok=True)
        
    output_path = os.path.join(MAPS_DIR, payload.map_name)
    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source {WORKSPACE_SETUP_BASH} && ros2 run nav2_map_server map_saver_cli -f {output_path}"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15.0)
        if res.returncode == 0:
            return {"status": "success", "message": f"Map successfully saved as '{payload.map_name}' in {MAPS_DIR}"}
        else:
            raise HTTPException(status_code=500, detail=f"map_saver_cli failed: {res.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=544, detail="Timeout while saving map.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing map_saver_cli: {e}")
