"""The tool that shows what a change does to the prompts of a profile.

Its promise, as one sentence. Given what the two sides say of a profile, the
tool tells for every prompt whether it is the same on both (text, parameters,
sha256), AND which sentences differ, AND takes each side's numbers by that
side's own rule, AND counts what could not be read or computed as a problem
and ends the run with 1 on it, AND refuses a request it cannot carry out
before anything is read or written (an output folder inside the repository or
one that holds files, a profile that is a path, a profile on neither side),
AND does not fail on what an option has nothing to show for, AND ends the run
with 1 on a domain line outside the contract ranges that is not in the new
text.

Every AND has its tests below, each with a case built to break it.

What these tests leave out, on the owner's word (2026-10-07). They build no
repository, unpack no commit and start no process: the two sides are handed to
the tool as the data its probes return, and the real code is read in this
process. So the way from a ref to that data (`read_sides`: the archive of a
commit, a process per side) has no test. And they assert what the tool decided
(a status, a count, the lines of a diff, an exit code, a refusal), not the
wording it reports it in.
"""
import difflib
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import render_prompts as rp  # noqa: E402

SHA, HEAD = "a" * 40, "b" * 40

ROWS = "Find the numbers. Quote the passage. Never invent a value.\n"
FIELD = "Answer one field. Be brief.\n"


# ---------------------------------------------------------------------------
# The two sides, as the data a probe returns
# ---------------------------------------------------------------------------

def rec(text: str, *, sha: str = "", owner: str = "alpha", front_lines=0,
        composition=None, **meta) -> dict:
    """One prompt as a probe describes it."""
    return {"text": text, "meta": meta, "owner": owner,
            "sha256": sha or hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "front_lines": front_lines, "composition": composition}


def side(prompts=None, *, numbers=None, lineage=("alpha",)) -> dict:
    """What a probe says of a profile it could read."""
    return {"state": "ok", "prompts": dict(prompts or {}),
            "numbers": {"configured": False} if numbers is None else numbers,
            "lineage": list(lineage)}


MISSING = {"state": "missing", "detail": "unknown profile", "prompts": {},
           "numbers": None, "lineage": []}
FAILED = {"state": "failed", "detail": "SyntaxError: invalid syntax",
          "prompts": {}, "numbers": None, "lineage": []}
REFUSED = {"error": "ValueError: the loader refuses this prompt"}


def numbers(window: int, sources: int, budgets: dict,
            rule: str = "sent") -> dict:
    """What a probe computed of a profile with an extraction spec."""
    return {"configured": True, "rule": rule, "framed": False,
            "sources_per_request": sources, "window_tokens": window,
            "budgets": budgets,
            "settings": {name: 0 for name in rp.SETTING_NAMES}}


def reported(before: dict, after: dict, *, ranges=None, what_if=False):
    """`report` for one profile, with what a test asks of it by name."""
    args = SimpleNamespace(before="HEAD", what_if=what_if)
    lines, written, problems = rp.report(
        args, ["alpha"], ranges, SHA, HEAD, False,
        {("before", "alpha"): before, ("after", "alpha"): after})
    rows = written[0][1] if written else []
    return SimpleNamespace(
        text="\n".join(lines), written=written, problems=problems,
        status={pid: state for pid, state, _b, _a in rows},
        order=[row[0] for row in rows],
        files=written[0][2] if written else [])


def changed(diff: str) -> list:
    """The lines of a `.sentences.diff` that say a sentence moved."""
    return [line for line in diff.splitlines()[2:] if line[:1] in "+-"]


def body(diff: str) -> list:
    """A `.sentences.diff` without the two lines that name its sides."""
    return diff.splitlines()[2:]


def files_under(folder: Path) -> list:
    return sorted(path.relative_to(folder).as_posix()
                  for path in folder.rglob("*") if path.is_file())


# ---------------------------------------------------------------------------
# AND whether a prompt is the same on both sides
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("before,after,state", [
    ({"text": "a", "meta": {}, "sha256": "1"},
     {"text": "a", "meta": {}, "sha256": "1"}, rp.IDENTICAL),
    ({"text": "a", "meta": {}, "sha256": "1"},
     {"text": "b", "meta": {}, "sha256": "2"}, rp.CHANGED),
    # the system message is the same, the request is not
    ({"text": "a", "meta": {"max_tokens": 1}, "sha256": "1"},
     {"text": "a", "meta": {"max_tokens": 2}, "sha256": "1"}, rp.CHANGED),
    # the same text and parameters, the file written differently: the sha256
    # is what a stamp records
    ({"text": "a", "meta": {}, "sha256": "1"},
     {"text": "a", "meta": {}, "sha256": "2"}, rp.CHANGED),
    (None, {"text": "a", "meta": {}, "sha256": "1"}, rp.ADDED),
    ({"text": "a", "meta": {}, "sha256": "1"}, None, rp.REMOVED),
    ({"error": "boom"}, {"text": "a", "meta": {}, "sha256": "1"}, rp.ERROR),
    ({"text": "a", "meta": {}, "sha256": "1"}, {"error": "boom"}, rp.ERROR),
])
def test_what_makes_a_prompt_the_same_on_both_sides(before, after, state):
    assert rp.status_of(before, after) == state


def test_every_prompt_of_either_side_gets_its_status_and_what_moved_comes_first():
    before = side({"x/rows": rec(ROWS), "x/field": rec(FIELD),
                   "x/old": rec("Gone.\n")})
    after = side({"x/rows": rec(ROWS.replace("Quote", "Cite")),
                  "x/field": rec(FIELD), "x/new": rec("New.\n")})

    found = reported(before, after)

    assert found.status == {"x/rows": rp.CHANGED, "x/field": rp.IDENTICAL,
                            "x/new": rp.ADDED, "x/old": rp.REMOVED}
    assert found.order == ["x/rows", "x/new", "x/old", "x/field"]
    assert found.problems == 0


# ---------------------------------------------------------------------------
# AND the sentences that differ
# ---------------------------------------------------------------------------

def test_a_line_is_cut_into_sentences_and_not_into_abbreviations():
    assert rp.sentences("One. Two! Three? Four.") == [
        "One.", "Two!", "Three?", "Four."]
    assert rp.sentences("Use e.g. a table, z. B. a list. Next.") == [
        "Use e.g. a table, z. B. a list.", "Next."]
    assert rp.sentences("3. Opens a list item. And ends.") == [
        "3. Opens a list item.", "And ends."]
    assert rp.sentences("In 2045. Then it ends.") == [
        "In 2045.", "Then it ends."]
    assert rp.sentences("No capital. follows here") == [
        "No capital. follows here"]
    assert rp.sentences('He said. "Quoted." Done.') == [
        "He said.", '"Quoted."', "Done."]
    assert rp.sentences("") == [""]


def test_a_cut_loses_no_text_but_the_space_it_cut_at():
    line = '  Led by spaces. "Quoted." (Bracketed.) End of it.  '
    assert " ".join(p.strip() for p in rp.sentences(line)) \
        == " ".join(line.split())


def test_the_units_of_a_text_keep_blank_lines_and_the_final_newline():
    assert rp.units("Alpha. Bravo.\n\nCharlie.\n") == [
        "Alpha.", "Bravo.", "", "Charlie.", ""]
    assert rp.units("Alpha.") != rp.units("Alpha.\n")


def test_two_texts_that_differ_by_one_sentence_differ_by_two_lines():
    before = rp.units("Alpha. Bravo. Charlie. Delta. Echo. Foxtrot.\n")
    after = rp.units("Alpha. Bravo. Xray. Delta. Echo. Foxtrot.\n")
    diff = rp.unified(before, after, context=1)
    assert [line for line in diff if line[0] in "+-"] == ["-Charlie.", "+Xray."]
    assert rp.unified(before, before) == []


def test_a_long_text_with_many_blank_lines_is_diffed_down_to_what_changed():
    """The stock `difflib.unified_diff` treats an item that repeats as junk
    once a list holds 200, and blank lines repeat: it reports the blank line
    between two edited sentences as changed as well."""
    before = []
    for n in range(150):
        before += [f"S{n}.", ""]
    after = list(before)
    after[100:104] = ["", "", "", ""]               # S50. and S51. gone

    diff = rp.unified(before, after)

    assert [line for line in diff if line[0] in "+-"] == [
        "-S50.", "-S51.", "+", "+"]
    stock = [line for line in difflib.unified_diff(before, after, lineterm="")
             if line[0] in "+-" and not line.startswith(("+++", "---"))]
    assert len(stock) > 4


def test_each_changed_sentence_is_one_line_of_the_diff():
    """One sentence of three is edited in a paragraph that is one line of the
    file. A diff by lines would show the whole paragraph twice."""
    diff = rp.diff_text("x/rows", rec(ROWS), rec(
        ROWS.replace("Quote the passage.", "Quote the whole passage.")))

    assert changed(diff) == ["-Quote the passage.", "+Quote the whole passage."]
    assert " Find the numbers." in body(diff)       # context, not change
    assert " Never invent a value." in body(diff)


def test_trailing_whitespace_is_a_changed_sentence():
    """The model reads the space."""
    diff = rp.diff_text("x/field", rec(FIELD),
                        rec(FIELD.replace("Be brief.", "Be brief. ")))
    assert changed(diff) == ["-Be brief.", "+Be brief. "]


def test_an_added_or_a_removed_prompt_is_one_block_of_sentences():
    assert changed(rp.diff_text("x/new", None, rec("One. Two.\n"))) == [
        "+One.", "+Two."]
    assert changed(rp.diff_text("x/old", rec("One. Two.\n"), None)) == [
        "-One.", "-Two."]


# What moves a prompt without moving a sentence of it.
SILENT = {
    "the space between two sentences": (
        rec(FIELD), rec(FIELD.replace("field. Be", "field.  Be"))),
    "a parameter": (rec(FIELD, max_tokens=1000), rec(FIELD, max_tokens=900)),
    "how the file is written": (rec(FIELD, sha="1" * 64),
                                rec(FIELD, sha="2" * 64)),
}


@pytest.mark.parametrize("what", sorted(SILENT))
def test_a_change_no_sentence_shows_never_reads_as_no_change(what):
    """No sentence differs, the prompt does. A diff that showed nothing, or
    what it shows for two equal sides, would read as 'nothing changed'."""
    before, after = SILENT[what]
    same = body(rp.diff_text("x/field", before, before))

    diff = rp.diff_text("x/field", before, after)

    assert rp.status_of(before, after) == rp.CHANGED
    assert changed(diff) == []
    assert body(diff) and body(diff) != same


def test_the_diff_says_which_of_them_it_was_and_names_a_parameters_two_values():
    said = {what: tuple(body(rp.diff_text("x/field", *pair)))
            for what, pair in SILENT.items()}
    assert len(set(said.values())) == len(SILENT)
    moved = "\n".join(said["a parameter"])
    assert "max_tokens" in moved and "1000" in moved and "900" in moved


# ---------------------------------------------------------------------------
# What is written
# ---------------------------------------------------------------------------

def test_a_prompt_gets_the_file_of_each_side_it_has_and_a_diff_when_both_read(
        tmp_path):
    rows = rp.compare(
        side({"x/same": rec(ROWS), "x/old": rec("Gone.\n"),
              "x/bad": rec(FIELD)}),
        side({"x/same": rec(ROWS), "x/new": rec("New.\n"), "x/bad": REFUSED}))

    rp.write_profile(tmp_path, "alpha", rows, [], ("before", "after"))

    assert files_under(tmp_path / "alpha" / "x") == [
        "bad.before.txt",
        "new.after.txt", "new.sentences.diff",
        "old.before.txt", "old.sentences.diff",
        "same.after.txt", "same.before.txt", "same.sentences.diff"]


def test_a_text_is_written_byte_for_byte_as_the_loader_gave_it(tmp_path):
    """The trailing spaces and the final newline stay and the umlaut is UTF-8.
    Written as text, the platform would make its own line ends of them."""
    text = "Line one, with an umlaut ä.  \nLine two…\n"
    rows = rp.compare(side({"x/p": rec(text)}), side({"x/p": rec(text)}))

    rp.write_profile(tmp_path, "alpha", rows, [], ("before", "after"))

    for name in ("p.before.txt", "p.after.txt"):
        assert (tmp_path / "alpha" / "x" / name).read_bytes() \
            == text.encode("utf-8")


def test_a_block_put_back_is_written_with_what_it_adds(tmp_path):
    rows = rp.compare(side({"x/rows": rec(ROWS)}), side({"x/rows": rec(ROWS)}))
    with_block = ROWS + "Sandbox rule.\n"

    rp.write_profile(tmp_path, "alpha", rows,
                     [("x/rows", "sandbox", with_block)], ("before", "after"))

    base = tmp_path / "alpha" / "x"
    assert (base / "rows.what-if.sandbox.txt").read_bytes() \
        == with_block.encode("utf-8")
    assert changed((base / "rows.what-if.sandbox.sentences.diff").read_text(
        encoding="utf-8")) == ["+Sandbox rule."]


# ---------------------------------------------------------------------------
# AND the numbers by each side's own rule
# ---------------------------------------------------------------------------

SIZING_ID, ROWS_ID, FIELD_ID, REVIEW_ID, QUERIES_ID = (
    f"extraction/{name}" for name in
    ("sizing", "rows", "field", "review", "queries"))


class Library:
    """A loader over prompts held in memory. A prompt is what the runner
    below counts of it: its budget and the sources it leaves room for."""

    def __init__(self, **found):
        self.found = {f"extraction/{name}": SimpleNamespace(
            budget=budget, sources=sources)
            for name, (budget, sources) in found.items()}

    def load(self, pid, profile=None):
        if pid not in self.found:
            raise FileNotFoundError(pid)
        return self.found[pid]


def printing(library: Library, pid: str):
    """A window command that counts one prompt and prints its budget."""
    def command(runner):
        print(runner.context_budget(library.load(pid)))
        return 0
    return command


def runner_of(command=None, **more):
    """What the tool reads of a runner. *command* is what its
    `--print-context-budget` does, given the runner."""
    made = SimpleNamespace(
        PROMPT_IDS=(SIZING_ID, ROWS_ID, FIELD_ID, QUERIES_ID),
        REVIEW_PROMPT_ID=REVIEW_ID, QUERIES_PROMPT_ID=QUERIES_ID,
        load_spec=lambda path: "spec",
        context_budget=lambda prompt, spec=None: prompt.budget,
        fit_batch_sources=lambda prompt, spec: prompt.sources,
        **{name: index for index, name in enumerate(rp.SETTING_NAMES)})
    if command is not None:
        made.main = lambda argv: command(made)
    for name, value in more.items():
        setattr(made, name, value)
    return made


def numbers_by(monkeypatch, runner, library: Library, frame=()) -> dict:
    """`_numbers` with *runner* standing where it imports the tree's own."""
    import docpipe.extraction as extraction
    monkeypatch.setattr(extraction, "runner", runner, raising=False)
    monkeypatch.setattr(extraction, "fields", SimpleNamespace(
        frame_slots=lambda spec, frame: list(frame)), raising=False)
    profile = SimpleNamespace(
        component=lambda module, attr: frame if attr == "FRAME" else None)
    return rp._numbers(profile, library, "spec.json")


LIBRARY = Library(sizing=(900, 3), rows=(500, 2), field=(300, 1),
                  review=(200, 1))


def test_each_side_takes_its_numbers_by_its_own_rule(monkeypatch):
    """A runner that says what a run sends is asked for it. One from before
    is read off its own command. The two give different numbers for the same
    prompts here: a tool that used one rule for both would show them equal."""
    newer = runner_of(request_budget=lambda spec, framed: 500,
                      batch_sources_for=lambda spec: 2)
    older = runner_of(printing(LIBRARY, SIZING_ID))

    after = numbers_by(monkeypatch, newer, LIBRARY)
    before = numbers_by(monkeypatch, older, LIBRARY)

    assert (after["rule"], after["window_tokens"],
            after["sources_per_request"]) == ("sent", 500, 2)
    assert (before["rule"], before["window_tokens"],
            before["sources_per_request"]) == ("single", 900, 3)


def test_an_older_runner_is_read_off_the_prompt_its_own_command_counts():
    """The tool is not told which prompt that tree sizes its window from.
    Built to fail: the command counting the field prompt, which is not the
    first of the runner's list, where a tool that guessed would look."""
    for pid, want in ((SIZING_ID, (900, 3)), (FIELD_ID, (300, 1))):
        runner = runner_of(printing(LIBRARY, pid))
        assert rp._single_prompt_rule(runner, "spec") == want


def _counts_all(runner):
    print(max(runner.context_budget(LIBRARY.load(pid))
              for pid in (SIZING_ID, ROWS_ID, FIELD_ID)))
    return 0


def _counts_one_prints_another(runner):
    runner.context_budget(LIBRARY.load(SIZING_ID))
    print(7)
    return 0


def _prints_what_it_did_not_count(runner):
    print(7)
    return 0


def _stops(runner):
    raise SystemExit(3)


def _ends_with_an_error(runner):
    print(runner.context_budget(LIBRARY.load(SIZING_ID)))
    return 2


@pytest.mark.parametrize("command", [
    _counts_all, _counts_one_prints_another, _prints_what_it_did_not_count,
    _stops, _ends_with_an_error])
def test_a_window_command_that_is_not_one_prompts_budget_is_no_rule_and_no_guess(
        command):
    runner = runner_of(command)
    asked = runner.context_budget

    with pytest.raises(RuntimeError):
        rp._single_prompt_rule(runner, "spec")

    assert runner.context_budget is asked       # the runner is as it was


def test_a_runner_with_neither_rule_is_no_rule_and_no_guess():
    with pytest.raises(RuntimeError):
        rp._single_prompt_rule(runner_of(), "spec")


def test_every_prompt_a_request_can_carry_has_its_budget(monkeypatch):
    """The search templates are no request. A prompt the profile does not
    have is said to be absent and is not left out."""
    library = Library(sizing=(900, 3), rows=(500, 2), field=(300, 1))

    found = numbers_by(monkeypatch, runner_of(printing(library, SIZING_ID)),
                       library)

    assert found["budgets"] == {SIZING_ID: 900, ROWS_ID: 500, FIELD_ID: 300,
                                REVIEW_ID: None}


def test_the_frame_axes_of_the_profile_reach_the_rule(monkeypatch):
    runner = runner_of(request_budget=lambda spec, framed: 1000 + framed,
                       batch_sources_for=lambda spec: 2)

    assert numbers_by(monkeypatch, runner, LIBRARY)["window_tokens"] == 1000
    framed = numbers_by(monkeypatch, runner, LIBRARY, frame=("year",))
    assert framed["framed"] is True and framed["window_tokens"] == 1001


def test_a_setting_the_runner_no_longer_has_is_an_error_and_not_a_none(
        monkeypatch):
    """A constant that was renamed means the budget is counted another way.
    As None it would stand in the table and look like a value."""
    runner = runner_of(printing(LIBRARY, SIZING_ID))
    assert set(numbers_by(monkeypatch, runner, LIBRARY)["settings"]) \
        == set(rp.SETTING_NAMES)

    delattr(runner, "PRIOR_TOKENS")

    with pytest.raises(AttributeError):
        numbers_by(monkeypatch, runner, LIBRARY)


def test_the_numbers_of_both_sides_stand_in_the_summary():
    same = {"x/rows": rec(ROWS)}
    found = reported(
        side(same, numbers=numbers(11111, 3, {"x/rows": 7001}, "single")),
        side(same, numbers=numbers(22222, 2, {"x/rows": 7002})))

    assert found.problems == 0
    for value in ("11111", "22222", "7001", "7002"):
        assert value in found.text


def test_a_probe_does_not_read_the_callers_extract_settings(tmp_path,
                                                            monkeypatch):
    """The same two refs must give the same numbers on every machine."""
    monkeypatch.setenv("EXTRACT_BATCH_SOURCES", "2")
    monkeypatch.setenv("EXTRACT_ATTACH_IMAGES", "0")
    monkeypatch.setenv("LLM_MODEL", "kept")
    env = rp.probe_env(tmp_path, "alpha")
    assert not [key for key in env if key.startswith("EXTRACT_")]
    assert env["LLM_MODEL"] == "kept"


def test_a_probe_has_a_home_of_its_own_for_everything_it_may_write(tmp_path):
    env = rp.probe_env(tmp_path, "alpha")
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["DOCPIPE_PROFILE"] == "alpha"
    assert env["DOCPIPE_CONFIG"] == "" and env["DOCPIPE_ENV_FILE"] == ""
    assert Path(env["DOCPIPE_USAGE_DB"]).parent == tmp_path
    assert Path(env["DOCPIPE_DATA_ROOT"]).parent == tmp_path


# ---------------------------------------------------------------------------
# AND what could not be read or computed is a problem, never an empty column
# ---------------------------------------------------------------------------

def test_a_prompt_the_loader_refuses_is_a_problem_and_the_others_are_compared():
    found = reported(side({"x/rows": rec(ROWS), "x/bad": rec(FIELD)}),
                     side({"x/rows": rec(ROWS), "x/bad": REFUSED}))

    assert found.status == {"x/bad": rp.ERROR, "x/rows": rp.IDENTICAL}
    assert found.problems == 1


def test_numbers_that_could_not_be_computed_are_a_problem_and_the_prompts_are_compared():
    same = {"x/rows": rec(ROWS)}
    broken = {"configured": True, "error": "RuntimeError: no rule is known"}

    found = reported(side(same, numbers=numbers(900, 3, {})),
                     side(same, numbers=broken))

    assert found.problems == 1
    assert found.status == {"x/rows": rp.IDENTICAL}


@pytest.mark.parametrize("before, after", [
    (side({"x/rows": rec(ROWS)}), FAILED),
    (FAILED, side({"x/rows": rec(ROWS)})),
])
def test_a_side_that_could_not_be_read_is_a_problem_and_nothing_is_compared(
        before, after):
    """Compared with an empty side, every prompt would read as added or as
    removed."""
    found = reported(before, after)
    assert found.problems == 1
    assert found.written == []


def test_a_profile_one_side_does_not_have_is_all_added_or_all_removed():
    there = side({"x/rows": rec(ROWS), "x/field": rec(FIELD)})

    new = reported(MISSING, there)
    gone = reported(there, MISSING)

    assert set(new.status.values()) == {rp.ADDED} and new.problems == 0
    assert set(gone.status.values()) == {rp.REMOVED} and gone.problems == 0


def test_a_profile_on_neither_side_is_refused():
    with pytest.raises(rp.Refused):
        reported(MISSING, MISSING)


# ---------------------------------------------------------------------------
# AND what an option has nothing to show for is no failure
# ---------------------------------------------------------------------------

def composed(omitted=(), what_if=None) -> dict:
    return {"template": "rows", "overrides": ["value"],
            "omitted": list(omitted), "what_if": dict(what_if or {})}


def test_a_profile_without_a_spec_has_no_numbers_and_that_is_no_problem():
    same = side({"x/rows": rec(ROWS)})
    assert reported(same, same).problems == 0


def test_what_if_where_nothing_is_composed_or_left_out_is_no_problem():
    plain = side({"x/rows": rec(ROWS)})
    whole = side({"x/rows": rec(ROWS, composition=composed())})

    for after in (plain, whole):
        found = reported(plain, after, what_if=True)
        assert found.problems == 0 and found.files == []


def test_a_block_left_out_is_put_back_only_when_asked_for():
    with_block = ROWS + "Sandbox rule.\n"
    after = side({"x/rows": rec(ROWS, composition=composed(
        ["sandbox"], {"sandbox": with_block}))})

    assert reported(after, after).files == []
    asked = reported(after, after, what_if=True)
    assert asked.files == [("x/rows", "sandbox", with_block)]
    assert asked.problems == 0


def test_a_block_left_out_with_no_text_for_it_is_a_problem_when_asked_for():
    """The loader reports a block left out and offers nothing to put back.
    Asking for the what-if and getting a clean exit would be a lie."""
    after = side({"x/rows": rec(ROWS, composition=composed(["sandbox"]))})

    assert reported(after, after).problems == 0
    assert reported(after, after, what_if=True).problems == 1


def test_composition_is_read_from_a_prompt_by_name():
    class Plain:
        pass

    class Composed:
        composition = {"template": "rows", "overrides": ["b", "a"],
                       "omitted": ["x"], "what_if": {"x": "text"}}

    assert rp.composition_of(Plain()) is None
    assert rp.composition_of(Composed()) == {
        "template": "rows", "overrides": ["a", "b"], "omitted": ["x"],
        "what_if": {"x": "text"}}


# ---------------------------------------------------------------------------
# AND a domain line outside the contract ranges is in the new text
# ---------------------------------------------------------------------------

OLD = ("Role line.\n"                     # physical 5
       "\n"                               # 6
       "Contract sentence.\n"             # 7
       "1. Domain rule stays.\n"          # 8
       "Mixed line, both kinds.\n"        # 9
       "2. Another domain rule.\n")       # 10


def _record(text: str) -> dict:
    """A prompt whose file has four lines of front matter above its text."""
    return rec(text, front_lines=4)


def test_a_line_outside_the_ranges_that_is_not_in_the_new_text_is_named():
    new = ("Role line.\n\nNew contract wording.\n"
           "3. Domain rule stays.\nMixed line, new wording.\n")

    found = rp.check_domain(_record(OLD), _record(new), [(7, 7)], [(9, 9)])

    assert found["missing"] == [(10, "2. Another domain rule.")]
    assert found["checked"] == 3 and found["skipped"] == 1
    assert found["mixed"] == [(9, "Mixed line, both kinds.", False)]


def test_a_mixed_line_that_stands_is_listed_as_standing():
    found = rp.check_domain(_record(OLD), _record(OLD), [(7, 7)], [(9, 9)])
    assert found["mixed"] == [(9, "Mixed line, both kinds.", True)]
    assert found["missing"] == []


def test_a_leading_rule_number_is_ignored_and_no_other_number_is():
    old = "1. In 2045 the plan holds.\n"
    assert rp.check_domain(_record(old),
                           _record("7) In 2045 the plan holds.\n"),
                           [], [])["missing"] == []
    assert rp.check_domain(_record(old),
                           _record("1. In 2046 the plan holds.\n"),
                           [], [])["missing"] == [
                               (5, "1. In 2045 the plan holds.")]


def test_a_contract_line_that_went_missing_is_not_a_failure():
    """That is what the rewrite is for. A tool that checked every line would
    fail every rewrite."""
    new = OLD.replace("Contract sentence.", "Other.")
    assert rp.check_domain(_record(OLD), _record(new), [(7, 7)],
                           [(9, 9)])["missing"] == []
    assert rp.check_domain(_record(OLD), _record(new), [], [(9, 9)])[
        "missing"] == [(7, "Contract sentence.")]


def test_a_line_may_move_inside_the_new_text():
    new = "2. Another domain rule.\nRole line.\n1. Domain rule stays.\n"
    found = rp.check_domain(_record(OLD), _record(new), [(7, 7), (9, 9)], [])
    assert found["missing"] == []


def test_blank_lines_are_not_checked():
    found = rp.check_domain(_record("a line\n\n\nanother line\n"),
                            _record("another line a line\n"), [], [])
    assert found["checked"] == 2 and found["missing"] == []


def test_a_range_past_the_end_of_the_old_file_is_refused():
    """Ranges written for another file would leave lines unchecked without a
    word."""
    rp.check_domain(_record(OLD), _record(OLD), [(7, 10)], [])
    with pytest.raises(rp.Refused):
        rp.check_domain(_record(OLD), _record(OLD), [(7, 11)], [])


def test_lines_of_a_file_cannot_be_told_for_a_composed_text():
    composed_text = rec(OLD, front_lines=None)
    with pytest.raises(rp.Refused):
        rp.check_domain(composed_text, _record(OLD), [], [])


def test_the_lines_above_a_text_are_counted_only_when_the_text_ends_its_file(
        tmp_path):
    path = tmp_path / "p.md"
    path.write_bytes(b"---\nmax_tokens: 5\n---\nOne.\nTwo.\n")
    as_written = SimpleNamespace(path=path, text="One.\nTwo.\n")
    put_together = SimpleNamespace(path=path, text="One.\nTwo.\nThree.\n")

    assert rp._front_lines(as_written) == 3
    assert rp._front_lines(put_together) is None
    assert rp.physical_lines({"text": as_written.text, "front_lines": 3}) == [
        (4, "One."), (5, "Two.")]


GOOD_RANGES = '{"a": {"p/q": {"contract": [[1, 2], [5, 5]], "mixed": [[7, 8]]}}}'


def test_a_ranges_file_is_read_into_ranges(tmp_path):
    path = tmp_path / "ranges.json"
    path.write_text(GOOD_RANGES, encoding="utf-8")
    assert rp.read_ranges(path) == {"a": {"p/q": {
        "contract": [(1, 2), (5, 5)], "mixed": [(7, 8)]}}}


@pytest.mark.parametrize("content", [
    "[]",                                                   # no profiles
    '{"a": []}',                                            # no prompts
    '{"a": {"p/q": {"contract": [[1, 2]], "mixd": []}}}',   # a key it ignores
    '{"a": {"p/q": {"mixed": [[1, 2]]}}}',                  # no contract
    '{"a": {"p/q": {"contract": [[0, 2]]}}}',               # lines start at 1
    '{"a": {"p/q": {"contract": [[3, 2]]}}}',               # backwards
    '{"a": {"p/q": {"contract": [[1, true]]}}}',            # not a number
    '{"a": {"p/q": {"contract": [[1, 3]], "mixed": [[3, 4]]}}}',    # both
    "{not json",
])
def test_a_ranges_file_that_would_leave_lines_unchecked_is_refused(
        tmp_path, content):
    """Each differs in one thing from the file the test above reads."""
    path = tmp_path / "ranges.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(rp.Refused):
        rp.read_ranges(path)


RANGES = {"alpha": {"x/rows": {"contract": [(7, 7)], "mixed": [(9, 9)]}}}


@pytest.mark.parametrize("new, problems", [
    (OLD, 0),
    # what the rewrite is for
    (OLD.replace("Contract sentence.", "Other wording."), 0),
    # for a person to read
    (OLD.replace("Mixed line, both kinds.", "Mixed line, reworded."), 0),
    (OLD.replace("Domain rule stays.", "Domain rule moved."), 1),
    (OLD.replace("Domain rule stays.", "One.")
        .replace("Another domain rule.", "Two."), 2),
])
def test_each_reworded_domain_line_of_a_profile_is_one_problem(new, problems):
    found = reported(side({"x/rows": _record(OLD)}),
                     side({"x/rows": _record(new)}), ranges=RANGES)
    assert found.problems == problems


@pytest.mark.parametrize("ranges", [
    # a prompt that is not on both sides
    {"alpha": {"x/none": {"contract": [(5, 5)], "mixed": []}}},
    # ranges written for another file
    {"alpha": {"x/rows": {"contract": [(5, 99)], "mixed": []}}},
])
def test_ranges_that_cannot_be_held_to_the_prompt_are_a_problem(ranges):
    same = side({"x/rows": _record(OLD)})
    assert reported(same, same, ranges=RANGES).problems == 0
    assert reported(same, same, ranges=ranges).problems == 1


def test_without_a_ranges_file_the_domain_is_not_checked(monkeypatch):
    def checked(*args):
        raise AssertionError("the domain was checked")
    monkeypatch.setattr(rp, "_domain_section", checked)
    same = side({"x/rows": _record(OLD)})

    assert reported(same, same).problems == 0
    with pytest.raises(AssertionError):         # and with one, it is
        reported(same, same, ranges={})


# ---------------------------------------------------------------------------
# The command: what it refuses, what it writes, the code it ends with
# ---------------------------------------------------------------------------

@pytest.fixture
def tool(monkeypatch, tmp_path):
    """The command with its reading replaced. The repository is an empty
    folder, the ref stands for a made-up commit and the two sides are what a
    test hands over, so that what `run` itself decides can be seen."""
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    same = side({"x/rows": rec(ROWS)})
    box = SimpleNamespace(root=root, out=tmp_path / "out", read=[],
                          before=same, after=same)

    def read_sides(root_, sha, profiles, scratch):
        box.read.append(list(profiles))
        sides = {}
        for name in profiles:
            sides[("before", name)] = box.before
            sides[("after", name)] = box.after
        return HEAD, False, sides

    def run(*more, profiles=("alpha",), out=box.out):
        argv = ["--before", "HEAD", "--repo", str(root), *more]
        for name in profiles:
            argv += ["--profile", name]
        if out is not None:
            argv += ["--out", str(out)]
        return rp.main(argv)

    monkeypatch.setattr(rp, "repo_root", lambda path: root)
    monkeypatch.setattr(rp, "resolve_ref", lambda root_, ref: SHA)
    monkeypatch.setattr(rp, "read_sides", read_sides)
    box.run = run
    return box


def test_a_run_writes_what_it_rendered_and_ends_with_zero(tool, capsys):
    assert tool.run() == 0

    assert "summary.md" in files_under(tool.out)
    assert "alpha/x/rows.after.txt" in files_under(tool.out)
    assert str(tool.out) in capsys.readouterr().out
    assert files_under(tool.root) == []


def test_a_profile_asked_for_twice_is_rendered_once(tool):
    assert tool.run(profiles=("alpha", "alpha", "beta")) == 0
    assert tool.read == [["alpha", "beta"]]


def test_a_problem_ends_the_run_with_one_and_the_rest_is_written(tool):
    tool.after = side({"x/rows": rec(ROWS), "x/bad": REFUSED})

    assert tool.run() == 1

    written = files_under(tool.out)
    assert "alpha/x/rows.after.txt" in written
    assert "alpha/x/bad.after.txt" not in written
    assert "summary.md" in written


def test_a_side_that_could_not_be_read_ends_the_run_with_one(tool):
    tool.after = FAILED
    assert tool.run() == 1
    assert files_under(tool.out) == ["summary.md"]


def test_a_block_with_no_text_for_it_ends_the_run_with_one_only_when_asked_for(
        tool):
    tool.after = side({"x/rows": rec(ROWS, composition=composed(["sandbox"]))})
    assert tool.run(out=tool.out / "plain") == 0
    assert tool.run("--what-if", out=tool.out / "asked") == 1


def test_a_reworded_domain_line_ends_the_run_with_one(tool, tmp_path):
    ranges = tmp_path / "ranges.json"
    ranges.write_text(json.dumps({"alpha": {"x/rows": {"contract": [[7, 7]]}}}),
                      encoding="utf-8")
    tool.before = side({"x/rows": _record(OLD)})

    tool.after = side({"x/rows": _record(
        OLD.replace("Contract sentence.", "Other wording."))})
    assert tool.run("--check-domain", str(ranges),
                    out=tool.out / "inside") == 0

    tool.after = side({"x/rows": _record(
        OLD.replace("Domain rule stays.", "Domain rule moved."))})
    assert tool.run("--check-domain", str(ranges),
                    out=tool.out / "outside") == 1
    assert tool.run(out=tool.out / "unchecked") == 0


def test_a_profile_on_neither_side_ends_the_run_with_two_and_writes_nothing(
        tool):
    tool.before = tool.after = MISSING
    assert tool.run() == 2
    assert not tool.out.exists()


@pytest.mark.parametrize("name", ["../alpha", "a/b", "a\\b", ".hidden", ""])
def test_a_profile_is_a_name_and_not_a_path(tool, name):
    assert tool.run(profiles=(name,)) == 2
    assert tool.read == [] and not tool.out.exists()


def test_ranges_for_a_profile_nobody_asked_for_are_refused(tool, tmp_path):
    ranges = tmp_path / "ranges.json"
    ranges.write_text(json.dumps({"beta": {"x/rows": {"contract": [[1, 1]]}}}),
                      encoding="utf-8")

    assert tool.run("--check-domain", str(ranges)) == 2
    assert tool.read == [] and not tool.out.exists()
    assert tool.run("--check-domain", str(ranges),
                    profiles=("alpha", "beta")) == 0        # asked for, it holds


@pytest.mark.parametrize("where", [
    "review",                               # a folder inside
    "review/deeper/still",
    ".",                                    # the repository itself
    "../repo/review",                       # outside by its name, inside by its path
    "../elsewhere/../repo/review",          # through a folder beside it
])
def test_an_output_folder_inside_the_repository_is_refused(tool, where):
    """Compared as written, the last two are outside. Compared as the tool
    would write to them, they are not."""
    assert tool.run(out=tool.root / where) == 2
    assert tool.read == []
    assert files_under(tool.root) == []


@pytest.mark.parametrize("start, where", [
    ("repo", "review"),                     # the usual slip: a name, from inside
    ("repo", "./review/deeper"),
    ("repo", "../repo/review"),
    ("beside", "repo/review"),
])
def test_a_relative_output_folder_that_lies_inside_the_repository_is_refused(
        tool, monkeypatch, start, where):
    """The folder is named relative to where the tool is started and does not
    exist yet, so the check is made on the path as the tool would write to
    it."""
    monkeypatch.chdir(tool.root if start == "repo" else tool.root.parent)

    assert tool.run(out=where) == 2
    assert tool.read == []
    assert files_under(tool.root) == []


def test_the_same_relative_name_beside_the_repository_is_written(tool,
                                                               monkeypatch):
    """The refusals above are about the place and not about the name."""
    monkeypatch.chdir(tool.root.parent)

    assert tool.run(out="review") == 0
    assert "summary.md" in files_under(tool.root.parent / "review")
    assert files_under(tool.root) == []


def test_a_default_folder_that_lies_inside_the_repository_is_refused_too(
        tool, monkeypatch):
    """Where the default lies is the system's to say. The check is on the
    place it ends up in, whatever named it."""
    monkeypatch.setattr(rp.tempfile, "gettempdir",
                        lambda: str(tool.root / "tmp"))
    assert tool.run(out=None) == 2
    assert tool.read == [] and files_under(tool.root) == []


def test_the_default_folder_lies_in_the_temporary_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: str(tmp_path))
    chosen = rp.default_out()
    assert chosen.parent == tmp_path / rp.OUT_NAME and chosen.name


def test_a_folder_that_holds_files_is_refused_and_an_empty_one_is_not(tool):
    """Files of an earlier run would sit beside this one's and read as its
    own."""
    tool.out.mkdir()
    assert tool.run() == 0                      # empty: written into

    assert tool.run() == 2                      # now it holds that run
    assert tool.read == [["alpha"]]


def test_a_profile_is_required():
    with pytest.raises(SystemExit) as raised:
        rp.main(["--before", "HEAD"])
    assert raised.value.code == 2


def test_the_summary_names_both_commits_and_whether_the_working_tree_differs():
    args = SimpleNamespace(before="main")
    clean = rp._head_lines(args, SHA, HEAD, False, ["alpha"], "now")
    dirty = rp._head_lines(args, SHA, HEAD, True, ["alpha"], "now")

    assert clean != dirty
    for lines in (clean, dirty):
        text = "\n".join(lines)
        assert SHA[:12] in text and HEAD[:12] in text and "main" in text


# ---------------------------------------------------------------------------
# git and the archive: what is refused before anything is unpacked
# ---------------------------------------------------------------------------

def _git_that(monkeypatch, returncode=0, stdout=b"", missing=False):
    def run(command, **kwargs):
        if missing:
            raise FileNotFoundError(command[0])
        return SimpleNamespace(returncode=returncode, stdout=stdout,
                               stderr=b"fatal: it said why")
    monkeypatch.setattr(rp.subprocess, "run", run)


def test_a_git_that_fails_or_is_not_there_is_a_refusal(monkeypatch, tmp_path):
    _git_that(monkeypatch, stdout=str(tmp_path).encode() + b"\n")
    assert rp.repo_root(tmp_path) == tmp_path.resolve()

    _git_that(monkeypatch, returncode=128)
    with pytest.raises(rp.Refused):
        rp.repo_root(tmp_path)
    _git_that(monkeypatch, missing=True)
    with pytest.raises(rp.Refused):
        rp.repo_root(tmp_path)


def test_a_folder_that_is_no_repository_ends_the_run_with_two(monkeypatch,
                                                              tmp_path):
    _git_that(monkeypatch, returncode=128)
    out = tmp_path / "out"
    assert rp.main(["--profile", "alpha", "--before", "HEAD",
                    "--repo", str(tmp_path), "--out", str(out)]) == 2
    assert not out.exists()


def test_a_ref_that_starts_like_an_option_is_refused_before_git_is_asked(
        monkeypatch, tmp_path):
    def asked(*args, **kwargs):
        raise AssertionError("git was asked")
    monkeypatch.setattr(rp, "_git", asked)
    with pytest.raises(rp.Refused):
        rp.resolve_ref(tmp_path, "-oops")


def _archive(member: tarfile.TarInfo, data: bytes = b"") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        member.size = len(data)
        tar.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


def _link() -> tarfile.TarInfo:
    member = tarfile.TarInfo("docpipe/link")
    member.type = tarfile.SYMTYPE
    member.linkname = "elsewhere"
    return member


LEAVING = {
    # a member that names a parent folder would be written outside the tree
    "a parent folder": lambda: _archive(tarfile.TarInfo("../escaped.txt"), b"x"),
    # a link would be followed outside it
    "a link": lambda: _archive(_link()),
}


@pytest.mark.parametrize("what", sorted(LEAVING))
def test_an_archive_that_would_leave_its_folder_is_refused_and_nothing_is_unpacked(
        tmp_path, monkeypatch, what):
    data = LEAVING[what]()
    monkeypatch.setattr(rp, "_git", lambda *args, **kwargs: data)

    with pytest.raises(rp.Refused):
        rp.extract_tree(tmp_path, "abc", tmp_path / "tree")

    assert files_under(tmp_path) == [] and not (tmp_path / "tree").exists()


# ---------------------------------------------------------------------------
# The other end: the real loader and the real runner, read in this process
# ---------------------------------------------------------------------------

@pytest.fixture
def real(monkeypatch):
    """`probe` on this tree. It puts the tree in front of the import path and
    the runner reads the profile from the environment; both are undone."""
    monkeypatch.setattr(sys, "path", list(sys.path))

    def probe(name: str) -> dict:
        monkeypatch.setenv("DOCPIPE_PROFILE", name)
        return rp.probe(ROOT, name)
    return probe


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_the_real_code_gives_the_tool_what_it_reads_by_name(real, name):
    """The tool reads a loader and a runner by the names of their functions
    and attributes. A name that moved would show here: as a prompt that is not
    read, as numbers by a rule from before, or as no composition at all."""
    from docpipe.extraction import runner

    found = real(name)

    assert found["state"] == "ok"
    assert found["lineage"][0] == name and len(found["lineage"]) > 1
    assert not {pid: record["error"] for pid, record
                in found["prompts"].items() if "error" in record}
    assert len(found["prompts"]) > 25
    taken = found["numbers"]
    assert taken["configured"] and "error" not in taken, taken
    assert taken["rule"] == "sent"
    assert taken["window_tokens"] == max(
        taken["budgets"][pid] for pid in runner.sent_prompt_ids(taken["framed"]))
    put_together = {pid: record["composition"] for pid, record
                    in found["prompts"].items() if record["composition"]}
    assert "extraction/rows" in put_together
    for pid, composition in put_together.items():
        # what --what-if asks a loader for
        assert set(composition["omitted"]) <= set(composition["what_if"]), pid


def test_a_real_profile_without_an_extraction_spec_is_read_without_numbers(real):
    found = real("default")
    assert found["state"] == "ok" and found["numbers"] == {"configured": False}
    assert reported(found, found).problems == 0


def test_a_profile_the_tree_does_not_have_is_missing_and_not_a_crash(real):
    found = real("no-such-profile")
    assert found["state"] == "missing" and found["prompts"] == {}


def test_a_tree_the_code_was_not_imported_from_is_not_read(real, tmp_path):
    """The text would be this tree's and be reported as that one's."""
    with pytest.raises(RuntimeError):
        rp.probe(tmp_path, "kwp")


def test_a_real_prompt_the_loader_refuses_is_a_finding_and_the_others_are_read(
        real, monkeypatch):
    from docpipe import prompts
    whole = real("kwp")
    refused = next(pid for pid in sorted(whole["prompts"])
                   if not pid.startswith("extraction/"))
    load = prompts.load

    def refusing(prompt_id, *args, **kwargs):
        if prompt_id == refused:
            raise ValueError("the loader refuses this prompt")
        return load(prompt_id, *args, **kwargs)
    monkeypatch.setattr(prompts, "load", refusing)

    found = real("kwp")

    assert [pid for pid, record in found["prompts"].items()
            if "error" in record] == [refused]
    assert reported(whole, found).status[refused] == rp.ERROR


def test_a_prompt_comes_from_the_nearest_profile_that_has_it(tmp_path):
    child = SimpleNamespace(name="child", prompts_dir=tmp_path / "child")
    parent = SimpleNamespace(name="parent", prompts_dir=tmp_path / "parent")

    def at(folder: Path):
        return SimpleNamespace(text="T", sha256="s", meta={"max_tokens": 5},
                               path=folder / "x" / "p.md")

    owners = [child, parent]
    assert rp._describe(at(child.prompts_dir), owners)["owner"] == "child"
    assert rp._describe(at(parent.prompts_dir), owners)["owner"] == "parent"
    assert rp._describe(at(tmp_path / "other"), owners)["owner"] is None


# ---------------------------------------------------------------------------
# The pieces
# ---------------------------------------------------------------------------

def test_a_table_cell_cannot_break_the_table():
    head, _rule, row = rp._table(["a", "b"], [["x | y\nz", "w"]])
    cut = re.compile(r"(?<!\\)\|")
    assert "\n" not in row
    assert len(cut.split(row)) == len(cut.split(head))


def test_a_value_that_moved_shows_both_ends_and_one_that_did_not_shows_once():
    moved = rp.pair(6, 3)
    assert "6" in moved and "3" in moved
    assert rp.pair(6, 6).count("6") == 1
    assert "3" in rp.pair(None, 3) and "None" not in rp.pair(None, 3)
    assert rp.pair(None, None) and "None" not in rp.pair(None, None)
