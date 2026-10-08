"""A prompt that names a template is the core's contract text and the profile's
own parts, put together at load.

Promised: a prompt that names a template is the core's contract text in the
profile's language with the profile's parts put in AND nothing else, AND the
profile's domain parts reach the request unchanged, AND a part that is missing,
one the template does not know, a block that cannot be left out or a reference
to a rule that is gone fails at load with the prompt, the part, the profile and
the two files named, AND no placeholder reaches a request, AND the language is
that of the profile that owns the parts file, AND leaving a block out and
wording one itself do what they say, with the rules still numbered without a
gap and every reference following, AND the fingerprint is the sha256 of the
text a person would have written by hand, AND a file that names no template is
read exactly as before.

Each AND is its own test below, and each has the case built to break it: a part
that holds `{{x}}`, one that is misspelt, one that is deleted, a reference to
a rule that was left out, a part whose place is gone, a harvester built on a
profile whose part is open, a child that inherits the parts of a parent and
declares another language, a fingerprint taken after one part changed, a
refinement prompt that names a template.

The templates are small ones written here, in made-up languages, so that these
tests do not move with the templates the core ships. No model, no GPU.
"""
import hashlib
import importlib
import itertools
import json
from pathlib import Path

import pytest

from docpipe import doctor, prompts
from docpipe.extraction import contract, runner, verify, wording
from docpipe.extraction.pipeline import Source, WorkItem, group_items
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import load_profile
from tests.test_extraction_requests import Recorder

ROOT = Path(__file__).resolve().parent.parent

ROWS = "extraction/rows"

# One template with every mark the engine knows: a slot that is required, one
# that is optional, a block that stands inline, one of whole lines, a block
# that stands twice, rules that point at rules, and two facts.
TEMPLATE_XX = '''\
---
required: [role, example_reply]
optional: [value_more, sandbox_more]
blocks: [images, row_note, sandbox]
omittable: [images, sandbox]
---
{{role}}

You get sources.<!-- block: images --> Images follow the JSON.<!-- /block -->

Reply with one JSON object; a quote has at least {{min_quote_chars}} characters:

{{example_reply}}

<!-- block: row_note -->
Every entry is checked against the source.
<!-- /block -->
Rules:

<!-- rule: value --> "value": the number as printed; rule {{rule:invent}} applies.
{{value_more}}
<!-- block: sandbox -->
   If it must be calculated, see rule {{rule:sandbox}}.
<!-- /block -->

<!-- rule: quote --> "quote": from a source; "{{unstated}}" if it is not there.

<!-- block: sandbox -->
<!-- rule: sandbox --> Calculate with the sandbox.
{{sandbox_more}}

<!-- /block -->
<!-- rule: invent --> Invent nothing, and see rule {{rule:quote}}.
'''

# The same contract in another made-up language: other words, the same shape.
TEMPLATE_YY = TEMPLATE_XX.replace(
    "You get sources.", "Sources are given.").replace(
    "Reply with one JSON object; a quote has at least",
    "One JSON object is the reply; cite no fewer than").replace(
    "characters:", "letters:")

ROLE = "You read plans."
EXAMPLE = '{"tuples": []}'

PARTS = f'''\
---
template: rows
temperature: 0
max_tokens: 100
---
<!-- part: role -->
{ROLE}

<!-- part: example_reply -->
{EXAMPLE}
'''

# What TEMPLATE_XX and PARTS make, written out by hand.
EXPECTED = '''\
You read plans.

You get sources. Images follow the JSON.

Reply with one JSON object; a quote has at least 8 characters:

{"tuples": []}

Every entry is checked against the source.
Rules:

1. "value": the number as printed; rule 4 applies.
   If it must be calculated, see rule 3.

2. "quote": from a source; "out:unstated" if it is not there.

3. Calculate with the sandbox.

4. Invent nothing, and see rule 2.
'''

# The same with the sandbox and the images left out: three rules, the last one
# is the third and the first rule says so, and nothing points at the sandbox.
EXPECTED_WITHOUT = '''\
You read plans.

You get sources.

Reply with one JSON object; a quote has at least 8 characters:

{"tuples": []}

Every entry is checked against the source.
Rules:

1. "value": the number as printed; rule 3 applies.

2. "quote": from a source; "out:unstated" if it is not there.

3. Invent nothing, and see rule 2.
'''

FRONT = "---\ntemperature: 0\nmax_tokens: 100\n---\n"

_names = itertools.count(1)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.fixture
def templates(tmp_path, monkeypatch):
    """A template folder of the test's own, put where the core looks."""
    root = tmp_path / "templates"
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", root)

    def put(language: str, name: str, text: str) -> Path:
        return write(root / language / f"{name}.md", text)

    put("xx", "rows", TEMPLATE_XX)
    return put


@pytest.fixture
def shipped(templates):
    """The core's own templates, put beside the made-up ones: a profile that
    extends kwp keeps kwp's parts files, and those are made with the templates
    of the language kwp declares."""
    folder = Path(contract.__file__).resolve().parent / "contract"
    for path in sorted(folder.glob("*/*.md")):
        templates(path.parent.name, path.stem, path.read_text(encoding="utf-8"))


@pytest.fixture
def make(tmp_path, monkeypatch):
    """Profiles written to disk, each under a name of its own. `make(...)`
    returns the loaded profile."""
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))

    def build(*, extends="default", language=None, files=None, phrases=None):
        name = f"parts_{next(_names)}"
        home = tmp_path / name
        write(home / "__init__.py", "")
        write(home / "profile.py",
              "from docpipe.profile import Profile\n"
              f"PROFILE = Profile(name={name!r}, extends={extends!r})\n")
        lines = []
        if language is not None:
            lines.append(f"CONTRACT_LANGUAGE = {language!r}")
        if phrases:
            lines.append(f"PHRASES = {phrases!r}")
        if lines:
            write(home / "extraction.py", "\n".join(lines) + "\n")
        for pid, text in (files or {}).items():
            write(home / "prompts" / f"{pid}.md", text)
        importlib.invalidate_caches()       # a folder made a moment ago
        return load_profile(name)

    return build


def parts_with(*changes, front=None, drop=()):
    """A parts file of the parts in PARTS, with `<!-- part: name -->` sections
    added or replaced: ("name", "text")."""
    body = {"role": ROLE, "example_reply": EXAMPLE}
    for name in drop:
        del body[name]
    body.update(dict(changes))
    return (front or "---\ntemplate: rows\ntemperature: 0\nmax_tokens: 100\n---\n"
            ) + "".join(f"<!-- part: {name} -->\n{text}\n\n"
                        for name, text in body.items())


def without(*names):
    """The front matter of a parts file that leaves blocks out."""
    return ("---\ntemplate: rows\nwithout: [" + ", ".join(names)
            + "]\ntemperature: 0\nmax_tokens: 100\n---\n")


def rows_of(make, parts: str, language="xx", **more):
    profile = make(language=language, files={ROWS: parts}, **more)
    return profile, prompts.load(ROWS, profile)


def refusal(make, parts: str, language="xx", **more) -> prompts.PromptPartsError:
    profile = make(language=language, files={ROWS: parts}, **more)
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load(ROWS, profile)
    return raised.value


# ---------------------------------------------------------------------------
# The prompt is the template with the parts put in AND nothing else
# ---------------------------------------------------------------------------

def test_the_prompt_is_the_template_with_the_parts_put_in_and_nothing_else(
        make, templates):
    profile, prompt = rows_of(make, PARTS)
    assert prompt.text == EXPECTED
    assert prompt.meta == {"temperature": 0, "max_tokens": 100}
    assert prompt.id == ROWS
    assert prompt.path == prompts.path_for(ROWS, profile)


def test_the_text_moves_with_the_template_and_with_every_part(make, templates):
    """Built to fail: a prompt that stayed the same when the template or a
    part changed would not be made of them."""
    _, base = rows_of(make, PARTS)
    _, reworded = rows_of(make, parts_with(("role", "You read tables.")))
    assert reworded.text == EXPECTED.replace(ROLE, "You read tables.")
    templates("xx", "rows", TEMPLATE_XX.replace("Invent nothing", "Make nothing up"))
    _, edited = rows_of(make, PARTS)
    assert edited.text == EXPECTED.replace("Invent nothing", "Make nothing up")
    assert len({base.text, edited.text, reworded.text}) == 3


def test_an_optional_part_that_is_given_stands_in_its_place_and_one_that_is_not_leaves_no_line(
        make, templates):
    _, plain = rows_of(make, PARTS)
    assert "rule 4 applies.\n   If it must be calculated" in plain.text, \
        "the absent part left no blank line"
    _, more = rows_of(make, parts_with(
        ("value_more", "   A unit goes into \"unit_raw\".\n   Nothing else.")))
    assert more.text == EXPECTED.replace(
        '1. "value": the number as printed; rule 4 applies.\n',
        '1. "value": the number as printed; rule 4 applies.\n'
        '   A unit goes into "unit_raw".\n   Nothing else.\n')


def test_a_part_inside_a_block_goes_in_with_the_block(make, templates):
    _, prompt = rows_of(make, parts_with(("sandbox_more", "   Print the result.")))
    assert prompt.text == EXPECTED.replace(
        "3. Calculate with the sandbox.\n",
        "3. Calculate with the sandbox.\n   Print the result.\n")


def test_a_fact_in_the_template_is_the_codes_value_not_a_typed_one(
        make, templates, monkeypatch):
    _, prompt = rows_of(make, PARTS)
    assert "at least 8 characters" in prompt.text
    monkeypatch.setattr(verify, "MIN_QUOTE_CHARS", 12)
    _, moved = rows_of(make, PARTS)
    assert "at least 12 characters" in moved.text
    assert "8" not in moved.text


# ---------------------------------------------------------------------------
# AND the domain parts reach the request unchanged
# ---------------------------------------------------------------------------

DOMAIN = (
    '{"tuples": [{"source": "Q2", "value": 126656132, "quote": "| Erdgas | 1 |"}],'
    ' "nested": {"a": {"b": 1}}}\n'
    "\n"
    "   FALSCH: „Wärme“, \"x\" < y & z  \n"
    "\tTabbed line with a trailing tab\t\n"
    "A line with 100 % and a backslash \\ and 'single' quotes.")


def test_a_domain_part_stands_in_the_prompt_word_for_word(make, templates):
    _, prompt = rows_of(make, parts_with(("example_reply", DOMAIN)))
    assert DOMAIN in prompt.text
    assert prompt.text.count(DOMAIN) == 1


def test_the_check_that_a_part_stands_verbatim_can_fail(make, templates):
    """Built to fail: one character changed, or one indentation, and the
    sentence is not there."""
    _, prompt = rows_of(make, parts_with(("example_reply", DOMAIN)))
    assert DOMAIN.replace("Erdgas", "Erdgaz") not in prompt.text
    assert DOMAIN.replace("   FALSCH", "FALSCH") not in prompt.text


def test_a_part_may_name_a_fact_and_a_rule_and_nothing_else_in_double_braces(
        make, templates):
    _, prompt = rows_of(make, parts_with(
        ("value_more", "   At least {{min_quote_chars}} characters, rule "
                       "{{rule:quote}}.")))
    assert "   At least 8 characters, rule 2.\n" in prompt.text


@pytest.mark.parametrize("text", [
    "an open {{x}} placeholder",
    "a part may not put in another: {{role}}",
    "a rule reference that is not one: {{rule:}}",
    "a comment mark <!-- block: sandbox --> in a part",
    "{{ min_quote_chars",
])
def test_a_part_with_an_open_placeholder_is_refused(make, templates, text):
    error = refusal(make, parts_with(("value_more", text)))
    assert error.part == "value_more"
    assert "open placeholder" in str(error)


@pytest.mark.parametrize("sentence", ["{{open}}", "<!-- left -->", "a {{ b"])
def test_a_fact_whose_value_holds_an_open_mark_is_found_in_the_composed_text(
        make, templates, sentence):
    """The one place an open placeholder can still come from once the
    template and the parts have been read: a value the code fills in."""
    templates("xx", "facts", "---\nrequired: [role]\n---\n{{role}} {{option_means}}\n")
    profile = make(language="xx", phrases={"option_means": sentence}, files={
        "extraction/facts": "---\ntemplate: facts\n---\n<!-- part: role -->\nR\n"})
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load("extraction/facts", profile)
    assert "left in the composed text" in str(raised.value)


def test_a_placeholder_that_a_fact_fills_is_not_open(make, templates):
    """The other side of the case above: the same braces around the name of a
    fact are filled and not refused."""
    _, prompt = rows_of(make, parts_with(("value_more", "{{unstated}}")))
    assert "out:unstated\n" in prompt.text


# ---------------------------------------------------------------------------
# AND a part that is missing or not known fails at load, with names
# ---------------------------------------------------------------------------

def test_a_missing_required_part_names_the_prompt_the_part_the_profile_and_both_files(
        make, templates, tmp_path):
    profile = make(language="xx", files={ROWS: parts_with(drop=("example_reply",))})
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load(ROWS, profile)
    error = raised.value
    assert (error.prompt_id, error.part, error.profile) == (
        ROWS, "example_reply", profile.name)
    text = str(error)
    assert "example_reply" in text and ROWS in text and profile.name in text
    assert str(prompts.path_for(ROWS, profile)) in text
    assert str(tmp_path / "templates" / "xx" / "rows.md") in text
    assert dict(error.files) == {
        "parts file": str(prompts.path_for(ROWS, profile)),
        "template": str(tmp_path / "templates" / "xx" / "rows.md")}


def test_a_part_the_template_does_not_know_is_refused_and_the_near_one_named(
        make, templates):
    error = refusal(make, parts_with(("exampel_reply", EXAMPLE),
                                     drop=("example_reply",)))
    assert error.part == "exampel_reply"
    assert "did you mean 'example_reply'" in str(error)


def test_the_part_that_is_given_is_what_makes_the_check_pass(make, templates):
    """Built to fail: the same parts file with its part spelt right loads."""
    _, prompt = rows_of(make, parts_with(("example_reply", EXAMPLE)))
    assert prompt.text == EXPECTED


@pytest.mark.parametrize("parts, fragment", [
    ("---\ntemplate: rows\n---\nText before any part.\n"
     "<!-- part: role -->\nx\n", "before the first part"),
    ("---\ntemplate: rows\n---\n<!-- part: role -->\nx\n"
     "<!-- part: role -->\ny\n", "stands twice"),
    ("---\ntemplate: rows\n---\n<!-- part: role -->\n\n"
     "<!-- part: example_reply -->\ny\n", "is empty"),
    ("---\ntemplate: rows\n---\n", "is missing"),
])
def test_a_parts_file_that_is_not_a_list_of_parts_is_refused(
        make, templates, parts, fragment):
    assert fragment in str(refusal(make, parts))


def test_the_line_of_text_before_the_first_part_is_the_files_line(make, templates):
    error = refusal(make, "---\ntemplate: rows\n---\n\nText here.\n"
                          "<!-- part: role -->\nx\n")
    assert "in line 5" in str(error)


@pytest.mark.parametrize("front, fragment", [
    ("---\ntemplate: ../rows\n---\n", "must name a template"),
    ("---\ntemplate:\n---\n", "must name a template"),
    ("---\ntemplate: [rows]\n---\n", "must name a template"),
    ("---\ntemplate: missing\n---\n", "has no template 'missing'"),
])
def test_a_template_that_is_not_named_or_not_there_is_refused(
        make, templates, front, fragment):
    assert fragment in str(refusal(make, front))


def test_a_template_in_another_language_is_named_when_this_one_lacks_it(
        make, templates):
    templates("yy", "frame", "---\nrequired: [role]\n---\n{{role}}\n")
    error = refusal(make, "---\ntemplate: frame\n---\n<!-- part: role -->\nx\n")
    assert "no template 'frame' in language 'xx'" in str(error)
    assert "['yy']" in str(error)


# ---------------------------------------------------------------------------
# AND a template that is not a template is refused as one
# ---------------------------------------------------------------------------

def template_of(front: str = "", body: str = "{{role}}\n") -> str:
    """A template of one required part `role`, with more front matter and
    another body where a case needs them."""
    return f"---\nrequired: [role]\n{front}---\n{body}"


@pytest.mark.parametrize("template, fragment", [
    (template_of("blocks: [b]\n", "{{role}}\n<!-- block: b -->\ntext\n"),
     "never closed"),
    (template_of(body="{{role}}\n<!-- /block -->\n"), "never opened"),
    (template_of(body="{{role}}\n<!-- block: b -->\ntext\n<!-- /block -->\n"),
     "not among the template's blocks"),
    (template_of("blocks: [b]\n"), "declared and never used"),
    (template_of(body="{{role}}\n{{unknown}}\n"),
     "neither a part of this template"),
    (template_of("optional: [o]\n"), "declared and has no slot"),
    (template_of(body="{{role}}\n<!-- note -->\n"), "not a mark of a template"),
    (template_of(body="{{role}}\n{{ two words }}\n"),
     "not a mark of a template"),
    (template_of(body="{{role}}\n<!-- rule: r --> a\n<!-- rule: r --> b\n"),
     "stands twice"),
    (template_of(body="{{role}}\nsee {{rule:nowhere}}\n"), "does not have"),
    (template_of("optional: [o]\n", "{{role}}\n{{o}}\n{{o}}\n"),
     "stands twice"),
    (template_of("blocks: [role]\n"), "both a part and a block"),
    (template_of("omittable: [b]\n"), "not among the blocks"),
    (template_of("blocks: [b]\nomittable: [b]\n",
                 "<!-- block: b -->\n{{role}}\n<!-- /block -->\n"),
     "lies in the omittable block"),
    (template_of("temperature: 0\n"), "not a template's"),
    (template_of("optional: [role]\n"), "both required and optional"),
    (template_of("blocks: [min_quote_chars]\n"), "a fact of the core"),
    (template_of("blocks: b\n"), "must be a list of names"),
])
def test_a_template_that_breaks_its_own_rules_is_refused(
        make, templates, template, fragment):
    templates("xx", "bad", template)
    error = refusal(make, "---\ntemplate: bad\n---\n<!-- part: role -->\nx\n")
    assert fragment in str(error)
    assert str(contract.TEMPLATE_ROOT / "xx" / "bad.md") in str(error)


def test_a_template_that_is_right_is_not_refused_by_the_cases_above(make, templates):
    """Built to fail: the base all the cases above are made from loads."""
    templates("xx", "bad", template_of())
    profile = make(language="xx", files={
        ROWS: "---\ntemplate: bad\n---\n<!-- part: role -->\nx\n"})
    assert prompts.load(ROWS, profile).text == "x\n"


# ---------------------------------------------------------------------------
# AND leaving a block out does what it says: gapless numbers, references follow
# ---------------------------------------------------------------------------

def test_leaving_blocks_out_removes_them_and_the_numbers_stay_without_a_gap(
        make, templates):
    _, prompt = rows_of(make, parts_with(front=without("sandbox", "images")))
    assert prompt.text == EXPECTED_WITHOUT
    numbers = [int(line.split(".", 1)[0]) for line in prompt.text.splitlines()
               if line[:1].isdigit()]
    assert numbers == [1, 2, 3]


def test_a_rule_that_is_left_out_moves_the_rules_after_it_and_what_points_at_them(
        make, templates):
    templates("xx", "short", (
        "---\nrequired: [role]\nblocks: [first]\nomittable: [first]\n---\n"
        "{{role}}\n"
        "<!-- block: first -->\n"
        "<!-- rule: a --> First rule, see rule {{rule:c}}.\n"
        "<!-- /block -->\n"
        "<!-- rule: b --> Second rule.\n"
        "<!-- rule: c --> Third rule, see rule {{rule:b}}.\n"))

    def made(front):
        profile = make(language="xx", files={"extraction/short": (
            front + "<!-- part: role -->\nR\n")})
        return prompts.load("extraction/short", profile).text

    assert made("---\ntemplate: short\n---\n") == (
        "R\n1. First rule, see rule 3.\n2. Second rule.\n"
        "3. Third rule, see rule 2.\n")
    assert made("---\ntemplate: short\nwithout: [first]\n---\n") == (
        "R\n1. Second rule.\n2. Third rule, see rule 1.\n")


def test_a_reference_to_a_rule_that_was_left_out_is_refused(make, templates):
    """Built to fail: the sentence in the first rule points at the sandbox
    rule. Leaving the rule out and the sentence in is not a prompt."""
    templates("xx", "rows", TEMPLATE_XX.replace(
        "<!-- block: sandbox -->\n   If it must be calculated, see rule "
        "{{rule:sandbox}}.\n<!-- /block -->\n",
        "   If it must be calculated, see rule {{rule:sandbox}}.\n"))
    error = refusal(make, parts_with(front=without("sandbox")))
    assert error.part == "sandbox"
    assert "reference to rule 'sandbox'" in str(error)
    assert "block 'sandbox'" in str(error)


def test_a_reference_in_a_part_to_a_rule_that_was_left_out_is_refused(
        make, templates):
    error = refusal(make, parts_with(("value_more", "   See rule {{rule:sandbox}}."),
                                     front=without("sandbox")))
    assert "reference to rule 'sandbox'" in str(error)
    assert "block 'sandbox'" in str(error)


def test_a_part_whose_place_was_left_out_is_refused(make, templates):
    """Text of the profile that is never sent is a mistake, not a saving."""
    error = refusal(make, parts_with(("sandbox_more", "   Print the result."),
                                     front=without("sandbox")))
    assert error.part == "sandbox_more"
    assert "no place" in str(error) and "left out by `without`" in str(error)


@pytest.mark.parametrize("front, fragment", [
    (without("sandbox_"), "did you mean 'sandbox'"),
    (without("row_note"), "cannot be left out"),
    (without("sandbox", "sandbox"), "names a block twice"),
    ("---\ntemplate: rows\nwithout: sandbox\n---\n", "must be a list of block names"),
    ("---\ntemplate: rows\nwithout: [1]\n---\n", "must be a list of block names"),
])
def test_a_without_that_names_nothing_to_leave_out_is_refused(
        make, templates, front, fragment):
    assert fragment in str(refusal(make, parts_with(front=front)))


def test_a_block_cannot_be_both_left_out_and_worded(make, templates):
    error = refusal(make, parts_with(("images", " A picture follows."),
                                     front=without("images")))
    assert "both left out and worded" in str(error)


# ---------------------------------------------------------------------------
# AND wording a block itself does what it says
# ---------------------------------------------------------------------------

def test_a_part_with_the_name_of_a_block_replaces_the_block(make, templates):
    _, prompt = rows_of(make, parts_with(
        ("row_note", "Every entry is read twice, once per source.")))
    assert prompt.text == EXPECTED.replace(
        "Every entry is checked against the source.",
        "Every entry is read twice, once per source.")


def test_without_the_part_the_templates_own_text_stands_in_the_block(
        make, templates):
    """Built to fail: the case above, minus its part."""
    _, prompt = rows_of(make, PARTS)
    assert "Every entry is checked against the source." in prompt.text
    assert "read twice" not in prompt.text


def test_an_inline_block_is_replaced_where_it_stands(make, templates):
    _, prompt = rows_of(make, parts_with(("images", " A picture follows.")))
    assert "You get sources. A picture follows.\n" in prompt.text
    assert "Images follow" not in prompt.text


def test_a_block_that_is_worded_keeps_the_blank_lines_it_ended_with(make, templates):
    templates("xx", "gap", (
        "---\nrequired: [role]\nblocks: [note]\n---\n{{role}}\n"
        "<!-- block: note -->\nOld note.\n\n<!-- /block -->\nNext.\n"))

    def made(*parts):
        profile = make(language="xx", files={"extraction/gap": (
            "---\ntemplate: gap\n---\n<!-- part: role -->\nR\n" + "".join(
                f"<!-- part: {name} -->\n{text}\n" for name, text in parts))})
        return prompts.load("extraction/gap", profile).text

    assert made() == "R\nOld note.\n\nNext.\n"
    assert made(("note", "New note.")) == "R\nNew note.\n\nNext.\n"


def test_a_block_that_stands_twice_can_be_left_out_and_not_worded(make, templates):
    error = refusal(make, parts_with(("sandbox", "Calculate by hand.")))
    assert "stands 2 times" in str(error)
    assert "can only be left out" in str(error)


def test_the_composition_says_what_was_worded_and_what_was_left_out(
        make, templates):
    _, prompt = rows_of(make, parts_with(
        ("row_note", "Every entry is read twice."),
        front=without("sandbox", "images")))
    note = prompt.composition
    assert note["template"] == "rows" and note["language"] == "xx"
    assert note["overrides"] == ["row_note"]
    assert note["omitted"] == ["images", "sandbox"]
    assert sorted(note["what_if"]) == ["images", "sandbox"]


def test_a_plain_prompt_has_no_composition(make, templates):
    profile = make(files={"refinement/refine": "Plain.\n"})
    assert prompts.load("refinement/refine", profile).composition is None


def test_each_omitted_block_can_be_put_back_and_only_that_one(make, templates):
    """What the render tool shows for `--what-if`: the prompt with one block
    switched on, made under the same checks, and the others still out."""
    _, prompt = rows_of(make, parts_with(front=without("sandbox", "images")))
    back = prompt.composition["what_if"]
    assert back["images"] == EXPECTED_WITHOUT.replace(
        "You get sources.", "You get sources. Images follow the JSON.")
    assert back["sandbox"] == EXPECTED.replace(
        "You get sources. Images follow the JSON.", "You get sources.")
    assert prompt.text == EXPECTED_WITHOUT          # and the prompt is as it was


def test_a_block_put_back_is_made_when_asked_and_not_when_loaded(
        make, templates, monkeypatch):
    calls = []
    real = prompts._compose
    monkeypatch.setattr(prompts, "_compose",
                        lambda *args: calls.append(1) or real(*args))
    _, prompt = rows_of(make, parts_with(front=without("images")))
    assert len(calls) == 1
    prompt.composition["what_if"]["images"]
    prompt.composition["what_if"]["images"]
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# AND no placeholder reaches a request
# ---------------------------------------------------------------------------

def holds_a_mark(text: str) -> bool:
    """Whether a placeholder or a mark of a template is left in a text."""
    return "{{" in text or "<!--" in text


@pytest.fixture
def harvest_world(make, templates, monkeypatch):
    """A profile that extends kwp, takes its rows prompt from a template, and
    a client that keeps every request it is sent."""
    spec = load_spec(json.loads((ROOT / "profiles" / "kwp" / "extraction_spec.json")
                                .read_text(encoding="utf-8")))
    client = Recorder()
    monkeypatch.setattr(runner, "_client", lambda: client)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(runner, "RETRY_TEMPERATURE_STEP", 0.0)
    monkeypatch.setattr(runner, "CODE_ROUNDS", 2)

    def world(parts: str):
        profile = make(extends="kwp", language="xx", files={ROWS: parts})
        monkeypatch.setenv("DOCPIPE_PROFILE", profile.name)
        return profile, spec, client
    return world


def test_the_harvester_is_not_built_on_a_prompt_with_an_open_placeholder(
        harvest_world):
    profile, spec, client = harvest_world(
        parts_with(("example_reply", '{"tuples": []} {{x}}')))
    with pytest.raises(prompts.PromptPartsError):
        runner.make_harvester(spec=spec)
    assert client.sent == []


def test_a_request_carries_the_composed_text_and_no_mark(harvest_world):
    """Built to fail: the case above with the placeholder gone is built, asks,
    and its system message is the composed text and holds no double brace."""
    # room for an answer, or the harvester does not send a prompt this small
    profile, spec, client = harvest_world(
        PARTS.replace("max_tokens: 100", "max_tokens: 6144"))
    shown = [Source("table", 1, "| Erdgas | 1 |", {"document_id": 7, "page": 1}),
             Source("section", 2, "Das Zielszenario 2045.",
                    {"document_id": 7, "page": 2})]
    harvest = runner.make_harvester(spec=spec)
    harvest(group_items([WorkItem(7, spec.parameters[0], shown[0]),
                         WorkItem(7, spec.parameters[0], shown[1])])[0], [])
    system = client.sent[0]["messages"][0]
    assert system["role"] == "system" and system["content"] == EXPECTED
    assert not holds_a_mark(system["content"])


@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
@pytest.mark.parametrize("stage_id", [
    "rows", "field", "frame", "review", "example", "phrase", "anchors",
    "queries"])
def test_no_extraction_prompt_a_profile_ships_holds_a_placeholder(name, stage_id):
    text = prompts.load(f"extraction/{stage_id}", load_profile(name)).text
    assert not holds_a_mark(text)


def test_that_scan_can_fail(make, templates):
    """Built to fail: the prompts that would trip it, a plain one that holds
    the braces and one that holds a mark, are found by it."""
    profile = make(files={"extraction/rows": "Say {{x}}.\n",
                          "extraction/field": "Then <!-- y -->.\n",
                          "extraction/frame": "Clean.\n"})
    found = {pid: holds_a_mark(prompts.load(pid, profile).text)
             for pid in ("extraction/rows", "extraction/field",
                         "extraction/frame")}
    assert found == {"extraction/rows": True, "extraction/field": True,
                     "extraction/frame": False}


def test_the_doctor_reports_a_prompt_that_cannot_be_composed_as_a_failure(
        make, templates, monkeypatch):
    # only the prompt under test: the others the stage loads are the real
    # profile's and are composed from the core's templates, not from these
    monkeypatch.setattr(doctor, "_prompt_ids", lambda stage: (ROWS,))
    profile = make(extends="kwp", language="xx", files={
        ROWS: parts_with(drop=("example_reply",))})
    lines = [line for line in doctor.check_stages("extract", profile)
             if line.area == "prompts"]
    assert [line.status for line in lines] == [doctor.FAIL]
    assert "example_reply" in lines[0].detail and ROWS in lines[0].detail
    assert "<!-- part: name -->" in lines[0].hint


def test_the_doctor_passes_the_same_profile_when_the_part_is_there(
        make, templates, monkeypatch):
    monkeypatch.setattr(doctor, "_prompt_ids", lambda stage: (ROWS,))
    profile = make(extends="kwp", language="xx", files={ROWS: PARTS})
    lines = [line for line in doctor.check_stages("extract", profile)
             if line.area == "prompts"]
    assert [line.status for line in lines] == [doctor.OK]


# ---------------------------------------------------------------------------
# AND the language is that of the profile that owns the parts file
# ---------------------------------------------------------------------------

def test_a_language_gives_its_own_templates_text(make, templates):
    templates("yy", "rows", TEMPLATE_YY)
    _, xx = rows_of(make, PARTS, language="xx")
    _, yy = rows_of(make, PARTS, language="yy")
    assert xx.text == EXPECTED
    assert yy.text == EXPECTED.replace(
        "You get sources.", "Sources are given.").replace(
        "Reply with one JSON object; a quote has at least",
        "One JSON object is the reply; cite no fewer than").replace(
        "characters:", "letters:")
    assert "Sources are given." in yy.text and "Sources are given." not in xx.text


def test_a_child_that_inherits_the_parts_of_its_parent_gets_the_parents_language(
        make, templates):
    """The case that breaks it: the child declares another language, and the
    parts files it inherits are in the parent's. It gets that language, not
    the one it declares."""
    templates("yy", "rows", TEMPLATE_YY)
    parent = make(language="xx", files={ROWS: PARTS})
    child = make(extends=parent.name, language="yy")
    assert prompts.owner_of(ROWS, child).name == parent.name
    assert prompts.load(ROWS, child).text == EXPECTED
    assert prompts.load(ROWS, child).composition["language"] == "xx"


def test_a_child_with_a_parts_file_of_its_own_is_read_in_its_own_language(
        make, templates):
    """Built to fail: the case above, plus a parts file of the child's."""
    templates("yy", "rows", TEMPLATE_YY)
    parent = make(language="xx", files={ROWS: PARTS})
    child = make(extends=parent.name, language="yy", files={ROWS: PARTS})
    assert prompts.owner_of(ROWS, child).name == child.name
    assert "Sources are given." in prompts.load(ROWS, child).text


def test_a_child_that_declares_nothing_gets_the_language_of_the_parent(
        make, templates):
    parent = make(language="xx", files={ROWS: PARTS})
    child = make(extends=parent.name)
    assert prompts.load(ROWS, child).text == EXPECTED


def test_a_declaration_of_a_profile_that_does_not_own_the_parts_is_not_read(
        make, templates):
    parent = make(language=None, files={ROWS: PARTS})
    child = make(extends=parent.name, language="xx")
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load(ROWS, child)
    assert "declares no extraction.CONTRACT_LANGUAGE" in str(raised.value)
    assert parent.name in str(raised.value)


def test_a_profile_declares_for_itself_and_inherits_nothing_of_it(make):
    parent = make(language="xx")
    child = make(extends=parent.name)
    assert parent.own("extraction", "CONTRACT_LANGUAGE") == "xx"
    assert child.own("extraction", "CONTRACT_LANGUAGE") is None
    assert child.component("extraction", "CONTRACT_LANGUAGE") == "xx"


def test_a_profile_that_declares_no_language_is_refused_and_the_languages_named(
        make, templates):
    templates("yy", "rows", TEMPLATE_YY)
    error = refusal(make, PARTS, language=None)
    assert "declares no extraction.CONTRACT_LANGUAGE" in str(error)
    assert "['xx', 'yy']" in str(error)


def test_an_unknown_language_is_refused_and_the_languages_there_are_named(
        make, templates):
    templates("yy", "rows", TEMPLATE_YY)
    error = refusal(make, PARTS, language="zz")
    assert "'zz'" in str(error) and "['xx', 'yy']" in str(error)


@pytest.mark.parametrize("language", ["../templates/xx", "XX", "", "x x"])
def test_a_language_that_is_not_a_folder_name_is_not_a_language(
        make, templates, language):
    error = refusal(make, PARTS, language=language)
    assert "not a language the core has templates for" in str(error)


def test_the_core_with_no_templates_says_it_has_none(make, tmp_path, monkeypatch):
    monkeypatch.setattr(contract, "TEMPLATE_ROOT", tmp_path / "nowhere")
    error = refusal(make, PARTS, language="xx")
    assert "it has none" in str(error)


def test_the_languages_and_templates_are_the_folders_and_files_there_are(
        templates, tmp_path):
    templates("yy", "rows", TEMPLATE_YY)
    templates("yy", "frame", "---\nrequired: [role]\n---\n{{role}}\n")
    write(tmp_path / "templates" / "empty" / "notes.txt", "no template here")
    write(tmp_path / "templates" / "Not-A-Name" / "rows.md", "x")
    assert contract.languages() == ["xx", "yy"]
    assert contract.template_names("yy") == ["frame", "rows"]
    assert contract.template_names("xx") == ["rows"]
    assert contract.template_names("nowhere") == []
    assert contract.available() == [("xx", "rows"), ("yy", "frame"),
                                    ("yy", "rows")]


@pytest.mark.parametrize("language, name", [
    ("../xx", "rows"), ("xx", "../rows"), ("xx", "a/b"), ("XX", "rows"),
    ("xx", ""), ("xx", "Rows")])
def test_no_name_reaches_outside_the_template_folder(language, name):
    with pytest.raises(ValueError):
        contract.template_path(language, name)
    assert contract.template_path("xx", "rows").parent.parent == contract.TEMPLATE_ROOT


# ---------------------------------------------------------------------------
# AND the fingerprint is the sha256 of the file a person would have written
# ---------------------------------------------------------------------------

def sha_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_fingerprint_is_the_sha_of_the_monolithic_file_with_the_same_text(
        make, templates):
    _, prompt = rows_of(make, PARTS)
    assert prompt.sha256 == sha_of(FRONT + EXPECTED)


@pytest.mark.parametrize("front, written", [
    # the loader's keys anywhere in the front matter
    ("---\ntemperature: 0\ntemplate: rows\nmax_tokens: 100\n---\n", FRONT),
    # a list under a key of the loader goes with its key
    ("---\ntemplate: rows\nwithout:\n  - images\n  - sandbox\ntemperature: 0\n"
     "max_tokens: 100\n---\n", FRONT),
    ("---\ntemperature: 0\nmax_tokens: 100\nwithout:\n  - images\n  - sandbox\n"
     "template: rows\n---\n", FRONT),
    # a comment and a blank line that belong to the others stay
    ("---\n# the model\ntemperature: 0\n\ntemplate: rows\nmax_tokens: 100\n---\n",
     "---\n# the model\ntemperature: 0\n\nmax_tokens: 100\n---\n"),
    # nothing is left: the file a person would write has no front matter
    ("---\ntemplate: rows\n---\n", ""),
])
def test_the_fingerprint_follows_the_front_matter_the_profile_wrote(
        make, templates, front, written):
    omitted = "without" in front
    _, prompt = rows_of(make, parts_with(front=front))
    text = EXPECTED_WITHOUT if omitted else EXPECTED
    assert prompt.text == text
    assert prompt.sha256 == sha_of(written + text)


def test_the_keys_of_the_loader_are_not_parameters_of_the_request(make, templates):
    _, prompt = rows_of(make, parts_with(front=without("sandbox")))
    assert set(prompt.meta) == {"temperature", "max_tokens"}


def test_the_fingerprint_moves_with_a_part_the_template_the_language_and_a_block(
        make, templates):
    """Built to fail: one change each, and the sha is another."""
    templates("yy", "rows", TEMPLATE_YY)
    base = rows_of(make, PARTS)[1].sha256
    other_part = rows_of(make, parts_with(("role", "You read tables.")))[1].sha256
    other_language = rows_of(make, PARTS, language="yy")[1].sha256
    left_out = rows_of(make, parts_with(front=without("images")))[1].sha256
    worded = rows_of(make, parts_with(("row_note", "Read twice.")))[1].sha256
    templates("xx", "rows", TEMPLATE_XX.replace("Invent nothing", "Make up nothing"))
    other_template = rows_of(make, PARTS)[1].sha256
    assert len({base, other_part, other_language, left_out, worded,
                other_template}) == 6


def test_the_fingerprint_follows_the_text_and_not_the_parts_file(make, templates):
    """Two parts files that make one text have one sha: it is the text's."""
    _, first = rows_of(make, PARTS)
    spaced = parts_with().replace("<!-- part: example_reply -->\n",
                                  "<!-- part: example_reply -->\n\n\n")
    _, second = rows_of(make, spaced)
    assert first.text == second.text and first.sha256 == second.sha256


def test_the_version_a_run_records_is_the_composed_prompts(make, templates):
    profile, prompt = rows_of(make, PARTS)
    assert prompts.versions([ROWS], profile) == {ROWS: prompt.sha256}


# ---------------------------------------------------------------------------
# AND nothing goes stale because a prompt became composed
# ---------------------------------------------------------------------------

def test_a_stamp_from_before_the_prompts_were_composed_is_current(
        make, templates, shipped, tmp_path, monkeypatch):
    from tests.test_extraction_topup import SPEC
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    old = runner._stamp_current("a" * 64, "b" * 16, SPEC)
    profile = make(extends="kwp", language="xx", files={ROWS: PARTS})
    monkeypatch.setenv("DOCPIPE_PROFILE", profile.name)
    new = runner._stamp_current("a" * 64, "b" * 16, SPEC)
    assert new[ROWS] != old[ROWS], "the prompt really is another one"
    path = write(tmp_path / "plan.stamp.json", json.dumps(old))
    assert runner.stale(path, new) == []


def test_that_comparison_can_see_a_question_that_moved(
        make, templates, shipped, tmp_path, monkeypatch):
    """Built to fail: the stamp of the case above, with one question that is
    not today's."""
    from tests.test_extraction_topup import SPEC
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    old = runner._stamp_current("a" * 64, "b" * 16, SPEC)
    profile = make(extends="kwp", language="xx", files={ROWS: PARTS})
    monkeypatch.setenv("DOCPIPE_PROFILE", profile.name)
    new = runner._stamp_current("a" * 64, "b" * 16, SPEC)
    axis = next(key for key in old if key.startswith("axis/"))
    path = write(tmp_path / "plan.stamp.json", json.dumps({**old, axis: "moved"}))
    assert runner.stale(path, new) == [axis]


# ---------------------------------------------------------------------------
# AND a file that names no template is read as it always was
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_a_plain_prompt_keeps_the_sha_of_its_file_and_its_text(name):
    """Every prompt file of the profile, found by looking: the ones that name
    no template are read as they always were (the search sentences and the
    other stages are never composed, and an extraction prompt is plain until it
    is cut into parts), and the ones that do are composed."""
    profile = load_profile(name)
    plain, composed = [], []
    for path in sorted(profile.prompts_dir.rglob("*.md")):
        raw = path.read_text(encoding="utf-8")
        prompt_id = f"{path.parent.name}/{path.stem}"
        prompt = prompts.load(prompt_id, profile)
        assert prompt.path == path
        if "template" in prompts._split(raw)[0]:
            assert prompt.composition is not None, prompt_id
            composed.append(prompt_id)
            continue
        assert prompt.sha256 == sha_of(raw), prompt_id
        assert prompt.composition is None, prompt_id
        assert raw.endswith(prompt.text), prompt_id
        plain.append(prompt_id)
    assert {"extraction/phrase", "extraction/anchors",
            "extraction/queries"} <= set(plain)
    assert len(plain) + len(composed) == len(
        list(profile.prompts_dir.rglob("*.md")))


def test_a_plain_prompt_with_front_matter_keeps_every_key(make):
    profile = make(files={"refinement/refine": (
        "---\ntemperature: 0.1\nmax_tokens: 50\nwithout: [x]\n---\nPlain.\n")})
    prompt = prompts.load("refinement/refine", profile)
    assert prompt.meta == {"temperature": 0.1, "max_tokens": 50, "without": ["x"]}
    assert prompt.text == "Plain.\n"


def test_a_stage_without_templates_refuses_a_prompt_that_names_one(make, templates):
    """Built to fail: the same file without its `template` key is a prompt."""
    profile = make(files={"refinement/refine": (
        "---\ntemplate: rows\n---\n<!-- part: role -->\nx\n")})
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load("refinement/refine", profile)
    assert "no templates" in str(raised.value)
    assert raised.value.prompt_id == "refinement/refine"
    plain = make(files={"refinement/refine": "---\ntemperature: 0\n---\nx\n"})
    assert prompts.load("refinement/refine", plain).text == "x\n"


def test_the_profile_that_owns_a_file_is_found_down_the_line(make):
    parent = make(files={"refinement/refine": "Parent.\n"})
    child = make(extends=parent.name)
    own = make(extends=parent.name, files={"refinement/refine": "Own.\n"})
    nobody = make(extends=parent.name)
    assert prompts.owner_of("refinement/refine", child).name == parent.name
    assert prompts.owner_of("refinement/refine", own).name == own.name
    # nobody has it: the profile itself, where the message says it should be
    assert prompts.owner_of("refinement/missing", nobody).name == nobody.name
    with pytest.raises(ValueError):
        prompts.owner_of("no_stage", nobody)


# ---------------------------------------------------------------------------
# The facts
# ---------------------------------------------------------------------------

def test_a_fact_is_what_the_code_and_the_profiles_phrases_say(make, templates):
    templates("xx", "facts", (
        "---\nrequired: [role]\n---\n{{role}}\n{{min_quote_chars}}|{{unstated}}|"
        "{{option_means}}|{{option_spellings}}|{{unstated_means}}|"
        "{{unstated_spelling}}|{{frame_options}}\n"))
    profile = make(language="xx", phrases={
        "option_means": "definition", "frame_options": "choices"},
        files={"extraction/facts": (
            "---\ntemplate: facts\n---\n<!-- part: role -->\nR\n")})
    # the built-in profile's sentences stand where this one words none
    assert prompts.load("extraction/facts", profile).text == (
        "R\n8|out:unstated|definition|spellings|these passages do not state "
        "it|not stated in these passages|choices\n")
    phrases = wording.phrases(profile)
    assert [phrases[key] for key in ("option_means", "frame_options")] == [
        "definition", "choices"]


def test_a_fact_the_core_does_not_have_is_not_a_fact():
    with pytest.raises(KeyError):
        contract.facts(load_profile("default"), ["min_quote_chars", "nonsense"])


def test_only_the_facts_a_prompt_names_are_read(make, templates, monkeypatch):
    """A profile whose sentences are incomplete is told by a prompt that needs
    them, and not by one that does not."""
    def broken(profile=None):
        raise LookupError("the phrases are incomplete")
    monkeypatch.setattr(wording, "phrases", broken)
    _, prompt = rows_of(make, PARTS)            # uses min_quote_chars, unstated
    assert prompt.text == EXPECTED
    templates("xx", "needs", "---\nrequired: [role]\n---\n{{role}} {{option_means}}\n")
    profile = make(language="xx", files={"extraction/needs": (
        "---\ntemplate: needs\n---\n<!-- part: role -->\nR\n")})
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.load("extraction/needs", profile)
    assert "phrases are incomplete" in str(raised.value)


# ---------------------------------------------------------------------------
# The pieces, each on its own
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, ok", [
    ("rows", True), ("field_2", True), ("de", True),
    ("Rows", False), ("2rows", False), ("a-b", False), ("a/b", False),
    ("..", False), ("", False), ("rows ", False)])
def test_is_name_takes_what_can_be_a_folder_and_a_file_name_and_no_other(text, ok):
    assert contract.is_name(text) is ok


def test_language_of_is_what_the_profile_declares_and_not_what_it_inherits(make):
    parent = make(language="xx")
    assert contract.language_of(parent) == "xx"
    assert contract.language_of(make(extends=parent.name)) is None
    assert contract.language_of(make(language="")) == ""


def test_a_template_is_read_into_what_it_asks_of_a_profile(templates):
    template = prompts.read_template(
        contract.template_path("xx", "rows"), language="xx", name="rows",
        fact_names=contract.FACT_NAMES)
    assert (template.name, template.language) == ("rows", "xx")
    assert template.required == ("role", "example_reply")
    assert template.optional == ("value_more", "sandbox_more")
    assert template.blocks == ("images", "row_note", "sandbox")
    assert template.omittable == ("images", "sandbox")
    assert template.rules == ("value", "quote", "sandbox", "invent")
    assert template.block_counts == {"images": 1, "row_note": 1, "sandbox": 2}
    assert template.shape()["rules"] == frozenset(template.rules)
    # where a name lies: the blocks around it
    assert template.places["sandbox_more"] == ("sandbox",)
    assert template.places["role"] == () and template.rule_blocks["sandbox"] == ("sandbox",)


def test_a_template_is_not_read_when_a_fact_is_not_one_of_the_cores(templates):
    """Built to fail: the slot of a fact is a fact only when the core has it."""
    path = contract.template_path("xx", "rows")
    with pytest.raises(prompts.PromptPartsError) as raised:
        prompts.read_template(path, language="xx", name="rows", fact_names=())
    assert "neither a part of this template" in str(raised.value)


def test_the_parts_of_a_file_are_the_sections_between_the_lines_that_name_them():
    def fail(message, part=None):
        return ValueError((message, part))

    body = ("\n<!-- part: a -->\n\n  indented first line\nsecond\n\n\n"
            "<!-- part: b -->\nonly one   \n")
    assert prompts.read_parts(body, fail) == {
        "a": "  indented first line\nsecond", "b": "only one"}
    assert prompts.read_parts("", fail) == {}
    with pytest.raises(ValueError) as raised:
        prompts.read_parts("loose\n<!-- part: a -->\nx\n", fail, offset=4)
    assert "in line 5" in str(raised.value)


def test_line_at_counts_the_lines_of_the_file_and_not_of_the_body():
    body = "one\ntwo\nthree"
    assert prompts.line_at(body, 0, 0) == 1
    assert prompts.line_at(body, 0, body.index("two")) == 2
    assert prompts.line_at(body, 4, body.index("three")) == 7


def test_a_template_names_the_line_of_a_mark_it_does_not_know(make, templates):
    templates("xx", "bad", template_of(body="{{role}}\nfine\n<!-- note -->\n"))
    error = refusal(make, "---\ntemplate: bad\n---\n<!-- part: role -->\nx\n")
    assert "line 6:" in str(error)
