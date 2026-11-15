"""
_revision.py: The commit this code is.

`git archive` writes the commit into `REVISION` (`export-subst` in
.gitattributes), so code laid over an image from an archive knows which
commit it is, whatever the archive or the image is called (owner decision
2026-11-14: the trace of a run says which code wrote it). In a checkout the
placeholder stays and git is asked.

Author: Felix Vossel
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REVISION = "$Format:%H$"


def revision() -> str:
    """The commit of this code, "" where neither the archive nor git says."""
    if not REVISION.startswith("$"):
        return REVISION
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"],
                              cwd=Path(__file__).resolve().parent,
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""
