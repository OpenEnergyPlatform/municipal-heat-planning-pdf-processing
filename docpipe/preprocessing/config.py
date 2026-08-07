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

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
# DPI used when rendering a page region to a crop PNG (tables/figures).
PAGE_RENDER_DPI = 300

# DPI for the layout-detection model input. The model's preprocessor resizes
# every page to a fixed 800x800 (do_resize in its HF config), so rendering
# beyond ~150 DPI is discarded work; pages with crops are re-rendered at
# PAGE_RENDER_DPI (stage2 renders once only when the two values are equal).
LAYOUT_DETECT_DPI = 150

# ---------------------------------------------------------------------------
# Stage 1 – Text extraction
# ---------------------------------------------------------------------------
TEXT_BLOCK_MIN_CHARS = 3

HYPHEN_EXCEPTIONS = (
    "und", "oder", "bzw", "etc", "sowie", "als", "wie", "auch", "denn",
    "noch", "sondern", "doch", "jedoch", "allerdings", "hingegen",
    "beziehungsweise", "insbesondere", "zum", "zur", "im", "in", "am",
    "an", "auf", "von", "mit", "für", "über", "unter", "zwischen",
    "ohne", "gegen", "bis", "durch", "trotz", "wegen", "während",
)

# ---------------------------------------------------------------------------
# Stage 2 – Layout detection (PP-DocLayoutV3)
# ---------------------------------------------------------------------------
PP_DOCLAYOUT_MODEL_ID = "PaddlePaddle/PP-DocLayoutV3_safetensors"
LAYOUT_BATCH_SIZE = 30

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

# Per-class confidence thresholds, keyed by the model's class id.
PP_CLASS_THRESHOLDS: dict[int, float] = {
    0: 0.50, 1: 0.50, 2: 0.50, 3: 0.45,
    4: 0.55, 5: 0.40, 6: 0.40, 7: 0.50, 8: 0.50, 9: 0.50,
    10: 0.50, 11: 0.50, 12: 0.50, 13: 0.50, 14: 0.85,
    15: 0.40, 16: 0.50, 17: 0.55, 18: 0.50, 19: 0.50,
    20: 0.45, 21: 0.85, 22: 0.65, 23: 0.65, 24: 0.50,
}

# Global minimum confidence – boxes below this are discarded before
# per-class thresholds are applied.
PP_GLOBAL_MIN_CONF = 0.4

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

# Classes whose text blocks are removed from page content entirely. The image
# variants are running furniture too (municipal logos in page corners).
SUPPRESS_CLASSES = {"header", "header_image", "footer", "footer_image",
                    "number", "footnote"}

# ─── RUNNING HEADER / FOOTER STRIPPING (Stage 3, deterministic) ────────────
# Removes running headers/footers the layout model mislabelled as plain "text"
# (SUPPRESS_CLASSES only catches correctly labelled ones). Must run before
# Stage 3 merges consecutive blocks into segments.
HEADER_FOOTER_STRIP_ENABLE   = True
HEADER_FOOTER_ZONE_FRAC      = 0.12   # top/bottom page-height fraction = header/footer band
HEADER_FOOTER_MAX_LEN        = 90     # running headers are short single lines
HEADER_FOOTER_MIN_NORM_LEN   = 4      # ignore near-empty normalized text
HEADER_FOOTER_MIN_PAGE_FRAC  = 0.30   # must recur on >= this fraction of pages (and >= 3)

# ─── COLUMN LAYOUT / READING ORDER (Stage 3, deterministic) ────────────────
# A two-column page must be read column by column; sorting by (y, x) reads
# across the gutter. Which mode applies comes from the profile
# (column_layout: auto | single | double); these are the detector's tunables.
COLUMN_MIN_TEXT_BLOCKS  = 6      # too few blocks to tell a gutter from a gap
COLUMN_GUTTER_WIDTH_PT  = 8.0    # the strip that must stay clear of text
COLUMN_SEARCH_STEP_PT   = 2.0    # candidate gutter positions across the text width
COLUMN_MAX_SPAN_FRAC    = 0.25   # at most this fraction of text blocks may cross a gutter
COLUMN_MIN_COLUMN_SHARE = 0.5    # every column must carry this share of the average load
COLUMN_MIN_WIDTH_PT     = 60.0   # narrower than this is an indent, not a column
COLUMN_MAX_COLUMNS      = 4      # more splits than this is a table, not a text layout
# A text column has a left edge; the labels scattered around a chart do not.
# This is what keeps a diagram's internal text from being read as columns
# (measured on the corpus: real columns >= 0.90, chart labels <= 0.43).
COLUMN_ALIGN_TOL_PT     = 4.0    # left edges within this are the same edge
COLUMN_MIN_ALIGNED_FRAC = 0.75   # this share of a column's blocks must sit on it

# ─── DIRECTORY / INDEX SECTION REMOVAL (Stage 3, deterministic) ────────────
# Drops assembled sections dominated by directory-listing lines (tables of
# contents, lists of figures/tables, indexes). GUARDS: a section containing a
# media placeholder ([pN_imgM]/[pN_tblM]), or whose title names a bibliography,
# is never dropped — the latter goes to the Stage-4 [LITERATURE] BibTeX path.
DIRECTORY_STRIP_ENABLE          = True
DIRECTORY_MIN_ENTRIES           = 4      # need >= this many listing entries
DIRECTORY_SCORE_THRESHOLD       = 0.55   # listing-char fraction for a non-titled drop
DIRECTORY_TITLE_SCORE_THRESHOLD = 0.35   # lower bar when the title is itself a directory title
DIRECTORY_HEAD_LEN              = 120    # chars at the section start checked for "listing from the start"
DIRECTORY_HEAD_SCORE_THRESHOLD  = 0.5    # the opening must be this listing-dense
DIRECTORY_MAX_RESIDUAL_CHARS    = 350    # drop only if <= this many non-listing chars remain

# Classes that identify tables and images/figures.
TABLE_CLASSES  = {"table"}
IMAGE_CLASSES  = {"image", "chart"}

# Classes that can serve as a caption for a figure or table.
# Evaluated in priority order: figure_title > vision_footnote > nearest text.
CAPTION_CLASSES = {"figure_title", "vision_footnote"}

# Classes used as section titles (trigger a new section boundary).
SECTION_TITLE_CLASSES = {"doc_title", "paragraph_title"}

# A paragraph_title is demoted to inline text when its vertical overlap with
# another detected box exceeds (1.0 - this fraction).
TITLE_SAME_ROW_OVERLAP_FRACTION = 0.2

# Maximum distance in points for "nearest text block" caption search.
CAPTION_MAX_DIST_PT = 60.0

# A caption is a label, not a paragraph. Without this the nearest-text-block
# fallback below happily adopts a whole paragraph — measured on the corpus, 205
# captions ran past 40 words, the longest 156 — and since the winning block is
# REMOVED from the page, that prose disappears from the section text entirely.
# Real captions sit at 8 words median, 24 at the 99th percentile.
CAPTION_MAX_WORDS = 45


def caption_like(text) -> bool:
    """Is this short enough to be a caption rather than body prose?"""
    return bool(text) and len(str(text).split()) <= CAPTION_MAX_WORDS


# A symbol font (Wingdings and friends) puts its glyphs in the Unicode Private
# Use Area, where they carry no meaning outside that font: what the extractor
# returns for a checkmark or a smiley is an unassigned code point. Measured on
# the corpus, 423 sections across 99 documents carry them. They are dropped —
# as characters they are noise to the reader, to the LLM and to the embedder
# alike, and the legend around them ("Ein roter Smiley gibt an, dass …") says
# in prose what the glyph meant.
STRIP_PRIVATE_USE = True


def _is_private_use(char: str) -> bool:
    o = ord(char)
    return 0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0xFFFFD or 0x100000 <= o <= 0x10FFFD


def strip_private_use(text: str) -> tuple:
    """(text without private-use glyphs, how many were removed)."""
    if not STRIP_PRIVATE_USE or not text:
        return text, 0
    kept = [c for c in text if not _is_private_use(c)]
    removed = len(text) - len(kept)
    if not removed:
        return text, 0
    return "".join(kept), removed

# Reject a caption candidate when a section heading lies vertically between it
# and the table/figure — prevents linking a caption across a section boundary.
CAPTION_REJECT_ACROSS_TITLE = True

# ─── FONT-BASED HEADING PROMOTION (Stage 2 cross-check) ────────────────────
# Promote a plain Stage-1 text block to a "paragraph_title" when its dominant
# font is heading-like and the layout model did not already classify it.
FONT_HEADING_ENABLE        = True
FONT_HEADING_SIZE_RATIO    = 1.2   # font_size >= body_size * ratio → heading
FONT_HEADING_MIN_CHARS     = 3     # ignore very short fragments
FONT_HEADING_MAX_CHARS     = 90    # headings are short single lines
FONT_HEADING_ALLCAPS_MIN_CHARS = 6  # all-caps promotion needs this many chars (skip acronyms)

# Fraction of a text-block's area that must lie inside a layout region
# before the text block is suppressed.
TEXT_SUPPRESS_OVERLAP = 0.9

# ─── BOX EXPANSION ─────────────────────────────────────────────────────────
# Margins added around detected table/image boxes, in points.
# Format: (margin_left_pt, margin_top_pt, margin_right_pt, margin_bottom_pt)
TABLE_BOX_MARGIN_PT = (5.0, 5.0, 5.0, 8.0)
IMAGE_BOX_MARGIN_PT = (5.0, 5.0, 5.0, 10.0)

# Two boxes of the same class overlapping by more than this fraction are
# reduced to the higher-confidence one. Set to 1.0 to disable NMS.
NMS_OVERLAP_THRESHOLD = 0.5

# Semantic pre-masking: when cropping a table, white out the pixels of any
# detected figure/chart region overlapping it, so the vision model does not
# transcribe an embedded diagram's lines as phantom table rows.
MASK_FIGURES_IN_TABLE_CROPS = True


TITLE_EXCLUDE_PREFIXES = (
    "abbildung",
    "abb.",
    "tabelle",
    "tab.",
)

# ---------------------------------------------------------------------------
# Output directories / filenames
# ---------------------------------------------------------------------------
DIR_IMAGES  = "images"
DIR_RESULTS = "results"

CACHE_PAGES_JSON       = f"{DIR_RESULTS}/pages_extracted.json"
STRUCTURED_OUTPUT_JSON = f"{DIR_RESULTS}/structured_output.json"        # Stage 3 output

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
SURROGATES = compile(r"[\uD800-\uDFFF]")




def clean_unicode(s: str) -> str:
    """Remove surrogates, control chars, non-characters."""
    s = unicodedata.normalize("NFKC", s)
    s = SURROGATES.sub("", s)
    s = "".join(
        c for c in s
        if unicodedata.category(c) != "Cn"
        and not (0xFDD0 <= ord(c) <= 0xFDEF or (ord(c) & 0xFFFE) == 0xFFFE)
    )
    return s


def clean_data(obj):
    """Recursively clean unicode in nested dicts/lists/strings."""
    if isinstance(obj, dict):
        return {k: clean_data(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_data(v) for v in obj]
    if isinstance(obj, str):
        return clean_unicode(obj)
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