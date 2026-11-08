"""
layout.py: Stage 2. Detects the layout of every page with PP-DocLayoutV3 and
turns it into tables, images, section titles and text suppressions for
Stage 3.

The open fitz pages from Stage 1 are rendered in batches, by the prefetch
thread or by worker processes (`rendering.py`), and the model's inputs of a
batch are built in that thread too, while the batch before it runs through
the model. Each page then goes through `layout_blocks.process_page`, and its
crops are encoded and written by a thread of their own (`crops.py`). Once
every batch has run, `headings.py` and `layout_captions.py` pass over the
whole document.

A batch whose pages never reached the detection model is reported as
LayoutDetectionFailed rather than left with text and no layout, so the
caller drops the document for the next run to retry.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import math
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
from PIL import Image

from .config import (
    DIR_IMAGES,
    LAYOUT_BATCH_SIZE,
    LAYOUT_DETECT_DPI,
    LAYOUT_PREFETCH_BATCHES,
    LAYOUT_RENDER_PROCS,
    PAGE_RENDER_DPI,
    SECTION_TITLE_CLASSES,
    NMS_OVERLAP_THRESHOLD,
)
from .models import PageData
from .rendering import FITZ_LOCK, render_page_to_pil, as_image
from . import crops, headings, layout_blocks, layout_captions, layout_model, rendering

log = logging.getLogger(__name__)

def _prefetch(items, produce, depth: int):
    """
    Yield produce(item) for each item, computing up to *depth* items ahead in a
    worker thread. depth=0 falls back to plain sequential evaluation.

    An exception in the worker is re-raised in the consumer, so a failure looks
    exactly like it would without the thread.
    """
    if depth <= 0:
        for item in items:
            yield produce(item)
        return

    done = object()
    box: queue.Queue = queue.Queue(maxsize=depth)

    def work():
        try:
            for item in items:
                box.put(produce(item))
        except BaseException as exc:          # noqa: BLE001 — handed to consumer
            box.put(exc)
        finally:
            box.put(done)

    worker = threading.Thread(target=work, name="stage2-render", daemon=True)
    worker.start()
    try:
        while True:
            got = box.get()
            if got is done:
                return
            if isinstance(got, BaseException):
                raise got
            yield got
    finally:
        # Drain so a consumer that stops early cannot wedge the worker on put().
        while worker.is_alive():
            try:
                if box.get(timeout=0.1) is done:
                    break
            except queue.Empty:
                pass


class LayoutDetectionFailed(RuntimeError):
    """Raised when a batch never reached the model, so pages have no layout."""


def _process_batch(rendered: list, dets_per_page: list, same_dpi: bool,
                   images_dir: Path, footnotes: layout_blocks.FootnoteTally,
                   page_by_number: dict, writer) -> list:
    """Runs each page of a batch through `process_page` into
    *page_by_number* and hands its crops to *writer*; returns one future per
    crop, true once the crop is written."""
    futures = []
    for (pg, fp, det_img, rendered_crop), dets in zip(rendered, dets_per_page):
        try:
            if same_dpi:
                crop_img = det_img
            elif rendered_crop is not None:
                crop_img = rendered_crop
            else:
                with FITZ_LOCK:      # the prefetch thread is rendering too
                    crop_img = render_page_to_pil(fp, PAGE_RENDER_DPI)
            updated_pg, crop_jobs = layout_blocks.process_page(
                pg, fp, det_img.width, det_img.height, crop_img, dets, images_dir,
                footnotes,
            )
            page_by_number[updated_pg.page_number] = updated_pg
            futures.extend(writer.submit(crops.write_crop, job) for job in crop_jobs)
        except Exception as e:
            log.error(f"Page {pg.page_number} processing failed: {e}", exc_info=True)
    return futures


def detect_layout_all_pages(
    pages: list[PageData],
    fitz_pages: list[fitz.Page],
    output_dir: Path,
    model_tuple,
) -> list[PageData]:
    """
    Runs layout detection over *pages*, writing crop PNGs into
    output_dir/DIR_IMAGES and returning the updated PageData list (suppressed
    text blocks removed, table/image/title blocks added).

    *fitz_pages* must be in the same order as *pages* and still open;
    *model_tuple* is (processor, model, device) from load_model(). Pages are
    rendered and freed per batch, so the whole document is never resident.
    """
    processor, model, device = model_tuple

    if not pages:
        log.warning("Stage 2: no pages – skipping inference")
        return pages
    if len(pages) != len(fitz_pages):
        raise ValueError(
            f"List length mismatch: {len(pages)} PageData, "
            f"{len(fitz_pages)} fitz pages"
        )

    same_dpi = LAYOUT_DETECT_DPI == PAGE_RENDER_DPI
    log.info(
        f"Stage 2: PP-DocLayoutV3 – {len(pages)} pages | batch {LAYOUT_BATCH_SIZE} | "
        f"detect DPI {LAYOUT_DETECT_DPI} | crop DPI {PAGE_RENDER_DPI} | "
        f"NMS {NMS_OVERLAP_THRESHOLD}"
    )

    page_by_number: dict[int, PageData] = {pg.page_number: pg for pg in pages}

    images_dir = output_dir / DIR_IMAGES
    images_dir.mkdir(parents=True, exist_ok=True)

    n         = len(pages)
    n_batches = math.ceil(n / LAYOUT_BATCH_SIZE)
    written     = 0
    total_crops = 0
    failed_batches: list[int] = []
    footnotes = layout_blocks.FootnoteTally()

    def render_batch(b_idx: int):
        """One batch of detection inputs. Runs in the prefetch thread."""
        start = b_idx * LAYOUT_BATCH_SIZE
        end   = min(start + LAYOUT_BATCH_SIZE, n)
        chunk_pages = pages[start:end]
        chunk_fitz  = fitz_pages[start:end]

        # Skip pages that fail to render. The crop image is rendered later,
        # in the main loop.
        rendered: list[tuple[PageData, fitz.Page, Image.Image, None]] = []
        for pg, fp in zip(chunk_pages, chunk_fitz):
            try:
                with FITZ_LOCK:
                    image = render_page_to_pil(fp, LAYOUT_DETECT_DPI)
                rendered.append((pg, fp, image, None))
            except Exception as e:
                log.error(f"Page {pg.page_number}: render failed, skipping detection: {e}")
        return b_idx, chunk_pages, rendered

    def rendered_in_workers():
        """The batches of render_batch, every page rendered at both
        resolutions in a worker process (`rendering.py`)."""
        path = fitz_pages[0].parent.name
        if not path:
            raise ValueError("Stage 2: the document has no path to render from")
        dpis = ((LAYOUT_DETECT_DPI,) if same_dpi
                else (LAYOUT_DETECT_DPI, PAGE_RENDER_DPI))
        spans = [(b * LAYOUT_BATCH_SIZE, min((b + 1) * LAYOUT_BATCH_SIZE, n))
                 for b in range(n_batches)]
        got = rendering.batches(
            path, [[fp.number for fp in fitz_pages[s:e]] for s, e in spans],
            dpis, LAYOUT_RENDER_PROCS, LAYOUT_PREFETCH_BATCHES)
        for b_idx, ((s, e), results) in enumerate(zip(spans, got)):
            rendered = []
            for pg, fp, res in zip(pages[s:e], fitz_pages[s:e], results):
                if isinstance(res, str):
                    log.error(f"Page {pg.page_number}: render failed, skipping detection: {res}")
                    continue
                crop = None if same_dpi else as_image(res[PAGE_RENDER_DPI])
                rendered.append((pg, fp, as_image(res[LAYOUT_DETECT_DPI]), crop))
            yield b_idx, pages[s:e], rendered

    def with_inputs(batch):
        """A batch with the model's inputs built from its pages, or the
        exception that stopped them. Runs in the prefetch thread."""
        b_idx, chunk_pages, rendered = batch
        try:
            inputs = layout_model.model_inputs(processor, [r[2] for r in rendered]) if rendered else None
        except Exception as e:                # noqa: BLE001 — the batch's failure
            inputs = e
        return b_idx, chunk_pages, rendered, inputs

    if LAYOUT_RENDER_PROCS > 0:
        batches = _prefetch(rendered_in_workers(), with_inputs, LAYOUT_PREFETCH_BATCHES)
    else:
        batches = _prefetch(range(n_batches), lambda b: with_inputs(render_batch(b)),
                            LAYOUT_PREFETCH_BATCHES)

    # A batch's crops are encoded and written in a thread while the next batch
    # runs through the model: PNG encoding is 0.023 s a page on one core and
    # lets go of the GIL. The main thread waits for one batch's writes before
    # it hands over the next, so at most two batches of crops are held.
    writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage2-crops")
    writing: list = []

    def written_so_far(futures: list) -> int:
        return sum(1 for f in futures if f.result())

    try:
        for b_idx, chunk_pages, rendered, inputs in batches:
            log.info(
                f"Stage 2: batch {b_idx + 1}/{n_batches} "
                f"(pages {chunk_pages[0].page_number}–{chunk_pages[-1].page_number})"
            )
            if not rendered:
                continue

            det_images = [r[2] for r in rendered]
            try:
                dets_per_page = layout_model.infer_batch(det_images, processor, model, device,
                                             inputs=inputs)
            except Exception as e:
                log.error(f"Stage 2: inference failed for batch {b_idx + 1}: {e}",
                          exc_info=True)
                failed_batches.append(b_idx + 1)
                del det_images, rendered, inputs
                continue
            del inputs

            batch_writes = _process_batch(
                rendered, dets_per_page, same_dpi, images_dir, footnotes,
                page_by_number, writer)
            total_crops += len(batch_writes)
            written += written_so_far(writing)
            writing = batch_writes

            # Free this chunk's images before rendering the next.
            del det_images, rendered
        written += written_so_far(writing)
    finally:
        writer.shutdown(wait=True)

    updated_pages = [page_by_number[pg.page_number] for pg in pages]
    updated_pages = headings.promote_headings_by_font(updated_pages)
    updated_pages = layout_captions.resolve_captions(updated_pages)

    log.info(f"Stage 2: {written}/{total_crops} crops written")

    total_tables = sum(sum(1 for b in pg.blocks if b.type == "table") for pg in updated_pages)
    total_images = sum(sum(1 for b in pg.blocks if b.type == "image") for pg in updated_pages)
    total_titles = sum(
        sum(1 for b in pg.blocks if b.layout_label in SECTION_TITLE_CLASSES)
        for pg in updated_pages
    )
    log.info(
        f"Stage 2: done – {total_tables} tables | {total_images} images | "
        f"{total_titles} title blocks"
    )

    # A batch that never reached the model leaves its pages with text but no
    # layout at all: no tables, no figures, no headings. The document would go
    # on to be cached, sectioned and embedded, and would look complete
    # everywhere downstream. Refuse it instead — the caller drops the document
    # and the next run retries it.
    if failed_batches:
        raise LayoutDetectionFailed(
            "%d of %d batches failed (%s); %d page(s) have no layout"
            % (len(failed_batches), n_batches,
               ", ".join(str(b) for b in failed_batches[:8]),
               sum(min(LAYOUT_BATCH_SIZE, n - (b - 1) * LAYOUT_BATCH_SIZE)
                   for b in failed_batches))
        )

    # After the refusal above: a document that is dropped has no count worth
    # reading. Zero is logged too, so that "none found" is told from "not
    # counted".
    log.info(footnotes.line())

    return updated_pages
