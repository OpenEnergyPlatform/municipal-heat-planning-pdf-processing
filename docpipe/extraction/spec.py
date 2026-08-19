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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

VALUE_TYPES = ("float", "int")
SCENARIOS = ("status_quo", "trend", "target", "unknown")


class SpecError(ValueError):
    """A spec that must not be run with. Message names the offending field."""


def _fail(path: str, message: str) -> None:
    raise SpecError(f"{path}: {message}")


@dataclass
class Axis:
    """One dimension of a value: a closed vocabulary, an int, or an enum."""
    name: str
    vocabulary: Optional[dict] = None      # target URI -> corpus labels
    type: Optional[str] = None             # "int" for years
    enum: Optional[tuple] = None
    required: bool = False

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
    unit_target: str
    units_accepted: dict                   # unit string -> factor to target
    axes: dict                             # name -> Axis
    example: dict                          # {"source": str, "tuples": [...]}


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
    kinds = sum(x is not None for x in (vocabulary, axis_type, enum))
    if kinds != 1:
        _fail(path, "an axis is exactly one of: vocabulary, type, enum")
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
    if axis_type is not None and axis_type != "int":
        _fail(path, f"unsupported axis type {axis_type!r}")
    if enum is not None:
        if not isinstance(enum, list) or not all(isinstance(e, str) for e in enum):
            _fail(path, "enum must be a list of strings")
        enum = tuple(enum)
    return Axis(name=name, vocabulary=vocabulary, type=axis_type,
                enum=enum, required=bool(raw.get("required", False)))


def _validate_example(path: str, raw, units_accepted: dict) -> dict:
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
    for i, t in enumerate(tuples):
        if not isinstance(t, dict) or not isinstance(t.get("value"), (int, float)):
            _fail(f"{path}.tuples[{i}]", "each tuple needs a numeric 'value'")
        unit = t.get("unit_raw")
        if unit is not None and unit not in units_accepted:
            _fail(f"{path}.tuples[{i}].unit_raw",
                  f"{unit!r} is not in units_accepted")
    return raw


def _validate_parameter(path: str, raw) -> Parameter:
    if not isinstance(raw, dict):
        _fail(path, "parameter must be an object")
    for key in ("uri", "label", "description", "unit_target"):
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
    units = raw.get("units_accepted")
    if not isinstance(units, dict) or not units or \
            not all(isinstance(f, (int, float)) and f > 0 for f in units.values()):
        _fail(f"{path}.units_accepted",
              "non-empty object of unit string -> positive factor")
    axes_raw = raw.get("axes")
    if not isinstance(axes_raw, dict) or not axes_raw:
        _fail(f"{path}.axes", "required, non-empty object")
    axes = {name: _validate_axis(f"{path}.axes.{name}", name, a)
            for name, a in axes_raw.items()}
    example = _validate_example(f"{path}.example", raw.get("example"), units)
    return Parameter(uri=raw["uri"], label=raw["label"],
                     description=raw["description"], value_type=value_type,
                     unit_target=raw["unit_target"], units_accepted=units,
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
