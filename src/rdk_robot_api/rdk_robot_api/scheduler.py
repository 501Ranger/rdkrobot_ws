import os
import json
import uuid
import time
import threading
from datetime import datetime


class PatrolScheduler:
    def __init__(self, trigger_callback, logger=None):
        self.trigger_callback = trigger_callback
        self.logger = logger
        self.config_dir = os.path.expanduser("~/.rdk_robot")
        self.config_path = os.path.join(self.config_dir, "schedules.json")
        self.schedules = []
        self.lock = threading.Lock()
        self.is_running = False
        self.thread = None
        self.last_triggered = {}  # Map schedule_id -> last triggered date-hour-minute string

        # 加载已有的定时任务
        self.load_schedules()

    def log_info(self, msg):
        if self.logger:
            self.logger.info(f"[Scheduler] {msg}")
        else:
            print(f"[Scheduler] INFO: {msg}")

    def log_error(self, msg):
        if self.logger:
            self.logger.error(f"[Scheduler] {msg}")
        else:
            print(f"[Scheduler] ERROR: {msg}")

    def load_schedules(self):
        with self.lock:
            if not os.path.exists(self.config_path):
                self.schedules = []
                return
            try:
                with open(self.config_path, 'r') as f:
                    self.schedules = json.load(f)
                self.log_info(f"Loaded {len(self.schedules)} schedules from {self.config_path}")
            except Exception as e:
                self.log_error(f"Failed to load schedules: {e}")
                self.schedules = []

    def save_schedules(self):
        with self.lock:
            try:
                os.makedirs(self.config_dir, exist_ok=True)
                with open(self.config_path, 'w') as f:
                    json.dump(self.schedules, f, indent=4)
                self.log_info(f"Saved schedules to {self.config_path}")
            except Exception as e:
                self.log_error(f"Failed to save schedules: {e}")

    def add_schedule(self, time_str, repeat="daily"):
        """
        time_str: "HH:MM" 格式，例如 "18:00"
        repeat: 目前只支持 "daily" (每天)
        """
        # 简单验证时间格式
        try:
            parts = time_str.split(":")
            if len(parts) != 2:
                raise ValueError()
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h < 24 and 0 <= m < 60):
                raise ValueError()
        except Exception:
            raise ValueError("Time must be in 'HH:MM' format, e.g., '14:30'")

        item = {
            "id": str(uuid.uuid4())[:8],
            "time": time_str,
            "repeat": repeat,
            "enabled": True
        }
        with self.lock:
            self.schedules.append(item)
        self.save_schedules()
        return item

    def get_schedules(self):
        with self.lock:
            return list(self.schedules)

    def delete_schedule(self, schedule_id):
        success = False
        with self.lock:
            initial_count = len(self.schedules)
            self.schedules = [s for s in self.schedules if s["id"] != schedule_id]
            if len(self.schedules) < initial_count:
                success = True
        if success:
            self.save_schedules()
        return success

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.log_info("Scheduler background thread started.")

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.log_info("Scheduler background thread stopped.")

    def _run_loop(self):
        while self.is_running:
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")
            current_day_key = now.strftime("%Y-%m-%d-%H-%M")

            # 遍历所有任务
            with self.lock:
                for s in self.schedules:
                    if not s["enabled"]:
                        continue

                    # 判断时间是否吻合且这一分钟内没触发过
                    if s["time"] == current_time_str:
                        last_trig = self.last_triggered.get(s["id"])
                        if last_trig != current_day_key:
                            self.log_info(f"Triggering scheduled patrol for task {s['id']} at {s['time']}")
                            # 执行回调触发巡逻
                            try:
                                self.trigger_callback()
                                self.last_triggered[s["id"]] = current_day_key
                            except Exception as e:
                                self.log_error(f"Callback execution failed: {e}")

            # 每隔 10 秒检查一次即可，避免高频循环消耗 CPU
            time.sleep(10)
