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

Answers are JSON. Nothing can be written through it.

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
