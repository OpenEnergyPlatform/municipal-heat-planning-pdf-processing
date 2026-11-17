# docpipe.inference.pages

`docpipe/inference/pages.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pages.py: A page index over the corpus, beside the vector index.

The passages of the corpus are searched by their transcription. Where the
transcription of a map or a chart does not hold the detail, the page itself
does. The page index embeds the image of each page of each document with the
corpus's multimodal embedder, so that a search sentence, embedded as the
harvest embeds it, can be compared with a page in the same space (owner
decision 2026-11-17, from the literature on searching the page image
directly: ColPali 2024, Nemotron ColEmbed V2 2026). A found page backs no
value: the passages that stand on it join the candidates of the search, and
the reading still needs a line that holds the value (the two checks stay).

The index is two files beside the corpus database, built from it and never
written into it (as the word index, `lexical.py`):

    <name>.pages.faiss   one vector per page
    <name>.pages.db      which document and page each vector is, and the
                         fingerprint

    docpipe pages DB          build it, or build it again
    docpipe pages DB --check  say whether it is there and current

The fingerprint is a digest over the model, the render size and the
documents the corpus database names (file, bytes, pages). An index of
another model, of another render size or of other documents is stale, and a
stale index is not asked: a page of a document that has since changed, or a
vector of another model, would be worse than none. An embedder that takes
text only cannot embed a page: the index says so and is not built.

Author: Felix Vossel

## Classes

### PageIndex

```python
class PageIndex
```

The pages of a corpus with a vector each, searched per document.

#### PageIndex.\_\_init\_\_

```python
def __init__(self, index, rows: dict)
```

#### PageIndex.documents

```python
def documents(self) -> list
```

#### PageIndex.search

```python
def search(self, vectors: Sequence, document: int,
           most: int) -> list
```

The page numbers of *document* that lie closest to any of
*vectors*, best first, at most *most*: the best score any sentence
gave a page decides where it stands (as the vector search of the
passages does).

## Functions

### faiss_path_for

```python
def faiss_path_for(db_path) -> Path
```

### path_for

```python
def path_for(db_path) -> Path
```

The small database of the page index (document, page, vector id).

### render_page

```python
def render_page(pdf: Path, page_number: int, dpi: int)
```

The image of page *page_number* (from 1) of *pdf*, as the
preprocessing renders a page (`rendering.render_page_to_pil`).

### build

```python
def build(db_path, *, pdf_root, dpi: int = DEFAULT_DPI, embedder=None,
          render: Optional[Callable] = None, model: Optional[str] = None,
          out: Optional[Path] = None,
          faiss_out: Optional[Path] = None) -> dict
```

Build the page index of a corpus database. Returns what it holds:
`documents`, `pages`, `skipped` (documents with no PDF, by file name)
and `failed` (pages the embedder could not serve).

### state

```python
def state(db_path, index_path: Optional[Path] = None, *,
          faiss_path: Optional[Path] = None, model: Optional[str] = None,
          dpi: Optional[int] = None) -> str
```

`current`, `stale` or `missing`. *model* is the model that embeds the
search sentences now (the configured one); *dpi* the render size asked
for (the index's own where None).

### connect

```python
def connect(db_path, index_path: Optional[Path] = None, *,
            faiss_path: Optional[Path] = None, model: Optional[str] = None,
            dpi: Optional[int] = None) -> Optional[PageIndex]
```

The page index of a corpus, or None when it is missing or stale. None
is said in the log, once, with what to do.

### passages_on

```python
def passages_on(corpus: sqlite3.Connection, document: int,
                pages: Sequence[int]) -> list
```

[(kind, id)] of the passages of *document* that stand on *pages*:
those of the first page first, on a page the sections, then the tables,
then the figures. A passage that spans pages (a section over
`SectionPages`, a table or figure over its `Segments`) stands on each of
them and is listed once.

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
