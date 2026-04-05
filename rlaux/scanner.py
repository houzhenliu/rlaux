from __future__ import annotations

import subprocess
from typing import Any

import psutil

from .db import list_managed_pids

HIGH_CONF_KEYWORDS = ("train", "main.py", "ppo", "sac", "rl", "dqn", "a2c")


def _query_gpu_memory_map() -> dict[int, int]:
    # Optional enhancement; failure should not block core flow.
    cmd = [
        "nvidia-smi",
        "--query-compute-apps=pid,used_memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=1.5)
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}

    out: dict[int, int] = {}
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            used_mem = int(parts[1])
        except ValueError:
            continue
        out[pid] = used_mem
    return out


def scan_python_processes() -> list[dict[str, Any]]:
    managed_pids = list_managed_pids()
    gpu_mem_by_pid = _query_gpu_memory_map()

    results: list[dict[str, Any]] = []
    for proc in psutil.process_iter(attrs=["pid", "name", "cmdline", "create_time"]):
        try:
            info = proc.info
            pid = int(info.get("pid") or 0)
            name = (info.get("name") or "").lower()
            cmdline_list = info.get("cmdline") or []
            cmdline = " ".join(cmdline_list)
            cmdline_lower = cmdline.lower()

            looks_python = "python" in name or "python" in cmdline_lower
            has_script = any(part.endswith(".py") for part in cmdline_list)
            if not (looks_python and has_script):
                continue

            confidence = "high" if any(k in cmdline_lower for k in HIGH_CONF_KEYWORDS) else "normal"
            task_id = managed_pids.get(pid)
            results.append(
                {
                    "pid": pid,
                    "cmdline": cmdline,
                    "create_time": info.get("create_time"),
                    "managed": task_id is not None,
                    "task_id": task_id,
                    "confidence": confidence,
                    "gpu_mem_mb": gpu_mem_by_pid.get(pid),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    results.sort(key=lambda x: int(x["pid"]))
    return results
