"""
spec.py – The contract between a profile's ontology knowledge and the core.

The core never reads OWL or TTL. A profile distils its ontology into this
declarative form: which parameters to extract, along which axes, with which
closed vocabularies — and one real example per parameter. Everything the
extraction stage does downstream (prompt building, verification, refusal of
out-of-vocabulary answers) leans on this file being right, so loading is
strict: a spec that is wrong fails loudly here, naming the field, not three
hours into a batch.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

# What a parameter's value IS. Numbers were the first case, not the only one:
# an ontology asks for categories (a class from a vocabulary) and for plain
# statements of fact just as often, and those are evidenced exactly like a
# number — by the passage they stand in.
NUMERIC_TYPES = ("float", "int")
VALUE_TYPES = NUMERIC_TYPES + ("text", "category")
SCENARIOS = ("status_quo", "trend", "target", "unknown")


# One unit, written the way a German planning document happens to write it.
# The lists in a spec name the unit; these three patterns absorb the spelling.
# Measured on the 16-document pilot: 661 findings were refused for their unit,
# and 302 of them carried a unit the spec already accepts under another
# spelling — a subscript two, "pro Jahr" instead of "/a", "Äquivalent" instead
# of "eq". Enumerating spellings does not converge; this does.
_EQUIVALENT = re.compile(r"(?:ä|ae)q(?:uivalent(?:e|en)?|u?i?)\.?"
                         r"|(?<=co2)\s*[-_ ]?\s*eq", re.I)
_PER_YEAR = re.compile(r"pro\s*jahr|/\s*jahr|jährlich|jaehrlich|im\s*jahr"
                       r"|p\.?\s?a\.?$", re.I)
# Punctuation that only ever separates: spaces, dots in "Mio.", the hyphen in
# "CO2-Äq", the underscore in "t_CO2_äq", brackets, and every dash the corpus
# uses. A slash is NOT here: "t CO2/a" and "t CO2/Kopf" are different things.
_SEPARATORS = re.compile(r"[\s.\-_()\[\]‐-―]+")
# The canonical per-year suffix itself: "MWh/a", "t / a". Not "/ab".
_PER_A = re.compile(r"/\s*a(?![a-zäöüß])")


def normalise_unit(raw) -> str:
    """One spelling for a unit, so a list of units need not list them all.

    Conservative on purpose. It removes what only ever separates and unifies
    the two words German writes many ways, and it touches nothing else: per
    capita, per square metre and per kilowatt-hour stay distinct from the
    plain rate, because those are other quantities and accepting them would
    put a heat demand per square metre into a column of absolute demands.
    """
    s = unicodedata.normalize("NFKC", str(raw)).casefold()
    s = _EQUIVALENT.sub("eq", s)
    s = _PER_YEAR.sub("/a", s)
    s = _SEPARATORS.sub("", s)
    return re.sub(r"co2e(?!q)", "co2eq", s)


def states_a_year(raw) -> bool:
    """Does this text say the amount is per year?

    The same marker normalise_unit folds into "/a", asked of any text rather
    than of a unit. It exists because the year on a tuple is not a label but
    the period the amount is integrated over, and a unit that does not say
    "per year" leaves that period to the passage: measured on Kassel, 23
    accepted tuples carried a bare GWh or t, 11 of them in a sentence that
    says "pro Jahr", and 3 were a storage capacity that is not a rate at all.
    """
    text = unicodedata.normalize("NFKC", str(raw)).casefold()
    # "/a" is what normalise_unit folds the German phrasings INTO, so it is
    # the one form the regex itself never matches.
    return bool(_PER_YEAR.search(text) or _PER_A.search(text))


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
    the AR6 scenarios of ONE publication, for instance. The profile supplies
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
    type: Optional[str] = None             # "int" for years, "text" for wording
    enum: Optional[tuple] = None
    required: bool = False
    dynamic: bool = False
    # The one line the field request asks. It lives on the axis because the
    # harvest asks per field: a rule buried in a prompt that covers sixteen
    # fields at once is a rule the model can skip, and skipping is what cost
    # the corpus run 63.5% of its years.
    question: Optional[str] = None
    # How far from the row a passage may stand and still be its evidence:
    # "own" the row's own source or the section it stands in, "local" also a
    # source on the neighbouring page, "any" anywhere in the window.
    #
    # Measured on Kassel: 370 of 455 year readings and 87 percent of the area
    # readings cited a passage outside the row's own table and its section,
    # and 146 of them cited the annotated placeholder of a DIFFERENT table.
    # A row label and a column header are read off the table they are in; a
    # scenario is often named a page earlier; a class is argued in a methods
    # chapter anywhere in the plan. So this is per axis and the profile sets
    # it, not one rule for all seven.
    evidence: str = "any"
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
    # What this coordinate becomes in the graph: {"role": "type"|"edge"|
    # "parent"|"comment", ...}. The serializer reads the predicate from here
    # and the JSON schema publishes it, so the two cannot drift: a predicate
    # changed in one place used to leave the other describing a graph nobody
    # was writing.
    kg: Optional[dict] = None

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
    vocabulary: Optional[dict] = None      # category parameters: uri -> labels
    definitions: dict = field(default_factory=dict)
    # A category whose closed list is real but per document, filled in by the
    # profile before the harvest. Same rule as a dynamic axis, one level up.
    vocabulary_dynamic: bool = False
    # What a row of this parameter becomes in the graph: which node, which
    # class, which predicate carries the number and which the unit. Read by
    # the serializer and published by the JSON schema, so neither can drift
    # from the other.
    kg: Optional[dict] = None

    @property
    def is_numeric(self) -> bool:
        return self.value_type in NUMERIC_TYPES

    def unit_factor(self, raw) -> Optional[float]:
        """Factor onto unit_target for a unit as the document writes it.

        Exact spelling first, so a spec stays in charge of its own list; the
        normalised form only decides what the list could not have foreseen.
        """
        if raw in self.units_accepted:
            return self.units_accepted[raw]
        if not isinstance(raw, str):
            return None
        wanted = normalise_unit(raw)
        for unit, factor in self.units_accepted.items():
            if normalise_unit(unit) == wanted:
                return factor
        return None

    def value_to_uri(self) -> dict:
        """Corpus label (folded) -> URI, for a category parameter."""
        out: dict = {}
        for uri, labels in (self.vocabulary or {}).items():
            for label in labels:
                out[fold_label(label)] = uri
        return out


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
    by_uri: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_uri = {p.uri: p for p in self.parameters}


def _vocabulary(path: str, raw):
    """(uri -> spellings, uri -> definition) from either spec form.

    A list is the short form and still the common one: the entry is its
    spellings and the first is what the model is offered. An object adds the
    one thing the list could not carry -- what the term MEANS, in the
    ontology's own words -- without moving the spellings anywhere else.
    """
    if raw is None:
        return None, {}
    if not isinstance(raw, dict) or not raw:
        _fail(path, "vocabulary must be a non-empty object of uri -> labels")
    spellings, definitions = {}, {}
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
        else:
            spellings[uri] = entry
    return spellings, definitions


def _validate_axis(path: str, name: str, raw) -> Axis:
    if not isinstance(raw, dict):
        _fail(path, "axis must be an object")
    vocabulary, definitions = _vocabulary(path, raw.get("vocabulary"))
    axis_type = raw.get("type")
    enum = raw.get("enum")
    dynamic = bool(raw.get("dynamic", False))
    kg = raw.get("kg")
    if kg is not None:
        if not isinstance(kg, dict) or not kg:
            _fail(path, "kg must be a non-empty object")
        role = kg.get("role")
        if role not in ("type", "edge", "parent", "comment"):
            _fail(path, "kg.role must be one of: type, edge, parent, comment")
        if role == "edge" and not str(kg.get("predicate") or "").strip():
            _fail(path, "an edge names the predicate it writes")
        _validate_kg_ids(path, kg)
    evidence = raw.get("evidence", "any")
    if evidence not in ("own", "local", "any"):
        _fail(path, "evidence must be one of: own, local, any")
    derive = raw.get("derive")
    if derive is not None:
        if not isinstance(derive, dict):
            _fail(path, "derive must be an object")
        if derive.get("from") != "unit":
            _fail(path, "derive.from must be 'unit' (nothing else derives yet)")
        if not isinstance(vocabulary, dict) or derive.get("value") not in vocabulary:
            _fail(path, f"derive.value {derive.get('value')!r} is not a key of "
                        f"this axis' vocabulary")
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
    # "text" is what a coordinate looks like when the closed list lives
    # somewhere the spec cannot reach — the scenarios of ONE publication, for
    # instance, which differ per document. The wording is carried through and
    # resolved against that list where it is known; here it is just a string.
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
    return Axis(name=name, vocabulary=vocabulary, type=axis_type,
                enum=enum, required=bool(raw.get("required", False)),
                dynamic=dynamic, question=question, derive=derive,
                evidence=evidence, kg=kg, definitions=definitions)


def _validate_example(path: str, raw, value_type: str,
                      units_accepted: dict) -> dict:
    if not isinstance(raw, dict):
        _fail(path, "example is required: a real corpus snippet plus the "
                    "tuples it must yield (it becomes the prompt's few-shot "
                    "and the runner's golden test)")
    source = raw.get("source")
    if not isinstance(source, str) or len(source.split()) < 5:
        _fail(f"{path}.source", "must be a real snippet, not a placeholder")
    tuples = raw.get("tuples")
    if not isinstance(tuples, list) or not tuples:
        _fail(f"{path}.tuples", "must be a non-empty list")
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
        unit = t.get("unit_raw")
        if unit is not None and unit not in units_accepted:
            _fail(f"{path}.tuples[{i}].unit_raw",
                  f"{unit!r} is not in units_accepted")
    return raw


def _validate_parameter(path: str, raw) -> Parameter:
    if not isinstance(raw, dict):
        _fail(path, "parameter must be an object")
    for key in ("uri", "label", "description"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            _fail(f"{path}.{key}", "required, non-empty string")
    if len(raw["description"].split()) < 8:
        # The description IS the prompt's definition of the parameter. A stub
        # here means the model extracts on vibes.
        _fail(f"{path}.description", "too short to define the parameter for "
                                     "the model (under 8 words)")
    value_type = raw.get("value_type", "float")
    if value_type not in VALUE_TYPES:
        _fail(f"{path}.value_type", f"must be one of {VALUE_TYPES}")

    # A unit belongs to a measured quantity, a vocabulary to a category.
    # Demanding either from the other kind was what kept this contract
    # numbers-only.
    units: dict = {}
    unit_target = raw.get("unit_target")
    vocabulary, value_definitions = _vocabulary(f"{path}.vocabulary", raw.get("vocabulary"))
    vocabulary_dynamic = bool(raw.get("vocabulary_dynamic", False))
    if value_type in NUMERIC_TYPES:
        if not isinstance(unit_target, str) or not unit_target.strip():
            _fail(f"{path}.unit_target",
                  "required for a numeric parameter, non-empty string")
        units = raw.get("units_accepted")
        if not isinstance(units, dict) or not units or \
                not all(isinstance(f, (int, float)) and f > 0 for f in units.values()):
            _fail(f"{path}.units_accepted",
                  "non-empty object of unit string -> positive factor")
        # Two spellings of one unit are the point; two spellings that mean
        # different amounts and normalise alike would silently multiply a
        # value by a thousand, so that is a load error.
        collisions: dict = {}
        for unit, factor in units.items():
            key = normalise_unit(unit)
            if key in collisions and collisions[key][1] != factor:
                _fail(f"{path}.units_accepted",
                      f"{unit!r} and {collisions[key][0]!r} are the same "
                      f"spelling to the verifier but carry {factor} and "
                      f"{collisions[key][1]}")
            collisions[key] = (unit, factor)
    else:
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
    example = _validate_example(f"{path}.example", raw.get("example"),
                                value_type, units)
    if raw.get("kg") is not None:
        # The parameter's block used to be passed through unvalidated, which
        # is the hole "OEO_00030022 organisation" came through.
        _validate_kg_ids(path, raw["kg"])
    return Parameter(uri=raw["uri"], label=raw["label"],
                     description=raw["description"], value_type=value_type,
                     unit_target=unit_target, units_accepted=units,
                     vocabulary=vocabulary, definitions=value_definitions,
                     vocabulary_dynamic=vocabulary_dynamic,
                     axes=axes, example=example, kg=raw.get("kg"))


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
    return Spec(parameters=parameters,
                parameter_question=(question or None))


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
        "evidence": axis.evidence,
        "derive": axis.derive,
        # The offered list: identifier, the spellings a plan may use, and the
        # sentence saying what the term means. All three reach the model, so
        # all three decide whether an answer is still the answer to this
        # question.
        "options": {uri: {"spellings": sorted(map(str, labels or [])),
                          "definition": (axis.definitions or {}).get(uri)}
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
        "value_type": parameter.value_type,
        "unit_target": parameter.unit_target,
        "units": sorted(parameter.units_accepted or {}),
        "example": parameter.example,
    })


def value_fingerprint(parameter: "Parameter") -> str:
    """The list a category parameter answers from, or "" when it has none.

    Spellings AND meanings, the same three things an axis fingerprint takes:
    all of them reach the model when it picks (`fields.Slot.answerable`), so
    a changed definition is a changed question. Left out, a term whose
    meaning was rewritten would leave every document current.
    """
    if not parameter.vocabulary and not parameter.vocabulary_dynamic:
        return ""
    return _digest({
        "dynamic": parameter.vocabulary_dynamic,
        "options": {uri: {"spellings": sorted(map(str, labels or [])),
                          "definition": (parameter.definitions or {}).get(uri)}
                    for uri, labels in (parameter.vocabulary or {}).items()},
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
    for parameter in spec.parameters:
        out[f"parameter/{parameter.uri}"] = parameter_fingerprint(parameter)
        value = value_fingerprint(parameter)
        if value:
            out[f"value/{parameter.uri}"] = value
        for name, axis in (parameter.axes or {}).items():
            out[f"axis/{parameter.uri}/{name}"] = axis_fingerprint(axis)
    return out


_KG_ID = re.compile(r"^[A-Za-z]+_[0-9]+$")


def kg_name(block: dict, prefixes: str) -> str:
    """`{"prefix": "oeo", "predicate": "OEO_00000506"}` -> "oeo:OEO_00000506".

    Qualified from the spec rather than from an f-string in a serializer, and
    only against a prefix the profile's own Turtle header binds: the scenarios
    graph writes four namespaces where kwp writes five, and the same block is
    legal in one profile and unwritable in the other. `dc:abstract` in a kwp
    block would look right in the diff and produce a file no reader can load.
    """
    prefix, predicate = block.get("prefix"), block.get("predicate")
    if not prefix or not predicate:
        raise KeyError(f"{block!r} is no predicate: it needs prefix and "
                       f"predicate")
    if f"@prefix {prefix}:" not in prefixes:
        raise KeyError(f"prefix {prefix!r} is not declared in this profile's "
                       f"header, so the Turtle would not parse")
    return f"{prefix}:{predicate}"


def _validate_kg_ids(path: str, kg) -> None:
    """A class is an identifier and a predicate is one token.

    Both were written by hand as an identifier plus a gloss -- "OEO_00030022
    organisation", and worse "MHPO_00020018 heat plan area, BFO_0000050 part
    of the municipality area" -- and a serializer reading that emits
    `a oeo:OEO_00030022 organisation`, which is not Turtle. Refused where the
    spec is read, so it cannot reach a graph.

    A class is held to the identifier SHAPE and not merely to "no whitespace":
    "organisation" alone would mint `oeo:organisation`. A predicate is held
    only to being one token, because three legal predicates of the scenarios
    profile are the words `abstract`, `acronym` and `label`.
    """
    if not isinstance(kg, dict):
        return
    # Every depth: a class sits on the block, on a map entry and on an axis'
    # `linked_by` alike, and the worst string in the tree was three levels in.
    blocks, stack = [], [kg]
    while stack:
        block = stack.pop()
        blocks.append(block)
        stack.extend(v for v in block.values() if isinstance(v, dict))
    for block in blocks:
        klass = block.get("class")
        if klass is not None and not _KG_ID.match(str(klass)):
            _fail(path, f"kg class {klass!r} is not an identifier: a class is "
                        f"an id like OEO_00030022, and the words for it "
                        f"belong in a label or a note")
        predicate = block.get("predicate")
        if predicate is not None:
            text = str(predicate)
            if not text.strip() or text.split() != [text]:
                _fail(path, f"kg predicate {predicate!r} is not one token")


def own_evidence(spec: "Spec") -> frozenset:
    """(parameter uri, axis name) for every axis whose evidence rule is `own`.

    The rule is per axis and the profile sets it: a row label is read off the
    table it is in, a scenario is often named a page earlier, a class is
    argued in a methods chapter anywhere in the plan. Only `own` can be
    checked from what a harvest row records -- an owner and an id -- because
    `local` is a statement about pages and `any` is no restriction at all.

    So this is the set of axes a later reader may hold to the row's own
    source. Everything outside it was already judged by the harvest, where
    the pages were still in hand.
    """
    out = set()
    for parameter in spec.parameters:
        for name, axis in (parameter.axes or {}).items():
            if axis.evidence == "own":
                out.add((parameter.uri, name))
    return frozenset(out)
