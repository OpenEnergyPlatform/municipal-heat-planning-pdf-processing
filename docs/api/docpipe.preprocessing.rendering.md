# docpipe.preprocessing.rendering

`docpipe/preprocessing/rendering.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

rendering.py: Renders the pages of a PDF as images, in this process or in
worker processes.

MuPDF is not thread-safe within a process: every fitz call that renders or
reads a page goes through FITZ_LOCK, and a page rendered here waits for it.
On 3,254 pages of the KWP corpus, one core took 0.125 s per page for Stage
1's text and Stage 2's two renders, 0.087 s of it the 300 dpi render for the
crops, while a whole page through Stage 1-3 took 0.150 s. A worker process
opens the PDF itself and renders whole pages exactly as `render_page_to_pil`
does, at the same resolutions, so the pages of a batch render side by side on
as many cores as the job has.

A worker imports only fitz and PIL, so it loads in a moment.

## Functions

### render_page_to_pil

```python
def render_page_to_pil(page: fitz.Page, dpi: int) -> Image.Image
```

Renders a fitz.Page to a PIL RGB image in memory without any disk I/O.

### as_image

```python
def as_image(rendered: tuple) -> Image.Image
```

A page `render_page` rendered in a worker, as `render_page_to_pil`
returns it.

### render_page

```python
def render_page(path: str, number: int, dpis: tuple) -> dict | str
```

{dpi: (width, height, RGB bytes)} of page *number* of *path* at each of
*dpis*, or the text of the error that stopped it.

### pool

```python
def pool(size: int) -> cf.ProcessPoolExecutor
```

The process's pool of *size* workers, kept for every later document.

Started with spawn: a fork would copy the CUDA context and the locks of
the model's threads. A spawned worker imports the main program again, as
Python does for every start method but fork, so the main program must be
importable without running: every `__main__.py` of docpipe is guarded,
and a program read from stdin cannot start workers at all.

### batches

```python
def batches(path: str, numbers: Iterable[list], dpis: tuple, size: int,
            depth: int) -> Iterator[list]
```

For each list of page numbers in *numbers*, in order, the list of what
`render_page` gave for its pages. While a batch is read, at most
*depth* + 1 batches after it are rendering or held, as with the prefetch
thread's queue of *depth* and the batch it renders.

[Back to the index](../README.md)
