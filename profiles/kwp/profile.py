"""Kommunale Wärmeplanung: German municipal heat plans from the KWW register."""
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="kwp",
    title="Kommunale Wärmeplanung – Recherche",
    document_noun="Wärmeplan",
    source_language="de",
    answer_language="de",
    # Measured over the 801-document corpus: 184 plans have multi-column pages,
    # 44 of them throughout. Mostly two columns, a handful of three, one of
    # four. Those pages read as interleaved nonsense without this.
    # Takes effect on the next Stage 3 (--rebuild-stage3).
    column_layout="auto",
    # Filled by profiles/kwp/catalog.py; "jahr" is the year of the stored
    # publication token, so the filter and the label can never disagree.
    facets=(
        Facet("gemeinde", "Gemeinde"),
        Facet("bundesland_lang", "Bundesland"),
        Facet("jahr", "Jahr"),
    ),
)
