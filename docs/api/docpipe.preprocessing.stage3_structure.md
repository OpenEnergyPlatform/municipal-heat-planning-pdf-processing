# docpipe.preprocessing.stage3_structure

`docpipe/preprocessing/stage3_structure.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

stage3_structure.py: Assembles document sections deterministically
from pages that carry the layout labels Stage 2 attached.

Walks every block in reading order. A block labelled as a section
title opens a new Section; a table or figure block becomes a
TableRef or FigureRef plus a [block_id] placeholder in the section
content; plain text is appended as prose. Reading order across a
multi-column page is settled first, by columns.sort_pages.

Two passes run before assembly. strip_running_headers drops text
blocks whose page-number-normalized text recurs in the same header
or footer band on enough pages to be a running header or footer,
without touching a section title. drop_directory_sections removes
table-of-contents, list-of-figures and index sections by scoring how
much of a section's text is directory-listing entries, while keeping
a section that still references a real table or figure and routing a
bibliography title to the Stage 4 literature path instead of
dropping it.

A table's or figure's caption is settled during assembly, where the
section text and its placeholder are both available: resolve_title
(docpipe.captions) chooses between the caption block Stage 2 attached
by distance and a nearby sentence in the section text, for plans
whose tables carry a rounding footnote that would otherwise be read
as the caption.

Author: Felix Vossel

## Functions

### strip_running_headers

```python
def strip_running_headers(pages: list[PageData]) -> int
```

Drop text blocks whose page-number-normalized text recurs in the same
header/footer zone on at least HEADER_FOOTER_MIN_PAGE_FRAC of the pages.
Section titles are never touched. Mutates *pages* in place; returns the
number of blocks dropped.

### drop_directory_sections

```python
def drop_directory_sections(sections: list[Section]) -> tuple[list[Section], int]
```

Remove directory/index sections; returns (kept_sections, dropped_count).

### build_sections

```python
def build_sections(pages: list[PageData], column_layout: str = "auto") -> list[Section]
```

Assembles a flat list of Section objects from the annotated pages.

Each title block opens a Section; a synthetic "Dokument" section catches
content before the first title. Section.content carries [block_id] markers
where a table or figure appears in the reading order.

A table's caption is settled here, where the section text and the
placeholder are both in hand. Stage 2 links a caption block by distance,
and in a plan whose tables carry a rounding footnote it links the
footnote: 15 of Kassel's 89 tables were captioned "Hinweis: Wegen der
Rundung von Zahlenwerten ..." while the sentence naming them stood in the
text a few words before their own placeholder. `resolve_title` takes it
from there and leaves a caption that already opens like one alone. The
sentence stays in the section content: a quote of it has to remain
findable where it was read.

*column_layout* (from the profile: auto | single | double) decides whether a
page is read as one column or column by column.

Note: mutates *pages* (blocks are put in reading order and running
headers/footers are stripped, both in place).

### sections_to_dict

```python
def sections_to_dict(sections: list[Section]) -> dict
```

Serialises the section list into the final output JSON structure.

### save_output

```python
def save_output(sections: list[Section], output_dir: Path) -> Path
```

Writes the Stage 3 JSON under *output_dir* and returns its path.

[Back to the index](../README.md)
