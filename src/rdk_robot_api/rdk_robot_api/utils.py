import os
import time

_docker_cache = {}
_docker_cache_time = 0.0

def check_docker_container(name: str) -> bool:
    """
    带有 1.5 秒防抖缓存的 Docker 容器运行状态检测
    """
    global _docker_cache, _docker_cache_time
    current_time = time.time()
    if current_time - _docker_cache_time < 1.5 and name in _docker_cache:
        return _docker_cache[name]
        
    res = os.system(f"docker ps --filter name={name} | grep {name} >/dev/null 2>&1")
    is_running = (res == 0)
    _docker_cache[name] = is_running
    _docker_cache_time = current_time
    return is_running
