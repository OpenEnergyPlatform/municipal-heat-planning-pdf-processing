# docpipe.inference.code_exec

`docpipe/inference/code_exec.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

code_exec.py: Client for the sandboxed code execution service.

The module posts LLM-written Python to `sandbox_service.py` at the
address `CODE_EXEC_URL` names. It never raises: a sandbox outage
degrades to no calculation rather than breaking a query. The feature
stays off unless `CODE_EXEC_URL` is set, which `is_enabled()` reports.

## Functions

### is_enabled

```python
def is_enabled() -> bool
```

True iff a sandbox endpoint is configured.

### run_code

```python
def run_code(code: str, context: Optional[dict] = None,
             timeout: Optional[float] = None) -> dict
```

Execute `code` in the sandbox with `context` injected as variables.

Returns {"ok": bool, "stdout": str, "stderr": str, "exit_code": int|None,
"error": str|None}. Never raises: a disabled sandbox or any transport/HTTP
problem comes back as ok=False with an `error`.

[Back to the index](../README.md)
