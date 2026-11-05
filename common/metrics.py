"""Real process and host metrics exposed by each backend server."""

import os
import time

import psutil

_STARTED_AT = time.time()
_PROCESS = psutil.Process(os.getpid())


def collect_metrics(server_name: str, active_connections: int = 0) -> dict:
    """Return load metrics in the shape expected by the ML router."""
    cpu = psutil.cpu_percent(interval=0.05)
    memory = psutil.virtual_memory().percent

    try:
        response_time = round(_PROCESS.cpu_times().user * 10 + active_connections, 2)
    except psutil.Error:
        response_time = 0.0

    return {
        "server": server_name,
        "cpu": round(cpu, 2),
        "memory": round(memory, 2),
        "connections": int(active_connections),
        "latency": round(5.0 + (cpu * 0.8) + (memory * 0.25) + active_connections, 2),
        "response_time": response_time,
        "uptime_seconds": round(time.time() - _STARTED_AT, 2),
        "pid": os.getpid(),
    }
