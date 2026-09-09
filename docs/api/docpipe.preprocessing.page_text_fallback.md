# docpipe.preprocessing.page_text_fallback

`docpipe/preprocessing/page_text_fallback.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

page_text_fallback.py: Synthesizes text blocks for pages that carry
no usable PDF text layer.

Stage 1 reads the PDF's own text layer. Some plans have none: the
pages are vector graphics or images end to end, get_text returns
nothing, and every section Stage 3 assembles from them is a body of
bare [pNN_tbl0] markers. Eleven plans in the heat-plan corpus are
like that, together holding 1270 tables and figures that Stage 2
transcribed and that then had no text to explain them
(tests/test_page_text_fallback.py).

This module fills the gap at the level where it opens: a page's text
blocks. The page is rendered, one model call transcribes it, and the
reply becomes Block(type="text") entries on the same PageData every
other page carries. Stage 2, Stage 3, refinement, chunking and
embedding then run unchanged and read nothing about where the text
came from.

Each call does one job. Transcription is not cleanup: the model is
asked to read what is on the page and nothing else, and refinement
does its own work afterward, in its own calls. Asking for both at
once is how a model starts inventing the tidy version of a page it
cannot quite read.

The model call is an injected callable, so the loop, the thresholds
and the block synthesis are testable without a GPU.

Author: Felix Vossel

## Functions

### page_text_length

```python
def page_text_length(page: PageData) -> int
```

Characters of real text Stage 1 found on this page.

### needs_transcription

```python
def needs_transcription(page: PageData, min_chars: int = MIN_PAGE_CHARS) -> bool
```

True if this page's text layer is missing or too thin to be real.

### split_into_blocks

```python
def split_into_blocks(markdown: str) -> list[str]
```

A transcription split into the blocks Stage 3 will reason over.

Blank lines separate blocks, and a heading always starts one: Stage 3 finds
section titles by font size and boldness, neither of which survives a
transcription, so a heading has to arrive as its own block to have any
chance of being recognised as one.

### synthesize_blocks

```python
def synthesize_blocks(page: PageData, markdown: str,
                      prefix: Optional[str] = None) -> list[Block]
```

Transcribed text as Block objects, stacked down the page's text area.

The boxes are APPROXIMATE and say so: `bbox_approx` rides on every block so
that nothing downstream presents a synthesized rectangle as a measured one.
A highlight drawn from it points at the right page and the right region,
which is what a reader needs, but it is not a located line and must never
be counted as one.

A markdown heading becomes a block labelled `paragraph_title`, because that
label - not the font size - is what Stage 3 opens a section on
(SECTION_TITLE_CLASSES). Sizes and boldness are set as well, for the rules
further up that read them, but the label is the part that decides. Getting
this wrong put every transcribed page back into one pseudo-section, which
is the exact failure this module exists to end.

### fill_missing_page_text

```python
def fill_missing_page_text(
    pages: list[PageData],
    render: Callable[[int], object],
    transcribe: Callable[[object, int], Optional[str]],
    *,
    min_chars: int = MIN_PAGE_CHARS,
    max_pages: Optional[int] = None,
    workers: int = 1,
    render_workers: int = PAGE_RENDER_WORKERS,
) -> dict
```

Transcribe every page whose text layer is missing. Mutates *pages*.

`render(page_number)` returns whatever the transcriber takes (a PIL image
in the live wiring), `transcribe(image, page_number)` returns the page as
markdown, an empty string if the page carries no prose, or None if the call
failed. A page that yielded nothing keeps its empty text layer rather than
an invented one.

Returns a report: how many pages needed text, how many got it, how many had
nothing to give, how many broke, and how many blocks were synthesized. The
counts are the honest answer to "how much of this document is model-read
rather than PDF-read".

`pages_empty` and `pages_failed` are counted apart on purpose. A heat plan
is full of pages that are one large map, and the prompt tells the model to
return an empty string for those. Booking them as failures said 106 broken
calls for a run in which not one call broke.

### make_page_renderer

```python
def make_page_renderer(pdf_path, scratch_dir=None)
```

render(page_number) -> path of the rendered page PNG.

Written to disk rather than held in memory: the call layer takes a path.
Into scratch by default, NOT next to the document: a full page at
RENDER_DPI is about a megabyte, and a corpus-wide run would leave gigabytes
of them behind for nothing. The page is reproducible from the PDF at any
time, so the transcription is what is worth keeping, not the picture.

$TMPDIR is respected, which on the cluster is the job's own tmpfs.

### make_transcriber

```python
def make_transcriber(profile, *, client=None, model=None)
```

transcribe(image_path, page_number) -> markdown, or None on failure.

ONE job: read the page. No cleaning, no summarising, no restructuring —
refinement does that afterwards, in its own calls, on its own terms. The
prompt lives in the profile because what a page holds and in which language
is project knowledge, while "a page with no text layer needs reading" is not.

[Back to the index](../README.md)
