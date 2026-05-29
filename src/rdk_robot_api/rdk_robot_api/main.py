import threading
import uvicorn
import os
import subprocess
import time
import math
import yaml
import cv2
import json
import signal
from io import BytesIO
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from rclpy.action import ActionClient
from std_msgs.msg import String, Bool
from geometry_msgs.msg import PoseArray, Pose
from std_srvs.srv import Trigger
from sensor_msgs.msg import BatteryState
from nav_msgs.msg import Odometry
from nav2_msgs.srv import LoadMap, ManageLifecycleNodes
from nav2_msgs.action import NavigateToPose
from ament_index_python.packages import get_package_share_directory
from lifecycle_msgs.srv import ChangeState
from lifecycle_msgs.msg import Transition
import platform

from .scheduler import PatrolScheduler

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

# 寻找并确定静态文件目录的路径
try:
    share_dir = get_package_share_directory('rdk_robot_api')
    static_dir = os.path.join(share_dir, 'static')
except Exception:
    # 备用本地开发路径
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir, follow_symlink=True), name="static")

@app.get("/", response_class=HTMLResponse)
def read_index():
    """返回主页 HMI 控制面板"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail=f"index.html not found in {static_dir}")


# Pydantic 模型的请求载荷定义
class CommandPayload(BaseModel):
    cmd: str = Field(..., description="指令：'start', 'pause', 'stop', 'resume'")

class WaypointPayload(BaseModel):
    x: float
    y: float
    yaw: float = Field(0.0, description="朝向角(弧度)")

class TaskPayload(BaseModel):
    waypoints: List[WaypointPayload]

class SchedulePayload(BaseModel):
    time: str = Field(..., description="定时时间，格式 'HH:MM' (如 '18:30')")
    repeat: str = Field("daily", description="重复模式，目前仅支持 'daily'")

class MapSavePayload(BaseModel):
    map_name: str = Field(..., description="保存地图的文件名")

class POIPayload(BaseModel):
    name: str = Field(..., description="语义点名称，如 'kitchen'")
    x: float
    y: float
    yaw: float = Field(0.0, description="朝向角(弧度)")

class NavGoPayload(BaseModel):
    x: float = Field(None, description="目标物理 x 坐标")
    y: float = Field(None, description="目标物理 y 坐标")
    yaw: float = Field(0.0, description="目标物理 yaw 角度")
    poi_name: str = Field(None, description="语义点名称（若提供此参数，则忽略 x, y, yaw 并匹配该点的坐标）")


# ROS 2 桥接节点类
class RobotApiNode(Node):
    def __init__(self):
        super().__init__("robot_api_node")

        # 配置 Transient Local QoS 订阅状态
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)

        # 发布者
        self.patrol_cmd_pub = self.create_publisher(String, "/patrol/cmd", 10)
        self.waypoints_pub = self.create_publisher(PoseArray, "/patrol/set_waypoints", 10)

        # 订阅者
        self.battery_sub = self.create_subscription(
            BatteryState, "/battery_state", self.battery_callback, 10
        )
        self.odom_sub = self.create_subscription(
            Odometry, "/odom", self.odom_callback, 10
        )
        self.localize_status_sub = self.create_subscription(
            Bool, "/auto_localize/status", self.localize_status_callback, qos
        )

        # 服务客户端
        self.localize_cli = self.create_client(Trigger, "/trigger_auto_localize")
        self.load_map_cli = self.create_client(LoadMap, "/map_server/load_map")

        # 导航 Action 客户端
        self.nav_action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        # 内部缓存状态
        self.battery_pct = 0.0
        self.robot_pose = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        self.is_localizing = False
        
        # 导航相关变量
        self.current_nav_goal_handle = None
        self.latest_goal_id = 0
        self.nav_status = "idle"  # "idle", "navigating", "reached", "failed", "canceled"

        # 下位机在线检测时间戳
        self.last_battery_time = 0.0
        self.last_odom_time = 0.0

    def battery_callback(self, msg: BatteryState):
        self.battery_pct = msg.percentage * 100.0 if msg.percentage <= 1.0 else msg.percentage
        self.last_battery_time = time.time()

    def odom_callback(self, msg: Odometry):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        
        # 四元数转 yaw
        siny_cosp = 2.0 * (ori.w * ori.z + ori.x * ori.y)
        cosy_cosp = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        
        self.robot_pose = {
            "x": pos.x,
            "y": pos.y,
            "yaw": yaw
        }
        self.last_odom_time = time.time()

    def localize_status_callback(self, msg: Bool):
        self.is_localizing = msg.data

    def change_lifecycle_state(self, node_name: str, transition_id: int) -> bool:
        """调用 ROS 2 Lifecycle 服务更改节点运行状态"""
        srv_name = f"/{node_name}/change_state"
        client = self.create_client(ChangeState, srv_name)
        
        self.get_logger().info(f"Waiting for lifecycle service: {srv_name}...")
        if not client.wait_for_service(timeout_sec=2.0):
            self.get_logger().error(f"Lifecycle service {srv_name} not available.")
            return False
            
        req = ChangeState.Request()
        req.transition.id = transition_id
        
        self.get_logger().info(f"Calling change_state on {node_name} with transition id {transition_id}...")
        future = client.call_async(req)
        
        # 阻塞等待结果
        start_time = time.time()
        timeout = 4.0
        while not future.done():
            time.sleep(0.1)
            if time.time() - start_time > timeout:
                self.get_logger().error(f"Timeout waiting for {node_name} state transition.")
                return False
                
        res = future.result()
        if res and res.success:
            self.get_logger().info(f"Successfully transitioned {node_name} state.")
            return True
        else:
            self.get_logger().error(f"Failed to transition {node_name} state.")
            return False

    def change_localization_manager_state(self, command_id: int) -> bool:
        """调用 lifecycle_manager_localization 服务的 manage_nodes 来暂停/恢复/重置定位节点"""
        srv_name = "/lifecycle_manager_localization/manage_nodes"
        client = self.create_client(ManageLifecycleNodes, srv_name)
        
        self.get_logger().info(f"Waiting for localization manager service: {srv_name}...")
        if not client.wait_for_service(timeout_sec=2.0):
            self.get_logger().error(f"Localization manager service {srv_name} not available.")
            return False
            
        req = ManageLifecycleNodes.Request()
        req.command = command_id
        
        self.get_logger().info(f"Calling manage_nodes with command {command_id}...")
        future = client.call_async(req)
        
        # 阻塞等待结果
        start_time = time.time()
        timeout = 4.0
        while not future.done():
            time.sleep(0.1)
            if time.time() - start_time > timeout:
                self.get_logger().error(f"Timeout waiting for localization manager state change.")
                return False
                
        res = future.result()
        if res and res.success:
            self.get_logger().info(f"Successfully changed localization manager state.")
            return True
        else:
            self.get_logger().error(f"Failed to change localization manager state.")
            return False

    def publish_patrol_cmd(self, cmd: str):
        msg = String()
        msg.data = cmd
        self.patrol_cmd_pub.publish(msg)
        self.get_logger().info(f"Published patrol command: '{cmd}'")

    def publish_waypoints(self, wps: List[WaypointPayload]):
        msg = PoseArray()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()

        for wp in wps:
            pose = Pose()
            pose.position.x = wp.x
            pose.position.y = wp.y
            pose.position.z = 0.0
            # yaw 转四元数
            pose.orientation.z = math.sin(wp.yaw / 2.0)
            pose.orientation.w = math.cos(wp.yaw / 2.0)
            msg.poses.append(pose)

        self.waypoints_pub.publish(msg)
        self.get_logger().info(f"Published {len(wps)} waypoints dynamically.")

    # 导航控制逻辑
    def send_navigation_goal(self, x, y, yaw):
        if not self.nav_action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("NavigateToPose action server not available!")
            self.nav_status = "failed"
            return False

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        self.latest_goal_id += 1
        goal_id = self.latest_goal_id
        self.nav_status = "navigating"
        self.get_logger().info(f"Sending navigation goal to Action Server (Goal ID: {goal_id}): x={x:.2f}, y={y:.2f}, yaw={yaw:.2f}")

        send_goal_future = self.nav_action_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(
            lambda fut, gid=goal_id: self.nav_goal_response_callback(fut, gid)
        )
        return True

    def nav_goal_response_callback(self, future, goal_id):
        # 如果当前有更新的导航请求被发送，直接忽略这个旧请求的响应
        if goal_id != self.latest_goal_id:
            self.get_logger().info(f"Goal response for an outdated request {goal_id} (latest is {self.latest_goal_id}). Ignoring.")
            return

        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().info("Navigation goal rejected by Action Server.")
            self.nav_status = "failed"
            return

        self.get_logger().info("Navigation goal accepted by Action Server.")
        self.current_nav_goal_handle = goal_handle

        # 监听结果
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(
            lambda fut, gid=goal_id, gh=goal_handle: self.nav_result_callback(fut, gid, gh)
        )

    def nav_result_callback(self, future, goal_id, goal_handle):
        # 仅处理最新的导航请求及对应的 goal_handle 的结果，防止旧请求的回调覆盖当前状态
        if goal_id != self.latest_goal_id or goal_handle != self.current_nav_goal_handle:
            self.get_logger().info(f"Received result for an inactive/superseded goal {goal_id}. Ignoring.")
            return

        result = future.result()
        status = result.status
        self.get_logger().info(f"Navigation completed with Action status code: {status} for Goal ID: {goal_id}")

        # ROS 2 Action 状态码定义: 
        # STATUS_SUCCEEDED = 4, STATUS_CANCELED = 5
        if status == 4:
            self.nav_status = "reached"
        elif status == 5:
            self.nav_status = "canceled"
        else:
            self.nav_status = "failed"

        self.current_nav_goal_handle = None

    def cancel_navigation_goal(self):
        if self.current_nav_goal_handle:
            self.get_logger().info("Canceling current active navigation goal...")
            self.current_nav_goal_handle.cancel_goal_async()
            return True
        return False


# 全局控制变量
ros_node = None
scheduler = None

# 子进程与地图路径管理
slam_process = None
explore_process = None
loc_process = None
nav2_process = None
sim_process = None
agent_process = None
MAPS_DIR = os.path.expanduser("~/rdkrobot_ws/maps")
current_map_name = None


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


def trigger_patrol_by_schedule():
    """定时任务触发的回调函数"""
    if ros_node:
        ros_node.get_logger().info("Scheduled event triggered! Starting patrol...")
        ros_node.publish_patrol_cmd("start")


# FastAPI 路由定义

@app.get("/api/v1/system/info")
def get_system_info():
    """获取系统架构信息，用于前端判断是否为嵌入式 ARM 主机以控制仿真界面展示"""
    machine = platform.machine().lower()
    is_arm = "arm" in machine or "aarch64" in machine
    return {
        "is_arm": is_arm,
        "machine": machine
    }

@app.get("/api/v1/robot/status")
def get_robot_status():
    """获取小车电池、位姿等实时状态以及下位机在线状态"""
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    
    # 动态检测下位机是否在线：3秒内收到过电池包或里程计包即视为在线
    current_time = time.time()
    mcu_online = (current_time - ros_node.last_battery_time < 3.0) or \
                 (current_time - ros_node.last_odom_time < 3.0)
                 
    return {
        "battery_percentage": round(ros_node.battery_pct, 1),
        "pose": ros_node.robot_pose,
        "is_localizing": ros_node.is_localizing,
        "nav_status": ros_node.nav_status,
        "mcu_online": mcu_online
    }

# Gazebo 仿真控制接口

@app.post("/api/v1/sim/start")
def start_gazebo_simulation():
    """启动 Gazebo 仿真"""
    global sim_process
    if sim_process and sim_process.poll() is None:
        return {"status": "success", "message": "Simulation is already running."}
        
    # 启动前强制清理残留的孤立 Gazebo 进程，防止端口/Master占用导致无法正常加载 GUI
    try:
        os.system("pkill -9 -f gzserver || true")
        os.system("pkill -9 -f gzclient || true")
        os.system("pkill -9 -f gazebo || true")
    except Exception as e:
        if ros_node:
            ros_node.get_logger().warn(f"Failed to clear old gazebo processes: {e}")
        
    cmd = [
        "bash", "-c",
        "source /opt/ros/humble/setup.bash && source /home/ranger/rdkrobot_ws/install/setup.bash && ros2 launch rdk_robot_bringup gazebo_bringup.launch.py"
    ]
    try:
        sim_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        return {"status": "success", "message": "Gazebo simulation started successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start Gazebo simulation: {e}")

@app.post("/api/v1/sim/stop")
def stop_gazebo_simulation():
    """停止 Gazebo 仿真"""
    global sim_process
    if not sim_process or sim_process.poll() is not None:
        return {"status": "success", "message": "Simulation is not running."}
        
    try:
        terminate_process_group(sim_process)
        sim_process = None
        return {"status": "success", "message": "Gazebo simulation stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop Gazebo simulation: {e}")


# micro-ROS 代理控制接口

@app.post("/api/v1/agent/start")
def start_microros_agent():
    """启动 micro-ROS 串口代理 (Docker)"""
    global agent_process
    # 检测是否已经在运行
    res = os.system("docker ps --filter name=microros_agent | grep microros_agent >/dev/null 2>&1")
    if res == 0:
        return {"status": "success", "message": "micro-ROS agent is already running."}
        
    # 强制清理重名的残留容器
    os.system("docker kill microros_agent >/dev/null 2>&1 || true")
    os.system("docker rm microros_agent >/dev/null 2>&1 || true")
    
    # 构建拉起串口代理的 Docker 命令，默认连接 /dev/ttyACM0
    cmd = [
        "docker", "run", "--name", "microros_agent", "--rm",
        "-v", "/dev:/dev", "--privileged",
        "microros/micro-ros-agent:humble",
        "serial", "--dev", "/dev/ttyACM0", "-b", "921600"
    ]
    try:
        agent_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        return {"status": "success", "message": "micro-ROS agent started successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start micro-ROS agent: {e}")

@app.post("/api/v1/agent/stop")
def stop_microros_agent():
    """停止 micro-ROS 串口代理"""
    global agent_process
    try:
        os.system("docker kill microros_agent >/dev/null 2>&1 || true")
        if agent_process:
            terminate_process_group(agent_process)
            agent_process = None
        return {"status": "success", "message": "micro-ROS agent stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop micro-ROS agent: {e}")

@app.get("/api/v1/agent/status")
def get_microros_agent_status():
    """获取 micro-ROS 代理的运行状态"""
    res = os.system("docker ps --filter name=microros_agent | grep microros_agent >/dev/null 2>&1")
    running = (res == 0)
    return {"running": running}


# 巡逻控制接口

@app.post("/api/v1/patrol/cmd")
def post_patrol_cmd(payload: CommandPayload):
    """发送巡逻控制指令"""
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    
    cmd_lower = payload.cmd.lower()
    if cmd_lower not in ["start", "pause", "stop", "resume"]:
        raise HTTPException(status_code=400, detail="Invalid command. Allowed: start, pause, stop, resume")
    
    ros_node.publish_patrol_cmd(cmd_lower)
    return {"status": "success", "command_sent": cmd_lower}

@app.post("/api/v1/patrol/task")
def post_patrol_task(payload: TaskPayload):
    """下发动态巡逻任务（即更新航点）"""
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    if not payload.waypoints:
        raise HTTPException(status_code=400, detail="Waypoint list cannot be empty")
    
    ros_node.publish_waypoints(payload.waypoints)
    return {"status": "success", "waypoints_count": len(payload.waypoints)}

# 定时巡逻管理接口

@app.post("/api/v1/patrol/schedule")
def add_patrol_schedule(payload: SchedulePayload):
    """添加定时巡逻任务"""
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")
    try:
        item = scheduler.add_schedule(payload.time, payload.repeat)
        return {"status": "success", "schedule": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/v1/patrol/schedules")
def get_patrol_schedules():
    """获取所有定时巡逻任务列表"""
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")
    return scheduler.get_schedules()

@app.delete("/api/v1/patrol/schedule/{schedule_id}")
def delete_patrol_schedule(schedule_id: str):
    """删除指定的定时巡逻任务"""
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")
    success = scheduler.delete_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Schedule with ID {schedule_id} not found")
    return {"status": "success", "deleted_id": schedule_id}

# 自动定位接口

@app.post("/api/v1/nav/auto-localize")
def trigger_auto_localize():
    """触发自动全局重定位"""
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    
    # 检查服务是否存在
    if not ros_node.localize_cli.service_is_ready():
        raise HTTPException(
            status_code=503, 
            detail="Auto localization service not available. Make sure auto_localize node is running."
        )
    
    req = Trigger.Request()
    # 异步调用服务以防阻塞 API
    future = ros_node.localize_cli.call_async(req)
    return {"status": "success", "message": "Trigger request sent to auto_localize node."}

@app.get("/api/v1/nav/auto-localize/status")
def get_auto_localize_status():
    """获取自动全局重定位的运行状态"""
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    return {
        "is_localizing": ros_node.is_localizing
    }


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


# Nav2 导航栈状态查询接口（仅供内部监控用，启停由 SLAM 联动控制）

@app.get("/api/v1/nav2/status")
def get_nav2_status():
    """获取 Nav2 导航栈运行状态"""
    running = (nav2_process is not None) and (nav2_process.poll() is None)
    return {"running": running}

# SLAM 建图控制接口

def _auto_start_nav2_after_delay(use_sim: bool, delay: float = 8.0):
    """后台线程：等待 SLAM 初始化后自动拉起 Nav2 导航栈"""
    global nav2_process
    time.sleep(delay)

    # 如果 SLAM 已经不在了（被用户手动停止），就不再启动
    if slam_process is None or slam_process.poll() is not None:
        if ros_node:
            ros_node.get_logger().info("Auto-Nav2: SLAM is no longer running. Skipping Nav2 auto-start.")
        return

    if nav2_process and nav2_process.poll() is None:
        if ros_node:
            ros_node.get_logger().info("Auto-Nav2: Nav2 is already running. Skip.")
        return

    sim_flag = "true" if use_sim else "false"
    try:
        bringup_share = get_package_share_directory('rdk_robot_bringup')
        params_file = os.path.join(
            bringup_share, 'config',
            'nav2_sim_params.yaml' if use_sim else 'nav2_params.yaml'
        )
    except Exception:
        params_file = (
            f"/home/ranger/rdkrobot_ws/install/rdk_robot_bringup/share/rdk_robot_bringup/config/"
            f"{'nav2_sim_params.yaml' if use_sim else 'nav2_params.yaml'}"
        )

    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source /home/ranger/rdkrobot_ws/install/setup.bash && "
        f"ros2 launch rdk_robot_bringup navigation.launch.py use_sim_time:={sim_flag} params_file:={params_file}"
    ]
    try:
        nav2_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        if ros_node:
            ros_node.get_logger().info(
                f"Auto-Nav2: Nav2 navigation stack started automatically (sim={sim_flag}, params={os.path.basename(params_file)})."
            )
    except Exception as e:
        if ros_node:
            ros_node.get_logger().error(f"Auto-Nav2: Failed to start Nav2: {e}")


@app.post("/api/v1/slam/start")
def start_slam_mapping():
    """启动 SLAM 建图"""
    global slam_process, loc_process
    
    # 1. 检查并确保定位节点（map_server/amcl）挂起，释放 /map 话题 and TF，防止冲突
    if loc_process and loc_process.poll() is None:
        ros_node.get_logger().info("SLAM requested. Pausing active localization nodes...")
        ros_node.change_localization_manager_state(1) # PAUSE

    # 2. 如果 SLAM 进程已经运行，直接返回
    if slam_process and slam_process.poll() is None:
        return {"status": "success", "message": "SLAM mapping is already running."}

    # 3. 仿真模式下，等待 /odom 话题就绪（最多等 12 秒）
    #    Gazebo 的 diff_drive 插件需要数秒才能完成初始化并发布 odom→base_footprint TF
    #    若 slam_toolbox 在 TF 链就绪之前启动，它会因获取不到变换而静默失败（只剩激光点云无地图）
    use_sim = check_use_sim_time(ros_node)
    if use_sim:
        ros_node.get_logger().info("Sim mode: waiting for /odom topic to be ready before starting SLAM...")
        odom_ready = False
        for _ in range(120):  # 最多等待 12 秒
            topic_names = [name for name, _ in ros_node.get_topic_names_and_types()]
            if "/odom" in topic_names and ros_node.last_odom_time > 0.0:
                odom_ready = True
                ros_node.get_logger().info("/odom is active. Proceeding to start SLAM.")
                break
            time.sleep(0.1)
        if not odom_ready:
            raise HTTPException(
                status_code=503,
                detail="Timeout waiting for /odom topic. Make sure Gazebo simulation is fully running before starting SLAM."
            )

    sim_flag = "true" if use_sim else "false"
    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source /home/ranger/rdkrobot_ws/install/setup.bash && ros2 launch rdk_robot_bringup slam.launch.py use_sim_time:={sim_flag}"
    ]
    try:
        slam_process = subprocess.Popen(cmd, preexec_fn=os.setsid)

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

@app.post("/api/v1/slam/stop")
def stop_slam_mapping():
    """停止 SLAM 建图（同时联动停止 Nav2 导航栈）"""
    global slam_process, nav2_process
    if not slam_process or slam_process.poll() is not None:
        return {"status": "success", "message": "SLAM mapping is not running."}

    try:
        ros_node.get_logger().info("Terminating slam_toolbox process group...")
        terminate_process_group(slam_process)
        slam_process = None

        # 联动停止 Nav2（SLAM 停了，/map 就没了，导航也没有意义继续运行）
        if nav2_process and nav2_process.poll() is None:
            ros_node.get_logger().info("Auto-stopping Nav2 navigation stack along with SLAM...")
            terminate_process_group(nav2_process)
            nav2_process = None

        return {"status": "success", "message": "SLAM mapping and Nav2 navigation stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop SLAM: {e}")

@app.get("/api/v1/slam/status")
def get_slam_mapping_status():
    """获取 SLAM 建图状态"""
    running = (slam_process is not None) and (slam_process.poll() is None)
    return {"running": running}

@app.post("/api/v1/slam/save")
def save_slam_map(payload: MapSavePayload):
    """保存当前 SLAM 地图"""
    if not os.path.exists(MAPS_DIR):
        os.makedirs(MAPS_DIR, exist_ok=True)
        
    output_path = os.path.join(MAPS_DIR, payload.map_name)
    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source /home/ranger/rdkrobot_ws/install/setup.bash && ros2 run nav2_map_server map_saver_cli -f {output_path}"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15.0)
        if res.returncode == 0:
            return {"status": "success", "message": f"Map successfully saved as '{payload.map_name}' in {MAPS_DIR}"}
        else:
            raise HTTPException(status_code=500, detail=f"map_saver_cli failed: {res.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout while saving map.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing map_saver_cli: {e}")

# 自主探索建图控制接口

@app.post("/api/v1/explore/start")
def start_autonomous_exploration():
    """启动自主探索建图"""
    global explore_process
    if explore_process and explore_process.poll() is None:
        return {"status": "success", "message": "Autonomous exploration is already running."}
    
    try:
        bringup_share = get_package_share_directory('rdk_robot_bringup')
        explore_config = os.path.join(bringup_share, 'config', 'explore.yaml')
    except Exception:
        explore_config = "/home/ranger/rdkrobot_ws/install/rdk_robot_bringup/share/rdk_robot_bringup/config/explore.yaml"

    cmd = [
        "bash", "-c",
        f"source /opt/ros/humble/setup.bash && source /home/ranger/rdkrobot_ws/install/setup.bash && ros2 run explore_lite explore --ros-args --params-file {explore_config}"
    ]
    try:
        explore_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        return {"status": "success", "message": "Autonomous exploration started successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start exploration: {e}")

@app.post("/api/v1/explore/stop")
def stop_autonomous_exploration():
    """停止自主探索建图"""
    global explore_process
    if not explore_process or explore_process.poll() is not None:
        return {"status": "success", "message": "Autonomous exploration is not running."}
    
    try:
        terminate_process_group(explore_process)
        explore_process = None
        return {"status": "success", "message": "Autonomous exploration stopped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop exploration: {e}")

@app.get("/api/v1/explore/status")
def get_autonomous_exploration_status():
    """获取自主探索运行状态"""
    running = (explore_process is not None) and (explore_process.poll() is None)
    return {"running": running}

# 地图文件与管理接口

@app.get("/api/v1/maps")
def list_saved_maps():
    """获取本地保存的所有地图列表"""
    global current_map_name
    if not os.path.exists(MAPS_DIR):
        return []
    maps = []
    for file in os.listdir(MAPS_DIR):
        if file.endswith(".yaml") and not file.endswith("_semantic.json"):
            map_name = file[:-5]
            yaml_path = os.path.join(MAPS_DIR, file)
            try:
                with open(yaml_path, 'r') as f:
                    data = yaml.safe_load(f)
                maps.append({
                    "name": map_name,
                    "image": data.get("image", ""),
                    "resolution": data.get("resolution", 0.0),
                    "origin": data.get("origin", []),
                    "created_at": datetime.fromtimestamp(os.path.getctime(yaml_path)).strftime("%Y-%m-%d %H:%M:%S")
                })
            except Exception:
                maps.append({
                    "name": map_name,
                    "created_at": datetime.fromtimestamp(os.path.getctime(yaml_path)).strftime("%Y-%m-%d %H:%M:%S")
                })
                
    # 辅助自动设定当前加载的地图名（若空则默认设为第一个）
    if current_map_name is None and maps:
        current_map_name = maps[0]["name"]
        
    return maps

@app.delete("/api/v1/maps/{map_name}")
def delete_saved_map(map_name: str):
    """从本地删除指定地图的所有文件 (.yaml + .pgm + 语义json)"""
    yaml_path = os.path.join(MAPS_DIR, f"{map_name}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(status_code=404, detail=f"Map '{map_name}' not found.")
        
    pgm_path = None
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        image_filename = data.get("image", f"{map_name}.pgm")
        if os.path.isabs(image_filename):
            pgm_path = image_filename
        else:
            pgm_path = os.path.join(MAPS_DIR, image_filename)
    except Exception:
        pgm_path = os.path.join(MAPS_DIR, f"{map_name}.pgm")
        
    poi_path = os.path.join(MAPS_DIR, f"{map_name}_semantic.json")
        
    try:
        os.remove(yaml_path)
        if pgm_path and os.path.exists(pgm_path):
            os.remove(pgm_path)
        if os.path.exists(poi_path):
            os.remove(poi_path)
        return {"status": "success", "message": f"Successfully deleted map '{map_name}' files."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete files: {e}")

@app.get("/api/v1/maps/{map_name}/image")
def get_map_image(map_name: str):
    """读取本地 PGM 格式地图，流式转换为 PNG 格式输出"""
    yaml_path = os.path.join(MAPS_DIR, f"{map_name}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(status_code=404, detail=f"Map '{map_name}' not found.")
        
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        image_filename = data.get("image", f"{map_name}.pgm")
        if os.path.isabs(image_filename):
            pgm_path = image_filename
        else:
            pgm_path = os.path.join(MAPS_DIR, image_filename)
    except Exception:
        pgm_path = os.path.join(MAPS_DIR, f"{map_name}.pgm")
        
    if not os.path.exists(pgm_path):
        raise HTTPException(status_code=404, detail="PGM image file not found.")
        
    # 使用 OpenCV 读取并压缩为 PNG 字节流输出
    img = cv2.imread(pgm_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(status_code=500, detail="Failed to load map PGM image.")
        
    success, encoded_img = cv2.imencode('.png', img)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode image to PNG.")
        
    return StreamingResponse(BytesIO(encoded_img.tobytes()), media_type="image/png")

@app.post("/api/v1/maps/{map_name}/load")
def load_map_into_navigation(map_name: str):
    """动态将指定地图载入 Nav2 导航系统"""
    global current_map_name, slam_process, loc_process
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
        
    yaml_path = os.path.join(MAPS_DIR, f"{map_name}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(status_code=404, detail=f"Map yaml {map_name}.yaml not found")
        
    # 1. 互斥安全检查：如果要加载静态地图定位导航，先关闭 SLAM 建图
    if slam_process and slam_process.poll() is None:
        ros_node.get_logger().info("Map loading requested. Terminating active SLAM process group...")
        terminate_process_group(slam_process)
        slam_process = None

    # 2. 检查并确保定位节点（map_server & amcl）已经启动
    if loc_process is None or loc_process.poll() is not None:
        ros_node.get_logger().info("Starting localization (map_server & amcl) process group...")
        use_sim = check_use_sim_time(ros_node)
        sim_flag = "true" if use_sim else "false"
        cmd = [
            "bash", "-c",
            f"source /opt/ros/humble/setup.bash && source /home/ranger/rdkrobot_ws/install/setup.bash && ros2 launch rdk_robot_bringup localization.launch.py use_sim_time:={sim_flag}"
        ]
        try:
            loc_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
            # 给服务 3 秒初始化时间，再尝试调用它的加载服务
            time.sleep(3.0)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start localization launch: {e}")
    else:
        # 如果定位进程已经在运行但处于挂起状态，恢复 map_server 和 amcl
        ros_node.get_logger().info("Localization process already running. Resuming map_server & amcl...")
        ros_node.change_localization_manager_state(2) # RESUME

    # 3. 检查服务是否就绪
    # 最多尝试等待 5 秒，直到服务可用
    service_ready = False
    for _ in range(50):
        if ros_node.load_map_cli.service_is_ready():
            service_ready = True
            break
        time.sleep(0.1)

    if not service_ready:
        raise HTTPException(
            status_code=503, 
            detail="Nav2 LoadMap service (/map_server/load_map) is not available. Ensure Nav2 Map Server is running."
        )
        
    req = LoadMap.Request()
    req.map_url = yaml_path
    
    future = ros_node.load_map_cli.call_async(req)
    
    # 阻塞等待结果
    start_time = time.time()
    timeout = 10.0
    while not future.done():
        time.sleep(0.1)
        if time.time() - start_time > timeout:
            raise HTTPException(status_code=504, detail="Timeout waiting for Nav2 map_server to load map")
            
    res = future.result()
    # 0 代表成功加载
    if res.result == 0:
        current_map_name = map_name  # 更新全局当前地图名
        return {"status": "success", "message": f"Successfully loaded map: {map_name}"}
    else:
        raise HTTPException(status_code=500, detail=f"Map server failed to load map, result code: {res.result}")

# 语义地图 (POI) 管理接口

@app.post("/api/v1/maps/{map_name}/pois")
def save_map_pois(map_name: str, pois: List[POIPayload]):
    """为指定地图保存/更新语义点列表"""
    if not os.path.exists(MAPS_DIR):
        os.makedirs(MAPS_DIR, exist_ok=True)
    poi_path = os.path.join(MAPS_DIR, f"{map_name}_semantic.json")
    try:
        # 转换为 dict 列表保存
        data = [p.dict() for p in pois]
        with open(poi_path, 'w') as f:
            json.dump(data, f, indent=4)
        return {"status": "success", "message": f"POIs saved successfully for map '{map_name}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write POI file: {e}")

@app.get("/api/v1/maps/{map_name}/pois", response_model=List[POIPayload])
def get_map_pois(map_name: str):
    """获取指定地图的全部语义点列表"""
    poi_path = os.path.join(MAPS_DIR, f"{map_name}_semantic.json")
    if not os.path.exists(poi_path):
        return []
    try:
        with open(poi_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read POI file: {e}")

# 通用导航与语义导航接口

@app.post("/api/v1/nav/go")
def navigate_to_target(payload: NavGoPayload):
    """控制小车进行导航（物理坐标导航 或 语义点导航）"""
    global current_map_name
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
        
    # 1. 检查是否为语义导航
    if payload.poi_name:
        if current_map_name is None:
            # 尝试自动读取已保存的地图
            maps = list_saved_maps()
            if maps:
                current_map_name = maps[0]["name"]
            else:
                raise HTTPException(
                    status_code=400, 
                    detail="No map loaded and no map files exist to resolve POI name. Load a map first."
                )
        
        poi_path = os.path.join(MAPS_DIR, f"{current_map_name}_semantic.json")
        if not os.path.exists(poi_path):
            raise HTTPException(
                status_code=404, 
                detail=f"No semantic POI files found for current map '{current_map_name}'. Add POIs first."
            )
            
        try:
            with open(poi_path, 'r') as f:
                pois = json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read POI file: {e}")
            
        target_poi = None
        for p in pois:
            if p["name"] == payload.poi_name:
                target_poi = p
                break
                
        if not target_poi:
            raise HTTPException(
                status_code=404, 
                detail=f"POI '{payload.poi_name}' not found in current map '{current_map_name}'"
            )
            
        target_x = target_poi["x"]
        target_y = target_poi["y"]
        target_yaw = target_poi["yaw"]
    else:
        # 物理坐标导航
        if payload.x is None or payload.y is None:
            raise HTTPException(
                status_code=400, 
                detail="Invalid request. Provide both 'x' and 'y' coordinates, or a valid 'poi_name'."
            )
        target_x = payload.x
        target_y = payload.y
        target_yaw = payload.yaw
        
    # 2. 触发 ROS 2 Action 客户端发送导航目标
    success = ros_node.send_navigation_goal(target_x, target_y, target_yaw)
    if not success:
        raise HTTPException(
            status_code=503,
            detail="Nav2 Action Server 'navigate_to_pose' is not available. Ensure Nav2 Navigation is running."
        )
    return {
        "status": "success", 
        "message": f"Navigation request sent. Target: x={target_x:.2f}, y={target_y:.2f}, yaw={target_yaw:.2f}"
    }

@app.post("/api/v1/nav/cancel")
def cancel_navigation():
    """中止当前的导航任务"""
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    canceled = ros_node.cancel_navigation_goal()
    if canceled:
        return {"status": "success", "message": "Navigation cancellation request sent."}
    else:
        return {"status": "success", "message": "No active navigation goal to cancel."}

@app.get("/api/v1/nav/status")
def get_navigation_status():
    """获取当前的导航状态"""
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    return {
        "status": ros_node.nav_status
    }


def ros2_thread_entry():
    global ros_node
    rclpy.init()
    ros_node = RobotApiNode()
    rclpy.spin(ros_node)
    ros_node.destroy_node()
    rclpy.shutdown()


def sigterm_handler(signum, frame):
    raise KeyboardInterrupt


def main():
    global scheduler
    
    # 注册 SIGTERM 信号处理器，确保收到 SIGTERM 时能运行 finally 块清理进程组
    signal.signal(signal.SIGTERM, sigterm_handler)
    
    # 1. 启动 ROS 2 守护子线程
    ros_thread = threading.Thread(target=ros2_thread_entry, daemon=True)
    ros_thread.start()
    
    # 2. 启动定时器调度器
    scheduler = PatrolScheduler(trigger_callback=trigger_patrol_by_schedule)
    scheduler.start()
    
    # 3. 运行 FastAPI Uvicorn 服务 (监听 0.0.0.0:8000)
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except KeyboardInterrupt:
        pass
    finally:
        if scheduler:
            scheduler.stop()
        # 退出时彻底清理所有可能残留的后台进程组，防止僵尸进程
        terminate_process_group(slam_process)
        terminate_process_group(explore_process)
        terminate_process_group(loc_process)
        terminate_process_group(nav2_process)
        terminate_process_group(sim_process)
        terminate_process_group(agent_process)
        os.system("docker kill microros_agent >/dev/null 2>&1 || true")


if __name__ == "__main__":
    main()
