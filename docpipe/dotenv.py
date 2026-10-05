"""
dotenv.py – Populate os.environ from a `.env` file before anything reads it.

Config modules across docpipe capture their values at import time
(`LLM_API_KEY = os.environ.get(...)`). Whoever loads the .env therefore has to
win the race against the first such import — and an app that imports
docpipe.inference before its own config module loses it silently: the key is
simply "EMPTY" and the endpoint answers 401.

So the load happens in docpipe/__init__.py, which by definition runs before any
module under docpipe.

Only keys not already set are added, so an explicit environment variable — a
SLURM script's export, a systemd `Environment=` — always wins over the file.

Author: Felix Vossel
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# What a .env put into the environment, {name: (file, value)}, and the files
# read: `docpipe config` says where a value in effect comes from.
LOADED: dict = {}
FILES: list = []
# The names that say which one file to load.
NAMED = ("DOCPIPE_ENV_FILE", "INFERENCE_ENV_FILE")


def _read(p: Path) -> bool:
    """One file into os.environ; False if it cannot be read."""
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
            LOADED[key] = (str(p), val)
    FILES.append(p)
    return True


def unload(path: Path) -> None:
    """Take back what one file put into the environment: the names it set
    that still carry its value. The file can be read again afterwards."""
    where = str(path)
    for name, (file, value) in list(LOADED.items()):
        if file == where:
            if os.environ.get(name) == value:
                os.environ.pop(name, None)
            del LOADED[name]
    FILES[:] = [f for f in FILES if str(f) != where]


def load_dotenv(extra: Optional[Path] = None) -> Path | None:
    """Read the first readable candidate into os.environ; return which one.

    With `extra`, that one file, unless it is not there or was read before:
    a project's own .env, for a command run in one of its subdirectories.
    """
    if extra is not None:
        p = Path(extra)
        seen = {str(f.resolve()) for f in FILES}
        if p.is_file() and str(p.resolve()) not in seen and _read(p):
            return p
        return None
    candidates = [
        os.environ.get("DOCPIPE_ENV_FILE"),
        os.environ.get("INFERENCE_ENV_FILE"),
        ".env",
    ]
    for path in candidates:
        if not path:
            continue
        p = Path(path)
        if p.is_file() and _read(p):
            return p      # first readable .env wins
    return None
