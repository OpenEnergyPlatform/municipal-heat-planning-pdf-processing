# docpipe.providers.base

`docpipe/providers/base.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

base.py: What every provider speaks towards the stages.

The stages were written against one client: `client.chat.completions.create`
with a model, messages, a token limit and a reply format, answered by an
object with `choices[0].message.content`, a `finish_reason` and a `usage`.
A failure is an exception with an HTTP `status_code` when there was one. That
stays the contract. A provider is whatever turns such a call into a request
of its API and the API's answer back into that object, so no stage knows
which API it is talking to.

Author: Felix Vossel

## Classes

### ProviderError

```python
class ProviderError(Exception)
```

A request the API did not serve.

`status_code` is the HTTP status, or None when no reply came at all;
`retry_after` the seconds the API asked to wait, when it said.

#### ProviderError.\_\_init\_\_

```python
def __init__(self, message: str, status_code: Optional[int] = None,
             retry_after: Optional[float] = None)
```

### ProviderTimeout

```python
class ProviderTimeout(ProviderError)
```

No answer within the request's time.

### Endpoint

```python
@dataclass
class Endpoint
```

Where one role's requests go.

Fields:

- `role: str`
- `provider: str`
- `base_url: Optional[str] = None`
- `api_key: Optional[str] = None`
- `timeout: Optional[float] = None`
- `thinking_room: int = 0`
- `options: dict = field(default_factory=dict)`

## Functions

### reply

```python
def reply(text: str, finish: str, *, prompt_tokens: Optional[int] = None,
          completion_tokens: Optional[int] = None, model: Optional[str] = None,
          reasoning: Optional[str] = None,
          cached_tokens: Optional[int] = None) -> SimpleNamespace
```

One answer, in the shape the stages read.

`cached_tokens` is the part of `prompt_tokens` the API served from its
cache; it is on the usage block only where the API said so.

### facade

```python
def facade(create, models=None, embeddings=None) -> SimpleNamespace
```

A client with the attribute paths the stages call.

### split_messages

```python
def split_messages(messages) -> tuple
```

(system text, turns) of an OpenAI-shaped conversation.

A turn is (role, parts); a part is ("text", text) or ("image", media
type, base64 data). System messages are joined: the APIs that take the
system text beside the conversation take one.

### image_bytes

```python
def image_bytes(data: str) -> bytes
```

### wanted_schema

```python
def wanted_schema(response_format) -> Optional[tuple]
```

(name, schema) of a reply format that carries a schema, else None.

A request for "some JSON object" is refused: a hosted model is asked
inside a schema or for plain text, never for JSON it may wrap in prose.

### enforced

```python
def enforced(response_format, dialect: str = schemas.ALL_REQUIRED,
             budget: Optional[tuple] = None) -> tuple
```

(name, strict schema, decode) or (None, None, None).

### decoded

```python
def decoded(text: str, decode) -> str
```

### merge

```python
def merge(into: dict, extra: dict) -> dict
```

`extra` laid over `into`, table by table.

### sends_temperature

```python
def sends_temperature(provider: str, model: str) -> bool
```

### refused_temperature

```python
def refused_temperature(provider: str, model: str, exc: BaseException) -> bool
```

True when *exc* is the API refusing this model's temperature.

For every request that carried one, not only the first to learn it: the
requests that were under way when the first refusal came are refused
the same way, and each is sent again without.

### blank

```python
def blank(text) -> bool
```

A turn with nothing in it, which the hosted APIs refuse to take.

### seconds

```python
def seconds(text) -> Optional[float]
```

A Retry-After header, or a duration such as "32s", as seconds.

### json_error

```python
def json_error(raw: bytes) -> str
```

The message of an API's JSON error body, or the body's first line.

[Back to the index](../README.md)
