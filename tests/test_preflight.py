"""The preflight holds any profile to what a corpus run rests on.

The promise, one sentence: a profile is checked the way the run reads it,
by the spec it names (and no other) AND the prompts in effect for it AND
the passages it says its prompts hold AND the writer of its graph, built
as the run builds it, AND the pin of its vocabulary where it keeps one;
the two profiles of this repository get the checks they always got, by
name and in order; a profile the audit cannot get through is a failed
line and not a traceback; and the command ends 1 when a check fails.

Three lines came after, each with its own promise.

The shapes: every property of the profile's shapes that no parameter asks
AND the profile does not record as left out is a warning, never a failure,
AND a profile with no shapes file is skipped and not warned.

The pin: every class whose definition in the spec is not the pin's, or which
only the pin defines, is a note, never a failure, AND an equal definition
is none.

The field example: the one-line example reply of the field prompt is read by
the reader of the run and every row of it comes out backed, AND the same
reply with a quote that stands in no passage comes out unbacked.

Each AND has its own test, and each test has a profile built to break it.
So has every check on what a spec has to say.
"""
import json

import pytest

from docpipe import profile as profiles
from docpipe.extraction import preflight
from tests.test_default_profile import _bound, _child, clean  # noqa: F401

EX = "https://graph.test/vocab#"


def _spec(graph=True) -> dict:
    raw = {
        "parameters": [
            {"uri": "report_title", "label": "Title",
             "description": "The title of the report as its cover page "
                            "states it.",
             "value_type": "text", "axes": {},
             "example": {"source": "The report Net Zero by 2050 sets out "
                                   "a pathway",
                         "tuples": [{"value": "Net Zero",
                                     "quote": "The report Net Zero by 2050 "
                                              "sets out a pathway"}]},
             "kg": {"node": "report", "max": 1,
                    "property": {"prefix": "ex", "predicate": "title",
                                 "label": "title"}}},
        ],
    }
    if graph:
        raw["graph"] = {
            "base": "https://graph.test/id/", "prefixes": {"ex": EX},
            "nodes": {"report": {"class": "ex:Report", "per": "document"}},
            "links": []}
    return raw


def _project(folder, spec=None, extraction="", *, name="mine", **files):
    """A profile outside the repository that extends the built-in one."""
    files = dict(files)
    if spec is not None:
        files["extraction_spec.json"] = json.dumps(spec)
        extraction = ("from pathlib import Path\n"
                      "SPEC_PATH = Path(__file__).with_name("
                      "'extraction_spec.json')\n" + extraction)
    if extraction:
        files["extraction.py"] = extraction
    return _child(folder, name, **files)


def _rows(name="mine") -> dict:
    return {what: (verdict, detail)
            for _profile, what, verdict, detail in preflight.audit(name)}


# -- the two profiles kept here -----------------------------------------------

def test_the_profiles_of_this_repository_are_checked_as_before(clean):
    """Ninety-six checks over both, by the names they always had and the
    three that came after. A check that is added or dropped changes this
    number and has to say so here."""
    rows = preflight.audit("kwp") + preflight.audit("scenarios")
    failed = [row for row in rows if row[2] == "FAIL"]
    assert not failed, failed
    assert len(rows) == 96
    for name in ("kwp", "scenarios"):
        own = {what: verdict for profile, what, verdict, _d in rows
               if profile == name}
        assert own["field prompt asks one field"] == "ok"
        assert own["rows prompt no longer fixes one parameter"] == "ok"
        assert own["serializer present"] == "ok"
        assert own["every ontology id matches the pin"] == "ok"


def test_the_script_runs_the_two_profiles_kept_here(clean, capsys):
    from scripts import preflight_profiles as script
    assert script.OURS == ["kwp", "scenarios"]
    assert script.main([]) == 0
    printed = capsys.readouterr().out
    assert "=== kwp ===" in printed and "=== scenarios ===" in printed
    assert "96 check(s), 0 failure(s)" in printed
    # and a name given is the one checked
    assert script.main(["default"]) == 1
    assert "=== default ===" in capsys.readouterr().out


# -- the spec the profile names -----------------------------------------------

def test_a_profile_without_a_spec_fails_on_that_and_is_told_what_drafts_one(
        clean, capsys):
    rows = preflight.audit("default")
    assert [(what, verdict) for _p, what, verdict, _d in rows] == [
        ("spec present", "FAIL")]
    assert "docpipe compile spec" in rows[0][3]
    assert preflight.main(["default"]) == 1
    assert "1 check(s), 1 failure(s)" in capsys.readouterr().out


def test_the_spec_is_the_one_the_profile_names_wherever_it_lives(
        tmp_path, clean):
    home = _project(tmp_path, spec=_spec())
    _bound(clean, tmp_path)
    rows = _rows()
    assert rows["spec present"] == (
        "ok", str(home / "extraction_spec.json"))
    assert rows["parameters loaded"] == ("ok", "1 parameter(s)")
    # the same profile with the file gone: said by its path, nothing else run
    (home / "extraction_spec.json").unlink()
    assert list(_rows()) == ["spec present"]
    assert _rows()["spec present"][0] == "FAIL"


# -- the writer of the graph --------------------------------------------------

def test_a_spec_with_a_graph_block_is_written_by_the_generic_writer(
        tmp_path, clean):
    _project(tmp_path, spec=_spec(graph=True))
    _bound(clean, tmp_path)
    verdict, detail = _rows()["serializer present"]
    assert verdict == "ok" and "generic writer" in detail


def test_a_profile_with_neither_writer_nor_graph_block_fails(tmp_path, clean):
    _project(tmp_path, spec=_spec(graph=False))
    _bound(clean, tmp_path)
    verdict, detail = _rows()["serializer present"]
    assert verdict == "FAIL" and "nothing says what the graph is" in detail


def test_a_profile_s_own_writer_is_the_one_found(tmp_path, clean):
    home = _project(tmp_path, spec=_spec(graph=False),
                    **{"kg.py": "def make_serializer(db):\n"
                                "    return lambda name, rows: None\n"})
    _bound(clean, tmp_path)
    verdict, detail = _rows()["serializer present"]
    assert verdict == "ok" and detail == str(home / "kg.py")


def test_a_writer_that_does_not_import_is_a_failure_and_not_a_crash(
        tmp_path, clean):
    _project(tmp_path, spec=_spec(graph=True),
             **{"kg.py": "import a_library_nobody_has\n"})
    _bound(clean, tmp_path)
    verdict, detail = _rows()["serializer present"]
    assert verdict == "FAIL" and "a_library_nobody_has" in detail


# -- the passages a profile says its prompts hold -----------------------------

def test_the_built_in_prompts_hold_the_built_in_passages(tmp_path, clean):
    _project(tmp_path, spec=_spec())
    _bound(clean, tmp_path)
    rows = _rows()
    assert rows["field prompt asks one field"] == ("ok", "")
    # the German regression mark belongs to the German profiles alone
    assert "rows prompt no longer fixes one parameter" not in rows


def test_a_prompt_in_another_language_is_held_to_the_inherited_passage(
        tmp_path, clean):
    """A profile that words the field prompt itself and says nothing about
    it is still checked: with the passage of the profile it extends, which
    its own prompt does not hold."""
    german = "---\ntemperature: 0\nmax_tokens: 4096\n---\nGefragt ist GENAU EIN Feld.\n"
    _project(tmp_path, spec=_spec(),
             **{"prompts/extraction/field.md": german})
    _bound(clean, tmp_path)
    verdict, detail = _rows()["field prompt asks one field"]
    assert verdict == "FAIL"
    assert "not in extraction/field" in detail
    assert "EXACTLY ONE field" in detail


def test_a_profile_says_its_own_passages_in_its_own_language(tmp_path, clean):
    german = "---\ntemperature: 0\nmax_tokens: 4096\n---\nGefragt ist GENAU EIN Feld.\n"
    _project(tmp_path, spec=_spec(),
             extraction="PROMPT_CHECKS = (\n"
                        "    ('field prompt asks one field', "
                        "'extraction/field', 'GENAU EIN Feld', True),\n"
                        "    ('field prompt lost the old rule', "
                        "'extraction/field', 'Gefragt ist', False),\n"
                        "    ('frame prompt says choose', "
                        "'extraction/frame', 'Choose, do not generate', "
                        "True),\n"
                        "    ('frame prompt says nothing of this', "
                        "'extraction/frame', 'a passage it has not', "
                        "True),\n"
                        ")\n",
             **{"prompts/extraction/field.md": german})
    _bound(clean, tmp_path)
    rows = _rows()
    assert rows["field prompt asks one field"] == ("ok", "")
    # a passage that must not be there and is
    verdict, detail = rows["field prompt lost the old rule"]
    assert verdict == "FAIL" and "still in extraction/field" in detail
    # a prompt the fixed checks do not open is opened for the profile's
    assert rows["frame prompt says choose"] == ("ok", "")
    assert rows["frame prompt says nothing of this"][0] == "FAIL"


def test_a_check_that_cannot_be_read_is_named_and_not_run(tmp_path, clean):
    _project(tmp_path, spec=_spec(),
             extraction="PROMPT_CHECKS = (\n"
                        "    ('no flag', 'extraction/field', 'x'),\n"
                        "    ('fine', 'extraction/field', "
                        "'EXACTLY ONE field', True),\n"
                        ")\n")
    _bound(clean, tmp_path)
    rows = _rows()
    broken = [what for what in rows if what.startswith("prompt checks are")]
    assert len(broken) == 1 and rows[broken[0]][0] == "FAIL"
    assert "no flag" in rows[broken[0]][1]
    assert "no flag" not in rows            # not run as a check
    assert rows["fine"] == ("ok", "")


def test_what_counts_as_a_prompt_check():
    good, bad = preflight.prompt_checks([
        ("a", "extraction/rows", "passage", True),
        ["b", "extraction/rows", "passage", False],
        ("c", "extraction/rows", "passage", "yes"),
        ("d", "extraction/rows", "", True),
        "extraction/rows",
    ])
    assert [entry[0] for entry in good] == ["a", "b"]
    assert len(bad) == 3
    assert preflight.prompt_checks(None) == ([], [])


# -- the command --------------------------------------------------------------

def test_the_command_checks_the_profile_in_effect(tmp_path, clean, capsys):
    _project(tmp_path, spec=_spec())
    _bound(clean, tmp_path)
    clean.setenv(profiles.ENV_VAR, "mine")
    # this project never generated the shape it publishes: a hard failure
    assert preflight.main([]) == 1
    printed = capsys.readouterr().out
    assert "=== mine ===" in printed and "X schema present" in printed
    # named on the line, the name wins over the one in effect
    assert preflight.main(["default"]) == 1
    printed = capsys.readouterr().out
    assert "=== default ===" in printed and "=== mine ===" not in printed


def test_the_command_without_any_profile_says_so(clean, capsys):
    clean.delenv(profiles.ENV_VAR, raising=False)
    with pytest.raises(SystemExit) as stopped:
        preflight.main([])
    assert stopped.value.code == 2
    assert "no profile" in capsys.readouterr().err


def test_a_warning_alone_does_not_fail_the_run(capsys):
    assert preflight.report([("p", "soft", "warn", "moved"),
                             ("p", "fine", "ok", "")]) == 0
    assert "! soft" in capsys.readouterr().out
    assert preflight.report([("p", "hard", "FAIL", "")]) == 1
    assert preflight.report([]) == 0


# -- the same checks, by name and in order ------------------------------------

NAMES = [
    "spec present", "parameters loaded", "every axis has a question",
    "units of numeric parameters are disjoint", "the unit question is set",
    "every derived axis hits its own vocabulary",
    "the parameter question is in the spec", "one anchor per question",
    "every axis target carries its question",
    "no anchor for the value itself", "no shrug in the vocabulary",
    "out:unstated is selectable", "prompt extraction/rows",
    "extraction/rows: temperature 0", "extraction/rows: answer room",
    "prompt extraction/field", "extraction/field: temperature 0",
    "extraction/field: answer room", "prompt extraction/queries",
    "prompt extraction/anchors", "field prompt names 'groups'",
    "field prompt names 'answers'", "field prompt names 'value_raw'",
    "field prompt names 'quote'", "field prompt names 'corrections'",
    "field prompt names 'out:unstated'",
    "field prompt keys the reply by field name",
    "field prompt asks one field",
    "field prompt's own example reads back",
    "rows prompt names 'quantities'",
    "rows prompt no longer fixes one parameter",
    "rows prompt shows a text value", "anchors prompt knows the question",
    "serializer present", "jsonschema importable", "schema present",
    "schema current", "vocabulary snapshot present",
    "every ontology id matches the pin", "pin named",
    "labels from the corpus rather than the ontology",
    "definitions agree with the pin",
    "every id family has a file that knows it", "sources refreshed",
    "sources unchanged since reviewed",
    "every axis says what it becomes in the graph",
    "every parameter says what it becomes in the graph",
    "every shape property is asked or left out on purpose",
]
# The checks that only ever warn. Two of them read a file outside the
# repository (what the last refresh of the sources pulled), so what they say
# belongs to the machine and is not pinned.
WARN_ONLY = {
    "labels from the corpus rather than the ontology",
    "definitions agree with the pin",
    "every id family has a file that knows it", "sources refreshed",
    "sources unchanged since reviewed",
    "every axis says what it becomes in the graph",
    "every parameter says what it becomes in the graph",
    "every shape property is asked or left out on purpose",
}


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_profile_kept_here_gets_the_checks_it_always_got(name, clean):
    """By name and in order, and every one that can fail passes. A check
    that is renamed, moved, added or dropped has to be entered here."""
    rows = preflight.audit(name)
    assert [what for _p, what, _v, _d in rows] == NAMES
    assert {profile for profile, _w, _v, _d in rows} == {name}
    for _profile, what, verdict, detail in rows:
        if what in WARN_ONLY:
            assert verdict in ("ok", "warn"), (what, detail)
        else:
            assert verdict == "ok", (what, detail)


# -- the spec, once more: named elsewhere, and not named at all ---------------

def test_the_spec_read_is_the_named_one_and_not_the_one_beside_the_profile(
        tmp_path, clean):
    two = _spec()
    two["parameters"].append({**two["parameters"][0], "uri": "second_title",
                              "label": "Second"})
    elsewhere = tmp_path / "specs" / "named.json"
    elsewhere.parent.mkdir()
    elsewhere.write_text(json.dumps(_spec()), encoding="utf-8")
    _child(tmp_path / "profiles", "mine", **{
        "extraction_spec.json": json.dumps(two),      # a decoy
        "extraction.py": f"SPEC_PATH = {str(elsewhere)!r}\n"})
    _bound(clean, tmp_path / "profiles")
    rows = _rows()
    assert rows["spec present"] == ("ok", str(elsewhere))
    assert rows["parameters loaded"] == ("ok", "1 parameter(s)")


def test_a_spec_the_profile_does_not_name_is_not_a_spec(tmp_path, clean):
    """The run reads `extraction.SPEC_PATH` and nothing else. A file that
    merely lies beside the profile would pass here and be refused there."""
    home = _child(tmp_path, "mine",
                  **{"extraction_spec.json": json.dumps(_spec())})
    _bound(clean, tmp_path)
    rows = preflight.audit("mine")
    assert [(what, verdict) for _p, what, verdict, _d in rows] == [
        ("spec present", "FAIL")]
    assert "names no extraction.SPEC_PATH" in rows[0][3]
    assert str(home / "extraction_spec.json") in rows[0][3]
    assert "not named" in rows[0][3]


# -- what the spec has to say, each with a spec that does not say it ----------

def _numeric(**changes) -> dict:
    """Two numeric parameters that pass; `changes` break one thing."""
    def parameter(uri, unit):
        return {
            "uri": uri, "label": uri.title(),
            "description": "A yearly amount the document states for the "
                           "whole area it plans for.",
            "value_type": "float", "unit_target": unit,
            "units_accepted": {unit: {"factor": 1.0,
                                      "names_period": False}},
            "axes": {"carrier": {"vocabulary": {"ex:Gas": ["natural gas"],
                                                "ex:Oil": ["heating oil"]},
                                 "question": "Which energy carrier?"},
                     "year": {"type": "int", "question": "Which year?"}},
            "example": {"source": f"Natural gas 42 {unit} in 2020",
                        "tuples": [{"value": 42, "unit_raw": unit}]},
            "kg": {"node": "report",
                   "property": {"prefix": "ex", "predicate": uri,
                                "label": uri}}}
    raw = {"unit_question": "Which unit does this number have?",
           "parameter_question": "Which quantity is this number?",
           "parameters": [parameter("demand", "GWh"),
                          parameter("capacity", "MW")]}
    for change in changes.values():
        change(raw)
    return raw


def _break(tmp_path, clean, **changes) -> dict:
    _project(tmp_path, spec=_numeric(**changes))
    _bound(clean, tmp_path)
    return _rows()


def test_the_spec_that_passes_passes(tmp_path, clean):
    rows = _break(tmp_path, clean)
    for what in ("every axis has a question",
                 "units of numeric parameters are disjoint",
                 "the unit question is set",
                 "the parameter question is in the spec",
                 "no shrug in the vocabulary", "out:unstated is selectable"):
        assert rows[what][0] == "ok", (what, rows[what])


def test_an_axis_without_a_question_is_named(tmp_path, clean):
    rows = _break(tmp_path, clean, blank=lambda raw: raw["parameters"][0][
        "axes"]["carrier"].pop("question"))
    assert rows["every axis has a question"] == ("FAIL", "demand.carrier")


def test_a_unit_two_numeric_parameters_share_is_named(tmp_path, clean):
    def share(raw):
        raw["parameters"][1]["units_accepted"]["GWh"] = {
            "factor": 1.0, "names_period": False}
    rows = _break(tmp_path, clean, share=share)
    assert rows["units of numeric parameters are disjoint"] == ("FAIL", "GWh")


def test_numbers_without_the_two_questions_fail(tmp_path, clean):
    rows = _break(tmp_path, clean,
                  unit=lambda raw: raw.pop("unit_question"),
                  parameter=lambda raw: raw.pop("parameter_question"))
    assert rows["the unit question is set"][0] == "FAIL"
    assert rows["the parameter question is in the spec"][0] == "FAIL"


def test_an_entry_that_means_i_do_not_know_is_named(tmp_path, clean):
    def shrug(raw):
        raw["parameters"][0]["axes"]["carrier"]["vocabulary"]["Unknown"] = [
            "not stated"]
    rows = _break(tmp_path, clean, shrug=shrug)
    assert rows["no shrug in the vocabulary"] == (
        "FAIL", "demand.carrier=Unknown")


def test_a_coordinate_and_a_parameter_that_say_nothing_of_the_graph_warn(
        tmp_path, clean):
    rows = _break(tmp_path, clean,
                  mute=lambda raw: raw["parameters"][1].pop("kg"))
    verdict, detail = rows["every axis says what it becomes in the graph"]
    assert verdict == "warn" and "demand.carrier" in detail
    assert rows["every parameter says what it becomes in the graph"] == (
        "warn", "capacity")


# -- the shape the profile publishes ------------------------------------------

def test_a_schema_that_is_not_the_one_of_the_spec_is_stale_and_the_hint_repairs_it(
        tmp_path, clean, capsys):
    """Also for a spec named somewhere else: the command the line names
    reads the spec the profile names, or it could not clear the line."""
    from docpipe.extraction import schema
    elsewhere = tmp_path / "specs" / "named.json"
    elsewhere.parent.mkdir()
    elsewhere.write_text(json.dumps(_spec()), encoding="utf-8")
    home = _child(tmp_path / "profiles", "mine", **{
        "extraction.py": f"SPEC_PATH = {str(elsewhere)!r}\n",
        schema.SCHEMA_NAME: "{}\n"})
    _bound(clean, tmp_path / "profiles")
    rows = _rows()
    assert rows["schema present"] == ("ok", str(home / schema.SCHEMA_NAME))
    verdict, hint = rows["schema current"]
    assert verdict == "FAIL"
    assert hint == "python -m docpipe.extraction.schema mine --write"
    assert schema.main(["mine", "--write"]) == 0
    capsys.readouterr()
    assert _rows()["schema current"] == ("ok", "")


# -- prompts that are not there -----------------------------------------------

def test_a_passage_asked_of_a_prompt_that_does_not_exist_fails(
        tmp_path, clean):
    _project(tmp_path, spec=_spec(),
             extraction="PROMPT_CHECKS = (('ghost says so', "
                        "'extraction/ghost', 'anything', True),)\n")
    _bound(clean, tmp_path)
    verdict, detail = _rows()["ghost says so"]
    assert verdict == "FAIL" and "extraction/ghost" in detail


def _alone(tmp_path, prompts_kept, extraction=""):
    """A profile that extends nothing and has only the prompts named."""
    from docpipe.builtin.default import profile as built_in
    theirs = built_in.PROFILE.prompts_dir / "extraction"
    files = {f"prompts/extraction/{name}.md":
             (theirs / f"{name}.md").read_text(encoding="utf-8")
             for name in prompts_kept}
    files["extraction_spec.json"] = json.dumps(_spec())
    # The copies are the built-in parts files, in the language those are in:
    # a profile that owns a parts file declares the language of it itself.
    files["extraction.py"] = (
        "from pathlib import Path\n"
        "from docpipe.builtin.default.extraction import PHRASES\n"
        "SPEC_PATH = Path(__file__).with_name('extraction_spec.json')\n"
        "CONTRACT_LANGUAGE = 'en'\n"
        + extraction)
    return _child(tmp_path, "alone", extends=None, **files)


def test_a_prompt_the_stage_needs_and_the_profile_lacks_fails_and_the_rest_runs(
        tmp_path, clean):
    _alone(tmp_path, ("rows", "field", "anchors"))
    _bound(clean, tmp_path)
    rows = _rows("alone")
    assert rows["prompt extraction/queries"][0] == "FAIL"
    assert rows["prompt extraction/rows"][0] == "ok"
    assert rows["field prompt names 'groups'"][0] == "ok"
    # the audit got to its last check
    assert "every parameter says what it becomes in the graph" in rows


def test_a_prompt_that_is_missing_fails_every_line_about_it(tmp_path, clean):
    _alone(tmp_path, ("rows", "queries", "anchors"),
           extraction="PROMPT_CHECKS = (('field prompt asks one field', "
                      "'extraction/field', 'EXACTLY ONE field', True),)\n")
    _bound(clean, tmp_path)
    rows = _rows("alone")
    assert rows["prompt extraction/field"][0] == "FAIL"
    assert rows["field prompt names 'groups'"][0] == "FAIL"
    assert rows["field prompt keys the reply by field name"][0] == "FAIL"
    assert rows["field prompt asks one field"][0] == "FAIL"


# -- the generic writer, built as the run builds it ---------------------------

def test_a_graph_block_the_generic_writer_refuses_fails_before_the_harvest(
        tmp_path, clean):
    """What `docpipe compile spec` drafts has a placeholder for the base of
    the graph. The block is there, and no graph can be written from it."""
    draft = _spec()
    draft["graph"]["base"] = "https://example.org/id/"
    _project(tmp_path, spec=draft)
    _bound(clean, tmp_path)
    verdict, detail = _rows()["serializer present"]
    assert verdict == "FAIL" and "placeholder" in detail


# -- the vocabulary module, through the profile -------------------------------

VOCABULARY = (
    "import json\n"
    "from pathlib import Path\n"
    "VOCABULARY_PATH = Path(__file__).with_name('vocabulary.json')\n"
    "def load():\n"
    "    return json.loads(VOCABULARY_PATH.read_text(encoding='utf-8'))\n"
    "def check(spec, snapshot):\n"
    "    return list(snapshot.get('problems') or ())\n"
    "def foreign_labels(spec, snapshot):\n"
    "    return []\n")


def test_the_pin_of_a_project_is_held_against_its_spec(tmp_path, clean):
    home = _project(tmp_path, spec=_spec(), **{
        "vocabulary.py": VOCABULARY,
        "vocabulary.json": json.dumps({
            "pin": {"oeo_version_iri": "https://pin.test/1.0"},
            "problems": ["term x is deprecated"]})})
    _bound(clean, tmp_path)
    rows = _rows()
    assert rows["vocabulary snapshot present"] == (
        "ok", str(home / "vocabulary.json"))
    assert rows["every ontology id matches the pin"] == (
        "FAIL", "term x is deprecated")
    assert rows["pin named"] == ("ok", "https://pin.test/1.0")
    # this module names no sources, so nothing asks what was pulled
    assert "sources refreshed" not in rows


def test_a_pin_that_is_not_there_fails_and_nothing_is_held_against_it(
        tmp_path, clean):
    _project(tmp_path, spec=_spec(), **{"vocabulary.py": VOCABULARY})
    _bound(clean, tmp_path)
    rows = _rows()
    assert rows["vocabulary snapshot present"][0] == "FAIL"
    assert "every ontology id matches the pin" not in rows


def test_a_profile_without_a_pin_is_not_asked_for_one(tmp_path, clean):
    _project(tmp_path, spec=_spec())
    _bound(clean, tmp_path)
    assert "vocabulary snapshot present" not in _rows()


def test_half_a_vocabulary_module_is_said_and_not_run(tmp_path, clean):
    _project(tmp_path, spec=_spec(), **{
        "vocabulary.py": "def check(spec, snapshot):\n    return []\n"})
    _bound(clean, tmp_path)
    rows = _rows()
    verdict, detail = rows["vocabulary module is whole"]
    assert verdict == "FAIL" and "load" in detail and "foreign_labels" in detail
    assert "vocabulary snapshot present" not in rows


# -- a profile the audit cannot get through -----------------------------------

def test_a_name_that_is_no_profile_is_a_failed_line(clean, capsys):
    rows = preflight.audit("no_such_profile")
    assert [(what, verdict) for _p, what, verdict, _d in rows] == [
        ("profile found", "FAIL")]
    assert "no_such_profile" in rows[0][3]
    # and the table of the profile named beside it is still printed
    assert preflight.main(["no_such_profile", "default"]) == 1
    printed = capsys.readouterr().out
    assert "=== no_such_profile ===" in printed
    assert "=== default ===" in printed and "X spec present" in printed


def test_a_profile_the_audit_cannot_finish_fails_and_the_others_are_printed(
        tmp_path, clean, capsys):
    """A profile that stands alone and says none of the sentences of the
    stage: the audit stops where the first one is needed."""
    _child(tmp_path, "mute", extends=None, **{
        "extraction_spec.json": json.dumps(_spec()),
        "extraction.py": "from pathlib import Path\n"
                         "SPEC_PATH = Path(__file__).with_name("
                         "'extraction_spec.json')\n"})
    _bound(clean, tmp_path)
    assert preflight.main(["mute", "default"]) == 1
    printed = capsys.readouterr().out
    assert "X the audit ran to its end" in printed
    assert "PHRASES" in printed
    assert "=== default ===" in printed


def test_a_profile_is_named_on_the_line_by_its_directory_too(
        tmp_path, clean, capsys):
    home = _project(tmp_path / "elsewhere", spec=_spec())
    assert preflight.main([str(home)]) == 1         # no schema written yet
    printed = capsys.readouterr().out
    assert "=== mine ===" in printed and "X schema present" in printed
    assert "profile found" not in printed


# -- the shapes: what nobody asks ---------------------------------------------

SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <https://graph.test/vocab#> .
@prefix shp: <https://graph.test/shapes#> .

shp:ReportShape a sh:NodeShape ;
    sh:targetClass ex:Report ;
    sh:property [ sh:path ex:title ; sh:datatype xsd:string ] ;
    sh:property [ sh:path ex:inventedProperty ; sh:datatype xsd:string ] .
"""
SHAPES_ASKED = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <https://graph.test/vocab#> .
@prefix shp: <https://graph.test/shapes#> .

shp:ReportShape a sh:NodeShape ;
    sh:targetClass ex:Report ;
    sh:property [ sh:path ex:title ; sh:datatype xsd:string ] .
"""
SHAPES_ROW = "every shape property is asked or left out on purpose"
NOTHING_OPEN = ("0 of 2 shape propert(y/ies) nobody asks and the profile "
                "does not record")


def _shaped(tmp_path, clean, extraction="", text=SHAPES, hook=True,
            name="mine"):
    """A project whose profile names a shapes file, written with `text`."""
    shapes = tmp_path / f"{name}.ttl"
    shapes.write_text(text, encoding="utf-8")
    where = (f"def shapes_files():\n    return [Path({str(shapes)!r})]\n"
             if hook else "")
    _project(tmp_path, spec=_spec(), extraction=where + extraction,
             name=name)
    _bound(clean, tmp_path)
    return _rows(name)[SHAPES_ROW]


def test_a_shape_property_nobody_asks_is_a_warning_and_names_its_shape(
        tmp_path, clean):
    pytest.importorskip("rdflib")
    verdict, detail = _shaped(tmp_path, clean)
    # a warning and not a failure: the line stops no run
    assert verdict == "warn"
    assert "report.inventedProperty" in detail
    assert "1 of 2 shape propert" in detail
    # the property the spec asks is not named
    assert "report.title" not in detail


def test_a_shape_property_the_profile_records_is_not_a_warning(
        tmp_path, clean):
    pytest.importorskip("rdflib")
    recorded = ("NOT_EXTRACTED = {('report', 'inventedProperty'): "
                "'nobody reads it'}\n")
    assert _shaped(tmp_path, clean, recorded) == ("ok", NOTHING_OPEN)


def test_a_record_for_another_shape_does_not_cover_this_one(tmp_path, clean):
    """The key is the shape and the property: a label left out of one shape
    is no decision about the same word on a shape that comes later."""
    pytest.importorskip("rdflib")
    elsewhere = ("NOT_EXTRACTED = {('dataset', 'inventedProperty'): "
                 "'nobody reads it'}\n")
    verdict, detail = _shaped(tmp_path, clean, elsewhere)
    assert verdict == "warn" and "report.inventedProperty" in detail


def test_a_record_that_cannot_be_read_covers_nothing_and_is_named(
        tmp_path, clean):
    pytest.importorskip("rdflib")
    broken = ("NOT_EXTRACTED = {'inventedProperty': 'no shape named', "
              "('report', 'inventedProperty'): ''}\n")
    verdict, detail = _shaped(tmp_path, clean, broken)
    assert verdict == "warn"
    assert "report.inventedProperty" in detail
    assert "unreadable NOT_EXTRACTED entries" in detail
    # even where nothing else is open, an unreadable record is said
    verdict, detail = _shaped(tmp_path, clean, broken, text=SHAPES_ASKED,
                              name="again")
    assert verdict == "warn" and detail.startswith("0 of 1 shape")
    assert "unreadable NOT_EXTRACTED entries" in detail


def test_what_counts_as_a_record_of_a_left_out_property():
    good, bad = preflight.not_extracted({
        ("study", "OEO_00000508"): "no contact person is read",
        ("only one",): "one part",
        ("a", "b", "c"): "three parts",
        ("study", ""): "empty part",
        ("study", "OEO_1"): "",
        ("study", "OEO_2"): None,
        "study.OEO_3": "a string",
    })
    assert good == {("study", "OEO_00000508"): "no contact person is read"}
    assert len(bad) == 6
    assert preflight.not_extracted(None) == ({}, [])
    # nothing recorded is nothing, in whatever empty form
    for empty in ({}, [], (), set()):
        assert preflight.not_extracted(empty) == ({}, [])


def test_a_record_that_is_no_mapping_covers_nothing_and_is_named_once():
    """The profile's record is a mapping of (shape, property) to a reason. A
    list of names, a number or a text is no record, and the audit has to be
    able to say so in its line."""
    for broken in (["a", "b"], 5, "text", [("a", "b", "c")], {("a", "b")},
                   [(("study", "OEO_1"), "a reason")]):
        good, bad = preflight.not_extracted(broken)
        assert good == {}, broken
        assert len(bad) == 1 and "not a mapping" in bad[0], broken


def test_a_record_that_is_no_mapping_is_a_warning_and_not_a_traceback(
        tmp_path, clean):
    pytest.importorskip("rdflib")
    verdict, detail = _shaped(tmp_path, clean, "NOT_EXTRACTED = 5\n")
    # the property it should have covered is open, and the record is named
    assert verdict == "warn"
    assert "report.inventedProperty" in detail
    assert ("unreadable NOT_EXTRACTED entries: the record itself is of type "
            "int, not a mapping") in detail


def test_a_profile_without_a_shapes_file_is_skipped_and_not_warned(
        tmp_path, clean):
    # no hook at all
    assert _shaped(tmp_path, clean, hook=False) == (
        "ok", "skipped: the profile names no shapes file")
    # a hook that names no file, and one that names a file that is not there
    empty = "def shapes_files():\n    return []\n"
    assert _shaped(tmp_path, clean, empty, name="two")[0] == "ok"
    gone = ("def shapes_files():\n"
            "    return [Path(__file__).with_name('gone.ttl')]\n")
    verdict, detail = _shaped(tmp_path, clean, gone, name="three")
    assert verdict == "ok" and detail.startswith("skipped: no shapes file")


def test_a_hook_that_does_not_run_and_a_file_that_does_not_parse_warn(
        tmp_path, clean):
    pytest.importorskip("rdflib")
    breaks = "def shapes_files():\n    raise RuntimeError('no cache')\n"
    verdict, detail = _shaped(tmp_path, clean, breaks)
    assert verdict == "warn" and "RuntimeError: no cache" in detail
    verdict, detail = _shaped(tmp_path, clean, name="two",
                              text="this is no turtle at all {{{")
    assert verdict == "warn" and "could not be read" in detail


# -- the pin: definitions -----------------------------------------------------

DEFINITIONS = "definitions agree with the pin"


def _defined(tmp_path, clean, entry, pin_says, name="mine"):
    """A project whose one class has `entry` in the spec and `pin_says`
    in the pin."""
    raw = _numeric()
    raw["parameters"][0]["axes"]["carrier"]["vocabulary"] = {
        "OEO_00000292": entry}
    snapshot = {"pin": {"oeo_version_iri": "https://pin.test/1.0"},
                "problems": [],
                "terms": {"OEO_00000292": {
                    "label": "natural gas", "alt_labels": [],
                    "definition": pin_says, "deprecated": False,
                    "kind": "class", "parents": []}}}
    _project(tmp_path, spec=raw, name=name,
             **{"vocabulary.py": VOCABULARY,
                "vocabulary.json": json.dumps(snapshot)})
    _bound(clean, tmp_path)
    return _rows(name)[DEFINITIONS]


def test_an_equal_definition_is_no_note(tmp_path, clean):
    said = "Natural gas is a gas mixture."
    assert _defined(tmp_path, clean, {"label": "natural gas",
                                      "definition": said}, said) == (
        "ok", "0 class(es) with a rewritten definition, "
              "0 class(es) only the pin defines")


def test_a_definition_that_differs_only_in_its_white_space_is_no_note(
        tmp_path, clean):
    assert _defined(tmp_path, clean, {
        "label": "natural gas",
        "definition": "Natural gas is\n a gas  mixture."},
        "Natural gas is a gas mixture.")[0] == "ok"
    # on the side of the pin too, which wraps its lines as it likes
    assert _defined(tmp_path, clean, {
        "label": "natural gas", "definition": "Natural gas is a gas mixture."},
        "Natural gas is\na gas  mixture.", name="pin")[0] == "ok"


def test_a_rewritten_definition_is_a_note_and_not_a_failure(tmp_path, clean):
    verdict, detail = _defined(
        tmp_path, clean,
        {"label": "natural gas", "definition": "A gas mixture."},
        "Natural gas is a gas mixture of methane and ethane.")
    assert verdict == "warn"
    assert detail.startswith("1 class(es) with a rewritten definition "
                             "(OEO_00000292), 0 class(es)")


def test_a_definition_only_the_pin_has_is_a_note(tmp_path, clean):
    # the short form of an entry carries no definition at all
    verdict, detail = _defined(tmp_path, clean, ["natural gas"],
                               "Natural gas is a gas mixture.")
    assert verdict == "warn"
    assert detail == ("0 class(es) with a rewritten definition, 1 class(es) "
                      "only the pin defines (OEO_00000292)")


def test_a_definition_only_the_spec_has_is_not_a_difference(tmp_path, clean):
    assert _defined(tmp_path, clean, {"label": "natural gas",
                                      "definition": "Ours."}, "")[0] == "ok"


def test_a_profile_without_a_pin_has_no_definition_line(tmp_path, clean):
    _project(tmp_path, spec=_spec())
    _bound(clean, tmp_path)
    assert DEFINITIONS not in _rows()


# -- the field prompt's own example -------------------------------------------

EXAMPLE_ROW = "field prompt's own example reads back"
FRONT = "---\ntemperature: 0\nmax_tokens: 4096\n---\n"
GOOD = ('{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2"], '
        '"value": "Baseline", "value_raw": "the Baseline scenario", '
        '"quote": "In the Baseline scenario, spending is flat until 2030."}], '
        '"answers": {"R3": {"value": "Option B", "value_raw": "Option B", '
        '"quote": "Results for Option B are shown in Figure 4."}}}}}')


def _scenario_spec() -> dict:
    """The spec of `_spec` with a closed `scenario` coordinate."""
    raw = _spec()
    raw["parameters"][0]["axes"] = {"scenario": {
        "vocabulary": {"ex:Base": ["Baseline", "the Baseline scenario"],
                       "ex:B": ["Option B"]},
        "question": "Which scenario is meant?"}}
    return raw


def _example(tmp_path, clean, line, spec=None, name="mine"):
    _project(tmp_path, spec=spec or _spec(), name=name, **{
        "prompts/extraction/field.md":
            FRONT + "Return one object, on one line:\n\n" + line + "\n"})
    _bound(clean, tmp_path)
    return _rows(name)[EXAMPLE_ROW]


def test_the_example_of_the_built_in_prompt_reads_back(tmp_path, clean):
    """The built-in field prompt, over a spec that has no `scenario`: the
    example is read as free text, and the line says so."""
    _project(tmp_path, spec=_spec())
    _bound(clean, tmp_path)
    verdict, detail = _rows()[EXAMPLE_ROW]
    assert verdict == "ok", detail
    assert "3 row(s) read from their quotes, and 3 row(s) unbacked" in detail
    assert "'scenario' is no coordinate of this spec" in detail


def test_the_example_is_read_against_the_list_of_the_spec(tmp_path, clean):
    verdict, detail = _example(tmp_path, clean, GOOD, _scenario_spec())
    assert verdict == "ok", detail
    assert "no coordinate" not in detail
    # an answer the list does not hold is not backed, for the same example
    off = GOOD.replace('"value": "Option B"', '"value": "Gloomy"')
    verdict, detail = _example(tmp_path, clean, off, _scenario_spec(),
                               name="two")
    assert verdict == "FAIL" and "R3: not_an_option" in detail


def test_an_example_whose_answer_is_not_in_its_quote_fails(tmp_path, clean):
    wrong = GOOD.replace('"value_raw": "Option B"',
                         '"value_raw": "Option C"')
    verdict, detail = _example(tmp_path, clean, wrong)
    assert verdict == "FAIL"
    assert "R3: answer_not_in_quote" in detail


def test_an_example_without_a_quote_or_with_a_short_one_fails(
        tmp_path, clean):
    bare = GOOD.replace(', "quote": "Results for Option B are shown in '
                        'Figure 4."', "")
    verdict, detail = _example(tmp_path, clean, bare)
    assert verdict == "FAIL" and "R3: quote_not_in_source" in detail
    short = GOOD.replace('"value_raw": "Option B", "quote": "Results for '
                         'Option B are shown in Figure 4."',
                         '"value_raw": "B", "quote": "B"')
    verdict, detail = _example(tmp_path, clean, short, name="two")
    assert verdict == "FAIL" and "R3: quote_too_short" in detail


def test_an_example_that_is_not_exactly_one_object_fails(tmp_path, clean):
    verdict, detail = _example(tmp_path, clean, GOOD + " and more")
    assert verdict == "FAIL" and "not exactly one JSON object" in detail
    two = ('{"fields": {"scenario": {"answers": {}}, "year": {"answers": '
           '{}}}}')
    verdict, detail = _example(tmp_path, clean, two, name="two")
    assert verdict == "FAIL" and "exactly one field" in detail
    none = '{"fields": {"scenario": {"answers": {}}}}'
    verdict, detail = _example(tmp_path, clean, none, name="three")
    assert verdict == "FAIL" and "answers no row" in detail


def test_an_example_that_only_says_not_stated_carries_nothing_to_back(
        tmp_path, clean):
    only = ('{"fields": {"scenario": {"answers": {"R1": '
            '{"value": "out:unstated"}}}}}')
    verdict, detail = _example(tmp_path, clean, only)
    assert verdict == "FAIL" and "carries a quote" in detail
    # and one that mixes is read on the rows that have a quote
    mixed = GOOD.replace('"answers": {', '"answers": {"R4": '
                         '{"value": "out:unstated"}, ')
    verdict, detail = _example(tmp_path, clean, mixed, name="two")
    assert verdict == "ok", detail
    assert detail.startswith("3 row(s) read")


def test_a_prompt_without_an_example_line_warns_and_does_not_fail(
        tmp_path, clean):
    verdict, detail = _example(tmp_path, clean,
                               'Reply with {"fields": ...} as an object.')
    assert verdict == "warn" and "starts with" in detail
    # a wrapped example is not found, and the line says so
    wrapped = '{\n  "fields": {"scenario": {"answers": {}}}\n}'
    assert _example(tmp_path, clean, wrapped, name="two")[0] == "warn"


def test_every_example_line_of_the_prompt_is_read_and_not_only_the_first(
        tmp_path, clean):
    broken = GOOD.replace('"value_raw": "Option B"',
                          '"value_raw": "Option C"')
    verdict, detail = _example(tmp_path, clean, GOOD + "\n" + broken)
    assert verdict == "FAIL" and "R3: answer_not_in_quote" in detail
    # two good ones are two good ones
    verdict, detail = _example(tmp_path, clean, GOOD + "\n" + GOOD,
                               name="two")
    assert verdict == "ok" and detail.startswith("2 example line(s)")


def test_an_example_the_reader_cannot_walk_is_a_failed_line_and_no_traceback(
        tmp_path, clean):
    """A "groups" that is no list and a group whose "rows" is none: the
    reader raises on both, and the audit must still get to its other lines."""
    for name, line in (
            ("one", '{"fields": {"scenario": {"groups": 5}}}'),
            ("two", '{"fields": {"scenario": {"groups": [{"rows": 5, '
                    '"value": "Baseline", "value_raw": "Baseline", '
                    '"quote": "In the Baseline scenario, spending is flat."'
                    '}]}}}')):
        verdict, detail = _example(tmp_path, clean, line, name=name)
        assert verdict == "FAIL", (name, detail)
        assert "could not walk the example: TypeError" in detail
        # and the profile's lines after it are there
        assert "rows prompt names 'quantities'" in _rows(name)


def test_a_reader_that_backs_an_invented_quote_fails_the_line(
        tmp_path, clean):
    """The first half of the line holds of any reader that backs
    everything. The copy with the invented quote is what can fail it."""
    import importlib

    from docpipe.extraction import fields
    # the module the audit imports, which is not always the one the package
    # holds an attribute for: the `clean` fixture forgets modules
    pipeline = importlib.import_module("docpipe.extraction.pipeline")
    real = pipeline.merge_field

    def lenient(rows, sources, slot, reply, **kwargs):
        real(rows, sources, slot, reply, **kwargs)
        for row in rows:
            row.claim[f"{slot.name}_state"] = fields.READ
        return {"failed": []}

    clean.setattr(pipeline, "merge_field", lenient)
    verdict, detail = _example(tmp_path, clean, GOOD)
    assert verdict == "FAIL"
    assert "a quote that stands in no passage is still read" in detail


def test_an_example_that_quotes_the_invented_passage_cannot_tell_the_copies_apart(
        tmp_path, clean):
    """The copy is only a copy that must fail when its quote stands in no
    passage. An example that prints that very sentence as a quote has made
    the sentence a passage, and the line says so instead of passing."""
    same = GOOD.replace("Results for Option B are shown in Figure 4.",
                        preflight.INVENTED_QUOTE).replace(
        '"value_raw": "Option B"', '"value_raw": "passage"')
    verdict, detail = _example(tmp_path, clean, same)
    assert verdict == "FAIL" and "invented quote stands in a passage" in detail


def test_the_example_lines_are_the_lines_that_open_the_reply():
    text = ('Intro with "fields" in the middle.\n'
            '  {"fields": {"a": {}}}  \n'
            'and {"fields": not at the start}\n'
            '{"fields": {"b": {}}}\n')
    assert preflight.example_lines(text) == ['{"fields": {"a": {}}}',
                                             '{"fields": {"b": {}}}']
    assert preflight.example_lines(None) == []


def test_a_missing_field_prompt_fails_the_example_line_too(tmp_path, clean):
    _alone(tmp_path, ("rows", "queries", "anchors"))
    _bound(clean, tmp_path)
    verdict, detail = _rows("alone")[EXAMPLE_ROW]
    assert verdict == "FAIL" and "no field prompt" in detail


# -- the two helpers on their own ---------------------------------------------

def test_reads_back_says_whether_one_example_line_is_a_reply_the_run_reads(
        clean):
    from docpipe.extraction.spec import load
    clean.setenv(profiles.ENV_VAR, "default")
    spec = load(_scenario_spec())
    ok, detail = preflight.reads_back(GOOD, spec)
    assert ok, detail
    assert detail.startswith("3 row(s) read from their quotes, and 3 row(s)")
    # the same line with a quote the passage does not carry is not backed
    broken = GOOD.replace('"value_raw": "Option B"', '"value_raw": "nothing"')
    ok, detail = preflight.reads_back(broken, spec)
    assert not ok and "R3: answer_not_in_quote" in detail


def test_example_verdict_is_reads_back_with_a_raise_made_into_a_verdict(clean):
    from docpipe.extraction.spec import load
    clean.setenv(profiles.ENV_VAR, "default")
    spec = load(_scenario_spec())
    assert preflight.example_verdict(GOOD, spec)[0] is True
    ok, detail = preflight.example_verdict(
        '{"fields": {"scenario": {"groups": 5}}}', spec)
    assert ok is False and "TypeError" in detail


def test_shapes_verdict_is_ok_when_nothing_is_run_and_a_warning_when_open(
        tmp_path):
    pytest.importorskip("rdflib")

    class Profile:
        def __init__(self, **parts):
            self.parts = parts

        def component(self, module, name):
            return self.parts.get(name)

    raw = _spec()
    assert preflight.shapes_verdict(Profile(), raw)[0] is True
    gone = Profile(shapes_files=lambda: [tmp_path / "gone.ttl"])
    ok, detail = preflight.shapes_verdict(gone, raw)
    assert ok and detail.startswith("skipped")
    (tmp_path / "shapes.ttl").write_text(SHAPES, encoding="utf-8")
    there = Profile(shapes_files=lambda: [tmp_path / "shapes.ttl"])
    ok, detail = preflight.shapes_verdict(there, raw)
    assert not ok and "report.inventedProperty" in detail
    recorded = Profile(shapes_files=lambda: [tmp_path / "shapes.ttl"],
                       NOT_EXTRACTED={("report", "inventedProperty"): "no"})
    assert preflight.shapes_verdict(recorded, raw)[0] is True
