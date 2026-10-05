# docpipe.llm_preflight

`docpipe/llm_preflight.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

llm_preflight.py: Asks the server what it can do, before the first
document.

A stage knows what one request costs it (`config.max_request_tokens()`);
the server knows how much context it was started with. Nothing compared
the two, so a `--max-model-len` set too small surfaced as a slow trickle
of truncated replies hours into a run, with 42 windows silently keeping
their raw text, instead of as a single error within the first second.

Two questions, both answered by the provider's list of models:
  * does it serve the model the stage is about to request?
  * is its context at least as large as the worst-case request?

A hosted API is asked a third: does the model answer inside a reply schema?
That is the only way a hosted model is asked for JSON (see `providers`), so
a model that cannot is refused here and not after the first document.

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
def serving_limits(base_url: str, api_key: str, timeout: float = 30.0,
                   role: str = "llm")
```

(served model ids, max_model_len or None) as the server reports them.

### assert_reply_schema

```python
def assert_reply_schema(base_url: str, api_key: str, model: str, *,
                        what: str = "this stage",
                        role: str = "llm") -> Optional[str]
```

Raise PreflightError unless *model* answers inside a reply schema.

One small request, with the reasoning settings every request carries. A
model that takes no schema, or refuses a setting, refuses every request
of the run; here it says so once, with the variable that changes it.

None when it did. When the API could not be asked there is no verdict:
why, as a sentence, and the run asks anyway.

### assert_serving

```python
def assert_serving(base_url: str, api_key: str, model: str,
                   required_tokens: int, *, what: str = "this stage",
                   flag: str = CONTEXT_FLAG,
                   role: str = "llm") -> Optional[int]
```

Raise PreflightError unless *base_url* serves *model* with room for
*required_tokens*. Logs both numbers on success, so they end up in the
job's output file where the next person can read them. Returns the
server's window, or None when it does not report one; such a server is
asked the request fields all the same.

### assert_request_extras

```python
def assert_request_extras(base_url: str, api_key: str, model: str, *,
                          what: str = "this stage",
                          role: str = "llm") -> Optional[str]
```

Raise PreflightError unless the server accepts the reasoning settings.

One request of one token. A server that refuses `reasoning_effort`
refuses every request of the run, and without this it says so as a 400
per document for as long as the job lives. Named here with the variable
that turns it off, because that is a restart and not a release.

None when the server took them. A server that could not be asked (down,
busy, a 5xx) gives no verdict: why, as a sentence, and the settings go out
anyway. The two are told apart so that a caller who reports "accepted"
knows it was.

### assert_request_accepted

```python
def assert_request_accepted(base_url: str, api_key: str, model: str, *,
                            what: str = "this stage",
                            role: str = "llm") -> Optional[str]
```

The probe of the request fields that `assert_serving` sends for this
role's kind of server: the reply schema of a hosted API, the reasoning
settings of one's own. For the doctor, which asks it on its own.

Raises PreflightError on a refusal; returns None when the server
accepted, and a sentence when it could not be asked.

[Back to the index](../README.md)
