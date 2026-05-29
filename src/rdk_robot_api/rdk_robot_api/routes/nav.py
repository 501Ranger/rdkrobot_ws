import os
import json
import math
import asyncio
from fastapi import APIRouter, HTTPException
from geometry_msgs.msg import Pose
from nav2_msgs.action import ComputePathToPose

from .. import ros_node as rn
from .. import config
from ..models import NavGoPayload, TaskPayload

router = APIRouter(prefix="/api/v1/nav", tags=["Navigation"])

# 辅助函数：通过 rclpy action 计算两点之间的路径
async def compute_path_segment(ros_node, start_pose, goal_pose) -> list:
    """
    使用 ComputePathToPose Action 规划 start_pose 到 goal_pose 的路径。
    start_pose: geometry_msgs/Pose，若为 None，则以当前机器人位姿作为起点 (use_start = False)
    goal_pose: geometry_msgs/Pose
    返回: 包含 {'x': ..., 'y': ...} 的点列表，如果失败则返回 None
    """
    if not ros_node.compute_path_client.wait_for_server(timeout_sec=2.0):
        ros_node.get_logger().warn("ComputePathToPose Action Server not available. Will fallback to straight line.")
        return None

    goal_msg = ComputePathToPose.Goal()
    goal_msg.pose.header.frame_id = 'map'
    goal_msg.pose.header.stamp = ros_node.get_clock().now().to_msg()
    goal_msg.pose.pose = goal_pose

    if start_pose is not None:
        goal_msg.use_start = True
        goal_msg.start.header.frame_id = 'map'
        goal_msg.start.header.stamp = ros_node.get_clock().now().to_msg()
        goal_msg.start.pose = start_pose
    else:
        goal_msg.use_start = False

    # 发送目标
    future = ros_node.compute_path_client.send_goal_async(goal_msg)
    
    # 异步非阻塞等待目标响应
    while not future.done():
        await asyncio.sleep(0.02)
        
    goal_handle = future.result()
    if not goal_handle.accepted:
        ros_node.get_logger().warn("ComputePathToPose Goal rejected by server.")
        return None

    # 异步非阻塞等待结果
    result_future = goal_handle.get_result_async()
    while not result_future.done():
        await asyncio.sleep(0.02)

    action_result = result_future.result()
    # status 4 为 SUCCEEDED
    if action_result.status == 4:
        path_msg = action_result.result.path
        points = []
        for pose_stamped in path_msg.poses:
            pos = pose_stamped.pose.position
            points.append({
                "x": round(pos.x, 3),
                "y": round(pos.y, 3)
            })
        return points
    else:
        ros_node.get_logger().warn(f"ComputePathToPose Action failed with status: {action_result.status}")
        return None

@router.post("/preview")
async def preview_patrol_path(payload: TaskPayload):
    """
    多点导航路径精细预览：
    计算机器人当前位置 -> 航点0 -> 航点1 -> ... 的真实避障规划路径并拼接返回。
    如果路径规划动作服务器不可用或规划失败，则优雅降级为以直线段连接的路径，保障系统坚韧度。
    """
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    if not payload.waypoints:
        return {"status": "success", "path": []}

    # 1. 转换航点列表为 ROS Pose 对象
    poses = []
    for wp in payload.waypoints:
        pose = Pose()
        pose.position.x = wp.x
        pose.position.y = wp.y
        pose.position.z = 0.0
        pose.orientation.z = math.sin(wp.yaw / 2.0)
        pose.orientation.w = math.cos(wp.yaw / 2.0)
        poses.append(pose)

    # 2. 提取当前机器人位姿作为首段起点
    curr_pose_dict = rn.ros_node.robot_pose
    curr_pose = Pose()
    curr_pose.position.x = curr_pose_dict["x"]
    curr_pose.position.y = curr_pose_dict["y"]
    curr_pose.position.z = 0.0
    curr_pose.orientation.z = math.sin(curr_pose_dict["yaw"] / 2.0)
    curr_pose.orientation.w = math.cos(curr_pose_dict["yaw"] / 2.0)

    # 3. 构造路径分段计算队列：当前位置 -> 0, 0 -> 1, 1 -> 2 ...
    segments = [(curr_pose, poses[0])]
    for i in range(len(poses) - 1):
        segments.append((poses[i], poses[i+1]))

    # 4. 依次计算各个段落的规划路径并拼接
    combined_path = []
    for start, goal in segments:
        segment_pts = await compute_path_segment(rn.ros_node, start, goal)
        if segment_pts:
            # 降采样，每段最多提取 50 个点以防返回路径点过多导致前端卡顿
            total_pts = len(segment_pts)
            max_points = max(10, 150 // len(segments))
            step = max(1, total_pts // max_points)
            sampled_pts = [segment_pts[j] for j in range(0, total_pts, step)]
            if total_pts > 0 and sampled_pts[-1] != segment_pts[-1]:
                sampled_pts.append(segment_pts[-1])
            combined_path.extend(sampled_pts)
        else:
            # ⚠️ 容错降级：规划失败时直接添加起点和终点，表现为折线直线段
            combined_path.append({"x": round(start.position.x, 3), "y": round(start.position.y, 3)})
            combined_path.append({"x": round(goal.position.x, 3), "y": round(goal.position.y, 3)})

    # 5. 去除相邻的重复点，优化前端 SVG 渲染效率
    filtered_path = []
    for pt in combined_path:
        if not filtered_path or filtered_path[-1] != pt:
            filtered_path.append(pt)

    return {"status": "success", "path": filtered_path}

@router.post("/auto-localize")
def trigger_auto_localize():
    """触发自动全局重定位"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    
    if not rn.ros_node.localize_cli.service_is_ready():
        raise HTTPException(
            status_code=503, 
            detail="Auto localization service not available. Make sure auto_localize node is running."
        )
    
    req = Trigger.Request()
    rn.ros_node.localize_cli.call_async(req)
    return {"status": "success", "message": "Trigger request sent to auto_localize node."}

@router.get("/auto-localize/status")
def get_auto_localize_status():
    """获取自动全局重定位的运行状态"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    return {
        "is_localizing": rn.ros_node.is_localizing
    }

@router.post("/go")
def navigate_to_target(payload: NavGoPayload):
    """控制小车进行导航（物理坐标导航 或 语义点导航）"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
        
    if payload.poi_name:
        if config.current_map_name is None:
            # 尝试拉取地图列表找默认值
            from .maps import get_saved_maps_list
            maps = get_saved_maps_list()
            if maps:
                config.current_map_name = maps[0]["name"]
            else:
                raise HTTPException(
                    status_code=400, 
                    detail="No map loaded and no map files exist to resolve POI. Load a map first."
                )
        
        poi_path = os.path.join(config.MAPS_DIR, f"{config.current_map_name}_semantic.json")
        if not os.path.exists(poi_path):
            raise HTTPException(
                status_code=404, 
                detail=f"No semantic POI files found for current map '{config.current_map_name}'."
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
                detail=f"POI '{payload.poi_name}' not found in current map '{config.current_map_name}'."
            )
            
        target_x = target_poi["x"]
        target_y = target_poi["y"]
        target_yaw = target_poi["yaw"]
    else:
        if payload.x is None or payload.y is None:
            raise HTTPException(
                status_code=400, 
                detail="Invalid request. Provide both 'x' and 'y' coordinates, or a valid 'poi_name'."
            )
        target_x = payload.x
        target_y = payload.y
        target_yaw = payload.yaw
        
    success = rn.ros_node.send_navigation_goal(target_x, target_y, target_yaw)
    if not success:
        raise HTTPException(
            status_code=503,
            detail="Nav2 Action Server 'navigate_to_pose' is not available. Ensure Nav2 is running."
        )
    return {
        "status": "success", 
        "message": f"Navigation request sent. Target: x={target_x:.2f}, y={target_y:.2f}, yaw={target_yaw:.2f}"
    }

@router.post("/cancel")
def cancel_navigation():
    """中止当前的导航任务"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    canceled = rn.ros_node.cancel_navigation_goal()
    if canceled:
        return {"status": "success", "message": "Navigation cancellation request sent."}
    else:
        return {"status": "success", "message": "No active navigation goal to cancel."}

@router.get("/status")
def get_navigation_status():
    """获取当前的导航状态"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    return {
        "status": rn.ros_node.nav_status
    }
