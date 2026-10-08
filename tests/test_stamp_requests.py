"""What a stamp fingerprint counts must reach the model.

A fingerprint says "this question changed", and a changed question makes a
stamped document stale. Counting something no request shows makes a document
stale over a sentence no model read: the definitions of a category value were
counted while the rows request never showed one, so a reworded ontology term
cost a corpus a re-read for nothing.

Promised: every input of every fingerprint the stamp compares arrives in a
request of the harvest, AND the check can tell, so an input that is counted and
never sent is found.

The requests are the ones the harvest sends, built by its own askers against a
recording client. The inputs are not listed here, they are found: each leaf of
a raw spec is changed in turn, the parts the fingerprints hash are compared
before and after, and a leaf that moves one has to show up in the requests (a
sentinel text) or change them (a flag).
"""
import copy
import json
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from docpipe.extraction import fields, runner, spec as spec_mod
from docpipe.extraction.pipeline import Row, Source, WorkItem, group_items
from docpipe.profile import load_profile

PROFILES = Path(__file__).resolve().parent.parent / "profiles"

# Containers whose keys are data (a uri, an axis name, a unit), not the shape
# of the spec.
DATA_KEYS = ("axes", "vocabulary", "units_accepted", "definitions")
# Subtrees no fingerprint reads, so changing them is noise.
SKIP = ("kg", "graph", "_comment")
# A string that is one of a few kinds: a sentinel would not load.
SWAP = {"int": "text", "text": "int", "float": "int"}

# What a fingerprint counts and no request shows, on purpose. Each is a leaf
# of the raw spec, with the one (family, part) of a fingerprint it is counted
# in and the reason it still belongs to the key. A leaf that moves any other
# part is not exempt: another input counted from the same leaf is found. The
# test below holds that each really is never sent: an entry that starts being
# shown is an exemption nobody needs.
NEVER_SHOWN = {
    "parameters.[].unit_target": (
        ("parameter", "unit_target"),
        "the model reads the unit; the target is what the number is "
        "converted to afterwards, and a moved target moves every value_target"),
    "parameters.[].axes.*.vocabulary.*": (
        ("axis", "options"),
        "the uri an axis class resolves to: the model answers with the class "
        "name and the verifier maps it, so a renamed uri moves every stored "
        "answer and no request"),
    "parameters.[].vocabulary.*": (
        ("value", "options"),
        "the same for the list a category value is chosen from"),
    "parameters.[].axes.*.required": (
        ("axis", "required"),
        "whether the verifier refuses an empty answer; no request carries "
        "such a flag"),
}
# Parts a leaf of a spec cannot move alone, because changing it makes the spec
# invalid. Neither is in a request: the flag says where a list comes from, and
# a derived coordinate is never asked.
NOT_REACHED = {("axis", "dynamic"), ("value", "dynamic"), ("axis", "derive")}

# A raw spec that carries every kind of input the two profiles do not: an enum.
RICH = {
    "parameter_question": "Welche Groesse ist diese Zahl?",
    "unit_question": "Welche Einheit ist diese Zahl?",
    "parameters": [
        {"uri": "energy", "label": "Endenergie",
         "description": "Endenergieverbrauch je Energietraeger, Sektor und "
                        "Jahr, wie im Plan bilanziert.",
         "value_type": "float", "unit_target": "kWh",
         "units_accepted": {
             "kWh/a": {"factor": 0.001, "names_period": True},
             "MWh/a": {"factor": 1.0, "names_period": True}},
         "axes": {
             "carrier": {"question": "Welcher Energietraeger steht hier?",
                         "required": True,
                         "vocabulary": {"oeo:gas": {
                             "label": "Erdgas", "spellings": ["Gas"],
                             "definition": "Ein brennbares Gas."}}},
             "basis": {"question": "Auf welcher Basis steht die Zahl?",
                       "enum": ["Ist", "Ziel"]},
             "year": {"question": "Welches Jahr?", "type": "int"}},
         "example": {"source": "| Erdgas | 42.005 | MWh/a | im Jahr 2020 |",
                     "tuples": [{"value": 42005, "unit_raw": "MWh/a"}]}},
        {"uri": "kind", "label": "Art des Szenarios",
         "description": "Die Art eines Szenarios, gewaehlt aus der Liste der "
                        "Klassen, die dieses Feld zulaesst.",
         "value_type": "category",
         "vocabulary": {"oeo:target": {
             "label": "Zielszenario", "spellings": ["Ziel"],
             "definition": "Ein Szenario mit einem Ziel."}},
         "axes": {},
         "example": {"source": "Das Zielszenario beschreibt den angestrebten "
                               "Zustand im Jahr 2045.",
                     "tuples": [{"value": "Zielszenario"}]}},
    ],
}


def _profiles():
    return sorted(p.parent.name for p in PROFILES.glob("*/extraction_spec.json"))


class _Recorder:
    """The model, as far as a request goes: it keeps what it was sent."""

    def __init__(self):
        self.sent = []
        recorder = self

        class _Msg:
            content = '{"x": 1}'
            reasoning_content = ""

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]
            usage = None

        class _Completions:
            @staticmethod
            def create(**kw):
                recorder.sent.append(json.dumps(
                    {"messages": kw.get("messages"),
                     "response_format": kw.get("response_format")},
                    ensure_ascii=False, default=str))
                return _Resp()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _requests(spec, frame_names, patch) -> str:
    """Everything the harvest sends the model for this spec, as one text."""
    client = _Recorder()
    patch.setattr(runner, "_client", lambda: client)
    patch.setattr(runner.time, "sleep", lambda s: None)
    source = Source("table", 1, "| Erdgas | 1 |", {"document_id": 7, "page": 1})
    row = Row("R1", 0, {"value": 1, "quote": "| Erdgas | 1 |", "unit": "MWh/a"})
    harvest = runner.make_harvester(spec=spec)
    for parameter in [*spec.parameters, None]:       # per parameter, per document
        harvest(group_items([WorkItem(7, parameter, source)])[0])
    ask = runner.make_field_asker()
    for parameter in spec.parameters:
        unit = fields.unit_slot(spec, parameter)
        for slot in [*fields.asked_slots(parameter),
                     *([unit] if unit is not None else [])]:
            ask([source], [row], slot)
    ask([source], [row], fields.parameter_slot(spec))
    frame = fields.frame_slots(spec, frame_names)
    if frame:
        runner.make_frame_asker()([source], frame)
    runner.make_anchors(spec, client=client)
    runner.document_anchor(spec, {"name": "Plan"}, client=client)
    # Sorted: the anchors are written by a pool, in no fixed order.
    return "\n".join(sorted(client.sent))


def _family(key: str) -> str:
    return key if key.startswith("slot/") else key.split("/")[0]


def _parts(spec) -> set:
    """{(family, part, value)} for everything the fingerprints of this spec
    hash, read off the digest itself so that no list of inputs is kept here."""
    seen: dict = {}
    real = spec_mod._digest

    def recording(parts):
        digest = real(parts)
        seen[digest] = parts
        return digest

    with MonkeyPatch.context() as patch:
        patch.setattr(spec_mod, "_digest", recording)
        keys = spec_mod.fingerprints(spec)
    return {(_family(key), part, json.dumps(value, sort_keys=True,
                                            ensure_ascii=False))
            for key, digest in keys.items()
            for part, value in seen[digest].items()}


def _leaves(node, path=()):
    """(kind, path) for every value of a raw spec and every key that is data
    rather than the spec's own shape."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SKIP:
                continue
            if path and path[-1] in DATA_KEYS:
                yield "key", path + (key,)
            yield from _leaves(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _leaves(value, path + (index,))
    else:
        yield "value", path


def _pattern(path) -> str:
    """The role of a leaf: its path with the data keys and indices folded."""
    out, parent = [], None
    for step in path:
        out.append("[]" if isinstance(step, int)
                   else "*" if parent in DATA_KEYS else step)
        parent = step
    return ".".join(map(str, out))


def _at(raw, path):
    for step in path:
        raw = raw[step]
    return raw


def _changed(raw, kind, path, sentinel):
    """A copy of the raw spec with this one leaf changed, or None."""
    out = copy.deepcopy(raw)
    parent, last = _at(out, path[:-1]), path[-1]
    if kind == "key":
        items = [(last + sentinel if k == last else k, v)
                 for k, v in parent.items()]             # keeps its place
        parent.clear()
        parent.update(items)
        return out
    value = parent[last]
    if isinstance(value, bool):
        parent[last] = not value
    elif isinstance(value, str):
        parent[last] = SWAP.get(value, value + sentinel)
    elif isinstance(value, (int, float)):
        parent[last] = value + 1
    else:
        return None
    return out


class Inputs:
    """What the leaves of one raw spec did to the fingerprints and to the
    requests.

    `unsent` maps a leaf pattern that moved a hashed part and showed up in no
    request to the (family, part) pairs it moved; `reached` is every pair some
    leaf moved and `hashed` every pair the fingerprints hash at all.
    """

    def __init__(self, raw, frame_names, patch):
        self.unsent: dict = {}
        self.reached: set = set()
        before_spec = spec_mod.load(copy.deepcopy(raw))
        before = _parts(before_spec)
        self.hashed = {(family, part) for family, part, _v in before}
        base = _requests(before_spec, frame_names, patch)
        seen = set()
        for kind, path in _leaves(raw):
            pattern = _pattern(path)
            if (kind, pattern) in seen:
                continue
            sentinel = f"ZQ{len(seen)}ZQ"
            changed = _changed(raw, kind, path, sentinel)
            if changed is None:
                continue
            try:
                spec = spec_mod.load(changed)
            except spec_mod.SpecError:
                continue
            seen.add((kind, pattern))
            moved = {(family, part)
                     for family, part, _v in before ^ _parts(spec)}
            if not moved:
                continue                    # no fingerprint counts this leaf
            self.reached |= moved
            text = _requests(spec, frame_names, patch)
            value = _at(raw, path) if kind == "value" else None
            if kind == "key" or (isinstance(value, str)
                                 and value not in SWAP):
                shown = sentinel in text
            else:                           # a flag, a number, a swapped kind
                shown = text != base
            if not shown:
                self.unsent[pattern] = sorted(moved)


def _inputs_of(name, patch):
    patch.setenv("DOCPIPE_PROFILE", "kwp" if name == "rich" else name)
    if name == "rich":
        return Inputs(copy.deepcopy(RICH), (), patch)
    raw = json.loads((PROFILES / name / "extraction_spec.json")
                     .read_text(encoding="utf-8"))
    frame = load_profile(name).component("extraction", "FRAME") or ()
    return Inputs(raw, frame, patch)


@pytest.fixture(scope="module", params=[*_profiles(), "rich"])
def found(request):
    """One pass over a spec, shared by the tests below."""
    with MonkeyPatch.context() as patch:
        yield request.param, _inputs_of(request.param, patch)


@pytest.fixture(scope="module")
def rich():
    with MonkeyPatch.context() as patch:
        yield _inputs_of("rich", patch)


def _stray(got) -> dict:
    """The leaves that moved a counted part no request shows, less the ones
    named in NEVER_SHOWN for exactly that part."""
    return {pattern: moved for pattern, moved in got.unsent.items()
            if moved != [NEVER_SHOWN.get(pattern, ((),))[0]]}


def test_every_input_a_fingerprint_counts_arrives_in_a_request(found):
    name, got = found
    stray = _stray(got)
    assert not stray, (
        f"{name}: counted by a stamp key and shown in no request: {stray}. "
        f"Take it out of the fingerprint, or show it, or list it in "
        f"NEVER_SHOWN with the reason it still belongs to the key")


def test_every_part_a_fingerprint_hashes_is_reached_by_some_leaf(rich):
    """A part no leaf moves is an input this check never looked at: a new
    input of a fingerprint has to be exercised here or named in NOT_REACHED."""
    unreached = rich.hashed - rich.reached - NOT_REACHED
    assert not unreached, f"hashed and never exercised: {sorted(unreached)}"


def test_what_is_listed_as_never_shown_still_is(rich):
    """An exemption that stopped being true is a hole in the next check."""
    named = {leaf: [part] for leaf, (part, _why) in NEVER_SHOWN.items()}
    assert named == {leaf: rich.unsent.get(leaf) for leaf in NEVER_SHOWN}


def test_a_definition_counted_and_never_sent_is_found():
    """The case this file exists for, built by construction: the fingerprint
    of a category value counts its definitions, as it did, and no request
    shows one."""
    def counting_definitions(parameter):
        if not parameter.vocabulary and not parameter.vocabulary_dynamic:
            return ""
        return spec_mod._digest({
            "dynamic": parameter.vocabulary_dynamic,
            "options": {uri: {"spellings": sorted(map(str, labels or [])),
                              "definition": (parameter.definitions
                                             or {}).get(uri)}
                        for uri, labels in (parameter.vocabulary
                                            or {}).items()}})

    with MonkeyPatch.context() as patch:
        patch.setenv("DOCPIPE_PROFILE", "kwp")
        patch.setattr(spec_mod, "value_fingerprint", counting_definitions)
        got = Inputs(copy.deepcopy(RICH), (), patch)
    assert "parameters.[].vocabulary.*.definition" in got.unsent
    assert got.unsent["parameters.[].vocabulary.*.definition"] \
        == [("value", "options")]
    # And the axis, whose definitions the field request does show, is not
    # accused of the same.
    assert "parameters.[].axes.*.vocabulary.*.definition" not in got.unsent


def test_a_flag_that_moves_a_key_and_no_request_is_found():
    """The same for a bare flag, which a sentinel cannot show: a fingerprint
    counting a parameter's `integrated` while no request carries it."""
    def counting_a_flag(parameter):
        return spec_mod._digest({
            "uri": parameter.uri, "label": parameter.label,
            "description": parameter.description,
            "value_type": parameter.value_type,
            "unit_target": parameter.unit_target,
            "units": sorted(parameter.units_accepted or {}),
            "example": parameter.example,
            "integrated": parameter.integrated})

    raw = copy.deepcopy(RICH)
    raw["parameters"][0]["integrated"] = True
    with MonkeyPatch.context() as patch:
        patch.setenv("DOCPIPE_PROFILE", "kwp")
        patch.setattr(spec_mod, "parameter_fingerprint", counting_a_flag)
        got = Inputs(raw, (), patch)
    assert got.unsent["parameters.[].integrated"] \
        == [("parameter", "integrated")]


def test_a_second_input_counted_from_an_exempt_leaf_is_found():
    """`unit_target` is exempt as the part it is counted in. Counted a second
    time as another part, it is a new input that no request shows, and the
    exemption does not cover it."""
    real = spec_mod.parameter_fingerprint

    def counting_it_twice(parameter):
        return spec_mod._digest({"question": real(parameter),
                                 "target again": parameter.unit_target})

    with MonkeyPatch.context() as patch:
        patch.setenv("DOCPIPE_PROFILE", "kwp")
        patch.setattr(spec_mod, "parameter_fingerprint", counting_it_twice)
        got = Inputs(copy.deepcopy(RICH), (), patch)
    assert "parameters.[].unit_target" in _stray(got)
