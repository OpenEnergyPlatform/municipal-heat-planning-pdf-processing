# docpipe.providers.anthropic_api

`docpipe/providers/anthropic_api.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

anthropic_api.py: The Anthropic API, through its SDK.

A stage's request becomes one Messages request. The system prompt goes
beside the conversation and is marked for the prompt cache, since thousands
of requests of a run share it. A reply schema goes out as the output format
the API generates in. The request is streamed and read as one message, so a
long answer does not run into an HTTP timeout.

The models that can decline a request for safety reasons are asked with the
API's own fallback: a declined request is answered by the model the API
names for it, and the reply says which model that was. A reply the whole
chain declined comes back as refused, which a stage reads as "no answer".

Author: Felix Vossel

## Classes

### AnthropicChat

```python
class AnthropicChat
```

#### AnthropicChat.\_\_init\_\_

```python
def __init__(self, endpoint: base.Endpoint)
```

#### AnthropicChat.client

```python
def client(self)
```

#### AnthropicChat.embeddings

```python
def embeddings(self, **_)
```

#### AnthropicChat.models

```python
def models(self)
```

#### AnthropicChat.create

```python
def create(self, *, model, messages, max_tokens=None, temperature=None,
           response_format=None, extra_body=None, timeout=None)
```

[Back to the index](../README.md)
