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

# DPI used to render a page as input to the layout-detection model. The model's
# image processor downsamples internally, so this may be set lower than
# PAGE_RENDER_DPI to cut Stage-2 memory/compute. Crops are always taken at
# PAGE_RENDER_DPI. Default equals PAGE_RENDER_DPI → one render per page and no
# behavioural change; lower to ~150–200 to save memory at a possible
# detection-accuracy cost (validate on real documents before changing).
LAYOUT_DETECT_DPI = 300

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

# Per-class confidence thresholds from config.json of the model.
# OPTIMIZED: Lowered thresholds for tables (4, 21) and images (3, 14) to improve recall.
PP_CLASS_THRESHOLDS: dict[int, float] = {
    0: 0.50, 1: 0.50, 2: 0.50, 3: 0.45,  # chart: 0.50 → 0.45
    4: 0.55, 5: 0.40, 6: 0.40, 7: 0.50, 8: 0.50, 9: 0.50,  # content: 0.65 → 0.55
    10: 0.50, 11: 0.50, 12: 0.50, 13: 0.50, 14: 0.85,  # image: 0.90 → 0.85
    15: 0.40, 16: 0.50, 17: 0.55, 18: 0.50, 19: 0.50,
    20: 0.45, 21: 0.85, 22: 0.65, 23: 0.65, 24: 0.50,  # table: 0.90 → 0.85
}

# Global minimum confidence – boxes below this are discarded before
# per-class thresholds are applied.
PP_GLOBAL_MIN_CONF = 0.4  # Lowered from 0.5 to catch more candidates

# Exact id2label mapping from config.json (25 classes, ids 0-24).
# IDs 8/9 both map to "footer", 12/13 both map to "header" – as defined in
# the upstream model config.
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
    9:  "footer",
    10: "footnote",
    11: "formula_number",
    12: "header",
    13: "header",
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

# Classes whose text blocks are removed from page content entirely.
SUPPRESS_CLASSES = {"header", "footer", "number", "footnote"}

# ─── RUNNING HEADER / FOOTER STRIPPING (Stage 3, deterministic) ────────────
# SUPPRESS_CLASSES drops blocks PP-DocLayout *labels* "header"/"footer", but the
# layout model mislabels the running header as plain "text" on ~1 in 5 documents,
# so it leaks into the section content. This deterministic pass removes text
# blocks whose page-number-normalized text recurs in the top/bottom page zone
# across many pages — catching what the layout model misses, BEFORE Stage 3
# merges consecutive blocks into segments. Section-title blocks are never
# touched (layout_label guard). Set False to A/B compare.
HEADER_FOOTER_STRIP_ENABLE   = True
HEADER_FOOTER_ZONE_FRAC      = 0.12   # top/bottom page-height fraction = header/footer band
HEADER_FOOTER_MAX_LEN        = 90     # running headers are short single lines
HEADER_FOOTER_MIN_NORM_LEN   = 4      # ignore near-empty normalized text
HEADER_FOOTER_MIN_PAGE_FRAC  = 0.30   # must recur on >= this fraction of pages (and >= 3)

# ─── DIRECTORY / INDEX SECTION REMOVAL (Stage 3, deterministic) ────────────
# Tables of contents, lists of figures/tables, indexes etc. are low-value
# listing noise that would otherwise be embedded. Drop assembled sections whose
# content is dominated by directory-listing lines (dot leaders, or
# "Abbildung N: … <page>"). A section is dropped when EITHER its title is itself
# a directory heading (Inhalt/…verzeichnis), OR its content is a listing from
# the very start AND has almost no prose left over. The last two conditions
# protect real content sections that merely reference a few figures or end with
# a short list (e.g. a "Maßnahmen" chapter with a prose intro). GUARDS: a
# section that contains a real media placeholder ([pN_imgM]/[pN_tblM]) or whose
# title names a bibliography (Literatur/Quellen/Referenzen) is NEVER dropped —
# the latter goes to the Stage-4 [LITERATURE] BibTeX path instead. Set False to
# A/B compare.
DIRECTORY_STRIP_ENABLE          = True
DIRECTORY_MIN_ENTRIES           = 4      # need >= this many listing entries
DIRECTORY_SCORE_THRESHOLD       = 0.55   # listing-char fraction for a non-titled drop
DIRECTORY_TITLE_SCORE_THRESHOLD = 0.35   # lower bar when the title is itself a directory title
DIRECTORY_HEAD_LEN              = 120    # chars at the section start checked for "listing from the start"
DIRECTORY_HEAD_SCORE_THRESHOLD  = 0.5    # the opening must be this listing-dense (protects prose intros)
DIRECTORY_MAX_RESIDUAL_CHARS    = 350    # drop only if <= this many non-listing chars remain (protects prose bodies)

# Classes that identify tables and images/figures.
TABLE_CLASSES  = {"table"}
IMAGE_CLASSES  = {"image", "chart"}

# Classes that can serve as a caption for a figure or table.
# Evaluated in priority order: figure_title > vision_footnote > nearest text.
CAPTION_CLASSES = {"figure_title", "vision_footnote"}

# Classes used as section titles (trigger a new section boundary).
SECTION_TITLE_CLASSES = {"doc_title", "paragraph_title"}

# A paragraph_title is treated as inline text (not a section heading) when its
# vertical overlap with another detected box exceeds (1.0 - this fraction),
# i.e. 0.2 → titles overlapping a neighbour by more than 80 % vertically are
# demoted. Consumed in stage2_layout._process_page.
TITLE_SAME_ROW_OVERLAP_FRACTION = 0.2

# Maximum distance in points for "nearest text block" caption search.
CAPTION_MAX_DIST_PT = 60.0

# Reject a caption candidate when a section heading lies vertically between it
# and the table/figure — prevents linking a caption across a section boundary.
CAPTION_REJECT_ACROSS_TITLE = True

# ─── FONT-BASED HEADING PROMOTION (Stage 2 cross-check) ────────────────────
# Promote a plain Stage-1 text block to a section heading ("paragraph_title")
# when its dominant font is heading-like and PP-DocLayout did NOT already
# classify it — a cheap deterministic catch for headings the layout model
# missed on linear layouts (also supplies heading ranks for downstream use).
# Set FONT_HEADING_ENABLE = False to disable.
FONT_HEADING_ENABLE        = True
FONT_HEADING_SIZE_RATIO    = 1.2   # font_size >= body_size * ratio → heading
FONT_HEADING_MIN_CHARS     = 3     # ignore very short fragments
FONT_HEADING_MAX_CHARS     = 90    # headings are short single lines
FONT_HEADING_ALLCAPS_MIN_CHARS = 6  # all-caps promotion needs this many chars (skip acronyms)

# Fraction of a text-block's area that must lie inside a layout region
# before the text block is suppressed.
TEXT_SUPPRESS_OVERLAP = 0.9

# ─── BOX EXPANSION (NEW) ───────────────────────────────────────────────────
# Expand detected table and image boxes by these margins (in points) to ensure
# full content capture, especially captions and padding.
# Format: (margin_left_pt, margin_top_pt, margin_right_pt, margin_bottom_pt)
TABLE_BOX_MARGIN_PT = (5.0, 5.0, 5.0, 8.0)   # Extra space, more below for caption
IMAGE_BOX_MARGIN_PT = (5.0, 5.0, 5.0, 10.0)  # Extra space, more below for caption

# Non-maximum suppression: remove overlapping detections of the same class.
# If two boxes of the same class overlap by more than this fraction, keep only
# the one with higher confidence. Set to 1.0 to disable NMS.
NMS_OVERLAP_THRESHOLD = 0.5

# Semantic pre-masking: when cropping a table, white out (255,255,255) the
# pixels of any detected figure/chart region that overlaps the table, so the
# vision model does not transcribe an embedded diagram's lines as phantom
# table rows. Set to False to A/B compare. (After Munshi 2026, "Semantic
# Pre-Masking" — reported grid-shift hallucinations 87% → 0%.)
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
    """
    Serialise *data* as UTF-8 JSON to *path* atomically.

    Writes to a temporary file in the same directory and os.replace()s it onto
    the destination, so a crash / Ctrl-C / power loss mid-write can never leave
    a truncated, unreadable file behind (os.replace is atomic on the same
    filesystem, including on Windows).
    """
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