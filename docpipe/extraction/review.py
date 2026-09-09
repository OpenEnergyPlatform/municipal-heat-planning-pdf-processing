"""
review.py: Reads again, under a narrower window, the values at the lowest trust
level.

The record this pass writes is read as more than it is, so what it is comes
first: the same model, over the same document, shown a window that is a strict
subset of the one the sweep already walked, the row's own passage and the
section that passage stands in. It is a self-consistency check under a narrowed
window, not an independent second reading.

That narrowing is enough to catch the failure the lowest trust level names, a
value read off a passage belonging to another row, because the narrowed window
holds no such passage. It cannot catch the same picture misread the same way
twice. An independent second opinion would need a different model or a
different window, the page image rather than the transcription, and this pass
is neither.

An agreement between the two readings never raises the trust level; it is
recorded as a mark and nothing else. A disagreement is treated as a reason,
because two readings of the same passage that do not match is a fact about the
value.

What the pass writes is one flag per reviewed row, appended to `flags`, and one
line per reviewed row in `review.csv` beside the harvest. It adds neither a new
record kind nor a new key on a tuple: the tuple branch of the published schema
stays closed, and the second reading's own content is a curation artifact
rather than evidence.

Author: Felix Vossel
"""
from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from . import fields
from .pipeline import answer_in_quote
from .remap import stamp_path_of
from .spec import Spec, fold_label, own_evidence
from .trust import (LEVEL_C, REVIEW_AGREE, REVIEW_DISAGREE, REVIEW_UNBACKED,
                    document_summary, trust)
from .verify import quote_in, value_in_quote

log = logging.getLogger(__name__)

# Which reason names a coordinate. A whitelist and not a split on ":", because
# three of the reasons carry a colon and name nothing a question could be
# asked about -- `review:disagree` most of all, which would otherwise ask for
# a coordinate called "disagree" on every row this pass has already seen.
NAMES_AN_AXIS = ("nonlocal", "exhausted", "unbacked")

# What the second reading said, beside what a curator needs to find the value.
# Its own file: the harvest is evidence and this is a working list.
COLUMNS = ("document", "parameter", "value", "unit", "page", "owner",
           "quote", "field", "first", "second", "second_quote", "verdict")

# How much of a passage a working list carries.
CELL = 300


def _cell(text) -> str:
    flat = " ".join(str(text if text is not None else "").split())
    return flat if len(flat) <= CELL else flat[:CELL].rstrip() + " …"


def rows_to_review(tuples: list, *, own: Optional[frozenset] = None,
                   force: bool = False) -> list:
    """The values a second reading is worth spending a request on.

    The lowest level and nothing above it: a value whose passages are all
    local and whose coordinates were all read has nothing for a narrower
    window to find. And each row once -- a row already carrying a review flag
    is not asked again, because the second answer would be the second answer
    to the same question and no more.
    """
    out = []
    for row in tuples:
        if trust(row, own=own)["level"] != LEVEL_C:
            continue
        if not force and any(f.startswith("review:")
                             for f in row.get("flags") or ()):
            continue
        out.append(row)
    return out


def disputed(verdict: dict) -> list:
    """The coordinates this row's reasons actually name, in order, once each.

    A row whose reasons name none is asked for its value alone. That is the
    common case for `repaired` and `computed`, and asking such a row for all
    seven of its coordinates would spend the whole review budget re-reading
    what nothing is wrong with.
    """
    out: list = []
    for reason in verdict.get("reasons") or ():
        prefix, _, axis = str(reason).partition(":")
        if prefix in NAMES_AN_AXIS and axis and axis not in out:
            out.append(axis)
    return out


def review_fields(parameter, names) -> list:
    """The value slot plus the named coordinates, in spec order."""
    wanted = set(names or ())
    return [fields.value_slot(parameter)] + [
        slot for slot in fields.axis_slots(parameter) if slot.name in wanted]


def backed(target, answer, wording: Optional[str], quote: str,
           shown: list) -> bool:
    """Both clauses a field answer is held to, applied to a review answer.

    The quote sits verbatim in one of the two passages, AND it contains the
    answer. Written here against the same two functions the harvest uses, so
    the review's idea of evidence and the harvest's cannot drift apart.
    """
    if not quote or not any(quote_in(source.text or "", quote)
                            for source in shown):
        return False
    if isinstance(target, fields.Slot):
        return answer_in_quote(target, answer, wording, quote)
    return value_in_quote({"value": answer, "value_raw": wording or answer},
                          target, quote)


def _value_agrees(row: dict, parameter, reply: dict, shown: list) -> Optional[bool]:
    """Does the second reading's value match the number the graph carries?

    `value_target` and not `value`: the harvest converts onto the spec's own
    unit, so a second reading answering 241000 kWh/a against a stored 241
    MWh/a said the same thing in a different unit and is not a disagreement.
    """
    given = reply.get("value")
    wording = reply.get("value_raw")
    quote = reply.get("value_quote") or ""
    if given is None:
        return None
    if not backed(parameter, given, wording, quote, shown):
        return None
    if not parameter.is_numeric:
        if parameter.vocabulary:
            mapped = parameter.value_to_uri().get(fold_label(given))
            return mapped is not None and mapped == row.get("value_uri")
        return fold_label(given) == fold_label(row.get("value"))
    factor = parameter.unit_factor(reply.get("unit"))
    try:
        target = round(float(given) * float(factor), 6)
    except (TypeError, ValueError):
        # A unit the spec does not accept has no factor and a value that is
        # not a number has no product. Neither is a disagreement about the
        # number: it is an answer nothing can be compared with, and unguarded
        # it is a crash in the middle of a corpus pass.
        return None
    return target == row.get("value_target")


def _axis_agrees(row: dict, parameter, slot, reply: dict,
                 shown: list) -> Optional[bool]:
    given = reply.get(slot.name)
    wording = reply.get(f"{slot.name}_raw")
    quote = reply.get(f"{slot.name}_quote") or ""
    if given is None:
        return None
    if not backed(slot, given, wording, quote, shown):
        return None
    if slot.kind == fields.NUMBER:
        try:
            return int(given) == int(row.get(slot.name))
        except (TypeError, ValueError):
            return None
    axis = (parameter.axes or {}).get(slot.name)
    if axis is not None and axis.vocabulary:
        mapped = axis.label_to_uri().get(fold_label(given))
        return mapped is not None and mapped == row.get(slot.name)
    return fold_label(given) == fold_label(row.get(slot.name))


def agrees(row: dict, parameter, reply: dict, slots: list,
           shown: list) -> Optional[bool]:
    """True, False, or None when the second reading decided nothing.

    None is the honest third answer and not a failure: an answer whose quote
    is in neither passage, or whose quote does not carry it, or whose unit the
    spec does not accept, says nothing about the first reading.
    """
    verdicts = [_value_agrees(row, parameter, reply, shown)]
    for slot in slots:
        if slot.kind == fields.VALUE:
            continue
        verdicts.append(_axis_agrees(row, parameter, slot, reply, shown))
    if any(v is None for v in verdicts):
        return None
    return all(verdicts)


def review_row(row: dict, parameter, slots: list, shown: list,
               ask: Callable, captured: Optional[dict] = None) -> str:
    """Read one value again. Returns the flag appended, or "".

    Nothing but `flags` moves. The second reading's own value and quote are
    written to the working list, never onto the row: a harvest row is what
    one run read, and a pass that edits it in place destroys the thing the
    disagreement is a disagreement with.
    """
    reply = ask(row, shown, parameter, slots)
    if not isinstance(reply, dict):
        # Nothing happened. No flag, so the row is asked again next time.
        return ""
    if captured is not None:
        # What the second reading actually said, for the working list. Handed
        # out here rather than written onto the row: a harvest row is what one
        # run read, and a pass that edits it destroys the thing a
        # disagreement is a disagreement with.
        captured.update(reply)
    verdict = agrees(row, parameter, reply, slots, shown)
    flag = (REVIEW_UNBACKED if verdict is None
            else REVIEW_AGREE if verdict else REVIEW_DISAGREE)
    row.setdefault("flags", [])
    if flag not in row["flags"]:
        row["flags"].append(flag)
    return flag


def _working_lines(document: str, row: dict, parameter, slots: list,
                   reply: dict, flag: str) -> list:
    """One line per field asked, for the working list beside the harvest."""
    provenance = row.get("provenance") or {}
    base = {
        "document": document,
        "parameter": (row.get("parameter") or "").rsplit("/", 1)[-1],
        "value": row.get("value"),
        "unit": row.get("unit_raw") or row.get("unit") or "",
        "page": provenance.get("page"),
        "owner": f"{provenance.get('owner_kind')} "
                 f"{provenance.get('owner_id')}".strip(),
        "quote": _cell(row.get("quote")),
        "verdict": flag,
    }
    out = []
    for slot in slots:
        name = "value" if slot.kind == fields.VALUE else slot.name
        out.append({**base, "field": name,
                    "first": row.get(name),
                    "second": (reply or {}).get(name),
                    "second_quote": _cell((reply or {}).get(f"{name}_quote"))})
    return out


def review_file(path: Path, spec: Spec, *, ask: Callable,
                sources_for: Callable, own: Optional[frozenset] = None,
                limit: int = 0, working: Optional[list] = None) -> Counter:
    """Review one harvest file in place. Returns what the reading came to.

    The summary is recomputed rather than carried over: a disagreement is a
    reason, and the summary counts reasons. A carried summary would report the
    run before the review.
    """
    stats: Counter = Counter()
    lines: list = []
    tuples, refusals, document_id = [], [], None
    document = Path(path).stem
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            stats["unreadable line kept"] += 1
            lines.append(line)
            continue
        if row.get("kind") == "summary":
            document_id = row.get("document_id")
            continue
        if row.get("kind") != "tuple":
            if row.get("kind") == "refusal":
                refusals.append(row)
            lines.append(line)
            continue
        tuples.append(row)
        lines.append(row)
    for row in rows_to_review(tuples, own=own):
        if limit and stats["reviewed"] >= limit:
            break
        parameter = spec.by_uri.get(row.get("parameter"))
        if parameter is None:
            stats["unknown parameter kept"] += 1
            continue
        slots = review_fields(parameter, disputed(trust(row, own=own)))
        shown = sources_for(row) or []
        if not shown:
            stats["no passage"] += 1
            continue
        captured: dict = {}
        flag = review_row(row, parameter, slots, shown, ask, captured)
        if not flag:
            stats["no reply"] += 1
            continue
        stats["reviewed"] += 1
        stats[flag.split(":", 1)[1]] += 1
        if working is not None:
            working.extend(_working_lines(document, row, parameter, slots,
                                          captured, flag))
    out = [json.dumps(row, ensure_ascii=False) if isinstance(row, dict)
           else row for row in lines]
    if document_id is not None:
        out.append(json.dumps(
            {"kind": "summary",
             **document_summary(document_id, tuples, refusals,
                                own=own_evidence(spec))},
            ensure_ascii=False))
    tmp = Path(path).with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(path)
    return stats


def run(harvest_dir: Path, spec: Spec, *, ask: Callable,
        sources_for: Callable, documents=None, limit: int = 0,
        prompt_sha: str = "", model: str = "") -> Counter:
    """Review a whole harvest directory, or the documents named by stem.

    The stamps stay, and none is created. The review changes nothing a resume
    decides on -- values, coordinates and states are byte-identical, only
    `flags` grows -- so dropping the stamps would make the next harvest read
    the corpus again and throw the review away. Creating one where none exists
    would do the opposite and skip a document that was never harvested.

    What the review wrote goes into the stamps of the documents it READ and
    no other: a run cut short by `limit` leaves the rest without a review
    key, which is the only way a later run can tell them apart.
    """
    stats: Counter = Counter()
    harvest_dir = Path(harvest_dir)
    own = own_evidence(spec)
    working: list = []
    left = limit
    wanted = None if documents is None else set(documents)
    read: list = []
    for path in sorted(harvest_dir.glob("*.jsonl")):
        if path.name.endswith(".trace.jsonl"):
            continue
        if wanted is not None and path.stem not in wanted:
            continue
        got = review_file(path, spec, ask=ask, sources_for=sources_for,
                          own=own, limit=left, working=working)
        stats.update(got)
        stats["documents"] += 1
        read.append(path)
        if limit:
            left = limit - stats["reviewed"]
            if left <= 0:
                break
    for name, value in (("review/prompt", prompt_sha), ("review/model", model)):
        if not value:
            continue
        for path in read:
            stamp = stamp_path_of(path)
            try:
                stored = json.loads(stamp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            stored[name] = value
            stamp.write_text(json.dumps(stored, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    if working:
        out_path = harvest_dir / "review.csv"
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(working)
        stats["working list lines"] = len(working)
        log.info("review: %d line(s) -> %s", len(working), out_path)
    return stats
