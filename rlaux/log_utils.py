from __future__ import annotations

from collections import deque
from pathlib import Path


def tail_lines(path: str, lines: int = 100) -> str:
    p = Path(path)
    if not p.exists():
        return f"[log not found] {path}"
    if lines < 1:
        lines = 1
    if lines > 2000:
        lines = 2000

    buf: deque[str] = deque(maxlen=lines)
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            buf.append(line)
    return "".join(buf)
