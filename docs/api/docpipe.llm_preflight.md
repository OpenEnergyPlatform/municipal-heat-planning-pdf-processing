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

And one thing every stage agrees with the server about before it asks
anything: `request_extras`, the reasoning settings. They live here because
they are the same for every stage and because getting them wrong fails the
same way a window set too small does: hours in, as replies whose JSON was
truncated by the think block in front of it.

## Classes

### PreflightError

```python
class PreflightError(RuntimeError)
```

The server cannot serve what this stage is about to ask of it.

## Functions

### thinking_enabled

```python
def thinking_enabled() -> bool
```

### reasoning_effort

```python
def reasoning_effort() -> str
```

"" when the server is not to be told one at all.

### request_extras

```python
def request_extras() -> dict
```

The `extra_body` of every chat request this pipeline sends.

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

### assert_request_extras

```python
def assert_request_extras(base_url: str, api_key: str, model: str, *,
                          what: str = "this stage") -> None
```

Raise PreflightError unless the server accepts the reasoning settings.

One request of one token. A server that refuses `reasoning_effort`
refuses every request of the run, and without this it says so as a 400
per document for as long as the job lives. Named here with the variable
that turns it off, because that is a restart and not a release.

[Back to the index](../README.md)
