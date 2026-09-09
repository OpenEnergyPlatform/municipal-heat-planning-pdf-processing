# docpipe.ingest.fetch

`docpipe/ingest/fetch.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

fetch.py: Downloads a source PDF to disk and counts its pages.

download_pdf sends a browser User-Agent, because municipal sites answer a
default requests client with 403, and writes the response through a temporary
file before the atomic rename, so a killed job leaves no partial PDF for a
later run to reuse. get_num_pages and download_pdf both check the file for a
%PDF header before handing it to PyMuPDF, which can segfault on a truncated or
non-PDF file rather than raise.

Author: Felix Vossel

## Functions

### filename_for

```python
def filename_for(url: str) -> str
```

The name a download of *url* will be saved under (lowercased).

### download_pdf

```python
def download_pdf(url: str, data_dir: Path) -> str
```

Download `url` into `data_dir` and return the saved filename (lowercased).

A no-op returning the existing name if the file is already there. Raises
requests.HTTPError on a failed request and IOError if the response is not a
PDF.

### get_num_pages

```python
def get_num_pages(filename: str, data_dir: Path) -> int
```

Page count of `data_dir / filename`.

Raises IOError if the file is not a PDF, FileNotFoundError if it is missing.

[Back to the index](../README.md)
