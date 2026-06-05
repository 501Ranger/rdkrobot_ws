import os
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import ros_node as rn

router = APIRouter(prefix="/api/v1/voice", tags=["Voice"])

# Request Payload Models
class TTSPayload(BaseModel):
    text: str

class CommandPayload(BaseModel):
    text: str

class SourceEventPayload(BaseModel):
    angle: float
    confidence: float = 1.0

class RecordPayload(BaseModel):
    name: str

class PlacePayload(BaseModel):
    name: str
    x: float
    y: float
    yaw: float

def get_places_file_path() -> str:
    # 1. Try workspace source path first
    src_path = "/home/linrain/rdkrobot_ws/src/rdk_voice_assistant/config/places.yaml"
    if os.path.exists(src_path):
        return src_path

    # 2. Try ROS 2 install package share path
    try:
        import ament_index_python.packages
        pkg_share = ament_index_python.packages.get_package_share_directory('rdk_voice_assistant')
        share_path = os.path.join(pkg_share, 'config', 'places.yaml')
        if os.path.exists(share_path):
            return share_path
    except Exception:
        pass

    # 3. Fallback
    return src_path

@router.post("/tts")
def trigger_voice_tts(payload: TTSPayload):
    """向 TTS 语音播报话题发布文本"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    try:
        rn.ros_node.publish_voice_reply(payload.text)
        return {"status": "success", "message": f"Successfully published TTS text: '{payload.text}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish TTS text: {e}")

@router.post("/command/inject")
def inject_voice_command(payload: CommandPayload):
    """模拟注入语音指令"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    try:
        rn.ros_node.publish_voice_api_command(payload.text)
        return {"status": "success", "message": f"Successfully injected voice command: '{payload.text}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to inject command: {e}")

@router.post("/source_event/simulate")
def simulate_source_event(payload: SourceEventPayload):
    """模拟声源定位角度事件"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    try:
        rn.ros_node.publish_voice_source_sim(payload.angle, payload.confidence)
        return {"status": "success", "message": f"Successfully simulated source event: angle={payload.angle}, confidence={payload.confidence}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to simulate source event: {e}")

@router.post("/record")
def trigger_voice_record(payload: RecordPayload):
    """触发当前位置打点记录"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    try:
        rn.ros_node.publish_voice_record_cmd(payload.name)
        return {"status": "success", "message": f"Triggered voice record command for name: '{payload.name}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger record command: {e}")

@router.get("/places")
def get_voice_places():
    """获取所有已保存地点"""
    path = get_places_file_path()
    if not os.path.exists(path):
        return {"places": {}}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read places: {e}")

@router.post("/places")
def add_voice_place(payload: PlacePayload):
    """手动配置/修改指定地点的绝对坐标"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    try:
        rn.ros_node.publish_voice_record_cmd(payload.name, payload.x, payload.y, payload.yaw)
        return {"status": "success", "message": f"Sent coordinate save command for '{payload.name}' to voice node"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send coordinate save command: {e}")
