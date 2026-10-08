# docpipe.providers.openai_api

`docpipe/providers/openai_api.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

openai_api.py: The hosted OpenAI API.

The same client the stages always used, minus what only a server of one's
own takes: the chat-template switch and the repetition penalty are left out,
the token limit goes by its current name and includes the room the model
may think in, and a reply schema is sent as a strict one.

Author: Felix Vossel

## Classes

### OpenAIChat

```python
class OpenAIChat
```

#### OpenAIChat.\_\_init\_\_

```python
def __init__(self, endpoint: base.Endpoint)
```

#### OpenAIChat.client

```python
def client(self)
```

#### OpenAIChat.create

```python
def create(self, *, model, messages, max_tokens=None, temperature=None,
           response_format=None, extra_body=None, timeout=None)
```

[Back to the index](../README.md)
