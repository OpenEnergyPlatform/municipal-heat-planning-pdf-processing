"""AR6 scenario literature: the publications the IIASA AR6 scenario database cites."""
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="scenarios",
    # Everything the default profile has, this one writes itself; a test
    # holds that, so no other prompt ever stands in for a missing one.
    extends="default",
    title="IPCC-AR6-Szenarienliteratur – Recherche",
    document_noun="Publikation",
    # Journal articles and agency reports are typeset in two columns far more
    # often than heat plans are, and a two-column page read line by line is
    # interleaved nonsense. Takes effect on the next Stage 3 (--rebuild-stage3).
    column_layout="auto",
    # Filled by profiles/scenarios/catalog.py; "year" is the year stored in
    # DocumentMeta, the same one the label prints.
    facets=(
        Facet("year", "Jahr"),
        Facet("venue", "Journal / Herausgeber"),
        Facet("scenario", "AR6-Szenario"),
    ),
)
