# docpipe.ingest.pdf_info

`docpipe/ingest/pdf_info.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pdf_info.py: What a PDF says about itself in its information dictionary.

The software that wrote a PDF usually put the document's title and its
creation date into the file. A folder of PDFs has no register to say what
they are called, so this is the one place to learn it. A dictionary that is
empty, or says neither, gives nothing; so does one that cannot be read, and
that is said, once, in the log. Nothing here decides whether a document is
usable: the text layer is graded by pdf_quality.

Author: Felix Vossel

## Functions

### parse_date

```python
def parse_date(text) -> Optional[str]
```

A PDF date as far as it is given: YYYY, YYYY-MM or YYYY-MM-DD.

None for no date, for a text that is not written the way the PDF
specification writes one, and for a date that is not on the calendar.

### from_metadata

```python
def from_metadata(metadata) -> dict
```

{"title": ..., "created": ...} from PyMuPDF's metadata dictionary.

A key the dictionary does not say is not in the result.

### read

```python
def read(path) -> dict
```

What the information dictionary of the PDF at *path* says, as
`from_metadata`; {} when it says nothing and when it cannot be read.

[Back to the index](../README.md)
