from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Task:
    id: int
    command: str
    log_path: str
    pid: Optional[int]
    pgid: Optional[int]
    status: str
    managed: bool
    created_at: str
    started_at: Optional[str]
    ended_at: Optional[str]
    cwd: str
