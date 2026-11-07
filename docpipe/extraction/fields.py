"""
fields.py: Computes the deterministic skeleton of a tuple from the spec.

A tuple's shape is not something a model decides. The spec already
states which coordinates a parameter has, which of them are a choice
from a closed list, and which are a number or a wording, and that
shape is identical for every value in the corpus. So the shape is
computed here, from the spec, and the model is never asked for it. It
is asked, one field at a time, to fill the shape in.

Asking per field is the point. One request for every coordinate lets a
model quietly drop one it is unsure of, and dropping is
free: the field stays nullable, nothing refuses it, nothing counts
it. Measured on the 204 document corpus run, the year was missing on
63.5 percent of all values, and on 13 percent of those it stood in
the very quote the model had itself cited. A request that asks for
one field and shows the choices has no such exit: it names the entry
and the passage it was read in, or it states that the passage does
not say.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import wording
from .spec import UNIT, Parameter, fold_label

# What a slot wants back. VALUE is the only one that decides how many rows
# there are; every other slot fills a column of rows that already exist.
VALUE = "value"
CHOICE = "choice"
NUMBER = "number"
TEXT = "text"

# The answer that says the passages do not state this coordinate. It is an
# answer, not a gap: a row left out of a field reply and a row the document
# genuinely says nothing about used to be the same empty cell, and they were
# 16% to 34% of every coordinate on the 1079-document run. One of the two is
# a statement about the corpus and the other is a statement about the model,
# and a pipeline that cannot tell them apart can improve neither.
#
# A protocol token, not a German phrase: the prompt explains it in the
# profile's language, the wire carries this. It rides the out: convention, so
# the serializers already refuse to mint it as a class.
UNSTATED = "out:unstated"

# The entries a closed list marks the two ends of a range with, protocol
# tokens as UNSTATED is: in "zwischen 60 und 100 MWh" 60 is the lower and 100
# the upper end of one range, and the run links them on both rows under
# RANGE, [lower, upper] (`reading.link_ranges`, owner decision 2026-11-06).
RANGE_LOW = "out:range_low"
RANGE_HIGH = "out:range_high"
RANGE = "range"

# What is known about one coordinate of one row, always one of these.
READ = "read"                # answered, and the passage carries it
SAID_UNSTATED = "unstated"   # answered: the passages do not say it
UNANSWERED = "unanswered"    # the request came back without this row
# Still open when the sweep ran out of budget with the document
# unread to the end. Deliberately not "unstated": one is a finding
# about the document, the other is a finding about the run, and
# collapsing them is the mistake this module was written to stop
# making.
EXHAUSTED = "exhausted"
# Answered, and the answer could not be backed: the passage cited is
# not in anything the model was shown, or it is and does not carry
# the answer. Its own outcome, because "said nothing" and "said
# something it could not back" are different findings about the
# model, and collapsing them is the mistake this module exists to
# stop making. It stays open (a later window can still read the
# coordinate properly) and only survives to the end if none does.
UNBACKED = "unbacked"
# Filled without asking, because the spec already decides it: the
# parameter a unit belongs to, the aggregation every accepted unit of
# a parameter implies. Its own state, because "the spec knew this"
# and "the model read this" are different findings about the corpus,
# and a coordinate that carries evidence it was never given evidence
# for is the one thing this module exists to prevent. A derived
# coordinate still carries the wording it was derived from.
DERIVED = "derived"
# Never asked, because a gate coordinate already put this row outside
# what this run serializes. A finding about the run's scope, and
# neither about the document nor about the model, so it is not
# "unstated" and not "unanswered". It exists because the alternative
# is an empty cell, and an empty cell is the one thing every state in
# this module was written to prevent.
OUT_OF_SLICE = "out_of_slice"

# The key a coordinate carries when a pass after the harvest read it, a top-up
# that re-read it or a pass that appended its row: `<axis>_producer`, the
# position of the entry of the stamp's `producers` list that did. The harvest
# writes none, so a coordinate without it was read by the harvest, and one
# that no later pass touched must keep reading that way.
PRODUCER = "_producer"
BY_HARVEST, BY_PASS, BY_UNKNOWN = "harvest", "pass", "unknown"

# Every key one coordinate owns on a claim (`schema._slot_properties`): its
# answer and state, its wording, its quote and the passage that holds it,
# where it was read, what the model saw where it found it unstated, its link,
# the names of what it means (`naming.MEANS`) and the pass that read it.
# Taking a coordinate off, or copying it whole, means all of them.
COORDINATE_KEYS = ("", "_state", "_raw", "_raw_foreign", "_quote", "_source",
                   "_window", "_seen", "_link_quote", "_link_source",
                   "_means", PRODUCER)


def reader_of(row: dict, name: str, producers) -> tuple:
    """(who, index, entry) for the coordinate `name` of a stored row.

    No key: the harvest read it (BY_HARVEST). A key that points at an entry
    of `producers`: that pass did (BY_PASS). A key that points at none:
    BY_UNKNOWN, and never the harvest. `--recheck` deletes the stamps, so a
    position can outlive the list it was written for; reading that as the
    harvest would put a top-up's answer under a model that never saw it.
    """
    if f"{name}{PRODUCER}" not in row:
        return BY_HARVEST, None, None
    index = row[f"{name}{PRODUCER}"]
    if (not isinstance(index, int) or isinstance(index, bool)
            or not isinstance(producers, list)
            or not 0 <= index < len(producers)
            or not isinstance(producers[index], dict)):
        return BY_UNKNOWN, None, None
    return BY_PASS, index, producers[index]


@dataclass(frozen=True)
class Option:
    """One entry of a closed list, as the model sees it and as it comes back."""
    label: str                  # what the model answers
    uri: str                    # what the label resolves to
    synonyms: tuple = ()        # the other spellings the spec knows
    # What the term means, as the request shows it: the spec's gloss where it
    # has one, else the definition (owner decision 2026-11-05, ticket 26).
    definition: str = ""


@dataclass(frozen=True)
class Slot:
    """One field of one parameter: a single question with a single answer."""
    name: str
    kind: str
    required: bool = False
    question: Optional[str] = None
    options: tuple = ()
    # {"from": "unit", "value": uri} when the spec decides this coordinate.
    derive: Optional[dict] = None
    # The kind of thing whose name the document gives here, such as
    # "scenario" (`spec.Axis.merged`): a value stated for several of them is
    # one row per name, and which of the document's names mean the same thing
    # is asked once the document is read (`naming.py`).
    merged: Optional[str] = None
    # Whether an answer may be the print itself where the list has no entry
    # for it: the unit, which is never refused (owner decision 2026-11-07,
    # `pipeline.printed_only`).
    keeps_print: bool = False

    @property
    def is_closed(self) -> bool:
        return self.kind == CHOICE and bool(self.options)

    def answerable(self) -> dict:
        """The closed list as the request shows it, UNSTATED included.

        A finite set of correct answers is a choice, and "the passages do not
        state it" is one of the correct answers, so it belongs in the list the
        model picks from, not only in the prose above it. It was in the prompt
        and not in the options, which asks the model to remember a rule instead
        of reading a row.
        """
        # With a meaning where the ontology gives one. The prompt has
        # promised since the first run that the question names what each
        # entry means, and nothing did: the model was handed a class
        # identifier and a list of German words and asked to decide by
        # meaning rather than by which word looks nearest. Where no entry
        # has a meaning the short form stays, so a profile that has not
        # written any pays nothing for the promise.
        # The two keys are protocol, the same English pair in every profile
        # (a prompt that names them names these); the gloss of UNSTATED is
        # the profile's prose.
        # Each entry by its meaning only (owner decision 2026-11-07: the
        # answer is the entry the plan's words mean, never the nearest
        # spelling); the spellings stay in the spec for the check of an
        # answer that gives no wording (`pipeline.answer_in_quote`).
        words = wording.phrases()
        means = words["option_means"]
        out = {opt.label: {means: opt.definition} if opt.definition else {}
               for opt in self.options}
        out[UNSTATED] = {means: words["unstated_means"]}
        return out


def beside_names(slot: Slot) -> bool:
    """Does a coordinate of names take entries beside them
    (`spec.Axis.beside`, owner decision 2026-11-07): a free-text slot with a
    list?"""
    return slot.kind == TEXT and bool(slot.options)


def wording_asked(slot: Slot) -> bool:
    """Is the printed wording (`value_raw`) asked beside a coordinate's
    answer? Only where the answer is not the print itself: an entry of a
    list or a number, and a coordinate of names that takes entries beside
    them, whose entry the wording backs. A free text answer is its own
    wording; the request does not ask it twice, and the row keeps it as its
    wording (`pipeline.merge_field`, owner decision 2026-11-06)."""
    return bool(slot.is_closed) or slot.kind == NUMBER or beside_names(slot)


def value_schema(slot: Slot, unstated: bool = True) -> dict:
    """The answers a coordinate can take in a grammar: one entry of its list,
    UNSTATED included; for a number an integer or UNSTATED; else a wording.
    UNSTATED is an answer of every kind: a grammar that takes only an integer
    for a year leaves the model no way to say the passage prints none.
    Without *unstated* it is none: the combing leaves a coordinate it did not
    find out of its reply, and the run, not the model, says the plan does not
    state it once every passage was listed (owner decision 2026-11-06)."""
    if slot.is_closed:
        # A unit may be left without an entry where none fits; its print
        # is its answer then (`Slot.keeps_print`).
        return {"enum": [label for label in slot.answerable()
                         if unstated or label != UNSTATED]
                + ([""] if slot.keeps_print else [])}
    if slot.kind == NUMBER:
        if not unstated:
            return {"type": "integer"}
        return {"anyOf": [{"type": "integer"}, {"enum": [UNSTATED]}]}
    return {"type": "string"}


# What an example reply writes for an answer (`value_example`): a placeholder
# for an entry of a list or a wording, a year for a number, as the prompts'
# examples always did.
SAID = "..."
YEAR = 2022


def value_example(slot: Slot):
    """A coordinate's answer as the example of a request shows it, read and
    of the kind `value_schema` takes: an entry of its list or a wording as a
    placeholder, a number as a year. Never UNSTATED: an example shows every
    coordinate read (owner decision 2026-11-06), and the prompt's rule line
    shows how an unstated one looks."""
    if not slot.is_closed and slot.kind == NUMBER:
        return YEAR
    return SAID


def _options(vocabulary: dict, definitions: Optional[dict] = None,
             glosses: Optional[dict] = None) -> tuple:
    """The closed list as options, first label canonical, rest synonyms.

    The spec writes a vocabulary as uri -> [labels] and the first label is the
    one the class is called by; the others exist so a document's own spelling
    still resolves. Only the canonical one is offered, or the list the model
    reads would be four times as long for no added choice.

    The meaning rides along where the spec carries one, because "decide by
    the definition and not by the nearest word" is a rule that needs the
    definition in the request to be followable; in one line of the profile's
    language where the spec has that (*glosses*, ticket 26).
    """
    out = []
    for uri, labels in (vocabulary or {}).items():
        labels = [l for l in labels if isinstance(l, str) and l.strip()]
        if not labels:
            continue
        meaning = ((glosses or {}).get(uri)
                   or (definitions or {}).get(uri, ""))
        out.append(Option(label=labels[0], uri=uri, synonyms=tuple(labels[1:]),
                          definition=meaning))
    return tuple(out)


def parameter_slot(spec) -> Slot:
    """Which quantity a value is: a choice from the spec's own parameters.

    The plan used to be built per parameter, so a table holding a consumption
    and an emission was retrieved twice, read twice and paid for twice. It
    made the document's whole owner set into three documents' worth of
    requests, which was 804 planned sources against 234 owners.

    Asked instead of assumed, it is the same shape as every other coordinate:
    a finite list, one request, one quote. And it is a real question: a
    passage rarely says "this is an emission", it says "t CO2-Äq", so the
    evidence is the wording that makes it one.
    """
    return Slot(name="parameter", kind=CHOICE, required=True,
                question=spec.parameter_question,
                options=tuple(Option(label=p.label, uri=p.uri)
                              for p in spec.parameters))


def holds(parameter: Parameter, claim: dict) -> bool:
    """Is the row's value one of this parameter's entries?

    A category parameter's value is an answer to its closed list (owner,
    2026-09-11). The value is read before the parameter, as the wording the
    passage prints, so a row whose parameter is read with a value its list
    does not hold has the value asked again, to that list (`value_choice`).
    The lookup is the one `verify._check_value` resolves the value with.

    A value left out with the wording beside it is the answer that no entry
    fits, and fits every category parameter. A text or numeric parameter
    holds any value here; its own checks are elsewhere.
    """
    if parameter.value_type != "category":
        return True
    value = claim.get("value")
    if not isinstance(value, str) or not value.strip():
        return True
    return fold_label(value.strip()) in parameter.value_to_uri()


# Counted by a pass over a harvest on disk for a document whose own choice
# lists could not be closed. Such a file is left as it is: read against an
# empty list a choice degrades to a wording, and nothing would report it.
LISTS_UNREADABLE = "choice lists unreadable, left alone"


def has_number(claim: dict) -> bool:
    """Is this row's value a number, so that a unit belongs to it?

    Asked only where a unit can be: of a spec with a numeric parameter. A
    wording there is a text parameter's value and carries no unit, whatever
    the value request wrote beside it. A spec without one has no unit
    question, and what counts as a wording there is `is_wording`'s to say.
    """
    from .verify import canonical_number
    value = claim.get("value")
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and canonical_number(value) is not None


def unit_slot(spec, parameter: Optional[Parameter] = None) -> Optional[Slot]:
    """Which entry of units_accepted a number is in: a choice, with a passage.

    A coordinate like the parameter, and asked before it: the value request
    writes the unit as the passage prints it, and which entry that means is a
    reading, not a lookup. "450 kWh über das Jahr" is kWh/a and a storage
    capacity of 200 kWh is kWh; "Gigawattstunden" is GWh; "kWh/m²a" is in no
    list and the number keeps the unit as printed, unconverted. A
    spelling table stood in for this reading once, and measured on 641 plans
    of corpus_m5 it let 3,324 tuples carry an entry their wording
    contradicts.

    Every numeric parameter's list at once when no parameter is named,
    because the entry chosen is what settles the parameter
    (`derive_parameter`); beside each entry stands the parameter it belongs
    to, which is the meaning the model decides by. One parameter's list for a
    stored row that already knows its parameter (the schema, a top-up). None
    for a spec without a numeric parameter.
    """
    holders = [p for p in spec.parameters
               if p.is_numeric and (parameter is None or p is parameter)]
    belongs: dict = {}
    for holder in holders:
        for unit in holder.units_accepted:
            belongs.setdefault(unit, []).append(holder.label)
    if not belongs:
        return None
    return Slot(name=UNIT, kind=CHOICE, required=True,
                question=spec.unit_question,
                options=tuple(Option(label=unit, uri=unit,
                                     definition=", ".join(labels))
                              for unit, labels in belongs.items()),
                keeps_print=True)


def asked_slots(parameter: Parameter) -> list:
    """The coordinates a request has to ask for: every axis the spec does not
    already decide."""
    return [slot for slot in axis_slots(parameter) if not slot.derive]


def frame_slots(spec, names) -> list:
    """The coordinates the profile says span the document's frame, in its order.

    A frame coordinate belongs to the DOCUMENT and not to the row. A plan has
    three scenario containers and a handful of reference years, and they stand
    in headings, captions and column headers, while the carrier and the
    sector stand in the table row itself and are different in every cell. The
    first kind can be found once and then asked about; the second cannot.

    WHICH ones those are is the profile's business. The core never names a
    coordinate, so this takes a list of names and resolves it against the
    spec, exactly like `SLICE` does for the gate.

    Read off the first parameter that has all of them, because a frame is one
    per document: a spec whose parameters disagreed about it would have two
    frames and no way to say which one a value hangs in. A name no parameter
    has yields nothing at all rather than a shorter frame: half a frame is
    a pair set that is silently missing a coordinate.
    """
    wanted = [name for name in (names or ())]
    if not wanted:
        return []
    for parameter in spec.parameters:
        by_name = {slot.name: slot for slot in axis_slots(parameter)}
        if all(name in by_name for name in wanted):
            return [by_name[name] for name in wanted]
    return []


def is_wording(spec, claim: dict) -> bool:
    """Is this row's value a wording, which only a parameter that is not
    numeric can hold?

    A string that is no number is one. In a spec without a numeric parameter
    every string is: "2030" is a year there, and that a number without a
    unit belongs to no parameter is a rule about parameters that have units.
    Read as a number, every bare year and every dotted date of such a spec
    left the harvest `out_of_slice`, unasked.

    There a row whose value was left out, with the wording in `value_raw`,
    is one too: that is how the value request says no entry of the list
    fits, and the row is kept with its wording. A value that is no string
    and has no wording beside it is not one. No parameter takes it, so
    asking would pay for a refusal.

    The rule stops at a spec with a numeric parameter: there a digit string
    is a number, whichever text parameter might have held a year.
    """
    from .verify import canonical_number
    value = claim.get("value")
    measured = any(p.is_numeric for p in spec.parameters)
    if isinstance(value, str):
        return not measured or canonical_number(value) is None
    if measured:
        return False
    wording = claim.get("value_raw")
    return isinstance(wording, str) and bool(wording.strip())


def derive_parameter(spec, claim: dict):
    """Which parameter this row belongs to, or None when that is a question.

    A wording belongs to the text parameter when the spec has exactly one.
    A number is decided by its unit alone.

    The spec says it itself: "the unit separates the two parameters". Measured
    over the kwp spec the nine energy units and the forty-two emission units
    share not one spelling, and over Kassel not one of 559 accepted tuples
    contradicted its unit. Asking anyway cost 322 of 1,043 field windows, 30.9
    percent, and 18.0 of 187.5 field minutes per plan.

    None whenever the unit does not settle it: no unit, a unit no parameter
    accepts (the row is refused later, with the unit as the reason), or a unit
    two parameters accept. Then the question is a real question and is asked.
    """
    if is_wording(spec, claim):
        text = [p for p in spec.parameters if not p.is_numeric]
        return text[0] if len(text) == 1 else None
    # The entry the unit question read, never the wording beside it: the
    # wording is what the passage prints, and which entry it means was a
    # question of its own (`unit_slot`).
    unit = claim.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        return None
    holders = [p for p in spec.parameters
               if p.is_numeric and unit in p.units_accepted]
    return holders[0] if len(holders) == 1 else None


def parameter_undecidable(spec, claim: dict) -> bool:
    """True when NO parameter of the spec could hold this row.

    `derive_parameter` returns None for three different situations and only
    one of them is a question: a unit two parameters accept. The other two,
    no unit at all, and a unit no parameter accepts, are already decided
    AGAINST every answer the model could give, because `verify._check_value`
    refuses on the same `unit_factor` lookup that just failed.

    Measured on the M3 acceptance run: 69 rows reached the parameter sweep,
    45 with a unit no parameter accepts and 24 with no unit. Not one was
    ambiguous, because the kwp spec's two numeric unit lists share no
    spelling. They cost 178 of 853 field requests, 20.9 percent, and every
    one of the five answers they produced was refused afterwards anyway.
    """
    if is_wording(spec, claim):
        # A wording needs a text parameter, and one is a decision.
        return not [p for p in spec.parameters if not p.is_numeric]
    unit = claim.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        # The unit question read no entry: the passages do not state one,
        # or state one no list holds. Either way no parameter can take the
        # row, and `verify._check_value` refuses it with the wording.
        return True
    return not [p for p in spec.parameters
                if p.is_numeric and unit in p.units_accepted]


def derived_by_unit(claim: dict, parameter) -> bool:
    """Does the spec decide the coordinates it derives from the unit for this
    value: the unit question read an entry of the parameter's list that
    converts onto the parameter's own unit? Where it read the print without
    one, the model is asked them (owner decision 2026-11-07: "wo es nicht
    automatisch geht, soll es das LLM versuchen"); so is a value whose entry
    converts onto a unit of its own, an emission factor in g CO2/kWh being
    no annual amount."""
    unit = claim.get(UNIT)
    return (claim.get(f"{UNIT}_state") == READ
            and parameter.unit_factor(unit) is not None
            and parameter.target_of(unit) == parameter.unit_target)


def derives(slot, claim: dict, parameter) -> bool:
    """Does the spec set *slot* for this value instead of asking it: the
    unit decides it (`derived_by_unit`), and the coordinate the spec names in
    `unless_read` was not read. "im Mittel der Jahre 2019 bis 2021" in MWh/a
    is a mean and no annual sum, so where the plan names the start of a span
    the aggregation is asked (owner decision 2026-11-07: "Wenn es nach OEO
    ein Mittelwert ist, dann ist es ein Mittelwert")."""
    if not slot.derive or not derived_by_unit(claim, parameter):
        return False
    unless = slot.derive.get("unless_read")
    return not (unless and claim.get(f"{unless}_state") == READ)


def apply_derived(rows: list, slot: Slot) -> int:
    """Write a derived coordinate onto every row that has none. Returns how many.

    The wording it was derived from is kept, and so is the row's own passage:
    a derived coordinate is not evidence-free, it is evidenced by the unit the
    value request already quoted.
    """
    if not slot.derive:
        return 0
    done = 0
    for row in rows:
        if row.claim.get(f"{slot.name}_state"):
            continue
        row.claim[slot.name] = slot.derive["value"]
        row.claim[f"{slot.name}_state"] = DERIVED
        wording = row.claim.get("unit_raw") or row.claim.get("unit")
        if wording:
            row.claim[f"{slot.name}_raw"] = wording
        # The passage the unit was read in, where the unit question read one;
        # the value's own passage where the unit slot was not answered.
        quote = row.claim.get("unit_quote") or row.claim.get("quote")
        if quote:
            row.claim[f"{slot.name}_quote"] = quote
        done += 1
    return done


def value_slot(parameter: Parameter) -> Slot:
    """The row maker: the one request that decides how many values there are."""
    if parameter.is_numeric:
        return Slot(name="value", kind=VALUE, required=True,
                    question=parameter.description)
    return Slot(name="value", kind=VALUE, required=True,
                question=parameter.description,
                options=_options(parameter.vocabulary,
                                 getattr(parameter, "definitions", None),
                                 getattr(parameter, "glosses", None)))


def value_choice(parameter: Parameter) -> Slot:
    """The value of a category parameter, asked again as one of its entries.

    The rows request reads a value before its parameter, so what it writes is
    the wording the passage prints: "includes only adopted policies" where
    the list holds the types of a scenario. Once the parameter is read, which
    entry that wording is becomes a question of its own, with a quote like
    every coordinate, and the wording stays in value_raw. Asking the
    parameter again instead left the model no answer that could pass: on one
    corpus run 8,810 rows were asked it in every window to the end of their
    document, and 5,636,615 answers were refused.
    """
    return Slot(name="value", kind=CHOICE, required=True,
                question=parameter.description,
                options=_options(parameter.vocabulary,
                                 getattr(parameter, "definitions", None),
                                 getattr(parameter, "glosses", None)))


def axis_slots(parameter: Parameter) -> list:
    """Every coordinate of this parameter, in spec order, as its own question.

    A dynamic axis whose list the profile could not fill for this document has
    no options left, so it degrades to a wording, the same rule verify.py
    follows one step later.
    """
    out = []
    for name, axis in parameter.axes.items():
        if axis.vocabulary:
            slot = Slot(name=name, kind=CHOICE, required=axis.required,
                        question=axis.question,
                        options=_options(axis.vocabulary, axis.definitions,
                                         axis.glosses),
                        derive=axis.derive)
        elif axis.enum:
            slot = Slot(name=name, kind=CHOICE, required=axis.required,
                        question=axis.question,
                        options=tuple(Option(label=e, uri=e) for e in axis.enum))
        elif axis.type == "int":
            slot = Slot(name=name, kind=NUMBER, required=axis.required,
                        question=axis.question)
        else:
            # A coordinate of names keeps the entries it takes beside them
            # as its list (`beside_names`).
            slot = Slot(name=name, kind=TEXT, required=axis.required,
                        question=axis.question,
                        options=_options(getattr(axis, "beside", None),
                                         axis.definitions, axis.glosses),
                        merged=getattr(axis, "merged", None))
        out.append(slot)
    return out


def slots(parameter: Parameter) -> list:
    """The full skeleton: the value slot first, then every coordinate."""
    return [value_slot(parameter)] + axis_slots(parameter)
