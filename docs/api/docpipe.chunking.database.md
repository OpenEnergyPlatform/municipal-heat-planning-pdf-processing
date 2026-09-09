# docpipe.chunking.database

`docpipe/chunking/database.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

database.py: Inserts sections, tables and images from merged data,
and writes FAISS embedding ids back to the database.

Documents themselves are populated by fileprocessing. The database
is the source of truth for what has been embedded and for FAISS id
allocation. Its schema lives only in the database file itself,
readable with `sqlite3 KWP.db .schema`: a checked-in copy of the
schema was removed because nothing read it, and an unchecked second
copy would only record what was once true.

Author: Felix Vossel

## Classes

### EmbeddingWriter

```python
class EmbeddingWriter
```

Writes FAISS ids for many batches and many documents over one connection.

Batches are packed by text length and straddle documents freely, so a
connection per (batch, document) pair came to roughly one connect, two
PRAGMAs and a document lookup per embedding. What a document's rows are
called cannot change while it is being embedded, so every lookup here is
read once per document and kept.

#### EmbeddingWriter.\_\_init\_\_

```python
def __init__(self, db_path: Path)
```

#### EmbeddingWriter.close

```python
def close(self) -> None
```

#### EmbeddingWriter.write

```python
def write(
    self,
    pdf_name: str,
    records: list[tuple[str, int, Optional[str], int]],
) -> None
```

Write one document's share of a batch; see write_embedding_ids_batch.

## Functions

### connect

```python
def connect(db_path: Path) -> sqlite3.Connection
```

Open a connection with foreign-key enforcement enabled.

### enrich_page_source

```python
def enrich_page_source(db_path: Path, root_dir: Path,
                       *, force: bool = False) -> dict
```

Record, per document, how many of its pages the MODEL read.

Eleven plans of the heat-plan corpus have no PDF text layer. Stage 1
renders those pages and a model transcribes them, and from there Stage 2,
Stage 3, refinement, chunking and embedding run unchanged and know nothing
about where the text came from. The section text of those plans is
therefore itself a model reading, and so is every quote verified against
it -- a passage can be found, be shown, and still be a transcription of
something the page did not say.

The count already exists: preprocessing writes it per document. It just
never reached the database, so nothing downstream could tell the two
kinds of plan apart. Additive, no model, one JSON read per directory.

### enrich_caption

```python
def enrich_caption(db_path: Path, *, force: bool = False) -> dict
```

Give every table and figure the sentence that names it. No model.

Stage 2 links a caption block to a table by distance and, in a plan whose
tables carry a rounding footnote, links the footnote: 15 of Kassel's 89
tables were captioned "Hinweis: Wegen der Rundung von Zahlenwerten ...".
The caption is the only line of a table a model can quote for the table's
own year, and 240 of 379 tuples from the twelve titled tables carried a
year read off another table's caption.

Stage 3 settles this at write time now, but the corpus was built before
that and re-preprocessing 1.082 plans costs GPU days. The rule is a pure
function of the section text and the placeholder, so it runs here over
the finished database instead: one pass, no model, additive.

`caption_source` records what happened to each row -- 'stage' when the
stored caption was kept, 'section_text' when it was replaced -- and is
the resume marker: without `force` a row that already has it is skipped,
so a second run updates nothing.

What it does not reach is the vectors. A table is embedded as caption +
markdown, and that text is built from the merged JSON, not from here, so
a row marked 'section_text' is a row whose stored vector still encodes
the footnote. It is not a regression -- the vector is the one that was
always there -- and what a reader and the model are shown is now right.
The vector follows when the plan is preprocessed again, where Stage 3
settles the caption before anything is embedded.

### update_database

```python
def update_database(
    db_path: Path,
    root_dir: Path,
    *,
    force: bool = False,
) -> None
```

Read merged output.json for each PDF and insert its sections, page
provenance, tables and images into the database.

Documents must already exist in the DB (created by fileprocessing).

### enrich_bbox

```python
def enrich_bbox(db_path: Path, root_dir: Path, *, force: bool = False) -> dict
```

Backfill the `bbox` column on existing Segments/Tables/Images rows from
Stage-3 outputs, updating that column only — no delete, re-embed or re-chunk.

Requires Stage 3 to have been re-run so each doc's sections.json
carries the geometry. `force` also re-derives rows that already have a bbox;
by default those are skipped, so a partial run resumes. Returns a stats dict
of updated counts.

### get_existing_embeddings

```python
def get_existing_embeddings(
    db_path: Path,
    pdf_name: str,
    *,
    doc_id: Optional[int] = None,
) -> set[tuple[str, int, Optional[str]]]
```

Items of this PDF that already have embeddings, as a set of
(embedding_type, section_index, item_id) — item_id is the table/figure
block id, None for section-level embeddings. Empty if the doc is unknown.

Runs on the calling thread's connection. Pass `doc_id` when the caller has
already resolved it — the prepare loop asks document_id() first.

### clear_embedding_ids

```python
def clear_embedding_ids(db_path: Path, pdf_name: str) -> list[int]
```

Clear all embeddings for a given PDF and return the old FAISS IDs so they
can be removed from the index.

### get_document_faiss_ids

```python
def get_document_faiss_ids(db_path: Path, pdf_name: str) -> list[int]
```

Read-only snapshot of every FAISS id currently mapped to a document; [] if
the doc is unknown.

Must be called BEFORE the db step's --force delete removes the Embeddings
rows, or the ids are gone and their vectors are orphaned in the index.

### document_id

```python
def document_id(db_path: Path, pdf_name: str) -> Optional[int]
```

The Documents row id for this processed directory, or None.

Asked BEFORE embedding: a directory whose document was never registered
(renamed in the register, an import that failed, a leftover from an older
corpus) produces perfectly good vectors that no row can ever point at.

Shares the calling thread's connection with get_existing_embeddings, which
the prepare loop calls straight afterwards.

### drop_embeddings_missing_from_index

```python
def drop_embeddings_missing_from_index(db_path: Path, known_ids) -> int
```

Delete Embeddings rows whose vector is not in the index. Returns the count.

A DB row is written per batch, the index is persisted per flush chunk, so a
crash between the two (an OOM kill, a node failure, a timeout) leaves rows
pointing at vectors that never reached the file. The next run reads those
rows as "already embedded" and skips the item forever: the DB says it is
searchable, the index has nothing, and no error is ever raised. Reconciling
at startup turns that silent hole into re-work.

An EMPTY index is not treated as "nothing is embedded" — that is what a
mistyped index path looks like, and it would delete every row in the
database. It is refused loudly instead.

### next_faiss_id

```python
def next_faiss_id(db_path: Path) -> int
```

Smallest FAISS id not currently claimed by any Embeddings row.

Seed id allocation from here, not from index.ntotal: ntotal is a live count
and can dip below the high-water mark after an eviction, so it hands back an
id another row still holds and the faiss_id PK rejects the insert.

### write_embedding_ids_batch

```python
def write_embedding_ids_batch(
    db_path: Path,
    pdf_name: str,
    records: list[tuple[str, int, Optional[str], int]],
) -> None
```

Write FAISS embedding ids to the DB in one transaction.

`records` are (embedding_type, section_index, item_id, faiss_id); item_id is
the table/figure block id, None for sections. Records whose owner row
cannot be resolved are skipped and counted — the vector is already in the
FAISS index, so skipping one means index and database have drifted apart,
which is worth a line in the log rather than silence.

One-shot wrapper. The embed loop keeps a single EmbeddingWriter for the
whole chunk instead of reconnecting per batch and document.

[Back to the index](../README.md)
