"""
code_exec.py: Client for the sandboxed code execution service.

The module posts LLM-written Python to `sandbox_service.py` at the
address `CODE_EXEC_URL` names. It never raises: a sandbox outage
degrades to no calculation rather than breaking a query. The feature
stays off unless `CODE_EXEC_URL` is set, which `is_enabled()` reports.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from . import config

log = logging.getLogger(__name__)


def is_enabled() -> bool:
    """True iff a sandbox endpoint is configured."""
    return bool(config.CODE_EXEC_URL)


def run_code(code: str, context: Optional[dict] = None,
             timeout: Optional[float] = None) -> dict:
    """
    Execute `code` in the sandbox with `context` injected as variables.

    Returns {"ok": bool, "stdout": str, "stderr": str, "exit_code": int|None,
    "error": str|None}. Never raises: a disabled sandbox or any transport/HTTP
    problem comes back as ok=False with an `error`.
    """
    if not config.CODE_EXEC_URL:
        return {"ok": False, "stdout": "", "stderr": "", "exit_code": None,
                "error": "code-exec disabled"}
    body = json.dumps({"code": code, "context": context or {}}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.CODE_EXEC_TOKEN:
        headers["Authorization"] = f"Bearer {config.CODE_EXEC_TOKEN}"
    req = urllib.request.Request(config.CODE_EXEC_URL, data=body, method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout or config.CODE_EXEC_TIMEOUT) as resp:
            out = json.loads(resp.read() or b"{}")
        if not isinstance(out, dict):
            return {"ok": False, "stdout": "", "stderr": "", "exit_code": None,
                    "error": "malformed response"}
        out.setdefault("ok", False)
        out.setdefault("stdout", "")
        out.setdefault("stderr", "")
        return out
    except urllib.error.HTTPError as e:
        log.warning("code-exec HTTP %s", e.code)
        return {"ok": False, "stdout": "", "stderr": "", "exit_code": None,
                "error": f"HTTP {e.code}"}
    except Exception as e:  # timeout / connection / json
        log.warning("code-exec call failed: %s", e)
        return {"ok": False, "stdout": "", "stderr": "", "exit_code": None,
                "error": f"{type(e).__name__}: {e}"}
