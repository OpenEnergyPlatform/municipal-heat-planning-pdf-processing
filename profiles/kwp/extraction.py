"""Extraction stage wiring: the kwp spec, the slice gate, the frame, and what
a plan says about itself."""
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")

# Which coordinates decide whether a value belongs in the graph at all, in the
# order they are asked, and which answers keep the row. They are asked FIRST
# and alone: a row that falls out here costs three requests instead of eight.
# Measured on the 20-plan draft, of 6,763 harvested tuples the serializer
# dropped 1,554 for a quantity the graph does not hold.
#
# THE SCENARIO NO LONGER GATES. It did, and it was the bigger half: 2,510 of
# those 6,763 tuples were dropped for being a status quo, a trend or a
# potential rather than the target scenario, and dropping them was a decision
# about the graph rather than about the plan. MHPO names all three
# (aggregated inventory analysis MHPO_00020005, aggregated potential analysis
# MHPO_00020006) and OEO names the reference scenarios, so a heat plan's
# inventory belongs in the graph as much as its target does and the row has
# to be asked its coordinates to get there.
#
# What still gates is the quantity, and only through its out: entries: those
# are deliberate non-classes the model chose (a share, a specific figure, a
# generation amount), and no ontology term is waiting for them.
#
# None means "any class the graph takes", which is every entry that does not
# start with out:. A tuple names the answers that keep the row.
SLICE = {"quantity": None}


def document_context(conn, document_id: int) -> dict:
    """What this plan says about itself, for the sentence it is searched with.

    The municipality, because a plan writes its own name into headings,
    captions and table titles, and a search anchor that carries it ranks this
    plan's own sections above the boilerplate every plan shares. It lives in
    the catalog join and in no query the core makes, so the core asks the
    profile for it rather than growing a second idea of what a document is.

    Missing metadata is not an error here. The anchor is written from the
    ontology annotation either way and this only makes it sharper.
    """
    try:
        row = conn.execute("""
            SELECT m.name
            FROM Documents d
            LEFT JOIN DocumentMeta dm  ON dm.document = d.id
            LEFT JOIN Municipalities m ON dm.municipality_ags = m.ags
            WHERE d.id = ?
        """, (document_id,)).fetchone()
    except Exception:
        return {}
    # By position. Whether a connection carries a row factory is the caller's
    # business, and a hook that only works on one of the two shapes is a hook
    # that works until somebody passes a plain connection.
    name = row[0] if row else None
    return {"name": name} if name else {}


# Which coordinates belong to the DOCUMENT and not to the row. A plan has
# three scenario containers and a handful of reference years, and they stand
# in headings, captions and column headers -- the carrier and the sector stand
# in the table row itself and are different in every cell. So these two are
# found ONCE, before any value, and every value request afterwards asks for
# one of the pairs that were really found.
#
# Not a cross product. A plan with a target scenario for 2030/2035/2040/2045
# and an inventory for 2022 has five pairs, not twenty.
#
# Measured on M3, this is what it replaces: the year axis produced 1,849
# refusals against 0 readings, because every window after the first excluded
# the row's own source and only that one could carry the year.
FRAME = ("scenario", "year")

# The pair a passage is read under when it names no part of any pair the
# frame found, no scenario and no year: an inventory table that states
# neither is the plan's inventory. Owner decision 2026-09-10, after Kassel's
# Tabelle 3 (CO2 by sector and carrier, no year anywhere) left 35 values
# without one. Used only when a document has exactly one such pair.
FRAME_DEFAULT = {"scenario": "status_quo"}
