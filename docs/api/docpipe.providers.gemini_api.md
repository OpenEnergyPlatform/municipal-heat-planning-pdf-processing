# docpipe.providers.gemini_api

`docpipe/providers/gemini_api.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

gemini_api.py: The Google Gemini API, over its REST interface.

A stage's request becomes one `generateContent` call: the system prompt as
the system instruction, the conversation as contents, an image as inline
data, a reply schema as the JSON schema the API generates in. Text
embeddings go through `batchEmbedContents`.

Author: Felix Vossel

## Classes

### GeminiChat

```python
class GeminiChat
```

#### GeminiChat.\_\_init\_\_

```python
def __init__(self, endpoint: base.Endpoint, *, opener=None)
```

#### GeminiChat.client

```python
def client(self)
```

#### GeminiChat.models

```python
def models(self)
```

#### GeminiChat.create

```python
def create(self, *, model, messages, max_tokens=None, temperature=None,
           response_format=None, extra_body=None, timeout=None)
```

#### GeminiChat.embeddings

```python
def embeddings(self, *, model, input)
```

[Back to the index](../README.md)
