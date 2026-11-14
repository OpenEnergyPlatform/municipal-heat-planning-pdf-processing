"""The page `docpipe edit` serves is the build of its sources
(scripts/build_editor_page.py).

1. The committed page names, in web/BUILT_FROM, the fingerprint of every
   file the build reads as they stand.
2. The fingerprint changes with the content and the name of any file the
   build reads, and not with the line endings of a checkout.
3. The build holds the Node on the path to the versions package.json names.

Broken by construction: a source with one byte more, a file added, a Node
older than the sources need.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_editor_page as page  # noqa: E402

SOURCES = {"index.html": b"<div id=\"root\"></div>\n",
           "package.json": b"{}\n",
           "src/App.tsx": b"export const App = () => null;\n"}


@pytest.mark.skipif(not (page.UI / "src").is_dir(),
                    reason="a tree without the page's sources")
def test_the_committed_page_is_the_build_of_its_sources():
    assert page.stamped() is not None, "web/BUILT_FROM is missing"
    assert page.current(), ("docpipe/editor/web is not the build of "
                            "docpipe/editor/ui: python "
                            "scripts/build_editor_page.py")


def test_the_fingerprint_follows_every_file_the_build_reads():
    first = page.fingerprint(SOURCES)
    assert page.fingerprint(dict(SOURCES)) == first
    changed = dict(SOURCES, **{"src/App.tsx": SOURCES["src/App.tsx"] + b" "})
    assert page.fingerprint(changed) != first
    added = dict(SOURCES, **{"src/lib/x.ts": b"export {};\n"})
    assert page.fingerprint(added) != first
    moved = {("src/Other.tsx" if name == "src/App.tsx" else name): body
             for name, body in SOURCES.items()}
    assert page.fingerprint(moved) != first


def test_the_fingerprint_does_not_follow_line_endings():
    crlf = {name: body.replace(b"\n", b"\r\n")
            for name, body in SOURCES.items()}
    assert page.fingerprint(crlf) == page.fingerprint(SOURCES)


@pytest.mark.parametrize("found, fits", [
    ("v20.19.0\n", True), ("v20.25.1", True), ("v22.12.0", True),
    ("v25.5.0", True), ("v20.18.3", False), ("v21.7.0", False),
    ("v22.11.9", False), ("v18.20.0", False)])
def test_the_node_on_the_path_is_held_to_the_engines(found, fits):
    problem = page.node_problem("^20.19.0 || >=22.12.0", found)
    assert (problem is None) == fits, problem
