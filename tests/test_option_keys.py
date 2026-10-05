"""The entries of a closed list go to the model under English keys.

Promised: kwp, scenarios and the built-in profile name the two keys of every
entry of a closed list "means" and "spellings" AND nothing else in a request
of kwp or scenarios (the field request, the second reading, the frame request
and the chat's coordinate question) differs from what it was, except the
prompt sentence that names those keys AND no harvest stamped before goes
stale by it.

`tests/fixtures/option_keys_before.json` holds the four requests of both
profiles as the code built them while the keys were still German, over one
fixed window and fixed synthetic slots, so that it moves with the code and
the prompts and not with a spec. What a request is now is what the fixture
says with exactly two words renamed. A request that differs in a third place
is not this change: whoever changes a request of these profiles on purpose
changes the fixture in the same commit and says so.
"""
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docpipe import prompts
from docpipe.extraction import fields, runner, wording
from docpipe.extraction.pipeline import Row, Source
from docpipe.extraction.spec import fingerprints, load as load_spec
from docpipe.inference import llm_client
from docpipe.profile import load_profile

FIXTURE = (Path(__file__).resolve().parent / "fixtures"
           / "option_keys_before.json")
GERMAN = ("kwp", "scenarios")

# The whole difference, as a table: the word that stood in a request and the
# one that stands there now. Quoted, so the German prose of a prompt ("die
# Schreibweisen") is not touched, and a key and the prompt sentence that names
# it are renamed by the same rule.
RENAMED = {'"bedeutet"': '"means"', '"Schreibweisen"': '"spellings"'}


# -- one fixed window and fixed slots ------------------------------------------

CARRIER = fields.Slot(
    name="carrier", kind=fields.CHOICE, question="Welcher Energieträger?",
    options=(
        fields.Option(label="Erdgas", uri="u1",
                      synonyms=("Gas H", "Erdgas (netzgebunden)"),
                      definition="ein Gas"),
        fields.Option(label="Strom", uri="u2", synonyms=("Elektrizität",)),
        fields.Option(label="out:total", uri="out:total",
                      synonyms=("Summe",), definition="eine Summenzeile"),
    ))
SCENARIO = fields.Slot(
    name="scenario", kind=fields.CHOICE, question="Welcher Zustand?",
    options=(
        fields.Option(label="Bestand", uri="status_quo",
                      synonyms=("Ist-Zustand",),
                      definition="der Stand, den der Plan selbst erhebt"),
        fields.Option(label="Zielszenario", uri="target",
                      synonyms=("Klimaschutzszenario",)),
    ))
YEAR = fields.Slot(name="year", kind=fields.NUMBER, question="Welches Jahr?")
VALUE = fields.Slot(name="value", kind=fields.VALUE, required=True,
                    question="Welche Zahl steht dort?")

TABLE = "| Energieträger | 2022 |\n| Erdgas | 241 |"
SOURCE = Source("table", 1, TABLE,
                {"document_id": 7, "page": 85, "block_id": "p85_tbl0",
                 "title": "Tabelle 17", "section_title": "Verbrauch"})
PARENT = Source("section", 5, "Abschnitt 4: Endenergieverbrauch 2022.",
                {"document_id": 7, "page": 85, "via": "parent"})
ROW = Row(label="R1", item_index=0,
          claim={"value": 241, "quote": "| Erdgas | 241 |", "unit": "MWh/a"})
STORED = {"value": 241, "quote": "| Erdgas | 241 |", "unit": "MWh/a",
          "provenance": {"owner_kind": "table", "owner_id": 1,
                         "parent_section": 5}}
NUMERIC = NS(is_numeric=True, units_accepted={"MWh/a"})


# -- the four requests -----------------------------------------------------------

def _answer(content):
    return NS(choices=[NS(message=NS(content=content, reasoning_content=""),
                          finish_reason="stop")], usage=None)


def _recording_client(seen, content):
    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    seen.append({"messages": kw["messages"],
                                 "temperature": kw["temperature"],
                                 "response_format": kw.get("response_format")})
                    return _answer(content)
    return _Client()


def requests_of(name: str) -> dict:
    """The field request, the second reading, the frame request and the
    chat's coordinate question of this profile, as they would be sent."""
    sent: dict = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DOCPIPE_PROFILE", name)
        patch.setattr(runner, "MAX_MODEL_LEN", 32768)
        patch.setattr(runner, "ATTACH_IMAGES", False)
        for key, content, ask in (
                ("field", '{"fields": {"carrier": {"answers": {}}}}',
                 lambda: runner.make_field_asker()(
                     [SOURCE, PARENT], [ROW], CARRIER, None, 7, None,
                     {"R1": SOURCE})),
                ("review", "{}",
                 lambda: runner.make_review_asker()(
                     STORED, [SOURCE, PARENT], NUMERIC, [VALUE, CARRIER])),
                ("frame", '{"pairs": []}',
                 lambda: runner.make_frame_asker()(
                     [SOURCE, PARENT], [SCENARIO, YEAR], 7))):
            seen: list = []
            patch.setattr(runner, "_client",
                          lambda seen=seen, content=content:
                          _recording_client(seen, content))
            ask()
            assert len(seen) == 1, f"{key}: {len(seen)} request(s) were sent"
            sent[key] = seen[0]
        asked: list = []
        patch.setattr(llm_client, "LLM_STUB_MODE", False)
        patch.setattr(llm_client, "_chat_json",
                      lambda messages, temperature: asked.append(
                          {"messages": messages, "temperature": temperature})
                      or {"answer": None})
        llm_client.choose(prompts.load("kg/coordinate"),
                          "Wie hoch ist der Verbrauch an Erdgas?",
                          CARRIER.question, CARRIER.answerable())
        assert len(asked) == 1, f"coordinate: {len(asked)} request(s)"
        sent["coordinate"] = {**asked[0], "response_format": None}
    return sent


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def renamed(value, table=RENAMED):
    """*value* with the two words renamed in every string of it, and in
    nothing else."""
    if isinstance(value, str):
        for old, new in table.items():
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [renamed(item, table) for item in value]
    if isinstance(value, dict):
        return {key: renamed(item, table) for key, item in value.items()}
    return value


def text_of(value) -> str:
    """Every string of a request, as the model reads them."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_of(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(text_of(item) for item in value.values())
    return ""


def differences(expected, got, where="") -> list:
    """Where two requests differ, as the paths of what is not the same."""
    if isinstance(expected, dict) and isinstance(got, dict):
        out = []
        for key in sorted(set(expected) | set(got)):
            if key not in expected or key not in got:
                out.append(f"{where}/{key} (only one side has it)")
            else:
                out += differences(expected[key], got[key], f"{where}/{key}")
        return out
    if isinstance(expected, list) and isinstance(got, list):
        if len(expected) != len(got):
            return [f"{where} ({len(expected)} against {len(got)} item(s))"]
        return [path for i, (a, b) in enumerate(zip(expected, got))
                for path in differences(a, b, f"{where}[{i}]")]
    return [] if expected == got else [where]


@pytest.fixture(scope="module")
def before():
    return _fixture()


def worded(name) -> dict:
    """The profile's phrase table itself, so a test can edit it."""
    return wording.phrases(load_profile(name))


def _spec_path(name) -> Path:
    return Path(load_profile(name).component("extraction", "SPEC_PATH"))


def _spec(name):
    return load_spec(_spec_path(name))


# -- the keys -------------------------------------------------------------------

def option_keys(slot) -> set:
    """The keys the entries of this slot's closed list are sent under."""
    return {key for entry in slot.answerable().values()
            if isinstance(entry, dict) for key in entry}


@pytest.mark.parametrize("name", [*GERMAN, "default"])
def test_every_profile_names_the_keys_of_an_entry_means_and_spellings(
        name, monkeypatch):
    own = wording.phrases(load_profile(name))
    assert (own["option_means"], own["option_spellings"]) == (
        "means", "spellings")
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    assert option_keys(CARRIER) == {"means", "spellings"}
    # and in the order the request has always had them
    assert list(CARRIER.answerable()["Erdgas"]) == ["means", "spellings"]


@pytest.mark.parametrize("name", GERMAN)
def test_a_profile_that_still_says_the_german_keys_is_caught(
        name, monkeypatch):
    """The case that breaks it: the table as it was."""
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    monkeypatch.setitem(worded(name), "option_means", "bedeutet")
    monkeypatch.setitem(worded(name), "option_spellings", "Schreibweisen")
    assert option_keys(CARRIER) == {"bedeutet", "Schreibweisen"}
    assert option_keys(CARRIER) != {"means", "spellings"}


def keys_over_spec(name) -> set:
    """The keys of every list the real spec can send: the parameter's, the
    unit's, the value's of a parameter that has a list (the second reading
    offers it) and every axis'."""
    spec = _spec(name)
    slots = [fields.parameter_slot(spec)]
    for parameter in spec.parameters:
        slots += fields.slots(parameter)
        unit = fields.unit_slot(spec, parameter)
        if unit is not None:
            slots.append(unit)
    seen: set = set()
    for slot in slots:
        if slot.options:
            seen |= option_keys(slot)
    return seen


@pytest.mark.parametrize("name", GERMAN)
def test_no_closed_list_of_the_spec_goes_out_under_a_german_key(
        name, monkeypatch):
    """The union has to be the two keys, which also says the spec carries
    definitions at all: a spec without any would pass an empty check."""
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    assert keys_over_spec(name) == {"means", "spellings"}


@pytest.mark.parametrize("name", GERMAN)
def test_a_german_key_over_the_spec_is_caught(name, monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    monkeypatch.setitem(worded(name), "option_means", "bedeutet")
    assert keys_over_spec(name) == {"bedeutet", "spellings"}
    assert keys_over_spec(name) != {"means", "spellings"}


# -- nothing else moved ---------------------------------------------------------

@pytest.mark.parametrize("name", GERMAN)
def test_a_request_of_the_german_profiles_differs_by_exactly_the_two_words(
        name, before):
    got = requests_of(name)
    assert set(got) == set(before[name]) == {
        "field", "review", "frame", "coordinate"}
    assert differences(renamed(before[name]), got) == []
    # and the words really are the ones that were sent, so the comparison
    # above is not between two requests that never carried them
    sent = text_of(got)
    assert '"means":' in sent and '"spellings":' in sent
    assert '"bedeutet"' not in sent and '"Schreibweisen"' not in sent


@pytest.mark.parametrize("name", GERMAN)
def test_the_fixture_really_holds_the_german_keys(name, before):
    """The other half of the promise: the "before" is German. A fixture that
    had been regenerated from the new code would make the test above compare
    the code with itself."""
    sent = text_of(before[name])
    assert '"bedeutet":' in sent and '"Schreibweisen":' in sent
    assert '"means"' not in sent and '"spellings"' not in sent
    for key in ("field", "review", "frame", "coordinate"):
        user = before[name][key]["messages"][-1]["content"]
        assert '"bedeutet":' in user, key


@pytest.mark.parametrize("name", GERMAN)
def test_the_keys_not_renamed_are_caught(name, before, monkeypatch):
    """The table put back to the German words is a difference, and it shows
    in the user message of every request and nowhere else."""
    monkeypatch.setitem(worded(name), "option_means", "bedeutet")
    monkeypatch.setitem(worded(name), "option_spellings", "Schreibweisen")
    found = differences(renamed(before[name]), requests_of(name))
    assert found, "the German keys went out and nothing noticed"
    assert all(path.endswith("/content") for path in found), found
    assert {path.split("/")[1] for path in found} == {
        "field", "review", "frame", "coordinate"}


@pytest.mark.parametrize("name", GERMAN)
def test_a_third_difference_in_a_request_is_caught(name, before,
                                                    monkeypatch):
    """Not the two words but a third thing: a sentence of the stage worded
    otherwise reaches the options of every request that lists UNSTATED."""
    monkeypatch.setitem(worded(name), "unstated_means", "nichts davon")
    found = differences(renamed(before[name]), requests_of(name))
    assert found, "a third difference went through"
    assert any("messages" in path for path in found)


@pytest.mark.parametrize("name", GERMAN)
def test_a_third_difference_in_a_prompt_or_a_body_is_caught(name, before):
    """Each way a request can differ in a third place, one at a time."""
    got = requests_of(name)
    for change in (
            lambda r: r["field"]["messages"][0].update(
                content=r["field"]["messages"][0]["content"] + " Rate."),
            lambda r: r["review"].update(temperature=0.7),
            lambda r: r["frame"]["messages"].append(
                {"role": "user", "content": "und noch etwas"}),
            lambda r: r["coordinate"]["messages"][0].update(
                content=r["coordinate"]["messages"][0]["content"] + " Rate."),
            lambda r: r["field"].update(response_format=None)):
        other = copy.deepcopy(got)
        change(other)
        assert differences(renamed(before[name]), other), change


def test_the_comparison_sees_a_rename_the_prompt_did_not_follow(before):
    """The sentence of rule 7 is part of the request. A prompt that kept the
    German words next to keys that are English tells the model of keys that
    are not there."""
    got = requests_of("kwp")
    stale = copy.deepcopy(got)
    system = stale["field"]["messages"][0]
    system["content"] = system["content"].replace(
        '"means"', '"bedeutet"').replace('"spellings"', '"Schreibweisen"')
    assert differences(renamed(before["kwp"]), stale) == [
        "/field/messages[0]/content"]


# -- the prompt names what the request sends -----------------------------------

def _rule_seven(text: str) -> str:
    lines = [line for line in text.splitlines() if line.startswith("7. ")]
    assert len(lines) == 1, lines
    return lines[0]


def _keys_the_rule_names(text: str) -> set:
    quoted = set(re.findall(r'"([^"]+)"', _rule_seven(text)))
    return {word for word in quoted if not word.startswith("out:")}


def test_the_kwp_field_prompt_names_the_keys_the_request_sends(before):
    """The one prompt that names the keys, by the sentence of rule 7."""
    got = requests_of("kwp")["field"]
    named = _keys_the_rule_names(got["messages"][0]["content"])
    user = got["messages"][-1]["content"]
    assert named == {"means", "spellings"}
    for key in named:
        assert f'"{key}":' in user, key
    # the case that breaks it: the prompt as it was names keys not sent
    was = before["kwp"]["field"]["messages"][0]["content"]
    old = _keys_the_rule_names(was)
    assert old == {"bedeutet", "Schreibweisen"}
    assert old != named


def test_the_scenarios_prompts_name_no_key_of_an_entry(before):
    """Nothing to follow there: its field prompt describes the entries and
    names no key, so it cannot go stale by the rename."""
    named = re.compile(r'"(means|spellings|bedeutet|Schreibweisen)"')
    for key in ("field", "review", "frame", "coordinate"):
        for text in (before["scenarios"][key]["messages"][0]["content"],
                     requests_of("scenarios")[key]["messages"][0]["content"]):
            assert not named.search(text), key
    # the case that breaks it: the one prompt that does name them
    assert named.search(before["kwp"]["field"]["messages"][0]["content"])


# -- no stamp goes stale --------------------------------------------------------

def _first_definition(node, below=None):
    """The first dict that holds both a label and a definition; with `below`,
    the first one that lies under a key of that name."""
    if isinstance(node, dict):
        worded = isinstance(node.get("definition"), str) and node.get("label")
        if below is None and worded:
            return node
        for key, item in node.items():
            found = _first_definition(item, None if key == below else below)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _first_definition(item, below)
            if found is not None:
                return found
    return None


def _stamped(directory, stamp: dict):
    """A document of an earlier run: its harvest and the stamp beside it."""
    (directory / "plan.jsonl").write_text("", encoding="utf-8")
    (directory / "plan.stamp.json").write_text(json.dumps(stamp),
                                               encoding="utf-8")


@pytest.mark.parametrize("name", GERMAN)
def test_a_harvest_stamped_with_the_german_keys_is_current_with_the_english(
        name, tmp_path, monkeypatch):
    """The stamp's keys come from what the spec holds, and the wording the
    stage sends them in is not among them. Written under the German table and
    with another prompt than today's, read under the new ones: nothing in it
    differs, so no document is asked again."""
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    spec = _spec(name)
    now = runner._stamp_current("spec-sha", "anchors-sha", spec)
    with monkeypatch.context() as old:
        old.setitem(worded(name), "option_means", "bedeutet")
        old.setitem(worded(name), "option_spellings", "Schreibweisen")
        then = runner._stamp_current("spec-sha", "anchors-sha", spec)
    assert then == now, "the stamp does not carry the wording of a request"
    assert fingerprints(spec) and fingerprints(spec).items() <= now.items()
    # What was recorded about the prompts is recorded and never compared: the
    # prompt of kwp's rule 7 is another text since this change.
    earlier = {k: ("sha-of-the-prompt-before"
                   if k in runner.PROMPT_IDS else v) for k, v in now.items()}
    assert earlier != now
    _stamped(tmp_path, earlier)
    assert runner.stale(tmp_path / "plan.stamp.json", now) == []
    assert runner.already_done("plan", tmp_path, "spec-sha", force_stale=True,
                               anchors_sha="anchors-sha", spec=spec) is True, (
        "force_stale redoes exactly the stale ones: True means current")


@pytest.mark.parametrize("name", GERMAN)
def test_a_changed_definition_still_makes_the_stamp_stale(
        name, tmp_path, monkeypatch):
    """The case that breaks it, so that the test above is not a stamp that
    nothing can move: the same entry shown to the model in other words is
    another question, and the stamp says which. The meaning of an entry of a
    coordinate reaches the model, so it moves the stamp; the meaning of a
    class a value is filed under is shown to no request and moves nothing
    (tests/test_stamp_requests.py), so there the entry's name is changed."""
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    data = json.loads(_spec_path(name).read_text(encoding="utf-8"))
    spec = load_spec(copy.deepcopy(data))
    entry = _first_definition(data, below="axes")
    if entry is not None:
        entry["definition"] += " (und noch etwas)"
    else:
        entry = _first_definition(data)
        assert entry is not None, f"the spec of {name} carries no definition"
        entry["label"] += " (und noch etwas)"
    moved = load_spec(data)
    _stamped(tmp_path, runner._stamp_current("spec-sha", "anchors-sha", spec))
    changed = runner.stale(tmp_path / "plan.stamp.json",
                           runner._stamp_current("spec-sha", "anchors-sha",
                                                 moved))
    assert changed and all(k.startswith(runner.QUESTION_KEYS)
                           for k in changed), changed
    assert runner.already_done("plan", tmp_path, "spec-sha", force_stale=True,
                               anchors_sha="anchors-sha", spec=moved) is False
