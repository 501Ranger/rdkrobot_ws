import os
import yaml
from ament_index_python.packages import get_package_share_directory

# 寻找并确定静态文件目录的路径
try:
    share_dir = get_package_share_directory('rdk_robot_api')
    static_dir = os.path.join(share_dir, 'static')
except Exception:
    # 备用本地开发路径
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))

# 加载统一配置 robot_params.yaml
robot_config = {}
try:
    api_share = get_package_share_directory('rdk_robot_api')
    config_path = os.path.join(api_share, 'config', 'robot_params.yaml')
except Exception:
    config_path = "/home/ranger/rdkrobot_ws/src/rdk_robot_api/config/robot_params.yaml"

if os.path.exists(config_path):
    try:
        with open(config_path, 'r') as f:
            robot_config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading robot_params.yaml: {e}")

MAPS_DIR = os.path.expanduser("~/rdkrobot_ws/maps")
current_map_name = None
