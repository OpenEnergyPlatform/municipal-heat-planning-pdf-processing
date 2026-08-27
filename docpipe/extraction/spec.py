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
    type: Optional[str] = None             # "int" for years, "text" for wording
    enum: Optional[tuple] = None
    required: bool = False
    dynamic: bool = False

    def label_to_uri(self) -> dict:
        """Corpus label (casefolded) -> URI. Built once, used per tuple."""
        out: dict = {}
        for uri, labels in (self.vocabulary or {}).items():
            for label in labels:
                out[label.casefold()] = uri
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
    # A category whose closed list is real but per document, filled in by the
    # profile before the harvest. Same rule as a dynamic axis, one level up.
    vocabulary_dynamic: bool = False

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
        """Corpus label (casefolded) -> URI, for a category parameter."""
        out: dict = {}
        for uri, labels in (self.vocabulary or {}).items():
            for label in labels:
                out[label.casefold()] = uri
        return out


@dataclass
class Spec:
    parameters: list
    by_uri: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_uri = {p.uri: p for p in self.parameters}


def _validate_axis(path: str, name: str, raw) -> Axis:
    if not isinstance(raw, dict):
        _fail(path, "axis must be an object")
    vocabulary = raw.get("vocabulary")
    axis_type = raw.get("type")
    enum = raw.get("enum")
    dynamic = bool(raw.get("dynamic", False))
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
                other = seen.get(label.casefold())
                if other and other != uri:
                    # One label mapping to two URIs would make every match a
                    # coin toss; better to refuse the spec than to guess later.
                    _fail(f"{path}.{uri}", f"label {label!r} already maps to {other}")
                seen[label.casefold()] = uri
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
    return Axis(name=name, vocabulary=vocabulary, type=axis_type,
                enum=enum, required=bool(raw.get("required", False)),
                dynamic=dynamic)


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
    vocabulary = raw.get("vocabulary")
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
                    other = seen.get(label.casefold())
                    if other and other != uri:
                        _fail(f"{path}.vocabulary.{uri}",
                              f"label {label!r} already maps to {other}")
                    seen[label.casefold()] = uri
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
    return Parameter(uri=raw["uri"], label=raw["label"],
                     description=raw["description"], value_type=value_type,
                     unit_target=unit_target, units_accepted=units,
                     vocabulary=vocabulary,
                     vocabulary_dynamic=vocabulary_dynamic,
                     axes=axes, example=example)


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
    return Spec(parameters=parameters)
