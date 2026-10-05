# docpipe.ingest.fetch

`docpipe/ingest/fetch.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

fetch.py: Downloads a source PDF to disk and counts its pages.

download_pdf sends a configurable User-Agent (a browser's by default, because
municipal sites answer a default requests client with 403) and streams the
body into a temporary file in the data directory, so a PDF is never held in
memory whole and a killed job leaves no partial file for a later run to
reuse. A body over the size limit is refused with its size. A file is named
after the last segment of its URL, so two URLs can claim one name: the URL a
file came from is kept beside it, and a second, different URL for that name
is refused with both named, instead of being read from the first one's
bytes. get_num_pages and download_pdf both check the file for a %PDF header
before handing it to PyMuPDF, which can segfault on a truncated or non-PDF
file rather than raise.

Author: Felix Vossel

## Classes

### DownloadRefused

```python
class DownloadRefused(OSError)
```

A download that was not kept. An OSError, so that ingest lists it with
the other files it could not fetch and goes on.

### NameTaken

```python
class NameTaken(DownloadRefused)
```

Two different URLs end in one file name.

### TooLarge

```python
class TooLarge(DownloadRefused)
```

A body over the size limit.

## Functions

### user_agent

```python
def user_agent() -> str
```

The User-Agent a download sends: the setting, else its default.

### max_download_bytes

```python
def max_download_bytes() -> int
```

The size limit of one download, in bytes.

### filename_for

```python
def filename_for(url: str) -> str
```

The name a download of *url* will be saved under (lowercased).

### source_file

```python
def source_file(filename: str, data_dir: Path) -> Path
```

Where the URL of a downloaded file is kept.

### source_of

```python
def source_of(filename: str, data_dir: Path) -> Optional[str]
```

The URL *filename* was downloaded from, None if nobody wrote it down
(a file put there by hand, or downloaded before this was kept).

### check_name

```python
def check_name(filename: str, url: str, data_dir: Path) -> None
```

Raise NameTaken if *filename* in *data_dir* came from another URL.

A name is taken by a file that is there. The URL a killed job left
beside a file that never arrived holds nothing, and the next download
of that name overwrites it.

### download_pdf

```python
def download_pdf(url: str, data_dir: Path) -> str
```

Download `url` into `data_dir` and return the saved filename (lowercased).

A no-op returning the existing name if the file is already there and came
from this URL. Raises NameTaken if it came from another one, TooLarge if
the body is over the size limit, requests.HTTPError on a failed request
and IOError if the response is not a PDF.

### get_num_pages

```python
def get_num_pages(filename: str, data_dir: Path) -> int
```

Page count of `data_dir / filename`.

Raises IOError if the file is not a PDF, FileNotFoundError if it is missing.

[Back to the index](../README.md)
