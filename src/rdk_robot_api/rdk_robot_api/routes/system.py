import platform
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/system", tags=["System"])

@router.get("/info")
def get_system_info():
    """获取系统架构信息，用于前端判断是否为嵌入式 ARM 主机以控制仿真界面展示"""
    machine = platform.machine().lower()
    is_arm = "arm" in machine or "aarch64" in machine
    return {
        "is_arm": is_arm,
        "machine": machine
    }
