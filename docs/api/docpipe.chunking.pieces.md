# docpipe.chunking.pieces

`docpipe/chunking/pieces.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pieces.py: The entries of the index are the pieces the harvest reads (owner
decisions 2026-11-17: "Die Einträge im Index sind die Stücke der Ernte";
"**Nichts** kürzen, einfach ggf. clever aufteilen und darauf achten, dass
die Zuordnung zu Sektion und Seite etc. nicht verlieren gehen").

A section, a table and a figure become a passage of numbered lines as the
harvest makes it: the text as the harvest is given it (`runner._source_of`:
the heading, or the caption, in front where the text does not open with it;
a placeholder in a section named by its caption, as `inference.db` shows
it), cut into lines by `extraction.units.passage_of` and into pieces of the
flow's `piece_lines` lines by `units.chunks_of`. One entry is one piece:

- of a section: its heading and its own lines, eight sentences;
- of a table: its title, head and the lines under it, the rows its own
  rows stand under (indented under, or grouped by a group row), and its
  own rows;
- of a figure: its caption and the lines of its description;

and a table's or figure's entries begin with its context sentence, where
the rule `context_sentence` gave one (the sentence of the part of the table
the piece's rows stand in, `context.lead_of`).

Each entry knows which piece it is (as the harvest counts them), its own
first and last line, and its page: a table's or figure's own page, a
section piece's the page its first own line stands on in the section's
segments, the text as the PDF gave it page by page (`line_pages`).

An entry that does not fit the embedder's window is split into parts
(`IndexPiece.parts`, `docpipe.window.split`): each part shows every line its
piece carries, and its own lines as many as fit; nothing is cut.

Author: Felix Vossel

## Classes

### IndexPiece

```python
@dataclass
class IndexPiece
```

One piece of a passage as an entry of the index: its *chunk*
(`units.Chunk`), the *lead* in front of it (a context sentence and its
line break, or ""), the *heading* a section piece shows where its own
lines do not hold it, and the page each of its passage's lines stands
on (*pages*, by line number).

Fields:

- `chunk: units.Chunk`
- `lead: str = ""`
- `heading: str = ""`
- `pages: Optional[dict] = None`

#### IndexPiece.index

```python
@property
def index(self) -> int
```

#### IndexPiece.passage

```python
@property
def passage(self) -> units.Passage
```

#### IndexPiece.render

```python
def render(self, numbers=None, replaced: Optional[dict] = None) -> str
```

The entry's text: the lead, the heading where the lines shown do
not hold it, the lines shown of the own lines *numbers* (all where
None), a line in *replaced* as the text given there.

#### IndexPiece.text

```python
def text(self) -> str
```

#### IndexPiece.page_of

```python
def page_of(self, numbers=None)
```

The page the first of the own lines *numbers* stands on, else
the passage's.

#### IndexPiece.first_last

```python
def first_last(self, numbers=None) -> tuple
```

#### IndexPiece.parts

```python
def parts(self, fits: Callable[[str], bool], name: str = "") -> list
```

[window.Part] of this entry, each of which *fits*: the whole
where it fits, else its own lines as many as fit with every line
it carries, a line that does not fit alone at its sentences, then
its words (`window.split`). A piece of carried lines alone is one
part, or `window.TooLong`.

## Functions

### piece_lines

```python
def piece_lines() -> int
```

How many lines a piece holds: the number `piece_lines` of the flow of
the profile in force, as the harvest reads it.

### section_content

```python
def section_content(section: dict) -> str
```

### captions_of

```python
def captions_of(section: dict, resolve: Optional[Callable] = None) -> dict
```

{block id: caption} of the tables and figures of a merged section,
each as the database holds it: the item's caption resolved by *resolve*
(caption, section text, block id), `captions.resolve_title` where none
is given, as the database step resolves it.

### as_held

```python
def as_held(caption, content, block)
```

A caption as it stands: one the database already holds, resolved
once before (`captions_of`).

### section_source

```python
def section_source(section: dict, captions: dict) -> Source
```

### item_source

```python
def item_source(kind: str, section: dict, item: dict, captions: dict
                ) -> Source
```

### line_pages

```python
def line_pages(texts: list, section: dict) -> list
```

The page each of a section's lines *texts* stands on: the page of
the segment (the PDF's text of the section, page by page) where its
words are found, searched from where the line before was found; a
placeholder line on its table's or figure's page; a line not found on
the page of the line before it, the first on the section's page.

### section_pieces

```python
def section_pieces(section: dict, captions: dict, size: int) -> list
```

[IndexPiece] of a merged section's text, in order. A section whose
text is nothing but its heading has none (its title has a vector of its
own).

### item_pieces

```python
def item_pieces(kind: str, section: dict, item: dict, captions: dict,
                size: int, lead_of: Callable) -> list
```

[IndexPiece] of a merged table or figure, in order, each with the
lead *lead_of(item, first line, last line)* gives it.

[Back to the index](../README.md)
