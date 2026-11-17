# docpipe.chunking.chunking

`docpipe/chunking/chunking.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

chunking.py: Builds embedding inputs from merged section data.

The entries of the index are the pieces the harvest reads (owner decisions
2026-11-17, `pieces.py`): for each section its title, and its pieces, each
its heading and its lines; for each table and figure its pieces, each a text
input and, when its picture exists on disk, a vision-language input of the
picture and the same text. A table or figure placeholder inside a section's
text is named by the item's caption, as the harvest shows it.

Every input knows which piece of its owner it is, its own first and last
line and its page. Nothing is cut: an input that does not fit the
embedder's window is split into parts, each with the lines its piece
carries (`fit_inputs`, `docpipe.window`).

Author: Felix Vossel

## Classes

### EmbeddingInput

```python
@dataclass
class EmbeddingInput
```

A single item to be embedded; ``image`` is set only for VL inputs.

*piece* is which piece of its owner it is, as the harvest counts them
(0 for a section's title), *part* which part of that piece where the
piece did not fit the embedder's window; *page* the page its first own
line stands on, *first_line* and *last_line* its own lines as the
harvest numbers its passage (None for a title, or a piece of carried
lines only). *unit* is the piece it was made of, for splitting it.

Fields:

- `embedding_type: str`
- `pdf_name: str`
- `section_index: int`
- `item_id: Optional[str]`
- `text: str`
- `image: Optional[str] = None`
- `piece: Optional[int] = None`
- `part: int = 0`
- `page: Optional[int] = None`
- `first_line: Optional[int] = None`
- `last_line: Optional[int] = None`
- `unit: object = field(default=None, repr=False, compare=False)`

#### EmbeddingInput.key

```python
@property
def key(self) -> tuple
```

What names it among a document's inputs.

## Functions

### build_embedding_inputs

```python
def build_embedding_inputs(
    merged_data: dict,
    pdf_name: str,
    output_dir: Path,
    *,
    log_counts: bool = True,
    size: Optional[int] = None,
    resolve: Optional[Callable] = None,
) -> list[EmbeddingInput]
```

Build the section/table/figure embedding inputs (text + VL), one per
piece, for one PDF; each whole, before any split (`fit_inputs`).

`output_dir` is the base for resolving each item's image path; VL inputs are
only emitted for images that exist on disk. Returns [] if nothing qualifies.
`log_counts` False leaves out the line that counts them, for a caller that
builds them only to compare (chunking/sync.py). *size* is the lines of a
piece, the flow's `piece_lines` where not given. *resolve* gives a table's
or figure's caption as the database holds it (`pieces.captions_of`); a
caller whose document already holds those passes `pieces.as_held`.

### fit_inputs

```python
def fit_inputs(inputs: list, fits: Callable[[str, Optional[str]], bool],
               unfit: Optional[Callable] = None) -> list
```

*inputs* each split into the parts that fit the embedder's window:
*fits(text, picture)* says whether a text with its picture fits. An
input that fits is kept as it is (part 0); one that does not is split
by its piece (`pieces.IndexPiece.parts`), each part with every line its
piece carries, the parts numbered from 0 with their own lines and the
page of their first line. An input without a piece to split by, or
whose carried lines alone do not fit (`window.TooLong`), is handed to
*unfit(input, reason)* and left out: it is never cut.

[Back to the index](../README.md)
