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
