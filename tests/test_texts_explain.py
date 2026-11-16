"""
test_texts_explain.py: a text a person reads explains, and nothing else.

The promise, in one sentence: no text the editor shows or the published
schema carries says when or by whom something was decided or what stood
there before; each part is a test of its own, with a case that breaks it by
construction:

1. Every explanation the server sends the page of both profiles.
2. The German of the page, its keys and its words.
3. The note of each spec and every note of each drawing of the graph.
4. Every description of the published schemas.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from test_editor_i18n import server_texts

REPO = Path(__file__).resolve().parents[1]
PROFILES = ("kwp", "scenarios")

# A decision with its date, whose decision, and what stood there before.
HISTORY = re.compile(
    r"\b20\d\d-\d\d-\d\d\b|\bdecided on\b|\bentschieden am\b"
    r"|\bowner (decision|request)s?\b|Entscheidung des Eigentümers"
    r"|\bvorher stand\b|\bfrüher stand\b|\bused to be\b",
    re.IGNORECASE)


def history(texts) -> list:
    """The texts of *texts* ({text: where} or a list) that tell history."""
    pairs = texts.items() if isinstance(texts, dict) else ((t, "") for t in
                                                           texts)
    return sorted(f"{where}: {text[:160]!r}" for text, where in pairs
                  if isinstance(text, str) and HISTORY.search(text))


def strings(node, skip=("python",)) -> list:
    """Every string of a JSON value, a key named in *skip* left out."""
    if isinstance(node, dict):
        return [s for k, v in node.items() if k not in skip
                for s in strings(v, skip)]
    if isinstance(node, list):
        return [s for v in node for s in strings(v, skip)]
    return [node] if isinstance(node, str) else []


def descriptions(node) -> list:
    if isinstance(node, dict):
        own = [node["description"]] if isinstance(
            node.get("description"), str) else []
        return own + [s for v in node.values() for s in descriptions(v)]
    if isinstance(node, list):
        return [s for v in node for s in descriptions(v)]
    return []


@pytest.mark.parametrize("text", [
    "Off: it stays as it is. Decided on 2026-09-13.",
    "Where the value stands (owner decisions 2026-11-08): its passage.",
    "Vorher stand hier je Klasse ein eigener Parameter.",
    "Standard: Ihre Entscheidung vom 2026-11-12",
    "What happens when it is off was decided on 2026-11-12.",
])
def test_a_text_telling_history_is_found(text):
    assert history([text])


@pytest.mark.parametrize("text", [
    "A span such as \"2030-2045\" is read for every year of it.",
    "A date such as \"31.12.2022\" backs the year 2022.",
    "A stamp written before those keys existed carries none of them.",
    "Which entry the document's wording means is decided by the model.",
])
def test_an_explanation_is_left_alone(text):
    assert not history([text])


def test_the_server_explains_and_tells_no_history():
    said = history(server_texts())
    assert not said, "history in the page:\n" + "\n".join(said)


def test_the_german_of_the_page_tells_no_history():
    path = REPO / "docpipe/editor/ui/src/i18n/de.json"
    words = json.loads(path.read_text(encoding="utf-8"))
    said = history({**{k: "key" for k in words},
                    **{v: k[:40] for k, v in words.items()}})
    assert not said, "history in de.json:\n" + "\n".join(said)


@pytest.mark.parametrize("profile", PROFILES)
def test_the_notes_of_the_spec_and_the_graph_tell_no_history(profile):
    folder = REPO / "profiles" / profile
    spec = json.loads((folder / "extraction_spec.json").read_text(
        encoding="utf-8"))
    note = spec.get("_comment") or []
    graph = json.loads((folder / "graph.json").read_text(encoding="utf-8"))
    said = history([" ".join(note) if isinstance(note, list) else note]
                   + strings(graph))
    assert not said, "\n".join(said)


@pytest.mark.parametrize("profile", PROFILES)
def test_the_published_schema_tells_no_history(profile):
    schema = json.loads((REPO / "profiles" / profile
                         / "extraction_schema.json").read_text(
                             encoding="utf-8"))
    said = history(descriptions(schema))
    assert not said, "\n".join(said)
