"""
config.py – Central configuration of the pipeline.

Author: Felix Vossel
"""
from pathlib import Path
from re import compile

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
PAGE_RENDER_DPI = 300

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

# Classes that identify tables and images/figures.
TABLE_CLASSES  = {"table"}
IMAGE_CLASSES  = {"image", "chart"}

# Classes that can serve as a caption for a figure or table.
# Evaluated in priority order: figure_title > vision_footnote > nearest text.
CAPTION_CLASSES = {"figure_title", "vision_footnote"}

# Classes used as section titles (trigger a new section boundary).
SECTION_TITLE_CLASSES = {"doc_title", "paragraph_title"}

# How much horizontal overlap (fraction of the narrower box) is tolerated
# before a paragraph_title on the same vertical level is NOT treated as a
# title but as inline text.
TITLE_SAME_ROW_OVERLAP_FRACTION = 0.2  # 40 % vertical overlap → skip as title

# Maximum distance in points for "nearest text block" caption search.
CAPTION_MAX_DIST_PT = 60.0

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

CACHE_PAGES_JSON       = "results/pages_extracted.json"
STRUCTURED_OUTPUT_JSON = "results/structured_output.json"       # Stage 3 output
FINAL_OUTPUT_JSON      = "results/structured_output_final.json"  # Stage 4 output

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
SURROGATES = compile(r"[\uD800-\uDFFF]")


# ---------------------------------------------------------------------------
# Configuration for Ollama (Stage 4)
# ---------------------------------------------------------------------------

OLLAMA_MODEL = "gpt-oss:120b"
OLLAMA_HOST = "http://localhost:11435"
OLLAMA_TIMEOUT = 300
OLLAMA_NUM_PARALLEL = 2
MAX_RETRIES = 4
WINDOW_SIZE = 3  # sections processed per LLM call

# Ollama inference options.
OLLAMA_OPTIONS = {
    "temperature": 0.1,
}

# ---------------------------------------------------------------------------
# System prompt for the LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a document post-processing assistant. You receive sections extracted \
from German municipal heat planning documents ("Kommunale Wärmeplanung"). \
The extraction pipeline uses PyMuPDF text extraction and PP-DocLayoutV3 \
layout detection, which produces systematic artefacts you must correct.

You will receive a JSON object with a "sections" array containing 1–3 sections. \
Each section has the fields: title, content, page_number, tables, figures.

Apply the following tasks to each section:

1. CLEAN EXTRACTION ARTEFACTS
   Fix broken words caused by line-break hyphenation, e.g. "Wärme- versorgung" \
becomes "Wärmeversorgung". Remove leaked headers, footers, and stray page \
numbers from the content. Fix garbled Unicode and normalize whitespace. Remove \
orphaned single-word fragments that are clearly extraction debris. Never alter \
the meaning and never add information that was not in the original.

2. CLEAN TITLES AND CAPTIONS
   Remove numbering prefixes and label prefixes from the "title" field and \
from all "caption" fields inside the "tables" and "figures" arrays. Strip \
leading chapter/section numbers (e.g. "1.", "2.3", "4.1.2", "A.1", "IV."), \
figure labels (e.g. "Abbildung 1:", "Abb. 3:", "Figure 2:"), table labels \
(e.g. "Tabelle 4:", "Tab. 2:", "Table 1:"), and appendix labels (e.g. \
"Anhang A:", "Anlage 1:"), including their trailing separator (colon, dash, \
dot, or space). After stripping, only the descriptive text should remain. \
Also normalize capitalization, e. g. "POTENTIALANALYSE" becomes "Potentialanalyse". \
Examples: "4.1 Wärmebedarfsanalyse" becomes "Wärmebedarfsanalyse", \
"Abbildung 3: Wärmebedarf nach Sektoren" becomes "Wärmebedarf nach Sektoren", \
"Tab. 5: Kennwerte" becomes "Kennwerte". Keep all other fields (id, path, \
page_number) in tables and figures unchanged.

3. REMOVE DIRECTORY SECTIONS
   If a section consists purely of a table of contents, list of figures, list \
of tables, list of abbreviations, or a similar structural index page that \
contains only page references and listings with no substantive prose, set its \
_action to "remove". However, if such a section also contains substantive \
text beyond the directory listings, split it: remove the directory part and \
keep the substantive content as a separate section.

4. CONVERT BIBLIOGRAPHY SECTIONS
   If a section contains bibliography or reference entries (indicated by titles \
like Literaturverzeichnis, Quellenverzeichnis, Quellen, or Referenzen), \
convert it into a literature section. Set the title to "[LITERATURE]", the \
_action to "replace", and the content to a JSON array of BibTeX strings. Use \
the most appropriate entry type (@article, @book, @inproceedings, @techreport, \
@misc, etc.). Derive citation keys from the first author's last name and the \
year, e.g. "mueller2023". If information for a BibTeX field is missing, omit \
that field rather than guessing.

5. MERGE FRAGMENTS
   If a section has no real heading and is clearly just a broken continuation \
of the previous section, set its _action to "merge_into_previous".

6. SPLIT SECTIONS
   If a section contains a clear sub-heading within its content that starts a \
new topic, split it into multiple sections, each with _action set to "keep". \
Distribute the tables and figures arrays based on which placeholder references \
(like [p3_tbl0] or [p5_img2]) appear in each split part's content.

IMPORTANT RULES:
- Preserve ALL table and figure placeholders like [p3_tbl0] or [p5_img2] \
exactly as they appear. Never remove or modify these references.
- Never invent or add content. Only clean, restructure, and convert.
- Every section in your response MUST include an "_action" field with one of \
the values: "keep", "remove", "merge_into_previous", or "replace".

OUTPUT FORMAT:

Respond with ONLY a valid JSON object. No markdown fences, no explanations, \
no text outside the JSON.

The JSON object has a single key "sections" containing an array of section \
objects. There are two types of section objects:

Type 1 — Regular section (used with _action "keep", "remove", or \
"merge_into_previous"):
{
  "title": "Section title (string, cleaned of prefixes)",
  "content": "Section text as a single string",
  "page_number": 12,
  "tables": [
    {"id": "p2_tbl0", "path": "images/p2_tbl0.png", "caption": "Cleaned caption or null", "page_number": 12}
  ],
  "figures": [
    {"id": "p3_img0", "path": "images/p3_img0.png", "caption": "Cleaned caption or null", "page_number": 13}
  ],
  "_action": "keep"
}

Type 2 — Literature section (used only with _action "replace", only for \
bibliography/reference sections):
{
  "title": "[LITERATURE]",
  "content": [
    "@article{mueller2023, author = {Mueller, Hans}, title = {Wärmeplanung}, year = {2023}}",
    "@techreport{bmwk2024, author = {BMWK}, title = {Leitfaden}, year = {2024}}"
  ],
  "page_number": 95,
  "tables": [],
  "figures": [],
  "_action": "replace"
}

Note the difference: for regular sections, "content" is a string. For \
literature sections, "content" is an array of BibTeX entry strings.

EXAMPLE 1 — Regular cleaning:

Input:
{"sections": [{"title": "4.1 Wärmebedarfs- analyse", "content": "Die Wärme- \
versorgung der Kommune basiert auf fossilen Energieträgern. [p2_tbl0] zeigt \
die Verteilung. 17", "page_number": 12, "tables": [{"id": "p2_tbl0", "path": \
"images/p2_tbl0.png", "caption": "Tabelle 2: Energieträger im Bestand", \
"page_number": 12}], "figures": []}]}

Output:
{"sections": [{"title": "Wärmebedarfsanalyse", "content": "Die Wärmeversorgung \
der Kommune basiert auf fossilen Energieträgern. [p2_tbl0] zeigt die \
Verteilung.", "page_number": 12, "tables": [{"id": "p2_tbl0", "path": \
"images/p2_tbl0.png", "caption": "Energieträger im Bestand", "page_number": \
12}], "figures": [], "_action": "keep"}]}

EXAMPLE 2 — Bibliography conversion:

Input:
{"sections": [{"title": "8 Literaturverzeichnis", "content": "Mueller, H. \
(2023): Kommunale Wärmeplanung in Deutschland. Berlin: Springer. BMWK (2024): \
Leitfaden Kommunale Wärmeplanung. Bundesministerium für Wirtschaft und \
Klimaschutz.", "page_number": 95, "tables": [], "figures": []}]}

Output:
{"sections": [{"title": "[LITERATURE]", "content": [\
"@book{mueller2023, author = {Mueller, H.}, title = {Kommunale Wärmeplanung \
in Deutschland}, year = {2023}, publisher = {Springer}, address = {Berlin}}", \
"@techreport{bmwk2024, author = {BMWK}, title = {Leitfaden Kommunale \
Wärmeplanung}, year = {2024}, institution = {Bundesministerium für Wirtschaft \
und Klimaschutz}}"], "page_number": 95, "tables": [], "figures": [], \
"_action": "replace"}]}
"""


def clean_unicode(s: str) -> str:
    """Remove surrogates, control chars, non-characters."""
    import unicodedata
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