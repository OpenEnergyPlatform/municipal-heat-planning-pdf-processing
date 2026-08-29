"""
config.py – Constants for the AR6 profile. The corpus is one JSON index next to
its PDFs, so there is little to configure.

Author: Felix Vossel
"""

# Siblings of pdf_index.json, both produced by their own step of the crawl and
# both optional: without them the scenarios have no names and the publications
# no title, year or venue.
SCENARIO_FILE = "ar6_scenarios.json"
PUBLICATION_META_FILE = "publication_meta.json"

# The status pdf_index.json gives an entry whose PDF was actually fetched.
# Every other status ("closed", "kein_dokument", …) is a bibliography entry
# without a file.
AVAILABLE_STATUS = "pdf"

PDF_SUFFIX = ".pdf"

# A publication is dated by its year only; the core stores a day-precise token,
# so the year is pinned to its first day.
PUBLISHED_DAY = "0101"
