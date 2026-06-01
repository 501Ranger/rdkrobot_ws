from pydantic import BaseModel, Field
from typing import List

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

class HardwareInitPayload(BaseModel):
    agent_port: str = Field(None, description="micro-ROS 串口号")
    lidar_port: str = Field(None, description="雷达驱动串口号")

class BluetoothConnectPayload(BaseModel):
    mac: str = Field(..., description="蓝牙设备的 MAC 地址")

