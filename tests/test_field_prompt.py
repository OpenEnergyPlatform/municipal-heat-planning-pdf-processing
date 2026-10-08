"""The field prompt is the core's template with the profile's own parts put in,
and each profile says what it said.

Promised: the field prompt of a profile is the core's field template of the
profile's language with the profile's parts put in AND it names the keys of the
request in the order the request has them AND a profile has the rules it had:
what it leaves out it lacked and what it keeps it still says, with the rules
numbered without a gap and every pointer at the rule it names AND what the
profile writes about its own corpus reaches the prompt word for word AND the
least length of a quote, the word for "not stated" and the two keys of an entry
are the code's and not typed AND a parts file that lacks a part, misspells one,
leaves a placeholder open, leaves a block out whose part it still writes, or
leaves a rule number with no rule is found before any request is sent AND the
field request carries that text and no mark of a template AND the sha256 a run
records is that of the text sent, and a harvest stamped under the prompt as it
was is still current.

Each AND is its own test below, and each has the case built to break it: a
template with two keys swapped, a profile that does not leave out what it
lacked, a part that is deleted, misspelt or open, a block left out whose part
is still there, a rule whose text is gone, a patched length of a quote.

The sentences each profile had are written here as witnesses, taken from the
prompts as they were before they were cut into parts: they are the other end of
the comparison, since the parts files cannot be compared with themselves. No
model, no GPU.
"""
import hashlib
import importlib
import itertools
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docpipe import doctor, prompts
from docpipe.extraction import contract, fields, runner, verify, wording
from docpipe.extraction.pipeline import Row, Source
from docpipe.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent
FIELD = "extraction/field"
HOMES = {"kwp": ROOT / "profiles" / "kwp",
         "scenarios": ROOT / "profiles" / "scenarios",
         "default": ROOT / "docpipe" / "builtin" / "default"}
LANGUAGE = {"kwp": "de", "scenarios": "de", "default": "en"}
OPENING = {"de": "Du bestimmst EINE Angabe zu", "en": "You determine ONE piece"}
# What the profiles say about the model's parameters, which this change does not
# touch.
SETTINGS = {"kwp": {"temperature": 0, "max_tokens": 6144},
            "scenarios": {"temperature": 0, "max_tokens": 5120},
            "default": {"temperature": 0, "max_tokens": 5120}}
# The blocks a profile leaves out and the parts it words a block with.
OMITTED = {
    "kwp": ["by_similarity", "domain_slot_2", "rows_source", "same_forms"],
    "scenarios": ["base_years", "by_meaning", "closed_out", "found_next",
                  "no_guessing", "target_years", "year_value"],
    "default": ["closed_out", "found_next", "no_guessing"],
}
OVERRIDES = {"kwp": ["closed_out_text"],
             "scenarios": ["rows_carry", "unstated_when"], "default": []}
# The numbered rules each profile has, in order: the ones it had before, with
# the numbers of its own file (kwp 9, scenarios 8, default 9).
RULES = {
    "kwp": ["value", "value_raw", "quote", "domain_1", "every_row",
            "closed_out", "by_meaning", "need_more", "corrections"],
    "scenarios": ["value", "value_raw", "quote", "domain_1", "domain_2",
                  "every_row", "need_more", "corrections"],
    "default": ["value", "value_raw", "quote", "domain_1", "domain_2",
                "every_row", "by_meaning", "need_more", "corrections"],
}
# What each profile says, by a sentence of the prompts as they were: True where
# the profile had it, False where it did not. A profile that gains a sentence
# it lacked or loses one it had fails here.
WITNESS = {
    "de": {
        "by_meaning": "Entscheide nach der Bedeutung",
        "closed_out": "das Gegenteil einer Klasse",
        "base_years": '"base_years" (nur bei der Frage nach dem Jahr',
        "target_years": '"target_years" (nur bei der Frage nach dem Jahr',
        "year_value": 'Ist "field.name" gleich "year"',
        "literal_copy": "dieselbe Beugung, dieselbe Reihenfolge",
        "no_guessing": "Rate nicht und ergänze nichts aus Weltwissen",
        "rows_source": "Steht die eigene Quelle der Zeile",
        "same_forms": "Beide Formen bedeuten dasselbe",
        "by_similarity": "per Ähnlichkeit gesucht",
    },
    "en": {
        "by_meaning": "Decide by meaning",
        "closed_out": "the opposite of a class",
        "base_years": '"base_years" (only when the question asks',
        "target_years": '"target_years" (only when the question asks',
        "year_value": "If the question asks for a year",
        "no_guessing": "Do not guess and do not add anything from world",
        "rows_source": "If the row's own source",
        "same_forms": "Both forms mean the same",
        "by_similarity": "The search is then by similarity",
        "options_explained": "is always among them",
    },
}
SAYS = {
    "kwp": {"by_meaning", "closed_out", "base_years", "target_years",
            "year_value", "literal_copy", "no_guessing"},
    "scenarios": {"rows_source", "same_forms", "by_similarity"},
    "default": {"by_meaning", "base_years", "target_years", "year_value",
                "rows_source", "same_forms", "by_similarity",
                "options_explained"},
}
# Sentences of each profile's own about its corpus, as they stood in its
# prompt before it was cut into parts. Two of kwp's are as the owner had them
# rewritten on 2026-10-06: the passages inside its examples are descriptions
# in << >> that no plan prints, because the model cited the example passages
# as its quote (48,737 dropped answers of one harvest).
DOMAIN = {
    "kwp": [
        'RICHTIG für das Jahr einer Zahl aus p85_tbl0: "<<Titel hinter '
        '„[p85_tbl0:“, wörtlich, mit der Jahreszahl darin>>"',
        '"| Energieträger | <<Sektor 1>> Endenergie in kWh/a | <<Sektor 2>> '
        'Endenergie in kWh/a | <<Sektor 3>> Endenergie in kWh/a |" bestimmt '
        'den SEKTOR, und die Zahl mit "column": 2 gehört zu <<Sektor 1>>.',
        'Enthält "options" Einträge, die ausdrücklich das Gegenteil einer '
        'Klasse sind (Summenzeile, Restposition, ausdrücklich unbekannter '
        'Wert, Prozentanteil, Potenzial), sind das richtige Antworten und '
        'keine Notlösung.',
        'Rate das Jahr nicht aus dem Erscheinungsjahr des Plans.',
    ],
    "scenarios": [
        'Dafür führt die Liste den Eintrag "Szenario-Familie" — WÄHLE IHN.',
        'Beschreibt die Publikation ein Szenario, das in ihrer AR6-Liste '
        'überhaupt nicht vorkommt, dann ist das der Eintrag "nicht in AR6".',
        'etwa Zeilennummern eines Manuskripts („Horizon 311 2020“): sie '
        'gehören zur Zeichenkette.',
        '"das erste Szenario" ist kein Name aus dem Dokument und keine '
        'gültige Antwort.',
    ],
    "default": [
        'If the document describes something that none of the options covers '
        'at all, choose the entry the list has for that case, if it has one.',
        'such as the line numbers of a manuscript ("Annual Report 311 2020")',
        'WRONG: "scenario" — too short, finds everything and nothing.',
        'Do not guess the year from the year the document was published.',
    ],
}

_names = itertools.count(1)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def file_of(name: str) -> str:
    return (HOMES[name] / "prompts" / "extraction" / "field.md").read_text(
        encoding="utf-8")


def text_of(name: str) -> str:
    return prompts.load(FIELD, load_profile(name)).text


def says(name: str, text: str) -> set:
    """Which of the witnessed sentences the text holds."""
    return {key for key, sentence in WITNESS[LANGUAGE[name]].items()
            if sentence in text}


def numbered(text: str) -> dict:
    """{number: the rest of the line of the rule that has it}."""
    return {int(number): body
            for number, body in re.findall(r"^(\d+)\. ?(.*)$", text, re.M)}


@pytest.fixture
def make(tmp_path, monkeypatch):
    """Profiles written to disk under a name of their own: `build(extends,
    language, field)` returns the loaded profile."""
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))

    def build(*, extends, language=None, field=None):
        name = f"field_{next(_names)}"
        home = tmp_path / name
        write(home / "__init__.py", "")
        write(home / "profile.py",
              "from docpipe.profile import Profile\n"
              f"PROFILE = Profile(name={name!r}, extends={extends!r})\n")
        if language is not None:
            write(home / "extraction.py", f"CONTRACT_LANGUAGE = {language!r}\n")
        if field is not None:
            write(home / "prompts" / "extraction" / "field.md", field)
        importlib.invalidate_caches()           # a folder made a moment ago
        return load_profile(name)

    return build


def refusal(profile) -> prompts.PromptPartsError:
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load(FIELD, profile)
    return raised.value


def cut(text: str, part: str) -> str:
    """A parts file without one of its sections."""
    pattern = rf"<!-- part: {part} -->\n.*?(?=<!-- part: |\Z)"
    cleaned, count = re.subn(pattern, "", text, flags=re.S)
    assert count == 1, part
    return cleaned


# ---------------------------------------------------------------------------
# It is the template of the profile's language with the profile's parts put in
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_field_prompt_is_the_template_of_its_language_with_the_parts_in(name):
    prompt = prompts.load(FIELD, load_profile(name))
    assert prompt.composition["template"] == "field"
    assert prompt.composition["language"] == LANGUAGE[name]
    assert prompt.composition["omitted"] == OMITTED[name]
    assert prompt.composition["overrides"] == OVERRIDES[name]
    assert prompt.text.startswith(OPENING[LANGUAGE[name]])
    # the parameters of the model are the profile's, as they were
    assert prompt.meta == SETTINGS[name]
    # and the template is the core's: its rules are the ones it names
    template = contract.read(LANGUAGE[name], "field")
    assert template.required == ("subject", "groups_note", "value_raw_is",
                                 "example_reply")


def test_that_comparison_fails_when_a_word_of_the_template_moves(
        tmp_path, monkeypatch):
    """Built to fail: the German template with one word changed is another
    prompt for the two German profiles and the same one for the English."""
    import shutil
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    path = folder / "de" / "field.md"
    text = path.read_text(encoding="utf-8")
    assert text.count("Quellen aus DEMSELBEN Dokument") == 1
    before = {name: prompts.load(FIELD, load_profile(name))
              for name in LANGUAGE}
    write(path, text.replace("Quellen aus DEMSELBEN Dokument",
                             "Quellen aus DERSELBEN Fundstelle"))
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    for name in ("kwp", "scenarios"):
        moved = prompts.load(FIELD, load_profile(name))
        assert "DERSELBEN Fundstelle" in moved.text
        assert moved.text != before[name].text
        assert moved.sha256 != before[name].sha256
    assert prompts.load(FIELD, load_profile("default")).text == \
        before["default"].text


# ---------------------------------------------------------------------------
# It names the keys of the request in the order the request has them
# ---------------------------------------------------------------------------

SOURCE = Source("table", 1, "| Erdgas | 241 |",
                {"document_id": 7, "page": 85, "block_id": "p85_tbl0",
                 "title": "Tabelle 17", "section_title": "Verbrauch"})
ROW = Row(label="R1", item_index=0,
          claim={"value": 241, "quote": "| Erdgas | 241 |", "unit": "MWh/a"})
YEAR = fields.Slot(name="year", kind=fields.NUMBER, question="Welches Jahr?")
BASES = [{"state": "base", "axis": "year", "year": 2020,
          "quote": "Das Basisjahr ist 2020."}]
TARGETS = [{"state": "target", "axis": "year", "year": 2045,
            "quote": "Das Zieljahr ist 2045."}]
CORRECTIONS = [{"row": "R1", "reason": "x"}]


def payload_keys(bases) -> list:
    """The keys of the object the field request sends, in its order."""
    return list(runner._field_payload([SOURCE], [ROW], YEAR, CORRECTIONS,
                                      {"R1": SOURCE}, bases))


def bullet_keys(text: str) -> list:
    return re.findall(r'^- "(\w+)"', text, re.M)


def test_the_payload_has_the_keys_the_prompt_names():
    """What the request sends: sources, rows, the plan's base years where there
    are any, then the field asked, and the corrections of a retry last. The
    prompt names the same keys, in the order kwp's prompt always had (the base
    years after the field, which is not the order of the request and is not
    read from it)."""
    assert payload_keys(BASES) == ["sources", "rows", "base_years", "fields",
                                   "corrections"]
    assert payload_keys(BASES + TARGETS) == [
        "sources", "rows", "base_years", "target_years", "fields",
        "corrections"]
    assert payload_keys(None) == ["sources", "rows", "fields", "corrections"]


def year_keys(name: str) -> list:
    """The keys of the plan's named years that this profile's prompt says."""
    said = says(name, text_of(name))
    return [key for key in ("base_years", "target_years") if key in said]


def expected_keys(years: list) -> list:
    """The order the prompts of kwp, scenarios and the built-in profile have
    their keys in once the rows and the fields stand as the request has them
    (plan 2.5, item 2): the named years, where a profile has them, come
    last."""
    return ["sources", "rows", "fields"] + list(years)


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_keys_are_named_as_the_request_has_them_in_kwps_order(name):
    named = bullet_keys(text_of(name))
    years = year_keys(name)
    offered = (BASES if "base_years" in years else []) + (
        TARGETS if "target_years" in years else [])
    sent = [key for key in payload_keys(offered or None)
            if key != "corrections"]
    # AND the same keys the request sends, none more and none fewer
    assert sorted(named) == sorted(sent)
    # AND in the order kwp had: the named years do not move above the field
    assert named == expected_keys(years)
    # the retry's key is the last thing the prompt describes
    last = numbered(text_of(name))[max(numbered(text_of(name)))]
    assert last.startswith('"corrections"')


def test_that_kwps_keys_are_not_moved_to_the_order_of_the_request(
        tmp_path, monkeypatch):
    """Built to fail: the German template with the bullet of the base years put
    above the bullet of "fields", the order the request has, is not kwp's."""
    import shutil
    folder = tmp_path / "contract"
    shutil.copytree(contract.TEMPLATE_ROOT, folder)
    path = folder / "de" / "field.md"
    text = path.read_text(encoding="utf-8")
    opening = "<!-- block: base_years -->\n- "
    closing = "<!-- /block -->\n"
    first = text.index(opening)
    bullet = text[first:text.index(closing, first)]
    fields_bullet = '- "fields"'
    moved = text.replace(bullet + closing, "", 1)
    moved = moved.replace(fields_bullet, bullet + closing + fields_bullet, 1)
    assert moved != text
    write(path, moved)
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", folder)
    named = bullet_keys(text_of("kwp"))
    assert named == ["sources", "rows", "base_years", "fields", "target_years"]
    assert named != expected_keys(year_keys("kwp"))


# ---------------------------------------------------------------------------
# A profile has the rules it had, numbered without a gap, pointed at rightly
# ---------------------------------------------------------------------------

def rules_of(prompt) -> list:
    """The numbered rules the template gives a prompt: the ones it has, minus
    those that lie in a block the prompt leaves out."""
    template = contract.read(prompt.composition["language"], "field")
    omitted = set(prompt.composition["omitted"])
    return [rule for rule in template.rules
            if not omitted & set(template.rule_blocks[rule])]


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_a_profile_has_the_rules_it_had_and_they_are_numbered_without_a_gap(
        name):
    prompt = prompts.load(FIELD, load_profile(name))
    assert rules_of(prompt) == RULES[name]
    assert sorted(numbered(prompt.text)) == list(range(1, len(RULES[name]) + 1))


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_a_profile_says_what_it_said_and_nothing_it_did_not(name):
    assert says(name, text_of(name)) == SAYS[name]


def test_a_profile_that_does_not_leave_out_what_it_lacked_is_found(make):
    """Built to fail: scenarios without the line that leaves out its missing
    rule says the by-meaning rule, which it never had, and has a rule more."""
    own = file_of("scenarios")
    assert "without: [base_years, target_years, year_value, no_guessing, " \
           "closed_out, by_meaning, found_next]" in own
    greedy = make(extends="scenarios", language="de", field=own.replace(
        "closed_out, by_meaning, found_next]", "closed_out, found_next]"))
    prompt = prompts.load(FIELD, greedy)
    assert says("scenarios", prompt.text) != SAYS["scenarios"]
    assert "by_meaning" in says("scenarios", prompt.text)
    assert len(numbered(prompt.text)) == len(RULES["scenarios"]) + 1


def test_a_profile_that_loses_a_rule_it_had_is_found(make):
    """Built to fail: kwp with its by-meaning rule left out has one rule less
    and no longer says it."""
    own = file_of("kwp")
    lost = make(extends="kwp", language="de", field=own.replace(
        "without: [", "without: [by_meaning, ", 1))
    prompt = prompts.load(FIELD, lost)
    assert says("kwp", prompt.text) == SAYS["kwp"] - {"by_meaning"}
    assert len(numbered(prompt.text)) == len(RULES["kwp"]) - 1


# what a pointer at a rule says it points at, and the rule that holds it
POINTERS = (
    (r"Regel (\d+) sagt, wie du sie benutzt", '"need_more"'),
    (r"Regel (\d+) gilt auch für sie", '"quote"'),
    (r"Rule (\d+) says how you use them", '"need_more"'),
    (r"under rule (\d+)\)", '"need_more"'),
    (r"Rule (\d+) applies to them too", '"quote"'),
)


def pointers_wrong(text: str) -> list:
    """The pointers of a prompt at a rule that is not the one they name."""
    rules = numbered(text)
    wrong = []
    for pattern, head in POINTERS:
        for number in re.findall(pattern, text):
            if head not in rules.get(int(number), ""):
                wrong.append((pattern, number))
    return wrong


@pytest.mark.parametrize("name, pointed", [("kwp", 3), ("scenarios", 0),
                                           ("default", 3)])
def test_every_pointer_at_a_rule_points_at_the_rule_it_names(name, pointed):
    text = text_of(name)
    found = sum(len(re.findall(pattern, text)) for pattern, _ in POINTERS)
    assert found == pointed
    assert pointers_wrong(text) == []


def test_the_pointers_follow_when_a_rule_is_left_out(make):
    """Built to fail: the built-in prompt with the three rules it can lose
    left out has its need_more rule as the seventh, and the pointers at it
    say seven. A text with the old number in one of them is found by the same
    check."""
    own = file_of("default")
    thin = make(extends="default", language="en", field=own.replace(
        "without: [no_guessing, closed_out, found_next]",
        "without: [no_guessing, closed_out, found_next, by_meaning]"))
    text = prompts.load(FIELD, thin).text
    assert numbered(text)[7].startswith('The year, and "need_more"')
    assert "Rule 7 says how you use them" in text
    assert "(except under rule 7)" in text
    assert pointers_wrong(text) == []
    assert text.count("Rule 7 says how you use them") == 2, (
        "the base years and the target years each point at it")
    stale = text.replace("Rule 7 says", "Rule 8 says", 1)
    assert pointers_wrong(stale) == [(r"Rule (\d+) says how you use them", "8")]


def empty_rules(text: str) -> list:
    """The numbers of rules that are a number and nothing else."""
    return [number for number, body in numbered(text).items()
            if not body.strip()]


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_no_rule_of_a_shipped_prompt_is_a_number_with_no_rule(name):
    assert empty_rules(text_of(name)) == []


def test_a_rule_number_with_no_text_behind_it_is_found(make):
    """Built to fail: scenarios without the part of its second rule about its
    corpus keeps the place of that rule, and the loader cannot know."""
    gone = make(extends="scenarios", language="de",
                field=cut(file_of("scenarios"), "domain_rule_2"))
    text = prompts.load(FIELD, gone).text
    assert empty_rules(text) == [5]


# ---------------------------------------------------------------------------
# A profile says "what is found comes as the next request" where it said it
# ---------------------------------------------------------------------------

FOUND = {"de": "Was gefunden wird, kommt als nächste Anfrage mit denselben Zeilen.",
         "en": "What is found comes as the next request with the same rows."}
# The first line of each profile's own example for the need_more rule.
EXAMPLE_OF_NEED_MORE = {"kwp": 'RICHTIG: ein ganzer Satz mit dem Wort',
                        "scenarios": 'RICHTIG: "The NDC scenario assumes',
                        "default": 'RIGHT: "The Forecast scenario assumes'}
# Whether the sentence stands before the example lines, as the prompts were.
FOUND_BEFORE_EXAMPLE = {"kwp": False, "scenarios": True, "default": True}


def need_more_rule(text: str) -> str:
    """The text of the need_more rule: from its number to the next rule that is
    not part of it."""
    start = re.search(r'^\d+\. (?:Das Jahr, und |The year, and )?"need_more"',
                      text, re.M)
    stop = re.search(r'^\d+\. "corrections"', text, re.M)
    return text[start.start():stop.start()]


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_sentence_that_says_where_what_is_found_goes_stands_once_where_it_stood(
        name):
    rule = need_more_rule(text_of(name))
    sentence = FOUND[LANGUAGE[name]]
    assert rule.count(sentence) == 1
    before = rule.index(sentence) < rule.index(EXAMPLE_OF_NEED_MORE[name])
    assert before is FOUND_BEFORE_EXAMPLE[name]


def test_a_profile_that_keeps_both_places_says_the_sentence_twice(make):
    """Built to fail: scenarios without the line that leaves the later place
    out says the sentence in both, which it did not."""
    own = file_of("scenarios")
    assert "closed_out, by_meaning, found_next]" in own
    twice = make(extends="scenarios", language="de", field=own.replace(
        "closed_out, by_meaning, found_next]", "closed_out, by_meaning]"))
    rule = need_more_rule(prompts.load(FIELD, twice).text)
    assert rule.count(FOUND["de"]) == 2


def test_a_profile_that_leaves_both_places_out_loses_the_sentence(make):
    """Built to fail: kwp with the later place left out has no such sentence
    any more, and the rule is shorter than the one it had."""
    own = file_of("kwp")
    lost = make(extends="kwp", language="de", field=own.replace(
        "without: [", "without: [found_next, ", 1))
    rule = need_more_rule(prompts.load(FIELD, lost).text)
    assert rule.count(FOUND["de"]) == 0
    assert need_more_rule(text_of("kwp")).count(FOUND["de"]) == 1


# ---------------------------------------------------------------------------
# What the profile writes about its own corpus reaches the prompt unchanged
# ---------------------------------------------------------------------------

def domain_missing(name: str, text: str) -> list:
    """The sentences of the profile's own that are not in the text."""
    return [sentence for sentence in DOMAIN[name] if sentence not in text]


@pytest.mark.parametrize("name", sorted(DOMAIN))
def test_the_profiles_own_sentences_stand_in_its_prompt_word_for_word(name):
    assert domain_missing(name, text_of(name)) == []


def test_a_sentence_of_the_profile_that_is_not_there_word_for_word_is_found(
        make):
    """Built to fail: kwp with one word of its rule about the columns written
    otherwise has that sentence no more."""
    own = file_of("kwp")
    assert own.count("gehört zu <<Sektor 1>>.") == 1
    changed = make(extends="kwp", language="de", field=own.replace(
        "gehört zu <<Sektor 1>>.", "gehört zu <<Sektor 2>>.", 1))
    text = prompts.load(FIELD, changed).text
    assert domain_missing("kwp", text) == [DOMAIN["kwp"][1]]
    assert domain_missing("kwp", text_of("kwp")) == []


def number_of(text: str, key: str) -> str:
    """The number of the rule that names *key* in its first words."""
    (found,) = [str(n) for n, body in numbered(text).items()
                if f'"{key}"' in body[:40]]
    return found


def parts_missing(name: str, text: str) -> list:
    """The sections of the profile's parts file that are not in the text, each
    with the word for "not stated" and the pointers at rules filled in."""
    body = file_of(name).split("---\n", 2)[2]
    parts = prompts.read_parts(body, lambda message, part=None: ValueError(
        message))
    assert {"subject", "groups_note", "value_raw_is", "example_reply"} <= set(
        parts)
    missing = []
    for label, part in parts.items():
        shown = part.replace("{{unstated}}", fields.UNSTATED)
        for rule in ("need_more", "quote"):
            shown = shown.replace("{{rule:" + rule + "}}", number_of(text, rule))
        assert "{{" not in shown, (label, shown)
        if shown not in text:
            missing.append(label)
    return missing


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_every_part_of_a_profile_stands_in_its_prompt_as_written(name):
    assert parts_missing(name, text_of(name)) == []


def test_a_part_that_is_not_in_the_text_as_written_is_found():
    """Built to fail: one letter of the text moved, and the part that held it
    is named."""
    text = text_of("kwp")
    assert "gehört EINMAL hin." in text
    assert parts_missing("kwp", text.replace("gehört EINMAL hin.",
                                             "gehört einmal hin.")) == [
        "groups_note"]


def test_a_changed_letter_of_a_part_is_a_changed_prompt(make):
    own = file_of("kwp")
    changed = make(extends="kwp", language="de",
                   field=own.replace("EINMAL hin.", "EINMAL hin!", 1))
    moved = prompts.load(FIELD, changed)
    now = prompts.load(FIELD, load_profile("kwp"))
    assert moved.sha256 != now.sha256
    assert "EINMAL hin!" in moved.text and "EINMAL hin!" not in now.text
    assert parts_missing("kwp", moved.text) == ["groups_note"]


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_example_reply_is_one_line_and_names_the_field_by_name(name):
    text = text_of(name)
    lines = [l for l in text.splitlines() if l.strip().startswith('{"fields"')]
    assert len(lines) == 1
    assert '"field":' not in text


# ---------------------------------------------------------------------------
# What the code decides is the code's
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, said", [
    ("kwp", "(mindestens {} Zeichen)"),
    ("scenarios", "(mindestens {} Zeichen)"),
    ("default", "(at least {} characters)")])
def test_the_least_length_of_a_quote_is_the_codes_number(name, said,
                                                         monkeypatch):
    profile = load_profile(name)
    before = prompts.load(FIELD, profile)
    assert said.format(verify.MIN_QUOTE_CHARS) in before.text
    monkeypatch.setattr(verify, "MIN_QUOTE_CHARS", 12)
    moved = prompts.load(FIELD, profile)
    assert said.format(12) in moved.text and said.format(8) not in moved.text
    assert moved.sha256 != before.sha256


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_word_for_not_stated_is_the_codes_word(name, monkeypatch):
    profile = load_profile(name)
    before = prompts.load(FIELD, profile).text
    assert before.count(f'"{fields.UNSTATED}"') >= 2
    monkeypatch.setattr(fields, "UNSTATED", "out:unknown")
    moved = prompts.load(FIELD, profile).text
    assert fields.UNSTATED == "out:unknown"
    assert moved.count('"out:unknown"') == before.count('"out:unstated"')
    assert '"out:unstated"' not in moved


@pytest.mark.parametrize("name", ["kwp", "default"])
def test_the_two_keys_of_an_entry_are_the_keys_the_request_sends(name,
                                                                 monkeypatch):
    """The rule that says how to decide by meaning names the keys by the same
    words the closed list is sent under: patched to other words, the prompt
    follows."""
    profile = load_profile(name)
    text = prompts.load(FIELD, profile).text
    rule = next(body for body in numbered(text).values()
                if body.startswith(("Entscheide nach", "Decide by meaning")))
    assert '"means"' in rule and '"spellings"' in rule
    table = wording.phrases(profile)
    monkeypatch.setitem(table, "option_means", "bedeutet")
    monkeypatch.setitem(table, "option_spellings", "Schreibweisen")
    moved = prompts.load(FIELD, profile).text
    assert '"bedeutet"' in moved and '"Schreibweisen"' in moved
    assert '"means"' not in moved and '"spellings"' not in moved


def test_a_profile_that_does_not_name_the_keys_is_not_moved_by_them(
        monkeypatch):
    """Scenarios has no by-meaning rule, so no key of an entry stands in its
    prompt: the words of the table are not in its text."""
    profile = load_profile("scenarios")
    before = prompts.load(FIELD, profile)
    table = wording.phrases(profile)
    monkeypatch.setitem(table, "option_means", "bedeutet")
    assert prompts.load(FIELD, profile).sha256 == before.sha256
    assert '"means"' not in before.text and '"spellings"' not in before.text


# ---------------------------------------------------------------------------
# The language is that of the profile that owns the parts file
# ---------------------------------------------------------------------------

def test_a_child_reads_the_parts_it_inherits_in_the_language_of_their_owner(
        make):
    """Built to fail: a child that declares the other language still gets the
    parts of the profile it extends in the language those are in."""
    german = make(extends="kwp", language="en")
    prompt = prompts.load(FIELD, german)
    assert prompt.path == HOMES["kwp"] / "prompts" / "extraction" / "field.md"
    assert prompt.composition["language"] == "de"
    assert prompt.text == text_of("kwp") and prompt.sha256 == prompts.load(
        FIELD, load_profile("kwp")).sha256
    english = make(extends="default", language="de")
    assert prompts.load(FIELD, english).text == text_of("default")


def test_a_profile_with_parts_of_its_own_says_its_language_itself(make):
    own = make(extends="default", language="de", field=file_of("kwp"))
    prompt = prompts.load(FIELD, own)
    assert prompt.composition["language"] == "de"
    assert prompt.text.startswith(OPENING["de"])
    # the words the code fills in are the profile's own, the built-in ones here
    assert "these passages do not state it" in prompt.text
    silent = make(extends="default", field=file_of("kwp"))
    problem = refusal(silent)
    assert "CONTRACT_LANGUAGE" in str(problem)
    assert str(contract.languages()) in str(problem)
    assert problem.prompt_id == FIELD and problem.profile == silent.name


# ---------------------------------------------------------------------------
# A parts file that is not right is found before a request is sent
# ---------------------------------------------------------------------------

def named(problem, profile, part) -> None:
    """The refusal names the prompt, the part, the profile and both files."""
    assert problem.prompt_id == FIELD
    assert problem.profile == profile.name
    assert problem.part == part
    files = dict(problem.files)
    assert files["parts file"] == str(
        profile.prompts_dir / "extraction" / "field.md")
    assert files["template"] == str(contract.template_path("de", "field"))


@pytest.mark.parametrize("part", ["subject", "groups_note", "value_raw_is",
                                  "example_reply"])
def test_a_parts_file_without_a_part_the_template_needs_is_refused(make, part):
    profile = make(extends="kwp", language="de",
                   field=cut(file_of("kwp"), part))
    problem = refusal(profile)
    assert f"{part!r} is missing" in str(problem)
    named(problem, profile, part)
    # the same file with the part is the profile's prompt
    whole = make(extends="kwp", language="de", field=file_of("kwp"))
    assert prompts.load(FIELD, whole).text == text_of("kwp")


def test_a_misspelt_part_is_refused_and_the_near_one_named(make):
    profile = make(extends="kwp", language="de", field=file_of("kwp").replace(
        "part: value_raw_is", "part: value_raw_it", 1))
    problem = refusal(profile)
    assert "value_raw_it" in str(problem)
    assert "did you mean 'value_raw_is'" in str(problem)


def test_a_part_with_a_placeholder_open_is_refused(make):
    profile = make(extends="kwp", language="de", field=file_of("kwp").replace(
        "auf einmal und gehört EINMAL hin.",
        "auf einmal und gehört {{EINMAL}} hin.", 1))
    problem = refusal(profile)
    assert "{{EINMAL}}" in str(problem) and problem.part == "groups_note"
    named(problem, profile, "groups_note")


def test_a_block_left_out_whose_part_is_still_written_is_refused(make):
    """The base years: the bullet and the rule go together. A profile that
    leaves the block out and keeps the rule it explains is refused."""
    profile = make(extends="kwp", language="de", field=file_of("kwp").replace(
        "without: [", "without: [base_years, ", 1))
    problem = refusal(profile)
    assert "base_years_rule" in str(problem)
    assert "base_years" in str(problem) and "without" in str(problem)
    named(problem, profile, "base_years_rule")


def test_the_doctor_reports_a_field_prompt_that_cannot_be_composed(make):
    broken = make(extends="kwp", language="de",
                  field=cut(file_of("kwp"), "groups_note"))
    (line,) = doctor._prompts_of("extract", broken)
    assert line.status == doctor.FAIL
    assert "groups_note" in line.detail and FIELD in line.detail
    assert "<!-- part: name -->" in line.hint
    for name in ("kwp", "scenarios"):
        (ok,) = doctor._prompts_of("extract", load_profile(name))
        assert ok.status == doctor.OK, name


# ---------------------------------------------------------------------------
# The field request carries that text and no mark of a template
# ---------------------------------------------------------------------------

class Client:
    """Answers with an empty field and keeps what it was asked."""

    def __init__(self):
        self.asked = []
        reply = NS(choices=[NS(message=NS(content='{"fields": {"carrier": '
                                         '{"answers": {}}}}',
                                         reasoning_content=None),
                               finish_reason="stop")], usage=None)
        self.chat = NS(completions=NS(
            create=lambda **kwargs: self.asked.append(kwargs) or reply))


CARRIER = fields.Slot(
    name="carrier", kind=fields.CHOICE, question="Welcher Träger?",
    options=(fields.Option(label="Erdgas", uri="u1", synonyms=("Gas",),
                           definition="ein Gas"),))


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_the_field_request_carries_the_composed_text_and_no_mark(
        name, monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    monkeypatch.setattr(runner, "MAX_MODEL_LEN", 32768)
    monkeypatch.setattr(runner, "ATTACH_IMAGES", False)
    client = Client()
    monkeypatch.setattr(runner, "_client", lambda: client)
    runner.make_field_asker()([SOURCE], [ROW], CARRIER, None, 7, None,
                              {"R1": SOURCE})
    (asked,) = client.asked
    system = asked["messages"][0]
    prompt = prompts.load(FIELD, load_profile(name))
    assert system == {"role": "system", "content": prompt.text}
    assert "{{" not in system["content"] and "<!--" not in system["content"]
    assert asked["temperature"] == SETTINGS[name]["temperature"]


def test_no_request_is_built_on_a_field_prompt_that_cannot_be_composed(
        make, monkeypatch):
    """Built to fail: a profile whose field prompt lacks a part is refused
    when the asker is made, before there is a request to send."""
    broken = make(extends="kwp", language="de",
                  field=cut(file_of("kwp"), "value_raw_is"))
    monkeypatch.setenv("DOCPIPE_PROFILE", broken.name)
    client = Client()
    monkeypatch.setattr(runner, "_client", lambda: client)
    with pytest.raises(prompts.PromptPartsError) as raised:
        runner.make_field_asker()
    assert raised.value.part == "value_raw_is"
    assert client.asked == []


# ---------------------------------------------------------------------------
# The fingerprint is that of the text sent, and nothing goes stale
# ---------------------------------------------------------------------------

def hand_written(raw: str, text: str) -> str:
    """The file a person would have written for the composed text: the front
    matter without the two keys of the loader, then the text."""
    front = raw.split("---\n", 2)[1].rstrip("\n")
    kept ="\n".join(line for line in front.split("\n")
                     if not line.startswith(("template:", "without:")))
    return f"---\n{kept}\n---\n{text}"


@pytest.mark.parametrize("name", sorted(LANGUAGE))
def test_the_fingerprint_is_the_sha_of_the_file_with_the_text_sent(name):
    prompt = prompts.load(FIELD, load_profile(name))
    assert prompt.sha256 == sha(hand_written(file_of(name), prompt.text))
    assert prompts.versions([FIELD], load_profile(name)) == {
        FIELD: prompt.sha256}


def test_the_fingerprint_moves_with_a_part_a_block_and_the_language(make):
    base = prompts.load(FIELD, load_profile("scenarios")).sha256
    own = file_of("scenarios")
    shas = {
        "a part": prompts.load(FIELD, make(
            extends="scenarios", language="de", field=own.replace(
                "keine gültige Antwort", "keine Antwort", 1))).sha256,
        "a block": prompts.load(FIELD, make(
            extends="scenarios", language="de", field=own.replace(
                "closed_out, by_meaning, found_next]",
                "closed_out, found_next]"))).sha256,
        "the language": prompts.load(
            FIELD, load_profile("default")).sha256,
    }
    assert base not in shas.values()
    assert len(set(shas.values())) == 3


def test_a_stamp_from_before_the_prompt_was_composed_is_current(
        monkeypatch, tmp_path):
    """A harvest stamped under the field prompt as it was is read under the
    composed one: the hash it recorded is recorded and never compared. A
    question that moved is still found."""
    import json
    from tests.test_extraction_topup import SPEC
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    now = runner._stamp_current("a" * 64, "b" * 16, SPEC)
    assert now["extraction/field"] == prompts.load(FIELD).sha256
    earlier = {**now, "extraction/field": "sha-of-the-prompt-before"}
    path = write(tmp_path / "plan.stamp.json", json.dumps(earlier))
    assert runner.stale(path, now) == []
    axis = next(key for key in now if key.startswith("axis/"))
    moved = write(tmp_path / "moved.stamp.json",
                  json.dumps({**earlier, axis: "moved"}))
    assert runner.stale(moved, now) == [axis]


# ---------------------------------------------------------------------------
# The templates are held in both languages
# ---------------------------------------------------------------------------

def test_the_field_template_is_held_in_both_languages():
    from tests.test_contract_templates import EN_ONLY, folder_problems
    examined, problems = folder_problems(EN_ONLY)
    assert "field" in examined
    assert problems == []
    de, en = contract.read("de", "field"), contract.read("en", "field")
    assert en.shape()["blocks"] - de.shape()["blocks"] == {"options_explained"}
    assert de.shape()["required"] == en.shape()["required"]
    assert de.rules == en.rules == (
        "value", "value_raw", "quote", "domain_1", "domain_2", "every_row",
        "closed_out", "by_meaning", "need_more", "corrections")


# ---------------------------------------------------------------------------
# Where the template's sentence fits scenarios less well, it says its own
# ---------------------------------------------------------------------------

ROWS_KEY = {
    "scenarios": '- "rows": die Werte, jeder mit einer Kennung ("id": "R1", '
                 '"R2", …), seiner Quelle und der Passage, in der er steht.',
    "kwp": '- "rows": die Werte, je mit Kennung ("id": "R1", "R2", …), Quelle, '
           'Wert, Einheit und Passage.',
}
UNSTATED_WHEN = {
    "scenarios": "Nennen die gezeigten Passagen überhaupt kein Szenario, "
                 "antworte für diese Zeile",
    "kwp": "Steht die Angabe in KEINER der gezeigten Quellen, antworte für "
           "diese Zeile",
}


@pytest.mark.parametrize("part, said", [("rows_carry", ROWS_KEY),
                                        ("unstated_when", UNSTATED_WHEN)])
def test_scenarios_says_its_own_sentence_and_kwp_the_templates(make, part,
                                                              said):
    """Promised (owner, 2026-10-07): a row of scenarios carries no unit, and
    what its field request asks for is a scenario, so scenarios says in its
    own words what a row carries and when the answer is "not stated" AND kwp
    keeps the template's sentence.

    Built to fail: the scenarios parts file without the part is told the
    template's sentence, and that is another prompt."""
    own = prompts.load(FIELD, load_profile("scenarios"))
    assert said["scenarios"] in own.text and said["kwp"] not in own.text
    assert said["kwp"] in text_of("kwp")
    assert said["scenarios"] not in text_of("kwp")
    bare = make(extends="scenarios", language="de",
                field=cut(file_of("scenarios"), part))
    without = prompts.load(FIELD, bare)
    assert part not in without.composition["overrides"]
    assert said["kwp"] in without.text and said["scenarios"] not in without.text
    assert without.sha256 != own.sha256
