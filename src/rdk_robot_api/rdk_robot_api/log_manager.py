import os
import json
import uuid
import threading
from datetime import datetime

LOGS_DIR = os.path.expanduser("~/.rdk_robot")
LOGS_FILE = os.path.join(LOGS_DIR, "navigation_logs.json")
_lock = threading.Lock()

class LogManager:
    @staticmethod
    def _ensure_logs_file():
        if not os.path.exists(LOGS_DIR):
            os.makedirs(LOGS_DIR, exist_ok=True)
        if not os.path.exists(LOGS_FILE):
            try:
                with open(LOGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump([], f)
            except Exception as e:
                print(f"[LogManager] Failed to initialize log file: {e}")

    @staticmethod
    def add_log(log_type: str, status: str, duration: float, distance: float, start_pose: dict, end_pose: dict) -> dict:
        """
        添加一条新的导航或巡逻任务日志
        """
        LogManager._ensure_logs_file()
        
        new_log = {
            "id": str(uuid.uuid4()),
            "type": log_type,  # "single" (单点导航) or "patrol" (多点巡逻)
            "status": status,  # "reached" (到达), "canceled" (取消), "failed" (失败)
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": round(duration, 1),
            "distance": round(distance, 2),
            "start_pose": start_pose,
            "end_pose": end_pose
        }

        with _lock:
            try:
                if os.path.exists(LOGS_FILE):
                    with open(LOGS_FILE, 'r', encoding='utf-8') as f:
                        logs = json.load(f)
                else:
                    logs = []
            except Exception:
                logs = []
                
            # 最新记录放在最前面
            logs.insert(0, new_log)
            
            # 最大记录 300 条
            if len(logs) > 300:
                logs = logs[:300]
                
            try:
                with open(LOGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(logs, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[LogManager] Failed to write logs: {e}")
                
        return new_log

    @staticmethod
    def get_logs() -> list:
        LogManager._ensure_logs_file()
        with _lock:
            try:
                if os.path.exists(LOGS_FILE):
                    with open(LOGS_FILE, 'r', encoding='utf-8') as f:
                        return json.load(f)
            except Exception:
                pass
            return []

    @staticmethod
    def delete_log(log_id: str) -> bool:
        LogManager._ensure_logs_file()
        with _lock:
            try:
                if os.path.exists(LOGS_FILE):
                    with open(LOGS_FILE, 'r', encoding='utf-8') as f:
                        logs = json.load(f)
                else:
                    return False
                
                initial_len = len(logs)
                logs = [log for log in logs if log.get("id") != log_id]
                
                if len(logs) < initial_len:
                    with open(LOGS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(logs, f, indent=4, ensure_ascii=False)
                    return True
            except Exception as e:
                print(f"[LogManager] Failed to delete log {log_id}: {e}")
            return False

    @staticmethod
    def clear_logs() -> bool:
        LogManager._ensure_logs_file()
        with _lock:
            try:
                with open(LOGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump([], f)
                return True
            except Exception as e:
                print(f"[LogManager] Failed to clear logs: {e}")
            return False
