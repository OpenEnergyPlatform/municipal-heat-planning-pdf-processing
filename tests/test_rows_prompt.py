"""The rows prompt is the core's template with the profile's parts put in.

Promised: the rows prompt of a profile is the core's rows template of the
profile's language with the profile's parts put in AND no parts file repeats
a sentence of the template AND every part of the profile
reaches the request word for word AND no profile gains a rule it did not have
and none loses one, what it leaves out stays out and what it worded itself
stays its own AND "source" and "quote" are two numbered rules in every profile
AND the numbers are gapless and every reference to a rule points at the rule it
means AND the least length of a quote is the code's number and not a typed one
AND the language is that of the profile that owns the parts file AND a request
for rows carries that text and no mark of a template AND a parts file that
lacks a part, misspells one, leaves a placeholder open or leaves out what cannot
be left out is refused at load with the prompt, the part, the profile and both
files named AND its fingerprint is the sha256 of the text sent, so no stamp
goes stale for it.

Each AND is its own test below, and each has the case built to break it: a part
changed by a letter, a template sentence copied into a parts file, a profile
that does not leave out what it lacked, a block left out under a reference, a
patched least length, a part that holds `{{x}}`.

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
from _pytest.monkeypatch import MonkeyPatch

from docpipe import doctor, prompts
from docpipe.extraction import contract, runner, verify
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import ENV_VAR, load_profile

ROOT = Path(__file__).resolve().parent.parent
ROWS = "extraction/rows"
NAMES = ("kwp", "scenarios", "default")
LANGUAGE = {"kwp": "de", "scenarios": "de", "default": "en"}
HOMES = {"kwp": ROOT / "profiles" / "kwp",
         "scenarios": ROOT / "profiles" / "scenarios",
         "default": ROOT / "docpipe" / "builtin" / "default"}
# What each file says about the model's request: nothing of it is the loader's.
FRONT = "---\ntemperature: 0\nmax_tokens: 6144\n---\n"

# The rules each profile has, in order, by the words each rule starts with.
RULES = {
    "kwp": ['"value"', '"unit_raw"', '"source"', '"quote"',
            '"status" und "need_more"', "Rechnen lassen statt rechnen",
            "Nichts erfinden"],
    "scenarios": ['"value"', '"source"', '"quote"', "Ein Eintrag je Wert",
                  "Zitate sind keine Fundstellen", "Auswahl statt Formulierung",
                  '"status" und "need_more"', "Nichts erfinden"],
    "default": ['"value"', '"unit_raw"', '"source"', '"quote"',
                "One entry per value", "Citations are not places",
                "Choice instead of formulation", '"status" and "need_more"',
                "Have it calculated instead of calculating", "Invent nothing"],
}
# What each rule of a reference is: the rule a sentence points at.
REFERENCES = {
    "kwp": {"Regel": ["Rechnen lassen statt rechnen"]},
    "scenarios": {"Regel": ['"value"']},
    "default": {"rule": ["Have it calculated instead of calculating",
                         '"value"']},
}
# Sentences a profile says and sentences it does not say, which is what "no
# profile gains or loses a rule" comes to for the sentences that were one
# profile's and not another's (plan 2.2).
SAYS = {
    "kwp": ['"units_accepted"', '- "frame" (optional)', "Rechne NICHT im Kopf",
            "Eine Zahl, die du nur im Bild", "Wenn gerechnet werden MUSS",
            "Die Namen und Zahlen in den Beispielen oben",
            "zitier die ganze Zeile", "Ein Feld OHNE",
            "was dort nicht beziffert ist, existiert nicht"],
    "scenarios": ['Steht bei einem Feld "value_classes"', "Rate nicht",
                  "Was du aus Vorwissen", 'JEDER Eintrag trägt "source"',
                  "und das ist der Normalfall", "Nicht aus zwei Quellen",
                  "Zitier nur das Stück",
                  "was dort nicht steht, existiert nicht"],
    "default": ['"units_accepted"', '"value_classes"', "Image for Q1",
                "Do not guess", "values already fetched from this document",
                "Do NOT calculate",
                "A number that you only read off", "EVERY entry carries",
                "Do not assemble it from two sources",
                "What you would have to add from prior knowledge",
                "what does not stand there does not exist",
                'or, with a "frame", none of them belongs to the frame'],
}
SILENT = {
    "kwp": ['"value_classes"', "Auswahl statt Formulierung", "Rate nicht",
            "Was du aus Vorwissen", 'JEDER Eintrag trägt "source"',
            "und das ist der Normalfall", "Nicht aus zwei Quellen",
            "Zitier nur das Stück", "Schreib es Zeichen für Zeichen ab",
            "Die Vorderseite", "was dort nicht steht, existiert nicht"],
    "scenarios": ['"units_accepted"', '"frame"', '"anchors"', "Frame",
                  "Rechne NICHT im Kopf", "Sandbox", "unit_raw",
                  "Die Namen und Zahlen in den Beispielen oben",
                  "Eine Zahl, die du nur im Bild", "Tabellenzeile",
                  "Ein Feld OHNE", "innerhalb des Frames",
                  "was dort nicht beziffert ist"],
    "default": [],
}

_names = itertools.count(1)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def file_of(name: str) -> str:
    return (HOMES[name] / "prompts" / "extraction" / "rows.md").read_text(
        encoding="utf-8")


def load_rows(name: str) -> prompts.Prompt:
    return prompts.load(ROWS, load_profile(name))


def parts_of(text: str) -> dict:
    """{part name: its text} of a parts file."""
    meta, body = prompts._split(text)
    offset = text[:len(text) - len(body)].count("\n")

    def fail(message, part=None):
        return ValueError(message)
    return prompts.read_parts(body, fail, offset)


def drop_part(text: str, name: str) -> str:
    """The parts file without one part, as a person would take it out."""
    pattern = re.compile(rf"<!-- part: {name} -->\n.*?(?=<!-- part: |\Z)", re.S)
    assert pattern.search(text), name
    return pattern.sub("", text, count=1).rstrip("\n") + "\n"


def without_more(text: str, *blocks: str) -> str:
    return text.replace("without: [", "without: [" + ", ".join(blocks) + ", ", 1)


def numbered(text: str) -> list:
    """[(number, the rule's first line)] of the numbered rules of a prompt."""
    return [(int(m.group(1)), m.group(2)) for m in
            re.finditer(r"^(\d+)\. (.*)$", text, re.M)]


@pytest.fixture
def make(tmp_path, monkeypatch):
    """Profiles written to disk, each under a name of its own: `build(extends,
    language, rows)` returns the loaded profile."""
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))

    def build(*, extends, language=None, rows=None):
        name = f"rows_{next(_names)}"
        home = tmp_path / name
        write(home / "__init__.py", "")
        write(home / "profile.py",
              "from docpipe.profile import Profile\n"
              f"PROFILE = Profile(name={name!r}, extends={extends!r})\n")
        if language is not None:
            write(home / "extraction.py", f"CONTRACT_LANGUAGE = {language!r}\n")
        if rows is not None:
            write(home / "prompts" / "extraction" / "rows.md", rows)
        importlib.invalidate_caches()
        return load_profile(name)

    return build


def variant(make, name: str, text: str):
    return make(extends=name, language=LANGUAGE[name], rows=text)


def refusal(profile) -> prompts.PromptPartsError:
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load(ROWS, profile)
    return raised.value


# ---------------------------------------------------------------------------
# It is the template with the parts put in
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_the_rows_prompt_is_the_template_of_the_language_with_the_parts_in(name):
    prompt = load_rows(name)
    assert prompt.composition["template"] == "rows"
    assert prompt.composition["language"] == LANGUAGE[name]
    assert prompt.meta == {"temperature": 0, "max_tokens": 6144}
    template = contract.read(LANGUAGE[name], "rows")
    assert template.required == ("role", "asked_afterwards", "example_reply",
                                 "partial_when")
    # every rule the template has is in the text, unless the profile left out
    # its block, and no other rule is
    assert [head for _n, head in numbered(prompt.text)] and all(
        any(line.startswith(head) for _n, line in numbered(prompt.text))
        for head in RULES[name])


def test_a_template_of_another_wording_makes_another_prompt(tmp_path,
                                                            monkeypatch):
    """Built to fail: the German template with one word changed is another
    prompt for the two German profiles and the same one for the English."""
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    path = folder / "de" / "rows.md"
    text = path.read_text(encoding="utf-8")
    assert text.count("Deine Aufgabe in diesem Schritt ist EINE") == 1
    before = {name: load_rows(name).sha256 for name in NAMES}
    write(path, text.replace("Deine Aufgabe in diesem Schritt ist EINE",
                             "Deine Aufgabe in diesem Schritt ist GENAU EINE"))
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    for name in ("kwp", "scenarios"):
        assert load_rows(name).sha256 != before[name]
        assert "GENAU EINE:" in load_rows(name).text
    assert load_rows("default").sha256 == before["default"]


# ---------------------------------------------------------------------------
# AND no parts file repeats a sentence of the template
# ---------------------------------------------------------------------------

def template_sentences(language: str) -> set:
    """The sentences of a template that say something: marks and slots are
    taken out, and what is left is cut at the end of a sentence."""
    path = contract.template_path(language, "rows")
    body = prompts._split(path.read_text(encoding="utf-8"))[1]
    body = re.sub(r"<!--.*?-->", "", body)
    body = re.sub(r"\{\{.*?\}\}", "|", body)
    out = set()
    for piece in re.split(r"(?<=[.:;!?])\s+|\n", body):
        piece = piece.strip(" -|")
        if len(piece) >= 40 and "|" not in piece:
            out.add(piece)
    return out


def copies_of_the_template(language: str, parts_text: str) -> list:
    return sorted(s for s in template_sentences(language) if s in parts_text)


@pytest.mark.parametrize("name", NAMES)
def test_no_parts_file_says_a_sentence_the_template_says(name):
    assert len(template_sentences(LANGUAGE[name])) > 30
    assert copies_of_the_template(LANGUAGE[name], file_of(name)) == []


def test_that_scan_finds_a_template_sentence_in_a_parts_file():
    """Built to fail: the first sentence of the German template, pasted into a
    parts file, and the same sentence in the English one."""
    sentence = "Jeder Eintrag wird maschinell und wörtlich gegen die Quelle geprüft;"
    assert any(s.startswith(sentence) for s in template_sentences("de"))
    pasted = file_of("kwp") + "\n" + next(
        s for s in template_sentences("de") if s.startswith(sentence))
    assert copies_of_the_template("de", pasted)
    assert not copies_of_the_template("en", file_of("kwp"))


# ---------------------------------------------------------------------------
# AND every part of the profile reaches the request word for word
# ---------------------------------------------------------------------------

def parts_that_are_missing(name: str, prompt: prompts.Prompt) -> list:
    return sorted(part for part, text in parts_of(file_of(name)).items()
                  if text not in prompt.text)


@pytest.mark.parametrize("name", NAMES)
def test_every_part_of_the_profile_stands_in_the_prompt_word_for_word(name):
    assert len(parts_of(file_of(name))) >= 14
    assert parts_that_are_missing(name, load_rows(name)) == []


@pytest.mark.parametrize("name", NAMES)
def test_a_part_changed_by_a_letter_is_not_the_part_that_was_held(name, make):
    """Built to fail: the example reply with one letter changed reaches the
    prompt changed, and the part as it was is not in it any more."""
    text = file_of(name)
    changed = text.replace('"value"', '"valu"', 1)
    assert changed != text
    moved = prompts.load(ROWS, variant(make, name, changed))
    assert parts_that_are_missing(name, moved) == ["example_reply"]
    assert moved.sha256 != load_rows(name).sha256


# ---------------------------------------------------------------------------
# AND no profile gains a rule and none loses one
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_each_profile_has_the_rules_it_had_and_in_the_order_it_had_them(name):
    rules = numbered(load_rows(name).text)
    assert [n for n, _ in rules] == list(range(1, len(RULES[name]) + 1))
    for (number, line), head in zip(rules, RULES[name]):
        assert line.startswith(head), (number, line[:60], head)


@pytest.mark.parametrize("name", NAMES)
def test_each_profile_says_what_it_said_and_is_silent_about_what_it_was(name):
    text = load_rows(name).text
    assert [s for s in SAYS[name] if s not in text] == []
    assert [s for s in SILENT[name] if s in text] == []


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_profile_that_does_not_leave_out_what_it_lacked_gains_it(name, make):
    """Built to fail: the same parts file without its `without`, which is how
    it would read if the template's superset were taken. It gains rules and
    sentences it never had."""
    text = file_of(name)
    kept = re.sub(r"^without: \[.*\]\n", "", text, flags=re.M)
    assert kept != text
    # a part whose place is gone does not matter here: none of these has one
    gained = prompts.load(ROWS, variant(make, name, kept)).text
    assert len(numbered(gained)) > len(RULES[name])
    assert [s for s in SILENT[name] if s in gained]


def test_a_rule_the_template_has_and_the_profile_worded_stays_its_own():
    """kwp words the first sentence of rule 1 itself, by a part named as the
    block: the template's wording of it is not in the prompt."""
    kwp = load_rows("kwp")
    assert kwp.composition["overrides"] == ["value_text"]
    assert 'ohne Rechtsform: aus "endura kommunal GmbH"' in kwp.text
    assert "Ein Text muss ZEICHEN FÜR ZEICHEN" not in kwp.text
    assert "Ein Text muss ZEICHEN FÜR ZEICHEN" in load_rows("scenarios").text
    assert load_rows("default").composition["overrides"] == []


@pytest.mark.parametrize("name, omitted", [
    ("kwp", {"quantities_choice", "no_guessing", "normal_case",
             "place_example_more", "place_front_page", "source_every",
             "quote_one_source", "quote_narrow", "quote_inner_numbers",
             "per_value", "citations", "choice", "invent_knowledge",
             "quote_whole_row"}),
    ("scenarios", {"quantities_units", "quantities_text", "frame_keys",
                   "completeness", "frame_empty", "value_number", "unit_raw",
                   "quote_whole_row", "quote_copy", "examples_foreign",
                   "status_frame", "invent_chart", "sandbox"}),
    ("default", set())])
def test_what_a_profile_leaves_out_is_listed_and_is_what_it_lacked(name, omitted):
    assert set(load_rows(name).composition["omitted"]) == omitted


# ---------------------------------------------------------------------------
# AND "source" and "quote" are two numbered rules in every profile
# ---------------------------------------------------------------------------

def source_and_quote_are_apart(text: str) -> bool:
    """The rule of "source" and the rule of "quote" are two, one after the
    other."""
    rules = numbered(text)
    at = {kind: [n for n, line in rules if line.startswith(f'"{kind}"')]
          for kind in ("source", "quote")}
    return (len(at["source"]) == 1 and len(at["quote"]) == 1
            and at["quote"][0] == at["source"][0] + 1
            and not any(re.match(r'"source" (und|and) "quote"', line)
                        for _n, line in rules))


@pytest.mark.parametrize("name", NAMES)
def test_source_and_quote_are_two_rules_in_every_profile(name):
    assert source_and_quote_are_apart(load_rows(name).text)


def test_that_check_finds_the_two_rules_run_together():
    """Built to fail: the form scenarios and the built-in profile had."""
    old = ('1. "value": x\n\n2. "source" und "quote": "source" ist die '
           'Kennung.\n\n3. Ein Eintrag je Wert.\n')
    assert not source_and_quote_are_apart(old)
    assert source_and_quote_are_apart(
        '1. "value": x\n\n2. "source": y\n\n3. "quote": z\n')


# ---------------------------------------------------------------------------
# AND the numbers are gapless and a reference points at the rule it means
# ---------------------------------------------------------------------------

def references(text: str, word: str) -> list:
    """[the first line of the rule each "<word> N" in the text points at]."""
    rules = dict(numbered(text))
    return [rules.get(int(m.group(1)), f"no rule {m.group(1)}")
            for m in re.finditer(rf"\b{word} (\d+)\b", text)]


@pytest.mark.parametrize("name", NAMES)
def test_every_reference_points_at_the_rule_it_means(name):
    text = load_rows(name).text
    ((word, wanted),) = REFERENCES[name].items()
    found = references(text, word)
    assert len(found) == len(wanted)
    for line, head in zip(found, wanted):
        assert line.startswith(head), (line[:60], head)


def test_leaving_a_block_out_moves_the_numbers_and_what_points_at_them(make):
    """Built to fail: kwp without the unit rule. The rules after it move up by
    one and the reference to the sandbox rule says the new number."""
    text = file_of("kwp")
    for part in ("unit_examples", "unit_heading"):
        text = drop_part(text, part)
    prompt = prompts.load(ROWS, variant(make, "kwp", without_more(text,
                                                                  "unit_raw")))
    rules = numbered(prompt.text)
    assert [n for n, _ in rules] == list(range(1, len(RULES["kwp"])))
    assert not any(line.startswith('"unit_raw"') for _n, line in rules)
    ((target,),) = [references(prompt.text, "Regel")]
    assert target.startswith("Rechnen lassen statt rechnen")
    assert "siehe Regel 5." in prompt.text
    assert "siehe Regel 6." in load_rows("kwp").text


def test_leaving_the_sandbox_out_leaves_no_reference_to_it(make):
    text = drop_part(file_of("kwp"), "sandbox_more")
    prompt = prompts.load(ROWS, variant(make, "kwp", without_more(text,
                                                                  "sandbox")))
    assert references(prompt.text, "Regel") == []
    assert "Sandbox" not in prompt.text
    assert "Rechnen lassen" not in prompt.text
    assert "Sandbox" in load_rows("kwp").text


# ---------------------------------------------------------------------------
# AND a part that is not there leaves no gap behind
# ---------------------------------------------------------------------------

def gaps_in(text: str) -> list:
    """What an absent part or a left-out block must not leave: two blank lines
    in a row, a line that ends in a space, two spaces inside a line."""
    found = []
    if "\n\n\n" in text:
        found.append("two blank lines in a row")
    if any(line != line.rstrip() for line in text.split("\n")):
        found.append("a line that ends in a space")
    if re.search(r"(?<=\S)  +(?=\S)", text):
        found.append("two spaces inside a line")
    if text.startswith("\n") or not text.endswith("\n"):
        found.append("blank lines around the text")
    return found


@pytest.mark.parametrize("name", NAMES)
def test_no_prompt_has_a_gap_where_a_part_is_missing_or_a_block_is_left_out(name):
    assert gaps_in(load_rows(name).text) == []


def test_a_block_that_is_not_left_out_and_has_no_part_leaves_a_gap(make):
    """Built to fail: kwp without leaving the front page's place out, and
    with no front page to put in it."""
    text = file_of("kwp").replace("place_front_page, ", "", 1)
    assert text != file_of("kwp")
    gap = prompts.load(ROWS, variant(make, "kwp", text)).text
    assert gaps_in(gap) == ["two blank lines in a row"]


# ---------------------------------------------------------------------------
# AND the least length of a quote is the code's number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, said", [
    ("kwp", "(mindestens {} Zeichen)"),
    ("scenarios", "(mindestens {} Zeichen)"),
    ("default", "(at least {} characters)")])
def test_the_least_length_of_a_quote_is_the_codes_number(name, said,
                                                         monkeypatch):
    before = load_rows(name)
    assert said.format(verify.MIN_QUOTE_CHARS) in before.text
    monkeypatch.setattr(verify, "MIN_QUOTE_CHARS", 12)
    moved = load_rows(name)
    assert said.format(12) in moved.text
    assert said.format(8) not in moved.text
    assert moved.sha256 != before.sha256


def test_no_parts_file_types_the_number_the_code_decides():
    typed = re.compile(rf"(?<![\w.,]){verify.MIN_QUOTE_CHARS}(?!\w|[.,]\d)")
    found = [(name, part) for name in NAMES
             for part, text in parts_of(file_of(name)).items()
             if typed.search(text)]
    assert found == []
    assert typed.search("at least 8 characters")


# ---------------------------------------------------------------------------
# AND the language is that of the profile that owns the parts file
# ---------------------------------------------------------------------------

def test_a_child_reads_the_parts_it_inherits_in_the_language_of_their_owner(
        make):
    german = make(extends="kwp", language="en")
    prompt = prompts.load(ROWS, german)
    assert prompt.composition["language"] == "de"
    assert prompt.text.startswith("Du findest Zahlen in deutschen")
    assert prompt.sha256 == load_rows("kwp").sha256
    english = make(extends="default", language="de")
    prompt = prompts.load(ROWS, english)
    assert prompt.composition["language"] == "en"
    assert prompt.sha256 == load_rows("default").sha256


def test_parts_with_no_declared_language_are_refused_and_say_what_there_is(make):
    silent = make(extends="default", rows=file_of("kwp"))
    problem = refusal(silent)
    assert "CONTRACT_LANGUAGE" in str(problem)
    assert str(contract.languages()) in str(problem)
    assert problem.prompt_id == ROWS and problem.profile == silent.name


# ---------------------------------------------------------------------------
# AND a request for rows carries that text and no mark of a template
# ---------------------------------------------------------------------------

def marks_in(text: str) -> list:
    return [mark for mark in ("{{", "}}", "<!--", "-->") if mark in text]


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_the_rows_request_carries_the_composed_text_and_no_mark(name):
    from tests.test_extraction_requests import _requests, faults_in_text
    with MonkeyPatch.context() as patch:
        sent = _requests(name, patch)["rows"]
    assert sent, "no rows request was sent"
    assert faults_in_text(sent, ROWS, name) == []
    for request in sent:
        assert marks_in(request["messages"][0]["content"]) == []
    assert marks_in(load_rows(name).text) == []


def test_that_scan_finds_a_mark_left_in_a_request():
    assert marks_in("Say {{x}} and <!-- block: y -->.") == [
        "{{", "}}", "<!--", "-->"]
    assert marks_in(load_rows("kwp").text) == []


def test_the_harvester_of_a_profile_with_an_open_part_is_refused_before_a_request(
        make, monkeypatch):
    """Built to fail: a part that holds `{{x}}`. No request is sent, because
    the prompt is loaded when the harvester is made."""
    text = file_of("kwp").replace('"quote": "Bearbeitung', '"quote": "{{x}}', 1)
    assert "{{x}}" in text
    bad = variant(make, "kwp", text)
    monkeypatch.setenv(ENV_VAR, bad.name)
    sent = []
    monkeypatch.setattr(runner, "_client", lambda: sent.append("client"))
    spec = load_spec(json.loads((HOMES["kwp"] / "extraction_spec.json")
                                .read_text(encoding="utf-8")))
    with pytest.raises(prompts.PromptPartsError) as raised:
        runner.make_harvester(spec=spec)
    assert "{{x}}" in str(raised.value) and raised.value.part == "example_reply"
    assert sent == []


# ---------------------------------------------------------------------------
# AND a parts file that does not fit is refused, and everything is named
# ---------------------------------------------------------------------------

def named(problem, profile, part, language="de") -> None:
    """The refusal names the prompt, the part, the profile and both files."""
    assert problem.prompt_id == ROWS
    assert problem.profile == profile.name
    assert problem.part == part
    files = dict(problem.files)
    assert files["parts file"] == str(
        profile.prompts_dir / "extraction" / "rows.md")
    assert files["template"] == str(contract.template_path(language, "rows"))


def test_a_missing_part_is_refused_and_the_doctor_fails_it(make):
    profile = variant(make, "kwp", drop_part(file_of("kwp"), "partial_when"))
    problem = refusal(profile)
    assert "'partial_when' is missing" in str(problem)
    named(problem, profile, "partial_when")
    (line,) = [l for l in doctor._prompts_of("extract", profile)
               if ROWS in l.detail]
    assert line.status == doctor.FAIL and "partial_when" in line.detail
    # the file with its part is the profile's prompt
    assert prompts.load(ROWS, variant(make, "kwp", file_of("kwp"))).sha256 \
        == load_rows("kwp").sha256


def test_a_misspelt_part_is_refused_and_the_near_one_named(make):
    profile = variant(make, "kwp", file_of("kwp").replace(
        "part: partial_when", "part: partial_whn", 1))
    problem = refusal(profile)
    assert "did you mean 'partial_when'" in str(problem)
    assert problem.part == "partial_whn"
    assert problem.prompt_id == ROWS and problem.profile == profile.name


def test_a_part_with_a_placeholder_open_is_refused(make):
    profile = variant(make, "scenarios", file_of("scenarios").replace(
        "Das Szenario betrachtet", "Das {{x}} betrachtet", 1))
    problem = refusal(profile)
    assert "{{x}}" in str(problem) and problem.part == "example_more"
    named(problem, profile, "example_more")


def test_a_block_that_cannot_be_left_out_is_refused(make):
    profile = variant(make, "scenarios", without_more(file_of("scenarios"),
                                                      "value_text"))
    problem = refusal(profile)
    assert "cannot be left out" in str(problem)
    assert problem.part == "value_text"


def test_a_block_the_template_does_not_have_is_refused_and_the_near_one_named(
        make):
    profile = variant(make, "scenarios", without_more(file_of("scenarios"),
                                                      "sandbx"))
    problem = refusal(profile)
    assert "sandbx" in str(problem) and "did you mean 'sandbox'" in str(problem)


def test_a_part_whose_place_is_left_out_is_refused(make):
    """kwp leaves the front page out; a front page it then words has no place."""
    text = file_of("kwp").rstrip("\n") + "\n\n<!-- part: front_page -->\nEine Seite.\n"
    profile = variant(make, "kwp", text)
    problem = refusal(profile)
    assert "has no place in the prompt" in str(problem)
    assert "place_front_page" in str(problem) and problem.part == "front_page"


# ---------------------------------------------------------------------------
# AND the fingerprint is the sha256 of the text sent, so no stamp goes stale
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_the_fingerprint_is_the_sha_of_the_file_a_person_would_have_written(name):
    prompt = load_rows(name)
    assert prompt.sha256 == sha(FRONT + prompt.text)
    assert prompts.versions([ROWS], load_profile(name)) == {
        ROWS: prompt.sha256}


def test_a_changed_part_a_changed_block_or_a_changed_setting_moves_the_sha(make):
    base = load_rows("kwp").sha256
    text = file_of("kwp")
    assert prompts.load(ROWS, variant(make, "kwp", text.replace(
        "Du findest Zahlen", "Du suchst Zahlen", 1))).sha256 != base
    assert prompts.load(ROWS, variant(make, "kwp", without_more(
        drop_part(drop_part(text, "unit_examples"), "unit_heading"),
        "unit_raw"))).sha256 != base
    assert prompts.load(ROWS, variant(make, "kwp", text.replace(
        "max_tokens: 6144", "max_tokens: 5000", 1))).sha256 != base


def test_a_stamp_from_before_the_prompt_was_composed_is_current(tmp_path,
                                                                monkeypatch):
    """A stamp records the sha of the prompt and compares none of them: the one
    it holds for the rows prompt is the file's from before, and the document is
    not stale for it. Built to fail: the same stamp with a question that moved
    is stale in that key."""
    from tests.test_extraction_topup import SPEC
    for name, before in (("kwp", "x" * 64), ("scenarios", "y" * 64)):
        monkeypatch.setenv("DOCPIPE_PROFILE", name)
        today = runner._stamp_current("a" * 64, "b" * 16, SPEC)
        assert today[ROWS] == load_rows(name).sha256
        stamp = tmp_path / f"{name}.stamp.json"
        stamp.write_text(json.dumps({**today, ROWS: before}), encoding="utf-8")
        assert runner.stale(stamp, today) == []
        axis = next(key for key in today if key.startswith("axis/"))
        stamp.write_text(json.dumps({**today, ROWS: before, axis: "moved"}),
                         encoding="utf-8")
        assert runner.stale(stamp, today) == [axis]


def test_a_profile_without_numbers_keeps_what_it_said_of_figure_descriptions(
        make):
    """Promised: the German template says of a figure description that what is
    not NUMBERED there does not exist, which is kwp's sentence about its
    numbers; scenarios reads titles, names and regions, and said that what
    does not STAND there does not exist. Each profile says its own.

    Built to fail: the scenarios parts file without its part is told the
    numbers sentence, and the one that is told it is no longer the one that
    said "stand"."""
    own = load_rows("scenarios")
    assert "invent_figures" in own.composition["overrides"]
    assert "was dort nicht steht, existiert nicht." in own.text
    assert "beziffert" not in own.text
    assert "was dort nicht beziffert ist, existiert nicht." in load_rows(
        "kwp").text
    assert "nicht steht, existiert nicht" not in load_rows("kwp").text
    without = prompts.load(ROWS, variant(
        make, "scenarios", drop_part(file_of("scenarios"), "invent_figures")))
    assert "invent_figures" not in without.composition["overrides"]
    assert "was dort nicht beziffert ist, existiert nicht." in without.text
    assert "was dort nicht steht, existiert nicht" not in without.text
    assert without.sha256 != own.sha256


def test_scenarios_names_the_kinds_of_its_sources_in_its_own_words(make):
    """Promised (owner, 2026-10-07): where a sentence of the template fits a
    profile less well, the profile says its own. Scenarios lists the kinds of
    sources it is shown in its own order and calls the description of a figure
    what its last rule calls it AND kwp keeps the template's sentence.

    Built to fail: the scenarios parts file without its part is told the
    template's kinds, and that is another prompt."""
    own = load_rows("scenarios")
    assert own.composition["overrides"] == ["invent_figures", "source_kinds"]
    assert ("— Textabschnitte, Tabellen (Markdown-Transkription) oder "
            "Abbildungsbeschreibungen.") in own.text
    assert "Diagrammbeschreibungen" not in own.text
    assert ("— Tabellen (Markdown-Transkription), Textabschnitte oder "
            "Diagrammbeschreibungen.") in load_rows("kwp").text
    without = prompts.load(ROWS, variant(
        make, "scenarios", drop_part(file_of("scenarios"), "source_kinds")))
    assert without.composition["overrides"] == ["invent_figures"]
    assert "Textabschnitte oder Diagrammbeschreibungen." in without.text
    assert without.sha256 != own.sha256
