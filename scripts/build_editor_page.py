"""
build_editor_page.py: The page of `docpipe edit`, built from its sources.

    python scripts/build_editor_page.py [--install] [--check]

The sources of the page are docpipe/editor/ui; what the editor serves is
docpipe/editor/web, committed so that running `docpipe edit` needs no Node.
This script is the one way from the first to the second:

1. the Node on the path is held to the versions the sources name
   (`engines` of package.json);
2. the libraries are installed from package-lock.json (`npm ci`) where
   node_modules is missing, or where --install asks for it; a node_modules
   that is a link to another checkout is used as it is;
3. `npm run build` checks the types and builds into web/;
4. web/index.html is written in LF: Vite copies the line endings of the
   checked-out ui/index.html and adds its own lines in LF, and a file of
   mixed endings is one git does not normalise;
5. the fingerprint of the sources is written into web/BUILT_FROM.

--check builds nothing: it says whether web/BUILT_FROM is the fingerprint
of the sources as they stand, and exits 1 where it is not, so a change of
the sources that was not built shows in a test and in
`scripts/change_audit.py`.

The fingerprint is a SHA-256 over every file the build reads, path by path,
each with its line endings as LF, so a checkout on Windows and one on Linux
agree.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "docpipe" / "editor" / "ui"
WEB = ROOT / "docpipe" / "editor" / "web"
STAMP = "BUILT_FROM"
# What the build reads besides src/: the page's frame, the libraries and
# their versions, the build's and the type check's settings.
FILES = ("index.html", "package.json", "package-lock.json", "vite.config.ts",
         "tsconfig.json")
SOURCES = "src"


def sources(ui: Path = UI) -> dict:
    """{path below ui/, with /: bytes} of every file the build reads."""
    out = {}
    for name in FILES:
        path = ui / name
        if path.is_file():
            out[name] = path.read_bytes()
    for path in sorted((ui / SOURCES).rglob("*")):
        if path.is_file():
            out[path.relative_to(ui).as_posix()] = path.read_bytes()
    return out


def fingerprint(files: dict) -> str:
    """The fingerprint of *files* ({path: bytes}): the same for the same
    paths and contents, whatever the line endings of the checkout."""
    digest = hashlib.sha256()
    for path in sorted(files):
        body = files[path].replace(b"\r\n", b"\n")
        digest.update(path.encode("utf-8") + b"\0")
        digest.update(str(len(body)).encode("ascii") + b"\0")
        digest.update(body)
    return "sha256:" + digest.hexdigest()


def stamped(web: Path = WEB) -> Optional[str]:
    """The fingerprint web/BUILT_FROM names, None where there is none."""
    path = web / STAMP
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def current(ui: Path = UI, web: Path = WEB) -> bool:
    """Is the built page the build of the sources as they stand?"""
    return stamped(web) == fingerprint(sources(ui))


def as_lf(path: Path) -> None:
    """*path* rewritten with LF line endings only."""
    raw = path.read_bytes()
    fixed = raw.replace(b"\r\n", b"\n")
    if fixed != raw:
        path.write_bytes(fixed)


def _version(text: str) -> tuple:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def node_problem(wanted: str, found: str) -> Optional[str]:
    """Why the Node *found* (`node --version`) does not meet *wanted* (the
    `engines` entry, alternatives joined by ||, each `>=X.Y.Z` or `^X.Y.Z`),
    None where it does."""
    have = _version(found)
    for alternative in wanted.split("||"):
        alternative = alternative.strip()
        low = _version(alternative)
        if not low:
            continue
        if alternative.startswith("^"):
            if have[:1] == low[:1] and have >= low:
                return None
        elif have >= low:
            return None
    return f"Node {found.strip()} does not meet {wanted!r} (package.json)"


def is_link(path: Path) -> bool:
    """Is *path* a link to a folder elsewhere (a symbolic link, or a
    junction on Windows, which `Path.is_symlink` does not see)?"""
    return path.is_symlink() or path.resolve() != path.absolute()


def _run(command: list, cwd: Path) -> None:
    done = subprocess.run(command, cwd=cwd)
    if done.returncode != 0:
        raise SystemExit(f"{' '.join(command)} failed "
                         f"(exit {done.returncode}); the page was not built")


def build(install: bool = False, ui: Path = UI, web: Path = WEB) -> str:
    """Build the page; its fingerprint."""
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        raise SystemExit("building the page needs Node and npm on the path "
                         "(running `docpipe edit` does not)")
    wanted = (json.loads((ui / "package.json").read_text(encoding="utf-8"))
              .get("engines") or {}).get("node")
    found = subprocess.run([node, "--version"], capture_output=True,
                           text=True).stdout
    if wanted:
        problem = node_problem(wanted, found)
        if problem:
            raise SystemExit(problem)
    modules = ui / "node_modules"
    if install and modules.exists() and is_link(modules):
        # npm would replace the link by a whole new tree in this checkout
        raise SystemExit(f"{modules} is a link to {modules.resolve()}: "
                         f"install there, not here; nothing was built")
    if install or not modules.exists():
        _run([npm, "ci"], ui)
    _run([npm, "run", "build"], ui)
    as_lf(web / "index.html")
    said = fingerprint(sources(ui))
    (web / STAMP).write_text(said + "\n", encoding="utf-8", newline="\n")
    return said


def main(argv=None) -> int:
    made = argparse.ArgumentParser(
        prog="build_editor_page.py",
        description="Build the page of `docpipe edit` from "
                    "docpipe/editor/ui into docpipe/editor/web.")
    made.add_argument("--install", action="store_true",
                      help="install the libraries from package-lock.json "
                           "(npm ci) even where node_modules exists")
    made.add_argument("--check", action="store_true",
                      help="build nothing; exit 1 where the built page is "
                           "not the build of the sources as they stand")
    args = made.parse_args(argv)
    if args.check:
        if current():
            print("the built page is the build of its sources")
            return 0
        print("docpipe/editor/web is not the build of docpipe/editor/ui: "
              "run python scripts/build_editor_page.py and commit "
              "docpipe/editor/web with the change")
        return 1
    print(f"built: {build(install=args.install)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
