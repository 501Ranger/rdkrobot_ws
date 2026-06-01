import platform
import os
import glob
import psutil
import subprocess
import re
from fastapi import APIRouter
from ..models import BluetoothConnectPayload

router = APIRouter(prefix="/api/v1/system", tags=["System"])

@router.get("/info")
def get_system_info():
    """获取系统架构信息，用于前端判断是否为嵌入式 ARM 主机并展示具体型号"""
    machine = platform.machine().lower()
    is_arm = "arm" in machine or "aarch64" in machine
    
    device_model = "Unknown Device"
    if is_arm:
        try:
            if os.path.exists("/proc/device-tree/model"):
                with open("/proc/device-tree/model", "r") as f:
                    device_model = f.read().strip().replace("\x00", "")
            else:
                device_model = "Embedded ARM Device"
        except Exception:
            device_model = "Embedded ARM Device"
    else:
        device_model = f"PC ({platform.processor() or platform.system()})"
        
    return {
        "is_arm": is_arm,
        "machine": machine,
        "hardware_platform": device_model
    }

@router.get("/status")
def get_system_status():
    """获取系统 CPU、内存占用率及内核温度，用于 HMI 实时看板展示"""
    cpu_usage = psutil.cpu_percent(interval=None)
    mem_usage = psutil.virtual_memory().percent
    
    cpu_temp = 0.0
    try:
        if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_str = f.read().strip()
                temp_val = float(temp_str)
                if temp_val > 1000:
                    temp_val /= 1000.0
                cpu_temp = round(temp_val, 1)
        elif hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            found = False
            for name, entries in temps.items():
                for entry in entries:
                    if entry.current > 0:
                        cpu_temp = round(entry.current, 1)
                        found = True
                        break
                if found:
                    break
    except Exception:
        pass
        
    return {
        "cpu": cpu_usage,
        "memory": mem_usage,
        "temperature": cpu_temp
    }

@router.get("/serial-ports")
def get_serial_ports():
    """获取当前上位机系统中可用的 ttyACM* 和 ttyUSB* 串口列表，方便一键选择"""
    try:
        ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
        ports.sort()
        return {"ports": ports}
    except Exception as e:
        return {"ports": [], "error": str(e)}

@router.post("/bluetooth/scan")
def scan_bluetooth_devices():
    """对附近蓝牙设备进行 4 秒扫描，并返回去重新鲜扫描到的含有 Xbox 的设备列表"""
    try:
        # 4 秒扫描附近的设备以更新蓝牙列表缓存
        subprocess.run(["bluetoothctl", "--timeout", "4", "scan", "on"], capture_output=True, timeout=6)
        
        # 读取发现的设备列表
        res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True)
        devices = []
        seen_macs = set()
        for line in res.stdout.strip().split("\n"):
            parts = line.split(" ", 2)
            if len(parts) >= 3 and parts[0] == "Device":
                mac = parts[1]
                name = parts[2]
                # 对 MAC 去重，并且筛选包含 Xbox/xbox 字符的设备名
                if mac not in seen_macs and "xbox" in name.lower():
                    seen_macs.add(mac)
                    devices.append({
                        "mac": mac,
                        "name": name
                    })
        return {"status": "success", "devices": devices}
    except Exception as e:
        return {"status": "error", "message": str(e), "devices": []}


@router.post("/bluetooth/connect")
def connect_bluetooth_device(payload: BluetoothConnectPayload):
    """信任并连接手柄（开启信任以支持以后手柄开机时自动回连）"""
    mac = payload.mac.strip()
    if not re.match(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", mac):
        return {"status": "error", "message": "无效的 MAC 地址格式"}
    
    try:
        # 1. 设为信任 (trust) 用于自动重连
        subprocess.run(["bluetoothctl", "trust", mac], capture_output=True)
        
        # 2. 进行配对 (pair)
        subprocess.run(["bluetoothctl", "pair", mac], timeout=12, capture_output=True)
        
        # 3. 进行连接 (connect)
        conn_res = subprocess.run(["bluetoothctl", "connect", mac], timeout=12, capture_output=True, text=True)
        
        # 双重检验连接状态
        info_res = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True)
        if "Connected: yes" in info_res.stdout or "Connection successful" in conn_res.stdout:
            return {"status": "success", "message": "已配对成功并标记为信任，后续手柄开机将自动回连主机！"}
        else:
            return {"status": "error", "message": f"连接手柄超时，请确保手柄已开启配对闪烁模式。详情: {conn_res.stdout.strip()}"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "连接超时，请确认手柄开启配对模式并靠近机器人主机"}
    except Exception as e:
        return {"status": "error", "message": f"连接出错: {str(e)}"}

@router.post("/bluetooth/disconnect")
def disconnect_bluetooth_device(payload: BluetoothConnectPayload):
    """断开已连接设备并清除配对/信任"""
    mac = payload.mac.strip()
    try:
        subprocess.run(["bluetoothctl", "disconnect", mac], capture_output=True)
        # 清除配对和信任，防止产生冲突或遗留无用绑定
        subprocess.run(["bluetoothctl", "untrust", mac], capture_output=True)
        subprocess.run(["bluetoothctl", "remove", mac], capture_output=True)
        return {"status": "success", "message": "已成功断开连接并清除了配对记录与自动回连信任。"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/bluetooth/status")
def get_bluetooth_status():
    """获取当前主机连接的手柄状态以及设备名称"""
    try:
        # 直接获取活跃的连接详情
        res = subprocess.run(["bluetoothctl", "info"], capture_output=True, text=True)
        if "Connected: yes" in res.stdout:
            mac_match = re.search(r"Device\s+([0-9A-Fa-f:]{17})", res.stdout)
            name_match = re.search(r"Name:\s+(.*)", res.stdout)
            mac = mac_match.group(1) if mac_match else ""
            name = name_match.group(1) if name_match else "Xbox Wireless Controller"
            return {"connected": True, "mac": mac, "name": name}
        
        # 兜底查询已配对的设备列表看其中有没有被激活的
        paired_res = subprocess.run(["bluetoothctl", "paired-devices"], capture_output=True, text=True)
        for line in paired_res.stdout.strip().split("\n"):
            parts = line.split(" ", 2)
            if len(parts) >= 3 and parts[0] == "Device":
                mac = parts[1]
                name = parts[2]
                info = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True)
                if "Connected: yes" in info.stdout:
                    return {"connected": True, "mac": mac, "name": name}
                    
        return {"connected": False, "mac": "", "name": ""}
    except Exception as e:
        return {"connected": False, "mac": "", "name": "", "error": str(e)}

