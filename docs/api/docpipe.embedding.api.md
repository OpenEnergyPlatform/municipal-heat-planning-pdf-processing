# docpipe.embedding.api

`docpipe/embedding/api.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

api.py: Embeds items by calling an embeddings API.

ApiEmbedder is for deployments without a GPU, or for a deployment
where the embedding model is served centrally. Which API it calls is
the provider of the `embedding` role (EMBEDDING_PROVIDER, see
docpipe/providers): an OpenAI-compatible /v1/embeddings endpoint, or
a hosted one. It batches items into groups of batch_size before
calling it, and asks a hosted API again that answers "not now".

The OpenAI request has no place for an image, so in that form
(EMBEDDING_API_FORMAT=input) embed() is text only: an item carrying an
image is refused with a ValueError rather than silently embedded as
text. A vLLM server also takes the item as a chat
(EMBEDDING_API_FORMAT=messages): the instruction, the picture and the
text in the turns the model's own code builds (`conversation`), which
embeds a figure with its picture.

Author: Felix Vossel

## Classes

### ApiEmbedder

```python
class ApiEmbedder
```

#### ApiEmbedder.\_\_init\_\_

```python
def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
             model: Optional[str] = None, batch_size: Optional[int] = None,
             form: Optional[str] = None, post=None)
```

#### ApiEmbedder.text_only

```python
@property
def text_only(self) -> bool
```

Whether a picture has no place in this embedder's requests.

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

## Functions

### data_uri

```python
def data_uri(image) -> str
```

A picture as the URL a chat message carries: a file as a data URI, a
URL as it is.

### conversation

```python
def conversation(item: dict) -> list
```

The chat one item is embedded as, in the messages form.

The turns of Qwen3VLEmbedder.format_model_input: the instruction as the
system turn (a full stop added where it ends without punctuation), the
picture before the text in the user turn, "NULL" for an item with
neither. The empty assistant turn is continued by the request
(`continue_final_message`), so the prompt ends where the model's own code
ends it with `add_generation_prompt`, and the pooled last token is the
same one.

### unit_rows

```python
def unit_rows(vectors) -> list
```

Each vector scaled to length one: the index is an inner-product index
of unit vectors, and the model's own code hands out unit vectors.

[Back to the index](../README.md)
