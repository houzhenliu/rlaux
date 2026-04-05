from __future__ import annotations

from pathlib import Path
from typing import List

import typer

from .config import DEFAULT_HOST, DEFAULT_PORT
from .db import list_tasks
from .runner import RunnerError, refresh_task_states, run_task, stop_task
from .web import run_dashboard

app = typer.Typer(help="Local RL training task manager")


def _shorten_cmd(cmd: str, limit: int = 64) -> str:
    if len(cmd) <= limit:
        return cmd
    return cmd[: limit - 3] + "..."


@app.command("run")
def run(
    log: str = typer.Option(..., "--log", help="Log file path"),
    command: List[str] = typer.Argument(..., help="Command after --"),
) -> None:
    """Start a task in background."""
    try:
        result = run_task(command=command, log_path=log)
    except RunnerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"task_id={result['task_id']}")
    typer.echo(f"pid={result['pid']}")
    typer.echo(f"pgid={result['pgid']}")
    typer.echo(f"log_path={result['log_path']}")


@app.command("list")
def list_cmd() -> None:
    """List managed tasks."""
    refresh_task_states()
    tasks = list_tasks()
    if not tasks:
        typer.echo("No tasks found.")
        return

    typer.echo("ID\tPID\tSTATUS\tMANAGED\tSTARTED_AT\tLOG\tCMD")
    for t in tasks:
        started = t.started_at or t.created_at
        typer.echo(
            f"{t.id}\t{t.pid or '-'}\t{t.status}\t{int(t.managed)}\t{started}\t"
            f"{Path(t.log_path).name}\t{_shorten_cmd(t.command)}"
        )


@app.command("stop")
def stop(task_id: int = typer.Argument(..., help="Task ID")) -> None:
    """Stop a managed task by id."""
    try:
        outcome = stop_task(task_id)
    except RunnerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"task_id={task_id}")
    typer.echo(f"result={outcome}")


@app.command("dashboard")
def dashboard(
    host: str = typer.Option(DEFAULT_HOST, "--host", help="Bind host"),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="Bind port"),
) -> None:
    """Run local dashboard web server."""
    typer.echo(f"Dashboard: http://{host}:{port}")
    try:
        run_dashboard(host=host, port=port)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
