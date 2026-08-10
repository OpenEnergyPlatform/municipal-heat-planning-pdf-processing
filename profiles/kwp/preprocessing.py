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
