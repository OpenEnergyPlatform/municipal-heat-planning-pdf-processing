# docpipe.embedding

`docpipe/embedding/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

\_\_init\_\_.py: Exposes one Embedder interface behind several backends.

get_embedder() reads EMBEDDING_BACKEND and returns one of three
things. "local" loads the model in this process, on this machine's
GPU (embedding/local.py). "api" calls an OpenAI-compatible
/v1/embeddings endpoint (embedding/api.py). Anything of the form
"package.module:attribute" is an import path: the module is imported,
the named attribute is called with the given keyword arguments, and
whatever it returns is used as the embedder. Which of the three a
deployment uses is a matter of configuration, not of code: a laptop
without a GPU points at an endpoint, a compute node loads the model.

The import-path form is the extension point. Loading a model
quantized, on demand, and freeing the memory again between queries
depends on one machine's hardware and not on the pipeline, so such an
implementation lives next to the deployment that needs it rather than
in this repository. It is named here only by import path; the
package requires of it only an `embed` method and an `embed_one`
method. See scripts/inference_app/README.md.

One limitation holds for every deployment: the OpenAI embeddings API
is text only. Image and image+text items (the *\_vl embedding types)
therefore need a local backend, or an endpoint that accepts
multimodal input.

Author: Felix Vossel

## Classes

### Embedder

```python
class Embedder(Protocol)
```

Turns items ({"text": ..., "image": ...}) into vectors.

#### Embedder.embed

```python
def embed(self, items: Sequence[dict]) -> list
```

#### Embedder.embed_one

```python
def embed_one(self, item: dict) -> list
```

## Functions

### get_embedder

```python
def get_embedder(backend: Optional[str] = None, **kwargs) -> Embedder
```

The embedder this deployment is configured for.

[Back to the index](../README.md)
