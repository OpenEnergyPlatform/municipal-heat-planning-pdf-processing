"""
preprocessing.py – What text extraction has to know about English.

The numbers here are for documents nobody has measured. A profile that
extends this one and has measured its corpus writes its own.

Author: Felix Vossel
"""

# A line ending in "-" is usually a word broken across the break, but not when
# the next line opens with one of these: "short-" + "and long-term" is a
# construction, and gluing it gives "shortand long-term".
HYPHEN_EXCEPTIONS = (
    "and", "or", "nor", "but", "to", "as", "than", "versus", "vs",
    "plus", "minus", "through", "via", "of", "in", "on", "at", "by",
    "for", "with", "without", "between", "within", "under", "over",
    "before", "after", "e.g", "i.e", "etc",
)

# Caption openers that must never be promoted to a section heading. Without
# them "Figure 3: ..." becomes a title and opens a section.
TITLE_EXCLUDE_PREFIXES = (
    "figure",
    "fig.",
    "table",
    "tab.",
)

# What opens a caption (docpipe/captions.py), in three patterns, each with
# its own anchor. A word, a number, a colon opens one wherever it stands
# ("Table 3:", "Figure 2-1:", "Fig. 2:"): the number is what carries it,
# "Note:" is a note. It keeps the umlauts the core's pattern had, so a profile
# that extends this one for a German corpus still reads "Übersicht 5:". The
# same with a letter before the number ("Table A.1:") is the second. The
# third takes the forms without a colon ("Figure 3.", "Fig. 2", "Table 1
# Annual totals"), but only where a text, a line or a sentence begins: "see
# Table 1." and "Table 1 shows" are prose, and a title taken from them would
# replace a caption Stage 2 found.
CAPTION_START = (
    r"(?:^|(?<=[\s\]]))([A-ZÄÖÜ][A-Za-zÄÖÜäöüß.]{2,14}\s+\d+(?:[-.–]\d+)*\s*:)",
    r"(?:^|(?<=[\s\]]))((?:Figure|Fig\.?|Table|Tab\.?|Box|Chart|Map|Plate)"
    r"\s+[A-Z]\.?\d+(?:[-.–]\d+)*\s*:)",
    r"(?:^\s*|(?<=\n)|(?<=[.!?\]]\s))((?:Figure|Fig\.?|Table|Tab\.?|Box|Chart|Map"
    r"|Plate)\s+(?:[A-Z]\.?)?\d+(?:[-.–]\d+)*(?:\.(?=\s|$)|\s*$|(?=\s+[A-Z])))",
)

# Words. Above this a text block beside a figure is read as prose and not as
# its caption. The two errors are not alike: a caption read as prose stays in
# the section's text, while prose read as a caption is taken out of it. So
# the number is on the low side for a corpus with long captions (scientific
# papers reach 150 words) and such a corpus sets its own.
CAPTION_MAX_WORDS = 60

# How a figure/table list entry opens ("Figure 3 Annual totals 27").
DIRECTORY_FIGTAB_WORDS = ("Figure", "Table", r"Fig\.", r"Tab\.")

# What a table of contents, a list of figures or an index calls itself: a
# section with one of these in its title, found anywhere in it, is dropped as a
# directory at a lower bar than one without. Fragments of a pattern, matched
# without regard to case. The four words are the ones stage 3 has always used,
# two English and two German; a profile for another language writes its own.
DIRECTORY_TITLE_WORDS = ("inhalt", "verzeichnis", "contents", "directory")

# Bibliography titles: routed to the bibliography path of stage 4 rather than
# dropped as a directory listing.
BIBLIOGRAPHY_TITLE_WORDS = ("references", "bibliography", "works cited",
                            "literature cited")

# The one line of the user's turn when a page without a text layer is read
# by the vision model; the system prompt is prompts/preprocessing/
# page_transcribe.md.
PAGE_REQUEST = "Page {page}. Return the text of this page."

# What the text before a document's first heading is called, and a part of a
# split section that has no title of its own. Stored with the sections, shown
# in a citation and read by the model: changing them is a rebuild of stage 3.
FRONT_SECTION_TITLE = "Document"
PART_TITLE = "Section"
