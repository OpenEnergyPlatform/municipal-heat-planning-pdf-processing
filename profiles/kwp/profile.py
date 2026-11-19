"""Kommunale Wärmeplanung: German municipal heat plans from the KWW register."""
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="kwp",
    # Everything the default profile has, this one writes itself, except the
    # prompts that are the default's byte for byte: those are inherited and
    # not copied. A test holds that list, so no English prompt ever stands in
    # for a missing one.
    extends="default",
    # Heat plans are published by the municipalities that adopt them.
    documents_shareable=True,
    title="Kommunale Wärmeplanung – Recherche",
    document_noun="Wärmeplan",
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


# The data files of this profile that no other tab of the editor edits, shown
# in its Sources tab (owner request 2026-11-19, A2: "Daten eines Profils ohne
# Platz in der Seite"): the file in this folder, what it holds, whether a
# person keeps it (kept) or a fetch writes it, and for a kept one what a key
# and an entry have to be (a pattern, a JSON schema). Read by config.py.
DATA_FILES = (
    {"file": "pdf_overrides.json", "kept": True,
     "about": "Municipalities whose PDF link in the register is broken, by "
              "Gemeindeschlüssel: the local file used instead (file), the "
              "municipality (place) and why (why). The file is placed in "
              "the data folder by hand and never downloaded; a file the "
              "register renamed is held to the name it is registered under "
              "the same way.",
     "key": r"^\d{7,8}$",
     "value": {"type": "object", "required": ["file"],
               "properties": {"file": {"type": "string", "minLength": 1},
                              "place": {"type": "string"},
                              "why": {"type": "string"}},
               "additionalProperties": False}},
    {"file": "shared_file_owners.json", "kept": True,
     "about": "Files the register hands to several municipalities that are "
              "not a convoy, by local file name: the Gemeindeschlüssel of "
              "the municipality the document belongs to (owner), read off "
              "the document, its name (place) and why (why). The other "
              "municipality has no plan of its own until it has its real "
              "link.",
     "key": r"^\S+\.pdf$",
     "value": {"type": "object", "required": ["owner"],
               "properties": {"owner": {"type": "integer"},
                              "place": {"type": "string"},
                              "why": {"type": "string"}},
               "additionalProperties": False}},
)
