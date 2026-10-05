"""
preprocessing.py – What text extraction has to know about English.

Author: Felix Vossel
"""

# A line ending in "-" is usually a word broken across the break, but not when
# the next line opens with one of these. English does it through suspended
# hyphenation — "short- and long-term", "pre- or post-2050", "CO2- and
# CH4-emissions" — which is far rarer than the German compound but produces the
# same damage when glued: "shortand long-term".
HYPHEN_EXCEPTIONS = (
    "and", "or", "nor", "but", "to", "as", "than", "versus", "vs",
    "plus", "minus", "through", "via", "of", "in", "on", "at", "by",
    "for", "with", "without", "between", "within", "under", "over",
    "before", "after", "e.g", "i.e", "etc",
)


# Caption openers that must never be promoted to a section heading. The German
# list would match nothing here, and every "Figure 3: ..." would open a section.
TITLE_EXCLUDE_PREFIXES = (
    "figure",
    "fig.",
    "table",
    "tab.",
    "box",
    "plate",
)

# What opens a caption (docpipe/captions.py): a word, a number, a colon. The
# pattern the core carried before it asked the profile, kept word for word so
# that every caption decision for this corpus stays what it was. The English
# forms without a colon ("Table 1", "Fig. 2") are the built-in profile's.
CAPTION_START = (
    r"(?:^|(?<=[\s\]]))([A-ZÄÖÜ][A-Za-zÄÖÜäöüß.]{2,14}\s+\d+(?:[-.–]\d+)*\s*:)",
)

# Journal and IPCC captions are not labels: panel descriptions, data sources
# and scenario legends routinely run 60-150 words, where a municipal heat plan
# sits at 8. Set high enough that those survive as captions instead of being
# read as body prose.
CAPTION_MAX_WORDS = 160

# How a figure/table list entry opens ("Figure 3 Global emissions 27").
DIRECTORY_FIGTAB_WORDS = ("Figure", "Table", r"Fig\.", r"Tab\.", "Box")

# Bibliography titles → routed to the Stage-4 [LITERATURE] BibTeX path.
BIBLIOGRAPHY_TITLE_WORDS = ("references", "bibliography", "works cited",
                            "literature cited")


# The one line of the user's turn when a page without a text layer is read
# by the vision model; the system prompt is prompts/preprocessing/
# page_transcribe.md.
PAGE_REQUEST = "Page {page}. Return the text of this page."

# What the text before a document's first heading is called, and a part of a
# split section that has no title of its own. German, although the corpus is
# English: these two words are stored with every section of the corpus as it
# was processed, and stage 3 finds its own front section by the first of
# them. Changing them is a rebuild of stage 3.
FRONT_SECTION_TITLE = "Dokument"
PART_TITLE = "Abschnitt"
