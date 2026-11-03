#!/usr/bin/env python3
"""
sandbox_service.py: Localhost HTTP wrapper around llm-sandbox.

The service keeps KWP_SANDBOX_PARALLEL containers for as long as it runs,
with no network, resource limits, every capability dropped and an execution
timeout, so untrusted, possibly prompt-injected LLM code cannot reach the
host or the network. Each request runs in one of them, and what the run left
behind, its processes and its files, is cleared before that container serves
the next one. The server binds loopback only and is guarded by a bearer
token; it must not be exposed directly.

    POST /run   Authorization: Bearer <KWP_SANDBOX_TOKEN>
       body: {"code": "<python>", "context": {"var": <json-value>, ...},
              "timeout": <int>}
       ->   {"ok": bool, "stdout": str, "stderr": str,
             "exit_code": int|null, "error": str|null}
    GET  /health -> {"ok": true}    (no auth; readiness probe)

`context` entries are injected as pre-defined variables (JSON-decoded)
before the submitted code runs. Every setting is read from the
environment; see the module below for the names and defaults.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from llm_sandbox.const import SandboxBackend
    from llm_sandbox.pool import (PoolConfig, PooledSandboxSession,
                                  create_pool_manager)
except ImportError:                 # the one package only this service needs
    # Said when the service is started (`main`), not here: `--help` has
    # to answer on a machine that does not have it.
    SandboxBackend = PoolConfig = PooledSandboxSession = None
    create_pool_manager = None

TOKEN = os.environ.get("KWP_SANDBOX_TOKEN", "")
IMAGE = os.environ.get("KWP_SANDBOX_IMAGE", "localhost/kwp-sandbox:latest")
HOST = os.environ.get("KWP_SANDBOX_HOST", "127.0.0.1")
PORT = int(os.environ.get("KWP_SANDBOX_PORT", "8600"))
DEFAULT_TIMEOUT = int(os.environ.get("KWP_SANDBOX_TIMEOUT", "20"))
MAX_TIMEOUT = int(os.environ.get("KWP_SANDBOX_MAX_TIMEOUT", "30"))
MEM = os.environ.get("KWP_SANDBOX_MEM", "512m")
PARALLEL = int(os.environ.get("KWP_SANDBOX_PARALLEL", "1"))

# Container hardening. `network_mode: none` is the key guard. Resource limits are
# best-effort under rootless cgroupfs but do not break container creation.
# `stop_signal`: the idle process of the image ignores SIGTERM, and every stop
# would wait ten seconds for it. Podman takes the number only.
HARDENING = {
    "network_mode": "none",
    "mem_limit": MEM,
    "pids_limit": 128,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges"],
    "stop_signal": 9,
}

# Runs at a time, one container each, one by default; keeps resource use
# bounded. A harvest has a machine to itself and many short runs.
_LOCK = threading.BoundedSemaphore(PARALLEL)

# Kept for as long as the service runs: a pool's defaults retire a container
# after five idle minutes and after an hour.
POOL_CONFIG = {"max_pool_size": PARALLEL, "min_pool_size": PARALLEL,
               "idle_timeout": None, "max_container_lifetime": None,
               "acquisition_timeout": 600}
POOL = None                         # the containers, opened by `main`

# What a run left goes before its container serves the next one: every
# process but the container's own, every file in the work dir and the temp
# dirs but the venv the pool built there.
CLEAR = """
import os, shutil, signal
mine = os.path.abspath(__file__)
for pid in os.listdir("/proc"):
    if pid.isdigit() and int(pid) not in (1, os.getpid()):
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass
for top in ("/sandbox", "/tmp", "/var/tmp", "/dev/shm"):
    if not os.path.isdir(top):
        continue
    for name in os.listdir(top):
        path = os.path.join(top, name)
        if name in (".sandbox-venv", ".sandbox-pip-cache") or path == mine:
            continue
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
"""
CLEAR_TIMEOUT = 20


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
            with PooledSandboxSession(pool_manager=POOL) as session:
                try:
                    result = session.run(full, timeout=timeout)
                finally:
                    cleared = session.run(CLEAR, timeout=CLEAR_TIMEOUT)
                # A container that kept what a run left is not handed on
                # as if it were clean.
                if getattr(cleared, "exit_code", 1) != 0:
                    raise RuntimeError("the container was not cleared: "
                                       + (getattr(cleared, "stderr", "")
                                          or "")[-300:])
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


def open_pool():
    """The containers of this service, made when it starts."""
    return create_pool_manager(backend=SandboxBackend.PODMAN, lang="python",
                               image=IMAGE, keep_template=True,
                               runtime_configs=HARDENING,
                               config=PoolConfig(**POOL_CONFIG))


def main(argv=None) -> None:
    import argparse
    argparse.ArgumentParser(
        prog="docpipe sandbox",
        description="The service that runs code a model wrote, in a "
                    "container without a network. It takes no arguments: "
                    "where it listens and what a run may use are settings "
                    "(`docpipe config --stage sandbox`), and "
                    "KWP_SANDBOX_TOKEN has to be set.").parse_args(argv)
    if create_pool_manager is None:
        raise SystemExit("the sandbox service needs llm-sandbox: "
                         "pip install 'docpipe[sandbox]'")
    if not TOKEN:
        raise SystemExit("KWP_SANDBOX_TOKEN must be set")
    global POOL

    def stop(*_):
        raise SystemExit(0)

    # A job ends the service with SIGTERM; the containers go with it.
    signal.signal(signal.SIGTERM, stop)
    POOL = open_pool()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"kwp sandbox service listening on {HOST}:{PORT}, "
          f"{PARALLEL} container(s)", flush=True)
    try:
        server.serve_forever()
    finally:
        POOL.close()


if __name__ == "__main__":
    main()
