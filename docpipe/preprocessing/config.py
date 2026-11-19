"""
config.py – Central configuration of the pipeline.

Author: Felix Vossel
"""
import json
import os
import tempfile
import unicodedata
from pathlib import Path
from re import compile

from docpipe.artifacts import (DIR_IMAGES, DIR_RESULTS,   # noqa: F401  (re-exported)
                               PAGE_TRANSCRIPTION_REPORT_JSON,
                               PAGES_JSON, SECTIONS_JSON)

# ---------------------------------------------------------------------------
# Stage 2 – Layout detection (PP-DocLayoutV3)
# ---------------------------------------------------------------------------
PP_DOCLAYOUT_MODEL_ID = "PaddlePaddle/PP-DocLayoutV3_safetensors"

# Pages per forward pass. The model keeps a mask per query per decoder layer —
# (batch x 6 x 300 x 200 x 200) — so the batch drives a multi-GB allocation:
# 30 pages asked for 8 GiB in one go and blew up a third worker on a shared
# GPU. 12 keeps that under ~3.5 GiB. Throughput is unaffected: the forward
# pass is 6% of the stage, the CPU-side rendering is the rest.
LAYOUT_BATCH_SIZE = 12

# Mixed precision for the detection forward pass: "bf16", "fp16" or "off".
# OFF by default, from measurement: the forward pass is 4.7 of ~80 ms per page
# (the rest is PyMuPDF rendering and the processor's resize, both CPU), and
# autocast makes it 1.15x faster — 0.7% of the stage for a precision change on
# box coordinates. Not a trade worth taking; the switch stays for the day the
# CPU side gets faster.
LAYOUT_AUTOCAST = os.environ.get("DOCPIPE_LAYOUT_AUTOCAST", "off").lower()

# Render the next batch's pages while the current one is on the GPU. 0 disables
# the prefetch thread; 1 is enough to hide the rendering, since one batch of
# work is all the GPU is ever waiting for.
LAYOUT_PREFETCH_BATCHES = int(os.environ.get("DOCPIPE_LAYOUT_PREFETCH", "1"))

# Worker processes that render the pages, both resolutions, in place of the
# prefetch thread (`rendering.py`). In one process MuPDF renders behind one
# lock, so every page waits on one core while the GPU stands idle. A scanned
# page of the 1,896-page book 10.1017_cbo9780511793677 is one JPEG 2000 image
# of 12 megapixels: one core took 0.58 s to render it at 150 dpi and 0.74 s at
# 300 dpi, and Stage 2 took 1.25 s a page of it in the scenario rebuild of
# 2026-11-11. On 3,254 KWP pages rendering was 0.119 of the 0.150 s a page
# took through Stage 1-3. Unset, there are as many workers as this process
# has CPUs to run on, less two for its main and prefetch threads;
# DOCPIPE_LAYOUT_RENDER_PROCS sets the number, and 0 keeps the thread.
def _render_procs() -> int:
    """The number of Stage 2's render workers (see above)."""
    value = os.environ.get("DOCPIPE_LAYOUT_RENDER_PROCS", "").strip()
    if value:
        return int(value)
    try:
        cpus = len(os.sched_getaffinity(0))   # what the job's cgroup grants
    except AttributeError:                     # no affinity on Windows, macOS
        cpus = os.cpu_count() or 1
    return max(0, cpus - 2)


LAYOUT_RENDER_PROCS = _render_procs()

# id2label mapping (25 classes, ids 0-24). The HF port's own id2label collapses
# four pairs the original Paddle label list distinguishes: 8/9 footer /
# footer_image, 12/13 header / header_image, 5/15 display / inline formula,
# 22/23 text / vertical_text. The image variants are named here so their
# suppression below is explicit; the formula and text collapses are kept —
# both members are treated identically downstream.
PP_ID2LABEL: dict[int, str] = {
    0:  "abstract",
    1:  "algorithm",
    2:  "aside_text",
    3:  "chart",
    4:  "content",
    5:  "formula",
    6:  "doc_title",
    7:  "figure_title",
    8:  "footer",
    9:  "footer_image",
    10: "footnote",
    11: "formula_number",
    12: "header",
    13: "header_image",
    14: "image",
    15: "formula",
    16: "number",
    17: "paragraph_title",
    18: "reference",
    19: "reference_content",
    20: "seal",
    21: "table",
    22: "text",
    23: "text",
    24: "vision_footnote",
}

# How long a caption gets is a property of the corpus, not of the pipeline: a
# municipal heat plan sits at 8 words median, an IPCC panel description at 60
# to 150. The rule `caption_max_words` says it per profile. The winning block
# is REMOVED from the page, so prose taken for a caption disappears from the
# section text entirely.
def caption_like(text) -> bool:
    """Is this short enough to be a caption rather than body prose?"""
    from docpipe import rules
    return bool(text) and len(str(text).split()) <= rules.get(
        "caption_max_words")


def title_exclude_prefixes() -> tuple:
    """Caption openers that must never be promoted to a section heading."""
    from docpipe import rules
    return tuple(rules.get("heading_excluded_prefixes"))


# A symbol font (Wingdings and friends) puts its glyphs in the Unicode Private
# Use Area, where they carry no meaning outside that font: what the extractor
# returns for a checkmark or a smiley is an unassigned code point. Measured on
# the corpus, 423 sections across 99 documents carry them. The rule
# `drop_private_use_glyphs` drops them: as characters they are noise to the
# reader, to the LLM and to the embedder alike, and the legend around them
# ("Ein roter Smiley gibt an, dass …") says in prose what the glyph meant.
def _is_private_use(char: str) -> bool:
    o = ord(char)
    return 0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0xFFFFD or 0x100000 <= o <= 0x10FFFD


def strip_private_use(text: str) -> tuple:
    """(text without private-use glyphs, how many were removed)."""
    from docpipe import rules
    if not text or not rules.get("drop_private_use_glyphs"):
        return text, 0
    kept = [c for c in text if not _is_private_use(c)]
    removed = len(text) - len(kept)
    if not removed:
        return text, 0
    return "".join(kept), removed

# Output directories and filenames: see docpipe/artifacts.py, imported above.

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
SURROGATES = compile(r"[\uD800-\uDFFF]")




def clean_unicode(s: str, nfkc=None) -> str:
    """Remove surrogates, control chars, non-characters. The text is first
    brought to the compatible normal form unless the rule
    `normalize_unicode_nfkc` is off; *nfkc* says it for a caller that read
    the rule once for many strings."""
    if nfkc is None:
        from docpipe import rules
        nfkc = rules.get("normalize_unicode_nfkc")
    if nfkc:
        s = unicodedata.normalize("NFKC", s)
    s = SURROGATES.sub("", s)
    s = "".join(
        c for c in s
        if unicodedata.category(c) != "Cn"
        and not (0xFDD0 <= ord(c) <= 0xFDEF or (ord(c) & 0xFFFE) == 0xFFFE)
    )
    return s


def clean_data(obj, nfkc=None):
    """Recursively clean unicode in nested dicts/lists/strings. The rule
    `normalize_unicode_nfkc` is read once for the whole structure."""
    if nfkc is None:
        from docpipe import rules
        nfkc = rules.get("normalize_unicode_nfkc")
    if isinstance(obj, dict):
        return {k: clean_data(v, nfkc) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_data(v, nfkc) for v in obj]
    if isinstance(obj, str):
        return clean_unicode(obj, nfkc)
    return obj


def dump_json_atomic(data, path) -> None:
    """Serialise *data* as UTF-8 JSON to *path* atomically (write temp file in
    the same directory, then os.replace), so an interrupted write can never
    leave a truncated file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise