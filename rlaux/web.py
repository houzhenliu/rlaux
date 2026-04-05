from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import DEFAULT_HOST, DEFAULT_PORT
from .db import get_task, list_tasks
from .log_utils import tail_lines
from .models import Task
from .runner import RunnerError, refresh_task_states, stop_task
from .scanner import scan_python_processes

ACTIVE_STATUSES = {"running", "unknown"}


def _active_tasks(tasks: list[Task]) -> list[Task]:
    return [task for task in tasks if task.status in ACTIVE_STATUSES]


def create_app() -> FastAPI:
    app = FastAPI(title="rlaux dashboard")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @app.get("/")
    def index(request: Request):
        refresh_task_states()
        tasks = _active_tasks(list_tasks())
        detected = scan_python_processes()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "tasks": tasks,
                "detected": detected,
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
