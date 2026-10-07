"""The frame prompt is the core's template with the profile's parts put in, and
it reads as it did before it was cut into parts, except for the words the
template says for every profile.

Promised: the frame prompt of a profile is the core's frame template of the
profile's language with the profile's parts put in AND nothing else, AND it
differs from the file it was by exactly the sentences listed here, each of
them the template's own wording (the built-in profile's differs by none), AND
every part of the profile reaches the prompt word for word, AND a profile has
the sentences it had and gets none it lacked, AND the key of the closed list
that the German prompt names is the key the request sends it under, AND the
language is that of the profile that owns the parts file, AND a request for the
frame carries that text and no mark of a template, AND a parts file that lacks
a part, misspells one or leaves a placeholder open is refused at load with the
prompt, the part, the profile and both files named, AND the template says the
same in both languages.

Each AND is its own test below, and each has the case built to break it: a
word moved in the template or in a prompt, a part that is dropped, given or
written without its space, a phrase that names the coordinate, a child that
declares the other language, a part that holds `{{x}}`, a part that is deleted
or misspelt, an English template that lost a part.

The file as it was is not in the repository any more. What is held of it is
its sha256 (the file, as a stage records it, and the text a model reads), taken
from the commit before, and the list of sentences that moved: put back, they
give that text again.

No model, no GPU.
"""
import hashlib
import importlib
import itertools
import json
import shutil
from pathlib import Path

import pytest

from docpipe import doctor, prompts
from docpipe.extraction import contract, fields, runner, wording
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import ENV_VAR, load_profile
from tests.test_extraction_requests import Recorder

ROOT = Path(__file__).resolve().parent.parent
FRAME = "extraction/frame"
FRONT = "---\ntemperature: 0\nmax_tokens: 4096\n---\n"

HOMES = {"kwp": ROOT / "profiles" / "kwp",
         "scenarios": ROOT / "profiles" / "scenarios",
         "default": ROOT / "docpipe" / "builtin" / "default"}
LANGUAGE = {"kwp": "de", "scenarios": "de", "default": "en"}
OPENING = {"de": "Du bekommst Abschnitte, Tabellen und Abbildungen",
           "en": "You receive sections, tables and figures"}

# The frame prompt of each profile as its file was before the file became a
# parts file: the sha256 of the file (what a stage records for it) and the
# sha256 of the text after its front matter (what a model reads).
BEFORE = {
    "kwp": ("cab072c0d4b0fca9daf479a0cf444446c6e7b58a91040d2892e420feab068337",
            "a245b69646e726b445c86d1b8455725df904bb6d87a769c4233458d6b543ff99"),
    "scenarios": (
        "ad1803e34f93b6b05ad7f6285e6563109563631c55d04dc012c70e99283a02a1",
        "a412c87cdbfe414da6c4d3d6de360effe94a6159dadcaa5589e88e82fafa5000"),
    "default": (
        "94dca54895b0def7432f70094d96081b346dfc211c25fa725c1c87729a885c6d",
        "3b0f7b2605731c567e551b2c8dc73e48bd2ff7a2f065617cc540ae7172569ce6"),
}

# Every sentence of the German prompts that moved, as (what the prompt says now,
# what the file said). The template names the document where kwp said the plan
# and scenarios said the publication, in the sentences of the contract; the
# domain noun is the profile's role sentence. Each pair is template wording.
CHANGES = {
    "kwp": [
        ("aus EINEM Dokument.", "aus EINEM Plan."),
        ("den RAHMEN dieses Dokuments zu bestimmen: welche Szenarien es "
         "führt", "den RAHMEN dieses Plans zu bestimmen: welche Szenarien "
         "er führt"),
        ("die in diesem Dokument WIRKLICH vorkommt",
         "die in diesem Plan WIRKLICH vorkommt"),
        ("wie sie im Dokument stehen könnten", "wie sie im Plan stehen könnten"),
        ('"scenario_raw": "<Wort des Dokuments>"',
         '"scenario_raw": "<Wort des Plans>"'),
    ],
    "scenarios": [
        ("aus EINEM Dokument.", "aus EINER Publikation."),
        ("den RAHMEN dieses Dokuments zu bestimmen: welche Szenarien es "
         "führt", "den RAHMEN zu bestimmen: welche Szenarien die "
         "Publikation führt"),
        ("die in diesem Dokument WIRKLICH vorkommt", "die wirklich vorkommt"),
        ("`scenario_quote` das Wort aus `scenario_raw`",
         "`scenario_quote` den Namen aus `scenario_raw`"),
        ("wie sie im Dokument stehen könnten",
         "wie sie in der Publikation stehen könnten"),
        ('"scenario_raw": "<Wort des Dokuments>"',
         '"scenario_raw": "<Name der Publikation>"'),
    ],
    "default": [],
}

REQUIRED = ("role", "pair_example", "raw_word", "year_rules")

_names = itertools.count(1)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def file_of(name: str) -> str:
    return (HOMES[name] / "prompts" / "extraction" / "frame.md").read_text(
        encoding="utf-8")


def parts_of(text: str) -> dict:
    """The parts of a parts file, as the loader reads them."""
    def fail(message, part=None):
        return AssertionError(message)
    return prompts.read_parts(prompts._split(text)[1], fail)


def without_part(text: str, name: str) -> str:
    """The parts file with one section gone."""
    head, *sections = text.split("<!-- part: ")
    kept = [s for s in sections if not s.startswith(f"{name} -->")]
    assert len(kept) == len(sections) - 1, name
    return head + "".join("<!-- part: " + s for s in kept)


def put_back(name: str, text: str) -> str:
    """The text of a German prompt with each moved sentence as the file said
    it, each of them found once."""
    for new, old in CHANGES[name]:
        assert text.count(new) == 1, (name, new)
        text = text.replace(new, old)
    return text


def frame_of(name: str) -> prompts.Prompt:
    return prompts.load(FRAME, load_profile(name))


@pytest.fixture
def make(tmp_path, monkeypatch):
    """Profiles written to disk, each under a name of its own: `build(extends,
    language, phrases, frame)` returns the loaded profile."""
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))

    def build(*, extends, language=None, phrases=None, frame=None):
        name = f"frame_{next(_names)}"
        home = tmp_path / name
        write(home / "__init__.py", "")
        write(home / "profile.py",
              "from docpipe.profile import Profile\n"
              f"PROFILE = Profile(name={name!r}, extends={extends!r})\n")
        lines = []
        if language is not None:
            lines.append(f"CONTRACT_LANGUAGE = {language!r}")
        if phrases is not None:
            lines.append(f"PHRASES = {phrases!r}")
        if lines:
            write(home / "extraction.py", "\n".join(lines) + "\n")
        if frame is not None:
            write(home / "prompts" / "extraction" / "frame.md", frame)
        importlib.invalidate_caches()           # a folder made a moment ago
        return load_profile(name)

    return build


def refusal(profile) -> prompts.PromptPartsError:
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load(FRAME, profile)
    return raised.value


# ---------------------------------------------------------------------------
# The prompt is the template with the parts put in AND nothing else
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BEFORE))
def test_the_frame_prompt_is_the_template_with_the_profiles_parts_and_nothing_else(
        name):
    """Built from the two files by hand: the template's text with each slot
    given the part of that name, and the facts filled."""
    prompt = frame_of(name)
    template = contract.template_path(LANGUAGE[name], "frame").read_text(
        encoding="utf-8").split("---\n", 2)[2]
    parts = parts_of(file_of(name))
    by_hand = template
    for part, text in parts.items():
        by_hand = by_hand.replace("{{" + part + "}}", text)
    for part in contract.read(LANGUAGE[name], "frame").optional:
        by_hand = by_hand.replace("{{" + part + "}}", "")
    facts = contract.facts(load_profile(name), ["frame_options"])
    by_hand = by_hand.replace("{{frame_options}}", facts["frame_options"])
    assert prompt.text == by_hand
    assert "{{" not in by_hand, "a slot of the template was not given"
    assert prompt.meta == {"temperature": 0, "max_tokens": 4096}
    assert prompt.id == FRAME
    assert prompt.composition["template"] == "frame"
    assert prompt.composition["language"] == LANGUAGE[name]


def test_the_text_moves_with_the_template_and_with_every_part(tmp_path,
                                                              monkeypatch, make):
    """Built to fail: a prompt that stayed the same when a part or the
    template changed would not be made of them."""
    base = frame_of("kwp")
    for part in REQUIRED:
        text = file_of("kwp")
        old = parts_of(text)[part]
        moved = make(extends="kwp", language="de",
                     frame=text.replace(old, old + " Nachtrag.", 1))
        assert prompts.load(FRAME, moved).text != base.text, part
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    path = folder / "de" / "frame.md"
    write(path, path.read_text(encoding="utf-8").replace(
        "Keine Fragen.", "Keine Frage."))
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    assert "Keine Frage." in frame_of("kwp").text
    assert "Keine Frage." in frame_of("scenarios").text
    assert "Keine Frage." not in frame_of("default").text


# ---------------------------------------------------------------------------
# It differs from the file it was by exactly the sentences listed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BEFORE))
def test_the_frame_prompt_is_the_file_it_was_but_for_the_listed_sentences(name):
    prompt = frame_of(name)
    assert sha(put_back(name, prompt.text)) == BEFORE[name][1]
    # the fingerprint is the sha of the file a person would have written
    assert prompt.sha256 == sha(FRONT + prompt.text)
    assert prompts.versions([FRAME], load_profile(name)) == {
        FRAME: prompt.sha256}
    if CHANGES[name]:
        assert prompt.sha256 != BEFORE[name][0]
    else:
        # the built-in profile is the template's own wording: nothing moved
        assert prompt.sha256 == BEFORE[name][0]
        assert sha(prompt.text) == BEFORE[name][1]


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_sentence_that_is_not_listed_is_found(name):
    """Built to fail: one word moved anywhere in the prompt, and what is put
    back is not the file it was."""
    text = frame_of(name).text
    for old, new in [("Wähle, generiere nicht.", "Wähle, erfinde nicht."),
                     ("Keine Fragen.", "Keine Frage."),
                     ("Lies jeden", "Lies alle"),
                     ("Wiederhole sie nicht", "Wiederhole sie")]:
        assert text.count(old) == 1, old
        assert sha(put_back(name, text.replace(old, new))) != BEFORE[name][1]
    # and one that is listed, moved back by hand, is the file it was
    assert sha(put_back(name, text)) == BEFORE[name][1]


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_every_listed_sentence_is_the_wording_of_the_template(name):
    """Class of each change: template wording means the sentence is the
    template's, and not a part of the profile."""
    template = contract.template_path("de", "frame").read_text(encoding="utf-8")
    parts = parts_of(file_of(name))
    for new, old in CHANGES[name]:
        assert new in template, new
        assert not any(new in part for part in parts.values()), new
        assert new != old


def test_that_check_can_fail():
    """Built to fail: a sentence that a part of kwp holds is no template
    wording."""
    template = contract.template_path("de", "frame").read_text(encoding="utf-8")
    parts = parts_of(file_of("kwp"))
    assert "Zwei getrennte Belege" not in template
    assert any("Zwei getrennte Belege" in part for part in parts.values())


# ---------------------------------------------------------------------------
# Every part of the profile reaches the prompt word for word
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BEFORE))
def test_every_part_of_a_profile_stands_in_its_prompt_word_for_word(name):
    text = frame_of(name).text
    parts = parts_of(file_of(name))
    assert set(REQUIRED) <= set(parts)
    for label, part in parts.items():
        assert text.count(part) == 1, label
        for line in part.split("\n"):
            assert line.strip() in text, (label, line)


@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_a_changed_letter_in_a_part_is_a_changed_prompt_and_nothing_else(
        name, make):
    """Built to fail: one letter of the role and of the year rules changed,
    and exactly that letter is changed in the prompt."""
    text, prompt = file_of(name), frame_of(name)
    parts = parts_of(text)
    for label in ("role", "year_rules"):
        part = parts[label]
        letter = next(i for i, c in enumerate(part) if c == "e")
        other = part[:letter] + "X" + part[letter + 1:]
        profile = make(extends=name, language=LANGUAGE[name],
                       frame=text.replace(part, other, 1))
        moved = prompts.load(FRAME, profile)
        assert moved.sha256 != prompt.sha256, label
        assert moved.text == prompt.text.replace(part, other, 1), label
        assert other in moved.text and part not in moved.text


# ---------------------------------------------------------------------------
# A profile has the sentences it had and gets none it lacked
# ---------------------------------------------------------------------------

def test_each_profile_keeps_what_it_has_in_the_places_where_they_differ():
    kwp, scenarios, default = (frame_of(n).text for n in
                               ("kwp", "scenarios", "default"))
    # a second sentence on the key of the raw word: kwp alone has one
    more = ("Führt der Plan mehrere Zielszenarien nebeneinander, gehört der "
            "konkrete Name hierhin.")
    assert more in kwp and more not in scenarios and more not in default
    assert ('("SSP2-4.5", "Current Policies", "NDC pathway").\n'
            in scenarios)
    assert '("Baseline", "Forecast", "Option B").\n' in default
    # what it says of a number that is no year: kwp says nothing in brackets
    assert "Ist sie keines, lass sie weg." in kwp
    assert ("Ist sie keines (eine Zahl in einer Einheit, ein Gesetzesdatum, "
            "eine Literaturangabe), lass sie weg.") in scenarios
    assert "If it is not one (a number in a unit, the date of a law, a " \
           "bibliographic reference), leave it out." in default
    assert "(eine Zahl" not in kwp


def test_a_profile_gains_a_sentence_only_by_giving_the_part_and_loses_it_by_dropping_it(
        make):
    """Built to fail: kwp given the parenthesis scenarios has, scenarios with
    it dropped, kwp with its second sentence dropped. Nothing else moves and no
    space or line is left behind."""
    kwp, scenarios = file_of("kwp"), file_of("scenarios")
    given = make(extends="kwp", language="de",
                 frame=kwp + "\n<!-- part: candidates_examples -->\n"
                 " (eine Zahl in einer Einheit)\n")
    assert ("Ist sie keines (eine Zahl in einer Einheit), lass sie weg."
            in prompts.load(FRAME, given).text)
    dropped = make(extends="scenarios", language="de", frame=without_part(
        scenarios, "candidates_examples"))
    after = prompts.load(FRAME, dropped).text
    assert "Ist sie keines, lass sie weg." in after
    assert after == frame_of("scenarios").text.replace(
        " (eine Zahl in einer Einheit, ein Gesetzesdatum, eine "
        "Literaturangabe)", "", 1)
    fewer = make(extends="kwp", language="de",
                 frame=without_part(kwp, "scenario_raw_more"))
    text = prompts.load(FRAME, fewer).text
    assert 'Umsetzungsszenario 2").\n' in text
    assert text == frame_of("kwp").text.replace(
        " Führt der Plan mehrere Zielszenarien nebeneinander, gehört der "
        "konkrete Name hierhin.", "", 1)
    quiet = make(extends="kwp", language="de",
                 frame=without_part(kwp, "quote_why"))
    assert "kopiert. Steht beides in derselben Passage" in prompts.load(
        FRAME, quiet).text


def test_a_part_written_without_the_space_that_joins_it_is_glued_to_the_sentence_before(
        make):
    """Built to fail, and the reason the parts that join a sentence start with
    a space: the loader puts a part in as it is written."""
    kwp = file_of("kwp")
    glued = make(extends="kwp", language="de", frame=kwp.replace(
        "\n Zwei getrennte Belege", "\nZwei getrennte Belege", 1))
    assert "kopiert.Zwei getrennte Belege" in prompts.load(FRAME, glued).text
    assert "kopiert.Zwei" not in frame_of("kwp").text


# ---------------------------------------------------------------------------
# The key of the closed list is the one the request sends
# ---------------------------------------------------------------------------

SOURCE = Source(owner_kind="section", owner_id=1,
                text="Der Verbrauch lag im Jahr 2020 bei 120 GWh.")
YEAR = fields.Slot(name="year", kind=fields.NUMBER)
SCENARIO = fields.Slot(name="scenario", kind=fields.CHOICE, options=(
    fields.Option(label="target", uri="t", synonyms=("Zielszenario",)),))


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_the_german_prompt_names_the_key_the_request_sends(name, monkeypatch):
    monkeypatch.setenv(ENV_VAR, name)
    key = wording.say("frame_options", slot="scenario")
    assert key == "scenarios"
    assert key in runner._frame_payload([SOURCE], [SCENARIO, YEAR])
    text = frame_of(name).text
    assert text.count(f'"{key}"') == 2
    assert f'- `scenario` ist einer der Schlüssel aus "{key}".' in text
    assert f'oder mit dem Schlüssel aus "{key}", der gepasst hätte.' in text


def test_a_phrase_that_names_the_coordinate_moves_the_key_in_the_prompt_too(
        make, monkeypatch):
    """Built to fail: the phrase of the built-in profile, `{slot}_options`,
    in a German profile. The prompt says the key the request sends for
    `scenario`, filled, and not the phrase with its braces."""
    child = make(extends="kwp", phrases={"frame_options": "{slot}_options"})
    monkeypatch.setenv(ENV_VAR, child.name)
    key = wording.say("frame_options", slot="scenario")
    assert key == "scenario_options"
    assert key in runner._frame_payload([SOURCE], [SCENARIO, YEAR])
    assert contract.facts(child, ["frame_options"]) == {"frame_options": key}
    text = prompts.load(FRAME, child).text
    assert text.count(f'"{key}"') == 2
    assert "{slot}" not in text and '"scenarios"' not in text
    # the same phrase, said as kwp says it, is kwp's prompt
    assert prompts.load(FRAME, child).text == frame_of("kwp").text.replace(
        '"scenarios"', f'"{key}"')


def test_the_english_prompt_names_no_key_that_could_go_stale(make, monkeypatch):
    text = frame_of("default").text
    assert ("`scenario` is one of the keys of the list the request gives for "
            "`scenario`.") in text
    assert "_options" not in text and '"scenarios"' not in text
    # whatever the phrase says: the prompt does not repeat it
    child = make(extends="default", phrases={"frame_options": "scenarios"})
    assert prompts.load(FRAME, child).text == text


# ---------------------------------------------------------------------------
# The language is that of the profile that owns the parts file
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_frame_prompt_is_in_the_language_of_its_profile(name):
    text = frame_of(name).text
    other = OPENING["en" if LANGUAGE[name] == "de" else "de"]
    assert OPENING[LANGUAGE[name]] in text
    assert other not in text


def test_a_child_reads_the_parts_it_inherits_in_the_language_of_their_owner(
        make):
    """Built to fail: a child that declares the other language still gets the
    parts of the profile it extends in the language those are in."""
    german = prompts.load(FRAME, make(extends="kwp", language="en"))
    assert german.text == frame_of("kwp").text
    assert german.composition["language"] == "de"
    english = prompts.load(FRAME, make(extends="default", language="de"))
    assert english.text == frame_of("default").text
    assert english.composition["language"] == "en"


def test_a_child_with_parts_of_its_own_says_its_language_itself(make):
    # the key of the list is a phrase of the profile that asks, and kwp's is
    # not the built-in one
    own = make(extends="default", language="de", frame=file_of("kwp"),
               phrases={"frame_options": "scenarios"})
    assert prompts.load(FRAME, own).text == frame_of("kwp").text
    silent = make(extends="default", frame=file_of("kwp"))
    problem = refusal(silent)
    assert "CONTRACT_LANGUAGE" in str(problem)
    assert str(contract.languages()) in str(problem)
    elvish = make(extends="default", language="xx", frame=file_of("kwp"))
    assert str(contract.languages()) in str(refusal(elvish))


# ---------------------------------------------------------------------------
# A request for the frame carries the text and no mark of a template
# ---------------------------------------------------------------------------

@pytest.fixture
def asker(monkeypatch):
    """(a way to build the frame asker for a profile, the model it asks)."""
    client = Recorder()
    monkeypatch.setattr(runner, "_client", lambda: client)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(runner, "RETRY_TEMPERATURE_STEP", 0.0)
    spec = load_spec(json.loads((HOMES["kwp"] / "extraction_spec.json")
                                .read_text(encoding="utf-8")))

    def build(name):
        monkeypatch.setenv(ENV_VAR, name)
        slots = fields.frame_slots(
            spec, load_profile(name).component("extraction", "FRAME") or ())
        assert slots, "the profile has no frame"
        return runner.make_frame_asker(), slots
    return build, client


def test_a_request_for_the_frame_carries_the_composed_text_and_no_mark(asker):
    build, client = asker
    ask, slots = build("kwp")
    ask([SOURCE], slots)
    assert client.sent, "no request was sent"
    system = client.sent[0]["messages"][0]
    prompt = frame_of("kwp")
    assert system == {"role": "system", "content": prompt.text}
    assert "{{" not in system["content"] and "<!--" not in system["content"]
    assert client.sent[0]["temperature"] == float(prompt.meta["temperature"])


def test_the_asker_is_not_built_on_a_prompt_with_an_open_placeholder(asker,
                                                                      make,
                                                                      monkeypatch):
    """Built to fail: the part with `{{x}}` in it, and no request is sent."""
    build, client = asker
    text = file_of("kwp")
    open_role = text.replace("deutsche kommunale", "deutsche {{x}} kommunale", 1)
    assert "{{x}}" in open_role
    profile = make(extends="kwp", language="de", frame=open_role)
    monkeypatch.setenv(ENV_VAR, profile.name)
    with pytest.raises(prompts.PromptPartsError):
        runner.make_frame_asker()
    assert client.sent == []


# ---------------------------------------------------------------------------
# A parts file that lacks a part, misspells one or leaves one open
# ---------------------------------------------------------------------------

def named(problem, profile, part, language="de") -> None:
    """The refusal names the prompt, the part, the profile and both files."""
    assert problem.prompt_id == FRAME
    assert problem.profile == profile.name
    assert problem.part == part
    files = dict(problem.files)
    assert files["parts file"] == str(
        profile.prompts_dir / "extraction" / "frame.md")
    assert files["template"] == str(contract.template_path(language, "frame"))


@pytest.mark.parametrize("part", REQUIRED)
def test_a_parts_file_without_a_required_part_is_refused_and_everything_is_named(
        part, make):
    profile = make(extends="kwp", language="de",
                   frame=without_part(file_of("kwp"), part))
    problem = refusal(profile)
    assert f"part '{part}' is missing" in str(problem)
    named(problem, profile, part)
    # the same file with its part is the profile's prompt
    whole = make(extends="kwp", language="de", frame=file_of("kwp"))
    assert prompts.load(FRAME, whole).text == frame_of("kwp").text


def test_the_parts_that_are_optional_can_all_be_left_out(make):
    """Built to fail the other way: a profile with only what the template
    requires is a prompt, and says nothing of what it did not give."""
    keep = {name: text for name, text in parts_of(file_of("kwp")).items()
            if name in REQUIRED}
    minimal = FRONT.replace("---\ntemperature", "---\ntemplate: frame\n"
                            "temperature", 1) + "".join(
        f"<!-- part: {name} -->\n{text}\n\n" for name, text in keep.items())
    text = prompts.load(FRAME, make(extends="kwp", language="de",
                                    frame=minimal)).text
    assert "Zwei getrennte Belege" not in text
    assert "Führt der Plan" not in text
    assert "kopiert. Steht beides" in text
    assert "Ist sie keines, lass sie weg." in text


def test_a_misspelt_part_is_refused_and_the_near_one_named(make):
    profile = make(extends="kwp", language="de", frame=file_of("kwp").replace(
        "part: year_rules", "part: year_rule", 1))
    problem = refusal(profile)
    assert "did you mean 'year_rules'" in str(problem)
    assert problem.part == "year_rule"
    assert problem.prompt_id == FRAME and problem.profile == profile.name


@pytest.mark.parametrize("part", ["role", "year_rules", "quote_why"])
def test_a_part_with_an_open_placeholder_is_refused_before_any_request(
        part, make):
    text = file_of("kwp")
    old = parts_of(text)[part]
    profile = make(extends="kwp", language="de",
                   frame=text.replace(old, old + " {{x}}", 1))
    problem = refusal(profile)
    assert "{{x}}" in str(problem) and problem.part == part
    named(problem, profile, part)


def test_the_doctor_reads_the_frame_prompt_and_fails_a_broken_one(make):
    ok = doctor._prompts_of("extract", load_profile("kwp"))
    assert [line.status for line in ok] == [doctor.OK]
    broken = make(extends="kwp", language="de",
                  frame=without_part(file_of("kwp"), "year_rules"))
    (line,) = doctor._prompts_of("extract", broken)
    assert line.status == doctor.FAIL
    assert "year_rules" in line.detail and FRAME in line.detail
    assert "<!-- part: name -->" in line.hint


# ---------------------------------------------------------------------------
# Nothing goes stale because the frame prompt is composed
# ---------------------------------------------------------------------------

def test_a_stamp_written_with_the_old_frame_prompt_is_current(tmp_path,
                                                              monkeypatch):
    """The stamp records the sha256 of every prompt and compares none of
    them: a harvest stamped when the frame prompt was one file is current for
    the composed one, whose sha256 is another."""
    from tests.test_extraction_topup import SPEC
    monkeypatch.setenv(ENV_VAR, "kwp")
    new = runner._stamp_current("a" * 64, "b" * 16, SPEC)
    assert new[FRAME] == frame_of("kwp").sha256
    old = {**new, FRAME: BEFORE["kwp"][0]}
    assert old[FRAME] != new[FRAME], "the prompt really is another one"
    path = write(tmp_path / "plan.stamp.json", json.dumps(old))
    assert runner.stale(path, new) == []


def test_that_comparison_can_see_a_question_that_moved(tmp_path, monkeypatch):
    """Built to fail: the stamp of the case above with one question that is
    not today's is stale for that question, and for nothing else."""
    from tests.test_extraction_topup import SPEC
    monkeypatch.setenv(ENV_VAR, "kwp")
    new = runner._stamp_current("a" * 64, "b" * 16, SPEC)
    axis = next(key for key in new if key.startswith("axis/"))
    old = {**new, FRAME: BEFORE["kwp"][0], axis: "moved"}
    path = write(tmp_path / "plan.stamp.json", json.dumps(old))
    assert runner.stale(path, new) == [axis]


# ---------------------------------------------------------------------------
# The template says the same in both languages
# ---------------------------------------------------------------------------

def test_the_frame_template_is_held_in_both_languages_with_the_same_shape():
    from tests.test_contract_templates import EN_ONLY, folder_problems
    examined, problems = folder_problems(EN_ONLY)
    assert "frame" in examined
    assert problems == []
    de, en = contract.read("de", "frame"), contract.read("en", "frame")
    assert de.shape() == en.shape()
    assert de.required == en.required == REQUIRED
    assert set(de.optional) == {"quote_why", "scenario_raw_more",
                                "candidates_examples"}
    # no block and no numbered rule: the contract of the frame is prose
    assert de.blocks == () and de.rules == ()
    assert "frame" not in EN_ONLY, "the frame has nothing only English says"


def test_an_english_template_that_lost_a_part_is_found(tmp_path, monkeypatch):
    """Built to fail: the English frame template without an optional part, and
    without a required one."""
    from tests.test_contract_templates import folder_problems
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    path = folder / "en" / "frame.md"
    text = path.read_text(encoding="utf-8")
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    assert [p for p in folder_problems({})[1] if p.startswith("frame:")] == []
    write(path, text.replace("candidates_examples", "candidate_examples"))
    found = [p for p in folder_problems({})[1] if p.startswith("frame:")]
    assert found and "candidates_examples" in found[0]
    write(path, text.replace(", raw_word", "", 1).replace(
        "{{raw_word}}", "", 1))
    found = [p for p in folder_problems({})[1] if p.startswith("frame:")]
    assert found and "raw_word" in found[0]


def test_the_german_template_names_the_key_by_the_fact_and_the_english_does_not():
    de = contract.template_path("de", "frame").read_text(encoding="utf-8")
    en = contract.template_path("en", "frame").read_text(encoding="utf-8")
    assert de.count("{{frame_options}}") == 2
    assert "{{frame_options}}" not in en
    assert '"scenarios"' not in de and '"scenarios"' not in en
