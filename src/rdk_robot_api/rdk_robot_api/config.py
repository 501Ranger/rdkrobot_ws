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

# 动态寻找 install/setup.bash 路径
WORKSPACE_SETUP_BASH = None
try:
    share_dir = get_package_share_directory('rdk_robot_api')
    # share_dir 通常为: [workspace]/install/rdk_robot_api/share/rdk_robot_api
    # 向上三级到 [workspace]/install
    install_dir = os.path.dirname(os.path.dirname(os.path.dirname(share_dir)))
    setup_path = os.path.join(install_dir, 'setup.bash')
    if os.path.exists(setup_path):
        WORKSPACE_SETUP_BASH = setup_path
except Exception:
    pass

if not WORKSPACE_SETUP_BASH:
    # __file__ 为 [workspace]/src/rdk_robot_api/rdk_robot_api/config.py
    # 向上三级到 [workspace]
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    setup_path = os.path.abspath(os.path.join(src_dir, 'install', 'setup.bash'))
    if os.path.exists(setup_path):
        WORKSPACE_SETUP_BASH = setup_path

if not WORKSPACE_SETUP_BASH:
    setup_path = os.path.expanduser("~/rdkrobot_ws/install/setup.bash")
    if os.path.exists(setup_path):
        WORKSPACE_SETUP_BASH = setup_path

if not WORKSPACE_SETUP_BASH:
    for user in ["linrain", "ranger"]:
        path = f"/home/{user}/rdkrobot_ws/install/setup.bash"
        if os.path.exists(path):
            WORKSPACE_SETUP_BASH = path
            break

if not WORKSPACE_SETUP_BASH:
    WORKSPACE_SETUP_BASH = "/home/linrain/rdkrobot_ws/install/setup.bash"

# 加载统一配置 robot_params.yaml
robot_config = {}
try:
    api_share = get_package_share_directory('rdk_robot_api')
    config_path = os.path.join(api_share, 'config', 'robot_params.yaml')
except Exception:
    # 备用本地开发路径
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_path = os.path.join(src_dir, 'src', 'rdk_robot_api', 'config', 'robot_params.yaml')
    if not os.path.exists(config_path):
        for user in ["linrain", "ranger"]:
            path = f"/home/{user}/rdkrobot_ws/src/rdk_robot_api/config/robot_params.yaml"
            if os.path.exists(path):
                config_path = path
                break
    if not os.path.exists(config_path):
        config_path = "/home/linrain/rdkrobot_ws/src/rdk_robot_api/config/robot_params.yaml"

if os.path.exists(config_path):
    try:
        with open(config_path, 'r') as f:
            robot_config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading robot_params.yaml: {e}")

# 动态寻找地图保存路径 (支持自定义工作空间名称)
workspace_dir = os.path.dirname(os.path.dirname(WORKSPACE_SETUP_BASH))
MAPS_DIR = os.path.join(workspace_dir, "maps")
current_map_name = None
CONFIG_PATH = config_path

__version__ = "3.0.0"
