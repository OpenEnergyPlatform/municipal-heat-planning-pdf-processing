# docpipe.embedding.api

`docpipe/embedding/api.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

api.py: Embeds items by calling an OpenAI-compatible /v1/embeddings
endpoint.

ApiEmbedder is for deployments without a GPU, or for a deployment
where the embedding model is served centrally. It batches items into
groups of batch_size before calling the endpoint. The OpenAI
embeddings schema has no place for an image, so embed() is text
only: an item carrying an image is refused with a ValueError rather
than silently embedded as text.

Author: Felix Vossel

## Classes

### ApiEmbedder

```python
class ApiEmbedder
```

#### ApiEmbedder.\_\_init\_\_

```python
def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
             model: Optional[str] = None, batch_size: Optional[int] = None)
```

#### ApiEmbedder.client

```python
def client(self)
```

#### ApiEmbedder.embed

```python
def embed(self, items: Sequence[dict]) -> list
```

#### ApiEmbedder.embed_one

```python
def embed_one(self, item: dict) -> list
```

[Back to the index](../README.md)
