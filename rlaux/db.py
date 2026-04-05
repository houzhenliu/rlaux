from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from .config import DB_PATH, ensure_home
from .models import Task


VALID_STATUSES = {"running", "stopped", "exited", "unknown"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    ensure_home()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                log_path TEXT NOT NULL,
                pid INTEGER,
                pgid INTEGER,
                status TEXT NOT NULL,
                managed INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                cwd TEXT NOT NULL
            )
            """
        )


def row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        command=row["command"],
        log_path=row["log_path"],
        pid=row["pid"],
        pgid=row["pgid"],
        status=row["status"],
        managed=bool(row["managed"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        cwd=row["cwd"],
    )


def create_task(command: str, log_path: str, cwd: str) -> int:
    init_db()
    now = utc_now()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (command, log_path, status, managed, created_at, cwd)
            VALUES (?, ?, 'unknown', 1, ?, ?)
            """,
            (command, log_path, now, cwd),
        )
        return int(cur.lastrowid)


def mark_task_started(task_id: int, pid: int, pgid: int) -> None:
    now = utc_now()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET pid = ?, pgid = ?, status = 'running', started_at = ?
            WHERE id = ?
            """,
            (pid, pgid, now, task_id),
        )


def mark_task_status(task_id: int, status: str, ended: bool = False) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    ended_at = utc_now() if ended else None
    with get_conn() as conn:
        if ended:
            conn.execute(
                "UPDATE tasks SET status = ?, ended_at = ? WHERE id = ?",
                (status, ended_at, task_id),
            )
        else:
            conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))


def get_task(task_id: int) -> Optional[Task]:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return row_to_task(row) if row else None


def list_tasks() -> List[Task]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
        return [row_to_task(row) for row in rows]


def list_managed_pids() -> dict[int, int]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, pid FROM tasks WHERE managed = 1 AND pid IS NOT NULL"
        ).fetchall()
    out: dict[int, int] = {}
    for row in rows:
        out[int(row["pid"])] = int(row["id"])
    return out
