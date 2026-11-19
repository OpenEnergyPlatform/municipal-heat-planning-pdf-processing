"""Scenario literature: publications on climate and energy scenarios."""
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="scenarios",
    # Everything the default profile has, this one writes itself, except the
    # prompts that are the default's byte for byte: those are inherited and
    # not copied. A test holds that list, so no other prompt ever stands in
    # for a missing one.
    extends="default",
    title="Scenario literature – research",
    document_noun="publication",
    # Journal articles and agency reports are typeset in two columns far more
    # often than heat plans are, and a two-column page read line by line is
    # interleaved nonsense. Takes effect on the next Stage 3 (--rebuild-stage3).
    column_layout="auto",
    # Filled by profiles/scenarios/catalog.py; "year" is the year stored in
    # DocumentMeta, the same one the label prints.
    facets=(
        Facet("year", "Year"),
        Facet("venue", "Journal / publisher"),
    ),
)


# The data files of this profile that no other tab of the editor edits, shown
# in its Sources tab (owner request 2026-11-19, A2: "Daten eines Profils ohne
# Platz in der Seite"): the file in this folder, what it holds, whether a
# person keeps it (kept) or a fetch writes it (`vocabulary.WRITES`), and for
# a kept one what a key and an entry have to be (a pattern, a JSON schema).
DATA_FILES = (
    {"file": "region_aliases.json", "kept": True,
     "about": "The spellings a document writes for a region that the OEKG "
              "does not carry, by the region's IRI, in their order. A fetch "
              "puts them before the OEKG's own labels in regions.json; a "
              "region the OEKG does not have is not offered.",
     "key": r"^https?://\S+$",
     "value": {"type": "array", "minItems": 1,
               "items": {"type": "string", "minLength": 1}}},
    {"file": "regions.json", "kept": False,
     "about": "Every region the OEKG has, by its IRI, with its spellings: "
              "those of region_aliases.json first, then the OEKG's labels. "
              "Written by a fetch."},
    {"file": "region_names.json", "kept": False,
     "about": "The name the graph gives each region, by its IRI, from the "
              "ISO 3166-1 list. Written by a fetch."},
    {"file": "region_aggregates.json", "kept": False,
     "about": "The groups of countries a document may name (the regions of "
              "the IIASA models, M49, the groups of the World Bank), each "
              "with its spellings, its members and where it comes from. "
              "Written by a fetch."},
)
