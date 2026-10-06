# docpipe.providers

`docpipe/providers/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

providers: Which API a stage's requests go to.

Every stage asks through one client shape (see `base`). `client(role, ...)`
builds it for the provider the role is set to:

    openai-compatible   a server of one's own (vLLM and the like): the OpenAI
                        client as the stages always built it, nothing between
    openai              the hosted OpenAI API
    anthropic           the Anthropic API
    gemini              the Google Gemini API

A role is what a request is for: `llm` (text: repair, extraction, chat),
`vlm` (tables, figures, scanned pages) and `embedding`. Each has its own
provider setting, so a corpus can be read by a hosted model and embedded by
a local one.

A hosted model is asked for JSON only inside a reply schema, which the API
enforces while it generates (`reply_format`). A server of one's own gets the
schema where it always got one, and everywhere with LLM_SCHEMA=all. The
requests of refinement, of the visuals stage and of page transcription send
theirs as the grammar of the reply on every provider (`grammar`).

Author: Felix Vossel

## Exports

What `__all__` names, and where each name is defined:

- `HOSTED`
- `OPENAI_COMPATIBLE`
- `PROVIDERS`
- `ROLES`
- `Endpoint` from [docpipe.providers.base](docpipe.providers.base.md)
- `ProviderError` from [docpipe.providers.base](docpipe.providers.base.md)
- `ProviderTimeout` from [docpipe.providers.base](docpipe.providers.base.md)

## Functions

### provider

```python
def provider(role: str) -> str
```

The provider a role is set to.

### hosted

```python
def hosted(role: str) -> bool
```

### enforces_schema

```python
def enforces_schema(role: str) -> bool
```

Whether every JSON request of this role goes out with its schema.

### grammar

```python
def grammar(name: str, schema: dict) -> dict
```

The `response_format` that makes *schema* the grammar of a reply.

For a request that always sends its schema, whatever the server is: the
server of one's own and the hosted API get the same dict, and the hosted
adapter makes it strict itself (see `base.enforced`). `reply_format` is
this, for a request that sends it only where the installation says so.

### reply_format

```python
def reply_format(role: str, name: str, schema: dict, otherwise=None)
```

The `response_format` of a request whose reply is *schema*.

*otherwise* is what the request sent before there were reply schemas for
it: nothing, or `{"type": "json_object"}`. A server of one's own keeps
getting that unless LLM_SCHEMA=all.

### formatted

```python
def formatted(role: str, name: str, schema: dict, otherwise=None) -> dict
```

`reply_format` as keyword arguments: empty when nothing is sent.

### request_options

```python
def request_options(role: str) -> dict
```

What an installation adds to every request body of this role.

### endpoint

```python
def endpoint(role: str, *, base_url: Optional[str] = None,
             api_key: Optional[str] = None,
             timeout: Optional[float] = None) -> Endpoint
```

Where a hosted role's requests go.

The address a stage passes is its own default when the installation set
none, and that default is a local server. So the address counts only when
the installation set it; otherwise the provider's own applies. A
placeholder key means "use the key the provider's own variable holds".

### client

```python
def client(role: str, **kwargs)
```

The client a stage sends this role's requests through.

For a server of one's own this is `openai.OpenAI(**kwargs)` and nothing
else, as each stage built it before. For a hosted provider it is that
provider's adapter behind the endpoint's gate (see `governor`).

A run that replays a cassette gets its player and no client at all; a
run that records one gets its client with the recorder around it (see
`cassette`). Neither is set in a run that names no cassette.

### replaying

```python
def replaying() -> bool
```

Whether this run takes its answers from a cassette: there is then no
server to ask, to watch or to steer by.

### gate

```python
def gate(role: str)
```

The gate of a hosted role's endpoint, or None for one's own server.

### timed_out

```python
def timed_out(exc: BaseException) -> bool
```

A request that got no answer within its time, whatever sent it.

[Back to the index](../README.md)
