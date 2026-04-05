from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Sequence

from .config import ensure_home
from .db import create_task, get_task, list_tasks, mark_task_started, mark_task_status
from .process_utils import is_pid_running, terminate_process_group


class RunnerError(RuntimeError):
    pass


def _resolve_log_path(log_path: str, cwd: str) -> Path:
    raw = Path(log_path)
    out = raw if raw.is_absolute() else Path(cwd) / raw
    out.parent.mkdir(parents=True, exist_ok=True)
    return out.resolve()


def run_task(command: Sequence[str], log_path: str, cwd: str | None = None) -> dict[str, str | int]:
    ensure_home()
    cmd = [part for part in command if part is not None]
    if not cmd:
        raise RunnerError("command is empty; use: rlaux run --log <file> -- <command>")

    task_cwd = str(Path(cwd or os.getcwd()).resolve())
    log_abs = _resolve_log_path(log_path, task_cwd)

    try:
        log_fh = open(log_abs, "ab", buffering=0)
    except OSError as exc:
        raise RunnerError(f"cannot write log file: {log_abs} ({exc})") from exc

    task_id = create_task(command=shlex.join(cmd), log_path=str(log_abs), cwd=task_cwd)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=task_cwd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as exc:
        mark_task_status(task_id, "unknown")
        raise RunnerError(f"failed to start command: {exc}") from exc
    finally:
        log_fh.close()

    pgid = os.getpgid(proc.pid)
    mark_task_started(task_id, proc.pid, pgid)

    return {
        "task_id": task_id,
        "pid": proc.pid,
        "pgid": pgid,
        "log_path": str(log_abs),
    }


def refresh_task_states() -> None:
    for task in list_tasks():
        if task.status != "running":
            continue
        if not is_pid_running(task.pid):
            mark_task_status(task.id, "exited", ended=True)


def stop_task(task_id: int) -> str:
    task = get_task(task_id)
    if task is None:
        raise RunnerError(f"task id not found: {task_id}")
    if not task.managed:
        raise RunnerError(f"task {task_id} is unmanaged and cannot be stopped")

    if not is_pid_running(task.pid):
        mark_task_status(task_id, "exited", ended=True)
        return "already-exited"

    result = terminate_process_group(task.pgid, fallback_pid=task.pid)
    mark_task_status(task_id, "stopped", ended=True)
    return result
