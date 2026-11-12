"""
blocks.py: The steps of a flow that only scenario papers need (owner
decision 2026-11-12, plan of the general blocks, point 8): the works a
publication presents, compares or cites, the work of a value, and the entry
of a scenario's name in the document's list. The page offers them beside the
general steps where this profile is open (`blocks.offered`), and a flow of
another profile cannot take them.

Author: Felix Vossel
"""
from docpipe.extraction.blocks import (FETCH_ROUNDS, FETCHES, NUMBERS, Box)


def works(engine, node, scope) -> None:
    """The works each chunk names, matched against the document's list of
    works, and the details of each new one (`addressed.Reader.works`)."""
    from docpipe.extraction import addressed
    reader = engine.reader
    doc = scope.get("doc")
    plan = doc.plan
    if reader.works_field is None or "work" not in plan.names:
        return
    with addressed.asking(addressed.Asking(
            node["id"], follow_ups=engine.number(node, "follow_ups"))):
        doc.reads.extend(reader.works(plan, plan.pieces(False), doc.counts))


def names(engine, node, scope) -> None:
    """The entry of the document's list each row of a value names
    (`addressed.Reader.named_value`)."""
    from docpipe.extraction import addressed
    value = scope.get("value")
    doc = scope.get("doc")
    plan = doc.plan
    parameter = value.read.batch.parameter
    merged = getattr(parameter, "merged", None)
    if not merged or merged not in plan.names:
        return
    with addressed.asking(addressed.Asking(
            node["id"], follow_ups=engine.follow_ups_of(node))):
        for one in value.rows:
            engine.reader.named_value(plan, parameter, one, doc.counts)


def work_coordinate(engine, node, scope) -> None:
    """The work a value belongs to (`addressed.Reader.work_coordinate`)."""
    from docpipe.extraction import addressed
    from docpipe.extraction.engine import Answer
    coord = scope.get("coord")
    doc = scope.get("doc")
    if "work" not in doc.plan.names:
        return
    with addressed.asking(addressed.Asking(
            node["id"], follow_ups=engine.number(node, "follow_ups"))):
        engine.reader.work_coordinate(
            doc.plan, coord.read, coord.row, coord.slot, doc.counts)
    scope.put("answer", Answer(True))


BOXES = (
    Box("works", "Ask the works of each chunk", "ask", "pieces", "values",
        "For each chunk the model says which lines speak of another work, a "
        "study or plan that is presented, compared or cited, and which line "
        "shows that the remaining lines belong to this publication. Each "
        "named work is looked up in the document's list of works, and each "
        "new work is asked for its details. Example: \"IEA (2021) Net Zero by "
        "2050\" in a comparison table becomes a work with its title, "
        "organisation and year. To change it: the follow-up questions, the "
        "answers in the wrong form and what the model may ask to see "
        "(`fetches`, `fetch_rounds`); what is asked about a new work is set "
        "under the works in the Spec tab.",
        "addressed.Reader.works", asks="work",
        settings=NUMBERS + (FETCHES, FETCH_ROUNDS),
        decided="2026-11-09, 2026-11-12", spec="works", top=True,
        inputs=("chunks", "lists"), outputs=("values", "lists"),
        run=works),
    Box("work_coordinate", "Ask a value's work", "ask", "coordinates",
        "answers",
        "Decides which work a value belongs to: where the value's line names "
        "a work, that is its work; otherwise the model chooses an entry of "
        "the document's list of works, and 0 means the work is not stated. It "
        "never searches the document. Example: a number in a row labelled "
        "\"IEA NZE\" belongs to that study, not to this publication. To "
        "change it: the follow-up questions; the step needs the works in the "
        "Spec tab, and the prompt `coord` shapes the question.",
        "addressed.Reader.work_coordinate", asks="coord",
        needs=("coordinate",), settings=NUMBERS, decided="2026-11-09",
        spec="works",
        inputs=("dimension", "lists"), outputs=("answer",),
        run=work_coordinate),
    Box("names", "Ask the list entry of a name", "ask", "values", "values",
        "Looks up a value that names a scenario in the document's list: the "
        "entry it is, or a new entry where the name is not on the list yet; 0 "
        "keeps the value without an entry. Words for several entries (\"all "
        "scenarios\") become one row per member where the field allows it. "
        "Example: \"NDC\" in a figure is the entry \"Nationally Determined "
        "Contributions\" named in chapter 2. To change it: what the model may "
        "ask to see (`fetches`, `fetch_rounds`), and the keys `merged` and "
        "`takes_group` of the field in the Spec tab, which this step needs.",
        "addressed.Reader.named_value", asks="names", needs=("value",),
        settings=NUMBERS + (FETCHES, FETCH_ROUNDS),
        decided="2026-11-08, 2026-11-12", spec="names",
        inputs=("value", "lists", "facts?"), outputs=("values",),
        run=names),
)
