from fastapi import APIRouter, HTTPException
from .. import ros_node as rn
from ..models import CommandPayload, TaskPayload, SchedulePayload

router = APIRouter(prefix="/api/v1/patrol", tags=["Patrol"])

# 由 main.py 启动时动态注入
scheduler = None

@router.post("/cmd")
def post_patrol_cmd(payload: CommandPayload):
    """发送巡逻控制指令"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    
    cmd_lower = payload.cmd.lower()
    if cmd_lower not in ["start", "start_once", "pause", "stop", "resume"]:
        raise HTTPException(status_code=400, detail="Invalid command. Allowed: start, start_once, pause, stop, resume")
    
    rn.ros_node.publish_patrol_cmd(cmd_lower)
    return {"status": "success", "command_sent": cmd_lower}

@router.post("/task")
def post_patrol_task(payload: TaskPayload):
    """下发动态巡逻任务（即更新航点）"""
    if not rn.ros_node:
        raise HTTPException(status_code=503, detail="ROS 2 node not initialized")
    if not payload.waypoints:
        raise HTTPException(status_code=400, detail="Waypoint list cannot be empty")
    
    rn.ros_node.publish_waypoints(payload.waypoints)
    return {"status": "success", "waypoints_count": len(payload.waypoints)}

@router.post("/schedule")
def add_patrol_schedule(payload: SchedulePayload):
    """添加定时巡逻任务"""
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")
    try:
        item = scheduler.add_schedule(payload.time, payload.repeat)
        return {"status": "success", "schedule": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/schedules")
def get_patrol_schedules():
    """获取所有定时巡逻任务列表"""
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")
    return scheduler.get_schedules()

@router.delete("/schedule/{schedule_id}")
def delete_patrol_schedule(schedule_id: str):
    """删除指定的定时巡逻任务"""
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not running")
    success = scheduler.delete_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Schedule with ID {schedule_id} not found")
    return {"status": "success", "deleted_id": schedule_id}
