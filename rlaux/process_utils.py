from __future__ import annotations

import os
import signal
import time


def is_pid_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def terminate_process_group(
    pgid: int | None,
    fallback_pid: int | None = None,
    term_timeout_sec: float = 3.0,
) -> str:
    if pgid and pgid > 0:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return "already-exited"

        deadline = time.time() + term_timeout_sec
        while time.time() < deadline:
            if fallback_pid and not is_pid_running(fallback_pid):
                return "terminated"
            time.sleep(0.2)

        try:
            os.killpg(pgid, signal.SIGKILL)
            return "killed"
        except ProcessLookupError:
            return "terminated"

    if fallback_pid and is_pid_running(fallback_pid):
        try:
            os.kill(fallback_pid, signal.SIGTERM)
            return "terminated"
        except ProcessLookupError:
            return "already-exited"

    return "already-exited"
