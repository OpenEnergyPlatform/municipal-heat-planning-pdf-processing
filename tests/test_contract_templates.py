"""The core's contract templates say the same in German and in English.

Promised: for every template of the core there is one in German and one in
English AND the two ask the same of a profile (the same required and optional
parts, blocks, omittable blocks and rule names) except for what only the
English says, which is listed here and nowhere else, AND no template types what
the code decides (the least length of a quote, the word for "not stated"),
AND the core's own code holds no German.

The checks run over every template that is in the template folder, found by
looking in it: a template added later is held without an edit here, and one
that has only one language fails. EN_ONLY is the one list that is edited, and
it is held in both directions: a name in it that the English template does not
have, or that the German one has, fails, so the list cannot go stale.

Each check is also run over a folder built to break it: a block missing from
one language, a template in one language only, a name listed that is not
English-only, a template that types the number the code decides.

No model, no GPU.
"""
import re
from pathlib import Path

import pytest

from docpipe import prompts
from docpipe.extraction import contract, fields, verify

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "docpipe" / "extraction" / "contract"
PAIR = ("de", "en")

# What only the English template says, by template: the names of a part, a
# block or a rule that the German one does not have and, until the owner takes
# them, does not get (plan 2.3, "Wording rule"). A template that names its
# block differently renames its entry here, in the same commit.
EN_ONLY = {
    "rows": {
        "images": "the sentence that images follow the JSON: the code sends "
                  "them to every profile's rows request, and only the "
                  "English prompt says so",
        "quantities_number": "the sentence that a field with units_accepted "
                             "is a number: only the English prompt says so, "
                             "the German profiles word the units where the "
                             "key is introduced",
    },
    "field": {
        "options_explained": "what \"means\", \"spellings\" and the "
                             "\"out:unstated\" entry of a closed list are, "
                             "in the key that holds the list",
    },
}

SHAPE = ("required", "optional", "blocks", "omittable", "rules")


def names_of(shape: dict) -> set:
    return set().union(*(shape[key] for key in SHAPE))


def shape_problems(name: str, de, en, en_only) -> list:
    """What the German and the English template of one name do not share."""
    problems = []
    german, english = de.shape(), en.shape()
    for key in SHAPE:
        missing = german[key] - english[key]
        if missing:
            problems.append(f"{name}: {key} {sorted(missing)} are in de and "
                            f"not in en")
        extra = english[key] - german[key] - set(en_only)
        if extra:
            problems.append(f"{name}: {key} {sorted(extra)} are in en and not "
                            f"in de, and not listed in EN_ONLY")
    for entry in sorted(en_only):
        if entry not in names_of(english):
            problems.append(f"{name}: EN_ONLY lists {entry!r}, which the "
                            f"English template does not have")
        if entry in names_of(german):
            problems.append(f"{name}: EN_ONLY lists {entry!r}, which the "
                            f"German template has: take the entry out")
    return problems


def folder_problems(en_only: dict) -> tuple:
    """(the names examined, what is wrong) for the template folder as it is
    now: every template of either language of the pair."""
    german, english = (set(contract.template_names(lang)) for lang in PAIR)
    problems = [f"template {name!r} is in {'de' if name in german else 'en'} "
                f"only" for name in sorted(german ^ english)]
    for name in sorted(german & english):
        problems += shape_problems(name, contract.read("de", name),
                                   contract.read("en", name),
                                   en_only.get(name, {}))
    return sorted(german | english), problems


# ---------------------------------------------------------------------------
# AND the German and the English template are one contract
# ---------------------------------------------------------------------------

def test_every_template_there_is_has_both_languages_and_the_same_shape():
    examined, problems = folder_problems(EN_ONLY)
    assert problems == []
    on_disk = sorted({path.stem for path in FOLDER.glob("*/*.md")})
    assert examined == on_disk, "a template in the folder was not looked at"
    languages = sorted(p.name for p in FOLDER.iterdir() if p.is_dir()) \
        if FOLDER.is_dir() else []
    assert languages in ([], list(PAIR)), "a language of the core is not held"


def test_a_name_in_en_only_is_in_the_english_template_and_not_in_the_german():
    """EN_ONLY is held against the templates that exist: an entry for a
    template that is there and is not English-only, or is not there at all,
    fails."""
    examined, _ = folder_problems(EN_ONLY)
    for name in examined:
        for entry in EN_ONLY.get(name, {}):
            en = contract.read("en", name).shape()
            de = contract.read("de", name).shape()
            assert entry in names_of(en), (name, entry)
            assert entry not in names_of(de), (name, entry)


TEMPLATE = (
    "---\nrequired: [role]\noptional: [more]\nblocks: [images, sandbox]\n"
    "omittable: [images, sandbox]\n---\n"
    "{{role}}\n{{more}}\n"
    "<!-- block: images -->\nImages follow.\n<!-- /block -->\n"
    "<!-- block: sandbox -->\n<!-- rule: sandbox --> Calculate.\n<!-- /block -->\n"
    "<!-- rule: invent --> Invent nothing.\n")


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A template folder of the test's own, in place of the core's."""
    root = tmp_path / "contract"
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", root)

    def put(language: str, name: str, text: str = TEMPLATE) -> None:
        path = root / language / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return put


def test_a_pair_that_agrees_is_held_and_found_without_a_list_of_names(folder):
    folder("de", "rows")
    folder("en", "rows")
    folder("de", "later")               # a template nobody listed anywhere
    folder("en", "later")
    assert folder_problems({}) == (["later", "rows"], [])


def test_a_template_in_one_language_only_is_found(folder):
    folder("de", "rows")
    folder("en", "rows")
    folder("en", "frame")
    examined, problems = folder_problems({})
    assert examined == ["frame", "rows"]
    assert problems == ["template 'frame' is in en only"]


def test_an_english_template_that_does_not_read_stops_the_check_and_names_the_file(
        folder):
    """A block cut out of the English template and still declared there: the
    template is refused as a template, and the check does not go on past it."""
    folder("de", "rows")
    folder("en", "rows", TEMPLATE.replace(
        "<!-- block: images -->\nImages follow.\n<!-- /block -->\n",
        "Images follow.\n"))
    with pytest.raises(prompts.PromptPartsError) as raised:
        folder_problems({})
    assert "images" in str(raised.value)
    assert str(contract.template_path("en", "rows")) in str(raised.value)


def test_a_block_that_the_english_lacks_in_its_declaration_is_found(folder):
    folder("de", "rows")
    english = (TEMPLATE.replace("blocks: [images, sandbox]", "blocks: [sandbox]")
               .replace("omittable: [images, sandbox]", "omittable: [sandbox]")
               .replace("<!-- block: images -->\nImages follow.\n<!-- /block -->\n",
                        "Images follow.\n"))
    folder("en", "rows", english)
    _, problems = folder_problems({})
    assert problems == [
        "rows: blocks ['images'] are in de and not in en",
        "rows: omittable ['images'] are in de and not in en"]


def test_a_part_and_a_rule_that_one_language_adds_are_found(folder):
    folder("de", "rows")
    english = (TEMPLATE.replace("optional: [more]", "optional: [more, extra]")
               .replace("{{more}}\n", "{{more}}\n{{extra}}\n")
               .replace("<!-- rule: invent -->",
                        "<!-- rule: extra_rule --> Extra.\n<!-- rule: invent -->"))
    folder("en", "rows", english)
    _, problems = folder_problems({})
    assert problems == [
        "rows: optional ['extra'] are in en and not in de, and not listed in "
        "EN_ONLY",
        "rows: rules ['extra_rule'] are in en and not in de, and not listed "
        "in EN_ONLY"]


def test_what_only_the_english_has_is_allowed_when_it_is_listed(folder):
    folder("de", "rows")
    english = (TEMPLATE.replace("optional: [more]", "optional: [more, extra]")
               .replace("{{more}}\n", "{{more}}\n{{extra}}\n"))
    folder("en", "rows", english)
    assert folder_problems({"rows": {"extra": "why"}}) == (["rows"], [])
    assert folder_problems({}) != (["rows"], [])


def test_an_entry_that_the_english_does_not_have_is_found(folder):
    folder("de", "rows")
    folder("en", "rows")
    _, problems = folder_problems({"rows": {"nothing": "why"}})
    assert problems == ["rows: EN_ONLY lists 'nothing', which the English "
                        "template does not have"]


def test_an_entry_that_the_german_has_as_well_is_found(folder):
    """A name stays on the list after the German template took it: the list
    would say the languages differ where they do not."""
    folder("de", "rows")
    folder("en", "rows")
    _, problems = folder_problems({"rows": {"images": "why"}})
    assert problems == ["rows: EN_ONLY lists 'images', which the German "
                        "template has: take the entry out"]


# ---------------------------------------------------------------------------
# AND no template types what the code decides
# ---------------------------------------------------------------------------

def typed_facts(text: str) -> list:
    """What a template spells out that the code decides: the number that is
    the least length of a quote, and the word for "not stated"."""
    found = []
    # a number on its own: not a part of 18, 2018, a8 or a decimal such as 8.5
    if re.search(rf"(?<![\w.,]){verify.MIN_QUOTE_CHARS}(?!\w|[.,]\d)", text):
        found.append(f"the number {verify.MIN_QUOTE_CHARS}")
    if fields.UNSTATED in text:
        found.append(f"the word {fields.UNSTATED!r}")
    return found


def test_no_template_of_the_core_types_a_fact():
    for language, name in contract.available():
        text = contract.template_path(language, name).read_text(encoding="utf-8")
        assert typed_facts(text) == [], (language, name)


@pytest.mark.parametrize("text, found", [
    ("a quote of at least 8 characters", ["the number 8"]),
    ("answer \"out:unstated\" if not there", ["the word 'out:unstated'"]),
    ("8 and out:unstated", ["the number 8", "the word 'out:unstated'"]),
    ("at least {{min_quote_chars}}, else \"{{unstated}}\"", []),
    ("Table 18, 2018, 8.5 and a8", []),
])
def test_the_check_for_a_typed_fact_can_fail_and_does_not_fail_on_other_digits(
        text, found):
    assert typed_facts(text) == found


def test_the_check_follows_the_code_and_not_the_number_it_had(monkeypatch):
    monkeypatch.setattr(verify, "MIN_QUOTE_CHARS", 12)
    assert typed_facts("at least 12 characters") == ["the number 12"]
    assert typed_facts("at least 8 characters") == []


# ---------------------------------------------------------------------------
# AND the core's own code holds no German
# ---------------------------------------------------------------------------

CORE_FILES = ("docpipe/prompts.py", "docpipe/extraction/contract.py",
              "scripts/render_prompts.py")
GERMAN_WORDS = re.compile(
    r"\b(der|die|das|dem|den|und|nicht|ist|sind|wird|werden|wenn|eine|einen|"
    r"einer|mit|für|auf|zum|zur|oder|auch|nur|Regel|Regeln|Quelle|"
    r"Quellen|Antwort|Zeichen|Zitat|Wärmeplan)\b")
UMLAUTS = re.compile("[äöüÄÖÜß]")


def german_in(text: str) -> list:
    return sorted({m.group(0) for m in GERMAN_WORDS.finditer(text)}
                  | {m.group(0) for m in UMLAUTS.finditer(text)})


@pytest.mark.parametrize("path", CORE_FILES)
def test_the_core_code_that_makes_prompts_holds_no_german(path):
    assert german_in((ROOT / path).read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("text, found", [
    ("Die Regel ist klar.", ["Regel", "ist"]),
    ("# Quelle und Antwort", ["Antwort", "Quelle", "und"]),
    ("Wärmeplan für alle", ["Wärmeplan", "für", "ä", "ü"]),
    ("The rule is clear; a source and an answer.", []),
])
def test_the_scan_for_german_can_fail(text, found):
    assert german_in(text) == found
