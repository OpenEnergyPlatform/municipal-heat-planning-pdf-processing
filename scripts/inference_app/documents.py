"""
documents.py – How this project labels its documents in the picker.

Heat plans are published per municipality, sometimes as one convoy plan for
several; the label has to say which. That is project knowledge, so it lives
here and not in docpipe.

Author: Felix Vossel
"""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional
from docpipe.inference.db import connect_readonly  # re-exported for the app

# Filename prefixes that are not a place name (convoy plans are named after
# their lead municipality, behind one of these).
_KONVOI_DROP_PREFIX = {"waermeplan", "waermepaln", "wärmeplan", "energiekonzept", "kwp"}


def list_documents(
    conn: sqlite3.Connection,
    include_superseded: bool = False,
) -> list[sqlite3.Row]:
    """
    Documents for the picker, newest/current first. Only current versions
    (is_current=1) unless include_superseded.

    Returns rows with keys: id, filename, published, num_pages,
    municipality_ags, organisation_unit, is_current, municipality_name,
    organisation_unit_name.
    """
    where = "" if include_superseded else "WHERE d.is_current = 1"
    sql = f"""
        SELECT d.id,
               d.filename,
               d.published,
               d.num_pages,
               dm.municipality_ags,
               dm.organisation_unit,
               d.is_current,
               m.name AS municipality_name,
               o.name AS organisation_unit_name
        FROM Documents d
        LEFT JOIN DocumentMeta dm     ON dm.document = d.id
        LEFT JOIN Municipalities m    ON dm.municipality_ags = m.ags
        LEFT JOIN OrganisationUnits o ON dm.organisation_unit = o.id
        {where}
        ORDER BY d.is_current DESC, d.published DESC, d.filename
    """
    return conn.execute(sql).fetchall()

def _konvoi_lead(filename: str) -> str:
    """
    Best-effort convoy lead name from a `*_konvoi_*` filename: the plan-type
    prefix, trailing date/quarter and "konvoi" marker are stripped, e.g.
    waermeplan_konvoi_hessigheim_20260401 → "Hessigheim". "" if nothing is left.
    """
    stem = (filename or "").rsplit(".", 1)[0]
    out = []
    for tok in re.split(r"[_\s]+", stem):
        t = tok.strip()
        tl = t.lower()
        if not t or tl in _KONVOI_DROP_PREFIX or tl == "konvoi":
            continue
        if re.fullmatch(r"\d{6,8}", t) or re.fullmatch(r"\d{4}q[1-4]", tl):
            continue  # date (20260401 / 250327) or quarter (2024q2)
        out.append(t)
    return " ".join(out).strip().title()

def _fmt_published(published) -> str:
    """Pretty-print the stored publish token: 20240708 → 2024-07-08, 2023q4 → 2023 Q4."""
    s = str(published or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    m = re.fullmatch(r"(\d{4})q([1-4])", s, re.IGNORECASE)
    if m:
        return f"{m.group(1)} Q{m.group(2)}"
    return s

def _covered_names(
    own_ags,
    own_muni_name: Optional[str],
    is_konvoi: bool,
    n_docs_in_ou: int,
    claimed_ags: set,
    ou_members: dict,
) -> list[str]:
    """
    Municipalities a plan covers, derived from OU membership (`ou_members` maps
    ags→name).

    The only per-document municipality link in the schema is the single
    `municipality_ags`; full membership lives in the OrganisationUnit. Rule:
      * OU with ONE plan → it covers ALL that OU's municipalities.
      * OU with SEVERAL plans → a standalone plan covers only its own
        municipality; a convoy plan additionally takes the OU members that no
        sibling plan claims via its own ags.
    Falls back to the plan's own municipality name if nothing resolves.
    """
    if n_docs_in_ou <= 1:
        ags_set = set(ou_members) if ou_members else set()
        if own_ags is not None:
            ags_set.add(own_ags)
    elif is_konvoi:
        ags_set = {a for a in ou_members if a not in claimed_ags}
        if own_ags is not None:
            ags_set.add(own_ags)
    else:
        ags_set = {own_ags} if own_ags is not None else set()
    names = sorted(ou_members[a] for a in ags_set if a in ou_members)
    if not names and own_muni_name:
        names = [own_muni_name]
    return names

def municipality_coverage(
    conn: sqlite3.Connection,
    documents: list[sqlite3.Row],
) -> dict[int, list[str]]:
    """
    Map each document id → the sorted list of municipalities it covers.

    Computed over the SAME `documents` set passed in, so sibling-plan claims match
    what the picker shows. The rule itself is `_covered_names`.
    """
    ou_members: dict = {}
    for r in conn.execute("SELECT organisation_unit, ags, name FROM Municipalities"):
        ou_members.setdefault(r["organisation_unit"], {})[r["ags"]] = r["name"]

    by_ou: dict = {}
    for d in documents:
        by_ou.setdefault(d["organisation_unit"], []).append(d)

    out: dict[int, list[str]] = {}
    for d in documents:
        siblings = by_ou.get(d["organisation_unit"], [])
        claimed = {s["municipality_ags"] for s in siblings}
        out[d["id"]] = _covered_names(
            d["municipality_ags"], d["municipality_name"],
            "konvoi" in (d["filename"] or "").lower(),
            len(siblings), claimed, ou_members.get(d["organisation_unit"], {}),
        )
    return out

def document_label(row: sqlite3.Row, covered: Optional[list[str]] = None) -> str:
    """
    Plan-centric picker label.

    `covered` = the municipalities this plan covers (from municipality_coverage).
    A plan covering several is labelled by its administrative unit + the count,
    one covering a single municipality by that municipality. If `covered` is
    omitted, falls back to the plan's own municipality_name.
    """
    filename = row["filename"] or ""
    konvoi = "konvoi" in filename.lower()
    published = _fmt_published(row["published"])
    tail = "(aktuell)" if row["is_current"] else "(alt)"

    if covered and len(covered) > 1:
        anchor = row["organisation_unit_name"] or _konvoi_lead(filename) or covered[0]
        parts = [str(anchor)]
        if konvoi:
            parts.append("Konvoi")
        parts.append(f"{len(covered)} Gemeinden")
    else:
        name = (covered[0] if covered else None) \
            or row["municipality_name"] or row["organisation_unit_name"] or filename
        parts = [str(name)]
        if konvoi:                       # single-member but convoy-named (rare)
            lead = _konvoi_lead(filename)
            parts.append(f"Konvoi: {lead}" if lead else "Konvoi")
    if published:
        parts.append(published)
    parts.append(tail)
    return " · ".join(parts)
