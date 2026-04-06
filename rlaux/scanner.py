from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import psutil

from .db import list_managed_pids

HIGH_CONF_KEYWORDS = (
    "train",
    "trainer",
    "main.py",
    "ppo",
    "sac",
    "rl",
    "dqn",
    "a2c",
    "ddp",
    "deepspeed",
    "torchrun",
    "accelerate",
)

SKIP_STATUSES = {
    psutil.STATUS_ZOMBIE,
    psutil.STATUS_DEAD,
}

_GPU_STATS_CACHE_TS = 0.0
_GPU_STATS_CACHE: dict[int, dict[str, int | None]] = {}


def _query_compute_apps() -> dict[int, dict[str, Any]]:
    cmd = [
        "nvidia-smi",
        "--query-compute-apps=pid,gpu_uuid,used_memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=1.5)
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}

    out: dict[int, dict[str, Any]] = {}
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        pid_raw, gpu_uuid, mem_raw = parts[0], parts[1], parts[2]
        try:
            pid = int(pid_raw)
            mem_mb = int(mem_raw)
        except ValueError:
            continue
        if pid <= 0:
            continue
        out[pid] = {
            "gpu_uuid": gpu_uuid or None,
            "gpu_mem_mb": mem_mb,
        }
    return out


def _query_gpu_devices() -> tuple[dict[str, int], dict[str, int]]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=uuid,index,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=1.5)
    except Exception:
        return {}, {}
    if proc.returncode != 0:
        return {}, {}

    util_by_uuid: dict[str, int] = {}
    index_by_uuid: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        uuid_raw, idx_raw, util_raw = parts[0], parts[1], parts[2]
        try:
            idx = int(idx_raw)
            util = int(util_raw)
        except ValueError:
            continue
        if not uuid_raw or idx < 0 or util < 0:
            continue
        index_by_uuid[uuid_raw] = idx
        util_by_uuid[uuid_raw] = util

    return util_by_uuid, index_by_uuid


def query_gpu_stats_by_pid() -> dict[int, dict[str, int | None]]:
    global _GPU_STATS_CACHE_TS
    global _GPU_STATS_CACHE

    now = time.time()
    cache_ttl_sec = 1.0
    if now - _GPU_STATS_CACHE_TS <= cache_ttl_sec:
        return dict(_GPU_STATS_CACHE)

    apps = _query_compute_apps()
    util_by_uuid, index_by_uuid = _query_gpu_devices()

    pids_by_gpu: dict[str, list[int]] = {}
    for pid, app in apps.items():
        gpu_uuid = app.get("gpu_uuid")
        if not gpu_uuid:
            continue
        pids_by_gpu.setdefault(gpu_uuid, []).append(pid)

    out: dict[int, dict[str, int | None]] = {}
    for pid, app in apps.items():
        gpu_uuid = app.get("gpu_uuid")
        mem_mb = app.get("gpu_mem_mb")

        gpu_util_device: int | None = None
        gpu_util_split: int | None = None
        gpu_index: int | None = None

        if gpu_uuid:
            gpu_util_device = util_by_uuid.get(gpu_uuid)
            gpu_index = index_by_uuid.get(gpu_uuid)
            if gpu_util_device is not None:
                group_size = len(pids_by_gpu.get(gpu_uuid, []))
                if group_size > 0:
                    gpu_util_split = int(round(gpu_util_device / group_size))
                else:
                    gpu_util_split = gpu_util_device

        out[pid] = {
            "gpu_mem_mb": int(mem_mb) if mem_mb is not None else None,
            "gpu_util_pct": gpu_util_split,
            "gpu_util_pct_device": gpu_util_device,
            "gpu_index": gpu_index,
        }

    _GPU_STATS_CACHE = out
    _GPU_STATS_CACHE_TS = time.time()
    return dict(out)


def _looks_pythonish(name: str, cmdline_lower: str) -> bool:
    return (
        "python" in name
        or "python" in cmdline_lower
        or "py" in name
        or " py" in f" {cmdline_lower}"
    )


def scan_python_processes(
    include_all: bool = False,
    gpu_stats_by_pid: dict[int, dict[str, int | None]] | None = None,
) -> list[dict[str, Any]]:
    managed_pids = list_managed_pids()
    if gpu_stats_by_pid is None:
        gpu_stats_by_pid = query_gpu_stats_by_pid()
    self_pid = os.getpid()

    candidates: list[dict[str, Any]] = []
    for proc in psutil.process_iter(
        attrs=["pid", "ppid", "name", "cmdline", "create_time", "status"]
    ):
        try:
            info = proc.info
            pid = int(info.get("pid") or 0)
            if pid <= 0 or pid == self_pid:
                continue
            ppid = int(info.get("ppid") or 0)

            status = info.get("status")
            if status in SKIP_STATUSES:
                continue

            if pid in managed_pids:
                continue

            name = (info.get("name") or "").lower()
            cmdline_list = info.get("cmdline") or []
            cmdline = " ".join(cmdline_list).strip()
            cmdline_lower = cmdline.lower()

            if not _looks_pythonish(name, cmdline_lower):
                continue

            confidence = "high" if any(k in cmdline_lower for k in HIGH_CONF_KEYWORDS) else "normal"
            if not include_all and confidence != "high":
                continue

            if not cmdline:
                if include_all:
                    cmdline = "[cmdline unavailable]"
                else:
                    continue

            if "rlaux dashboard" in cmdline_lower:
                continue

            gpu_stats = gpu_stats_by_pid.get(pid, {})
            gpu_mem_mb = gpu_stats.get("gpu_mem_mb")
            if gpu_mem_mb is None or gpu_mem_mb <= 0:
                continue

            candidates.append(
                {
                    "pid": pid,
                    "ppid": ppid,
                    "cmdline": cmdline,
                    "create_time": info.get("create_time"),
                    "managed": False,
                    "task_id": None,
                    "confidence": confidence,
                    "gpu_mem_mb": gpu_mem_mb,
                    "gpu_util_pct": gpu_stats.get("gpu_util_pct"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    candidate_pids = {int(item["pid"]) for item in candidates}
    results: list[dict[str, Any]] = []
    for item in candidates:
        if int(item.get("ppid") or 0) in candidate_pids:
            continue
        item.pop("ppid", None)
        results.append(item)

    results.sort(key=lambda x: int(x["pid"]))
    return results
