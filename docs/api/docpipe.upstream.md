# docpipe.upstream

`docpipe/upstream.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

upstream.py: Pulls the files a profile is written against, at the version
upstream currently calls its own.

A profile names its sources in `profiles/<name>/vocabulary.py: SOURCES`. This
module resolves each one to a version, downloads it into a cache keyed by that
version, and returns a record of what it got. What a file is for (a closure to
snapshot, shapes to validate against, regions to offer) is the profile's.

Three kinds:

  release_asset  An asset of the repository's latest GitHub release. A
                 repository without a release is an error, unless the source
                 says `until_released`: then it is skipped with a note.
  repo_files     Files at the head of a branch. The version is a digest over
                 their bytes. A source may name the commit its profile was
                 `reviewed` against, and the record then lists every file that
                 differs from that commit.
  sparql         A query against the OEKG endpoint. The token comes from the
                 environment variable `token_env` names and is written nowhere.

Only github.com and raw.githubusercontent.com are asked, never
api.github.com: the API allows 60 unauthenticated requests an hour per
address, and every user of a shared machine shares one address.

Network access goes through urllib with the proxy settings the environment
already has. A source that cannot be fetched raises. A run against an old
ontology that believes it has the current one is what this module prevents.

Author: Felix Vossel

## Classes

### UpstreamError

```python
class UpstreamError(RuntimeError)
```

A source that could not be resolved or fetched.

`status` is the HTTP status when there was one, so a file that does not
exist (404) can be told apart from a server or a network that failed.

#### UpstreamError.\_\_init\_\_

```python
def __init__(self, message: str, status: Optional[int] = None)
```

## Functions

### sha256

```python
def sha256(path: Path) -> str
```

### latest_release

```python
def latest_release(repo: str) -> Optional[str]
```

The tag of the latest release, or None if the repository has none.

github.com answers /releases/latest with a redirect to the release's tag
page, and a repository without a release with one to /releases.

### sparql

```python
def sparql(endpoint: str, query: str, token: str) -> list
```

[{variable: value}] from the OEKG endpoint.

The endpoint answers with a JSON string that itself holds the JSON result,
so the body is decoded twice.

### fetch

```python
def fetch(sources: dict, cache: Path = CACHE) -> dict
```

{name: record} for every source, in the order the profile names them.

### lock_path

```python
def lock_path(profile: str, cache: Path = CACHE) -> Path
```

### write_lock

```python
def write_lock(profile: str, records: dict, cache: Path = CACHE) -> Path
```

### load_lock

```python
def load_lock(profile: str, cache: Path = CACHE) -> Optional[dict]
```

### files

```python
def files(record: Optional[dict], suffix: str = "") -> list
```

The local paths of a record's files, optionally by suffix.

### summary

```python
def summary(name: str, record: dict) -> str
```

One English log line per source.

[Back to the index](../README.md)
