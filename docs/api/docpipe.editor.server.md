# docpipe.editor.server

`docpipe/editor/server.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

server.py: The local server of `docpipe edit` and the one file guard.

`App` answers a request as plain data (method, path, query and body in, a
status and an object out), so every promise of the endpoints can be held to
without a socket. What an endpoint says comes from `specs.py`; this module
only reads the file, asks the logic and, where the logic says so, writes.

`Files` is the one place the editor touches a file: it may write only inside
the profile's own folder and read only inside the folders of the profiles in
effect, the harvest it was given, the page itself and the generated
documentation. A path is resolved first, so `..` and links cannot lead out.

The HTTP layer binds 127.0.0.1 only, answers only a `Host` it knows (a page
of another site cannot reach the server by a name of its own) and takes a
POST only with the header the page sends (a form on another site cannot send
it). A request it answers without having read it to the end, a refusal, is
read off before the connection closes, so that the answer arrives. The
standard library is all this needs.

Author: Felix Vossel

## Classes

### Files

```python
class Files
```

Every byte the editor reads or writes itself goes through `open`.

#### Files.\_\_init\_\_

```python
def __init__(self, write_root: Path, read_roots: Sequence[Path])
```

#### Files.open

```python
def open(self, path, mode: str = "rb")
```

#### Files.read

```python
def read(self, path) -> bytes
```

#### Files.write

```python
def write(self, path, data: bytes) -> None
```

The whole file or the old one: written beside it, then put in its
place.

#### Files.digest

```python
def digest(self, path) -> str
```

The sha256 of a file's bytes, as hex.

#### Files.stamps

```python
def stamps(self, folder) -> list
```

The stamp files directly in a folder, sorted.

#### Files.tree

```python
def tree(self, folder) -> list
```

Every file below a folder, sorted; [] where there is none.

### App

```python
class App
```

The endpoints of CONTRACT section 3, without a socket.

#### App.\_\_init\_\_

```python
def __init__(self, profile, harvest: Optional[Path] = None,
             root: Optional[Path] = None)
```

#### App.shown

```python
def shown(self, path) -> str
```

A path as the user sees it: relative to the repository with
forward slashes where it lies under it, else absolute.

#### App.snapshot

```python
def snapshot(self) -> Optional[dict]
```

The ontology snapshot of the profile, loaded once; None where the
profile has none.

#### App.call

```python
def call(self, method: str, path: str, query: dict,
         body) -> tuple
```

(status, object) of a request: nothing is raised.

## Functions

### sha256

```python
def sha256(data: bytes) -> str
```

### serve

```python
def serve(app: App, port: int) -> ThreadingHTTPServer
```

The server bound to 127.0.0.1 (port 0: a free one), not yet
running.

### command

```python
def command(rest: Sequence[str]) -> int
```

[Back to the index](../README.md)
