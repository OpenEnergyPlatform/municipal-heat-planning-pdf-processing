#!/usr/bin/env python3
"""
change_audit.py – What this change touches that is not in the files it changes.

Every defect this repo lost a GPU run to had the same shape: the change was
correct inside the file it was written in, and wrong about something outside
it. A lock was put around the memo dicts and not the MuPDF call. A guard was
added to the carrier edge and not the sector edge. Resume stamps were deleted
to force a redo, and the code that reads them treats a missing stamp as "done"
— 165 documents skipped, the job exited 0.

None of those needed cleverness to catch. They needed someone to read the
other end. That is mechanical, so it is done here rather than remembered:

  siblings   a name this change touches that other places also use
  consumers  a literal this change writes that other files read
  untested   a function this change adds or moves that no test names

What it cannot check is the shape that needs judgement — a guarantee written
in a docstring and half implemented. "The quote sits in the source AND carries
the answer" is two clauses and was one check; no tool reads that. The rule for
it is in the procedure, not here: one clause, one assertion, and a case that
violates it by construction.

Usage:
    python scripts/change_audit.py                 # working tree against HEAD
    python scripts/change_audit.py HEAD~1..HEAD    # one commit

Author: Felix Vossel
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A name common enough that listing its other uses is noise, not a finding.
NOISE_ABOVE = 40
# Below this a name is too generic to mean anything shared.
MIN_NAME = 4

_NAME = re.compile(r"\b[a-z_][a-z0-9_]{%d,}\b" % (MIN_NAME - 1))
_STRING = re.compile(r"""["']([^"'\n]{4,80})["']""")
_DEF = re.compile(r"^\s*(?:async\s+)?def\s+([a-z_][a-z0-9_]*)")
# A line with no code punctuation in it is a docstring line.
_PROSE = re.compile(r"^\s*[A-Za-zÄÖÜäöü\"'][^=(){}\[\]:]*$")
_SKIP = re.compile(r"^(self|None|True|False|return|import|from|print|value|"
                   r"result|args|kwargs|data|path|name|line|text|file)$")


def _git(*argv) -> str:
    return subprocess.run(["git", *argv], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def changed(spec: str | None) -> tuple:
    """(files touched, lines added) for a commit range or the working tree."""
    argv = ["diff", "--unified=0"] + ([spec] if spec else ["HEAD"])
    diff = _git(*argv)
    files, added, current = [], [], None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            if current != "/dev/null":
                files.append(current)
        elif line.startswith("+") and not line.startswith("+++"):
            added.append((current, line[1:]))
    return files, added


def _hits(needle: str, written: set, literal: bool) -> list:
    """Where else this appears — every line this change did not write.

    Not "every file this change did not touch". The resume defect lived in
    runner.py and the deletion that broke it lived in recheck.py, and the same
    commit edited both: excluding whole files hid the one hit that mattered.
    A changed file is exactly where an unchanged consumer likes to sit.
    """
    argv = ["grep", "-n", "--no-color"]
    argv += ["-F"] if literal else ["-w"]
    out = _git(*argv, needle, "--", "*.py", "*.md", "*.sh", "*.json")
    rows = []
    for line in out.splitlines():
        path, _, body = line.partition(":")
        if "/__pycache__/" in path or body.partition(":")[2].strip() in written:
            continue
        rows.append(line)
    return rows


def siblings(written: set, added: list) -> dict:
    """Names this change touches that other places also use."""
    seen: set = set()
    for _path, line in added:
        # Prose, not code. A comment shares "anyone" and "predate" with half
        # the repo and none of that is a call site.
        if line.lstrip().startswith("#") or _PROSE.match(line):
            continue
        for name in _NAME.findall(line):
            if not _SKIP.match(name):
                seen.add(name)
    out: dict = {}
    for name in sorted(seen):
        rows = _hits(name, written, literal=False)
        if 0 < len(rows) <= NOISE_ABOVE:
            out[name] = rows
    return out


def consumers(written: set, added: list) -> dict:
    """Literals this change writes that other files read.

    The check that would have caught the resume defect: recheck.py deleted
    *.stamp.json, and already_done reads that name to decide whether a
    document needs work.
    """
    seen: set = set()
    for _path, line in added:
        for text in _STRING.findall(line):
            core = text.strip("*%s{}/ ").strip()
            if len(core) >= MIN_NAME and not core.startswith("http"):
                seen.add(core)
    out: dict = {}
    for text in sorted(seen):
        rows = _hits(text, written, literal=True)
        if 0 < len(rows) <= NOISE_ABOVE:
            out[text] = rows
    return out


def untested(added: list) -> list:
    """Functions this change adds that no test file names."""
    out = []
    for _path, line in added:
        match = _DEF.match(line)
        if not match:
            continue
        name = match.group(1)
        if name.startswith("_") or name.startswith("test"):
            continue
        if not _git("grep", "-l", "-w", name, "--", "tests/").strip():
            out.append(name)
    return out


def report(spec: str | None = None) -> int:
    files, added = changed(spec)
    if not files:
        print("change_audit: nothing changed")
        return 0
    written = {line.strip() for _p, line in added if line.strip()}
    print(f"change_audit: {len(files)} file(s), {len(added)} added line(s)\n")

    blocks = [
        ("CONSUMERS — a literal this change writes that other files read. "
         "Read each one before trusting what writing it means.",
         consumers(written, added)),
        ("SIBLINGS — a name this change touches that other places also use. "
         "Change every site or decide, per site, not to.",
         siblings(written, added)),
    ]
    findings = 0
    for title, table in blocks:
        if not table:
            continue
        print(title)
        for key, rows in sorted(table.items(), key=lambda kv: len(kv[1])):
            print(f"  {key}")
            for row in rows[:6]:
                print(f"      {row[:150]}")
            if len(rows) > 6:
                print(f"      ... {len(rows) - 6} more")
            findings += 1
        print()
    blank = untested(added)
    if blank:
        print("UNTESTED — added and named in no test:")
        for name in blank:
            print(f"  {name}")
        findings += len(blank)
        print()
    if not findings:
        print("nothing outside the changed files looks touched")
    return 0


if __name__ == "__main__":
    sys.exit(report(sys.argv[1] if len(sys.argv) > 1 else None))
