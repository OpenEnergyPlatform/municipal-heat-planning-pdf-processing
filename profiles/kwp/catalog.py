"""
catalog.py – How heat plans present themselves in the picker.

Plans are published per municipality, sometimes as one convoy plan for several
of them; the label has to say which, and the filters are municipality,
Bundesland and year. All of that is project knowledge, so it lives here and not
in docpipe.

Author: Felix Vossel
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from docpipe.inference.catalog import Catalog, format_published

from .config import PDF_OVERRIDES, link_filename

# Filename prefixes that are not a place name (convoy plans are named after
# their lead municipality, behind one of these).
_KONVOI_DROP_PREFIX = {"waermeplan", "waermepaln", "wärmeplan", "energiekonzept", "kwp"}


class KwpCatalog(Catalog):
    """The municipal view of the corpus: who a plan covers, and where."""

    def rows(self, conn: sqlite3.Connection,
             include_superseded: bool = False) -> list:
        """
        Documents for the picker, newest/current first. Only current versions
        (is_current=1) unless include_superseded.

        Rows carry the core columns plus municipality_ags, organisation_unit,
        municipality_name and organisation_unit_name.
        """
        where = "" if include_superseded else "WHERE d.is_current = 1"
        return conn.execute(f"""
            SELECT d.id,
                   d.external_id,
                   d.group_key,
                   d.filename,
                   d.published,
                   d.num_pages,
                   d.is_current,
                   d.supersedes,
                   dm.municipality_ags,
                   dm.organisation_unit,
                   m.name AS municipality_name,
                   o.name AS organisation_unit_name
            FROM Documents d
            LEFT JOIN DocumentMeta dm     ON dm.document = d.id
            LEFT JOIN Municipalities m    ON dm.municipality_ags = m.ags
            LEFT JOIN OrganisationUnits o ON dm.organisation_unit = o.id
            {where}
            ORDER BY d.is_current DESC, d.published DESC, d.filename
        """).fetchall()

    def facet_values(self, conn: sqlite3.Connection, rows) -> dict:
        """document id -> {gemeinde, bundesland_lang, jahr}."""
        coverage = municipality_coverage(conn, rows)
        states = _states_by_document(conn)
        out = {}
        for row in rows:
            values = {"gemeinde": coverage.get(row["id"], [])}
            state = states.get(row["id"])
            if state:
                values["bundesland_lang"] = [state]
            year = str(row["published"] or "")[:4]
            if year.isdigit():
                values["jahr"] = [year]
            out[row["id"]] = values
        return out

    def label(self, row, facets: Optional[dict] = None) -> str:
        return document_label(row, (facets or {}).get("gemeinde"))

    def detail(self, row, facets: Optional[dict] = None):
        covered = (facets or {}).get("gemeinde") or []
        if len(covered) <= 1:
            return ()
        return ((f"🏘 Zugehörige Gemeinden ({len(covered)})", covered),)


CATALOG = KwpCatalog


def _states_by_document(conn: sqlite3.Connection) -> dict:
    """document id -> Bundesland, from the KWW metadata of its municipality."""
    try:
        rows = conn.execute("""
            SELECT dm.document AS document, mm.bundesland_lang AS state
            FROM DocumentMeta dm
            JOIN MunicipalityMeta mm ON mm.ags = dm.municipality_ags
            WHERE mm.bundesland_lang IS NOT NULL AND mm.bundesland_lang != ''
        """).fetchall()
    except sqlite3.OperationalError:      # corpus imported without MunicipalityMeta
        return {}
    return {r["document"]: r["state"] for r in rows}


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


def _covered_names(
    own_ags,
    own_muni_name: Optional[str],
    is_konvoi: bool,
    n_docs_in_ou: int,
    claimed_ags: set,
    ou_members: dict,
) -> list:
    """
    Municipalities a plan covers, derived from OU membership (`ou_members` maps
    ags→name).

    The fallback for a corpus whose register metadata was never imported. The
    only per-document municipality link in the schema is the single
    `municipality_ags`, so membership has to be guessed from the
    OrganisationUnit, which misses convoys spanning several units. Rule:
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


def _register_members(conn: sqlite3.Connection) -> dict:
    """file name → {ags: municipality name}, straight from the KWW register.

    Which municipalities a plan covers is not something to infer. The export
    carries one row per municipality with that municipality's plan link, and
    several rows on one link IS the convoy. Its own convoy id agrees.
    """
    try:
        rows = conn.execute("""
            SELECT m.ags AS ags, m.name AS name, mm.link_waermeplan AS link
            FROM MunicipalityMeta mm
            JOIN Municipalities m ON m.ags = mm.ags
            WHERE mm.link_waermeplan IS NOT NULL AND mm.link_waermeplan != ''
        """).fetchall()
    except sqlite3.OperationalError:      # corpus imported without the register
        return {}
    out: dict = {}
    for row in rows:
        ags = int(row["ags"])
        # Same resolution ingest used to name the file, override included.
        name = link_filename(PDF_OVERRIDES.get(ags) or row["link"])
        out.setdefault(name, {})[ags] = row["name"]
    return out


def municipality_coverage(conn: sqlite3.Connection, documents) -> dict:
    """
    Map each document id → the sorted list of municipalities it covers.

    The register decides: every municipality whose plan link resolves to this
    document's file. Only a corpus without imported register metadata falls
    back to `_covered_names`, computed over the SAME `documents` set passed in
    so sibling-plan claims match what the picker shows.
    """
    register = _register_members(conn)
    ou_members: dict = {}
    for r in conn.execute("SELECT organisation_unit, ags, name FROM Municipalities"):
        ou_members.setdefault(r["organisation_unit"], {})[r["ags"]] = r["name"]

    by_ou: dict = {}
    for d in documents:
        by_ou.setdefault(d["organisation_unit"], []).append(d)

    out: dict = {}
    for d in documents:
        members = register.get((d["filename"] or "").lower())
        if members:
            out[d["id"]] = sorted(members.values())
            continue
        siblings = by_ou.get(d["organisation_unit"], [])
        claimed = {s["municipality_ags"] for s in siblings}
        out[d["id"]] = _covered_names(
            d["municipality_ags"], d["municipality_name"],
            "konvoi" in (d["filename"] or "").lower(),
            len(siblings), claimed, ou_members.get(d["organisation_unit"], {}),
        )
    return out


def document_label(row, covered: Optional[list] = None) -> str:
    """
    Plan-centric picker label.

    `covered` = the municipalities this plan covers (from municipality_coverage).
    A plan covering several is labelled by its administrative unit + the count,
    one covering a single municipality by that municipality. If `covered` is
    omitted, falls back to the plan's own municipality_name.
    """
    filename = row["filename"] or ""
    konvoi = "konvoi" in filename.lower()
    published = format_published(row["published"])
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
