"""
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
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from docpipe.reading import Hole

from .models import Block, PageData

log = logging.getLogger(__name__)

# A page with less real text than this is treated as having no text layer.
# Not zero: a scanned page often still carries a stamped page number or a
# copyright line from a digital overlay, which is text by the letter and
# nothing by the meaning.
MIN_PAGE_CHARS = 60

# Pages read concurrently. The server batches requests continuously, so this
# is the number in flight at it and the only throughput lever this stage has:
# documents are processed one at a time (the layout model is not thread-safe),
# so unlike refinement there is no second factor multiplying it. Eight was
# eight requests against four GPUs.
PAGE_WORKERS = int(os.environ.get("PAGE_TRANSCRIBE_WORKERS", "64"))

# Renders in flight. Rendering a page at RENDER_DPI is a PyMuPDF rasterise and
# a PIL PNG encode — CPU work holding the GIL, and it used to sit in the same
# slot as the model call, so raising the transcription count alone would just
# have added threads fighting over the encoder.
PAGE_RENDER_WORKERS = int(os.environ.get("PAGE_RENDER_WORKERS", "4"))

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

    A markdown heading becomes a block labelled `paragraph_title`, because that
    label - not the font size - is what Stage 3 opens a section on
    (SECTION_TITLE_CLASSES). Sizes and boldness are set as well, for the rules
    further up that read them, but the label is the part that decides. Getting
    this wrong put every transcribed page back into one pseudo-section, which
    is the exact failure this module exists to end.
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
            # The label decides, the font only supports it.
            layout_label="paragraph_title" if level else "text",
            font_size=(20.0 - 2.0 * (level - 1)) if level else 10.0,
            font_bold=bool(level),
            bbox_approx=True,
        ))
        cursor += height
    return blocks


def fill_missing_page_text(
    pages: list[PageData],
    render: Callable[[int], object],
    transcribe: Callable[[object, int], "str | Hole"],
    *,
    min_chars: int = MIN_PAGE_CHARS,
    max_pages: Optional[int] = None,
    workers: int = 1,
    render_workers: int = PAGE_RENDER_WORKERS,
    before_first: Optional[Callable[[], None]] = None,
) -> dict:
    """Transcribe every page whose text layer is missing. Mutates *pages*.

    *before_first* is called once there is a page to send and before any is
    sent: the place for a caller to ask whether the server is there. A
    document none of whose pages lacks its text never calls it.

    `render(page_number)` returns whatever the transcriber takes (a PIL image
    in the live wiring), `transcribe(image, page_number)` returns the page as
    markdown, an empty string if the page carries no prose, or a Hole that says
    why the call gave nothing. A page that yielded nothing keeps its empty text
    layer rather than an invented one.

    Returns a report: how many pages needed text, how many got it, how many had
    nothing to give, how many broke, which of those and why (`failed_pages`),
    and how many blocks were synthesized. The counts are the honest answer to
    "how much of this document is model-read rather than PDF-read".

    `pages_empty` and `pages_failed` are counted apart on purpose. A heat plan
    is full of pages that are one large map, and the prompt tells the model to
    return an empty string for those. Booking them as failures said 106 broken
    calls for a run in which not one call broke.
    """
    candidates = [p for p in pages if needs_transcription(p, min_chars)]
    report = {"pages_total": len(pages), "pages_missing_text": len(candidates),
              "pages_transcribed": 0, "pages_empty": 0, "pages_failed": 0,
              "failed_pages": [], "blocks_added": 0}
    if not candidates:
        return report
    if before_first is not None:
        before_first()

    if max_pages is not None and len(candidates) > max_pages:
        # A document where EVERY page needs the model is the expected case
        # here, so the cap is not about that: it is the guard against pointing
        # this at a corpus by accident and spending a night of GPU time on it.
        log.warning(
            "page transcription: %d pages need text, cap is %d — "
            "transcribing the first %d only",
            len(candidates), max_pages, max_pages)
        candidates = candidates[:max_pages]

    # Render and transcribe are different resources: the render is CPU under
    # the GIL, the transcription is a request the server wants many of. The
    # semaphore bounds the first without bounding the second.
    render_slots = threading.Semaphore(max(render_workers, 1))

    def read(page) -> "str | Hole":
        image = None
        try:
            with render_slots:
                image = render(page.page_number)
            if image is None:
                return Hole("error", "the page could not be rendered")
            got = transcribe(image, page.page_number)
            if not isinstance(got, (str, Hole)):
                # A transcriber that answers neither text nor why it has none.
                return Hole("error", f"the transcriber returned {got!r}")
            return got
        except Exception as e:                       # one page must not end the run
            log.error("page transcription: page %d failed: %s",
                      page.page_number, e)
            return Hole("error", f"{type(e).__name__}: {e}")
        finally:
            # A megabyte per page, and a document that needs this needs it for
            # every page. Held only as long as the call takes.
            try:
                if image is not None:
                    Path(image).unlink(missing_ok=True)
            except Exception:
                pass

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            replies = list(pool.map(read, candidates))
    else:
        replies = [read(page) for page in candidates]

    # Applied in page order regardless of the order they came back in: the
    # result of a run must not depend on which page the server finished first.
    for page, markdown in zip(candidates, replies):
        # A Hole is the only failure: the call raised, or the reply was not the
        # one object with its text. An answer of "" is an ANSWER: the page
        # holds no prose.
        if isinstance(markdown, Hole):
            report["pages_failed"] += 1
            report["failed_pages"].append({"page": page.page_number,
                                           "why": markdown.cause})
            continue
        blocks = synthesize_blocks(page, markdown)
        if not blocks:
            report["pages_empty"] += 1
            continue
        # Stage 2 keys its own ids off the same prefix, so the synthesized text
        # blocks replace the (empty or junk) text layer rather than joining it.
        page.blocks = [b for b in page.blocks if b.type != "text"] + blocks
        page.blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        report["pages_transcribed"] += 1
        report["blocks_added"] += len(blocks)

    log.info("page transcription: %d/%d page(s) had no text layer, %d "
             "transcribed, %d without prose, %d failed, %d block(s) added",
             report["pages_missing_text"], report["pages_total"],
             report["pages_transcribed"], report["pages_empty"],
             report["pages_failed"], report["blocks_added"])
    if report["pages_failed"]:
        # Rare enough to be worth a line of its own: an empty page is expected,
        # a broken call is not.
        causes: dict = {}
        for entry in report["failed_pages"]:
            causes[entry["why"]] = causes.get(entry["why"], 0) + 1
        log.warning("page transcription: %d page(s) could not be read at all; "
                    "page(s) by cause: %s", report["pages_failed"],
                    ", ".join(f"{c} {n}" for c, n in sorted(causes.items())))
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


def make_page_renderer(pdf_path, scratch_dir=None):
    """render(page_number) -> path of the rendered page PNG.

    Written to disk rather than held in memory: the call layer takes a path.
    Into scratch by default, NOT next to the document: a full page at
    RENDER_DPI is about a megabyte, and a corpus-wide run would leave gigabytes
    of them behind for nothing. The page is reproducible from the PDF at any
    time, so the transcription is what is worth keeping, not the picture.

    $TMPDIR is respected.
    """
    import tempfile
    from pathlib import Path

    import fitz
    from PIL import Image

    from .stage1_extract import _render_page_to_pil

    pdf_path = Path(pdf_path)
    if scratch_dir is None:
        scratch_dir = tempfile.mkdtemp(prefix="pagetext_")
    pages_dir = Path(scratch_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    # One Document per thread. PyMuPDF does not support concurrent access to
    # one, and every worker of the transcription pool called this.
    local = threading.local()

    def _doc():
        doc = getattr(local, "doc", None)
        if doc is None:
            doc = local.doc = fitz.open(pdf_path)
        return doc

    def render(page_number: int):
        out = pages_dir / f"p{page_number - 1}_page.png"
        if not out.exists():
            image: Image.Image = _render_page_to_pil(_doc()[page_number - 1],
                                                     RENDER_DPI)
            image.save(out, format="PNG")
        return out

    return render


# What a page request is allowed to answer with, when the prompt says nothing.
PAGE_TEMPERATURE = 0.1
PAGE_MAX_TOKENS = 4096


def page_request_tokens(profile) -> int:
    """Worst case for one page request: the page prompt + one page image + the
    reply we ask for, once. A reply cut off at its limit is asked once more
    with more room (see vision.call_vision), bounded by what the served window
    leaves beyond this number, so no second reply is counted. What the vision
    server has to be started for when it is asked to transcribe pages; the page
    is as large as a table crop at its largest, so the image is counted as
    there."""
    from docpipe import prompts
    from docpipe.visuals.config import IMAGE_TOKENS, TOKENS_PER_WORD

    prompt = prompts.load(PAGE_TRANSCRIBE_PROMPT_ID, profile)
    room = int((prompt.meta or {}).get("max_tokens", PAGE_MAX_TOKENS))
    return int(len(prompt.text.split()) * TOKENS_PER_WORD + IMAGE_TOKENS + room)


def make_transcriber(profile, *, client=None, model=None):
    """transcribe(image_path, page_number) -> markdown, or a Hole.

    ONE job: read the page. No cleaning, no summarising, no restructuring —
    refinement does that afterwards, in its own calls, on its own terms. The
    prompt lives in the profile because what a page holds and in which language
    is project knowledge, while "a page with no text layer needs reading" is not.

    The reply is the one object with a `markdown` that is text, and the empty
    string is an answer (a page that is one large map holds no prose). A reply
    that is not that object is a Hole with its cause, as it is for a table.
    """
    from docpipe import prompts
    from docpipe.visuals import replies, vision

    from docpipe.profile import profile_value

    prompt = prompts.load(PAGE_TRANSCRIBE_PROMPT_ID, profile)
    # The one line of the user's turn, in the prompt's language.
    request = (profile.require("preprocessing", "PAGE_REQUEST")
               if profile is not None
               else profile_value("preprocessing", "PAGE_REQUEST"))
    client = client or vision.create_client()
    model = model or vision.VLM_MODEL
    meta = prompt.meta or {}
    # The page request's own budget: the room a cut page is given once more is
    # what the served window leaves beyond it, not beyond the visuals stage's.
    budget = page_request_tokens(profile)

    def transcribe(image_path, page_number: int):
        reply = vision.call_vision(
            client, prompt.text,
            request.format(page=page_number),
            image_path, model=model,
            temperature=float(meta.get("temperature", PAGE_TEMPERATURE)),
            max_tokens=int(meta.get("max_tokens", PAGE_MAX_TOKENS)),
            reply=replies.PAGE, budget=budget,
        )
        return reply if isinstance(reply, Hole) else reply["markdown"]

    return transcribe
