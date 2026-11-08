"""
render_pool.py: Renders the pages of Stage 2 in worker processes.

MuPDF is not thread-safe within a process, so Stage 2 renders behind one lock
(`stage2_layout._FITZ_LOCK`) and the GPU waits for it: on 3,254 pages of the
KWP corpus, one core took 0.125 s per page for Stage 1's text and Stage 2's
two renders, 0.087 s of it the 300 dpi render for the crops, while a whole
page through Stage 1-3 took 0.150 s. A worker here opens the PDF itself and
renders whole pages exactly as `stage1_extract._render_page_to_pil` does, at
the same resolutions, so the pages of a batch render side by side on as many
cores as the job has.

Only fitz is imported, so a worker loads in a moment.
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import itertools
import multiprocessing as mp
from typing import Iterable, Iterator, Optional

import fitz

# In a worker: the one document it has open, by path.
_OPEN: dict = {}


def _document(path: str) -> fitz.Document:
    doc = _OPEN.get(path)
    if doc is None:
        for old in _OPEN.values():
            old.close()
        _OPEN.clear()
        doc = _OPEN[path] = fitz.open(path)
    return doc


def render_page(path: str, number: int, dpis: tuple) -> dict | str:
    """{dpi: (width, height, RGB bytes)} of page *number* of *path* at each of
    *dpis*, or the text of the error that stopped it."""
    try:
        page = _document(path)[number]
        out = {}
        for dpi in dpis:
            zoom = dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            out[dpi] = (pix.w, pix.h, pix.samples)
        return out
    except Exception as e:                    # noqa: BLE001 — reported per page
        return f"{type(e).__name__}: {e}"


_POOL: Optional[cf.ProcessPoolExecutor] = None
_POOL_SIZE = 0


def pool(size: int) -> cf.ProcessPoolExecutor:
    """The process's pool of *size* workers, kept for every later document.

    Started with spawn: a fork would copy the CUDA context and the locks of
    the model's threads. A spawned worker imports the main program again, as
    Python does for every start method but fork, so the main program must be
    importable without running: every `__main__.py` of docpipe is guarded,
    and a program read from stdin cannot start workers at all."""
    global _POOL, _POOL_SIZE
    if _POOL is None or _POOL_SIZE != size:
        if _POOL is not None:
            _POOL.shutdown()
        _POOL = cf.ProcessPoolExecutor(size, mp_context=mp.get_context("spawn"))
        _POOL_SIZE = size
    return _POOL


def batches(path: str, numbers: Iterable[list], dpis: tuple, size: int,
            depth: int) -> Iterator[list]:
    """For each list of page numbers in *numbers*, in order, the list of what
    `render_page` gave for its pages. While a batch is read, at most
    *depth* + 1 batches after it are rendering or held, as with the prefetch
    thread's queue of *depth* and the batch it renders."""
    ex = pool(size)
    pending: collections.deque = collections.deque()
    todo = iter(numbers)

    def submit(batch: list) -> None:
        pending.append([ex.submit(render_page, path, n, dpis) for n in batch])

    for batch in itertools.islice(todo, max(depth, 0) + 1):
        submit(batch)
    while pending:
        futures = pending.popleft()
        done = [f.result() for f in futures]
        following = next(todo, None)
        if following is not None:
            submit(following)
        yield done
