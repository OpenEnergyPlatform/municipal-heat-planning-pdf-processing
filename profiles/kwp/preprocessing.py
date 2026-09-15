"""
preprocessing.py – What text extraction has to know about German.

Author: Felix Vossel
"""

# A line ending in "-" is usually a word broken across the break, but not when
# the next line opens with one of these: "Wärme-" + "und Kälteversorgung" is a
# construction, and gluing it gives "Wärmeund Kälteversorgung".
HYPHEN_EXCEPTIONS = (
    "und", "oder", "bzw", "etc", "sowie", "als", "wie", "auch", "denn",
    "noch", "sondern", "doch", "jedoch", "allerdings", "hingegen",
    "beziehungsweise", "insbesondere", "zum", "zur", "im", "in", "am",
    "an", "auf", "von", "mit", "für", "über", "unter", "zwischen",
    "ohne", "gegen", "bis", "durch", "trotz", "wegen", "während",
)


# Caption openers that must never be promoted to a section heading. Without
# them "Abbildung 3: ..." becomes a title and opens a section (stage2_layout).
TITLE_EXCLUDE_PREFIXES = (
    "abbildung",
    "abb.",
    "tabelle",
    "tab.",
)

# A caption is a label, not a paragraph. Measured on this corpus: 8 words
# median, 24 at the 99th percentile, 205 captions past 40 words, longest 156.
# Above this the nearest-text-block fallback adopts whole prose paragraphs —
# and since the winning block is REMOVED from the page, that prose is lost.
CAPTION_MAX_WORDS = 45

# How a figure/table list entry opens ("Abbildung 3: ... 27"), for the
# deterministic directory removal in Stage 3.
DIRECTORY_FIGTAB_WORDS = ("Abbildung", "Tabelle", r"Abb\.", r"Tab\.")

# Bibliography titles → routed to the Stage-4 [LITERATURE] BibTeX path rather
# than dropped as a directory listing.
BIBLIOGRAPHY_TITLE_WORDS = ("literatur", "quellen", "referenz", "bibliograf")
