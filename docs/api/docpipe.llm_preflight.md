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

A stage that sends its reply schema as the grammar of every request
(refinement, the visuals stage, page transcription) has each of its schemas
put to the server once, as that stage will send it (`assert_reply_schemas`): a
server that refuses one refuses every request of the run.

What the preflight learns about the window stays with the run: a unit whose
reply was cut off and that cannot be split is asked once more with as much
room as the window leaves (`further_room`), and the stage that asks has the
number from here and not from a second request to the server.

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

### served_window

```python
def served_window(role: str = "llm") -> Optional[int]
```

The window, in tokens, that the server of *role* reported at this run's
preflight. None where it reported none (a hosted model whose window is its
own) and where nothing was asked (a caller that ran no preflight).

### further_room

```python
def further_room(asked: int, *, reply: int, budget: Optional[int],
                 role: str = "llm") -> Optional[int]
```

The token limit of the one further attempt of a unit whose reply was cut
off at *asked* tokens and that cannot be split: twice what it asked, or as
much as the served window leaves, whichever is smaller. None when the
window leaves no more room than the request had; nothing is sent then.

*budget* is the stage's largest request in tokens (the prompt, the largest
input and ONE largest reply, *reply* tokens), which the preflight checked
the window against. What the window holds beyond it is free for every
request of the run, so a request may have the reply the budget counts plus
that slack, and never more than twice what it asked:
min(2 * asked, reply + window - budget). A request that asked for less than
*reply* is doubled out of the reply alone.

Where the window is not known, or the caller has no budget, the room is
twice.

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

### assert_reply_schemas

```python
def assert_reply_schemas(base_url: str, api_key: str, model: str,
                         shapes: dict, *, what: str = "this stage",
                         role: str = "llm") -> Optional[str]
```

Raise PreflightError unless the server takes every reply schema in
*shapes* ({name: schema}) as the grammar of a request.

A stage that sends its schema with every request has no other way to ask
for JSON, so a server that refuses the schema refuses every request of
the run. One request of 32 tokens per shape, with the stage's own schema
and the reasoning settings every request carries; that the capped reply
is cut short is no matter, it is not read. Only a 4xx that is not a 429
is a refusal: a server that is busy or down gives no verdict, and the run
asks anyway.

None when every shape was taken; else why one could not be asked.

### assert_serving

```python
def assert_serving(base_url: str, api_key: str, model: str,
                   required_tokens: int, *, what: str = "this stage",
                   flag: str = CONTEXT_FLAG,
                   role: str = "llm",
                   shapes: Optional[dict] = None) -> Optional[int]
```

Raise PreflightError unless *base_url* serves *model* with room for
*required_tokens*. Logs both numbers on success, so they end up in the
job's output file where the next person can read them. Returns the
server's window, or None when it does not report one; such a server is
asked the request fields all the same. The window is kept for the run
(`served_window`).

*shapes* ({name: schema}) are the reply schemas the stage is about to send
as the grammar of its requests: the server is asked each one before the
first document (`assert_reply_schemas`).

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
