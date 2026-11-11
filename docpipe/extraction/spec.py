"""
spec.py: The contract between a profile's ontology knowledge and the core.

The core never reads OWL or TTL. A profile distils its ontology into this
declarative form: which parameters to extract, along which axes, with which
closed vocabularies, and one real example per parameter. Everything the
extraction stage does downstream (prompt building, verification, refusal of
out-of-vocabulary answers) leans on this file being right, so loading is
strict. `load` fails loudly here, naming the field, rather than three hours
into a batch.

The module also computes a fingerprint per question a spec asks: one sha256 per
parameter, per category answer space and per axis (`fingerprints`), plus one
for the coordinate that names which parameter a value belongs to
(`parameter_slot_fingerprint`). `runner.stale` compares a document's stamp
against these keys rather than against the whole file's hash, so an edit that
touches no question a document was asked through, such as a graph block or a
comment, costs nothing on the next run.

Three kinds of text a model is shown stand in the spec beside its parameters
(owner decision 2026-11-10; they stood in each profile's Python before): what a
document settles once for all its values (`plan_fields`), the other works a
document presents and what is asked of each (`works`), and the fixed entries of
a list the profile closes per document (`beside` of such a parameter). They
are loaded as strictly as a parameter and are in no fingerprint: a reworded
one leaves a harvest current, as a reworded prompt does.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .. import rules

# What a parameter's value IS. Numbers were the first case, not the only one:
# an ontology asks for categories (a class from a vocabulary) and for plain
# statements of fact just as often, and those are evidenced exactly like a
# number — by the passage they stand in.
NUMERIC_TYPES = ("float", "int")
VALUE_TYPES = NUMERIC_TYPES + ("text", "category")
# The step that reads a group of coordinates: the reading of each value
# (owner decision 2026-11-07); the survey that read a group per passage is
# gone (owner decisions 2026-11-08).
READ_IN = ("reading",)
# Which definition of a parameter a group's requests show (`Group`).
DEFINITIONS = ("brief", "full")
# The coordinate that names a number's entry of units_accepted.
UNIT = "unit"
# What a document can settle once for all its values, the keys of
# `plan_fields`: the settings that hold for every value, and the document's
# own base and target year (`addressed.Reader.settled`).
PLAN_FIELDS = ("settings", "base_year", "target_year")
# Those of them that are a year of the document's own, each a state of it
# that a spec can say which pairs of the frame are (`of`).
YEAR_FIELDS = ("base_year", "target_year")


def fold_label(raw) -> str:
    """One spelling for a vocabulary label, so a list need not list them all.

    NFKC and casefold, nothing else. It exists for one measured reason: a
    plan prints "CO₂-Emissionen" with U+2082 and every spec, schema and
    ontology writes "CO2-Emissionen" with the digit. Casefold alone leaves
    those two strings different, so 132 of Kassel's 204 emission readings
    were recorded as the model's own judgement call over one character, and
    a reading that answers with the document's spelling resolves to no class
    at all.

    Word order, hyphens and plurals stay distinct. Those are real differences
    between two labels, and folding them would map "CO2-Emissionen je Kopf"
    onto "CO2-Emissionen".
    """
    return unicodedata.normalize("NFKC", str(raw)).casefold()


class SpecError(ValueError):
    """A spec that must not be run with. Message names the offending field."""


def _fail(path: str, message: str) -> None:
    raise SpecError(f"{path}: {message}")


@dataclass
class Axis:
    """One dimension of a value: a closed vocabulary, an int, an enum — or a
    vocabulary that only exists per document (`dynamic`).

    Dynamic is for a coordinate whose closed list is real but not corpus-wide:
    the countries ONE publication names, for instance. The profile supplies
    that list per document and the runner fills `vocabulary` in before the
    harvest; where no profile does, the axis behaves like a text axis and the
    wording is simply carried through.
    """
    name: str
    vocabulary: Optional[dict] = None      # target URI -> corpus labels
    # target URI -> what the ontology says the term means, one sentence. The
    # field prompt has promised since the first run that the question names
    # what each entry means, and nothing did: the model was given a class
    # identifier and a list of German words and asked to decide by meaning.
    definitions: dict = field(default_factory=dict)
    # target URI -> one line in the profile's language saying what the entry
    # means, shown instead of its definition (owner decision 2026-11-05,
    # ticket 26): the ontology's English sentences were a third of every list
    # a classification request showed. Written once by the model from the
    # definition, which stays beside it to say when the line is due again.
    glosses: dict = field(default_factory=dict)
    type: Optional[str] = None             # "int" for years, "text" for wording
    enum: Optional[tuple] = None
    required: bool = False
    dynamic: bool = False
    # A free-text coordinate whose answer is the name the document gives a
    # thing, the kind of thing named here ("scenario", owner decisions
    # 2026-11-06): a value stated for several of them is one row per name, and
    # which of the document's names of that kind mean the same thing is asked
    # while it is read (`addressed.Names`).
    merged: Optional[str] = None
    # What such an axis answers instead of a name, uri -> labels like a
    # vocabulary, each an out: entry with its meaning in `definitions` (owner
    # decision 2026-11-07): "status quo" for a value of a past or the current
    # year, which belongs to no scenario, as KWP's closed list has "Bestand".
    # Read with its wording like an entry of a list, and never a name.
    beside: Optional[dict] = None
    # The one line the field request asks. It lives on the axis because the
    # harvest asks per field: a rule buried in a prompt that covers sixteen
    # fields at once is a rule the model can skip, and skipping is what cost
    # the corpus run 63.5% of its years.
    question: Optional[str] = None
    # A coordinate the SPEC already decides, so no request asks for it:
    # {"from": "unit", "value": "<a key of this axis' vocabulary>"}.
    #
    # Principle one, applied one step further. The structure of a tuple is
    # deterministic, and so is a coordinate every accepted unit of the
    # parameter fixes: measured over Kassel, all 452 aggregations the model
    # answered were `integral`, every one of them evidenced by the unit string
    # it had just been handed. Asking cost a fifth of the reply of every
    # five-field request for a coordinate the spec knew. What the unit does
    # NOT fix stays a question — the profile decides which is which.
    derive: Optional[dict] = None
    # The entry of this coordinate's list a value must have to be a value of
    # its parameter at all (owner decisions 2026-11-07): "scenario year" for
    # a year, "this publication" for an author. Asked before the coordinates
    # after it; a value read with another entry is asked for its parameter
    # once more, told it was read wrongly, is asked nothing further, and
    # stays out of the graph, as does one whose entry stays open
    # (`fields.kept`).
    keep: Optional[str] = None
    # Whether a value the plan states for several entries of this list is
    # one row per entry (owner decision 2026-11-07: "Fernwärme + Gas-NT" is
    # the value once with Fernwärme and once with Gas), as a value stated for
    # several names is (`merged`).
    several: bool = False
    # uri -> the group an entry belongs to ("group" of an entry object, owner
    # decision 2026-11-08): a list longer than a request shows with what
    # each entry means is asked group first (`flow.Numbers.list_meanings`).
    groups: dict = field(default_factory=dict)

    def label_to_uri(self) -> dict:
        """Corpus label (folded) -> URI. Built once, used per tuple."""
        out: dict = {}
        for uri, labels in (self.vocabulary or {}).items():
            for label in labels:
                out[fold_label(label)] = uri
        return out


@dataclass
class Parameter:
    uri: str
    label: str
    description: str
    value_type: str
    axes: dict                             # name -> Axis
    example: dict                          # {"source": str, "tuples": [...]}
    unit_target: Optional[str] = None      # numeric parameters only
    units_accepted: dict = field(default_factory=dict)  # unit -> factor
    # Whether this parameter's unit is an amount over a span or a rate. A
    # consumption in MWh/a is integrated over a year and a plan that states
    # one without saying over what has left something out; a power in MW is
    # not, and has no period to leave out. The verifier flags the first and
    # must not flag the second, or the flag fires on every row of one
    # parameter and means nothing.
    integrated: bool = True
    # What the spec says of each entry of units_accepted: does it name a
    # period ("MWh/a", "t per year") or is it a plain amount ("MWh")? Said by
    # the entry itself, {"factor": 1.0, "names_period": true}, and required
    # of every entry of an integrated parameter; an entry of a rate may stay
    # a bare factor. The unit question chooses the entry (a passage saying
    # "over the year" makes the model choose kWh/a), so the choice carries
    # the period, and the verifier reads this instead of a spelling. Shown to
    # no request and in no fingerprint.
    unit_names_period: dict = field(default_factory=dict)  # unit -> bool
    # The unit an entry converts onto where it is not unit_target, said by
    # the entry, {"factor": 1.0, "target": "g CO2/kWh"}: an emission factor
    # is a quotient and no mass, so it has no factor onto tonnes. A target
    # that names no ontology term keeps the value in the harvest and out of
    # the graph until the ontology has one (owner decision 2026-11-07).
    unit_targets: dict = field(default_factory=dict)  # unit -> target
    vocabulary: Optional[dict] = None      # category parameters: uri -> labels
    definitions: dict = field(default_factory=dict)
    glosses: dict = field(default_factory=dict)   # as on an axis
    # What a value of this parameter is, in one paragraph (owner decision
    # 2026-11-05, ticket 26). The requests that find values and the groups
    # that do not classify them show this; a group whose spec entry says
    # "definition": "full" shows `description`, and so does every request
    # where it is None.
    brief: Optional[str] = None
    # A category whose closed list is real but per document, filled in by the
    # profile before the harvest. Same rule as a dynamic axis, one level up.
    vocabulary_dynamic: bool = False
    # A free-text value that is the name the document gives a thing, merged
    # with the document's other names for it as on an axis.
    merged: Optional[str] = None
    # Asked once per document, with its title page and the pieces a search
    # finds best, never in every piece (owner decision 2026-11-08): a field
    # the document has once, its title, its authors, its organisation.
    once_per_document: bool = False
    # Whether a value whose scenario is the words of a group of scenarios
    # ("all scenarios") takes the members the document names, one row each
    # (owner decision 2026-11-08, i): years, regions, types do, a
    # description does not.
    takes_group: bool = True
    # uri -> the group an entry of the value's list belongs to, as on an
    # axis.
    groups: dict = field(default_factory=dict)
    # The entries a list closed per document always has beside the
    # document's own, uri -> labels like a vocabulary, each an out: entry
    # (spec: "beside", for a parameter with vocabulary_dynamic): "several
    # regions" and "other region" beside the regions one publication names,
    # so the list exists where a document names none. In no fingerprint.
    beside: Optional[dict] = None

    @property
    def is_numeric(self) -> bool:
        return self.value_type in NUMERIC_TYPES

    def unit_factor(self, unit) -> Optional[float]:
        """Factor onto unit_target for one entry of units_accepted, as listed.

        Exact and nothing else. Which entry a document's wording means is
        read by the model with its own passage (`fields.unit_slot`); a
        spelling table here would be a second reader that nothing checks.
        """
        if isinstance(unit, str):
            return self.units_accepted.get(unit)
        return None

    def target_of(self, unit) -> Optional[str]:
        """The unit one entry of units_accepted converts onto: its own
        target, else unit_target; None for no entry."""
        if self.unit_factor(unit) is None:
            return None
        return self.unit_targets.get(unit, self.unit_target)

    def names_period(self, unit) -> bool:
        """Does this entry of units_accepted name a period, as the spec says?

        Only the entry's own statement. A parameter whose entries carry none
        (a rate, or one built without `load`) has no answer to give, and
        guessing one would put a claim about a passage on a row.
        """
        if unit not in self.unit_names_period:
            raise SpecError(f"{self.uri}.units_accepted: entry {unit!r} says "
                            f"nothing about a period (names_period)")
        return self.unit_names_period[unit]

    def value_to_uri(self) -> dict:
        """Corpus label (folded) -> URI, for a category parameter."""
        out: dict = {}
        for uri, labels in (self.vocabulary or {}).items():
            for label in labels:
                out[fold_label(label)] = uri
        return out


@dataclass
class Group:
    """Coordinates a plan prints together, and the step that reads them.

    The ontology says what a value is; it does not say where a plan writes
    it. A number and its unit stand in one cell or one sentence, a scenario
    and its year in a title or a heading above a whole table. Asked one
    coordinate per request, the same passage went out once for each of them:
    245,762 field requests for 100 plans in corpus_m8_100. A group is asked
    in one request, each coordinate still answered and quoted for itself.
    """
    name: str
    coordinates: tuple
    read_in: str
    # Where a plan prints the group, in the words the prompts show.
    where: str
    # Whether its requests show a parameter's full definition rather than
    # its `brief` (spec: "definition": "full"): the group that classifies a
    # value needs every distinction the definition draws, the others only
    # what a value of the parameter is (owner decision 2026-11-05, ticket 26).
    full_definition: bool = False
    # Coordinates only the value's own passage states, such as what the
    # number counts: asked again with the passages around it, never searched
    # for in the rest of the plan (spec: "own_passage", owner decision
    # 2026-11-06).
    own_passage: tuple = ()
    # Coordinates printed with the number itself, such as "ca." or "bis zu":
    # read once with the value, its "not stated" an answer that nothing
    # qualifies the number, never asked again (spec: "own_value", owner
    # decision 2026-11-06).
    own_value: tuple = ()
    # The plan's frame (spec: "pair"): the scenario and the year, which the
    # plan's base and target years date a value by (`addressed.Plan`). The
    # reading asks them per value (owner decision 2026-11-07: each value is
    # asked its own scenario and year, none takes its passage's).
    pair: tuple = ()

    @property
    def paired(self) -> tuple:
        """The coordinates of the frame: its pair, else all of the group's
        coordinates."""
        return self.pair or self.coordinates

    def asked_near(self, slots: list) -> list:
        """The slots the second reading asks again with the passages around
        a value: all but those printed with the number itself."""
        return [slot for slot in slots if slot.name not in self.own_value]

@dataclass
class Spec:
    parameters: list
    # The one line that asks which parameter a value belongs to. The harvest
    # reads a passage once and finds the numbers in it; WHICH quantity each
    # number is, is a coordinate like any other and is asked for like any
    # other, with its own closed list and its own evidence. Reading the same
    # table once per parameter is how the plan came to be three times the
    # document.
    parameter_question: Optional[str] = None
    # The one line that asks which entry of units_accepted a number is in. A
    # coordinate like the parameter, asked before it and with the lists of
    # every numeric parameter, because the entry is what settles the
    # parameter. Only a spec with a numeric parameter has a use for it.
    unit_question: Optional[str] = None
    # name -> Group; empty for a spec read the old way only.
    groups: dict = field(default_factory=dict)
    by_uri: dict = field(default_factory=dict)
    # What a document settles once for all its values, each asked once in
    # the form of a document's field (spec: "plan_fields", owner decision
    # 2026-11-08): key of `PLAN_FIELDS` -> {"name", "means", "sentence"}. The
    # settings' lines stand beside every value's coordinates, the years are
    # the document's own base and target years. A year may say which pairs
    # of the document's frame are that state of it (`of`, coordinate -> the
    # key of an entry of its list: {"scenario": "status_quo"}, owner decision
    # 2026-11-10): a pass over a stored harvest, which asks no document its
    # years, takes them from the stored pairs by it
    # (`pipeline.state_years`); a run that reads a document asks them and
    # does not read it. Empty where a spec asks none. In no fingerprint.
    plan_fields: dict = field(default_factory=dict)
    # The works a document presents, compares, reviews or cites beside
    # itself (spec: "works", owner decision 2026-11-08, h): {"name", "means",
    # "fields": {parameter uri: the question asked at a new work's line}}.
    # None where a spec keeps no list of works. In no fingerprint.
    works: Optional[dict] = None

    def __post_init__(self) -> None:
        self.by_uri = {p.uri: p for p in self.parameters}

    def groups_read_in(self, step: str) -> list:
        return [group for group in self.groups.values()
                if group.read_in == step]


def _vocabulary(path: str, raw):
    """(uri -> spellings, uri -> definition, uri -> gloss) from either spec
    form.

    A list is the short form and still the common one: the entry is its
    spellings and the first is what the model is offered. An object adds the
    one thing the list could not carry -- what the term MEANS, in the
    ontology's own words -- without moving the spellings anywhere else, and
    may add that meaning in one line of the profile's language ("gloss"),
    which a request shows instead.
    """
    if raw is None:
        return None, {}, {}
    if not isinstance(raw, dict) or not raw:
        _fail(path, "vocabulary must be a non-empty object of uri -> labels")
    spellings, definitions, glosses = {}, {}, {}
    for uri, entry in raw.items():
        if isinstance(entry, dict):
            label = entry.get("label")
            rest = entry.get("spellings") or []
            if not isinstance(label, str) or not label.strip():
                _fail(f"{path}.{uri}", "an entry object needs a label")
            if not isinstance(rest, list):
                _fail(f"{path}.{uri}", "spellings must be a list")
            spellings[uri] = [label] + list(rest)
            meaning = entry.get("definition")
            if meaning is not None:
                if not isinstance(meaning, str) or not meaning.strip():
                    _fail(f"{path}.{uri}", "definition must be a sentence")
                definitions[uri] = meaning.strip()
            gloss = entry.get("gloss")
            if gloss is not None:
                if not isinstance(gloss, str) or not gloss.strip():
                    _fail(f"{path}.{uri}", "gloss must be a sentence")
                if meaning is None:
                    _fail(f"{path}.{uri}", "a gloss says a definition in "
                                           "short, so it needs one")
                glosses[uri] = gloss.strip()
        else:
            spellings[uri] = entry
    return spellings, definitions, glosses


def _entry_groups(path: str, raw) -> dict:
    """uri -> the group of an entry, from entry objects that name one
    ("group"); {} where none does."""
    groups: dict = {}
    for uri, entry in (raw or {}).items() if isinstance(raw, dict) else ():
        if not isinstance(entry, dict) or entry.get("group") is None:
            continue
        group = entry["group"]
        if not isinstance(group, str) or not group.strip():
            _fail(f"{path}.{uri}.group", "a group is a non-empty string")
        groups[uri] = group.strip()
    return groups


def _validate_axis(path: str, name: str, raw) -> Axis:
    if not isinstance(raw, dict):
        _fail(path, "axis must be an object")
    vocabulary, definitions, glosses = _vocabulary(path, raw.get("vocabulary"))
    axis_type = raw.get("type")
    enum = raw.get("enum")
    dynamic = bool(raw.get("dynamic", False))
    _refuse_kg(path, raw)
    if "evidence" in raw:
        # Refused rather than ignored, so the rule cannot come back through a
        # profile without anyone deciding it again.
        _fail(path, "evidence is not a key of an axis: a coordinate is "
                    "checked for its quote and its answer, wherever the "
                    "passage stands")
    derive = raw.get("derive")
    if derive is not None:
        if not isinstance(derive, dict):
            _fail(path, "derive must be an object")
        if derive.get("from") != "unit":
            _fail(path, "derive.from must be 'unit' (nothing else derives yet)")
        if not isinstance(vocabulary, dict) or derive.get("value") not in vocabulary:
            _fail(path, f"derive.value {derive.get('value')!r} is not a key of "
                        f"this axis' vocabulary")
        extra = set(derive) - {"from", "value"}
        if extra:
            _fail(path, f"derive has no key {sorted(extra)}")
    kinds = sum(x is not None for x in (vocabulary, axis_type, enum)) + int(dynamic)
    if kinds != 1:
        _fail(path, "an axis is exactly one of: vocabulary, type, enum, dynamic")
    if vocabulary is not None:
        if not isinstance(vocabulary, dict) or not vocabulary:
            _fail(path, "vocabulary must be a non-empty object of uri -> labels")
        seen: dict = {}
        for uri, labels in vocabulary.items():
            if not isinstance(labels, list) or not labels or \
                    not all(isinstance(l, str) and l.strip() for l in labels):
                _fail(f"{path}.{uri}", "labels must be a non-empty list of strings")
            for label in labels:
                other = seen.get(fold_label(label))
                if other and other != uri:
                    # One label mapping to two URIs would make every match a
                    # coin toss; better to refuse the spec than to guess later.
                    # Folded, because "CO₂-Emissionen" under one class and
                    # "CO2-Emissionen" under another IS that coin toss.
                    _fail(f"{path}.{uri}", f"label {label!r} already maps to {other}")
                seen[fold_label(label)] = uri
    # "text" is a coordinate the document names in its own words, such as
    # the scenarios of ONE publication, which differ per document. The
    # wording is carried through; here it is just a string.
    if axis_type is not None and axis_type not in ("int", "text"):
        _fail(path, f"unsupported axis type {axis_type!r}")
    if enum is not None:
        if not isinstance(enum, list) or not all(isinstance(e, str) for e in enum):
            _fail(path, "enum must be a list of strings")
        enum = tuple(enum)
    question = raw.get("question")
    if question is not None and (not isinstance(question, str) or
                                 not question.strip()):
        _fail(path, "question must be a non-empty string when given")
    merged = raw.get("merged")
    if merged is not None and (not isinstance(merged, str)
                               or not merged.strip()):
        _fail(path, "merged names the kind of thing, a non-empty string")
    if merged and (axis_type != "text" or vocabulary or enum or dynamic):
        _fail(path, "merged is for a free-text axis only")
    keep = raw.get("keep")
    if keep is not None and (not isinstance(vocabulary, dict)
                             or keep not in vocabulary):
        _fail(f"{path}.keep", f"{keep!r} is not a key of this axis' "
                              f"vocabulary")
    several = raw.get("several", False)
    if not isinstance(several, bool):
        _fail(f"{path}.several", "true or false")
    if several and not isinstance(vocabulary, dict):
        _fail(f"{path}.several", "several entries are for an axis with a "
                                 "vocabulary")
    beside, beside_definitions, beside_glosses = _vocabulary(
        f"{path}.beside", raw.get("beside"))
    if beside is not None:
        if not merged:
            _fail(f"{path}.beside", "entries beside the names are for an axis "
                                    "of names only (merged)")
        _validate_out_entries(f"{path}.beside", beside)
        definitions = {**definitions, **beside_definitions}
        glosses = {**glosses, **beside_glosses}
    return Axis(name=name, vocabulary=vocabulary, type=axis_type,
                enum=enum, required=bool(raw.get("required", False)),
                dynamic=dynamic, merged=merged, beside=beside,
                question=question, derive=derive,
                definitions=definitions, glosses=glosses, keep=keep,
                several=several,
                groups=_entry_groups(f"{path}.vocabulary",
                                     raw.get("vocabulary")))


def _validate_out_entries(path: str, entries: dict) -> None:
    """Entries offered beside a list of names or a document's own list: each
    an out: entry with its labels.

    The out: convention: nothing that turns an answer into a node or a name
    takes one (`graphkit.NOT_IN_GRAPH`).
    """
    for uri, labels in entries.items():
        if not str(uri).startswith("out:"):
            _fail(f"{path}.{uri}", "an entry beside a list is an out: "
                                   "entry, it names nothing")
        if not isinstance(labels, list) or not labels or \
                not all(isinstance(l, str) and l.strip() for l in labels):
            _fail(f"{path}.{uri}",
                  "labels must be a non-empty list of strings")


def _validate_example(path: str, raw, value_type: str,
                      units_accepted: dict) -> dict:
    if not isinstance(raw, dict):
        _fail(path, "example is required: a real corpus snippet plus the "
                    "tuples it must yield (it becomes the prompt's few-shot "
                    "and the runner's golden test)")
    source = raw.get("source")
    least = rules.get("example_least_words")
    if not isinstance(source, str) or len(source.split()) < least:
        _fail(f"{path}.source", f"must be a real snippet, not a placeholder "
                                f"(under {least} words)")
    tuples = raw.get("tuples")
    if not isinstance(tuples, list) or not tuples:
        _fail(f"{path}.tuples", "must be a non-empty list")
    defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    numeric = value_type in NUMERIC_TYPES
    for i, t in enumerate(tuples):
        if not isinstance(t, dict):
            _fail(f"{path}.tuples[{i}]", "each tuple must be an object")
        value = t.get("value")
        if numeric:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                _fail(f"{path}.tuples[{i}]", "each tuple needs a numeric 'value'")
        elif not isinstance(value, str) or not value.strip():
            _fail(f"{path}.tuples[{i}]",
                  f"a {value_type} parameter needs a non-empty string 'value'")
        # The entry, not the wording: `unit_raw` is how the snippet writes
        # the unit and may be anything, `unit` is the choice the example
        # shows the model making and the verifier holds to the list.
        unit = t.get("unit", defaults.get("unit"))
        if numeric and unit is not None and unit not in units_accepted:
            _fail(f"{path}.tuples[{i}].unit",
                  f"{unit!r} is not in units_accepted")
    return raw


def _validate_unit_entry(path: str, raw, integrated: bool) -> tuple:
    """(factor, names_period or None, target or None) of one entry of
    units_accepted.

    A bare factor is the short form and says nothing about a period. An
    integrated parameter has to say it for every entry: the verifier flags a
    plain amount from this statement and from nothing else, so an entry that
    left it out would be read as a plain amount by silence.
    """
    statement = target = None
    if isinstance(raw, dict):
        factor = raw.get("factor")
        statement = raw.get("names_period")
        target = raw.get("target")
        if target is not None and (not isinstance(target, str)
                                   or not target.strip()):
            _fail(f"{path}.target",
                  "the unit the factor converts onto where it is not "
                  "unit_target, a non-empty string")
        if statement is not None and not isinstance(statement, bool):
            _fail(f"{path}.names_period",
                  "true when the entry names a period (\"MWh/a\"), false "
                  "when it is a plain amount (\"MWh\")")
    else:
        factor = raw
    if not isinstance(factor, (int, float)) or factor <= 0:
        _fail(f"{path}.factor" if isinstance(raw, dict) else path,
              "a positive factor onto unit_target")
    if integrated and statement is None:
        _fail(f"{path}.names_period",
              "required for a unit of an integrated parameter: true when the "
              "entry names a period (\"MWh/a\"), false when it is a plain "
              "amount (\"MWh\")")
    return factor, statement, target


def _validate_parameter(path: str, raw) -> Parameter:
    if not isinstance(raw, dict):
        _fail(path, "parameter must be an object")
    for key in ("uri", "label", "description"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            _fail(f"{path}.{key}", "required, non-empty string")
    least = rules.get("description_least_words")
    if len(raw["description"].split()) < least:
        # The description IS the prompt's definition of the parameter. A stub
        # here means the model extracts on vibes.
        _fail(f"{path}.description", f"too short to define the parameter "
                                     f"for the model (under {least} words)")
    value_type = raw.get("value_type", "float")
    if value_type not in VALUE_TYPES:
        _fail(f"{path}.value_type", f"must be one of {VALUE_TYPES}")

    # A unit belongs to a measured quantity, a vocabulary to a category.
    # Demanding either from the other kind was what kept this contract
    # numbers-only.
    units: dict = {}
    unit_names_period: dict = {}
    unit_targets: dict = {}
    unit_target = raw.get("unit_target")
    vocabulary, value_definitions, value_glosses = _vocabulary(
        f"{path}.vocabulary", raw.get("vocabulary"))
    vocabulary_dynamic = bool(raw.get("vocabulary_dynamic", False))
    merged = raw.get("merged")
    if merged is not None and (not isinstance(merged, str)
                               or not merged.strip()):
        _fail(f"{path}.merged", "names the kind of thing, a non-empty string")
    if merged and (value_type != "text" or vocabulary or vocabulary_dynamic):
        _fail(f"{path}.merged", "for a free-text value only")
    brief = raw.get("brief")
    if brief is not None and (not isinstance(brief, str)
                              or not brief.strip()):
        _fail(f"{path}.brief", "a non-empty string when given")
    beside, beside_definitions, beside_glosses = _vocabulary(
        f"{path}.beside", raw.get("beside"))
    if beside is not None:
        if not vocabulary_dynamic:
            _fail(f"{path}.beside", "entries beside a document's own list "
                                    "are for a list the profile closes per "
                                    "document (vocabulary_dynamic)")
        _validate_out_entries(f"{path}.beside", beside)
        value_definitions = {**value_definitions, **beside_definitions}
        value_glosses = {**value_glosses, **beside_glosses}
    if value_type in NUMERIC_TYPES:
        if not isinstance(unit_target, str) or not unit_target.strip():
            _fail(f"{path}.unit_target",
                  "required for a numeric parameter, non-empty string")
        listed = raw.get("units_accepted")
        if not isinstance(listed, dict) or not listed:
            _fail(f"{path}.units_accepted",
                  "non-empty object of unit string -> positive factor, or "
                  "{factor, names_period}")
        if not isinstance(raw.get("integrated", True), bool):
            _fail(f"{path}.integrated",
                  "true when the unit is an amount over a span, false when "
                  "it is a rate")
        for unit, entry in listed.items():
            units[unit], period, target = _validate_unit_entry(
                f"{path}.units_accepted.{unit}", entry,
                bool(raw.get("integrated", True)))
            if period is not None:
                unit_names_period[unit] = period
            if target is not None and target != unit_target:
                unit_targets[unit] = target
    else:
        if "integrated" in raw:
            _fail(f"{path}.integrated",
                  f"a {value_type} parameter carries no integration period")
        if unit_target is not None or raw.get("units_accepted") is not None:
            _fail(f"{path}.unit_target",
                  f"a {value_type} parameter carries no unit")
        if value_type == "category":
            if vocabulary_dynamic:
                if vocabulary is not None:
                    _fail(f"{path}.vocabulary",
                          "a dynamic category carries no vocabulary in the spec")
            elif not isinstance(vocabulary, dict) or not vocabulary:
                _fail(f"{path}.vocabulary",
                      "a category parameter needs a vocabulary of uri -> labels, "
                      "or vocabulary_dynamic for a list the profile supplies "
                      "per document")
            seen: dict = {}
            for uri, labels in (vocabulary or {}).items():
                if not isinstance(labels, list) or not labels or \
                        not all(isinstance(l, str) and l.strip() for l in labels):
                    _fail(f"{path}.vocabulary.{uri}",
                          "labels must be a non-empty list of strings")
                for label in labels:
                    other = seen.get(fold_label(label))
                    if other and other != uri:
                        _fail(f"{path}.vocabulary.{uri}",
                              f"label {label!r} already maps to {other}")
                    seen[fold_label(label)] = uri
        elif vocabulary is not None or vocabulary_dynamic:
            _fail(f"{path}.vocabulary",
                  "only a category parameter carries a value vocabulary")

    # Axes are what a measured value varies along — carrier, sector, year.
    # A document's title varies along nothing, and demanding an axis from it
    # would mean inventing one. Empty is allowed; a wrong shape is not.
    axes_raw = raw.get("axes") or {}
    if not isinstance(axes_raw, dict):
        _fail(f"{path}.axes", "must be an object of axis name -> definition")
    axes = {name: _validate_axis(f"{path}.axes.{name}", name, a)
            for name, a in axes_raw.items()}
    for name, axis in axes.items():
        unless = (axis.derive or {}).get("unless_read")
        if unless is not None and unless not in axes:
            _fail(f"{path}.axes.{name}.derive",
                  f"unless_read {unless!r} is not an axis of this parameter")
    example = _validate_example(f"{path}.example", raw.get("example"),
                                value_type, units)
    for key in ("once_per_document", "takes_group"):
        if key in raw and not isinstance(raw[key], bool):
            _fail(f"{path}.{key}", "true or false")
    _refuse_kg(path, raw)
    return Parameter(uri=raw["uri"], label=raw["label"],
                     description=raw["description"], value_type=value_type,
                     unit_target=unit_target, units_accepted=units,
                     integrated=bool(raw.get("integrated", True)),
                     unit_names_period=unit_names_period,
                     unit_targets=unit_targets,
                     vocabulary=vocabulary, definitions=value_definitions,
                     glosses=value_glosses,
                     brief=brief.strip() if brief else None,
                     vocabulary_dynamic=vocabulary_dynamic,
                     merged=merged,
                     axes=axes, example=example,
                     once_per_document=bool(raw.get("once_per_document",
                                                    False)),
                     takes_group=bool(raw.get(
                         "takes_group", rules.get("default_takes_group"))),
                     groups=_entry_groups(f"{path}.vocabulary",
                                          raw.get("vocabulary")),
                     beside=beside)


def load(source: Union[Path, str, dict]) -> Spec:
    """Parse and validate a spec from a JSON file or an already-parsed dict."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            _fail(str(path), "spec file not found")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            _fail(str(path), f"not valid JSON: {e}")
    else:
        data = source
    if not isinstance(data, dict):
        _fail("spec", "top level must be an object")
    raw_parameters = data.get("parameters")
    if not isinstance(raw_parameters, list) or not raw_parameters:
        _fail("spec.parameters", "required, non-empty list")
    parameters = [_validate_parameter(f"spec.parameters[{i}]", p)
                  for i, p in enumerate(raw_parameters)]
    uris = [p.uri for p in parameters]
    if len(set(uris)) != len(uris):
        _fail("spec.parameters", "duplicate parameter uri")
    question = data.get("parameter_question")
    if question is not None and not (isinstance(question, str)
                                     and question.strip()):
        _fail("spec.parameter_question", "must be a non-empty string")
    unit_question = data.get("unit_question")
    if unit_question is not None and not (isinstance(unit_question, str)
                                          and unit_question.strip()):
        _fail("spec.unit_question", "must be a non-empty string")
    groups = _validate_groups(data.get("groups"), parameters,
                              bool(unit_question))
    return Spec(parameters=parameters,
                parameter_question=(question or None),
                unit_question=(unit_question or None), groups=groups,
                plan_fields=_validate_plan_fields(data.get("plan_fields"),
                                                  parameters, groups),
                works=_validate_works(data.get("works"), parameters))


def _validate_text(path: str, raw: dict, key: str, required: bool) -> None:
    value = raw.get(key)
    if value is None and not required:
        return
    if not isinstance(value, str) or not value.strip():
        _fail(f"{path}.{key}", "required, non-empty string" if required
              else "a non-empty string when given")


def _validate_of(path: str, raw, parameters: list, groups: dict) -> None:
    """`of` of a document's base or target year: coordinate -> the key of
    an entry of its list, what a pair of the document's frame reads on its
    other coordinates to be that state of it (`pipeline.state_years`).

    A coordinate outside every group's pair or an entry its list does not
    hold would match no pair, and the state would silently have no years;
    so it is refused here.
    """
    where = f"{path}.of"
    if not isinstance(raw, dict) or not raw:
        _fail(where, "a non-empty object of coordinate -> the key of an "
                     "entry of its list when given")
    paired = sorted({name for group in groups.values()
                     for name in group.pair})
    for name, entry in raw.items():
        if name not in paired:
            _fail(f"{where}.{name}", f"is no coordinate of a group's pair; "
                                     f"one of {paired}")
        lists = [parameter.axes[name].vocabulary for parameter in parameters
                 if name in parameter.axes
                 and parameter.axes[name].vocabulary]
        if not lists:
            _fail(f"{where}.{name}", "has no list in any parameter")
        if not isinstance(entry, str) or any(entry not in keys
                                             for keys in lists):
            _fail(f"{where}.{name}", f"{entry!r} is not a key of its list "
                                     f"in every parameter that carries it")


def _validate_plan_fields(raw, parameters=(), groups=None) -> dict:
    """key -> {"name", "means", "sentence"} of what a document settles once,
    and for a year of its own which pairs of its frame are that state of it
    (`of`).

    A key no step asks is refused rather than carried: it would be a text
    somebody wrote for the model that no request ever shows.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        _fail("spec.plan_fields", "a non-empty object of key -> field when "
                                  "given")
    out: dict = {}
    for key, entry in raw.items():
        path = f"spec.plan_fields.{key}"
        if key not in PLAN_FIELDS:
            _fail(path, f"no step asks it; one of {PLAN_FIELDS}")
        if not isinstance(entry, dict):
            _fail(path, "must be an object")
        known = {"name", "means", "sentence"}
        if key in YEAR_FIELDS:
            known.add("of")
        extra = sorted(set(entry) - known)
        if extra:
            _fail(path, f"has no key {extra}")
        _validate_text(path, entry, "name", True)
        _validate_text(path, entry, "means", True)
        _validate_text(path, entry, "sentence", False)
        if "of" in entry:
            _validate_of(path, entry["of"], list(parameters), groups or {})
        out[key] = dict(entry)
    return out


def _validate_works(raw, parameters: list) -> Optional[dict]:
    """{"name", "means", "fields"} of the works a document presents beside
    itself, None where the spec keeps no such list.

    A question keyed by a uri the spec does not have would be asked of
    nothing, so it is refused here.
    """
    if raw is None:
        return None
    path = "spec.works"
    if not isinstance(raw, dict):
        _fail(path, "must be an object")
    extra = sorted(set(raw) - {"name", "means", "fields"})
    if extra:
        _fail(path, f"has no key {extra}")
    _validate_text(path, raw, "name", True)
    _validate_text(path, raw, "means", True)
    fields = raw.get("fields", {})
    if not isinstance(fields, dict):
        _fail(f"{path}.fields", "an object of parameter uri -> the question "
                                "asked at a work's line")
    known = {parameter.uri for parameter in parameters}
    for uri, question in fields.items():
        if uri not in known:
            _fail(f"{path}.fields.{uri}", "is no parameter of the spec")
        if not isinstance(question, str) or not question.strip():
            _fail(f"{path}.fields.{uri}", "a non-empty question")
    return {**raw, "fields": dict(fields)} if "fields" in raw else dict(raw)


def _validate_groups(raw, parameters: list, asks_unit: bool) -> dict:
    """name -> Group, each coordinate of the spec in exactly one of them.

    A coordinate in no group would be read by no step, and one in two would
    be read twice with two answers to choose from.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        _fail("spec.groups", "must be a non-empty object of name -> group")
    known = {name for parameter in parameters for name in parameter.axes}
    if asks_unit and any(parameter.is_numeric for parameter in parameters):
        known.add(UNIT)
    groups: dict = {}
    owner: dict = {}
    for name, entry in raw.items():
        path = f"spec.groups.{name}"
        if not isinstance(entry, dict):
            _fail(path, "must be an object")
        coordinates = entry.get("coordinates")
        if (not isinstance(coordinates, list) or not coordinates
                or not all(isinstance(c, str) and c.strip()
                           for c in coordinates)):
            _fail(f"{path}.coordinates", "non-empty list of coordinate names")
        for coordinate in coordinates:
            if coordinate not in known:
                _fail(f"{path}.coordinates",
                      f"{coordinate!r} is no coordinate of the spec")
            if coordinate in owner:
                _fail(f"{path}.coordinates",
                      f"{coordinate!r} is already in group {owner[coordinate]!r}")
            owner[coordinate] = name
        read_in = entry.get("read_in")
        if read_in not in READ_IN:
            _fail(f"{path}.read_in", f"must be one of {READ_IN}")
        where = entry.get("where")
        if not isinstance(where, str) or not where.strip():
            _fail(f"{path}.where", "required, non-empty string")
        definition = entry.get("definition", "brief")
        if definition not in DEFINITIONS:
            _fail(f"{path}.definition", f"must be one of {DEFINITIONS}")
        own = {}
        for key in ("own_passage", "own_value"):
            listed = entry.get(key, [])
            if not isinstance(listed, list) or any(
                    c not in coordinates for c in listed):
                _fail(f"{path}.{key}", "a list of the group's coordinates")
            own[key] = tuple(listed)
        if set(own["own_passage"]) & set(own["own_value"]):
            _fail(f"{path}.own_value", "a coordinate is in own_passage or "
                                       "own_value, not both")
        pair = entry.get("pair", [])
        if not isinstance(pair, list) or any(c not in coordinates
                                             for c in pair):
            _fail(f"{path}.pair", "a list of the group's coordinates")
        groups[name] = Group(name, tuple(coordinates), read_in, where.strip(),
                             full_definition=definition == "full",
                             pair=tuple(pair), **own)
    missing = sorted(known - set(owner))
    if missing:
        _fail("spec.groups", f"in no group: {', '.join(missing)}")
    return groups


def _digest(parts) -> str:
    """A stable sha256 over whatever decides a question and its answer space.

    Stable across runs and across machines: the parts go through JSON with
    sorted keys, so a dict that was built in another order still hashes the
    same. A fingerprint that moves on its own would mark every document stale
    once and teach everyone to ignore it.
    """
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def axis_fingerprint(axis: "Axis") -> str:
    """What this coordinate asks and what it may answer.

    Everything the model sees for this axis, and nothing else: a changed
    comment, a reordered vocabulary or a new parameter elsewhere in the spec
    must not make a document stale for this axis. Options are sorted for the
    same reason -- the list is a set, and the order it happens to be written
    in is not part of the question.
    """
    vocabulary = axis.vocabulary or {}
    return _digest({
        "name": axis.name,
        "question": axis.question,
        "type": axis.type,
        "enum": sorted(axis.enum) if axis.enum else None,
        "required": axis.required,
        "dynamic": axis.dynamic,
        # Only where set, so no other coordinate's key moves.
        **({"merged": axis.merged} if axis.merged else {}),
        **({"beside": {uri: {"spellings": sorted(map(str, labels or [])),
                             "definition": (axis.definitions or {}).get(uri),
                             "gloss": (axis.glosses or {}).get(uri)}
                       for uri, labels in axis.beside.items()}}
           if axis.beside else {}),
        "derive": axis.derive,
        **({"keep": axis.keep} if axis.keep else {}),
        **({"groups": axis.groups} if axis.groups else {}),
        # The offered list: identifier, the spellings a plan may use, and the
        # sentence saying what the term means. All three reach the model, so
        # all three decide whether an answer is still the answer to this
        # question.
        "options": {uri: {"spellings": sorted(map(str, labels or [])),
                          "definition": (axis.definitions or {}).get(uri),
                          "gloss": (axis.glosses or {}).get(uri)}
                    for uri, labels in vocabulary.items()},
    })


def parameter_fingerprint(parameter: "Parameter") -> str:
    """What this parameter asks, WITHOUT its axes and without its own list.

    Without, because that is the whole point: a new energy carrier must open
    the carrier coordinate of the rows that could carry it, not every value
    of the parameter. The axes have fingerprints of their own, and so does
    the list a category parameter answers from -- an answer space that can
    be re-mapped from the wording is a different kind of change from a
    rewritten question, and a stamp that cannot tell them apart cannot say
    which one a run has to redo.
    """
    return _digest({
        "uri": parameter.uri,
        "label": parameter.label,
        "description": parameter.description,
        "brief": parameter.brief,
        "value_type": parameter.value_type,
        "unit_target": parameter.unit_target,
        "units": sorted(parameter.units_accepted or {}),
        "example": parameter.example,
        # Only where set, so no other field's key moves.
        **({"once_per_document": True}
           if parameter.once_per_document else {}),
        **({"takes_group": False} if not parameter.takes_group else {}),
    })


def value_fingerprint(parameter: "Parameter") -> str:
    """The list a category parameter answers from, or "" when it has none.

    The classes and their spellings, which is all the rows request shows the
    model for this list (`runner._parameter_payload` and
    `_quantities_payload`: the class name and the other spellings). The
    definitions are not in it: no request of the harvest puts them in front of
    the model for a category value, so counting them made a document stale
    over a sentence no model had read. An axis is another case, its field
    request does show them, and `axis_fingerprint` keeps them.

    A stamp written while the definitions were counted holds another digest,
    so a stored scenarios stamp reports its `value/<parameter>` keys stale
    once. `--remap` (no model) settles them; `--force-stale` first would read
    the document again for nothing. A document with a wording no list holds
    stays stale in that key (`not listed` in the remap's count) and is the
    one `--force-stale` is left for.
    """
    if not parameter.vocabulary and not parameter.vocabulary_dynamic:
        return ""
    # Without `beside`: the fixed entries of a list closed per document were
    # in no key while the profile's code held them, and stay in none.
    return _digest({
        "dynamic": parameter.vocabulary_dynamic,
        "options": {uri: {"spellings": sorted(map(str, labels or []))}
                    for uri, labels in (parameter.vocabulary or {}).items()},
        **({"groups": parameter.groups} if parameter.groups else {}),
    })


def parameter_slot_fingerprint(spec: "Spec") -> str:
    """The one coordinate that belongs to no parameter: which quantity a
    number is.

    It is asked like every other coordinate (`fields.parameter_slot`), with
    its own question and its own closed list, and that list is the parameters
    themselves. So it needs its own key.

    It also moves when a parameter is REMOVED, which no per-parameter key
    can: every key here is written from what the spec still has. That is not
    the general answer to a removal, though, and reading it as one is how a
    dropped AXIS came to move nothing at all. `runner.stale` reports a
    question key the stored stamp carries and the run no longer asks, which
    covers every kind; this key earns its place for the question and for the
    list the model chooses from.

    The uri and the label, because both reach the model. The description does
    not -- it is in `parameter/<uri>` instead, where the question that uses it
    is.
    """
    return _digest({
        "question": spec.parameter_question,
        "options": sorted([p.uri, p.label] for p in spec.parameters),
    })


def unit_slot_fingerprint(spec: "Spec") -> str:
    """The unit question and the entries it is answered from, "" without any.

    Its own key, like "slot/parameter": the unit is asked once, before the
    parameter, against every numeric parameter's list at once, so no
    per-parameter key says that this question moved. A harvest stamped before
    the question existed has no such key at all, which is what makes it stale
    in exactly this coordinate and in no other -- the top-up re-reads the
    unit of every row and leaves the rest of the document as it was.
    """
    units = sorted((p.uri, unit) for p in spec.parameters
                   if p.is_numeric for unit in p.units_accepted)
    if not units:
        return ""
    return _digest({"question": spec.unit_question, "options": units})


def fingerprints(spec: "Spec") -> dict:
    """{key: sha} for every question of a spec: parameter, answer space, axis.

    Flat, and the keys read as what they are: the stamp is compared key by
    key, and "parameter/<uri>" or "axis/<uri>/<name>" is what a run should be
    able to say changed. One nested block would only ever report that
    something inside it moved.

    Together they have to cover everything a document is asked through, or
    `runner.stale` -- which ignores the whole-file sha once these are present
    -- would call a document current over a changed question. That is what
    "slot/parameter" is doing here: without it the spec's own question and
    the list it offers would be in no key at all.
    """
    out = {"slot/parameter": parameter_slot_fingerprint(spec)}
    unit = unit_slot_fingerprint(spec)
    if unit:
        out["slot/unit"] = unit
    for parameter in spec.parameters:
        out[f"parameter/{parameter.uri}"] = parameter_fingerprint(parameter)
        value = value_fingerprint(parameter)
        if value:
            out[f"value/{parameter.uri}"] = value
        for name, axis in (parameter.axes or {}).items():
            out[f"axis/{parameter.uri}/{name}"] = axis_fingerprint(axis)
    return out


def _refuse_kg(path: str, raw: dict) -> None:
    """What a field or a coordinate becomes in the graph is drawn in the
    profile's graph file, not said in the spec: a `kg` block here is refused
    rather than carried, so nobody keeps editing a description the writers no
    longer read."""
    if "kg" in raw:
        _fail(f"{path}.kg", "a spec no longer says what a field becomes in "
                            "the graph: the graph is drawn in graph.json "
                            "(`map`, the Graph tab of `docpipe edit`)")
