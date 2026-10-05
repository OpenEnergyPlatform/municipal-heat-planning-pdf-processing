"""Any folder of English documents: the profile this package brings itself.

It knows no subject. A project either runs under it as it is, or keeps a
profile of its own that extends it (`extends="default"`) and writes only
what it knows better: its title, its filters, a prompt, its fields.
"""
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="default",
    title="Document collection",
    document_noun="document",
    column_layout="auto",
    # Filled by catalog.py from DocumentMeta: the subfolder a file came from.
    facets=(
        Facet("folder", "Folder"),
    ),
)
