from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import psutil
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import DEFAULT_HOST, DEFAULT_PORT
from .db import get_task, list_tasks
from .log_utils import tail_lines
from .models import Task
from .runner import RunnerError, refresh_task_states, stop_task
from .scanner import query_gpu_stats_by_pid, scan_python_processes

ACTIVE_STATUSES = {"running", "unknown"}


def _active_tasks(tasks: list[Task]) -> list[Task]:
    return [task for task in tasks if task.status in ACTIVE_STATUSES]


def _collect_option_values(args: list[str], start_idx: int) -> tuple[str, int]:
    values: list[str] = []
    i = start_idx
    while i < len(args) and not args[i].startswith("-"):
        values.append(args[i])
        i += 1

    if not values:
        return "true", start_idx
    if len(values) == 1:
        return values[0], i
    return " ".join(values), i


def _parse_command_params(command: str) -> list[tuple[str, str]]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return [("raw", command)]

    if len(tokens) <= 1:
        return []

    args = tokens[1:]
    rows: list[tuple[str, str]] = []
    pos_idx = 0
    i = 0

    while i < len(args):
        tok = args[i]

        if tok.startswith("--") and len(tok) > 2:
            if "=" in tok:
                name, value = tok.split("=", 1)
                rows.append((name, value))
                i += 1
                continue

            value, next_i = _collect_option_values(args, i + 1)
            rows.append((tok, value))
            i = next_i
            continue

        if tok.startswith("-") and len(tok) > 1:
            value, next_i = _collect_option_values(args, i + 1)
            rows.append((tok, value))
            i = next_i
            continue

        pos_idx += 1
        rows.append((f"arg{pos_idx}", tok))
        i += 1

    return rows


def _build_task_params(tasks: list[Task]) -> dict[int, list[tuple[str, str]]]:
    return {task.id: _parse_command_params(task.command) for task in tasks}


def _collect_process_tree_pids(root_pid: int) -> set[int]:
    out = {root_pid}
    try:
        proc = psutil.Process(root_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return out

    try:
        for child in proc.children(recursive=True):
            out.add(int(child.pid))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

    return out


def _build_managed_gpu_stats(
    tasks: list[Task],
    gpu_stats_by_pid: dict[int, dict[str, int | None]],
) -> dict[int, dict[str, int | None]]:
    out: dict[int, dict[str, int | None]] = {}
    for task in tasks:
        if not task.pid:
            continue

        pids = _collect_process_tree_pids(int(task.pid))
        mem_total = 0
        has_mem = False

        util_task_share_total = 0
        has_share = False
        util_by_gpu_device: dict[int, int] = {}
        util_fallback_max: int | None = None

        for pid in pids:
            stats = gpu_stats_by_pid.get(pid)
            if not stats:
                continue

            mem = stats.get("gpu_mem_mb")
            if mem is not None and mem > 0:
                mem_total += int(mem)
                has_mem = True

            util_split = stats.get("gpu_util_pct")
            util_device = stats.get("gpu_util_pct_device")
            gpu_idx = stats.get("gpu_index")

            if util_split is not None:
                util_task_share_total += int(util_split)
                has_share = True
            elif util_device is not None and gpu_idx is not None:
                util_by_gpu_device[int(gpu_idx)] = int(util_device)
            elif util_device is not None:
                util_fallback_max = (
                    int(util_device)
                    if util_fallback_max is None
                    else max(util_fallback_max, int(util_device))
                )

        if has_share:
            util_total: int | None = util_task_share_total
        elif util_by_gpu_device:
            util_total = sum(util_by_gpu_device.values())
        else:
            util_total = util_fallback_max

        out[task.id] = {
            "gpu_mem_mb": mem_total if has_mem else None,
            "gpu_util_pct": util_total,
        }

    return out


def _build_gpu_overview(
    managed_gpu_stats: dict[int, dict[str, int | None]],
    detected: list[dict[str, Any]],
) -> dict[str, int]:
    managed_pct = 0
    for stats in managed_gpu_stats.values():
        util = stats.get("gpu_util_pct")
        if util is not None:
            managed_pct += max(0, int(util))

    unmanaged_pct = 0
    for proc in detected:
        if bool(proc.get("managed")):
            continue
        util = proc.get("gpu_util_pct")
        if util is not None:
            unmanaged_pct += max(0, int(util))

    total = managed_pct + unmanaged_pct
    if total > 100:
        overflow = total - 100
        unmanaged_pct = max(0, unmanaged_pct - overflow)
        total = managed_pct + unmanaged_pct
        if total > 100:
            managed_pct = max(0, 100 - unmanaged_pct)
            total = managed_pct + unmanaged_pct

    idle_pct = max(0, 100 - total)
    return {
        "managed_pct": managed_pct,
        "unmanaged_pct": unmanaged_pct,
        "idle_pct": idle_pct,
        "total_pct": min(100, managed_pct + unmanaged_pct),
    }


def create_app() -> FastAPI:
    app = FastAPI(title="rlaux dashboard")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @app.get("/")
    def index(request: Request):
        refresh_task_states()
        tasks = _active_tasks(list_tasks())
        task_params = _build_task_params(tasks)

        show_all_raw = request.query_params.get("show_all", "0")
        show_all = show_all_raw in {"1", "true", "True"}
        gpu_stats_by_pid = query_gpu_stats_by_pid()
        detected = scan_python_processes(include_all=show_all, gpu_stats_by_pid=gpu_stats_by_pid)
        managed_gpu_stats = _build_managed_gpu_stats(tasks, gpu_stats_by_pid)
        gpu_overview = _build_gpu_overview(managed_gpu_stats, detected)

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "tasks": tasks,
                "task_params": task_params,
                "detected": detected,
                "managed_gpu_stats": managed_gpu_stats,
                "gpu_overview": gpu_overview,
                "show_all": show_all,
            },
        )

    @app.post("/tasks/{task_id}/stop")
    def stop(task_id: int):
        try:
            stop_task(task_id)
        except RunnerError:
            pass
        return RedirectResponse(url="/", status_code=303)

    @app.get("/tasks/{task_id}/log", response_class=PlainTextResponse)
    def logs(task_id: int, lines: int = 100):
        task = get_task(task_id)
        if task is None:
            return PlainTextResponse(f"task id not found: {task_id}", status_code=404)
        return PlainTextResponse(tail_lines(task.log_path, lines=lines))

    return app


def run_dashboard(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    app = create_app()
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except OSError as exc:
        raise RuntimeError(f"failed to start dashboard at http://{host}:{port}: {exc}") from exc
