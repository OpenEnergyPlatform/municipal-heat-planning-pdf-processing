"""
stage_layout.py: the rules of stage 2 (layout), the decisions the stage
used to hold as fixed values in its code (owner request 2026-11-19, A1:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard"). Their
values stand in the default profile's rules.json; a profile that decides
otherwise says so in its own. The stage reads each where it decides, when it
runs (`rules.get`), so that a changed value is the next run's.

Author: Felix Vossel
"""
from .kit import rule

# The group of these rules on the tab "stages".
GROUP = "Stage 2: layout"

# The kinds of region the layout model tells apart (the labels of
# `preprocessing/config.py: PP_ID2LABEL`): what a list of classes below may
# name. A ruleset module imports nothing of docpipe outside it, so they stand
# here; a test holds the two lists together.
LABELS = (
    "abstract", "algorithm", "aside_text", "chart", "content", "doc_title",
    "figure_title", "footer", "footer_image", "footnote", "formula",
    "formula_number", "header", "header_image", "image", "number",
    "paragraph_title", "reference", "reference_content", "seal", "table",
    "text", "vision_footnote",
)

RULES: tuple = (
    rule("crop_render_dpi", "stages", GROUP, "whole",
         "The resolution, in dots per inch, at which a table or a figure is "
         "cut out of its page as a picture. The pictures are what the "
         "reading of tables and figures sees. A higher number keeps more "
         "detail and makes larger pictures; a lower one does the opposite. "
         "Takes effect when stage 2 runs again.", least=100, most=600,
         where="layout.py (detect_layout_all_pages)",
         title="Resolution of table and figure pictures"),
    rule("layout_detect_dpi", "stages", GROUP, "whole",
         "The resolution, in dots per inch, at which a page is shown to the "
         "layout model. The model shrinks every page to a fixed size, so "
         "more than about 150 only costs time. When it equals the "
         "resolution of the table and figure pictures, each page is "
         "rendered once. Takes effect when stage 2 runs again.",
         least=72, most=300,
         where="layout.py (detect_layout_all_pages)",
         title="Resolution of a page for the layout model"),
    rule("layout_class_min_scores", "stages", GROUP, "map",
         "The least confidence, from 0 to 1, the layout model must "
         "have in a region of each kind for it to count, each kind "
         "under its name as the lists of kinds below name it (chart, "
         "image, table, text and so on). A higher value for a kind "
         "drops its uncertain regions; a lower one keeps more of them. "
         "A kind that is not listed uses the least confidence set for "
         "kinds not listed. Takes effect when stage 2 runs again.",
         of="number", where="layout_model.py (infer_batch)",
         title="Least confidence of each kind of region"),
    rule("layout_default_min_score", "stages", GROUP, "number",
         "The least confidence, from 0 to 1, for a region of a kind that "
         "has no value of its own in the least confidence of each kind of "
         "region. A higher value drops more of them. Takes effect when "
         "stage 2 runs again.", least=0, most=1,
         where="layout_model.py (infer_batch)",
         title="Least confidence of a kind not listed"),
    rule("layout_min_score", "stages", GROUP, "number",
         "The confidence, from 0 to 1, below which the layout model's "
         "regions are dropped at once, before the least confidence of each "
         "kind is applied. A higher value drops more uncertain regions "
         "everywhere. Takes effect when stage 2 runs again.",
         least=0, most=1, where="layout_model.py (infer_batch)",
         title="Least confidence of any region"),
    rule("layout_overlap_limit", "stages", GROUP, "number",
         "Two regions of the same kind that overlap by more than this share "
         "are reduced to the more certain one, and a table and a figure "
         "that overlap by more than it are reduced to the more certain one "
         "too, so that no area yields two pictures. A smaller value merges "
         "more regions; 1 merges none. Takes effect when stage 2 runs "
         "again.", least=0.1, most=1.0,
         where="layout_model.py (infer_batch)",
         title="Overlap at which regions are merged"),
    rule("layout_failed_batches_allowed", "stages", GROUP, "whole",
         "How many groups of pages the layout model may fail on before the "
         "document is refused. 0 refuses the document at the first failed "
         "group, which a later run then reads again. A document with a "
         "failed group has pages without tables, figures or headings and "
         "looks complete in every later stage, so a larger number is "
         "risky. Takes effect when stage 2 runs again.",
         least=0, most=100, where="layout.py (detect_layout_all_pages)",
         title="Failed page groups a document may have"),
    rule("furniture_classes", "stages", GROUP, "texts",
         "The kinds of region whose text is removed from the page "
         "altogether: running heads and feet, page numbers and the logos "
         "in the corners. A kind you add is removed; one you take out stays "
         "in the text. Takes effect when stage 2 runs again.",
         choices=LABELS, empty=True,
         where="layout_blocks.py (process_page)",
         title="Kinds of region that are removed"),
    rule("footnote_classes", "stages", GROUP, "texts",
         "The kinds of region whose text is a footnote at the foot of a "
         "page. Their text stays in the document and is set on a line of "
         "its own after the text of its page. Empty: no region is read as a "
         "footnote. Takes effect when stage 2 runs again; stage 3 places "
         "the footnotes when it runs again.",
         choices=LABELS, empty=True,
         where="layout_blocks.py (process_page), sections.py "
               "(_block_is_footnote)",
         title="Kinds of region that are footnotes"),
    rule("table_classes", "stages", GROUP, "texts",
         "The kinds of region that are cut out as a table picture. A kind "
         "you add is read as a table. Takes effect when stage 2 runs again.",
         choices=LABELS,
         where="layout_blocks.py (process_page), layout_model.py",
         title="Kinds of region that are tables"),
    rule("figure_classes", "stages", GROUP, "texts",
         "The kinds of region that are cut out as a figure picture. A kind "
         "you add is read as a figure. Takes effect when stage 2 runs "
         "again.", choices=LABELS,
         where="layout_blocks.py (process_page), layout_model.py",
         title="Kinds of region that are figures"),
    rule("caption_classes", "stages", GROUP, "texts",
         "The kinds of region that may be the caption of a table or a "
         "figure. Such a region next to a table or figure is taken as its "
         "caption before any other text is. Takes effect when stage 2 runs "
         "again.", choices=LABELS,
         where="layout_blocks.py, layout_captions.py, headings.py",
         title="Kinds of region that are captions"),
    rule("heading_classes", "stages", GROUP, "texts",
         "The kinds of region that are headings. Every heading opens a new "
         "section of the document in stage 3. A kind you add opens "
         "sections; one you take out is read as plain text. Takes effect "
         "when stage 2 runs again; stage 3 builds the sections when it "
         "runs again.", choices=LABELS,
         where="layout_blocks.py, layout_captions.py, headings.py, "
               "sections.py",
         title="Kinds of region that are headings"),
    rule("text_suppress_overlap", "stages", GROUP, "number",
         "The share of a text block that must lie inside a region of the "
         "page (a table, a figure, a caption, a heading, a footnote or a "
         "removed kind) for the block to count as part of it. A text block "
         "that lies inside a table or figure is not read again as text. A "
         "larger share removes fewer blocks from the text. Takes effect "
         "when stage 2 runs again.", least=0.1, most=1.0,
         where="layout_blocks.py (_lies_in)",
         title="Share of a text block inside a region"),
    rule("table_crop_margins_pt", "stages", GROUP, "map",
         "The margin, in points, added on each side of a table before it "
         "is cut out as a picture: left, top, right and bottom. A larger "
         "margin takes in more of what lies around the table; it also "
         "removes the text there from the page text. Takes effect when "
         "stage 2 runs again.", of="number",
         where="layout_blocks.py (process_page)",
         title="Margins around a table picture"),
    rule("figure_crop_margins_pt", "stages", GROUP, "map",
         "The margin, in points, added on each side of a figure before it "
         "is cut out as a picture: left, top, right and bottom. A larger "
         "margin takes in more of what lies around the figure; it also "
         "removes the text there from the page text. Takes effect when "
         "stage 2 runs again.", of="number",
         where="layout_blocks.py (process_page)",
         title="Margins around a figure picture"),
    rule("mask_figures_in_tables", "stages", GROUP, "switch",
         "On: a figure that lies inside a table is painted white in the "
         "table's picture, so that its lines are not read as rows of the "
         "table. Off: the table's picture shows the figure as it is. Takes "
         "effect when stage 2 runs again.",
         where="layout_blocks.py (process_page)",
         title="Blank out figures inside tables"),
    rule("heading_same_row_gap", "stages", GROUP, "number",
         "A heading that stands on the same line as a removed region or "
         "another region (an inline label, a number in the margin) is read "
         "as text and not as a heading. Two regions share a line when they "
         "overlap vertically by more than 1 minus this value. A larger "
         "value lets them share a line more easily, so more headings are "
         "read as text. Takes effect when stage 2 runs again.",
         least=0, most=0.5,
         where="layout_blocks.py (process_page), headings.py",
         title="Gap that still counts as the same line"),
    rule("heading_excluded_prefixes", "stages", GROUP, "texts",
         "The words a text must not open with to be a heading, written in "
         "lower case. They are the words that open the caption of a table "
         "or a figure, so that \"Figure 3: ...\" does not open a section. "
         "A word you add keeps more texts from being headings. Takes "
         "effect when stage 2 runs again.",
         where="config.py (title_exclude_prefixes)",
         title="Words that open a caption, not a heading"),
    rule("font_headings", "stages", GROUP, "switch",
         "On: a text block the layout model did not call a heading is "
         "made one when its font looks like a heading (larger than the "
         "body text, or bold, or all capitals). Off: only what the layout "
         "model calls a heading is a heading. Takes effect when stage 2 "
         "runs again.", where="headings.py (promote_headings_by_font)",
         title="Find headings by their font"),
    rule("font_heading_size_ratio", "stages", GROUP, "number",
         "A text block whose font is at least this many times the size of "
         "the body text is made a heading. A larger number finds fewer "
         "headings. Takes effect when stage 2 runs again.",
         least=1.0, most=3.0, where="headings.py (_looks_like_heading)",
         title="Heading size compared with body text"),
    rule("font_heading_min_chars", "stages", GROUP, "whole",
         "A text block shorter than this is never made a heading by its "
         "font. A larger number ignores more short fragments. Takes effect "
         "when stage 2 runs again.", least=1, most=50,
         where="headings.py (_looks_like_heading)",
         title="Fewest characters of a heading found by font"),
    rule("font_heading_max_chars", "stages", GROUP, "whole",
         "A text block longer than this is never made a heading by its "
         "font, because a heading is a short line. A larger number allows "
         "longer headings. Takes effect when stage 2 runs again.",
         least=10, most=500, where="headings.py (_looks_like_heading)",
         title="Most characters of a heading found by font"),
    rule("font_heading_caps_min_chars", "stages", GROUP, "whole",
         "A text block in capitals is made a heading only when it has at "
         "least this many letters, which keeps acronyms out. A larger "
         "number finds fewer headings in capitals. Takes effect when "
         "stage 2 runs again.", least=1, most=50,
         where="headings.py (_looks_like_heading)",
         title="Fewest characters of a heading in capitals"),
    rule("heading_prose_end_marks", "stages", GROUP, "chars",
         "The marks that end a sentence. A text block that ends with one of "
         "them, or has one of them followed by a space and a capital "
         "letter inside it, is a sentence of running text and is never "
         "made a heading by its font. A mark you add keeps more text from "
         "being a heading. Takes effect when stage 2 runs again.",
         where="headings.py (_looks_like_heading)",
         title="Marks that end a sentence of running text"),
    rule("bold_larger_is_heading", "stages", GROUP, "switch",
         "On: a bold text block whose font is larger than the body text, "
         "however slightly, is made a heading by its font. Off: only a "
         "block whose font is the set multiple of the body text, or in "
         "capitals, is. Takes effect when stage 2 runs again.",
         where="headings.py (_looks_like_heading)",
         title="Bold and larger text is a heading"),
    rule("caption_max_distance_pt", "stages", GROUP, "number",
         "How far, in points, a plain text block may lie from a table or a "
         "figure to be taken as its caption when no caption region is "
         "there. A larger distance takes in text further away; text taken "
         "as a caption is removed from the page text. Takes effect when "
         "stage 2 runs again.", least=0, most=300,
         where="layout_captions.py (resolve_captions)",
         title="Farthest distance of a caption"),
    rule("caption_not_across_heading", "stages", GROUP, "switch",
         "On: a text is not taken as the caption of a table or a figure "
         "when a heading lies between them on the page. Off: a caption "
         "may lie across a heading. Takes effect when stage 2 runs again.",
         where="layout_captions.py (resolve_captions)",
         title="No caption across a heading"),
    rule("caption_max_words", "stages", GROUP, "whole",
         "The most words a text may have to be a caption. A longer text is "
         "running text and stays in the text of its section. Running text "
         "taken as a caption is removed from the text, while a caption "
         "taken as running text only stays in it, so a larger number is "
         "the riskier one: set it near the length of the longest caption "
         "of the documents. Takes effect when stage 2 runs again, and "
         "when stage 3 runs again.", least=1, most=1000,
         where="config.py (caption_like)",
         title="Most words of a caption"),
)
