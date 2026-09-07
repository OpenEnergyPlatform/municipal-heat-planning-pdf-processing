"""
trust.py – How much of a value the run can actually stand behind.

Every accepted tuple is verified: its number is in its quote, its quote is in
a shown source, every coordinate names the passage it was read in. That is a
floor, not a grade. Two values that both clear it can still differ by a lot:

  one has every coordinate read off its own table, in the plan's own text
  one has its year read off the caption of a different table three pages away

The second is the failure this whole repair is about, and until now nothing
downstream could tell the two apart. A reader of the graph saw two numbers.

So: a deterministic level per value, computed from what the harvest already
records. No model, no second opinion, no threshold anybody tuned.

  A  the plan's own text says it, every coordinate read, every passage local
  B  the same, but read out of a table transcription or a figure description
     -- which is a model's reading of a picture -- or out of a plan whose
     pages had no text layer at all and were transcribed page by page
  C  something is off: a passage that belongs to another row, a coordinate
     the run gave up on, a repaired quote, a computed number, a contested
     identity

The reasons are a closed list, because a reason nobody can enumerate is a
reason nobody can count. What makes a C is what a curator should look at.

Measured on Kassel's 559 tuples, which is why the levels are cut here and not
somewhere else: 527 of 559 came out of a table or figure image, so image
origin alone separates nothing and is not a warning. What does separate: 370
of 455 year readings cited a passage outside the row's own table and its
section, 87 percent of the area readings, 47 percent of the scenarios, 49
percent of the sectors -- and 13 percent of the carriers, which is the one
coordinate the row itself really carries.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from .fields import EXHAUSTED, READ, UNBACKED
from .verify import TIER_TEXT

LEVEL_A = "A"
LEVEL_B = "B"
LEVEL_C = "C"

# Flags that say something about how the value itself was arrived at. Each is
# a reason on its own, and each is a different thing for a curator to check.
FLAG_REASONS = {"quote_repaired": "repaired", "computed": "computed",
                "not_located": "not_located"}


def _owners(row: dict) -> set:
    """The sources a coordinate of THIS row may have been read in.

    Its own table or section, and the section that table stands in. The same
    pair `pipeline.evidence_is_local` enforces for an axis with evidence
    "own" -- read here from what the harvest wrote down, because by the time
    a graph is built the window is long gone.
    """
    provenance = row.get("provenance") or {}
    out = set()
    kind, owner = provenance.get("owner_kind"), provenance.get("owner_id")
    if kind and owner is not None:
        out.add((kind, owner))
    parent = provenance.get("parent_section")
    if parent is not None:
        out.add(("section", parent))
    return out


def reasons(row: dict, *, conflict: bool = False,
            transcribed: bool = False) -> list:
    """Every reason this value is not an A, in a fixed order.

    Empty means nothing is wrong with it that the harvest can see.
    """
    found: list = []
    local = _owners(row)
    for key in sorted(row):
        if not key.endswith("_state"):
            continue
        name = key[:-len("_state")]
        state = row[key]
        if state in (EXHAUSTED, UNBACKED):
            found.append(f"{state}:{name}")
            continue
        if state != READ:
            # Derived, "the plan does not say it", never asked because the
            # row left at the gate: none of those is a doubt about the
            # reading. They are findings about the plan or about this run's
            # scope, and they are recorded as such elsewhere.
            continue
        source = row.get(f"{name}_source")
        if local and source and tuple(source) not in local:
            found.append(f"nonlocal:{name}")
    for flag in row.get("flags") or []:
        reason = FLAG_REASONS.get(flag)
        if reason and reason not in found:
            found.append(reason)
    if conflict:
        found.append("conflict")
    if transcribed:
        # Not a doubt about the reading, a doubt about the page it was read
        # from: this plan had no text layer and a model transcribed it, so
        # the section text is itself a reading. Its own reason, because it
        # caps the level rather than condemning the value.
        found.append("page_transcribed")
    return found


def trust(row: dict, *, conflict: bool = False, transcribed: bool = False,
          corroborated: bool = False) -> dict:
    """{level, reasons, image_origin, corroborated} for one accepted tuple."""
    why = reasons(row, conflict=conflict, transcribed=transcribed)
    hard = [r for r in why if r != "page_transcribed"]
    image = row.get("tier") != TIER_TEXT
    if hard:
        level = LEVEL_C
    elif image or transcribed:
        level = LEVEL_B
    else:
        level = LEVEL_A
    return {"level": level, "reasons": why, "image_origin": image,
            "corroborated": bool(corroborated)}


def sentence(verdict: dict, row: Optional[dict] = None) -> str:
    """One line a reader of the graph can act on."""
    parts = [f"Vertrauen: {verdict['level']}"]
    if verdict.get("image_origin"):
        provenance = (row or {}).get("provenance") or {}
        image = provenance.get("image")
        parts.append("aus einem Bild" + (f" ({image})" if image else ""))
    if verdict.get("corroborated"):
        parts.append("zweite Quelle bestätigt")
    if verdict["reasons"]:
        parts.append(", ".join(verdict["reasons"]))
    if verdict["level"] == LEVEL_C:
        parts.append("Prüfung empfohlen")
    return " · ".join(parts)
