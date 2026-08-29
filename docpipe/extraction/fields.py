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


@dataclass(frozen=True)
class Option:
    """One entry of a closed list, as the model sees it and as it comes back."""
    label: str                  # what the model answers
    uri: str                    # what the label resolves to
    synonyms: tuple = ()        # the other spellings the spec knows


@dataclass(frozen=True)
class Slot:
    """One field of one parameter: a single question with a single answer."""
    name: str
    kind: str
    required: bool = False
    question: Optional[str] = None
    options: tuple = ()

    @property
    def is_closed(self) -> bool:
        return self.kind == CHOICE and bool(self.options)


def _options(vocabulary: dict) -> tuple:
    """The closed list as options — first label canonical, rest synonyms.

    The spec writes a vocabulary as uri -> [labels] and the first label is the
    one the class is called by; the others exist so a document's own spelling
    still resolves. Only the canonical one is offered, or the list the model
    reads would be four times as long for no added choice.
    """
    out = []
    for uri, labels in (vocabulary or {}).items():
        labels = [l for l in labels if isinstance(l, str) and l.strip()]
        if not labels:
            continue
        out.append(Option(label=labels[0], uri=uri, synonyms=tuple(labels[1:])))
    return tuple(out)


def value_slot(parameter: Parameter) -> Slot:
    """The row maker: the one request that decides how many values there are."""
    if parameter.is_numeric:
        return Slot(name="value", kind=VALUE, required=True,
                    question=parameter.description)
    return Slot(name="value", kind=VALUE, required=True,
                question=parameter.description,
                options=_options(parameter.vocabulary))


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
                        question=axis.question, options=_options(axis.vocabulary))
        elif axis.enum:
            slot = Slot(name=name, kind=CHOICE, required=axis.required,
                        question=axis.question,
                        options=tuple(Option(label=e, uri=e) for e in axis.enum))
        elif axis.type == "int":
            slot = Slot(name=name, kind=NUMBER, required=axis.required,
                        question=axis.question)
        else:
            slot = Slot(name=name, kind=TEXT, required=axis.required,
                        question=axis.question)
        out.append(slot)
    return out


def slots(parameter: Parameter) -> list:
    """The full skeleton: the value slot first, then every coordinate."""
    return [value_slot(parameter)] + axis_slots(parameter)
