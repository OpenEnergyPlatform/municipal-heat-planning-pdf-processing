"""Kommunale Wärmeplanung: German municipal heat plans from the KWW register."""
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="kwp",
    title="Kommunale Wärmeplanung – Recherche",
    document_noun="Wärmeplan",
    source_language="de",
    answer_language="de",
    column_layout="single",   # heat plans are single-column throughout
    # Filled by profiles/kwp/catalog.py; "jahr" is the year of the stored
    # publication token, so the filter and the label can never disagree.
    facets=(
        Facet("gemeinde", "Gemeinde"),
        Facet("bundesland_lang", "Bundesland"),
        Facet("jahr", "Jahr"),
    ),
)
