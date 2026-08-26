"""Extraction stage wiring: where the ar6 spec lives, and the lists that are
only closed once a document is named.

Two of the ar6 fields have a finite set of correct answers, but the set is not
the same for every publication, so it cannot sit in the spec file:

  scenario / scenario_label  the AR6 scenarios THIS publication documents.
                             The corpus holds 1389 of them, one publication
                             documents up to 146, and the model has to pick
                             from that publication's own list.
  scenario_region            the 249 study regions the OEKG actually uses,
                             narrowed to those the document names at all.

The narrowing is not a guess. Every claim has to quote its source verbatim, and
the sources are exactly the section, table and figure texts scanned here, so a
region whose name appears nowhere in them could never have been quoted. What is
dropped is unreachable, not merely unlikely — and dropping it keeps the prompt
at the handful of countries a paper mentions instead of all 249.
"""
import json
import re
import sqlite3
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")
REGIONS_PATH = Path(__file__).with_name("regions.json")

# A label this short is a word only by accident: "US" hides inside "thus" and
# "UK" inside "Ukraine", so those are matched on word boundaries.
_SHORT = 4


def _regions() -> dict:
    return json.loads(REGIONS_PATH.read_text(encoding="utf-8"))


def _document_text(conn: sqlite3.Connection, document_id: int) -> str:
    """Everything a harvest of this document could ever quote from."""
    rows = conn.execute(
        "SELECT s.content FROM Sections s WHERE s.document = ? "
        "UNION ALL "
        "SELECT t.markdown FROM Tables t JOIN Sections s ON t.section = s.id "
        "WHERE s.document = ? "
        "UNION ALL "
        "SELECT i.description FROM Images i JOIN Sections s ON i.section = s.id "
        "WHERE s.document = ?",
        (document_id, document_id, document_id),
    ).fetchall()
    return "\n".join(str(r[0]) for r in rows if r[0])


def _mentioned(text: str, labels: list) -> bool:
    lowered = text.casefold()
    for label in labels:
        needle = label.casefold()
        if needle not in lowered:
            continue
        if len(needle) > _SHORT:
            return True
        if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", lowered):
            return True
    return False


def document_scenarios(conn: sqlite3.Connection, document_id: int) -> dict:
    """The AR6 scenarios this publication documents, as a choice list.

    Keyed by the AR6 name itself rather than an invented IRI: the name is the
    identity the corpus links against, and kg.py resolves it the same way.
    """
    rows = conn.execute(
        "SELECT sc.name FROM Scenarios sc "
        "JOIN DocumentScenarios ds ON ds.scenario = sc.id "
        "WHERE ds.document = ? ORDER BY sc.name",
        (document_id,),
    ).fetchall()
    return {str(r[0]): [str(r[0])] for r in rows if r[0]}


def document_regions(conn: sqlite3.Connection, document_id: int) -> dict:
    text = _document_text(conn, document_id)
    if not text:
        return {}
    return {iri: labels for iri, labels in _regions().items()
            if _mentioned(text, labels)}


def document_axes(conn: sqlite3.Connection, document_id: int) -> dict:
    """Per-document choice lists, keyed by axis name and by parameter uri."""
    out: dict = {}
    scenarios = document_scenarios(conn, document_id)
    if scenarios:
        out["scenario"] = scenarios          # the coordinate on other fields
        out["scenario_label"] = scenarios    # and the value of the field itself
    regions = document_regions(conn, document_id)
    if regions:
        out["scenario_region"] = regions
    return out
