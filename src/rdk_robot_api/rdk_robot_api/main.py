import threading
import uvicorn
import os
import subprocess
import time
import math
import yaml
import cv2
import json
from io import BytesIO
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
from nav2_msgs.srv import LoadMap
from nav2_msgs.action import NavigateToPose
from ament_index_python.packages import get_package_share_directory

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
        self.nav_status = "idle"  # "idle", "navigating", "reached", "failed", "canceled"

    def battery_callback(self, msg: BatteryState):
        self.battery_pct = msg.percentage * 100.0 if msg.percentage <= 1.0 else msg.percentage

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

    def localize_status_callback(self, msg: Bool):
        self.is_localizing = msg.data

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

        self.nav_status = "navigating"
        self.get_logger().info(f"Sending navigation goal to Action Server: x={x:.2f}, y={y:.2f}, yaw={yaw:.2f}")

        send_goal_future = self.nav_action_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(self.nav_goal_response_callback)
        return True

    def nav_goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().info("Navigation goal rejected by Action Server.")
            self.nav_status = "failed"
            return

        self.get_logger().info("Navigation goal accepted by Action Server.")
        self.current_nav_goal_handle = goal_handle

        # 监听结果
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(self.nav_result_callback)

    def nav_result_callback(self, future):
        result = future.result()
        status = result.status
        self.get_logger().info(f"Navigation completed with Action status code: {status}")

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
MAPS_DIR = os.path.expanduser("~/rdkrobot_ws/maps")
current_map_name = None


def trigger_patrol_by_schedule():
    """定时任务触发的回调函数"""
    if ros_node:
        ros_node.get_logger().info("Scheduled event triggered! Starting patrol...")
        ros_node.publish_patrol_cmd("start")


# FastAPI 路由定义

@app.get("/api/v1/robot/status")
def get_robot_status():
    """获取小车电池、位姿等实时状态"""
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    return {
        "battery_percentage": round(ros_node.battery_pct, 1),
        "pose": ros_node.robot_pose,
        "is_localizing": ros_node.is_localizing,
        "nav_status": ros_node.nav_status
    }

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

# SLAM 建图控制接口

@app.post("/api/v1/slam/start")
def start_slam_mapping():
    """启动 SLAM 建图"""
    global slam_process
    if slam_process and slam_process.poll() is None:
        return {"status": "success", "message": "SLAM mapping is already running."}
    
    cmd = [
        "bash", "-c",
        "source /opt/ros/humble/setup.bash && source /home/ranger/rdkrobot_ws/install/setup.bash && ros2 launch rdk_robot_bringup slam.launch.py"
    ]
    try:
        slam_process = subprocess.Popen(cmd)
        return {"status": "success", "message": "SLAM mapping node started successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start SLAM: {e}")

@app.post("/api/v1/slam/stop")
def stop_slam_mapping():
    """停止 SLAM 建图"""
    global slam_process
    if not slam_process or slam_process.poll() is not None:
        return {"status": "success", "message": "SLAM mapping is not running."}
    
    try:
        slam_process.terminate()
        try:
            slam_process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            slam_process.kill()
        slam_process = None
        return {"status": "success", "message": "SLAM mapping node stopped successfully."}
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
        explore_process = subprocess.Popen(cmd)
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
        explore_process.terminate()
        try:
            explore_process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            explore_process.kill()
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
    global current_map_name
    if not ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
        
    yaml_path = os.path.join(MAPS_DIR, f"{map_name}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(status_code=404, detail=f"Map yaml {map_name}.yaml not found")
        
    if not ros_node.load_map_cli.service_is_ready():
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


def main():
    global scheduler
    
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


if __name__ == "__main__":
    main()
