"""The five extraction prompts are composed from the core, and the whole holds.

Promised: the rows, field, frame, review and example prompt of kwp, scenarios
and the built-in profile are each the core's template of the profile's language
with the profile's parts put in AND the German and the English template of each
of the five ask the same of a profile AND no composed text of the three
profiles carries a placeholder or a mark of a template, and the English ones
hold no German AND the checks the preflight makes on the prompts hold on the
composed text of all three AND a stamp written before the prompts were composed
makes no document stale, while one whose question moved still does.

Each AND is its own test below, and each has a case built to break it: a plain
file among the five, a template missing in one language, a text with a mark or
with German words in it, a prompt that lost the key a check asks for, a stamp
that is the one of today, a stamp whose question moved.

The stamp is the other end of the last comparison: the fixture holds the sha256
each prompt had in the stamp before the contract moved into the core, which
today's files cannot give. No model, no GPU.
"""
import json
import re
import shutil
from pathlib import Path

import pytest

from docpipe import prompts
from docpipe.extraction import contract, fields, preflight, runner
from docpipe.profile import load_profile
from tests.test_contract_templates import EN_ONLY, folder_problems, german_in
from tests.test_default_profile import clean  # noqa: F401
from tests.test_extraction_topup import SPEC
from tests.test_prompt_parts import holds_a_mark

ROOT = Path(__file__).resolve().parent.parent
BEFORE = ROOT / "tests" / "fixtures" / "prompt_shas_before_composition.json"
FIVE = ("rows", "field", "frame", "review", "example")
LANGUAGE = {"kwp": "de", "scenarios": "de", "default": "en"}
SPEC_SHA, ANCHORS_SHA = "a" * 64, "b" * 16


def load(name: str, stage: str):
    return prompts.load(f"extraction/{stage}", load_profile(name))


# ---------------------------------------------------------------------------
# Each of the five is the template of the profile's language with its parts
# ---------------------------------------------------------------------------

def uncomposed(profile, stages, language: str) -> list:
    """The prompts among *stages* that are not composed from the template of
    their own name in this language."""
    found = []
    for stage in stages:
        composition = prompts.load(f"extraction/{stage}", profile).composition
        if (composition is None or composition["template"] != stage
                or composition["language"] != language):
            found.append(stage)
    return found


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_five_prompts_of_a_profile_are_composed_in_its_language(name):
    assert uncomposed(load_profile(name), FIVE, LANGUAGE[name]) == []


def test_a_plain_file_among_the_five_and_another_language_are_found():
    """Built to fail: a prompt that names no template is not composed, and the
    German profile asked for English is not in that language."""
    kwp = load_profile("kwp")
    assert uncomposed(kwp, ("rows", "phrase", "queries"), "de") == [
        "phrase", "queries"]
    assert uncomposed(kwp, FIVE, "en") == list(FIVE)


# ---------------------------------------------------------------------------
# The two languages ask the same of a profile, for all five
# ---------------------------------------------------------------------------

def templates_missing(languages=("de", "en")) -> dict:
    """{template: the languages that have none} for the five."""
    return {stage: [lang for lang in languages
                    if stage not in contract.template_names(lang)]
            for stage in FIVE
            if any(stage not in contract.template_names(lang)
                   for lang in languages)}


def test_each_of_the_five_templates_is_in_both_languages_and_asks_the_same():
    assert templates_missing() == {}
    examined, problems = folder_problems(EN_ONLY)
    assert set(FIVE) <= set(examined)
    assert problems == []


def test_a_template_of_the_five_missing_in_one_language_is_found(
        tmp_path, monkeypatch):
    """Built to fail: the core's templates with the English review template
    gone, and with a block cut out of the German field template."""
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    (folder / "en" / "review.md").unlink()
    assert templates_missing() == {"review": ["en"]}
    _, problems = folder_problems(EN_ONLY)
    assert "template 'review' is in de only" in problems


def test_a_block_that_one_language_does_not_have_is_found(tmp_path, monkeypatch):
    """Built to fail: the German rows template with the block of the normal
    case taken out of its declaration and its text, which the English one
    still has."""
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    path = folder / "de" / "rows.md"
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    cut = text.replace("<!-- block: normal_case -->", "").replace(
        "normal_case, ", "", 2)
    cut = cut.replace(" und das ist der Normalfall<!-- /block -->",
                      " und das ist der Normalfall", 1)
    assert cut != text and "block: normal_case" not in cut
    path.write_bytes(cut.encode("utf-8"))
    _, problems = folder_problems(EN_ONLY)
    assert "rows: blocks ['normal_case'] are in en and not in de, and not " \
        "listed in EN_ONLY" in problems


# ---------------------------------------------------------------------------
# No mark of a template is left, and the English text holds no German
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(LANGUAGE))
@pytest.mark.parametrize("stage", FIVE)
def test_no_composed_text_of_the_five_holds_a_mark_of_a_template(name, stage):
    assert not holds_a_mark(load(name, stage).text)


def test_a_text_with_a_mark_is_found():
    """Built to fail: an open placeholder and a comment of a template."""
    assert holds_a_mark("Answer in {{unstated}} words.")
    assert holds_a_mark("Rule one <!-- rule: value --> says.")
    assert not holds_a_mark("Answer with out:unstated.")


@pytest.mark.parametrize("stage", FIVE)
def test_the_english_prompts_hold_no_german(stage):
    assert german_in(load("default", stage).text) == []
    template = contract.template_path("en", stage).read_text(encoding="utf-8")
    assert german_in(template) == []


def test_german_in_an_english_prompt_is_found():
    """Built to fail: a German sentence in an English text."""
    assert german_in("Return only the answer, und nichts weiter.") == ["und"]
    assert german_in(load("kwp", "rows").text) != []


# ---------------------------------------------------------------------------
# What the preflight asks of the prompts holds on the composed text
# ---------------------------------------------------------------------------

FIELD_KEYS = ("groups", "answers", "value_raw", "quote", "corrections",
              "fields", fields.UNSTATED)


def prompt_problems(checks, texts: dict) -> list:
    """What the preflight finds wrong in prompt texts: the keys the field
    prompt names, the flat reply it must not describe, and the passages the
    profile says its prompts hold (`PROMPT_CHECKS`, as the preflight reads
    them)."""
    entries, malformed = preflight.prompt_checks(checks)
    problems = [f"malformed check {bad}" for bad in malformed]
    field = texts.get("extraction/field", "")
    problems += [f"field prompt does not name {key!r}"
                 for key in FIELD_KEYS if f'"{key}"' not in field]
    if '"field":' in field:
        problems.append("field prompt describes the flat reply")
    for what, where, passage, has_to_be_there in entries:
        if (passage in texts.get(where, "")) != has_to_be_there:
            problems.append(what)
    return problems


def texts_of(name: str) -> dict:
    return {f"extraction/{stage}": load(name, stage).text
            for stage in ("rows", "field")}


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_checks_the_preflight_makes_on_the_prompts_hold_for_each_profile(name):
    checks = load_profile(name).component("extraction", "PROMPT_CHECKS")
    assert checks, "a profile that checks nothing holds nothing"
    assert prompt_problems(checks, texts_of(name)) == []


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_the_preflight_of_the_two_corpus_profiles_passes_on_the_composed_text(
        name, clean):
    rows = preflight.audit(name)
    assert [row for row in rows if row[2] == "FAIL"] == []
    own = {what: verdict for _p, what, verdict, _d in rows}
    assert own["field prompt asks one field"] == "ok"
    assert own["rows prompt no longer fixes one parameter"] == "ok"
    assert own[f"field prompt names {fields.UNSTATED!r}"] == "ok"


def test_a_prompt_that_lost_what_a_check_asks_for_is_found():
    """Built to fail: the German field prompt without the words that say it
    asks one field, without the key of the corrections, and in the flat
    reply; and the rows prompt with the old fixed parameter in it."""
    checks = load_profile("kwp").component("extraction", "PROMPT_CHECKS")
    texts = texts_of("kwp")
    flat = texts["extraction/field"].replace("GENAU EIN Feld", "ein Feld")
    flat = flat.replace('"corrections"', "'corrections'")
    flat += '\n{"field": "x"}\n'
    problems = prompt_problems(checks, {**texts, "extraction/field": flat,
                                        "extraction/rows":
                                        texts["extraction/rows"]
                                        + '\n"parameter": die gesuchte Größe'})
    assert "field prompt asks one field" in problems
    assert "rows prompt no longer fixes one parameter" in problems
    assert "field prompt does not name 'corrections'" in problems
    assert "field prompt describes the flat reply" in problems


def test_the_german_field_template_holds_what_the_preflight_asks_of_it():
    text = contract.template_path("de", "field").read_text(encoding="utf-8")
    assert "GENAU EIN Feld" in text
    assert "EINER der gezeigten Quellen" in text
    assert '"parameter": die gesucht' not in text and '"field":' not in text
    for key in ("groups", "answers", "value_raw", "quote", "corrections",
                "fields"):
        assert f'"{key}"' in text, key
    assert "{{unstated}}" in text, "the word for not stated is the code's"


# ---------------------------------------------------------------------------
# A stamp from before the prompts were composed makes no document stale
# ---------------------------------------------------------------------------

STAMPED = ("queries", "anchors", "rows", "field", "phrase", "frame")
COMPOSED_NOW = {"rows", "field", "frame"}


def before_stamp(name: str, today: dict) -> dict:
    """The stamp a run of this profile wrote before the prompts were composed:
    today's keys with the sha256 each prompt then had."""
    shas = json.loads(BEFORE.read_text(encoding="utf-8"))[name]
    return {**today, **{f"extraction/{stage}": shas[f"extraction/{stage}"]
                        for stage in STAMPED},
            "review/prompt": shas["extraction/review"],
            "review/model": "a-model"}


def moved(before: dict, today: dict, name: str) -> set:
    """The prompts whose sha256 is not the one the stamp holds."""
    now = {f"extraction/{stage}": load(name, stage).sha256 for stage in STAMPED}
    now["review/prompt"] = load(name, "review").sha256
    return {key.split("/")[1] for key, sha in now.items()
            if before.get(key) != sha}


@pytest.fixture(params=["kwp", "scenarios"])
def profile_name(request, monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", request.param)
    runner.UNSERVED.clear()
    yield request.param
    runner.UNSERVED.clear()


def stamp_at(folder: Path, stamp: dict, name: str = "plan") -> Path:
    path = folder / f"{name}.stamp.json"
    path.write_text(json.dumps(stamp), encoding="utf-8")
    (folder / f"{name}.jsonl").write_text("{}\n", encoding="utf-8")
    return path


def test_the_stamp_before_the_prompts_were_composed_holds_other_prompts_than_now(
        profile_name):
    """The precondition of the tests below, held on its own so that they
    cannot pass over two stamps that are the same: the three composed prompts
    have another sha256 than the stamp's, and nothing else has."""
    today = runner._stamp_current(SPEC_SHA, ANCHORS_SHA, SPEC)
    before = before_stamp(profile_name, today)
    assert moved(before, today, profile_name) == COMPOSED_NOW


def test_that_precondition_can_fail_a_stamp_of_today_has_nothing_moved(
        profile_name):
    today = runner._stamp_current(SPEC_SHA, ANCHORS_SHA, SPEC)
    same = {**today, "review/prompt": load(profile_name, "review").sha256}
    assert moved(same, today, profile_name) == set()


def test_the_search_prompts_are_the_ones_the_stamp_recorded(profile_name):
    """The sentences the anchors are made of and the cache key that hashes the
    anchors prompt are not touched: their sha256 is the recorded one."""
    shas = json.loads(BEFORE.read_text(encoding="utf-8"))[profile_name]
    for stage in ("queries", "anchors", "phrase"):
        assert load(profile_name, stage).sha256 == shas[f"extraction/{stage}"]
    assert load(profile_name, "review").sha256 == shas["extraction/review"]


def test_no_document_of_a_stamp_from_before_is_stale(profile_name, tmp_path):
    today = runner._stamp_current(SPEC_SHA, ANCHORS_SHA, SPEC)
    path = stamp_at(tmp_path, before_stamp(profile_name, today))
    assert runner.stale(path, today) == []
    for force_stale in (False, True):
        assert runner.already_done(
            "plan", tmp_path, SPEC_SHA, force_stale=force_stale,
            anchors_sha=ANCHORS_SHA, spec=SPEC) is True
    assert runner.documents_to_harvest(
        [(1, "plan.pdf")], tmp_path, SPEC_SHA, anchors_sha=ANCHORS_SHA,
        spec=SPEC) == []


def test_a_stamp_from_before_whose_question_moved_is_still_stale(
        profile_name, tmp_path):
    """Built to fail: the same stamp with one question that is not today's is
    stale in that key and in no other, so the comparison does look at a stamp
    that carries the old prompts."""
    today = runner._stamp_current(SPEC_SHA, ANCHORS_SHA, SPEC)
    axis = next(key for key in today if key.startswith("axis/"))
    path = stamp_at(tmp_path, {**before_stamp(profile_name, today),
                               axis: "moved"})
    assert runner.stale(path, today) == [axis]
    assert runner.documents_to_harvest(
        [(1, "plan.pdf")], tmp_path, SPEC_SHA, force_stale=True,
        anchors_sha=ANCHORS_SHA, spec=SPEC) == [(1, "plan.pdf")]
