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


def load_dotenv() -> Path | None:
    """Read the first readable candidate into os.environ; return which one."""
    candidates = [
        os.environ.get("DOCPIPE_ENV_FILE"),
        os.environ.get("INFERENCE_ENV_FILE"),
        ".env",
    ]
    for path in candidates:
        if not path:
            continue
        p = Path(path)
        if not p.is_file():
            continue
        try:
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except OSError:
            continue
        return p          # first readable .env wins
    return None
