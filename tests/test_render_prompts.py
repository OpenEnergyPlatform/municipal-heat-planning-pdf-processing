"""The tool that shows what a change does to the prompts of a profile.

Its promise, as one sentence. For every prompt of each profile named, the tool
writes the text the code of the 'before' ref and the code of the working tree
would each send, read by each tree's own loader, AND the sentences that differ
between them, AND the numbers a run takes from each side's prompts by that
side's own rule, AND it writes nothing into the repository, AND it refuses an
output folder inside the repository, AND what an option has nothing to show for
yet it says so and does not fail, AND a domain line outside the contract ranges
that is not in the new text is named and fails the run.

Every AND has its tests below, and each has a case built to break it: a loader
that differs between the two trees, a sentence that is edited, a rule that
differs between the two runners, a file written beside the code, a folder
inside the repository, a loader that offers an omission and no text for it, a
domain line that was reworded.

The trees are small ones written here, so that these tests do not move with the
prompts of the profiles, plus two runs on a copy of the real code. No model, no
GPU, no data folder.
"""
import difflib
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import render_prompts as rp  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git is not installed")


# ---------------------------------------------------------------------------
# A tree small enough to read: what the tool needs of a loader and a runner
# ---------------------------------------------------------------------------

PROFILE_PY = '''\
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Profile:
    def __init__(self, name, extends=None):
        self.name, self.extends = name, extends

    def lineage(self):
        out = [self]
        while out[-1].extends:
            out.append(load_profile(out[-1].extends))
        return out

    @property
    def prompts_dir(self):
        return ROOT / "profiles" / self.name / "prompts"

    def component(self, module, attr):
        spec = ROOT / "profiles" / self.name / "spec.json"
        if (module, attr) == ("extraction", "SPEC_PATH") and spec.is_file():
            return spec
        return None


def load_profile(name):
    home = ROOT / "profiles" / name
    if not (home / "extends.txt").is_file():
        raise LookupError("unknown profile %r" % name)
    extends = (home / "extends.txt").read_text().strip() or None
    return Profile(name, extends)
'''

LOADER_PY = '''\
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

SHOUT = SHOUT_VALUE
COMPOSE = COMPOSE_VALUE


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    meta: dict
    sha256: str
    path: Path
    composition: object = None


def load(prompt_id, profile=None, use_ambient=True):
    for owner in profile.lineage():
        path = owner.prompts_dir / (prompt_id + ".md")
        if path.is_file():
            break
    else:
        raise FileNotFoundError(prompt_id)
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    front = re.match(r"---\\n(.*?)\\n---\\n", raw, re.S)
    if front:
        for line in front.group(1).splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = float(value) if "." in value else int(value)
        body = raw[front.end():]
    if "REFUSED" in body:
        raise ValueError("the loader refuses this prompt")
    text = body.upper() if SHOUT else body
    composition = None
    if COMPOSE and prompt_id == "extraction/rows":
        composition = {"template": "rows", "overrides": ["value"],
                       "omitted": ["sandbox"]}
        if COMPOSE == "full":
            composition["what_if"] = {"sandbox": text + "Sandbox rule.\\n"}
    return Prompt(prompt_id, text, meta,
                  hashlib.sha256(raw.encode()).hexdigest(), path, composition)
'''

RUNNER_HEAD = '''\
import os
from types import SimpleNamespace

from docpipe import prompts
from docpipe.profile import load_profile

BATCH_SOURCES = int(os.environ.get("EXTRACT_BATCH_SOURCES", "6"))
BATCH_CHARS = 14000
MAX_SOURCE_CHARS = 16000
ATTACH_IMAGES = True
PRIOR_MAX = 24
PRIOR_TOKENS = 110
QUERIES_PROMPT_ID = "extraction/queries"
ROWS_PROMPT_ID = "extraction/rows"
FIELD_PROMPT_ID = "extraction/field"
REVIEW_PROMPT_ID = "extraction/review"


def load_spec(path):
    return SimpleNamespace(parameters=[])


def context_budget(prompt, spec=None):
    return (len(prompt.text.split()) * 3 + BATCH_SOURCES * 100
            + int(prompt.meta.get("max_tokens", 100)))


def fit_batch_sources(prompt, spec, wanted=BATCH_SOURCES):
    return max(1, min(wanted, int(prompt.meta.get("max_tokens", 100)) // 1000))
'''

AMBIENT = '''

def _ambient():
    return load_profile(os.environ["DOCPIPE_PROFILE"])
'''

# The rule before: one prompt is counted for the window, and the command that
# prints the window is the only place that says which. The tool is not told
# its id.
RUNNER_SINGLE = RUNNER_HEAD + AMBIENT + '''
SIZING_PROMPT_ID = "extraction/sizing"
PROMPT_IDS = (SIZING_PROMPT_ID, ROWS_PROMPT_ID, FIELD_PROMPT_ID)


def _sizing():
    return context_budget(prompts.load(SIZING_PROMPT_ID, _ambient()),
                          load_spec(None))


def main(argv):
    if argv[:1] == ["--print-context-budget"]:
        print(_sizing())
        return 0
    return 2
'''

# The rule after: the window is the largest budget of what a run sends.
RUNNER_SENT = RUNNER_HEAD + AMBIENT + '''
PROMPT_IDS = (ROWS_PROMPT_ID, FIELD_PROMPT_ID)


def request_budget(spec, framed):
    return max(context_budget(prompts.load(pid, _ambient()), spec)
               for pid in PROMPT_IDS)


def batch_sources_for(spec):
    return fit_batch_sources(prompts.load(ROWS_PROMPT_ID, _ambient()), spec)
'''

FIELDS_PY = '''\
def frame_slots(spec, frame):
    return list(frame)
'''

ROWS_BODY = ("Find the numbers. Quote the passage. Never invent a value.\n"
             "\n"
             "1. value: the number as written. Keep it.\n"
             "2. quote: the whole row. Keep it too.\n")
FIELD_BODY = "Answer one field. Be brief.\n"
SIZING_BODY = "One prompt sizes the window. " * 40 + "\n"
REFINE_BODY = "Refine the text.\n"


def front(**meta) -> str:
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in meta.items()) + "---\n"


ROWS = front(temperature=0, max_tokens=2000) + ROWS_BODY
FIELD = front(temperature=0, max_tokens=1000) + FIELD_BODY
SIZING = front(temperature=0.1, max_tokens=3000) + SIZING_BODY

# Where a prompt of the small tree lies, for the tests that edit one.
PROMPTS = "profiles/alpha/prompts"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def build_tree(root: Path, *, shout=False, compose=None, runner="single",
               profiles=("alpha",)) -> None:
    """Write (or overwrite) the small tree: a loader, a runner and prompts."""
    write(root / "docpipe" / "__init__.py", "")
    write(root / "docpipe" / "profile.py", PROFILE_PY)
    write(root / "docpipe" / "prompts.py",
          LOADER_PY.replace("SHOUT_VALUE", repr(shout))
                   .replace("COMPOSE_VALUE", repr(compose)))
    write(root / "docpipe" / "extraction" / "__init__.py", "")
    write(root / "docpipe" / "extraction" / "fields.py", FIELDS_PY)
    write(root / "docpipe" / "extraction" / "runner.py",
          RUNNER_SINGLE if runner == "single" else RUNNER_SENT)
    for name in profiles:
        home = root / "profiles" / name
        write(home / "extends.txt", "")
        write(home / "spec.json", "{}")
        for pid, text in {
                "extraction/rows": ROWS, "extraction/field": FIELD,
                "extraction/sizing": SIZING,
                "extraction/review": front(max_tokens=100) + "Review it.\n",
                "refinement/refine": REFINE_BODY}.items():
            write(home / "prompts" / f"{pid}.md", text)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
         "-C", str(repo), *args],
        check=True, capture_output=True)
    return done.stdout.decode("utf-8", "replace")


def commit(repo: Path, message: str = "state") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    """A repository with the small tree committed."""
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    build_tree(path)
    commit(path)
    return path


@pytest.fixture
def out(tmp_path):
    return tmp_path / "out"


def render(repo, out, *args, profiles=("alpha",), before="HEAD") -> int:
    argv = []
    for name in profiles:
        argv += ["--profile", name]
    # `=`: a ref that starts with '-' must reach the tool, not argparse
    argv += [f"--before={before}", "--repo", str(repo), "--out", str(out),
             *args]
    return rp.main(argv)


def summary(out: Path) -> str:
    return (out / "summary.md").read_text(encoding="utf-8")


def section(text: str, name: str) -> str:
    """The `## name` part of the summary."""
    parts = text.split("\n## ")
    return next("## " + p for p in parts if p.startswith(f"{name}\n"))


def all_rows(text: str, first: str) -> list:
    """The cells of every table row whose first cell is *first*."""
    found = []
    for line in text.splitlines():
        row = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if line.startswith("|") and row and row[0] == first:
            found.append(row)
    return found


def cells(text: str, first: str) -> list:
    rows = all_rows(text, first)
    assert rows, f"no table row starting with {first!r} in:\n{text}"
    return rows[0]


# A prompt shows in three tables of a profile's section, told apart by width.
def prompt_row(text: str, pid: str) -> list:
    return next(r for r in all_rows(text, f"`{pid}`") if len(r) == 9)


def budget_row(text: str, pid: str) -> list:
    return next(r for r in all_rows(text, f"`{pid}`") if len(r) == 3)


def status(out: Path, pid: str, name: str = "alpha") -> str:
    return prompt_row(section(summary(out), name), pid)[2]


def snapshot(repo: Path) -> dict:
    """Every file and folder of the working tree outside .git, with what a
    write would change."""
    found = {}
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo)
        if ".git" in rel.parts:
            continue
        stat = path.stat()
        found[rel.as_posix()] = ((stat.st_size, stat.st_mtime_ns)
                                 if path.is_file() else "dir")
    return found


def lines_of(path: Path) -> list:
    return path.read_text(encoding="utf-8").splitlines()


def changed_lines(diff: list) -> list:
    """The lines of a diff that say something moved, without its header."""
    return [line for line in diff[2:] if line[:1] in "+-"]


# ---------------------------------------------------------------------------
# AND the text each tree's own loader would send
# ---------------------------------------------------------------------------

def test_before_and_after_are_each_read_by_their_own_loader(repo, out):
    """The committed loader upper-cases every prompt, the working tree's does
    not, and no prompt file moved. A tool that read both sides with one loader
    would show two equal texts."""
    build_tree(repo, shout=True)
    commit(repo)
    build_tree(repo, shout=False)

    assert render(repo, out) == 0

    base = out / "alpha" / "extraction"
    assert (base / "rows.before.txt").read_text(encoding="utf-8") \
        == ROWS_BODY.upper()
    assert (base / "rows.after.txt").read_text(encoding="utf-8") == ROWS_BODY
    assert status(out, "extraction/rows") == "changed"


def test_after_is_the_working_tree_with_edits_not_yet_committed(repo, out):
    """And 'before' is the ref asked for, which need not be HEAD. A tool that
    read HEAD for 'after' would not see the edit."""
    edited = ROWS.replace("Never invent a value.", "Never guess a value.")
    write(repo / PROMPTS / "extraction/rows.md", edited)
    commit(repo, "second state")
    write(repo / PROMPTS / "extraction/rows.md",
          edited.replace("Keep it too.", "Keep it as well."))

    assert render(repo, out, before="HEAD~1") == 0

    base = out / "alpha" / "extraction"
    assert (base / "rows.before.txt").read_text(encoding="utf-8") == ROWS_BODY
    after = (base / "rows.after.txt").read_text(encoding="utf-8")
    assert "Never guess a value." in after and "Keep it as well." in after
    assert "uncommitted changes under docpipe/ or profiles/" in summary(out)
    assert "no uncommitted" not in summary(out)


def test_the_console_says_what_was_found_and_where_it_was_written(repo, out,
                                                                  capsys):
    write(repo / PROMPTS / "extraction/rows.md",
          ROWS.replace("Keep it too.", "Keep it as well."))

    assert render(repo, out, profiles=("alpha", "alpha")) == 0   # asked twice

    said = capsys.readouterr().out
    assert said.count("alpha: ") == 1                           # rendered once
    assert "alpha: 5 prompt(s): 0 error, 1 changed, 0 added, 0 removed, " \
           "4 identical" in said
    assert f"written to {out}" in said


def test_the_summary_names_the_ref_and_the_commit_it_stands_for(repo, out):
    assert render(repo, out) == 0

    head = git(repo, "rev-parse", "HEAD").strip()
    text = summary(out)
    assert f"`HEAD` (`{head[:12]}`)" in text
    assert "no uncommitted changes under docpipe/ or profiles/" in text


def test_a_text_is_written_as_the_loader_gave_it(repo, out):
    """Byte for byte: the trailing space and the final newline stay, the
    umlaut is UTF-8, and a CRLF file of the working tree gives the text its LF
    twin in the commit gives (the loader reads text, not bytes)."""
    body = "Line one, with an umlaut ä.  \nLine two…\n"
    write(repo / PROMPTS / "refinement/refine.md", body)
    commit(repo)
    write(repo / PROMPTS / "refinement/refine.md",
          body.replace("\n", "\r\n"))

    assert render(repo, out) == 0

    base = out / "alpha" / "refinement"
    assert (base / "refine.before.txt").read_bytes() == body.encode("utf-8")
    assert (base / "refine.after.txt").read_bytes() == body.encode("utf-8")
    assert status(out, "refinement/refine") == "identical"


def test_a_prompt_is_identical_changed_added_or_removed(repo, out):
    """The three steps of a removal in one tree: the runner no longer names
    the prompt that sized the window, so its file may go."""
    build_tree(repo, runner="sent")
    write(repo / PROMPTS / "extraction/rows.md",
          ROWS.replace("Keep it too.", "Keep it as well."))
    write(repo / PROMPTS / "refinement/new.md", "A new one.\n")
    (repo / PROMPTS / "extraction/sizing.md").unlink()

    assert render(repo, out) == 0

    states = {pid: status(out, pid) for pid in
              ("extraction/rows", "extraction/field", "refinement/new",
               "extraction/sizing")}
    assert states == {"extraction/rows": "changed",
                      "extraction/field": "identical",
                      "refinement/new": "added",
                      "extraction/sizing": "removed"}
    base = out / "alpha"
    assert (base / "refinement/new.after.txt").is_file()
    assert not (base / "refinement/new.before.txt").exists()
    assert (base / "extraction/sizing.before.txt").is_file()
    assert not (base / "extraction/sizing.after.txt").exists()
    # What changed is named before what did not
    text = section(summary(out), "alpha")
    ids = [line.split("|")[1].strip() for line in text.splitlines()
           if line.startswith("| `") and len(line.split("|")) == 11]
    assert ids.index("`extraction/rows`") < ids.index("`extraction/field`")


def test_a_change_of_parameters_alone_is_a_change(repo, out):
    """The system message is the same, the request is not: max_tokens and the
    temperature are part of what a prompt is. A tool that compared the text
    would call it identical."""
    write(repo / PROMPTS / "extraction/field.md",
          FIELD.replace("max_tokens: 1000", "max_tokens: 900"))

    assert render(repo, out) == 0

    assert status(out, "extraction/field") == "changed"
    assert prompt_row(section(summary(out), "alpha"),
                      "extraction/field")[5] == "1000 -> 900"
    diff = lines_of(out / "alpha/extraction/field.sentences.diff")
    assert diff[2:] == ["# max_tokens: 1000 -> 900"]


def test_a_file_written_differently_is_a_change_for_its_sha_alone(repo, out):
    """The same text and parameters, another order in the front matter: the
    sha256 is what a stamp records, so it is said."""
    write(repo / PROMPTS / "extraction/field.md",
          front(max_tokens=1000, temperature=0) + FIELD_BODY)

    assert render(repo, out) == 0

    assert status(out, "extraction/field") == "changed"
    diff = lines_of(out / "alpha/extraction/field.sentences.diff")
    assert len(diff) == 3 and "the sha256 differs" in diff[2]


def test_trailing_whitespace_is_a_change_and_shows_as_one(repo, out):
    """The model reads the space. It is a changed sentence in the diff."""
    write(repo / PROMPTS / "extraction/field.md",
          FIELD.replace("Be brief.", "Be brief. "))

    assert render(repo, out) == 0

    assert status(out, "extraction/field") == "changed"
    diff = lines_of(out / "alpha/extraction/field.sentences.diff")
    assert changed_lines(diff) == ["-Be brief.", "+Be brief. "]


def test_whitespace_between_sentences_is_a_change_the_diff_names_in_words(
        repo, out):
    """No sentence differs, the text does: an empty diff would read as
    'nothing changed'."""
    write(repo / PROMPTS / "extraction/field.md",
          FIELD.replace("field. Be", "field.  Be"))

    assert render(repo, out) == 0

    assert status(out, "extraction/field") == "changed"
    diff = lines_of(out / "alpha/extraction/field.sentences.diff")
    assert diff[2:] == ["# the sentences are the same; the texts differ in "
                        "whitespace only"]


# ---------------------------------------------------------------------------
# AND the sentences that differ
# ---------------------------------------------------------------------------

def test_each_changed_sentence_is_one_line_of_the_diff(repo, out):
    """One sentence of three is edited in a paragraph that is one line of the
    file. A diff by lines would show the whole paragraph twice."""
    write(repo / PROMPTS / "extraction/rows.md",
          ROWS.replace("Quote the passage.", "Quote the whole passage."))

    assert render(repo, out) == 0

    diff = lines_of(out / "alpha/extraction/rows.sentences.diff")
    assert changed_lines(diff) == ["-Quote the passage.",
                                   "+Quote the whole passage."]
    assert " Find the numbers." in diff       # context, not change
    assert " Never invent a value." in diff


def test_a_file_that_was_not_edited_has_a_diff_that_says_so(repo, out):
    assert render(repo, out) == 0

    diff = lines_of(out / "alpha/extraction/rows.sentences.diff")
    assert diff[2:] == ["# the same on both sides"]


def test_a_removed_or_an_added_prompt_is_one_block_of_sentences(repo, out):
    build_tree(repo, runner="sent")
    write(repo / PROMPTS / "refinement/new.md", "One. Two.\n")
    (repo / PROMPTS / "refinement/refine.md").unlink()

    assert render(repo, out) == 0

    assert changed_lines(lines_of(
        out / "alpha/refinement/new.sentences.diff")) == ["+One.", "+Two."]
    assert changed_lines(lines_of(
        out / "alpha/refinement/refine.sentences.diff")) == [
            "-Refine the text."]


# ---------------------------------------------------------------------------
# AND the numbers by each side's own rule
# ---------------------------------------------------------------------------

def _ctx(body: str, max_tokens: int, sources: int = 6) -> int:
    """The small runner's budget, counted here and not by the tool."""
    return len(body.split()) * 3 + sources * 100 + max_tokens


def test_each_side_takes_its_numbers_by_its_own_rule(repo, out):
    """Before, the window is one prompt's budget and the sources follow its
    max_tokens; after, the largest budget of what is sent and the rows
    prompt's max_tokens. The two rules give different numbers here. A tool
    that used the working tree's rule for both would show equal columns."""
    build_tree(repo, runner="sent")

    assert render(repo, out) == 0

    text = section(summary(out), "alpha")
    assert cells(text, "window (tokens)")[1:] == [
        str(_ctx(SIZING_BODY, 3000)),
        str(max(_ctx(ROWS_BODY, 2000), _ctx(FIELD_BODY, 1000)))]
    assert cells(text, "sources per request (sources)")[1:] == ["3", "2"]
    rule = cells(text, "rule")
    assert "one prompt for both" in rule[1]
    assert "the prompts a run sends" in rule[2]
    # the budget of every prompt a request can carry, side by side
    assert budget_row(text, "extraction/rows")[1:] == [
        str(_ctx(ROWS_BODY, 2000))] * 2
    assert budget_row(text, "extraction/sizing")[1:] == [
        str(_ctx(SIZING_BODY, 3000)), "-"]


def test_the_prompt_an_older_tree_counts_its_window_from_is_the_one_its_command_names(
        repo, out):
    """The tool is not told which prompt that tree sizes the window from, and
    reads it off what the tree's own command does. Built to fail: the same tree
    with the command counting from the field prompt, whose numbers are not the
    ones of the first prompt of the tree's list, which is where a tool that
    guessed would look."""
    write(repo / "docpipe/extraction/runner.py",
          RUNNER_SINGLE.replace("prompts.load(SIZING_PROMPT_ID",
                                "prompts.load(FIELD_PROMPT_ID"))
    commit(repo)
    build_tree(repo, runner="sent")

    assert render(repo, out) == 0

    text = section(summary(out), "alpha")
    assert cells(text, "window (tokens)")[1] == str(_ctx(FIELD_BODY, 1000))
    assert cells(text, "window (tokens)")[1] != str(_ctx(SIZING_BODY, 3000))
    assert cells(text, "sources per request (sources)")[1] == "1"


# A window command that does not print the budget of one prompt, built on the
# command as the small tree writes it, and what the problem says of it.
WINDOW_COMMANDS = {
    "it counts every prompt": (
        "print(max(context_budget(prompts.load(p, _ambient()), "
        "load_spec(None)) for p in PROMPT_IDS))", "3 budget call(s)"),
    "it counts one and prints another number": (
        "_sizing(); print(7)", "1 budget call(s)"),
    "it prints a number it did not count": ("print(7)", "0 budget call(s)"),
    "it stops": ("raise SystemExit(3)", "exit 3"),
}


@pytest.mark.parametrize("what", sorted(WINDOW_COMMANDS))
def test_a_window_command_that_prints_no_one_prompts_budget_is_a_problem_not_a_guess(
        repo, out, capsys, what):
    new, said = WINDOW_COMMANDS[what]
    assert "print(_sizing())" in RUNNER_SINGLE, "built on the command as written"
    write(repo / "docpipe/extraction/runner.py",
          RUNNER_SINGLE.replace("print(_sizing())", new))
    commit(repo)
    build_tree(repo, runner="sent")

    assert render(repo, out) == 1

    text = summary(out)
    assert "is not a window counted from one prompt" in text
    assert said in text
    assert cells(section(text, "alpha"), "window (tokens)")[1] == "-"
    assert "1 problem(s)" in capsys.readouterr().err


def test_a_rule_the_runner_does_not_have_is_a_problem_not_a_guess(repo, out,
                                                                  capsys):
    """A runner with neither the request budget nor a command that prints its
    window has no rule the tool knows. It says so and the run fails."""
    write(repo / "docpipe/extraction/runner.py",
          RUNNER_HEAD + "\nPROMPT_IDS = (ROWS_PROMPT_ID,)\n")

    assert render(repo, out) == 1

    assert ("neither request_budget nor a command that prints its window"
            in summary(out))
    assert "1 problem(s)" in capsys.readouterr().err


def test_a_setting_the_runner_no_longer_has_is_a_problem_and_not_a_none(
        repo, out, capsys):
    """The table of settings names what the numbers rest on. A constant that
    was renamed would print as None and look like a value."""
    write(repo / "docpipe/extraction/runner.py",
          RUNNER_SINGLE.replace("PRIOR_TOKENS = 110\n", ""))

    assert render(repo, out) == 1

    text = summary(out)
    assert "- after: not computed, AttributeError" in text
    assert "PRIOR_TOKENS" in text and "None" not in text
    assert cells(section(text, "alpha"), "window (tokens)")[2] == "-"


def test_the_callers_settings_do_not_move_the_numbers(repo, out, monkeypatch):
    """EXTRACT_* of the shell the tool is started in are not read: the same
    two refs must give the same numbers on every machine."""
    monkeypatch.setenv("EXTRACT_BATCH_SOURCES", "2")

    assert render(repo, out) == 0

    text = section(summary(out), "alpha")
    assert "batch_sources 6" in text and "batch_sources 2" not in text
    assert cells(text, "sources per request (sources)")[1:] == ["3", "3"]


def test_the_environment_variable_would_have_moved_them(repo):
    """The case above can fail: the small runner does read the variable."""
    done = subprocess.run(
        [sys.executable, "-c",
         "import docpipe.extraction.runner as r; print(r.BATCH_SOURCES)"],
        cwd=repo, env={**os.environ, "EXTRACT_BATCH_SOURCES": "2",
                       "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True)
    assert done.stdout.strip() == "2"


def test_a_profile_without_a_spec_has_no_numbers_and_the_summary_says_so(
        repo, out):
    (repo / "profiles/alpha/spec.json").unlink()

    assert render(repo, out) == 0

    text = section(summary(out), "alpha")
    assert "- after: not computed, the profile configures no extraction " \
           "spec" in text
    assert cells(text, "window (tokens)")[2] == "-"


def test_a_profile_without_a_spec_on_both_sides_says_it_once(repo, out):
    (repo / "profiles/alpha/spec.json").unlink()
    commit(repo, "no spec")

    assert render(repo, out) == 0

    text = section(summary(out), "alpha")
    assert text.count("not computed, the profile configures no extraction "
                      "spec") == 1
    assert "- before and after: not computed" in text
    assert "window (tokens)" not in text


# ---------------------------------------------------------------------------
# AND nothing is written into the repository
# ---------------------------------------------------------------------------

@pytest.fixture
def bytecode_allowed(monkeypatch):
    """The caller's shell may already forbid bytecode. Then the tool's own
    guard would never be what keeps the repository clean, and a test could not
    tell."""
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)


def test_the_repository_is_as_it_was_after_a_run(repo, out, bytecode_allowed):
    build_tree(repo, runner="sent")             # an uncommitted change
    before = snapshot(repo)

    assert render(repo, out) == 0

    assert snapshot(repo) == before
    assert (out / "summary.md").is_file()


def test_the_check_can_see_a_stray_file(repo):
    """The case above can fail. Importing the tree the way a careless probe
    would writes bytecode into it, and the snapshot sees that."""
    before = snapshot(repo)
    env = {key: value for key, value in os.environ.items()
           if key not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
    subprocess.run([sys.executable, "-c", "import docpipe.extraction.runner"],
                   cwd=repo, env=env, check=True, capture_output=True)
    assert snapshot(repo) != before


def test_a_probe_has_a_home_of_its_own_for_everything_it_may_write(tmp_path):
    env = rp.probe_env(tmp_path, "alpha")
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["DOCPIPE_PROFILE"] == "alpha"
    assert env["DOCPIPE_CONFIG"] == "" and env["DOCPIPE_ENV_FILE"] == ""
    assert Path(env["DOCPIPE_USAGE_DB"]).parent == tmp_path
    assert Path(env["DOCPIPE_DATA_ROOT"]).parent == tmp_path


def test_a_probe_does_not_read_the_callers_extract_settings(tmp_path,
                                                            monkeypatch):
    monkeypatch.setenv("EXTRACT_BATCH_SOURCES", "2")
    monkeypatch.setenv("EXTRACT_ATTACH_IMAGES", "0")
    monkeypatch.setenv("LLM_MODEL", "kept")
    env = rp.probe_env(tmp_path, "alpha")
    assert not [key for key in env if key.startswith("EXTRACT_")]
    assert env["LLM_MODEL"] == "kept"


# ---------------------------------------------------------------------------
# AND an output folder inside the repository is refused
# ---------------------------------------------------------------------------

@pytest.fixture
def nothing_runs(monkeypatch):
    """A refusal must come before any work: no archive, no probe."""
    def fail(*args, **kwargs):
        raise AssertionError("work was started")
    monkeypatch.setattr(rp, "extract_tree", fail)
    monkeypatch.setattr(rp, "run_probe", fail)


@pytest.mark.parametrize("where", [
    "review",                               # a folder inside
    "review/deeper/still",
    ".",                                    # the repository itself
    "../repo/review",                       # outside by its name, inside by its path
])
def test_an_output_folder_inside_the_repository_is_refused(
        repo, where, nothing_runs, capsys):
    before = snapshot(repo)

    code = rp.main(["--profile", "alpha", "--before", "HEAD",
                    "--repo", str(repo), "--out", str(repo / where)])

    assert code == 2
    assert "inside the repository" in capsys.readouterr().err
    assert snapshot(repo) == before
    assert not (repo / "review").exists()


def test_a_path_that_reaches_the_repository_through_dots_is_refused(
        repo, tmp_path, nothing_runs, capsys):
    """It starts beside the repository and ends inside it. Compared as
    written it is outside; compared as resolved it is not."""
    sneaky = tmp_path / "elsewhere" / ".." / "repo" / "review"

    code = rp.main(["--profile", "alpha", "--before", "HEAD",
                    "--repo", str(repo), "--out", str(sneaky)])

    assert code == 2
    assert "inside the repository" in capsys.readouterr().err


@pytest.mark.parametrize("start, where", [
    ("repo", "review"),                     # the usual slip: a name, from inside
    ("repo", "./review/deeper"),
    ("repo", "../repo/review"),
    ("tmp", "repo/review"),                 # from the folder beside it
])
def test_a_relative_output_folder_that_lies_inside_the_repository_is_refused(
        repo, tmp_path, monkeypatch, start, where, nothing_runs, capsys):
    """The folder is named relative to where the tool is started and does not
    exist yet. A resolve that leaves such a path relative on the platform
    compares it with the repository as written and lets it through, so the
    check is made on the path as the tool would write to it."""
    monkeypatch.chdir(repo if start == "repo" else tmp_path)
    before = snapshot(repo)

    code = rp.main(["--profile", "alpha", "--before", "HEAD",
                    "--repo", str(repo), "--out", where])

    assert code == 2
    assert "inside the repository" in capsys.readouterr().err
    assert snapshot(repo) == before
    assert not (repo / "review").exists()


def test_a_relative_output_folder_outside_the_repository_is_accepted(
        repo, tmp_path, monkeypatch):
    """The case above is about the place: the same relative name, started from
    beside the repository, is outside it and is written."""
    monkeypatch.chdir(tmp_path)
    before = snapshot(repo)

    code = rp.main(["--profile", "alpha", "--before", "HEAD",
                    "--repo", str(repo), "--out", "review"])

    assert code == 0
    assert (tmp_path / "review" / "summary.md").is_file()
    assert snapshot(repo) == before


def test_an_output_folder_outside_the_repository_is_accepted(repo, out):
    """The refusals above are about the place and not about every folder."""
    assert render(repo, out) == 0
    assert (out / "summary.md").is_file()


def test_the_default_folder_is_in_the_temporary_folder_and_named_by_the_time(
        tmp_path, monkeypatch):
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: str(tmp_path))
    chosen = rp.default_out()
    assert chosen.parent == tmp_path / rp.OUT_NAME
    assert re.fullmatch(r"\d{8}T\d{6}Z", chosen.name)


def test_a_temporary_folder_inside_the_repository_is_refused_too(
        repo, monkeypatch, nothing_runs, capsys):
    """Where the default lies is the system's to say; the check is on the
    place it ends up in, whatever named it."""
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: str(repo / "tmp"))
    code = rp.main(["--profile", "alpha", "--before", "HEAD",
                    "--repo", str(repo)])
    assert code == 2
    assert "inside the repository" in capsys.readouterr().err


def test_a_folder_that_holds_files_is_refused(repo, out, nothing_runs, capsys):
    out.mkdir()
    (out / "left-over.txt").write_text("an earlier run", encoding="utf-8")

    assert render(repo, out) == 2

    assert "not an empty folder" in capsys.readouterr().err
    assert [p.name for p in out.iterdir()] == ["left-over.txt"]


def test_a_new_or_an_empty_folder_is_accepted(repo, out):
    out.mkdir()
    assert render(repo, out) == 0


# ---------------------------------------------------------------------------
# AND what an option has nothing to show for yet, it says
# ---------------------------------------------------------------------------

def test_what_if_and_overrides_say_so_where_nothing_is_composed(repo, out):
    assert render(repo, out, "--what-if") == 0

    text = summary(out)
    assert ("Nothing to show: no prompt of the after tree is composed from a "
            "template") in text
    assert "Nothing to show: no prompt of the after tree omits a block" in text


def test_overrides_and_omissions_are_listed_for_a_composed_prompt(repo, out):
    build_tree(repo, compose="full")

    assert render(repo, out) == 0

    text = section(summary(out), "alpha")
    assert all_rows(text, "`extraction/rows`")[-1] == [
        "`extraction/rows`", "rows", "value", "sandbox"]
    assert prompt_row(text, "extraction/rows")[-1] == "rows"
    assert prompt_row(text, "extraction/field")[-1] == "-"


def test_what_if_renders_an_omitted_block_back_in_and_shows_the_difference(
        repo, out):
    build_tree(repo, compose="full")

    assert render(repo, out, "--what-if") == 0

    base = out / "alpha/extraction"
    assert (base / "rows.what-if.sandbox.txt").read_text(
        encoding="utf-8") == ROWS_BODY + "Sandbox rule.\n"
    assert changed_lines(lines_of(
        base / "rows.what-if.sandbox.sentences.diff")) == ["+Sandbox rule."]
    assert "`extraction/rows`, block `sandbox`" in summary(out)


def test_an_omission_without_a_text_for_it_is_a_problem_not_silence(
        repo, out, capsys):
    """The loader reports a block left out and offers nothing to put back.
    Asking for the what-if and getting a clean exit would be a lie."""
    build_tree(repo, compose="bare")

    assert render(repo, out, "--what-if") == 1

    assert "gives no text for putting them back" in summary(out)
    assert "problem(s)" in capsys.readouterr().err


def test_without_what_if_an_omission_is_listed_and_not_asked_for(repo, out):
    build_tree(repo, compose="bare")

    assert render(repo, out) == 0

    assert not list(out.rglob("*.what-if.*"))
    assert "| `extraction/rows` | rows | value | sandbox |" in summary(out)


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
# A side that cannot be read is a failure, never an empty column
# ---------------------------------------------------------------------------

def test_a_side_whose_code_cannot_be_imported_fails_the_run(repo, out, capsys):
    write(repo / "docpipe/prompts.py", "def broken(:\n")

    assert render(repo, out) == 1

    text = summary(out)
    assert "The after side could not be read" in text
    assert "SyntaxError" in text
    assert "not rendered" in text
    assert "problem(s)" in capsys.readouterr().err


def test_a_prompt_the_loader_refuses_is_named_and_the_run_fails(repo, out):
    write(repo / PROMPTS / "refinement/refine.md", "This one is REFUSED.\n")

    assert render(repo, out) == 1

    text = summary(out)
    assert "refinement/refine (after): ValueError: the loader refuses" in text
    assert status(out, "refinement/refine") == "error"
    # the others were rendered all the same
    assert (out / "alpha/extraction/rows.after.txt").is_file()
    assert not (out / "alpha/refinement/refine.after.txt").exists()


def test_a_profile_new_since_the_ref_has_all_its_prompts_added(repo, out):
    build_tree(repo, profiles=("alpha", "beta"))

    assert render(repo, out, profiles=("alpha", "beta")) == 0

    text = section(summary(out), "beta")
    assert "The profile is not on the before side" in text
    assert prompt_row(text, "extraction/rows")[2] == "added"


def test_a_profile_on_neither_side_is_refused(repo, out, capsys):
    assert render(repo, out, profiles=("alpha", "gamma")) == 2
    assert "gamma" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("name", ["../alpha", "a/b", "a\\b", ".hidden", ""])
def test_a_profile_is_a_name_and_not_a_path(repo, out, name, capsys):
    assert render(repo, out, profiles=(name,)) == 2
    assert "profile's name" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("ref", ["no-such-ref", "-oops", "HEAD~40"])
def test_an_unknown_ref_is_refused_before_anything_is_written(repo, out, ref,
                                                              capsys):
    assert render(repo, out, before=ref) == 2
    assert re.search(r"is not a (ref|commit)", capsys.readouterr().err)
    assert not out.exists()


def test_a_profile_is_required():
    with pytest.raises(SystemExit) as raised:
        rp.main(["--before", "HEAD"])
    assert raised.value.code == 2


def test_a_folder_that_is_no_repository_is_refused(tmp_path, out, monkeypatch,
                                                   capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert rp.main(["--profile", "alpha", "--before", "HEAD",
                    "--repo", str(plain), "--out", str(out)]) == 2
    assert "render_prompts:" in capsys.readouterr().err
    assert not out.exists()


def test_an_archive_that_leaves_its_folder_is_refused(tmp_path, monkeypatch):
    """A member that names a parent folder would be written outside the
    temporary tree."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        member = tarfile.TarInfo("../escaped.txt")
        member.size = 1
        tar.addfile(member, io.BytesIO(b"x"))
    monkeypatch.setattr(rp, "_git", lambda *a, **k: buffer.getvalue())

    with pytest.raises(rp.Refused, match="leaves the folder"):
        rp.extract_tree(tmp_path, "abc", tmp_path / "tree")
    assert not (tmp_path / "escaped.txt").exists()


def test_an_archive_with_a_link_is_refused(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        member = tarfile.TarInfo("docpipe/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "elsewhere"
        tar.addfile(member)
    monkeypatch.setattr(rp, "_git", lambda *a, **k: buffer.getvalue())

    with pytest.raises(rp.Refused, match="link or a special file"):
        rp.extract_tree(tmp_path, "abc", tmp_path / "tree")


# ---------------------------------------------------------------------------
# AND a domain line outside the contract ranges is in the new text
# ---------------------------------------------------------------------------

def _record(text: str, front_lines: int = 4) -> dict:
    return {"text": text, "front_lines": front_lines, "meta": {},
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


OLD = ("Role line.\n"                     # physical 5
       "\n"                               # 6
       "Contract sentence.\n"             # 7
       "1. Domain rule stays.\n"          # 8
       "Mixed line, both kinds.\n"        # 9
       "2. Another domain rule.\n")       # 10


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
    with pytest.raises(rp.Refused, match="past the last line"):
        rp.check_domain(_record(OLD), _record(OLD), [(7, 11)], [])


def test_lines_of_a_file_cannot_be_told_for_a_composed_text():
    record = _record(OLD)
    record["front_lines"] = None
    with pytest.raises(rp.Refused, match="not the end of its file"):
        rp.check_domain(record, _record(OLD), [], [])


@pytest.mark.parametrize("content,why", [
    ("[]", "map a profile"),
    ('{"a": []}', "expected a mapping"),
    ('{"a": {"p/q": {"contract": [[1, 2]], "mixd": []}}}', "expected an object"),
    ('{"a": {"p/q": {"mixed": [[1, 2]]}}}', "expected an object"),
    ('{"a": {"p/q": {"contract": [[0, 2]]}}}', r"not \[first, last\]"),
    ('{"a": {"p/q": {"contract": [[3, 2]]}}}', r"not \[first, last\]"),
    ('{"a": {"p/q": {"contract": [[1, true]]}}}', r"not \[first, last\]"),
    ('{"a": {"p/q": {"contract": [[1, 3]], "mixed": [[3, 4]]}}}',
     "both contract and mixed"),
    ("{not json", "cannot read"),
])
def test_a_ranges_file_that_would_leave_lines_unchecked_is_refused(
        tmp_path, content, why):
    path = tmp_path / "ranges.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(rp.Refused, match=why):
        rp.read_ranges(path)


def test_a_ranges_file_is_read_into_ranges(tmp_path):
    path = tmp_path / "ranges.json"
    path.write_text('{"a": {"p/q": {"contract": [[1, 2], [5, 5]], '
                    '"mixed": [[7, 8]]}}}', encoding="utf-8")
    assert rp.read_ranges(path) == {"a": {"p/q": {
        "contract": [(1, 2), (5, 5)], "mixed": [(7, 8)]}}}


def _ranges(tmp_path, text):
    path = tmp_path / "ranges.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_on_the_command_line_a_reworded_domain_line_fails_the_run(
        repo, out, tmp_path):
    """Physical lines of the old file: the front matter has four, so the first
    sentence is line 5 and the second rule is line 8."""
    write(repo / PROMPTS / "extraction/rows.md",
          ROWS.replace("Keep it too.", "Keep it as well.")
              .replace("Find the numbers.", "Locate the numbers."))
    ranges = _ranges(tmp_path, '{"alpha": {"extraction/rows": '
                               '{"contract": [[5, 5]]}}}')

    assert render(repo, out, "--check-domain", str(ranges)) == 1

    text = section(summary(out), "alpha")
    assert ("old line 8 is not in the new text: `2. quote: the whole row. "
            "Keep it too.`") in text
    assert "`extraction/rows`: FAILED." in text
    assert "old line 7" not in text and "old line 5" not in text


def test_on_the_command_line_a_rewrite_inside_the_ranges_holds(
        repo, out, tmp_path):
    write(repo / PROMPTS / "extraction/rows.md",
          ROWS.replace("Find the numbers.", "Locate the numbers.")
              .replace("2. quote", "5. quote"))
    ranges = _ranges(tmp_path, '{"alpha": {"extraction/rows": '
                               '{"contract": [[5, 5]]}}}')

    assert render(repo, out, "--check-domain", str(ranges)) == 0

    assert "`extraction/rows`: holds." in section(summary(out), "alpha")


def test_on_the_command_line_mixed_lines_are_listed_for_a_person(
        repo, out, tmp_path):
    write(repo / PROMPTS / "extraction/rows.md",
          ROWS.replace("Keep it too.", "Keep it as well."))
    ranges = _ranges(tmp_path, '{"alpha": {"extraction/rows": '
                               '{"contract": [[5, 5]], "mixed": [[8, 8]]}}}')

    assert render(repo, out, "--check-domain", str(ranges)) == 0

    text = section(summary(out), "alpha")
    assert "mixed, old line 8 does not stand verbatim" in text
    assert "1 mixed line(s) for a person to read" in text


def test_a_prompt_the_ranges_name_that_the_before_tree_lacks_fails(
        repo, out, tmp_path):
    ranges = _ranges(tmp_path, '{"alpha": {"extraction/none": '
                               '{"contract": [[1, 1]]}}}')

    assert render(repo, out, "--check-domain", str(ranges)) == 1

    assert ("`extraction/none`: FAILED, it is not rendered on both sides"
            in summary(out))


def test_a_ranges_file_past_the_old_file_fails_the_run_and_says_where(
        repo, out, tmp_path):
    ranges = _ranges(tmp_path, '{"alpha": {"extraction/rows": '
                               '{"contract": [[5, 99]]}}}')

    assert render(repo, out, "--check-domain", str(ranges)) == 1

    assert "range 5-99 is past the last line (8) of the old file" \
        in summary(out)


def test_ranges_for_a_profile_nobody_asked_for_are_refused(repo, out, tmp_path,
                                                          nothing_runs, capsys):
    ranges = _ranges(tmp_path, '{"beta": {"extraction/rows": '
                               '{"contract": [[1, 1]]}}}')
    assert render(repo, out, "--check-domain", str(ranges)) == 2
    assert "beta" in capsys.readouterr().err


def test_without_a_ranges_file_nothing_is_said_about_the_domain(repo, out):
    assert render(repo, out) == 0
    assert "Domain check" not in summary(out)


# ---------------------------------------------------------------------------
# The pieces
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


@pytest.mark.parametrize("before,after,state", [
    ({"text": "a", "meta": {}, "sha256": "1"},
     {"text": "a", "meta": {}, "sha256": "1"}, rp.IDENTICAL),
    ({"text": "a", "meta": {}, "sha256": "1"},
     {"text": "b", "meta": {}, "sha256": "2"}, rp.CHANGED),
    ({"text": "a", "meta": {"max_tokens": 1}, "sha256": "1"},
     {"text": "a", "meta": {"max_tokens": 2}, "sha256": "1"}, rp.CHANGED),
    ({"text": "a", "meta": {}, "sha256": "1"},
     {"text": "a", "meta": {}, "sha256": "2"}, rp.CHANGED),
    (None, {"text": "a", "meta": {}, "sha256": "1"}, rp.ADDED),
    ({"text": "a", "meta": {}, "sha256": "1"}, None, rp.REMOVED),
    ({"error": "boom"}, {"text": "a", "meta": {}, "sha256": "1"}, rp.ERROR),
    ({"text": "a", "meta": {}, "sha256": "1"}, {"error": "boom"}, rp.ERROR),
])
def test_what_makes_a_prompt_the_same_on_both_sides(before, after, state):
    assert rp.status_of(before, after) == state


def test_a_table_cell_cannot_break_the_table():
    assert rp._table(["a"], [["x | y\nz"]])[2] == "| x \\| y z |"


def test_a_value_that_moved_shows_both_ends():
    assert rp.pair(6, 6) == "6"
    assert rp.pair(6, 3) == "6 -> 3"
    assert rp.pair(None, 3) == "- -> 3"
    assert rp.pair(None, None) == "-"


# ---------------------------------------------------------------------------
# Two runs on a copy of the real code
# ---------------------------------------------------------------------------

@pytest.fixture
def real(tmp_path):
    """The real loader and the real profiles, committed in a repository of
    their own: what the tool would be pointed at."""
    path = tmp_path / "real"
    path.mkdir()
    for name in rp.TREE_DIRS:
        shutil.copytree(ROOT / name, path / name, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc"))
    git(path, "init", "-q")
    commit(path)
    return path


def _expected(name: str, monkeypatch) -> dict:
    """The numbers of a profile, taken in this process by the code of this
    tree."""
    from docpipe import prompts
    from docpipe.extraction import fields, runner
    from docpipe.profile import load_profile
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    profile = load_profile(name)
    spec = runner.load_spec(Path(profile.component("extraction", "SPEC_PATH")))
    framed = bool(fields.frame_slots(
        spec, profile.component("extraction", "FRAME") or ()))
    window = runner.request_budget(spec, framed)
    sources = runner.batch_sources_for(spec)
    budgets = {pid: runner.context_budget(prompts.load(pid, profile), spec)
               for pid in (*runner.PROMPT_IDS, runner.REVIEW_PROMPT_ID)
               if pid != runner.QUERIES_PROMPT_ID}
    return {"window": window, "sources": sources, "budgets": budgets}


def test_the_real_profiles_are_identical_to_themselves_and_the_numbers_are_the_codes(
        real, out, monkeypatch, bytecode_allowed):
    """Nothing moved, so every prompt of the three profiles is identical, and
    the numbers equal what the code computes. A `.env` in the tree and the
    caller's environment ask for other settings and are not heard."""
    expected = {name: _expected(name, monkeypatch)
                for name in ("kwp", "scenarios")}
    (real / ".env").write_text("EXTRACT_BATCH_SOURCES=2\n", encoding="utf-8")
    monkeypatch.setenv("EXTRACT_BATCH_SOURCES", "3")
    before = snapshot(real)

    code = render(real, out, profiles=("kwp", "scenarios", "default"))

    assert code == 0, summary(out)
    assert snapshot(real) == before
    text = summary(out)
    for name in ("kwp", "scenarios", "default"):
        counts = cells(text, name)
        assert counts[2:7] == [counts[1], "0", "0", "0", "0"]   # all identical
        assert int(counts[1]) > 25                              # and many
    for name, want in expected.items():
        mine = section(text, name)
        assert cells(mine, "window (tokens)")[1:] == [str(want["window"])] * 2
        assert cells(mine, "sources per request (sources)")[1:] == [
            str(want["sources"])] * 2
        for pid, tokens in want["budgets"].items():
            assert budget_row(mine, pid)[1:] == [str(tokens)] * 2
        assert "batch_sources 6" in mine
    assert "configures no extraction spec" in section(text, "default")


def test_an_edited_sentence_of_a_real_prompt_is_that_prompt_alone(real, out):
    # a prompt that is one plain file, which no template composes
    path = real / "profiles/kwp/prompts/extraction/phrase.md"
    old = path.read_text(encoding="utf-8")
    first = old.split("---\n", 2)[2].split("\n", 1)[0]
    added = " A new sentence stands here."
    write(path, old.replace(first, first + added, 1))

    assert render(real, out, profiles=("kwp",)) == 0

    text = summary(out)
    changed = [line.split("|")[1].strip() for line in text.splitlines()
               if line.startswith("| `") and "| changed |" in line]
    assert changed == ["`extraction/phrase`"]
    diff = lines_of(out / "kwp/extraction/phrase.sentences.diff")
    assert changed_lines(diff) == ["+A new sentence stands here."]
    after = (out / "kwp/extraction/phrase.after.txt").read_text(
        encoding="utf-8")
    assert after == old.split("---\n", 2)[2].replace(first, first + added, 1)
    # the budget of that prompt grew by what the sentence adds, the others not
    mine = section(text, "kwp")
    phrase = budget_row(mine, "extraction/phrase")
    assert int(phrase[2]) > int(phrase[1])
    for other in ("extraction/rows", "extraction/field"):
        assert budget_row(mine, other)[1] == budget_row(mine, other)[2]


# ---------------------------------------------------------------------------
# AND a prompt the loader composes from a template is shown with what the
# profile worded and what it left out
# ---------------------------------------------------------------------------

SYNTH = "profiles/synth"
REWORDED = "Every entry is read twice."


def _composed_profile(real: Path) -> str:
    """The real loader with a profile of its own: its rows prompt is first one
    file as a person wrote it, committed, and then the parts of a made-up
    template that make the same text. What the working tree shows is the
    second, as it will be after a prompt of a profile has been cut into parts.
    Returns the text of the prompt."""
    from tests.test_prompt_parts import (EXPECTED_WITHOUT, FRONT, TEMPLATE_XX,
                                         parts_with, without)
    text = EXPECTED_WITHOUT.replace(
        "Every entry is checked against the source.", REWORDED)
    write(real / SYNTH / "__init__.py", "")
    write(real / SYNTH / "profile.py",
          "from docpipe.profile import Profile\n"
          "PROFILE = Profile(name='synth', extends='default')\n")
    write(real / SYNTH / "extraction.py", "CONTRACT_LANGUAGE = 'xx'\n")
    write(real / SYNTH / "prompts/extraction/rows.md", FRONT + text)
    commit(real, "a profile that wrote its rows prompt as one file")
    write(real / "docpipe/extraction/contract/xx/rows.md", TEMPLATE_XX)
    write(real / SYNTH / "prompts/extraction/rows.md", parts_with(
        ("row_note", REWORDED), front=without("sandbox", "images")))
    return text


def test_the_summary_lists_the_overrides_and_the_omissions_of_a_composed_prompt(
        real, out, bytecode_allowed):
    text = _composed_profile(real)

    assert render(real, out, profiles=("synth",)) == 0, summary(out)

    mine = section(summary(out), "synth")
    assert all_rows(mine, "`extraction/rows`")[-1] == [
        "`extraction/rows`", "rows", "row_note", "images, sandbox"]
    row = prompt_row(mine, "extraction/rows")
    # the same text, the same parameters and so the same sha256 as the file
    # the profile wrote by hand: nothing moved, and the summary says so
    assert row[2] == "identical" and row[-1] == "rows"
    assert (out / "synth/extraction/rows.after.txt").read_text(
        encoding="utf-8") == text
    assert not list(out.rglob("*.what-if.*"))


def test_a_prompt_that_is_not_composed_has_nothing_listed_beside_it(
        real, out, bytecode_allowed):
    _composed_profile(real)

    assert render(real, out, profiles=("synth",)) == 0

    mine = section(summary(out), "synth")
    assert prompt_row(mine, "extraction/phrase")[-1] == "-"
    listed = [row[0] for row in all_rows(mine, "`extraction/phrase`")]
    assert listed == ["`extraction/phrase`"]      # the prompt table alone


def test_what_if_renders_an_omitted_block_of_a_composed_prompt_back_in(
        real, out, bytecode_allowed):
    from tests.test_prompt_parts import EXPECTED
    text = _composed_profile(real)

    assert render(real, out, "--what-if", profiles=("synth",)) == 0, summary(out)

    base = out / "synth/extraction"
    images = (base / "rows.what-if.images.txt").read_text(encoding="utf-8")
    sandbox = (base / "rows.what-if.sandbox.txt").read_text(encoding="utf-8")
    assert images == text.replace(
        "You get sources.", "You get sources. Images follow the JSON.")
    assert sandbox == EXPECTED.replace(
        "You get sources. Images follow the JSON.", "You get sources.").replace(
        "Every entry is checked against the source.", REWORDED)
    # built to fail: a what-if that gave back the prompt as it is says nothing
    assert images != text and sandbox != text and images != sandbox
    assert changed_lines(lines_of(
        base / "rows.what-if.images.sentences.diff")) == [
            "+Images follow the JSON."]
    added = changed_lines(lines_of(
        base / "rows.what-if.sandbox.sentences.diff"))
    assert "+3. Calculate with the sandbox." in added
    assert "+   If it must be calculated, see rule 3." in added
    mine = section(summary(out), "synth")
    assert "`extraction/rows`, block `images`" in mine
    assert "`extraction/rows`, block `sandbox`" in mine


def test_a_composed_prompt_that_changed_is_a_changed_prompt_with_its_sentences(
        real, out, bytecode_allowed):
    """Built to fail: the case above is `identical` because the two sides were
    made to say the same. Put one sentence into a part and the tool says which
    prompt moved and which sentence."""
    _composed_profile(real)
    path = real / SYNTH / "prompts/extraction/rows.md"
    write(path, path.read_text(encoding="utf-8").replace(
        "You read plans.", "You read plans and tables."))

    assert render(real, out, profiles=("synth",)) == 0

    mine = section(summary(out), "synth")
    assert prompt_row(mine, "extraction/rows")[2] == "changed"
    assert changed_lines(lines_of(out / "synth/extraction/rows.sentences.diff")) \
        == ["-You read plans.", "+You read plans and tables."]
