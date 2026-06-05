import os
import yaml
import cv2
import json
import time
import subprocess
from io import BytesIO
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from nav2_msgs.srv import LoadMap

from .. import ros_node as rn
from .. import manager as m
from .. import config
from ..models import POIPayload
from ..utils import check_docker_container
import asyncio

router = APIRouter(prefix="/api/v1/maps", tags=["Maps"])

def get_saved_maps_list() -> list:
    """获取本地保存的所有地图列表的底层函数，供 nav 路由联动使用"""
    if not os.path.exists(config.MAPS_DIR):
        return []
    maps = []
    for file in os.listdir(config.MAPS_DIR):
        if file.endswith(".yaml") and not file.endswith("_semantic.json"):
            map_name = file[:-5]
            yaml_path = os.path.join(config.MAPS_DIR, file)
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
    if config.current_map_name is None and maps:
        config.current_map_name = maps[0]["name"]
        
    return maps

@router.get("")
def list_saved_maps():
    """获取本地保存的所有地图列表"""
    return get_saved_maps_list()

@router.delete("/{map_name}")
def delete_saved_map(map_name: str):
    """从本地删除指定地图的所有文件 (.yaml + .pgm + 语义json)"""
    yaml_path = os.path.join(config.MAPS_DIR, f"{map_name}.yaml")
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
            pgm_path = os.path.join(config.MAPS_DIR, image_filename)
    except Exception:
        pgm_path = os.path.join(config.MAPS_DIR, f"{map_name}.pgm")
        
    poi_path = os.path.join(config.MAPS_DIR, f"{map_name}_semantic.json")
        
    try:
        os.remove(yaml_path)
        if pgm_path and os.path.exists(pgm_path):
            os.remove(pgm_path)
        if os.path.exists(poi_path):
            os.remove(poi_path)
        return {"status": "success", "message": f"Successfully deleted map '{map_name}' files."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete files: {e}")

@router.get("/{map_name}/image")
def get_map_image(map_name: str):
    """读取本地 PGM 格式地图，流式转换为 PNG 格式输出"""
    yaml_path = os.path.join(config.MAPS_DIR, f"{map_name}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(status_code=404, detail=f"Map '{map_name}' not found.")
        
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        image_filename = data.get("image", f"{map_name}.pgm")
        if os.path.isabs(image_filename):
            pgm_path = image_filename
        else:
            pgm_path = os.path.join(config.MAPS_DIR, image_filename)
    except Exception:
        pgm_path = os.path.join(config.MAPS_DIR, f"{map_name}.pgm")
        
    if not os.path.exists(pgm_path):
        raise HTTPException(status_code=404, detail="PGM image file not found.")
        
    img = cv2.imread(pgm_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(status_code=500, detail="Failed to load map PGM image.")
        
    success, encoded_img = cv2.imencode('.png', img)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode image to PNG.")
        
    return StreamingResponse(BytesIO(encoded_img.tobytes()), media_type="image/png")

@router.post("/{map_name}/load")
async def load_map_into_navigation(map_name: str):
    """动态将指定地图载入 Nav2 导航系统"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
        
    yaml_path = os.path.join(config.MAPS_DIR, f"{map_name}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(status_code=404, detail=f"Map yaml {map_name}.yaml not found")
        
    # 1. 互斥安全检查：先关闭 SLAM 建图
    if m.slam_process and m.slam_process.poll() is None:
        rn.ros_node.get_logger().info("Map loading requested. Terminating active SLAM process group...")
        m.terminate_process_group(m.slam_process)
        m.slam_process = None

    # 2. 检查并确保定位节点已启动
    if m.loc_process is None or m.loc_process.poll() is not None:
        rn.ros_node.get_logger().info("Starting localization (map_server & amcl) process group...")
        # 借用 slam.py 中的 check_use_sim_time 函数
        from .slam import check_use_sim_time
        use_sim = check_use_sim_time(rn.ros_node)
        sim_flag = "true" if use_sim else "false"
        cmd = [
            "bash", "-c",
            f"source /opt/ros/humble/setup.bash && source {config.WORKSPACE_SETUP_BASH} && ros2 launch rdk_robot_bringup localization.launch.py use_sim_time:={sim_flag}"
        ]
        try:
            m.loc_process = subprocess.Popen(cmd, preexec_fn=os.setsid)
            await asyncio.sleep(3.0)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start localization launch: {e}")
    else:
        # 恢复 map_server 和 amcl
        rn.ros_node.get_logger().info("Localization process already running. Resuming map_server & amcl...")
        rn.ros_node.change_localization_manager_state(2) # RESUME

    # 3. 检查服务是否就绪
    service_ready = False
    for _ in range(50):
        if rn.ros_node.load_map_cli.service_is_ready():
            service_ready = True
            break
        await asyncio.sleep(0.1)

    if not service_ready:
        raise HTTPException(
            status_code=503, 
            detail="Nav2 LoadMap service (/map_server/load_map) is not available. Ensure Nav2 Map Server is running."
        )
        
    req = LoadMap.Request()
    req.map_url = yaml_path
    
    future = rn.ros_node.load_map_cli.call_async(req)
    
    # 阻塞等待结果
    start_time = time.time()
    timeout = 10.0
    while not future.done():
        await asyncio.sleep(0.1)
        if time.time() - start_time > timeout:
            raise HTTPException(status_code=544, detail="Timeout waiting for Nav2 map_server to load map")
            
    res = future.result()
    if res.result == 0:
        config.current_map_name = map_name  # 更新全局当前地图名
        
        # 地图加载成功后，自动向 AMCL 发布初始位姿 (0, 0, 0)
        # 这使 AMCL 立即开始发布 map->odom TF，解除 costmap 的 "map frame not exist" 报错
        # 实际场景中用户应随后使用"一键全局重定位"来获得精确定位
        await asyncio.sleep(1.5)  # 等待 AMCL 节点完成激活
        rn.ros_node.publish_initial_pose(x=0.0, y=0.0, yaw=0.0)
        rn.ros_node.get_logger().info(
            f"Map '{map_name}' loaded. Auto-published initial pose (0,0,0) to bootstrap AMCL TF."
        )
        
        return {"status": "success", "message": f"Successfully loaded map: {map_name}"}
    else:
        raise HTTPException(status_code=500, detail=f"Map server failed to load map, result code: {res.result}")

@router.post("/{map_name}/pois")
def save_map_pois(map_name: str, pois: List[POIPayload]):
    """为指定地图保存/更新语义点列表"""
    if not os.path.exists(config.MAPS_DIR):
        os.makedirs(config.MAPS_DIR, exist_ok=True)
    poi_path = os.path.join(config.MAPS_DIR, f"{map_name}_semantic.json")
    try:
        # dict 保存
        data = [p.dict() for p in pois]
        with open(poi_path, 'w') as f:
            json.dump(data, f, indent=4)
        return {"status": "success", "message": f"POIs saved successfully for map '{map_name}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write POI file: {e}")

@router.get("/{map_name}/pois", response_model=List[POIPayload])
def get_map_pois(map_name: str):
    """获取指定地图的全部语义点列表"""
    poi_path = os.path.join(config.MAPS_DIR, f"{map_name}_semantic.json")
    if not os.path.exists(poi_path):
        return []
    try:
        with open(poi_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read POI file: {e}")

class MapEditPayload(BaseModel):
    image_base64: str

@router.post("/{map_name}/edit")
def edit_map_file(map_name: str, payload: MapEditPayload):
    """接收前端 Canvas 涂鸦后的 RGBA 图像，转换为 ROS 8位单通道 PGM 灰度图，并覆盖写入原地图文件"""
    import base64
    import numpy as np
    import cv2
    
    # 1. 提取 PGM 物理路径
    yaml_path = os.path.join(config.MAPS_DIR, f"{map_name}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(status_code=404, detail=f"Map '{map_name}' not found.")
        
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        image_filename = data.get("image", f"{map_name}.pgm")
        if os.path.isabs(image_filename):
            pgm_path = image_filename
        else:
            pgm_path = os.path.join(config.MAPS_DIR, image_filename)
    except Exception:
        pgm_path = os.path.join(config.MAPS_DIR, f"{map_name}.pgm")
        
    # 2. 解码 Base64 图像
    try:
        base64_data = payload.image_base64
        if "," in base64_data:
            base64_data = base64_data.split(",", 1)[1]
        img_data = base64.b64decode(base64_data)
        nparr = np.frombuffer(img_data, np.uint8)
        img_rgba = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {e}")
        
    if img_rgba is None:
        raise HTTPException(status_code=400, detail="Failed to decode image data")
        
    # 3. 将 RGBA/RGB 转换为单通道 PGM 灰度图 (未知区域=205, 空闲区=254, 障碍物=0)
    try:
        height, width = img_rgba.shape[:2]
        gray_img = np.ones((height, width), dtype=np.uint8) * 205  # 默认 205 (未知)
        
        if img_rgba.shape[2] == 4:
            # 提取通道
            r, g, b, a = cv2.split(img_rgba)
            # 灰度转换
            gray_val = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)
            
            # 判定规则：凡是 alpha >= 50 的作为已知区域
            known_mask = a >= 50
            free_mask = known_mask & (gray_val > 127)
            occ_mask = known_mask & (gray_val <= 127)
            
            gray_img[free_mask] = 254
            gray_img[occ_mask] = 0
        else:
            gray_val = cv2.cvtColor(img_rgba, cv2.COLOR_BGR2GRAY)
            gray_img[gray_val > 127] = 254
            gray_img[gray_val <= 127] = 0
            
        # 4. 覆盖原图
        cv2.imwrite(pgm_path, gray_img)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process and save PGM map: {e}")
        
    # 5. 自动重载该地图到导航中
    return load_map_into_navigation(map_name)
