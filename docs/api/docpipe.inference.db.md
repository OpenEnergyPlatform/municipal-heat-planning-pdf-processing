# docpipe.inference.db

`docpipe/inference/db.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

db.py – The queries retrieval needs: which vectors belong to a document, and
what text sits behind a hit. Nothing here knows what the documents are about.

Author: Felix Vossel

## Functions

### connect_readonly

```python
def connect_readonly(db_path: Path) -> sqlite3.Connection
```

Open a read-only connection to a corpus database.

The `mode=ro` URI keeps the app from ever writing to the authoritative
database or taking a write lock that would contend with the batch pipeline
running against the same file.

### get_candidate_faiss_ids

```python
def get_candidate_faiss_ids(
    conn: sqlite3.Connection,
    document_id: int,
    embedding_types: list[str],
) -> list[tuple[int, str, str, int]]
```

Every (faiss_id, embedding_type, owner_kind, owner_id) belonging to
`document_id` whose embedding_type is in `embedding_types`, across all three
owner kinds (section / table / figure). Empty list if no type matches.

sqlite3 cannot bind a list into `IN (...)`, so the placeholder lists are
built per branch and the parameters flattened.

### section_item_captions

```python
def section_item_captions(conn: sqlite3.Connection, section_id: int,
                          content: Optional[str] = None) -> dict[str, str]
```

block_id -> caption for every table and figure anchored in this section.

With the section's own text in hand a caption Stage 2 failed to link is
resolved from the sentence before the placeholder — the same rule
fetch_owner_content uses, so the name a reader sees in the section and the
title the table itself carries are one string and not two.

### annotate_placeholders

```python
def annotate_placeholders(content: str, captions: dict[str, str]) -> str
```

Name the figure a placeholder stands for: [p17_img1] → [p17_img1: Abbildung 2-3 …].

The stored content keeps the bare id, which is right for the record but
useless to a reader: the section says "wie Abbildung 2-3 verdeutlicht" and
then shows a token that could be anything. The id stays, because it is the
handle the model uses to ask for the picture itself (see request_item).

### request_item

```python
def request_item(conn: sqlite3.Connection, document_id: Optional[int],
                 block_id: str) -> Optional[dict]
```

Look up one table/figure by the placeholder id the model quoted.

Scoped to `document_id`: block ids are only unique within a document, and
p17_img1 exists in nearly every plan.

### fetch_owner_content

```python
def fetch_owner_content(
    conn: sqlite3.Connection,
    owner_kind: str,
    owner_id: int,
) -> Optional[dict]
```

Fetch displayable content + citation fields for one retrieved owner.

Returns a uniform dict:
    {owner_kind, owner_id, title, text, page_number, image_path,
     section_number, section_title, document_id}
image_path is None for section owners; for table/figure owners it is the crop
path made RELATIVE TO IMAGE_ROOT. None if the row does not exist. Raises
ValueError on an unknown owner_kind.

### document_filename

```python
def document_filename(conn: sqlite3.Connection, document_id: Optional[int]) -> Optional[str]
```

The stored PDF filename for a document (used to build the source-PDF link).

### section_segments

```python
def section_segments(
    conn: sqlite3.Connection, section_id: int
) -> list[tuple[int, str]]
```

Raw, page-tagged text segments of a section (pre-refinement provenance):
[(page_number, text), ...] in reading order, kind 'text' only. These carry
the verbatim PDF-text-layer wording a `&search=` highlight must match, which
the refined Sections.content may not. See pdf_link.locate_quote.

NB `Segments.page` is a foreign key to `Pages.id`, NOT the human page number,
so it is joined to `Pages` to return the real 1-based `page_number` the PDF
viewer's `#page=` expects.

### section_segments_geo

```python
def section_segments_geo(
    conn: sqlite3.Connection, section_id: int
) -> list[tuple[int, str, Optional[list]]]
```

Like `section_segments`, but each triple also carries the segment's stored
`bbox`: a list of [x0, y0, x1, y1] rectangles in PDF points (top-left
origin), or None. See pdf_link.best_segment_rects.

On a pre-bbox database (no `bbox` column) every rects slot is None, so the
caller falls back to the `&search=` phrase highlight.

[Back to the index](../README.md)
