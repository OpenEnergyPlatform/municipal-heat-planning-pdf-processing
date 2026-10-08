"""The example prompt is the core's template with the profile's one example
reply put in, and it reads as it did before it was cut into parts.

Promised: the example prompt of a profile is the core's example template of the
profile's language with the profile's example reply put in AND it is, byte for
byte and as the sha256 a stage records, the file it was before it was composed
AND the least length of a quote in it is the code's number and not a typed one
AND the language is that of the profile that owns the parts file AND a request
for an example carries that text and no mark of a template AND every profile
that owns a parts file declares a language the core has the template in AND a
parts file that lacks its reply, misspells it or leaves a placeholder open is
refused at load with the prompt, the part, the profile and both files named.

Each AND is its own test below, and each has the case built to break it: a
template with one word moved, a child that declares the other language, a
patched least length, a reply that holds `{{x}}`, a profile with a parts file
and no declaration, a part that is deleted or misspelt.

No model, no GPU.
"""
import hashlib
import importlib
import itertools
import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docpipe import doctor, prompts
from docpipe.extraction import contract, verify
from docpipe.profile import ENV_VAR, load_profile

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = "extraction/example"

# The example prompt of each profile as its file was before the file became a
# parts file: the sha256 of the file (what a stage records for it) and the
# sha256 of the text after its front matter (what a model reads), taken from
# the files of the commit before. The text says the least length of a quote,
# which is the code's 8, so a change of that number moves them too: that is
# the prompt moving and is entered here on purpose.
BEFORE = {
    "kwp": ("e208bd8e8de87020829d0db0ced56080498cca707a22fa86193cc12a248e12ab",
            "7b62a1c34099aca9dec74f01992a6f8c11ace46ce3b9fa658f8485f4d99a5b46"),
    "scenarios": (
        "e79da9efa2d368c8a7554ac014058e3b5f4bf1c06bec48e419fa7ab759a0405a",
        "c60291b7c6dfa9fbcc3e54435873e74fabfe3c10034432404cba425e762ac5e9"),
    "default": (
        "f50536809883024b2024f069172b0ff234d6243e3fc23d6b4aa32e9450d5d96c",
        "1d444b95916f0e703d7c04926211177196934735b2443a3644673ffc0fb1e1ab"),
}
LANGUAGE = {"kwp": "de", "scenarios": "de", "default": "en"}
OPENING = {"de": "Du liest EINE Passage eines Dokuments",
           "en": "You read ONE passage of a document"}
HOMES = {"kwp": ROOT / "profiles" / "kwp",
         "scenarios": ROOT / "profiles" / "scenarios",
         "default": ROOT / "docpipe" / "builtin" / "default"}

PARAMETER = {"uri": "publisher", "label": "publisher", "value_type": "text",
             "description": "The organisation that prepared the report."}
PASSAGE = "The report was prepared by Riverside Housing Association in 2023."

_names = itertools.count(1)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def file_of(name: str) -> str:
    return (HOMES[name] / "prompts" / "extraction" / "example.md").read_text(
        encoding="utf-8")


@pytest.fixture
def make(tmp_path, monkeypatch):
    """Profiles written to disk, each under a name of its own: `build(extends,
    language, example)` returns the loaded profile."""
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))

    def build(*, extends, language=None, example=None):
        name = f"example_{next(_names)}"
        home = tmp_path / name
        write(home / "__init__.py", "")
        write(home / "profile.py",
              "from docpipe.profile import Profile\n"
              f"PROFILE = Profile(name={name!r}, extends={extends!r})\n")
        if language is not None:
            write(home / "extraction.py", f"CONTRACT_LANGUAGE = {language!r}\n")
        if example is not None:
            write(home / "prompts" / "extraction" / "example.md", example)
        importlib.invalidate_caches()           # a folder made a moment ago
        return load_profile(name)

    return build


def refusal(profile) -> prompts.PromptPartsError:
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load(EXAMPLE, profile)
    return raised.value


# ---------------------------------------------------------------------------
# It is the text and the sha256 it was
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BEFORE))
def test_the_example_prompt_is_the_text_and_the_sha_it_was_before_it_was_composed(
        name):
    profile = load_profile(name)
    prompt = prompts.load(EXAMPLE, profile)
    file_sha, text_sha = BEFORE[name]
    assert prompt.sha256 == file_sha
    assert sha(prompt.text) == text_sha
    # what a stage records is the same hash, so no stamp is stale for it
    assert prompts.versions([EXAMPLE], profile) == {EXAMPLE: file_sha}
    assert prompt.meta == {"temperature": 0, "max_tokens": 1024}
    assert prompt.composition["template"] == "example"
    assert prompt.composition["language"] == LANGUAGE[name]
    # nothing is worded by the profile itself, nothing is left out
    assert prompt.composition["overrides"] == []
    assert prompt.composition["omitted"] == []


def test_that_comparison_fails_when_a_word_of_the_template_moves(
        tmp_path, monkeypatch):
    """Built to fail: the German template with one word changed is another
    prompt for the two German profiles and the same one for the English."""
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    path = folder / "de" / "example.md"
    text = path.read_text(encoding="utf-8")
    assert text.count("Zeichen für Zeichen kopiert") == 1
    write(path, text.replace("Zeichen für Zeichen kopiert",
                             "Zeichen für Zeichen abgeschrieben"))
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    for name in ("kwp", "scenarios"):
        moved = prompts.load(EXAMPLE, load_profile(name))
        assert moved.sha256 != BEFORE[name][0]
        assert sha(moved.text) != BEFORE[name][1]
        assert "Zeichen für Zeichen abgeschrieben" in moved.text
    english = prompts.load(EXAMPLE, load_profile("default"))
    assert english.sha256 == BEFORE["default"][0]


@pytest.mark.parametrize("name", sorted(BEFORE))
def test_the_profiles_example_reply_reaches_the_prompt_word_for_word(
        name, make):
    """The one domain line: it stands in the text as the profile wrote it, and
    a changed letter in it is a changed prompt."""
    text = file_of(name)
    reply = text.split("<!-- part: example_reply -->\n", 1)[1].strip()
    assert reply.startswith('{"tuples": [')
    prompt = prompts.load(EXAMPLE, load_profile(name))
    assert f"\n\n{reply}\n\n" in prompt.text
    changed = make(extends=name, language=LANGUAGE[name], example=text.replace(
        "value_raw", "value_rav", 1))
    moved = prompts.load(EXAMPLE, changed)
    assert '"value_rav"' in moved.text and moved.sha256 != prompt.sha256
    assert moved.text.count("\n") == prompt.text.count("\n")


# ---------------------------------------------------------------------------
# The language is that of the profile that owns the parts file
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_example_prompt_is_in_the_language_of_its_profile(name):
    text = prompts.load(EXAMPLE, load_profile(name)).text
    other = OPENING["en" if LANGUAGE[name] == "de" else "de"]
    assert text.startswith(OPENING[LANGUAGE[name]])
    assert other not in text


def test_a_child_reads_the_parts_it_inherits_in_the_language_of_their_owner(
        make):
    """Built to fail: a child that declares the other language still gets the
    parts of the profile it extends in the language those are in."""
    german = make(extends="kwp", language="en")
    prompt = prompts.load(EXAMPLE, german)
    assert prompt.path == HOMES["kwp"] / "prompts" / "extraction" / "example.md"
    assert prompt.composition["language"] == "de"
    assert prompt.text.startswith(OPENING["de"])
    assert prompt.sha256 == BEFORE["kwp"][0]

    english = make(extends="default", language="de")
    prompt = prompts.load(EXAMPLE, english)
    assert prompt.composition["language"] == "en"
    assert prompt.text.startswith(OPENING["en"])
    assert prompt.sha256 == BEFORE["default"][0]


def test_a_child_with_parts_of_its_own_says_its_language_itself(make):
    own = make(extends="default", language="de", example=file_of("kwp"))
    prompt = prompts.load(EXAMPLE, own)
    assert prompt.path.parent.parent.parent.name == own.name
    assert prompt.text.startswith(OPENING["de"])
    assert prompt.sha256 == BEFORE["kwp"][0]
    # the same file with no declaration is refused, and says what there is
    silent = make(extends="default", example=file_of("kwp"))
    problem = refusal(silent)
    assert "CONTRACT_LANGUAGE" in str(problem)
    assert str(contract.languages()) in str(problem)
    assert problem.prompt_id == EXAMPLE and problem.profile == silent.name
    # and one that names a language the core has no templates for
    elvish = make(extends="default", language="xx", example=file_of("kwp"))
    assert str(contract.languages()) in str(refusal(elvish))


# ---------------------------------------------------------------------------
# The least length of a quote is the code's number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, said", [
    ("kwp", "(mindestens {} Zeichen)"),
    ("scenarios", "(mindestens {} Zeichen)"),
    ("default", "(at least {} characters)")])
def test_the_least_length_of_a_quote_is_the_codes_number(name, said,
                                                         monkeypatch):
    profile = load_profile(name)
    before = prompts.load(EXAMPLE, profile)
    assert said.format(verify.MIN_QUOTE_CHARS) in before.text
    monkeypatch.setattr(verify, "MIN_QUOTE_CHARS", 12)
    moved = prompts.load(EXAMPLE, profile)
    assert said.format(12) in moved.text
    assert said.format(8) not in moved.text
    assert moved.sha256 != before.sha256


# ---------------------------------------------------------------------------
# A request for an example carries the text and no mark of a template
# ---------------------------------------------------------------------------

class Client:
    """Answers with an empty list of tuples and keeps what it was asked."""

    def __init__(self):
        self.asked = []
        reply = NS(choices=[NS(message=NS(content='{"tuples": []}',
                                          reasoning_content=None),
                               finish_reason="stop")], usage=None)
        self.chat = NS(completions=NS(
            create=lambda **kwargs: self.asked.append(kwargs) or reply))


@pytest.mark.parametrize("name", sorted(BEFORE))
def test_a_request_for_an_example_carries_the_composed_text_and_no_mark(
        name, monkeypatch):
    from docpipe.compile import cli
    monkeypatch.setenv(ENV_VAR, name)
    prompt = prompts.load(EXAMPLE, load_profile(name))
    client = Client()
    assert cli.ask_for_example(client, prompt, dict(PARAMETER), PASSAGE) == {
        "tuples": []}
    (asked,) = client.asked
    system = asked["messages"][0]
    assert system == {"role": "system", "content": prompt.text}
    assert sha(system["content"]) == BEFORE[name][1]
    assert "{{" not in system["content"] and "<!--" not in system["content"]
    assert (asked["temperature"], asked["max_tokens"]) == (0.0, 1024)


def test_a_reply_with_a_placeholder_open_is_refused_before_any_request(make):
    """Built to fail: the prompt of a profile whose reply holds `{{x}}` is not
    made, so no request can carry it."""
    open_reply = file_of("kwp").replace(
        '{"tuples": [{"value"', '{"tuples": [{{x}}, {"value"', 1)
    assert "{{x}}" in open_reply
    profile = make(extends="kwp", language="de", example=open_reply)
    problem = refusal(profile)
    assert "{{x}}" in str(problem) and problem.part == "example_reply"
    assert problem.prompt_id == EXAMPLE and problem.profile == profile.name


# ---------------------------------------------------------------------------
# A parts file that lacks its reply, misspells it or leaves it open
# ---------------------------------------------------------------------------

def named(problem, profile, language="de") -> None:
    """The refusal names the prompt, the part, the profile and both files."""
    assert problem.prompt_id == EXAMPLE
    assert problem.profile == profile.name
    assert problem.part == "example_reply"
    files = dict(problem.files)
    assert files["parts file"] == str(
        profile.prompts_dir / "extraction" / "example.md")
    assert files["template"] == str(contract.template_path(language, "example"))


def test_a_parts_file_without_its_reply_is_refused_and_everything_is_named(
        make):
    front = file_of("kwp").split("<!-- part:", 1)[0]
    profile = make(extends="kwp", language="de", example=front)
    problem = refusal(profile)
    assert "'example_reply' is missing" in str(problem)
    named(problem, profile)
    # the same file with its reply is the profile's prompt
    whole = make(extends="kwp", language="de", example=file_of("kwp"))
    assert prompts.load(EXAMPLE, whole).sha256 == BEFORE["kwp"][0]


def test_a_misspelt_part_is_refused_and_the_near_one_named(make):
    profile = make(extends="kwp", language="de", example=file_of("kwp").replace(
        "part: example_reply", "part: example_repl", 1))
    problem = refusal(profile)
    assert "example_repl" in str(problem)
    assert "did you mean 'example_reply'" in str(problem)
    assert problem.part == "example_repl"
    assert problem.prompt_id == EXAMPLE and problem.profile == profile.name


def test_the_doctor_reads_the_example_prompt_of_a_profile_and_fails_a_broken_one(
        make):
    # the built-in profile configures no extraction stage, so the doctor does
    # not ask it for the prompts of one
    for name in ("kwp", "scenarios"):
        lines = doctor._prompts_of("compile", load_profile(name))
        assert [line.status for line in lines] == [doctor.OK], name
    front = file_of("kwp").split("<!-- part:", 1)[0]
    broken = make(extends="kwp", language="de", example=front)
    (line,) = doctor._prompts_of("compile", broken)
    assert line.status == doctor.FAIL
    assert "example_reply" in line.detail and EXAMPLE in line.detail
    assert "<!-- part: name -->" in line.hint


# ---------------------------------------------------------------------------
# Every profile that owns a parts file declares a language it is in
# ---------------------------------------------------------------------------

def declaration_faults(profile) -> tuple:
    """(how many parts files the profile owns, what is wrong with how it
    declares the language of them)."""
    owned, faults = 0, []
    language = contract.language_of(profile)
    for path in sorted(profile.prompts_dir.rglob("*.md")):
        meta = prompts._split(path.read_text(encoding="utf-8"))[0]
        if "template" not in meta:
            continue
        owned += 1
        where = f"{profile.name}: {path.parent.name}/{path.stem}"
        if language is None:
            faults.append(f"{where} names a template and the profile declares "
                          f"no CONTRACT_LANGUAGE")
        elif language not in contract.languages():
            faults.append(f"{where}: the core has no templates in {language!r}")
        elif not contract.template_path(language, meta["template"]).is_file():
            faults.append(f"{where}: the core has no template "
                          f"{meta['template']!r} in {language!r}")
    return owned, faults


def test_every_profile_that_owns_a_parts_file_declares_a_language_the_core_has():
    names = sorted(path.name for path in (ROOT / "profiles").iterdir()
                   if (path / "profile.py").is_file()) + ["default"]
    assert {"kwp", "scenarios", "default"} <= set(names)
    found = {name: declaration_faults(load_profile(name)) for name in names}
    assert {name: faults for name, (_, faults) in found.items()} == {
        name: [] for name in names}
    assert all(owned >= 1 for owned, _ in found.values()), \
        "a profile owns no parts file: nothing was held"


def test_that_scan_can_fail(make):
    """Built to fail: a parts file and no declaration, a language the core has
    no templates in, a template the language does not have."""
    silent = make(extends="default", example=file_of("kwp"))
    assert declaration_faults(silent) == (1, [
        f"{silent.name}: extraction/example names a template and the profile "
        f"declares no CONTRACT_LANGUAGE"])
    elvish = make(extends="default", language="xx", example=file_of("kwp"))
    assert declaration_faults(elvish) == (1, [
        f"{elvish.name}: extraction/example: the core has no templates in "
        f"'xx'"])
    ghost = make(extends="default", language="de", example=file_of("kwp").replace(
        "template: example", "template: ghost", 1))
    assert declaration_faults(ghost) == (1, [
        f"{ghost.name}: extraction/example: the core has no template 'ghost' "
        f"in 'de'"])
    sound = make(extends="default", language="de", example=file_of("kwp"))
    assert declaration_faults(sound) == (1, [])


# ---------------------------------------------------------------------------
# The templates the core ships are held, and the example is among them
# ---------------------------------------------------------------------------

def test_the_example_template_is_held_in_both_languages():
    from tests.test_contract_templates import EN_ONLY, folder_problems
    examined, problems = folder_problems(EN_ONLY)
    assert "example" in examined
    assert problems == []
    assert ("de", "example") in contract.available()
    assert ("en", "example") in contract.available()
    de, en = contract.read("de", "example"), contract.read("en", "example")
    assert de.shape() == en.shape()
    assert de.required == ("example_reply",)
    assert de.rules == ("value", "value_raw", "unit", "quote", "one_per_value",
                        "passage_is_data")
