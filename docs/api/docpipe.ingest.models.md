# docpipe.ingest.models

`docpipe/ingest/models.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

models.py: What a profile hands the ingest step.

The core knows a document by four things: what to call it, where to get it, who
it is, and which other documents are versions of it. Everything else is the
profile's business and travels in `meta` (written to DocumentMeta) or `payload`
(never inspected by the core).

Author: Felix Vossel

## Classes

### UnusablePDF

```python
class UnusablePDF(Exception)
```

A source PDF has no usable text layer — it is not registered.

### SourceDoc

```python
@dataclass
class SourceDoc
```

Fields:

- `external_id: str`: the profile's stable identity (heat plans: the file name, papers: the DOI)
- `filename: str`
- `url: Optional[str] = None`: where to fetch it; None means it must already lie in the data directory
- `group_key: Optional[str] = None`
- `published: Optional[str] = None`
- `meta: dict = field(default_factory=dict)`: -> DocumentMeta columns
- `payload: dict = field(default_factory=dict)`: opaque to the core

### Source

```python
class Source
```

A profile's document source.

`documents` receives the open connection because a profile usually has to
write its own rows (an organisation, a municipality) before it can name the
document's metadata. `after_document` runs once per yielded document that
was accepted — a rejected PDF must not leave project rows behind.

#### Source.documents

```python
def documents(self, connection)
```

#### Source.after_document

```python
def after_document(self, connection, doc: SourceDoc) -> None
```

[Back to the index](../README.md)
