"""
stage_sections.py: the rules of stage 3 (sections), the decisions the stage
used to hold as fixed values in its code (owner request 2026-11-19, A1:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard"). Their
values stand in the default profile's rules.json; a profile that decides
otherwise says so in its own. The stage reads each where it decides, when it
runs (`rules.get`), so that a changed value is the next run's.

Author: Felix Vossel
"""
from .kit import rule

# The group of these rules on the tab "stages".
GROUP = "Stage 3: sections"

RULES: tuple = (
    # -- reading order across columns --
    rule("column_min_text_blocks", "stages", GROUP, "whole",
         "The fewest text blocks a page needs before it is looked at for "
         "columns. With fewer, a gap between columns cannot be told from a "
         "gap between paragraphs, and the page is read as one column. A "
         "larger number leaves more pages as one column. Takes effect "
         "when stage 3 runs again.", least=2, most=50,
         where="columns.py (find_gutters)",
         title="Fewest text blocks of a page with columns"),
    rule("column_gutter_width_pt", "stages", GROUP, "number",
         "The width, in points, of the strip between two columns that must "
         "stay clear of text. A wider strip finds fewer gutters. Takes "
         "effect when stage 3 runs again.", least=1, most=50,
         where="columns.py (_half)",
         title="Width of the gap between columns"),
    rule("column_search_step_pt", "stages", GROUP, "number",
         "The distance, in points, between the places across a page that "
         "are tried as a gap between columns. A smaller step finds the gap "
         "more exactly and takes longer. Takes effect when stage 3 runs "
         "again.", least=0.5, most=20,
         where="columns.py (_clear_runs)",
         title="Search step for a gap between columns"),
    rule("column_run_join_steps", "stages", GROUP, "number",
         "Places that are tried as a gap and lie within this many search "
         "steps of one another are one gap. A larger number joins more of "
         "them. Takes effect when stage 3 runs again.",
         least=1.0, most=5.0, where="columns.py (_clear_runs)",
         title="Steps within which places make one gap"),
    rule("column_max_span_share", "stages", GROUP, "number",
         "The largest share of the text blocks of a page that may cross a "
         "gap between columns (a heading, a wide note). A page where more "
         "of them cross is not read as columns. A larger share accepts "
         "pages with more wide blocks. Takes effect when stage 3 runs "
         "again.", least=0, most=1, where="columns.py (find_gutters)",
         title="Largest share of blocks crossing a gap"),
    rule("column_min_load_share", "stages", GROUP, "number",
         "Every column must hold at least this share of the average number "
         "of blocks of a column, otherwise it is merged into its "
         "neighbour. A larger share drops more thin columns. Takes effect "
         "when stage 3 runs again.", least=0, most=1,
         where="columns.py (find_gutters)",
         title="Least share of a column's average load"),
    rule("column_min_blocks", "stages", GROUP, "whole",
         "Every column must hold at least this many text blocks, however "
         "few blocks the page has. A larger number drops columns with few "
         "blocks. Takes effect when stage 3 runs again.",
         least=1, most=20, where="columns.py (find_gutters)",
         title="Fewest text blocks of a column"),
    rule("column_min_width_pt", "stages", GROUP, "number",
         "The narrowest a column may be, in points. A narrower strip is an "
         "indent and not a column. A larger number finds fewer columns. "
         "Takes effect when stage 3 runs again.", least=10, most=300,
         where="columns.py (find_gutters)",
         title="Narrowest width of a column"),
    rule("column_max_columns", "stages", GROUP, "whole",
         "The most columns a page may have. A page that would split into "
         "more is a table and not a text layout, and is read as one "
         "column. A larger number accepts pages with more columns. Takes "
         "effect when stage 3 runs again.", least=2, most=10,
         where="columns.py (find_gutters)",
         title="Most columns of a page"),
    rule("column_edge_tolerance_pt", "stages", GROUP, "number",
         "Blocks whose left edges lie within this many points of each "
         "other are on the same edge. Text in a column has a left edge, "
         "the labels around a chart do not. A larger number counts more "
         "blocks as aligned. Takes effect when stage 3 runs again.",
         least=0.5, most=20, where="columns.py (_edge_clusters)",
         title="Tolerance of a left edge"),
    rule("column_min_aligned_share", "stages", GROUP, "number",
         "The share of the blocks of a column that must stand on its main "
         "left edges for it to be a column of text. A larger share "
         "rejects more columns, such as the labels of a chart. Takes "
         "effect when stage 3 runs again.", least=0, most=1,
         where="columns.py (_aligned_like_a_column)",
         title="Least share of blocks on the left edges"),
    rule("column_edge_groups", "stages", GROUP, "whole",
         "How many left edges are counted for a column: the biggest "
         "groups of blocks that start at the same place. Two covers a list "
         "whose lines start at the bullet and at the indent. A larger "
         "number accepts more scattered columns. Takes effect when stage 3 "
         "runs again.", least=1, most=5,
         where="columns.py (_aligned_like_a_column)",
         title="Number of left edges of a column"),
    # -- running heads and feet --
    rule("strip_running_headers", "stages", GROUP, "switch",
         "On: a line that repeats in the top or bottom band of many pages "
         "(a running head or foot) is removed from the text of the "
         "sections. Off: such lines stay in the text. Takes effect when "
         "stage 3 runs again.", where="sections.py (strip_running_headers)",
         title="Remove running heads and feet"),
    rule("running_header_band", "stages", GROUP, "number",
         "The share of the height of a page, at its top and at its bottom, "
         "that counts as the head band and the foot band. A larger share "
         "looks for running lines further into the page. Takes effect "
         "when stage 3 runs again.", least=0.02, most=0.4,
         where="sections.py (_header_zone)",
         title="Height of the head and foot band"),
    rule("running_header_max_chars", "stages", GROUP, "whole",
         "The most characters a line may have to be a running head or "
         "foot. A longer text block is not one. A larger number allows "
         "longer lines. Takes effect when stage 3 runs again.",
         least=10, most=500, where="sections.py (_header_candidate)",
         title="Most characters of a running line"),
    rule("running_header_min_chars", "stages", GROUP, "whole",
         "The fewest characters a running line must have once the page "
         "numbers are taken out of it. A shorter line is ignored. A "
         "larger number ignores more short lines. Takes effect when "
         "stage 3 runs again.", least=1, most=50,
         where="sections.py (strip_running_headers)",
         title="Fewest characters of a running line"),
    rule("running_header_page_share", "stages", GROUP, "number",
         "A line must come back on at least this share of the pages of a "
         "document to be a running head or foot (and on at least the "
         "fewest pages given for it). A larger share removes fewer lines. "
         "Takes effect when stage 3 runs again.", least=0.05, most=1.0,
         where="sections.py (strip_running_headers)",
         title="Share of pages a running line repeats on"),
    rule("running_header_min_pages", "stages", GROUP, "whole",
         "A document with fewer pages than this has no running heads or "
         "feet removed. A larger number leaves short documents as they "
         "are. Takes effect when stage 3 runs again.",
         least=1, most=100, where="sections.py (strip_running_headers)",
         title="Fewest pages of a document with running lines"),
    rule("running_header_min_repeats", "stages", GROUP, "whole",
         "A line must come back on at least this many pages to be a "
         "running head or foot, whatever the share of pages. A larger "
         "number removes fewer lines. Takes effect when stage 3 runs "
         "again.", least=2, most=100,
         where="sections.py (strip_running_headers)",
         title="Fewest repeats of a running line"),
    rule("running_header_number_digits", "stages", GROUP, "whole",
         "A number of up to this many digits standing alone in a running "
         "line is taken as a page number and left out when lines are "
         "compared, so that \"Report 12\" and \"Report 13\" are the same "
         "line. A larger number also leaves out longer numbers such as "
         "years. Takes effect when stage 3 runs again.",
         least=1, most=8, where="sections.py (_norm_header)",
         title="Most digits of a page number"),
    rule("keep_front_page_headers", "stages", GROUP, "switch",
         "On: the first page and the page of the document title keep all "
         "their lines, because their running head is often the citation "
         "line of the document. Off: running lines are removed from these "
         "pages too. Takes effect when stage 3 runs again.",
         where="sections.py (strip_running_headers)",
         title="Keep the lines of the first pages"),
    rule("sentence_end_marks", "stages", GROUP, "chars",
         "The marks that end a sentence. A footnote is set after the text "
         "of its page only where that text ends a sentence, otherwise it "
         "waits for the end of the sentence on the next page. A mark you "
         "add lets a footnote follow more endings. Takes effect when stage "
         "3 runs again.", where="sections.py (_ends_sentence)",
         title="Marks that end a sentence"),
    # -- directories --
    rule("strip_directory_sections", "stages", GROUP, "switch",
         "On: a section that is a table of contents, a list of figures or "
         "tables, or an index is removed. A section with a table or "
         "figure of its own, or a bibliography, is never removed. Off: "
         "these sections stay. Takes effect when stage 3 runs again.",
         where="sections.py (drop_directory_sections)",
         title="Remove directory sections"),
    rule("directory_min_entries", "stages", GROUP, "whole",
         "A section needs at least this many entries of a directory (a "
         "title, dots and a page number) to be removed as a directory. A "
         "larger number removes fewer sections. Takes effect when stage 3 "
         "runs again.", least=1, most=50,
         where="sections.py (_is_directory_section)",
         title="Fewest entries of a directory section"),
    rule("directory_listing_share", "stages", GROUP, "number",
         "The share of the characters of a section that entries of a "
         "directory must cover for a section without a directory title to "
         "be removed. A larger share removes fewer sections. Takes effect "
         "when stage 3 runs again.", least=0.1, most=1.0,
         where="sections.py (_is_directory_section)",
         title="Share of a directory section made of entries"),
    rule("directory_titled_listing_share", "stages", GROUP, "number",
         "The same share for a section whose title says that it is a "
         "directory: the lower bar. A larger share removes fewer such "
         "sections. Takes effect when stage 3 runs again.",
         least=0.05, most=1.0, where="sections.py (_is_directory_section)",
         title="Share of entries of a titled directory section"),
    rule("directory_head_chars", "stages", GROUP, "whole",
         "How many characters at the start of a section are checked for "
         "whether the section is a listing from its start. A larger number "
         "checks more of the opening. Takes effect when stage 3 runs "
         "again.", least=20, most=1000,
         where="sections.py (_is_directory_section)",
         title="Length of the opening that is checked"),
    rule("directory_head_share", "stages", GROUP, "number",
         "The share of the opening of a section that entries of a "
         "directory must cover for the section to be a listing from its "
         "start. A larger share removes fewer sections. Takes effect when "
         "stage 3 runs again.", least=0.1, most=1.0,
         where="sections.py (_is_directory_section)",
         title="Share of the opening made of entries"),
    rule("directory_max_other_chars", "stages", GROUP, "whole",
         "A section without a directory title is removed only if no more "
         "than this many characters of it are not entries, which keeps a "
         "section with running text. A larger number removes more "
         "sections. Takes effect when stage 3 runs again.",
         least=0, most=5000, where="sections.py (_is_directory_section)",
         title="Most characters of a directory besides entries"),
    rule("directory_min_chars", "stages", GROUP, "whole",
         "A section with fewer characters than this is never counted as a "
         "directory. A larger number leaves more short sections. Takes "
         "effect when stage 3 runs again.", least=0, most=500,
         where="sections.py (_directory_metrics)",
         title="Fewest characters of a directory section"),
    rule("directory_entry_max_chars", "stages", GROUP, "whole",
         "The most characters an entry of a directory may have before its "
         "page number: its title, with or without dots. A larger number "
         "takes longer lines as entries. Takes effect when stage 3 runs "
         "again.", least=10, most=300,
         where="sections.py (_directory_metrics)",
         title="Most characters of a directory entry"),
    rule("directory_figure_words", "stages", GROUP, "texts",
         "The words with which an entry of a list of figures or tables "
         "opens, such as \"Figure 3 Annual totals 27\". Each is part of a "
         "search pattern, so a point is written \"\\.\". A word you add "
         "finds more such entries. Takes effect when stage 3 runs again.",
         where="sections.py (_dir_figtab_re)",
         title="Words opening entries of figure or table lists"),
    rule("directory_title_words", "stages", GROUP, "texts",
         "Words that make the title of a section the title of a directory, "
         "such as \"contents\". They are searched anywhere in the title, "
         "without regard to case, as parts of a search pattern. A section "
         "with such a title is removed at the lower bar. Empty: no title "
         "makes a section a directory. Takes effect when stage 3 runs "
         "again.", empty=True, where="sections.py (_dir_title_re)",
         title="Words in the title of a directory section"),
    rule("bibliography_title_words", "stages", GROUP, "texts",
         "Words that make the title of a section the title of a "
         "bibliography. They are searched anywhere in the title, without "
         "regard to case, as parts of a search pattern. Such a section is "
         "never removed as a directory; it goes on to the reading of "
         "literature. A word you add protects more sections. Takes effect "
         "when stage 3 runs again.",
         where="sections.py (_dir_lit_title_re)",
         title="Words in the title of a bibliography"),
    # -- captions and the names of sections --
    rule("caption_opener_patterns", "stages", GROUP, "texts",
         "The search patterns that tell how a caption opens, each with its "
         "own anchor, such as a word, a number and a colon (\"Table 3:\"). "
         "A text opens a caption when one of them matches. They decide "
         "which sentence of a section is taken as the caption of a table "
         "or a figure when the layout linked another text, and the pieces "
         "of the last stage use them too. A pattern that matches the empty "
         "text is refused. Takes effect when stage 3 runs again.",
         where="captions.py (_caption_start)",
         title="How a caption opens"),
    rule("front_section_title", "stages", GROUP, "text",
         "The title of the section that holds the text before the first "
         "heading of a document. It is stored with the section, shown in "
         "citations and read by the model. Changing it leaves earlier "
         "results with the old title, so rebuild stage 3 and the stages "
         "after it for the documents that were read. Takes effect when "
         "stage 3 runs again.", where="sections.py (build_sections)",
         title="Title of the section before the first heading"),
    rule("part_section_title", "stages", GROUP, "text",
         "The title of a part of a section that was split and has no "
         "title of its own. It is stored with the part and shown in "
         "citations. Changing it leaves earlier results with the old "
         "title. Takes effect when stage 4 runs again.",
         where="split.py (apply_cuts)",
         title="Title of an untitled part of a section"),
    rule("normalize_unicode_nfkc", "stages", GROUP, "switch",
         "On: text is brought to the compatible normal form of Unicode "
         "before it is stored, so that, for example, a ligature or a "
         "superscript two is stored as its plain letters or digit, and "
         "broken surrogates, unassigned characters and non-characters are "
         "removed in either case. Off: the characters stay as they are "
         "printed. Changing it changes the text of every document, so "
         "read the documents again. Takes effect when stages 1 to 4 run "
         "again.", where="config.py (clean_unicode), also stage 4's",
         title="Normalise characters of the text"),
)
