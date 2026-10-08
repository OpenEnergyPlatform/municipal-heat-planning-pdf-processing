# docpipe.serve.http

`docpipe/serve/http.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

http.py: The value store over HTTP, read only.

    GET /                 what this server answers
    GET /documents        the documents with values
    GET /parameters       the parameters, their units and coordinates
    GET /values           the values that match the query
                          ?document= &parameter= &level= &text=
                          &limit= &offset= &coordinate.<name>=<value>
    GET /values/<id>      one value with everything that backs it
    GET /states           what the harvest says of a parameter in a document
                          (unstated, exhausted, ... never asked)
                          ?document= &parameter= &state= &limit= &offset=
    GET /coverage         documents by parameters, each cell its state
                          ?document= &parameter= &limit= &offset=
    GET /refusals         the claims that were refused, and why
                          ?document= &parameter= &limit= &offset=
    GET /search           passages by word: ?text= &document= &limit=
                          (503 with the reason where there is no corpus
                          database or word index)

Answers are JSON. Nothing can be written through it. A document or a
parameter the harvest does not have is a 404, not an empty answer.

It listens on this machine only unless told otherwise, and it does not
listen anywhere else without a token: with DOCPIPE_API_TOKEN set every
request has to carry `Authorization: Bearer <token>`. The standard
library's server is used as it is: fine behind a reverse proxy or for a
group, not something to put on the open internet by itself.

Author: Felix Vossel

## Functions

### token

```python
def token() -> Optional[str]
```

### arguments_of

```python
def arguments_of(query: str) -> dict
```

The query string as the arguments of `find_values`.

### answer

```python
def answer(store: Values, path: str, query: str = "") -> tuple
```

(status, body) for one GET.

### handler

```python
def handler(store: Values, secret: Optional[str])
```

### make_server

```python
def make_server(store: Values, host: str = "127.0.0.1",
                port: int = DEFAULT_PORT) -> ThreadingHTTPServer
```

### serve

```python
def serve(store: Values, host: str = "127.0.0.1",
          port: int = DEFAULT_PORT) -> int
```

[Back to the index](../README.md)
