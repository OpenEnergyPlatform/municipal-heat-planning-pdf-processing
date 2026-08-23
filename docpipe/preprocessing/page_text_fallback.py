"""
page_text_fallback.py – Text for pages that carry no text layer.

Stage 1 reads the PDF's own text layer. Some plans have none: the pages are
vector graphics or images end to end, `get_text` returns nothing, and every
section Stage 3 assembles is a body of bare [pNN_tbl0] markers. Eleven plans in
the heat-plan corpus are like that, together holding 1270 tables and figures
that Stage 2 transcribed and that then had no text to hang off.

This module fills that gap at the level where it opens: a page's text BLOCKS.
The page is rendered, one model call transcribes it, and the reply becomes
Block(type="text") entries on the same PageData every other page carries. From
there Stage 2, Stage 3, refinement, chunking and embedding run unchanged and
know nothing about where the text came from.

Deliberately ONE job per call. Transcription is not cleanup: the model is asked
to read what is on the page and nothing else, and the refinement stage does its
own work afterwards in its own calls. Asking for both at once is how a model
starts inventing the tidy version of a page it cannot quite read.

The model call is an injected callable, so the loop, the thresholds and the
block synthesis are testable without a GPU.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .models import Block, PageData

log = logging.getLogger(__name__)

# A page with less real text than this is treated as having no text layer.
# Not zero: a scanned page often still carries a stamped page number or a
# copyright line from a digital overlay, which is text by the letter and
# nothing by the meaning.
MIN_PAGE_CHARS = 60

# Pages read concurrently. The server batches requests, and a document with no
# text layer needs EVERY page read: serially that is an idle GPU and hours of
# wall clock for a plan the size of Leipzig.
PAGE_WORKERS = int(os.environ.get("PAGE_TRANSCRIBE_WORKERS", "8"))

# Where synthesized blocks are placed on the page, as a fraction of page height
# and width. A transcription has no coordinates, so the boxes are stacked down
# a typical text column instead of being measured.
TEXT_AREA = (0.08, 0.07, 0.92, 0.95)      # left, top, right, bottom


def page_text_length(page: PageData) -> int:
    """Characters of real text Stage 1 found on this page."""
    return sum(len((b.content or "").strip())
               for b in page.blocks if b.type == "text")


def needs_transcription(page: PageData, min_chars: int = MIN_PAGE_CHARS) -> bool:
    """True if this page's text layer is missing or too thin to be real."""
    return page_text_length(page) < min_chars


def split_into_blocks(markdown: str) -> list[str]:
    """A transcription split into the blocks Stage 3 will reason over.

    Blank lines separate blocks, and a heading always starts one: Stage 3 finds
    section titles by font size and boldness, neither of which survives a
    transcription, so a heading has to arrive as its own block to have any
    chance of being recognised as one.
    """
    blocks: list[str] = []
    for chunk in re.split(r"\n\s*\n", markdown or ""):
        current: list[str] = []
        for line in chunk.splitlines():
            if re.match(r"^\s{0,3}#{1,6}\s+\S", line):
                if current:
                    blocks.append("\n".join(current).strip())
                    current = []
                blocks.append(line.strip())
                continue
            current.append(line)
        if current and "\n".join(current).strip():
            blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def _heading_level(text: str) -> Optional[int]:
    match = re.match(r"^\s{0,3}(#{1,6})\s+(\S.*)$", text)
    return len(match.group(1)) if match else None


def synthesize_blocks(page: PageData, markdown: str,
                      prefix: Optional[str] = None) -> list[Block]:
    """Transcribed text as Block objects, stacked down the page's text area.

    The boxes are APPROXIMATE and say so: `bbox_approx` rides on every block so
    that nothing downstream presents a synthesized rectangle as a measured one.
    A highlight drawn from it points at the right page and the right region,
    which is what a reader needs, but it is not a located line and must never
    be counted as one.

    Markdown heading levels become font sizes, largest for `#`, because that is
    the signal Stage 3 uses to find section titles and a transcription has no
    fonts of its own.
    """
    texts = split_into_blocks(markdown)
    if not texts:
        return []

    prefix = prefix if prefix is not None else f"p{page.page_number - 1}"
    left, top, right, bottom = TEXT_AREA
    x0 = round(page.width_pt * left, 2)
    x1 = round(page.width_pt * right, 2)
    y_top = page.height_pt * top
    usable = page.height_pt * (bottom - top)

    weights = [max(len(t), 1) for t in texts]
    total = sum(weights)

    blocks: list[Block] = []
    cursor = y_top
    for i, (text, weight) in enumerate(zip(texts, weights)):
        height = usable * weight / total
        level = _heading_level(text)
        blocks.append(Block(
            id=f"{prefix}_t{i}",
            type="text",
            bbox=[x0, round(cursor, 2), x1, round(cursor + height, 2)],
            content=re.sub(r"^\s{0,3}#{1,6}\s+", "", text).strip(),
            # Stage 3 reads size and boldness to find titles. `#` is the
            # biggest, each further level one step smaller, body text is body
            # text.
            font_size=(20.0 - 2.0 * (level - 1)) if level else 10.0,
            font_bold=bool(level),
            bbox_approx=True,
        ))
        cursor += height
    return blocks


def fill_missing_page_text(
    pages: list[PageData],
    render: Callable[[int], object],
    transcribe: Callable[[object, int], Optional[str]],
    *,
    min_chars: int = MIN_PAGE_CHARS,
    max_pages: Optional[int] = None,
    workers: int = 1,
) -> dict:
    """Transcribe every page whose text layer is missing. Mutates *pages*.

    `render(page_number)` returns whatever the transcriber takes (a PIL image
    in the live wiring), `transcribe(image, page_number)` returns the page as
    markdown or None if the call failed. A failed page keeps its empty text
    layer rather than an invented one, and is counted.

    Returns a report: how many pages needed text, how many got it, and how many
    blocks were synthesized. The counts are the honest answer to "how much of
    this document is model-read rather than PDF-read".
    """
    candidates = [p for p in pages if needs_transcription(p, min_chars)]
    report = {"pages_total": len(pages), "pages_missing_text": len(candidates),
              "pages_transcribed": 0, "pages_failed": 0, "blocks_added": 0}
    if not candidates:
        return report

    if max_pages is not None and len(candidates) > max_pages:
        # A document where EVERY page needs the model is the expected case
        # here, so the cap is not about that: it is the guard against pointing
        # this at a corpus by accident and spending a night of GPU time on it.
        log.warning(
            "page transcription: %d pages need text, cap is %d — "
            "transcribing the first %d only",
            len(candidates), max_pages, max_pages)
        candidates = candidates[:max_pages]

    def read(page) -> Optional[str]:
        try:
            image = render(page.page_number)
            return transcribe(image, page.page_number) if image is not None else None
        except Exception as e:                       # one page must not end the run
            log.error("page transcription: page %d failed: %s",
                      page.page_number, e)
            return None

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            replies = list(pool.map(read, candidates))
    else:
        replies = [read(page) for page in candidates]

    # Applied in page order regardless of the order they came back in: the
    # result of a run must not depend on which page the server finished first.
    for page, markdown in zip(candidates, replies):
        if not markdown or not markdown.strip():
            report["pages_failed"] += 1
            continue
        blocks = synthesize_blocks(page, markdown)
        if not blocks:
            report["pages_failed"] += 1
            continue
        # Stage 2 keys its own ids off the same prefix, so the synthesized text
        # blocks replace the (empty or junk) text layer rather than joining it.
        page.blocks = [b for b in page.blocks if b.type != "text"] + blocks
        page.blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        report["pages_transcribed"] += 1
        report["blocks_added"] += len(blocks)

    log.info("page transcription: %d/%d page(s) had no text layer, %d "
             "transcribed, %d failed, %d block(s) added",
             report["pages_missing_text"], report["pages_total"],
             report["pages_transcribed"], report["pages_failed"],
             report["blocks_added"])
    return report


# ---------------------------------------------------------------------------
# Live wiring. Everything above runs without a GPU; everything below needs the
# vision server, and is imported lazily so that a preprocessing run which does
# not use the fallback keeps its today's dependency set.
# ---------------------------------------------------------------------------

PAGE_TRANSCRIBE_PROMPT_ID = "preprocessing/page_transcribe"

# Rendering resolution for the page handed to the model. Higher than the table
# crops need: a full page holds body text at 9-10 pt, and that is the size at
# which a digit stops being legible first.
RENDER_DPI = 200


def make_page_renderer(pdf_path, output_dir):
    """render(page_number) -> path of the rendered page PNG.

    Written to disk rather than passed in memory: the call layer takes a path,
    and the rendered page is the audit trail for text that has no PDF text
    layer to check it against.
    """
    from pathlib import Path

    import fitz
    from PIL import Image

    from .stage1_extract import _render_page_to_pil

    pdf_path = Path(pdf_path)
    pages_dir = Path(output_dir) / "images"
    pages_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)

    def render(page_number: int):
        out = pages_dir / f"p{page_number - 1}_page.png"
        if not out.exists():
            image: Image.Image = _render_page_to_pil(doc[page_number - 1], RENDER_DPI)
            image.save(out, format="PNG")
        return out

    return render


def make_transcriber(profile, *, client=None, model=None):
    """transcribe(image_path, page_number) -> markdown, or None on failure.

    ONE job: read the page. No cleaning, no summarising, no restructuring —
    refinement does that afterwards, in its own calls, on its own terms. The
    prompt lives in the profile because what a page holds and in which language
    is project knowledge, while "a page with no text layer needs reading" is not.
    """
    from docpipe import prompts
    from docpipe.visuals import vision

    prompt = prompts.load(PAGE_TRANSCRIBE_PROMPT_ID, profile)
    client = client or vision.create_client()
    model = model or vision.VLM_MODEL
    meta = prompt.meta or {}

    def transcribe(image_path, page_number: int):
        reply = vision.call_vision(
            client, prompt.text,
            f"Seite {page_number}. Gib den Text dieser Seite zurück.",
            image_path, model=model,
            temperature=float(meta.get("temperature", 0.1)),
            max_tokens=int(meta.get("max_tokens", 4096)),
        )
        if not isinstance(reply, dict):
            return None
        text = reply.get("markdown") or reply.get("text")
        return text if isinstance(text, str) else None

    return transcribe
