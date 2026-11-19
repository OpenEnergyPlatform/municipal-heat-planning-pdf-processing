# docpipe.visuals.strips

`docpipe/visuals/strips.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

strips.py: A table image whose transcription does not fit its reply, read in
strips (owner request 2026-11-19, on the rule of 2026-09-12 that a request
whose reply does not fit its limit is split and its reply never salvaged, and
on that of 2026-11-17: "Nichts kürzen, einfach ggf. clever aufteilen").

The image is cut where a pixel row carries no writing, between two rows of the
table and never through one: in the run of blank pixel rows nearest its middle
that has writing above and below. The first strip is asked as the whole table
was; each later strip as a part that continues it, with the prompt of a table
that may continue the table before it, shown the caption and head the table
was read with. A strip whose reply is cut off again is cut again; one with no
blank row left between writing has no halves, and then the table has no
content (`reading.Hole` "cut_off"), as before. The table is the first strip's
reply with the rows of every later strip under its head
(`continuation.body_rows`), as the merge joins the parts of a table the layout
cut (`continuation.join`).

Author: Felix Vossel

## Functions

### ink_rows

```python
def ink_rows(image) -> list
```

For each pixel row of *image* (a PIL image), how many of its pixels
are writing: darker by strip_ink_contrast than both what their column
holds in most rows and what their own row holds in most columns. A rule
across the table (a row of one colour), a shaded row and a vertical rule
(a column of one colour, also where a scan tilts it by up to
strip_rule_drift pixels) are no writing.

### cut_at

```python
def cut_at(ink: list) -> Optional[int]
```

The pixel row to cut an image with these *ink* rows (`ink_rows`) at:
the middle of the run of blank rows (at most strip_blank_pixels pixels of
writing) nearest the image's middle that has writing right above and
right below it; None where there is no such run.

### halves

```python
def halves(png: bytes) -> Optional[tuple]
```

The image *png* cut in two at `cut_at`, as two PNGs, top first; None
where it has no blank row between writing to cut at.

### height_of

```python
def height_of(png: bytes) -> int
```

The height of the image *png* in pixels.

### read

```python
def read(png: bytes, ask: Ask, name: str = "") -> tuple
```

(reply or Hole, requests) of a table image *png* read in strips.

*ask(strip, first)* is one request for a strip: *first* is None for the
first strip, which is asked as the whole table was, else the reply of the
first strip, whose caption and head a later strip is shown. The reply is
the first strip's with the rows of each later strip that stand under its
head, and "strips", how many strips it was read in. A Hole of another
cause than "cut_off" ends the reading with that hole; a strip cut off
again is cut again, and one that cannot be cut is the Hole "cut_off".

### strip_of

```python
def strip_of(png: bytes, sha: str, most: int = 4096) -> Optional[bytes]
```

The strip of the table image *png* whose sha256 is *sha*, cut from
it as `read` cuts one (the image itself, a half, a half of a half, ...),
so that a request the stage's log names by its strip is sent again with
the same picture (owner request 2026-11-19, A3); None where no cut of at
most *most* gives it.

[Back to the index](../README.md)
