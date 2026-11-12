"""
blocks.py: What only heat plans ask (owner decisions 2026-11-12: the plan
of the general blocks, point 8, and in the evening every question is "Ask
the model" with a preset): what a number is, chosen from the list of
quantities, and the year of a value from the plan's base and target years.
The page offers the two presets beside the general ones where this profile
is open (`blocks.offered`), and a flow of another profile cannot take them.

Author: Felix Vossel
"""
from docpipe.extraction.presets import VALUE_PLACE, Preset, i
from docpipe.extraction.targets import Target


def quantity(ask, counts):
    """What a number is, from the words it was read with: its own
    designation, the head of its column and its unit (rule
    `quantity_words`) go to the question of the list of quantities, asked
    as this step says (`addressed.Reader.quantity`)."""
    from docpipe.extraction.engine import Answer
    coord = ask.scope.get("coord")
    ask.reader.quantity(ask.plan, coord.read.batch.parameter, coord.row,
                        coord.slot, counts, node=ask.node)
    return Answer(True)


def plan_year(ask, counts):
    """A year nothing found, asked last with the plan's base and target
    years (owner decision 2026-11-07): the line of the value's place that
    names the plan's word for its state, and the year of the list it
    means; read where the words stand in that line and the year is one of
    the plan's (`pipeline.named_year`)."""
    from docpipe.extraction import forms
    from docpipe.extraction.addressed import resolve, years_listed
    from docpipe.extraction.fields import READ
    from docpipe.extraction.pipeline import merge_field
    from docpipe.extraction.targets import coord_notes
    reader, plan = ask.reader, ask.plan
    coord = ask.scope.get("coord")
    row, slot = coord.row, coord.slot
    listed = [b for b in plan.bases if b.get("axis") == slot.name]
    req = ask.request({"options": years_listed(listed)})
    shape, example = forms.of(ask.reply, req)
    reply = ask.ask(req, shape, example, counts,
                    **{**coord_notes(coord), "step": "plan_years"})
    if not isinstance(reply, dict):
        return None
    picks = reader._picks(reply, len(listed), False) or []
    got = resolve(req.shown, reply, plan.passages)
    if not picks or got.why is not None:
        return None
    state = row.claim.get(f"{slot.name}_state")
    row.claim.pop(f"{slot.name}_state", None)
    merge_field([row], req.shown.evidence(), slot, {"answers": {row.label: {
        "value": listed[picks[0] - 1]["year"], "value_raw": got.words,
        "quote": got.quote}}}, window=("plan_years", 1),
        bases=plan.bases, document=plan.document())
    if row.claim.get(f"{slot.name}_state") != READ and state:
        row.claim[f"{slot.name}_state"] = state
    return None


TARGETS = (
    Target("quantity", "what a number is",
           "The entry of the list of quantities the number's designation, "
           "column head and unit mean, read onto the value with the line "
           "of its designation, else its own.", quantity,
           gives=("words", "find", "options", "earlier", "dimension"),
           forms=("entry",)),
    Target("plan_year_of_value", "the year of a value among the plan's",
           "The year among the plan's base and target years that the "
           "value's line means, read with the line that says the plan's "
           "word for it.", plan_year, gives=("options",),
           forms=("year_choice",)),
)

PRESETS = (
    Preset(
        "quantity", "Ask what a number is",
        "Finds out what a number is, such as a demand or a share, from the "
        "words it was read with: its label, the head of its column and its "
        "unit (rule `quantity_words`). The model chooses the matching entry "
        "of the list of quantities. Example: \"Wärmebedarf\" in MWh/a becomes "
        "the entry heat demand. To change it: the inputs, up to how many "
        "entries the list shows what they mean, and the entries of the list "
        "in the Spec tab; the prompt `list` shapes the question.",
        "list",
        (i("words", "words", "always"),
         i("question", "dimension", "question"),
         i("lines", "find", "find_lines_if"),
         i("table", "find", "find_table"),
         i("settings", "document", "settings_text"),
         i("list", "options", "always"),
         i("earlier", "earlier", "as_is")),
        "entry", {"to": "quantity"},
        needs=("coordinate",), decided="2026-11-08"),
    Preset(
        "last_year", "Ask a value's year among the plan's years",
        "A year that no step before it found is asked last: the request shows "
        "the value's line and the document's base and target years, and the "
        "model chooses the year the line means. Example: a line with the word "
        "\"Zieljahr\" means the target year 2040. To change it: the inputs, "
        "or switch it off; the years come from the fields of the whole "
        "document, and the prompt `list` shapes the question.",
        "list",
        VALUE_PLACE + (
            i("question", "dimension", "question"),
            i("list", "options", "always")),
        "year_choice", {"to": "plan_year_of_value"},
        needs=("coordinate",), decided="2026-11-07"),
)
