# docpipe.ingest.pipeline

`docpipe/ingest/pipeline.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pipeline.py: Registers a profile's documents in its database.

The core repeats four steps for every corpus: it fetches the file,
checks its text layer, writes the Documents row, and links versions.
A file whose text is unreadable or garbled is refused and left out
of the corpus. A file with no text layer at all is registered
anyway and listed for preprocessing to read with the vision model,
because the pages exist to be read. What the documents are and
where they come from is defined by the profile's Source.

Author: Felix Vossel

## Functions

### register

```python
def register(doc: SourceDoc, connection: sqlite3.Connection, data_dir: Path,
             *, scans: Optional[dict] = None) -> bool
```

Fetch and register one document. False if it was already in the DB.

`scans` collects the documents that carry no text layer, keyed by filename.
They ARE registered: preprocessing reads their pages with the model. They are
collected so the run can say which documents depend on that.

### note_content

```python
def note_content(filename: str, connection: sqlite3.Connection,
                 data_dir: Path) -> None
```

Record which bytes a document is, or say that they are others now.

A new row gets the sha256 and the size of its file. So does a row from
before this was recorded, once. A row that has them is held against the
size of the file as it lies there: a different size is a different file
under the old name, and everything produced from the old one (sections,
vectors, harvest) is of the old one. That is said, and nothing is
stopped; a file edited to the same length is not seen here.

### ingest

```python
def ingest(source, db_file: Path, data_dir: Path,
           profile: Optional[Profile] = None) -> dict
```

Run a profile's source into its database. Returns the refused files.

[Back to the index](../README.md)
