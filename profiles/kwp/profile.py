"""Kommunale Wärmeplanung: German municipal heat plans from the KWW register."""
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="kwp",
    source_language="de",
    answer_language="de",
    column_layout="single",   # heat plans are single-column throughout
    facets=(
        Facet("gemeinde", "Gemeinde"),
        Facet("bundesland_lang", "Bundesland"),
        Facet("jahr_veroeffentlichung", "Jahr"),
    ),
)
