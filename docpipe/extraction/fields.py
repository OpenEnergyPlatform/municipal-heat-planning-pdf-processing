"""
fields.py – The deterministic skeleton of a tuple.

A tuple's shape is not something a model decides. The spec already says which
coordinates a parameter has, which of them are a choice from a closed list and
which are a number or a wording, and that shape is identical for every value
in the corpus. So it is computed here, from the spec, and the model is never
asked for it. It is asked, one field at a time, to fill it.

Asking per field is the point. One request for a whole tuple lets a model
quietly drop a coordinate it is unsure of, and dropping is free: the field is
nullable, nothing refuses, nothing counts it. Measured on the 204-document
corpus run, the year was missing on 63.5% of all values, and on 13% of those
it stood in the very quote the model had itself cited. A request that asks for
one field and shows the choices has no such exit — it names the entry and the
passage it read it in, or it says the passage does not say.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .spec import Parameter

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

# What is known about one coordinate of one row, always one of these.
READ = "read"              # answered and the passage carries it
SAID_UNSTATED = "unstated"  # answered: the passages do not say
UNANSWERED = "unanswered"   # the request came back without this row at all
# Still open when the sweep ran out of budget with the document unread to the
# end. Deliberately not "unstated": one is a finding about the plan, the other
# is a finding about the run, and collapsing them is the mistake this module
# was written to stop making.
EXHAUSTED = "exhausted"
# Answered, and the answer could not be backed: the passage cited is not in
# anything the model was shown, or it is and does not carry the answer. Its own
# outcome, because "said nothing" and "said something it could not back" are a
# different finding about the model and collapsing them is the mistake this
# module exists to stop making. It stays OPEN — a later window can still read
# the coordinate properly — and only survives to the end if none does.
UNBACKED = "unbacked"
# Filled without asking, because the spec already decides it: the parameter a
# unit belongs to, the aggregation every accepted unit of a parameter implies.
# Its own state, because "the spec knew this" and "the model read this" are a
# different finding about the corpus, and a coordinate that carries evidence
# it was never given evidence for is the one thing this module exists to
# prevent. What is derived still carries the wording it was derived FROM.
DERIVED = "derived"
# Never asked, because a gate coordinate already put this row outside what
# this run serializes. A finding about the RUN'S SCOPE, and neither about the
# plan nor about the model, so it is not "unstated" and not "unanswered". It
# exists because the alternative is an empty cell, and an empty cell is the
# one thing every state in this module was written to prevent.
OUT_OF_SLICE = "out_of_slice"


@dataclass(frozen=True)
class Option:
    """One entry of a closed list, as the model sees it and as it comes back."""
    label: str                  # what the model answers
    uri: str                    # what the label resolves to
    synonyms: tuple = ()        # the other spellings the spec knows
    definition: str = ""        # what the ontology says the term means


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
    # "own" | "local" | "any" — how far from the row its evidence may stand.
    evidence: str = "any"

    @property
    def is_closed(self) -> bool:
        return self.kind == CHOICE and bool(self.options)

    def answerable(self) -> dict:
        """The closed list as the request shows it, UNSTATED included.

        A finite set of correct answers is a choice, and "the passages do not
        state it" is one of the correct answers — so it belongs in the list the
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
        if any(opt.definition for opt in self.options):
            out = {opt.label: {"bedeutet": opt.definition,
                               "Schreibweisen": list(opt.synonyms)}
                   if opt.definition else {"Schreibweisen": list(opt.synonyms)}
                   for opt in self.options}
            out[UNSTATED] = {"bedeutet": "in diesen Passagen steht es nicht"}
            return out
        out = {opt.label: list(opt.synonyms) for opt in self.options}
        out[UNSTATED] = ["steht in diesen Passagen nicht"]
        return out


def _options(vocabulary: dict, definitions: Optional[dict] = None) -> tuple:
    """The closed list as options — first label canonical, rest synonyms.

    The spec writes a vocabulary as uri -> [labels] and the first label is the
    one the class is called by; the others exist so a document's own spelling
    still resolves. Only the canonical one is offered, or the list the model
    reads would be four times as long for no added choice.

    The meaning rides along where the spec carries one, because "decide by
    the definition and not by the nearest word" is a rule that needs the
    definition in the request to be followable.
    """
    out = []
    for uri, labels in (vocabulary or {}).items():
        labels = [l for l in labels if isinstance(l, str) and l.strip()]
        if not labels:
            continue
        out.append(Option(label=labels[0], uri=uri, synonyms=tuple(labels[1:]),
                          definition=(definitions or {}).get(uri, "")))
    return tuple(out)


def parameter_slot(spec) -> Slot:
    """Which quantity a value is — a choice from the spec's own parameters.

    The plan used to be built per parameter, so a table holding a consumption
    and an emission was retrieved twice, read twice and paid for twice. It
    made the document's whole owner set into three documents' worth of
    requests, which was 804 planned sources against 234 owners.

    Asked instead of assumed, it is the same shape as every other coordinate:
    a finite list, one request, one quote. And it is a real question — a
    passage rarely says "this is an emission", it says "t CO2-Äq", so the
    evidence is the wording that makes it one.
    """
    return Slot(name="parameter", kind=CHOICE, required=True,
                question=spec.parameter_question,
                options=tuple(Option(label=p.label, uri=p.uri)
                              for p in spec.parameters))


def asked_slots(parameter: Parameter) -> list:
    """The coordinates a request has to ask for: every axis the spec does not
    already decide."""
    return [slot for slot in axis_slots(parameter) if not slot.derive]


def frame_slots(spec, names) -> list:
    """The coordinates the profile says span the document's frame, in its order.

    A frame coordinate belongs to the DOCUMENT and not to the row. A plan has
    three scenario containers and a handful of reference years, and they stand
    in headings, captions and column headers -- while the carrier and the
    sector stand in the table row itself and are different in every cell. The
    first kind can be found once and then asked about; the second cannot.

    WHICH ones those are is the profile's business. The core never names a
    coordinate, so this takes a list of names and resolves it against the
    spec, exactly like `SLICE` does for the gate.

    Read off the first parameter that has all of them, because a frame is one
    per document: a spec whose parameters disagreed about it would have two
    frames and no way to say which one a value hangs in. A name no parameter
    has yields nothing at all rather than a shorter frame -- half a frame is
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


def derive_parameter(spec, claim: dict):
    """Which parameter this row belongs to, from its unit alone, or None.

    The spec says it itself: "the unit separates the two parameters". Measured
    over the kwp spec the nine energy units and the forty-two emission units
    share not one spelling, and over Kassel not one of 559 accepted tuples
    contradicted its unit. Asking anyway cost 322 of 1,043 field windows, 30.9
    percent, and 18.0 of 187.5 field minutes per plan.

    None whenever the unit does not settle it: no unit, a unit no parameter
    accepts (the row is refused later, with the unit as the reason), or a unit
    two parameters accept. Then the question is a real question and is asked.
    """
    from .verify import canonical_number
    value = claim.get("value")
    if isinstance(value, str) and canonical_number(value) is None:
        text = [p for p in spec.parameters if not p.is_numeric]
        return text[0] if len(text) == 1 else None
    unit = claim.get("unit") or claim.get("unit_raw")
    if not isinstance(unit, str) or not unit.strip():
        return None
    holders = [p for p in spec.parameters
               if p.is_numeric and p.unit_factor(unit) is not None]
    return holders[0] if len(holders) == 1 else None


def parameter_undecidable(spec, claim: dict) -> bool:
    """True when NO parameter of the spec could hold this row.

    `derive_parameter` returns None for three different situations and only
    one of them is a question: a unit two parameters accept. The other two --
    no unit at all, and a unit no parameter accepts -- are already decided
    AGAINST every answer the model could give, because `verify._check_value`
    refuses on the same `unit_factor` lookup that just failed.

    Measured on the M3 acceptance run: 69 rows reached the parameter sweep,
    45 with a unit no parameter accepts and 24 with no unit. Not one was
    ambiguous, because the kwp spec's two numeric unit lists share no
    spelling. They cost 178 of 853 field requests, 20.9 percent, and every
    one of the five answers they produced was refused afterwards anyway.
    """
    from .verify import canonical_number
    value = claim.get("value")
    if isinstance(value, str) and canonical_number(value) is None:
        # A non-numeric value needs a text parameter, and one is a decision.
        return not [p for p in spec.parameters if not p.is_numeric]
    unit = claim.get("unit") or claim.get("unit_raw")
    if not isinstance(unit, str) or not unit.strip():
        return True
    return not [p for p in spec.parameters
                if p.is_numeric and p.unit_factor(unit) is not None]


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
        if row.claim.get("quote"):
            row.claim[f"{slot.name}_quote"] = row.claim["quote"]
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
                                 getattr(parameter, "definitions", None)))


def axis_slots(parameter: Parameter) -> list:
    """Every coordinate of this parameter, in spec order, as its own question.

    A dynamic axis whose list the profile could not fill for this document has
    no options left, so it degrades to a wording — the same rule verify.py
    follows one step later.
    """
    out = []
    for name, axis in parameter.axes.items():
        if axis.vocabulary:
            slot = Slot(name=name, kind=CHOICE, required=axis.required,
                        question=axis.question,
                        options=_options(axis.vocabulary, axis.definitions),
                        derive=axis.derive, evidence=axis.evidence)
        elif axis.enum:
            slot = Slot(name=name, kind=CHOICE, required=axis.required,
                        question=axis.question, evidence=axis.evidence,
                        options=tuple(Option(label=e, uri=e) for e in axis.enum))
        elif axis.type == "int":
            slot = Slot(name=name, kind=NUMBER, required=axis.required,
                        question=axis.question, evidence=axis.evidence)
        else:
            slot = Slot(name=name, kind=TEXT, required=axis.required,
                        question=axis.question, evidence=axis.evidence)
        out.append(slot)
    return out


def slots(parameter: Parameter) -> list:
    """The full skeleton: the value slot first, then every coordinate."""
    return [value_slot(parameter)] + axis_slots(parameter)
