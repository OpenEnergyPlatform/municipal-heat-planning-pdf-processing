#!/usr/bin/env python3
"""
render_prompts.py: What a change does to the prompts of a profile, read before
anything runs.

A prompt is the contract with the model, and a sentence that moves in it moves
every request of a run. A diff of the files shows the words somebody edited. It
does not show the text the loader makes of them, and not what that text does to
the window a run asks the server for. So both sides are rendered by their own
code and set next to each other:

  before   `git archive` of a ref, unpacked into a temporary folder and read by
           THAT tree's loader, in a process of its own
  after    the working tree, read by its own loader the same way

Per profile and prompt it writes the exact text of each side
(`<stage>/<name>.before.txt`, `.after.txt`), the sentences that differ
(`.sentences.diff`, one changed sentence per line) and, in `summary.md`, the
sizes, the sha256 of each side and what a run takes from the prompts: sources
per request and the window it asks the server for, each by the rule of its own
side. The tool reads files and imports the two trees. It does not touch the
repository, a model or `data/`, and it refuses an output folder inside the
repository.

The numbers rest on the settings' defaults. The environment's EXTRACT_*
variables, a project file and a `.env` are not read, so two runs on two
machines give the same numbers.

    python scripts/render_prompts.py --profile kwp --profile scenarios --before HEAD
    python scripts/render_prompts.py --profile kwp --before main --out ../review
    python scripts/render_prompts.py --profile default --before HEAD~2 --what-if
    python scripts/render_prompts.py --profile kwp --before HEAD --check-domain r.json

`--check-domain FILE` holds a rewrite to "the domain stays word for word": the
file lists, per profile and prompt, the physical line numbers of the OLD file
(front matter counted) that are the core's contract wording and those that are
mixed:

    {"kwp": {"extraction/rows": {"contract": [[7, 7], [9, 9]],
                                 "mixed": [[37, 37]]}}}

Every other non-blank old line must stand verbatim in the new text, ignoring a
leading rule number ("12. "). A line that does not is named and the exit code
is 1. Mixed lines are listed with whether they stand verbatim, for a person to
read.

The summary lists the overrides and omissions of every composed prompt, and
`--what-if` also renders each block a profile leaves out back in. A loader that
composes prompts says so on `Prompt.composition`: None for a plain prompt,
else a mapping with `template`, `overrides` (block names a profile words
itself), `omitted` (block names it leaves out) and, for the what-if,
`what_if` ({omitted block: the prompt's text with that block put back}). A
loader that composes nothing has nothing to show, and the summary says so. One
that reports an omission and gives no text for it fails the run: the question
asked had an answer and it was not given.

Exit code: 0 when everything asked for was rendered, 1 when a prompt or a
profile could not be rendered or a domain line is missing, 2 when the request
cannot be carried out (an unknown ref, an output folder inside the repository).

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
# What a tree needs for its loader to read a profile's prompts.
TREE_DIRS = ("docpipe", "profiles")
OUT_NAME = "docpipe-prompt-review"
PROBE_FLAG = "--probe"
PROBE_SECONDS = 300
# Environment names the numbers must not depend on; see the module docstring.
SETTING_PREFIXES = ("EXTRACT_",)
SETTING_NAMES = ("BATCH_SOURCES", "BATCH_CHARS", "MAX_SOURCE_CHARS",
                 "ATTACH_IMAGES", "PRIOR_MAX", "PRIOR_TOKENS")

IDENTICAL, CHANGED, ADDED, REMOVED, ERROR = (
    "identical", "changed", "added", "removed", "error")
# What a person looks at first comes first.
ORDER = (ERROR, CHANGED, ADDED, REMOVED, IDENTICAL)

RULES = {
    "single": "one prompt for both: its budget is the window, its max_tokens "
              "set the sources",
    "sent": "the prompts a run sends: the largest of their budgets is the "
            "window, the max_tokens of the rows prompt set the sources",
}
# What a tree older than `request_budget` is asked for its window.
WINDOW_COMMAND = ["--print-context-budget", "db", "index", "out"]


class Refused(Exception):
    """A request that cannot be carried out. The message says why."""


# ---------------------------------------------------------------------------
# git, and the two trees
# ---------------------------------------------------------------------------

def _git(root: Path, *args: str, binary: bool = False):
    try:
        done = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise Refused("git is not installed or not on the path") from exc
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip()
        raise Refused(f"git {args[0]} failed: {said}")
    return done.stdout if binary else done.stdout.decode("utf-8", "replace")


def repo_root(path: Path) -> Path:
    """The top of the repository *path* lies in."""
    return Path(_git(path, "rev-parse", "--show-toplevel").strip()).resolve()


def resolve_ref(root: Path, ref: str) -> str:
    """The commit a ref names. A ref that starts with '-' is an option for
    git, not a ref."""
    if ref.startswith("-"):
        raise Refused(f"{ref!r} is not a ref")
    try:
        return _git(root, "rev-parse", "--verify", "--quiet",
                    f"{ref}^{{commit}}").strip()
    except Refused as exc:
        raise Refused(f"{ref!r} is not a commit of this repository") from exc


def head_state(root: Path) -> tuple:
    """(HEAD, whether the working tree differs from it where prompts and the
    loader live): the 'after' side is the working tree, not HEAD."""
    head = _git(root, "rev-parse", "HEAD").strip()
    dirty = bool(_git(root, "status", "--porcelain", "--",
                      *TREE_DIRS).strip())
    return head, dirty


def extract_tree(root: Path, sha: str, dest: Path) -> None:
    """The files of one commit that a loader needs, unpacked into *dest*.

    Files and folders only: a link would be followed outside the temporary
    folder or fail by the machine's rights, and either is a prompt that is
    quietly not the one the commit holds.
    """
    data = _git(root, "archive", "--format=tar", sha, "--", *TREE_DIRS,
                binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = tar.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if Path(member.name).is_absolute() or ".." in parts:
                raise Refused(f"the archive names {member.name!r}, which "
                              f"leaves the folder it is unpacked into")
            if not (member.isfile() or member.isdir()):
                raise Refused(f"{member.name} is a link or a special file; "
                              f"only files and folders are rendered")
        dest.mkdir(parents=True, exist_ok=True)
        tar.extractall(dest, members=members)


def _inside(path: Path, root: Path) -> bool:
    a, b = os.path.normcase(str(path)), os.path.normcase(str(root))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:                  # another drive
        return False


def default_out() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(tempfile.gettempdir()) / OUT_NAME / stamp


def choose_out(given: Optional[Path], root: Path) -> Path:
    """The folder to write into: resolved, outside the repository, empty or
    not there yet. Compared after resolving, so `..` and links do not get a
    path inside past the check. A folder that already holds files is refused
    because files of an earlier run would sit beside this one's and read as
    its own."""
    # Absolute first: where the platform's resolve leaves a relative path that
    # does not exist yet as it is, the check below would compare it as written.
    out = Path(os.path.abspath(
        given if given is not None else default_out())).resolve()
    if _inside(out, root):
        raise Refused(f"{out} lies inside the repository; what this tool "
                      f"writes is not part of it. Name a folder outside it "
                      f"with --out")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refused(f"{out} exists and is not an empty folder; name a "
                      f"new one with --out")
    return out


# ---------------------------------------------------------------------------
# What one tree's own loader says about a profile (runs in a process of its own)
# ---------------------------------------------------------------------------

def composition_of(prompt) -> Optional[dict]:
    """How a loader composed a prompt, or None for a plain one. See the module
    docstring for the names it reads."""
    found = getattr(prompt, "composition", None)
    if not found:
        return None
    return {"template": str(found.get("template", "")),
            "overrides": sorted(str(n) for n in found.get("overrides") or ()),
            "omitted": sorted(str(n) for n in found.get("omitted") or ()),
            "what_if": {str(k): str(v) for k, v in
                        dict(found.get("what_if") or {}).items()}}


def _front_lines(prompt) -> Optional[int]:
    """How many physical lines of the file lie above the text, or None when
    the text is not the end of that file (a composed prompt): a line number of
    the file means nothing then."""
    try:
        raw = Path(prompt.path).read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.endswith(prompt.text):
        return None
    return raw[:len(raw) - len(prompt.text)].count("\n")


def _describe(prompt, owners: list) -> dict:
    """What the report keeps of a prompt: its text and sha256 as the loader
    gives them, its parameters, the profile it comes from (the nearest one
    that has it) and how it was composed."""
    home = None
    for owner in owners:
        if _inside(Path(prompt.path).resolve(), owner.prompts_dir.resolve()):
            home = owner.name
            break
    return {"text": prompt.text, "sha256": prompt.sha256,
            "meta": json.loads(json.dumps(dict(prompt.meta), default=str)),
            "owner": home, "front_lines": _front_lines(prompt),
            "composition": composition_of(prompt)}


def _single_prompt_rule(runner, spec) -> tuple:
    """(window, sources per request) of a tree from before the two were taken
    from the prompts a run sends: it counted both from one prompt.

    Which prompt is the tree's own to say, and it says it by what it does: its
    `--print-context-budget` is run, and the prompt that `context_budget` is
    given is the one the window is counted from. The sources per request were
    sized from that same prompt. A command that prints a number no single
    `context_budget` call produced is no rule this tool knows, and says so
    instead of guessing."""
    asked = getattr(runner, "context_budget", None)
    main = getattr(runner, "main", None)
    if asked is None or main is None or not hasattr(runner,
                                                    "fit_batch_sources"):
        raise RuntimeError("the runner has neither request_budget nor a "
                           "command that prints its window, so no rule is "
                           "known for its window")
    calls: list = []

    def counting(prompt, *args, **kwargs):
        calls.append((prompt, asked(prompt, *args, **kwargs)))
        return calls[-1][1]

    printed = io.StringIO()
    runner.context_budget = counting
    try:
        with contextlib.redirect_stdout(printed):
            code = main(list(WINDOW_COMMAND))
    except SystemExit as exc:
        code = exc.code
    finally:
        runner.context_budget = asked
    words = printed.getvalue().split()
    if (code != 0 or len(calls) != 1 or len(words) != 1
            or not words[0].isdigit() or int(words[0]) != calls[0][1]):
        raise RuntimeError(
            f"the runner's window command (exit {code}, printed "
            f"{printed.getvalue().strip()!r}, {len(calls)} budget call(s)) "
            f"is not a window counted from one prompt, so no rule is known "
            f"for its window")
    return calls[0][1], runner.fit_batch_sources(calls[0][0], spec)


def _numbers(profile, prompts, spec_path) -> dict:
    """What a run takes from the prompts, by the rule of the tree being read:
    the sources per request and the window `--print-context-budget` prints,
    and the budget of every prompt a request can carry."""
    from docpipe.extraction import fields, runner
    spec = runner.load_spec(Path(spec_path))
    framed = bool(fields.frame_slots(
        spec, profile.component("extraction", "FRAME") or ()))
    budgets = {}
    for pid in (*runner.PROMPT_IDS, runner.REVIEW_PROMPT_ID):
        if pid == runner.QUERIES_PROMPT_ID:     # search templates, no request
            continue
        try:
            budgets[pid] = runner.context_budget(
                prompts.load(pid, profile), spec)
        except FileNotFoundError:
            budgets[pid] = None
    if hasattr(runner, "request_budget") and hasattr(runner,
                                                     "batch_sources_for"):
        rule = "sent"
        window = runner.request_budget(spec, framed)
        sources = runner.batch_sources_for(spec)
    else:
        rule = "single"
        window, sources = _single_prompt_rule(runner, spec)
    return {"configured": True, "rule": rule, "framed": framed,
            "sources_per_request": sources, "window_tokens": window,
            "budgets": budgets,
            # strictly: a renamed constant means the budget is counted
            # another way, and a table with "None" in it would hide that
            "settings": {name: getattr(runner, name)
                         for name in SETTING_NAMES}}


def probe(tree: Path, name: str) -> dict:
    """One profile as the loader of *tree* reads it: every prompt it has or
    inherits, and what a run would take from them. Imports the tree, so it runs
    in a process of its own and never in the caller's."""
    tree = tree.resolve()
    sys.path.insert(0, str(tree))
    import docpipe
    if Path(docpipe.__file__).resolve().parent.parent != tree:
        raise RuntimeError("docpipe was not imported from the tree asked for, "
                           "so the text would not be that tree's")
    from docpipe import prompts
    from docpipe.profile import load_profile
    try:
        profile = load_profile(name)
    except LookupError as exc:
        return {"state": "missing", "detail": str(exc), "prompts": {},
                "numbers": None, "lineage": []}
    owners = profile.lineage()
    ids = sorted({f"{path.parent.name}/{path.stem}" for owner in owners
                  for path in owner.prompts_dir.glob("*/*.md")})
    found: dict = {}
    for pid in ids:
        try:
            found[pid] = _describe(prompts.load(pid, profile), owners)
        except Exception as exc:        # the loader refusing a prompt is the finding
            found[pid] = {"error": f"{type(exc).__name__}: {exc}"}
    spec_path = profile.component("extraction", "SPEC_PATH")
    if spec_path is None:
        numbers = {"configured": False}
    else:
        try:
            numbers = _numbers(profile, prompts, spec_path)
        except Exception as exc:
            numbers = {"configured": True,
                       "error": f"{type(exc).__name__}: {exc}"}
    return {"state": "ok", "prompts": found, "numbers": numbers,
            "lineage": [owner.name for owner in owners]}


def _probe_main(argv: list) -> int:
    tree, name, out = Path(argv[0]), argv[1], Path(argv[2])
    out.write_text(json.dumps(probe(tree, name)), encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# Running the probe on a tree
# ---------------------------------------------------------------------------

def probe_env(scratch: Path, profile: str) -> dict:
    """The environment of one probe: the caller's, minus what would move the
    numbers, plus a place for everything a loader might write. Nothing is
    written beside the code, so the repository stays as it was."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(SETTING_PREFIXES)}
    env.update({
        "DOCPIPE_PROFILE": profile,
        "DOCPIPE_CONFIG": "",           # no project file
        "DOCPIPE_ENV_FILE": "",         # and no .env
        "INFERENCE_ENV_FILE": "",
        "DOCPIPE_USAGE_DB": str(scratch / "usage.db"),
        "DOCPIPE_DATA_ROOT": str(scratch / "data"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1"})
    return env


def run_probe(tree: Path, profile: str, scratch: Path) -> dict:
    """`probe` for one tree and profile, in a process whose working folder is
    empty: a `.env` or a `docpipe.toml` of the tree must not be found."""
    work = Path(tempfile.mkdtemp(dir=scratch))
    out = work / "probe.json"
    command = [sys.executable, str(Path(__file__).resolve()), PROBE_FLAG,
               str(tree), profile, str(out)]
    try:
        done = subprocess.run(command, cwd=work, env=probe_env(work, profile),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=PROBE_SECONDS)
    except subprocess.TimeoutExpired:
        return {"state": "failed", "prompts": {}, "numbers": None,
                "lineage": [],
                "detail": f"no answer within {PROBE_SECONDS} seconds"}
    if done.returncode != 0 or not out.is_file():
        tail = "\n".join(done.stderr.strip().splitlines()[-12:])
        return {"state": "failed", "prompts": {}, "numbers": None,
                "lineage": [], "detail": tail or "the probe wrote nothing"}
    return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Sentences and their diff
# ---------------------------------------------------------------------------

# The typographic quotes by code point, so that this file stays ASCII: what may
# close a sentence after its stop, and what may open one besides a capital.
_CLOSING = "\"')]" + "".join(chr(code) for code in (0x201C, 0x201D, 0x2019,
                                                     0xAB, 0xBB))
# A stop, the quotes and brackets that close the sentence with it, the space.
_STOP = re.compile(r"[.!?][" + re.escape(_CLOSING) + r"]*(\s+)(?=\S)")
# Besides a capital, what may open a sentence.
_OPENERS = "\"'([{<`" + "".join(chr(code) for code in (0x201E, 0x201C, 0x201A,
                                                       0x2018, 0xAB, 0xBB))


def sentences(line: str) -> list:
    """One line cut where a sentence ends: a stop, a space and a capital or an
    opening quote or bracket. Not after a single letter ("z. B.", "d. h.") and
    not after the number that opens a list item. The cut only decides what one
    line of the diff is. The same rule runs on both sides, so a wrong cut shows
    as two lines on each and never hides a change."""
    out, start = [], 0
    for hit in _STOP.finditer(line):
        words = line[start:hit.start()].split()
        word = words[-1].replace(".", "") if words else ""
        following = line[hit.end()]
        if word.isalpha() and len(word) < 2:
            continue
        if word.isdigit() and line[:hit.start()].strip() == word:
            continue                    # "3." that opens a list item
        if not (following.isupper() or following in _OPENERS):
            continue
        out.append(line[start:hit.start(1)])
        start = hit.end()
    out.append(line[start:])
    return out


def units(text: str) -> list:
    """The lines of a text, each cut into its sentences. A blank line is one
    unit and the end of the text is one, so a change of paragraphs or of the
    last newline is a change in the list."""
    out: list = []
    for line in text.split("\n"):
        out.extend(sentences(line) if line.strip() else [line])
    return out


def _range(start: int, stop: int) -> str:
    length = stop - start
    if length == 1:
        return str(start + 1)
    if not length:
        start -= 1
    return f"{start + 1},{length}"


def unified(before: list, after: list, context: int = 2) -> list:
    """The unified diff of two lists of units. Not `difflib.unified_diff`: its
    matcher treats an item that repeats as junk once a list reaches 200
    items, and blank lines repeat."""
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    out = []
    for group in matcher.get_grouped_opcodes(context):
        first, last = group[0], group[-1]
        out.append(f"@@ -{_range(first[1], last[2])} "
                   f"+{_range(first[3], last[4])} @@")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out += [f" {unit}" for unit in before[i1:i2]]
                continue
            if tag in ("replace", "delete"):
                out += [f"-{unit}" for unit in before[i1:i2]]
            if tag in ("replace", "insert"):
                out += [f"+{unit}" for unit in after[j1:j2]]
    return out


def _show(value) -> str:
    return "-" if value is None else str(value)


def pair(before, after) -> str:
    """One cell for a value that may have moved."""
    if before == after:
        return _show(after)
    return f"{_show(before)} -> {_show(after)}"


def status_of(before: Optional[dict], after: Optional[dict]) -> str:
    """Whether a prompt is the same on both sides: its text, its parameters
    and its sha256, which is what a stamp records."""
    if (before or {}).get("error") or (after or {}).get("error"):
        return ERROR
    if before is None:
        return ADDED
    if after is None:
        return REMOVED
    same = (before["text"] == after["text"] and before["meta"] == after["meta"]
            and before["sha256"] == after["sha256"])
    return IDENTICAL if same else CHANGED


def diff_text(pid: str, before: Optional[dict], after: Optional[dict],
              names: tuple = ("before", "after")) -> str:
    """The `.sentences.diff` of one prompt: the parameters that moved as
    comment lines, then the sentences."""
    old = before["text"] if before else ""
    new = after["text"] if after else ""
    meta_before = before["meta"] if before else {}
    meta_after = after["meta"] if after else {}
    lines = [f"--- {pid} ({names[0]})", f"+++ {pid} ({names[1]})"]
    for key in sorted(set(meta_before) | set(meta_after)):
        if meta_before.get(key) != meta_after.get(key):
            lines.append(f"# {key}: {_show(meta_before.get(key))} -> "
                         f"{_show(meta_after.get(key))}")
    moved = len(lines) > 2              # a parameter differs
    body = unified(units(old), units(new))
    if body:
        lines += body
    elif old != new:
        lines.append("# the sentences are the same; the texts differ in "
                     "whitespace only")
    elif moved:
        pass                            # the parameters are the whole change
    elif before and after and before["sha256"] != after["sha256"]:
        lines.append("# the text and the parameters are the same; the sha256 "
                     "differs, the file is written differently")
    else:
        lines.append("# the same on both sides")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The domain check
# ---------------------------------------------------------------------------

_RULE_NUMBER = re.compile(r"^\s*\d+[.)]\s+")
_RANGE_KEYS = ("contract", "mixed")


def read_ranges(path: Path) -> dict:
    """The file `--check-domain` names, as {profile: {prompt: {"contract":
    [(first, last)], "mixed": [...]}}}. A key it does not know is a mistake
    that would leave a line unchecked, so it is refused."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot read the ranges file: {exc}") from exc
    if not isinstance(data, dict):
        raise Refused("the ranges file must map a profile to its prompts")
    out: dict = {}
    for profile, prompts in data.items():
        if not isinstance(prompts, dict):
            raise Refused(f"ranges of {profile!r}: expected a mapping from "
                          f"prompt id to ranges")
        for pid, entry in prompts.items():
            where = f"ranges of {profile}/{pid}"
            if not isinstance(entry, dict) or set(entry) - set(_RANGE_KEYS) \
                    or "contract" not in entry:
                raise Refused(f"{where}: expected an object with 'contract' "
                              f"and optionally 'mixed'")
            parsed = {}
            for key in _RANGE_KEYS:
                parsed[key] = [_one_range(r, f"{where}, {key}")
                               for r in entry.get(key, [])]
            if _overlap(parsed["contract"], parsed["mixed"]):
                raise Refused(f"{where}: a line is both contract and mixed")
            out.setdefault(profile, {})[pid] = parsed
    return out


def _one_range(value, where: str) -> tuple:
    ok = (isinstance(value, list) and len(value) == 2
          and all(isinstance(n, int) and not isinstance(n, bool)
                  for n in value) and 1 <= value[0] <= value[1])
    if not ok:
        raise Refused(f"{where}: {value!r} is not [first, last] with "
                      f"1 <= first <= last")
    return (value[0], value[1])


def _overlap(left: list, right: list) -> bool:
    return any(a <= d and c <= b for a, b in left for c, d in right)


def _in(number: int, ranges: list) -> bool:
    return any(first <= number <= last for first, last in ranges)


def physical_lines(record: dict) -> list:
    """[(line number in the file, text)] of a prompt, the front matter above
    it counted. A text that is not the end of its file has no such numbers."""
    front = record.get("front_lines")
    if front is None:
        raise Refused("the text is not the end of its file, so lines of the "
                      "file cannot be told")
    lines = record["text"].split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [(front + index + 1, line) for index, line in enumerate(lines)]


def check_domain(old: dict, new: dict, contract: list, mixed: list) -> dict:
    """The old lines outside the contract ranges against the new text.

    A line passes when it stands in the new text exactly as written, apart
    from a leading rule number and the whitespace at its ends. Contract lines
    are not looked at: they are what the rewrite is meant to move. Mixed
    lines are listed with the answer, for a person to decide.
    """
    lines = physical_lines(old)
    last = lines[-1][0] if lines else 0
    for first, stop in (*contract, *mixed):
        if stop > last:
            raise Refused(f"range {first}-{stop} is past the last line "
                          f"({last}) of the old file")
    result = {"checked": 0, "skipped": 0, "missing": [], "mixed": []}
    for number, line in lines:
        if not line.strip():
            continue
        needle = _RULE_NUMBER.sub("", line).strip()
        if _in(number, contract):
            result["skipped"] += 1
        elif _in(number, mixed):
            result["mixed"].append((number, line, needle in new["text"]))
        else:
            result["checked"] += 1
            if needle not in new["text"]:
                result["missing"].append((number, line))
    return result


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------

def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(head: list, rows: list) -> list:
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return out


def compare(before: dict, after: dict) -> list:
    """[(prompt id, status, before record, after record)], what a person looks
    at first first."""
    ids = set(before["prompts"]) | set(after["prompts"])
    rows = []
    for pid in ids:
        b, a = before["prompts"].get(pid), after["prompts"].get(pid)
        rows.append((pid, status_of(b, a), b, a))
    return sorted(rows, key=lambda r: (ORDER.index(r[1]), r[0]))


def _count(rows: list) -> dict:
    return {status: sum(1 for r in rows if r[1] == status) for status in ORDER}


def _size(record: Optional[dict], key: str):
    if not record or record.get("error"):
        return None
    return len(record["text"]) if key == "chars" else len(record["text"].split())


def _sha(record: Optional[dict]):
    return record["sha256"][:12] if record and "sha256" in record else None


def _meta(record: Optional[dict], key: str):
    return record["meta"].get(key) if record and "meta" in record else None


def _prompt_table(rows: list) -> list:
    out = []
    for pid, status, b, a in rows:
        out.append([
            f"`{pid}`", pair((b or {}).get("owner"), (a or {}).get("owner")),
            status,
            pair(_size(b, "chars"), _size(a, "chars")),
            pair(_size(b, "words"), _size(a, "words")),
            pair(_meta(b, "max_tokens"), _meta(a, "max_tokens")),
            pair(_meta(b, "temperature"), _meta(a, "temperature")),
            pair(_sha(b), _sha(a)),
            ((a or {}).get("composition") or {}).get("template") or "-"])
    return _table(["prompt", "from", "status", "chars", "words", "max_tokens",
                   "temperature", "sha256 (12 hex)", "template"], out)


def _numbers_section(before: dict, after: dict) -> list:
    nb, na = before.get("numbers"), after.get("numbers")
    out = ["### What a run takes from the prompts", ""]
    absent: dict = {}                   # what is not there, by what is said of it
    for label, numbers in (("before", nb), ("after", na)):
        if not numbers:
            absent.setdefault(
                f"not read ({_state_note(label, before, after)})",
                []).append(label)
        elif not numbers.get("configured"):
            absent.setdefault("not computed, the profile configures no "
                              "extraction spec", []).append(label)
        elif numbers.get("error"):
            absent.setdefault(f"not computed, {numbers['error']}",
                              []).append(label)
    for text, labels in absent.items():
        out += [f"- {' and '.join(labels)}: {text}", ""]
    computed = {label: n for label, n in (("before", nb), ("after", na))
                if n and n.get("configured") and not n.get("error")}
    if not computed:
        return out

    def take(label: str, key: str):
        return computed[label][key] if label in computed else None

    def yes(value):
        return None if value is None else ("yes" if value else "no")

    out += [*_table(["", "before", "after"], [
        ["rule", RULES.get(take("before", "rule"), "-"),
         RULES.get(take("after", "rule"), "-")],
        ["frame axes in the profile", _show(yes(take("before", "framed"))),
         _show(yes(take("after", "framed")))],
        ["sources per request (sources)",
         _show(take("before", "sources_per_request")),
         _show(take("after", "sources_per_request"))],
        ["window (tokens)", _show(take("before", "window_tokens")),
         _show(take("after", "window_tokens"))]]), ""]
    out += ["The window is what `--print-context-budget` prints: counted with "
            "the configured sources per request, before a run lowers them to "
            "what the answer can hold.", ""]
    budgets: dict = {}
    for label, numbers in computed.items():
        for pid, tokens in numbers["budgets"].items():
            budgets.setdefault(pid, {})[label] = tokens
    out += ["Budget per prompt (tokens one request of it needs at worst):", "",
            *_table(["prompt", "before", "after"],
                    [[f"`{pid}`", _show(v.get("before")), _show(v.get("after"))]
                     for pid, v in sorted(budgets.items())]), ""]
    said = "; ".join(
        f"{label}: " + ", ".join(f"{key.lower()} {value}" for key, value
                                 in numbers["settings"].items())
        for label, numbers in computed.items())
    return out + [f"Settings the numbers rest on ({said}).", ""]


def _state_note(label: str, before: dict, after: dict) -> str:
    side = before if label == "before" else after
    return {"missing": "the profile is not there",
            "failed": "the probe failed"}.get(side["state"], "no numbers")


def _composition_section(rows: list, what_if: bool) -> tuple:
    """(lines, problems, files): overrides and omissions of the composed
    prompts, and, with --what-if, what each omitted block would add."""
    composed = [(pid, a["composition"]) for pid, _s, _b, a in rows
                if a and not a.get("error") and a.get("composition")]
    out = ["### Overrides and omitted blocks", ""]
    problems: list = []
    files: list = []
    if not composed:
        out += ["Nothing to show: no prompt of the after tree is composed "
                "from a template, so there is no override and no omitted "
                "block.", ""]
    else:
        out += _table(["prompt", "template", "overrides", "omitted"],
                      [[f"`{pid}`", c["template"],
                        ", ".join(c["overrides"]) or "-",
                        ", ".join(c["omitted"]) or "-"]
                       for pid, c in composed]) + [""]
    if what_if:
        out += ["### What if the omitted blocks were switched on", ""]
        asked = [(pid, c) for pid, c in composed if c["omitted"]]
        if not asked:
            out += ["Nothing to show: no prompt of the after tree omits a "
                    "block.", ""]
        for pid, c in asked:
            gone = [name for name in c["omitted"] if name not in c["what_if"]]
            if gone:
                problems.append(f"{pid}: the loader reports the omitted "
                                f"block(s) {', '.join(gone)} and gives no text "
                                f"for putting them back")
            for name, text in sorted(c["what_if"].items()):
                files.append((pid, name, text))
                out.append(f"- `{pid}`, block `{name}`: see "
                           f"`{pid}.what-if.{name}.sentences.diff`")
        if asked:
            out.append("")
    return out, problems, files


def _domain_section(name: str, rows: list, ranges: dict) -> tuple:
    """(lines, number of problems) of the check of one profile."""
    mine = ranges.get(name, {})
    out = ["### Domain check", ""]
    problems = 0
    if not mine:
        return out + [f"The ranges file names no prompt of {name}; nothing was "
                      f"checked.", ""], 0
    by_id = {pid: (b, a) for pid, _s, b, a in rows}
    out.append(f"Checked {len(mine)} of {len(by_id)} prompt(s): those the "
               f"ranges file names. Counts are in non-blank lines.")
    out.append("")
    for pid, entry in sorted(mine.items()):
        b, a = by_id.get(pid, (None, None))
        if not b or b.get("error") or not a or a.get("error"):
            out.append(f"- `{pid}`: FAILED, it is not rendered on both sides")
            problems += 1
            continue
        try:
            found = check_domain(b, a, entry["contract"], entry["mixed"])
        except Refused as exc:
            out.append(f"- `{pid}`: FAILED, {exc}")
            problems += 1
            continue
        state = "FAILED" if found["missing"] else "holds"
        out.append(f"- `{pid}`: {state}. {found['checked']} line(s) outside "
                   f"the ranges, {len(found['missing'])} not verbatim in the "
                   f"new text; {found['skipped']} contract line(s) skipped; "
                   f"{len(found['mixed'])} mixed line(s) for a person to read.")
        problems += len(found["missing"])
        for number, line in found["missing"]:
            out.append(f"  - old line {number} is not in the new text: "
                       f"`{line.strip()}`")
        for number, line, stands in found["mixed"]:
            out.append(f"  - mixed, old line {number} "
                       f"{'stands verbatim' if stands else 'does not stand verbatim'}"
                       f": `{line.strip()}`")
    out.append("")
    return out, problems


def _problems(rows: list) -> list:
    out = []
    for pid, status, b, a in rows:
        if status == ERROR:
            for label, record in (("before", b), ("after", a)):
                if record and record.get("error"):
                    out.append(f"{pid} ({label}): {record['error']}")
    return out


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))      # no newline translation


def _stage_name(pid: str) -> tuple:
    stage, _, name = pid.partition("/")
    return stage, name


def write_profile(out: Path, name: str, rows: list, files: list,
                  labels: tuple) -> None:
    """The files of one profile. A text is written as the loader gave it."""
    for pid, _status, b, a in rows:
        stage, leaf = _stage_name(pid)
        base = out / name / stage / leaf
        for side, record in (("before", b), ("after", a)):
            if record and not record.get("error"):
                _write(base.with_name(f"{leaf}.{side}.txt"), record["text"])
        if not (b and b.get("error")) and not (a and a.get("error")):
            _write(base.with_name(f"{leaf}.sentences.diff"),
                   diff_text(pid, b, a, labels))
    for pid, block, text in files:
        stage, leaf = _stage_name(pid)
        after = next(a for p, _s, _b, a in rows if p == pid)
        base = out / name / stage
        _write(base / f"{leaf}.what-if.{block}.txt", text)
        _write(base / f"{leaf}.what-if.{block}.sentences.diff",
               diff_text(pid, after, {**after, "text": text},
                         ("after", f"after, with {block}")))


def _head_lines(args, sha: str, head: str, dirty: bool, profiles: list,
                stamp: str) -> list:
    after = f"working tree, HEAD `{head[:12]}`" + (
        ", with uncommitted changes under docpipe/ or profiles/" if dirty
        else ", no uncommitted changes under docpipe/ or profiles/")
    return ["# Prompt review", "",
            *_table(["", ""], [
                ["before", f"`{args.before}` (`{sha[:12]}`)"],
                ["after", after],
                ["profiles", ", ".join(profiles)],
                ["rendered", stamp],
                ["settings", "the defaults: no environment variable, project "
                             "file or .env of the caller is read"]]), "",
            "A `.sentences.diff` shows one sentence per line; the numbers in "
            "its `@@` lines count sentences, not lines of the file.", ""]


def render(args, profiles: list, ranges: Optional[dict], root: Path,
           sha: str, scratch: Path) -> tuple:
    """(summary lines, the files to write per profile, number of problems)."""
    before_tree = scratch / "before"
    extract_tree(root, sha, before_tree)
    head, dirty = head_state(root)
    jobs = [(side, tree, name) for name in profiles
            for side, tree in (("before", before_tree), ("after", root))]
    with ThreadPoolExecutor(max_workers=min(len(jobs), 4)) as pool:
        probed = list(pool.map(
            lambda job: run_probe(job[1], job[2], scratch), jobs))
    sides = {(job[0], job[2]): result for job, result in zip(jobs, probed)}

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = _head_lines(args, sha, head, dirty, profiles, stamp)
    body: list = []
    overview: list = []
    written: list = []
    problems = 0
    for name in profiles:
        before, after = sides[("before", name)], sides[("after", name)]
        if before["state"] == "missing" and after["state"] == "missing":
            raise Refused(f"profile {name!r} is on neither side: "
                          f"{after['detail']}")
        section = [f"## {name}", ""]
        failed = [(label, side) for label, side in
                  (("before", before), ("after", after))
                  if side["state"] == "failed"]
        for label, side in failed:
            section += [f"The {label} side could not be read:", "", "```",
                        side["detail"], "```", ""]
            problems += 1
        for label, side in (("before", before), ("after", after)):
            if side["state"] == "missing":
                section += [f"The profile is not on the {label} side "
                            f"({side['detail']}); all its prompts count as "
                            f"{'added' if label == 'before' else 'removed'}.",
                            ""]
        if failed:
            overview.append([name, "-", "-", "-", "-", "-", "not rendered"])
            body += section
            continue
        rows = compare(before, after)
        counts = _count(rows)
        overview.append([name, len(rows), counts[IDENTICAL], counts[CHANGED],
                         counts[ADDED], counts[REMOVED], counts[ERROR]])
        lineage = ", ".join(after["lineage"]) or "-"
        section += [f"Prompts come from: {lineage} (after).", "",
                    *_numbers_section(before, after)]
        for side in (before, after):
            numbers = side.get("numbers") or {}
            problems += 1 if numbers.get("error") else 0
        section += ["### Prompts", "", *_prompt_table(rows), ""]
        found = _problems(rows)
        if found:
            section += ["Prompts the loader could not read:", "",
                        *[f"- {text}" for text in found], ""]
            problems += len(found)
        composition, trouble, files = _composition_section(rows, args.what_if)
        section += composition
        problems += len(trouble)
        section += [f"- {text}" for text in trouble] + (
            [""] if trouble else [])
        if ranges is not None:
            domain, bad = _domain_section(name, rows, ranges)
            section += domain
            problems += bad
        body += section
        labels = (f"before: {args.before}", "after: working tree")
        written.append((name, rows, files, labels))
    lines += ["## Overview (prompts per profile)", "",
              *_table(["profile", "prompts", "identical", "changed", "added",
                       "removed", "not readable"], overview), "", *body]
    return lines, written, problems


def _profiles(names: list) -> list:
    out: list = []
    for name in names:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise Refused(f"{name!r} is a profile's name, not a path")
        if name not in out:
            out.append(name)
    return out


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render_prompts.py",
        description="Render the prompts of profiles before and after a "
                    "change and say what moved. Reads files; touches neither "
                    "the repository nor a model.")
    parser.add_argument("--profile", action="append", required=True,
                        metavar="NAME",
                        help="a profile to render; give it once per profile")
    parser.add_argument("--before", required=True, metavar="REF",
                        help="the git ref the 'before' side is read from; "
                             "'after' is the working tree")
    parser.add_argument("--out", type=Path, metavar="DIR",
                        help="where to write, a new or empty folder outside "
                             "the repository (default: a folder named by "
                             "the time in the system's temporary folder)")
    parser.add_argument("--what-if", action="store_true",
                        help="render each omitted block of a composed prompt "
                             "back in")
    parser.add_argument("--check-domain", type=Path, metavar="FILE",
                        help="JSON of old line ranges per profile and prompt: "
                             "every other old line must stand verbatim in the "
                             "new text")
    parser.add_argument("--repo", type=Path, default=ROOT, metavar="DIR",
                        help="the repository whose working tree is the "
                             "'after' side (default: the one this script "
                             "lies in)")
    return parser


def run(args) -> int:
    profiles = _profiles(args.profile)
    ranges = read_ranges(args.check_domain) if args.check_domain else None
    if ranges is not None:
        stray = sorted(set(ranges) - set(profiles))
        if stray:
            raise Refused(f"the ranges file names {', '.join(stray)}, which "
                          f"--profile did not ask for")
    root = repo_root(args.repo)
    out = choose_out(args.out, root)
    sha = resolve_ref(root, args.before)
    with tempfile.TemporaryDirectory(prefix="docpipe-render-") as scratch:
        lines, written, problems = render(args, profiles, ranges, root, sha,
                                          Path(scratch))
    for name, rows, files, labels in written:
        write_profile(out, name, rows, files, labels)
    _write(out / "summary.md", "\n".join(lines) + "\n")
    for name, rows, _files, _labels in written:
        counts = _count(rows)
        print(f"{name}: {len(rows)} prompt(s): "
              + ", ".join(f"{counts[s]} {s}" for s in ORDER))
    print(f"written to {out}")
    if problems:
        print(f"{problems} problem(s), named in summary.md", file=sys.stderr)
    return 1 if problems else 0


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == [PROBE_FLAG]:
        return _probe_main(argv[1:])
    args = _parser().parse_args(argv)
    try:
        return run(args)
    except Refused as exc:
        print(f"render_prompts: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
