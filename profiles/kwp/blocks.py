"""
blocks.py: The steps of a flow that only heat plans need (owner decision
2026-11-12, plan of the general blocks, point 8): what a number is, chosen
from the list of quantities, and the year of a value from the plan's base
and target years. The page offers them beside the general steps where this
profile is open (`blocks.offered`), and a flow of another profile cannot
take them.

Author: Felix Vossel
"""
from docpipe.extraction.blocks import NUMBERS, Box


def quantity(engine, node, scope) -> None:
    """What a number is, from the words it was read with
    (`addressed.Reader.quantity`)."""
    from docpipe.extraction import addressed
    from docpipe.extraction.engine import Answer
    coord = scope.get("coord")
    doc = scope.get("doc")
    with addressed.asking(addressed.Asking(
            node["id"], follow_ups=engine.follow_ups_of(node))):
        engine.reader.quantity(doc.plan, coord.read.batch.parameter,
                               coord.row, coord.slot, doc.counts)
    scope.put("answer", Answer(True))


def last_year(engine, node, scope) -> None:
    """The year a value's line means, from the plan's base and target
    years (`addressed.Reader.last_year`)."""
    from docpipe.extraction import addressed
    coord = scope.get("coord")
    doc = scope.get("doc")
    engine.coord_base(coord, doc.plan)
    with addressed.asking(addressed.Asking(
            node["id"], follow_ups=engine.follow_ups_of(node))):
        engine.reader.last_year(doc.plan, coord.read.batch.parameter,
                                coord.row, coord.slot, doc.counts,
                                coord.noted or {})


BOXES = (
    Box("quantity", "Ask what a number is", "ask", "coordinates", "answers",
        "Finds out what a number is, such as a demand or a share, from the "
        "words it was read with: its label, the head of its column and its "
        "unit. The model chooses the matching entry of the list of "
        "quantities. Example: \"Wärmebedarf\" in MWh/a becomes the entry heat "
        "demand. To change it: up to how many entries the list shows what "
        "they mean, and the entries of the list in the Spec tab; the prompt "
        "`list` shapes the question.",
        "addressed.Reader.quantity", asks="list", needs=("coordinate",),
        settings=NUMBERS, decided="2026-11-08",
        inputs=("dimension", "facts?"), outputs=("answer",),
        run=quantity),
    Box("last_year", "Ask a value's year among the plan's years", "ask",
        "coordinates",
        "answers",
        "A year that no step before it found is asked last: the request shows "
        "the value's line and the document's base and target years, and the "
        "model chooses the year the line means. Example: a line with the word "
        "\"Zieljahr\" means the target year 2040. To change it: switch it "
        "off; the years come from the fields of the whole document, and the "
        "prompt `list` shapes the question.",
        "addressed.Reader.last_year", asks="list", needs=("coordinate",),
        settings=NUMBERS, decided="2026-11-07",
        inputs=("dimension", "facts"), outputs=("answer",),
        run=last_year),
)
