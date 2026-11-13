# docpipe.app.sandbox_service

`docpipe/app/sandbox_service.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

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

## Classes

### Handler

```python
class Handler(BaseHTTPRequestHandler)
```

#### Handler.do_GET

```python
def do_GET(self)
```

#### Handler.do_POST

```python
def do_POST(self)
```

#### Handler.log_message

```python
def log_message(self, *args)
```

## Functions

### run_code

```python
def run_code(code: str, context: dict | None, timeout: int) -> dict
```

### open_pool

```python
def open_pool()
```

The containers of this service, made when it starts.

### wait_until_ready

```python
def wait_until_ready(pool, timeout: float, clock=time.monotonic,
                     sleep=time.sleep) -> None
```

Back once every container of the pool stands idle. A run that came
before would make a container of its own while podman is still starting,
and failed so in a job.

### main

```python
def main(argv=None) -> None
```

[Back to the index](../README.md)
