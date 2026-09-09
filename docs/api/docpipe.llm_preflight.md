# docpipe.llm_preflight

`docpipe/llm_preflight.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

llm_preflight.py: Asks the server what it can do, before the first
document.

A stage knows what one request costs it (`config.max_request_tokens()`);
the server knows how much context it was started with. Nothing compared
the two, so a `--max-model-len` set too small surfaced as a slow trickle
of truncated replies hours into a run, with 42 windows silently keeping
their raw text, instead of as a single error within the first second.

Two questions, both answered by `GET {base_url}/models`:
  * does the server serve the model the stage is about to request?
  * is its context at least as large as the worst-case request?

## Classes

### PreflightError

```python
class PreflightError(RuntimeError)
```

The server cannot serve what this stage is about to ask of it.

## Functions

### serving_limits

```python
def serving_limits(base_url: str, api_key: str, timeout: float = 30.0)
```

(served model ids, max_model_len or None) as the server reports them.

### assert_serving

```python
def assert_serving(base_url: str, api_key: str, model: str,
                   required_tokens: int, *, what: str = "this stage",
                   flag: str = "--max-model-len") -> None
```

Raise PreflightError unless *base_url* serves *model* with room for
*required_tokens*. Logs both numbers on success, so they end up in the
job's output file where the next person can read them.

[Back to the index](../README.md)
