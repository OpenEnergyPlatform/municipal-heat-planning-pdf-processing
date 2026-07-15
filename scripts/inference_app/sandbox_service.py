#!/usr/bin/env python3
"""
sandbox_service.py – Localhost HTTP wrapper around llm-sandbox.

Each request runs the code in a FRESH, ephemeral container with no network,
resource limits, all capabilities dropped and an execution timeout, so untrusted,
possibly prompt-injected LLM code cannot reach the host or the network. It binds
loopback only and is guarded by a bearer token; do NOT expose it directly.

    POST /run   Authorization: Bearer <KWP_SANDBOX_TOKEN>
       body: {"code": "<python>", "context": {"var": <json-value>, ...}, "timeout": <int>}
       ->   {"ok": bool, "stdout": str, "stderr": str, "exit_code": int|null, "error": str|null}
    GET  /health -> {"ok": true}    (no auth; readiness probe)

`context` entries are injected as pre-defined variables (JSON-decoded) before the
submitted code. Configured entirely from the environment (see below).

Author: Felix Vossel
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llm_sandbox import SandboxSession
from llm_sandbox.const import SandboxBackend

TOKEN = os.environ.get("KWP_SANDBOX_TOKEN", "")
IMAGE = os.environ.get("KWP_SANDBOX_IMAGE", "localhost/kwp-sandbox:latest")
HOST = os.environ.get("KWP_SANDBOX_HOST", "127.0.0.1")
PORT = int(os.environ.get("KWP_SANDBOX_PORT", "8600"))
DEFAULT_TIMEOUT = int(os.environ.get("KWP_SANDBOX_TIMEOUT", "20"))
MAX_TIMEOUT = int(os.environ.get("KWP_SANDBOX_MAX_TIMEOUT", "30"))
MEM = os.environ.get("KWP_SANDBOX_MEM", "512m")

# Container hardening. `network_mode: none` is the key guard. Resource limits are
# best-effort under rootless cgroupfs but do not break container creation.
HARDENING = {
    "network_mode": "none",
    "mem_limit": MEM,
    "pids_limit": 128,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges"],
}

# One container at a time; keeps resource use bounded.
_LOCK = threading.Lock()


def _preamble(context: dict) -> str:
    """Inject each context entry as a JSON-decoded variable before the user code."""
    if not context:
        return ""
    lines = ["import json as _json"]
    for key, value in context.items():
        if isinstance(key, str) and key.isidentifier():
            lines.append(f"{key} = _json.loads({json.dumps(json.dumps(value))})")
    return "\n".join(lines) + "\n"


def run_code(code: str, context: dict | None, timeout: int) -> dict:
    full = _preamble(context or {}) + (code or "")
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    with _LOCK:
        try:
            with SandboxSession(backend=SandboxBackend.PODMAN, lang="python",
                                image=IMAGE, keep_template=True,
                                runtime_configs=HARDENING) as session:
                result = session.run(full, timeout=timeout)
                return {
                    "ok": getattr(result, "exit_code", 1) == 0,
                    "stdout": (result.stdout or ""),
                    "stderr": (getattr(result, "stderr", "") or ""),
                    "exit_code": getattr(result, "exit_code", None),
                    "error": None,
                }
        except Exception as e:  # container/backend error → structured failure
            return {"ok": False, "stdout": "", "stderr": "",
                    "exit_code": None, "error": f"{type(e).__name__}: {e}"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, {"error": "not found"})
        if not TOKEN or self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            return self._send(401, {"error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "bad json"})
        code = payload.get("code", "")
        if not isinstance(code, str) or not code.strip():
            return self._send(400, {"error": "missing code"})
        self._send(200, run_code(code, payload.get("context"), payload.get("timeout", DEFAULT_TIMEOUT)))

    def log_message(self, *args):
        pass  # quiet


def main() -> None:
    if not TOKEN:
        raise SystemExit("KWP_SANDBOX_TOKEN must be set")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"kwp sandbox service listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
