# docpipe.visuals.vision

`docpipe/visuals/vision.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

vision.py: Vision model interaction layer over an OpenAI compatible
API.

Creates the client, checks model availability, and makes the chat
completions call that sends a base64 encoded image and parses the
JSON response.

Author: Felix Vossel

## Functions

### looks_runaway

```python
def looks_runaway(text: str) -> bool
```

True if *text* carries the empty-cell run that precedes a truncated answer.

### create_client

```python
def create_client(base_url: str | None = None, timeout: float | None = None) -> openai.OpenAI
```

Creates an OpenAI client pointed at the vLLM server.

### check_model_available

```python
def check_model_available(
    client: openai.OpenAI,
    model: str = VLM_MODEL,
) -> bool
```

Verifies that the vLLM endpoint is reachable and serves *model*.

### call_vision

```python
def call_vision(
    client: openai.OpenAI,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    *,
    model: str = VLM_MODEL,
    max_retries: int = MAX_RETRIES,
    temperature: float = VLM_TEMPERATURE,
    max_tokens: int = VLM_MAX_TOKENS,
    repetition_penalty: float | None = None,
) -> dict | None
```

Sends an image + prompt to the vision model and parses the JSON response.

The wall-clock bound per request is the client timeout set by
create_client(), not *max_retries*.

Returns:
    Parsed JSON dict, or None once the retries are exhausted or the server
    rejects the request itself (a 4xx, which no retry would change).

### call_vision_plain

```python
def call_vision_plain(
    client: openai.OpenAI,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    *,
    model: str = VLM_MODEL,
    temperature: float = VLM_TEMPERATURE,
    max_tokens: int = VLM_MAX_TOKENS,
    key: str = "markdown",
) -> str | None
```

One unconstrained call: the answer as plain text, no JSON envelope.

The last resort after call_vision has given up. Of 112 parse failures in the
August 2026 run, 111 read "No JSON object found in response" on a 200 OK
that came back within the same second — the model answers, it just will not
wear the envelope. Discarding that answer loses information the model
already produced.

Returns the response text (``<think>`` stripped), or None if the call fails
or comes back empty.

[Back to the index](../README.md)
