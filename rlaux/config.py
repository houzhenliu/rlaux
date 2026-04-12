from __future__ import annotations

import os
from pathlib import Path

RLAUX_HOME = Path(os.environ.get("RLAUX_HOME", "~/.rlaux")).expanduser()
DB_PATH = RLAUX_HOME / "rlaux.db"
LOG_DIR = RLAUX_HOME / "logs"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 17878


def ensure_home() -> None:
    RLAUX_HOME.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
