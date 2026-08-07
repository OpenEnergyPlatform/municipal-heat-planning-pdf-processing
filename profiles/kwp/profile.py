"""Kommunale Wärmeplanung: German municipal heat plans from the KWW register."""
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="kwp",
    title="Kommunale Wärmeplanung – Recherche",
    document_noun="Wärmeplan",
    source_language="de",
    answer_language="de",
    # Most plans are single-column, but roughly one in eight is typeset in two
    # columns throughout (measured over the corpus), and those read as nonsense
    # without this. Takes effect on the next Stage 3 (--rebuild-stage3).
    column_layout="auto",
    # Filled by profiles/kwp/catalog.py; "jahr" is the year of the stored
    # publication token, so the filter and the label can never disagree.
    facets=(
        Facet("gemeinde", "Gemeinde"),
        Facet("bundesland_lang", "Bundesland"),
        Facet("jahr", "Jahr"),
    ),
)
