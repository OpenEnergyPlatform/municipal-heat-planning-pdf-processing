"""
stage_text.py: the rules of stage 1 (page text), the decisions the stage
used to hold as fixed values in its code (owner request 2026-11-19, A1:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard"). Their
values stand in the default profile's rules.json; a profile that decides
otherwise says so in its own. The stage reads each where it decides, when it
runs (`rules.get`), so that a changed value is the next run's.

Author: Felix Vossel
"""
from .kit import rule

# The group of these rules on the tab "stages".
GROUP = "Stage 1: page text"

RULES: tuple = (
    rule("text_block_min_chars", "stages", GROUP, "whole",
         "The fewest characters a block of text on a page needs to be kept "
         "(spaces at its ends do not count). A block must also hold at least "
         "one letter or digit. A larger number drops more short fragments such "
         "as lone page marks; a smaller one keeps them. Takes effect when "
         "stage 1 reads the text of a document again.",
         least=1, most=50, where="page_text.py (_is_valid_text_block)",
         title="Fewest characters of a text block"),
    rule("bold_block_share", "stages", GROUP, "number",
         "The share of the characters of a text block that must be printed "
         "bold for the block to count as bold, which later helps to find "
         "headings. 0.5 means at least half of them. A larger share makes "
         "fewer blocks bold; a smaller one makes more of them bold. Takes "
         "effect when stage 1 reads the text of a document again.",
         least=0.1, most=1.0, where="page_text.py (_dominant_font)",
         title="Share of bold characters of a bold block"),
    rule("join_hyphenated_words", "stages", GROUP, "switch",
         "On: a word broken by a hyphen at the end of a line is joined again "
         "when a lower-case letter stands before the hyphen and a lower-case "
         "letter opens the next line, except where the next line opens with "
         "one of the words that keep their hyphen. Off: no "
         "word is joined and the hyphen stays at the end of the line. Takes "
         "effect when stage 1 reads the text of a document again.",
         where="page_text.py (_spans_to_text)",
         title="Join words broken at a line end"),
    rule("hyphen_exceptions", "stages", GROUP, "texts",
         "The words that keep a hyphen at the end of a line instead of "
         "being joined to the next line when that line opens with one of "
         "them, as in \"short-\" and \"and long-term\". They are compared "
         "without regard to case and at the start of the next line only. A "
         "word you add keeps more hyphens; a word you remove lets the line "
         "be glued to the hyphenated word. Takes effect when stage 1 reads "
         "the text of a document again.",
         where="page_text.py (hyphen_exceptions)",
         title="Words that keep their hyphen"),
    rule("drop_private_use_glyphs", "stages", GROUP, "switch",
         "On: the characters of a symbol font (check marks, smileys and "
         "the like), which mean nothing outside that font, are removed from "
         "the text of a page. Off: they stay in the text as they are read. "
         "Takes effect when stage 1 reads the text of a document again.",
         where="config.py (strip_private_use)",
         title="Remove symbol font characters"),
    rule("page_text_min_chars", "stages", GROUP, "whole",
         "A page with fewer characters of text than this is taken to have no "
         "text layer, and a model reads its text from the picture of the "
         "page. A larger number sends more thinly written pages to the "
         "model; 0 sends none, whatever the page holds. Takes effect when "
         "stage 1 runs with the reading of pages without text.",
         least=0, most=2000,
         where="page_text_without_layer.py (needs_transcription)",
         title="Fewest characters of a page with text"),
    rule("transcribed_text_area", "stages", GROUP, "map",
         "Where the blocks of a page read by the model are placed on the "
         "page, as a share of its width (left and right) and of its height "
         "(top and bottom). The text has no position, so its blocks are "
         "stacked down this area in proportion to their length. A larger "
         "area gives each block more room; it only moves where a "
         "highlighted passage is drawn. Takes effect when stage 1 reads a "
         "page without text again.",
         of="number", where="page_text_without_layer.py (synthesize_blocks)",
         title="Area of a page read by the model"),
    rule("page_transcribe_dpi", "stages", GROUP, "whole",
         "The resolution, in dots per inch, of the picture of a page that "
         "the model reads. A higher number makes small print more legible "
         "and the picture larger and slower to read; a lower one does the "
         "opposite. Takes effect when stage 1 reads a page without text "
         "again.", least=72, most=400,
         where="page_text_without_layer.py (make_page_renderer)",
         title="Resolution of a page the model reads"),
    rule("page_transcribe_temperature", "stages", GROUP, "number",
         "How freely the model reads a page without text: 0 is the most "
         "literal. It applies when the prompt of the page reading names no "
         "temperature of its own; a larger value lets the model vary its "
         "wording more. Takes effect when stage 1 reads a page without text "
         "again.", least=0, most=2,
         where="page_text_without_layer.py (make_transcriber)",
         title="Temperature of the page reading"),
    rule("page_transcribe_max_tokens", "stages", GROUP, "whole",
         "The longest reply, in tokens, the model may give for one page "
         "without text. It applies when the prompt of the page reading names "
         "no limit of its own. A reply cut off at the limit is asked again "
         "with more room where the server allows it. A larger number allows "
         "pages with more text. Takes effect when stage 1 reads a page "
         "without text again.", least=256, most=65536,
         where="page_text_without_layer.py (make_transcriber, "
               "page_request_tokens)",
         title="Longest reply for a page"),
)
