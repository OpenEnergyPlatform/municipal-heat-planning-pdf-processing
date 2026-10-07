"""The review prompt is the core's template with the profile's own parts put in,
and it reads as it did before it was cut into parts.

Promised: the review prompt of a profile is the core's review template of the
profile's language with the profile's parts put in AND nothing else, AND it is,
byte for byte and as the sha256 a stage records, the file it was before it was
composed, AND no profile's file repeats a sentence of the template, AND what the profiles worded differently stays each profile's
own (scenarios words the row note and the unit itself and leaves out the
`_raw` bullet, kwp leaves out the sentence about the language of its texts),
AND the profile's domain parts reach the request word for word, AND the least
length of a quote and the word for "not stated" in it are the code's, AND the
language is that of the profile that owns the parts file, AND a request for a
second reading carries that text and no mark of a template, AND a parts file
that lacks a part, misspells one, words a block that is left out, leaves out a
block that cannot be, or leaves a placeholder open is refused at load with the
prompt, the part, the profile and both files named.

Each AND is its own test below, and each has the case built to break it: a
template with one word moved, a profile file that carries a sentence of the
template, a scenarios file without its overrides, a part that holds `{{x}}`, a
profile with a parts file and no declaration, a part that is deleted or
misspelt.

No model, no GPU.
"""
import hashlib
import importlib
import itertools
import json
import re
import shutil
from pathlib import Path

import pytest

from docpipe import doctor, prompts
from docpipe.extraction import contract, fields, runner, verify
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import ENV_VAR, load_profile
from tests.test_extraction_requests import Recorder

ROOT = Path(__file__).resolve().parent.parent
REVIEW = "extraction/review"

# The review prompt of each profile as its file was before it became a parts
# file: the sha256 of the file (what a stage records for it) and the sha256 of
# the text after its front matter (what a model reads), taken from the files of
# the commit before.
BEFORE = {
    "kwp": ("0ce5d97c928579eb188a25c66be32a4d68f186dc3c23e3909ced130574254d0f",
            "24958c3527565bbe8131bfabc084528a51f37b97a9d598a9d811aaf42059d744"),
    "scenarios": (
        "eb192233451815b20a110705a6125ba13f03cff3e653ec985be1cc275aa881fa",
        "dba4aed711e3e3ba6db6a4acb913904a3462703c1709442827b45bc01ae3b67f"),
    "default": (
        "5e604818f9b2a3ee23aaa9c5026d489e1728ea65ef187ead23a37db5d20cb97c",
        "47c4b30cf97b66414837974c54a2d493d40ac731bbd64fb1d193e078840ffd34"),
}
LANGUAGE = {"kwp": "de", "scenarios": "de", "default": "en"}
OPENING = {"de": "Du bekommst EINEN bereits gelesenen Wert",
           "en": "You receive ONE value that has already been read"}
HOMES = {"kwp": ROOT / "profiles" / "kwp",
         "scenarios": ROOT / "profiles" / "scenarios",
         "default": ROOT / "docpipe" / "builtin" / "default"}
# What each profile words itself, and what it leaves out, as the loader says.
WORDED = {"kwp": ([], ["corpus_language"]),
          "scenarios": (["field_unit", "row_note"], ["field_raw"]),
          "default": ([], [])}
# The parts each profile's file holds: the domain ones and the ones that word
# a block of the template.
PARTS_OF = {"kwp": {"role", "example_reply"},
            "scenarios": {"role", "row_note", "field_unit", "language_note",
                          "example_reply"},
            "default": {"role", "language_note", "example_reply"}}
DOMAIN_PARTS = ("role", "language_note", "example_reply")

# One sentence of each way the profiles differ, and who has it.
ROW_NOTE = {"kwp": "auch wenn es von `row` abweicht",
            "scenarios": "Wiederhole nicht, was dir gezeigt wird",
            "default": "Do not repeat what you are shown"}
RAW_BULLET = "`<name>_raw`"
UNITS_ACCEPTED = "`units_accepted`"
HAS_RAW = {"kwp": True, "scenarios": False, "default": True}
HAS_UNITS_ACCEPTED = {"kwp": True, "scenarios": False, "default": True}
# The sentence about the language of the texts, which kwp does not have.
LANGUAGE_NOTE = {"kwp": None,
                 "scenarios": "Zitiere in der Sprache der Passage.",
                 "default": "Quote in the language of the passage."}

_names = itertools.count(1)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def file_of(name: str) -> str:
    return (HOMES[name] / "prompts" / "extraction" / "review.md").read_text(
        encoding="utf-8")


def part_text(name: str, part: str) -> str:
    """The text of one part of a profile's parts file, as it stands there."""
    body = file_of(name)
    marks = list(re.finditer(r"^<!-- part: (\w+) -->\n", body, re.M))
    for index, mark in enumerate(marks):
        if mark.group(1) == part:
            stop = marks[index + 1].start() if index + 1 < len(marks) \
                else len(body)
            return body[mark.end():stop].strip()
    raise KeyError(part)


def without_part(text: str, part: str) -> str:
    """The parts file with one section taken out."""
    found = re.search(rf"<!-- part: {part} -->\n.*?(?=<!-- part: |\Z)", text,
                      re.S)
    assert found, part
    return text[:found.start()] + text[found.end():]


@pytest.fixture
def make(tmp_path, monkeypatch):
    """Profiles written to disk, each under a name of its own: `build(extends,
    language, review)` returns the loaded profile."""
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))

    def build(*, extends, language=None, review=None):
        name = f"review_{next(_names)}"
        home = tmp_path / name
        write(home / "__init__.py", "")
        write(home / "profile.py",
              "from docpipe.profile import Profile\n"
              f"PROFILE = Profile(name={name!r}, extends={extends!r})\n")
        if language is not None:
            write(home / "extraction.py", f"CONTRACT_LANGUAGE = {language!r}\n")
        if review is not None:
            write(home / "prompts" / "extraction" / "review.md", review)
        importlib.invalidate_caches()           # a folder made a moment ago
        return load_profile(name)

    return build


def refusal(profile) -> prompts.PromptPartsError:
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load(REVIEW, profile)
    return raised.value


def own(make, name: str, review: str):
    """A profile with a parts file of its own that is `name`'s, changed, in the
    language of `name`."""
    return make(extends=name, language=LANGUAGE[name], review=review)


# ---------------------------------------------------------------------------
# It is the text and the sha256 it was
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BEFORE))
def test_the_review_prompt_is_the_text_and_the_sha_it_was_before_it_was_composed(
        name):
    profile = load_profile(name)
    prompt = prompts.load(REVIEW, profile)
    file_sha, text_sha = BEFORE[name]
    assert prompt.sha256 == file_sha
    assert sha(prompt.text) == text_sha
    # what a stage records is the same hash, so no stamp is stale for it
    assert prompts.versions([REVIEW], profile) == {REVIEW: file_sha}
    assert prompt.meta == {"temperature": 0, "max_tokens": 1024}
    assert prompt.composition["template"] == "review"
    assert prompt.composition["language"] == LANGUAGE[name]
    overrides, omitted = WORDED[name]
    assert prompt.composition["overrides"] == overrides
    assert prompt.composition["omitted"] == omitted


def test_that_comparison_fails_when_a_word_of_the_template_moves(
        tmp_path, monkeypatch):
    """Built to fail: the German template with one word changed is another
    prompt for the two German profiles and the same one for the English, and
    the other way round."""
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)

    german = folder / "de" / "review.md"
    text = german.read_text(encoding="utf-8")
    assert text.count("Ein Zitat aus irgendetwas anderem") == 1
    write(german, text.replace("Ein Zitat aus irgendetwas anderem",
                               "Ein Zitat aus etwas anderem"))
    for name in ("kwp", "scenarios"):
        moved = prompts.load(REVIEW, load_profile(name))
        assert moved.sha256 != BEFORE[name][0]
        assert sha(moved.text) != BEFORE[name][1]
        assert "Ein Zitat aus etwas anderem wird verworfen" in moved.text
    assert prompts.load(REVIEW, load_profile("default")).sha256 == \
        BEFORE["default"][0]

    write(german, text)
    english = folder / "en" / "review.md"
    text = english.read_text(encoding="utf-8")
    assert text.count("A quote from anything else") == 1
    write(english, text.replace("A quote from anything else",
                                "A quote from something else"))
    assert prompts.load(REVIEW, load_profile("default")).sha256 != \
        BEFORE["default"][0]
    for name in ("kwp", "scenarios"):
        assert prompts.load(REVIEW, load_profile(name)).sha256 == BEFORE[name][0]


@pytest.mark.parametrize("name", sorted(BEFORE))
def test_a_stamp_from_before_the_review_was_composed_is_current(name):
    """A stage records the sha of the prompt it read; the composed prompt has
    the one the file had, so a record written before is not stale, and one
    that holds another sha is."""
    profile = load_profile(name)
    current = prompts.versions([REVIEW], profile)
    assert prompts.stale({REVIEW: BEFORE[name][0]}, current) == []
    assert prompts.stale({REVIEW: "0" * 64}, current) == [REVIEW]


# ---------------------------------------------------------------------------
# No profile's file repeats a sentence of the template
# ---------------------------------------------------------------------------

def template_sentences(language: str) -> list:
    """The lines of the template that are contract text and nothing else: a
    line with a slot or a fact in it is not one, and the marks of a block are
    not part of a line."""
    text = contract.template_path(language, "review").read_text(
        encoding="utf-8").split("\n---\n", 1)[1]
    lines = [re.sub(r"<!--.*?-->", "", line).strip() for line in text.split("\n")]
    return [line for line in lines
            if len(line) > 40 and "{{" not in line]


def doubled(parts_file: str, language: str) -> list:
    """The sentences of the template that a parts file holds as well."""
    return [line for line in template_sentences(language) if line in parts_file]


def test_the_template_has_sentences_to_hold_the_files_against():
    for language in ("de", "en"):
        assert len(template_sentences(language)) >= 10, language


@pytest.mark.parametrize("name", sorted(BEFORE))
def test_no_sentence_of_the_template_is_written_in_a_profiles_file(name):
    assert doubled(file_of(name), LANGUAGE[name]) == []


def test_that_scan_can_fail():
    """Built to fail: a profile file that holds the template's sentences,
    which is what the files were before they were cut into parts."""
    for name in sorted(BEFORE):
        composed = prompts.load(REVIEW, load_profile(name)).text
        assert len(doubled(composed, LANGUAGE[name])) >= 8, name


@pytest.mark.parametrize("name", sorted(BEFORE))
def test_a_profiles_file_holds_its_domain_parts_and_the_blocks_it_words(name):
    parts = set(re.findall(r"^<!-- part: (\w+) -->$", file_of(name), re.M))
    assert parts == PARTS_OF[name]
    template = contract.read(LANGUAGE[name], "review")
    assert parts - set(template.required + template.optional) == \
        set(WORDED[name][0])


# ---------------------------------------------------------------------------
# What the profiles worded differently stays each profile's own
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BEFORE))
def test_each_profile_keeps_the_sentences_it_had(name):
    text = prompts.load(REVIEW, load_profile(name)).text
    for who, sentence in ROW_NOTE.items():
        assert (sentence in text) is (who == name), (name, who)
    assert (RAW_BULLET in text) is HAS_RAW[name]
    assert (UNITS_ACCEPTED in text) is HAS_UNITS_ACCEPTED[name]
    for who, sentence in LANGUAGE_NOTE.items():
        if sentence:
            assert (sentence in text) is (who == name), (name, who)
    assert ("language_note" in PARTS_OF[name]) is bool(LANGUAGE_NOTE[name])


def test_scenarios_without_its_overrides_would_read_the_templates_sentences(make):
    """Built to fail: the same file without the part that words the row note,
    without the one that words the unit, and without the omission of the
    `_raw` bullet. Each puts the template's own sentence back, so each is what
    keeps the scenarios request as it was."""
    text = file_of("scenarios")
    plain = prompts.load(REVIEW, load_profile("scenarios")).text

    no_note = prompts.load(REVIEW, own(make, "scenarios",
                                       without_part(text, "row_note")))
    assert ROW_NOTE["kwp"] in no_note.text
    assert ROW_NOTE["scenarios"] not in no_note.text

    no_unit = prompts.load(REVIEW, own(make, "scenarios",
                                       without_part(text, "field_unit")))
    assert UNITS_ACCEPTED in no_unit.text and UNITS_ACCEPTED not in plain

    no_omission = prompts.load(REVIEW, own(make, "scenarios", text.replace(
        "without: [field_raw]\n", "", 1)))
    assert RAW_BULLET in no_omission.text and RAW_BULLET not in plain
    assert no_omission.composition["omitted"] == []


def test_the_raw_bullet_can_be_put_back_for_scenarios_and_only_that_one():
    """What switching the omission off would add: the render tool shows it."""
    prompt = prompts.load(REVIEW, load_profile("scenarios"))
    assert list(prompt.composition["what_if"]) == ["field_raw"]
    back = prompt.composition["what_if"]["field_raw"]
    assert RAW_BULLET in back and RAW_BULLET not in prompt.text
    assert back.replace(
        next(line for line in back.split("\n") if RAW_BULLET in line) + "\n",
        "") == prompt.text


def test_kwp_leaves_out_the_sentence_about_the_language_of_its_texts(make):
    """Built to fail: kwp's file with a sentence of that kind is refused,
    because the place it would stand in is left out, and the loader says
    which block that is."""
    text = file_of("kwp")
    given = text.rstrip("\n") + "\n\n<!-- part: language_note -->\nDie Texte sind deutsch.\n"
    problem = refusal(own(make, "kwp", given))
    assert problem.part == "language_note"
    assert "corpus_language" in str(problem)
    # the same sentence is where it belongs once the block is not left out
    taken = given.replace("without: [corpus_language]\n", "", 1)
    prompt = prompts.load(REVIEW, own(make, "kwp", taken))
    assert "\n\nDie Texte sind deutsch.\n\nTragen die zwei Passagen" in prompt.text


# ---------------------------------------------------------------------------
# The domain parts reach the request word for word
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BEFORE))
def test_the_profiles_domain_parts_reach_the_prompt_word_for_word(name, make):
    prompt = prompts.load(REVIEW, load_profile(name))
    held = [part for part in DOMAIN_PARTS if part in PARTS_OF[name]]
    assert held and "example_reply" in held and "role" in held
    for part in held:
        assert f"\n{part_text(name, part)}\n" in "\n" + prompt.text, (name, part)
    # a changed letter in a domain part is a changed prompt, and nothing else
    for part in held:
        text = file_of(name)
        old = part_text(name, part)
        changed = own(make, name, text.replace(old, old.replace("e", "E", 1), 1))
        moved = prompts.load(REVIEW, changed)
        assert moved.sha256 != prompt.sha256, (name, part)
        assert moved.text.count("\n") == prompt.text.count("\n")
        assert len(moved.text) == len(prompt.text)


def test_the_check_that_a_domain_part_stands_verbatim_can_fail():
    """Built to fail: the prompt of one profile does not hold the role of
    another."""
    kwp = prompts.load(REVIEW, load_profile("kwp")).text
    for other in ("scenarios", "default"):
        assert f"\n{part_text(other, 'role')}\n" not in "\n" + kwp


# ---------------------------------------------------------------------------
# The least length of a quote and "not stated" are the code's
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, said", [
    ("kwp", "mindestens {} Zeichen"),
    ("scenarios", "mindestens {} Zeichen"),
    ("default", "at least {} characters")])
def test_the_least_length_of_a_quote_is_the_codes_number(name, said,
                                                         monkeypatch):
    profile = load_profile(name)
    before = prompts.load(REVIEW, profile)
    assert said.format(verify.MIN_QUOTE_CHARS) in before.text
    monkeypatch.setattr(verify, "MIN_QUOTE_CHARS", 12)
    moved = prompts.load(REVIEW, profile)
    assert said.format(12) in moved.text
    assert said.format(8) not in moved.text
    assert moved.sha256 != before.sha256


@pytest.mark.parametrize("name", sorted(BEFORE))
def test_the_word_for_not_stated_is_the_codes_word(name, monkeypatch):
    profile = load_profile(name)
    before = prompts.load(REVIEW, profile)
    assert f"`{fields.UNSTATED}`" in before.text
    monkeypatch.setattr(fields, "UNSTATED", "out:none")
    moved = prompts.load(REVIEW, profile)
    assert "`out:none`" in moved.text
    assert "out:unstated" not in moved.text
    assert moved.sha256 != before.sha256


# ---------------------------------------------------------------------------
# The language is that of the profile that owns the parts file
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_review_prompt_is_in_the_language_of_its_profile(name):
    text = prompts.load(REVIEW, load_profile(name)).text
    other = OPENING["en" if LANGUAGE[name] == "de" else "de"]
    assert OPENING[LANGUAGE[name]] in text
    assert other not in text


def test_a_child_reads_the_parts_it_inherits_in_the_language_of_their_owner(
        make):
    """Built to fail: a child that declares the other language still gets the
    parts of the profile it extends in the language those are in."""
    german = make(extends="kwp", language="en")
    prompt = prompts.load(REVIEW, german)
    assert prompt.path == HOMES["kwp"] / "prompts" / "extraction" / "review.md"
    assert prompt.composition["language"] == "de"
    assert OPENING["de"] in prompt.text
    assert prompt.sha256 == BEFORE["kwp"][0]

    english = make(extends="default", language="de")
    prompt = prompts.load(REVIEW, english)
    assert prompt.composition["language"] == "en"
    assert OPENING["en"] in prompt.text
    assert prompt.sha256 == BEFORE["default"][0]


def test_a_child_with_parts_of_its_own_says_its_language_itself(make):
    mine = make(extends="default", language="de", review=file_of("kwp"))
    prompt = prompts.load(REVIEW, mine)
    assert prompt.path.parent.parent.parent.name == mine.name
    assert OPENING["de"] in prompt.text
    assert prompt.sha256 == BEFORE["kwp"][0]
    # the same file with no declaration is refused, and says what there is
    silent = make(extends="default", review=file_of("kwp"))
    problem = refusal(silent)
    assert "CONTRACT_LANGUAGE" in str(problem)
    assert str(contract.languages()) in str(problem)
    assert problem.prompt_id == REVIEW and problem.profile == silent.name
    # and one that names a language the core has no templates for
    elvish = make(extends="default", language="xx", review=file_of("kwp"))
    assert str(contract.languages()) in str(refusal(elvish))


# ---------------------------------------------------------------------------
# A request for a second reading carries the text and no mark of a template
# ---------------------------------------------------------------------------

def reviewed(monkeypatch, name: str) -> list:
    """The requests one profile's second reading sends, for a made-up value."""
    monkeypatch.setenv(ENV_VAR, name)
    spec = load_spec(json.loads((HOMES[name] / "extraction_spec.json")
                                .read_text(encoding="utf-8")))
    client = Recorder()
    monkeypatch.setattr(runner, "_client", lambda: client)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(runner, "RETRY_TEMPERATURE_STEP", 0.0)
    monkeypatch.setattr(runner, "CODE_ROUNDS", 2)
    parameter = spec.parameters[0]
    shown = [Source("table", 1, "| Erdgas | 1 |", {"document_id": 7, "page": 1}),
             Source("section", 2, "Das Zielszenario 2045.",
                    {"document_id": 7, "page": 2})]
    runner.make_review_asker()(
        {"value": 1, "quote": "| Erdgas | 1 |", "unit": "MWh/a",
         "parameter": parameter.uri}, shown, parameter,
        list(fields.asked_slots(parameter)))
    return client.take()


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_request_for_a_review_carries_the_composed_text_and_no_mark(
        name, monkeypatch):
    sent = reviewed(monkeypatch, name)
    assert sent, "no request was sent"
    prompt = prompts.load(REVIEW, load_profile(name))
    for request in sent:
        system = request["messages"][0]
        assert system == {"role": "system", "content": prompt.text}
        assert sha(system["content"]) == BEFORE[name][1]
        assert "{{" not in system["content"] and "<!--" not in system["content"]
        assert request["temperature"] == 0.0


def test_a_part_with_a_placeholder_open_is_refused_before_any_request(
        make, monkeypatch):
    """Built to fail: the second reading of a profile whose part holds `{{x}}`
    is not made, so no request can carry it."""
    client = Recorder()
    monkeypatch.setattr(runner, "_client", lambda: client)
    text = file_of("kwp")
    old = part_text("kwp", "role")
    profile = own(make, "kwp", text.replace(old, old + " {{x}}", 1))
    monkeypatch.setenv(ENV_VAR, profile.name)
    with pytest.raises(prompts.PromptPartsError) as raised:
        runner.make_review_asker()
    assert "{{x}}" in str(raised.value) and raised.value.part == "role"
    assert raised.value.prompt_id == REVIEW
    assert raised.value.profile == profile.name
    assert client.sent == []


# ---------------------------------------------------------------------------
# A parts file that is wrong is refused, and everything is named
# ---------------------------------------------------------------------------

def named(problem, profile, part, language="de") -> None:
    """The refusal names the prompt, the part, the profile and both files."""
    assert problem.prompt_id == REVIEW
    assert problem.profile == profile.name
    assert problem.part == part
    files = dict(problem.files)
    assert files["parts file"] == str(
        profile.prompts_dir / "extraction" / "review.md")
    assert files["template"] == str(contract.template_path(language, "review"))


@pytest.mark.parametrize("part", ["role", "example_reply"])
def test_a_parts_file_without_a_required_part_is_refused_and_everything_is_named(
        make, part):
    profile = own(make, "kwp", without_part(file_of("kwp"), part))
    problem = refusal(profile)
    assert f"{part!r} is missing" in str(problem)
    named(problem, profile, part)
    # the same file with its part is the profile's prompt
    whole = own(make, "kwp", file_of("kwp"))
    assert prompts.load(REVIEW, whole).sha256 == BEFORE["kwp"][0]


def test_a_misspelt_part_is_refused_and_the_near_one_named(make):
    profile = own(make, "scenarios", file_of("scenarios").replace(
        "part: row_note", "part: row_not", 1))
    problem = refusal(profile)
    assert "did you mean 'row_note'" in str(problem)
    assert problem.part == "row_not"
    assert problem.prompt_id == REVIEW and problem.profile == profile.name


def test_a_block_that_cannot_be_left_out_is_refused(make):
    profile = own(make, "kwp", file_of("kwp").replace(
        "without: [corpus_language]", "without: [corpus_language, row_note]", 1))
    problem = refusal(profile)
    assert "'row_note' cannot be left out" in str(problem)
    named(problem, profile, "row_note")


def test_a_block_that_is_left_out_and_worded_is_refused(make):
    """The raw bullet is left out for scenarios, so a part of that name says
    two things about one place."""
    given = file_of("scenarios").rstrip("\n") + (
        "\n\n<!-- part: field_raw -->\n- `<name>_raw`, wie das Dokument es "
        "schreibt,\n")
    profile = own(make, "scenarios", given)
    problem = refusal(profile)
    assert "left out and worded" in str(problem)
    named(problem, profile, "field_raw")
    # worded and not left out, it is the profile's sentence in the template's place
    worded = given.replace("without: [field_raw]\n", "", 1)
    text = prompts.load(REVIEW, own(make, "scenarios", worded)).text
    assert "- `<name>_raw`, wie das Dokument es schreibt,\n- bei einer Zahl" in text


@pytest.mark.parametrize("part", ["role", "row_note", "example_reply"])
def test_a_part_with_an_open_placeholder_is_refused(make, part):
    name = "scenarios"
    old = part_text(name, part)
    profile = own(make, name, file_of(name).replace(old, old + " {{x}}", 1))
    problem = refusal(profile)
    assert "{{x}}" in str(problem)
    named(problem, profile, part)


def test_the_doctor_reads_the_review_prompt_of_a_profile_and_fails_a_broken_one(
        make):
    for name in ("kwp", "scenarios"):
        lines = doctor._prompts_of("extract", load_profile(name))
        assert [line.status for line in lines] == [doctor.OK], name
    broken = own(make, "kwp", without_part(file_of("kwp"), "example_reply"))
    (line,) = doctor._prompts_of("extract", broken)
    assert line.status == doctor.FAIL
    assert "example_reply" in line.detail and REVIEW in line.detail
    assert "<!-- part: name -->" in line.hint


# ---------------------------------------------------------------------------
# The template is held in both languages
# ---------------------------------------------------------------------------

def test_the_review_template_is_held_in_both_languages_with_one_shape():
    from tests.test_contract_templates import EN_ONLY, folder_problems
    examined, problems = folder_problems(EN_ONLY)
    assert "review" in examined
    assert problems == []
    assert ("de", "review") in contract.available()
    assert ("en", "review") in contract.available()
    assert "review" not in EN_ONLY, "the two languages say the same here"
    de, en = contract.read("de", "review"), contract.read("en", "review")
    assert de.shape() == en.shape()
    assert de.required == ("role", "example_reply")
    assert de.optional == ("language_note",)
    assert set(de.blocks) == {"row_note", "field_raw", "field_unit",
                              "corpus_language"}
    assert set(de.omittable) == {"field_raw", "corpus_language"}
    assert de.rules == ()


def test_that_check_fails_for_an_english_template_that_lacks_a_block(tmp_path,
                                                                     monkeypatch):
    """Built to fail: the English template with the raw bullet's block cut
    out of the declaration and the text."""
    from tests.test_contract_templates import folder_problems
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    path = folder / "en" / "review.md"
    text = path.read_text(encoding="utf-8")
    cut = re.sub(r"<!-- block: field_raw -->\n.*?<!-- /block -->\n", "", text,
                 flags=re.S)
    assert cut != text
    cut = cut.replace("blocks: [row_note, field_raw, field_unit, "
                      "corpus_language]",
                      "blocks: [row_note, field_unit, corpus_language]")
    cut = cut.replace("omittable: [field_raw, corpus_language]",
                      "omittable: [corpus_language]")
    write(path, cut)
    _, problems = folder_problems({})
    assert "review: blocks ['field_raw'] are in de and not in en" in problems
    assert "review: omittable ['field_raw'] are in de and not in en" in problems
