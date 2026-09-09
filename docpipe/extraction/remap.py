"""
remap.py: Re-resolves a moved or grown vocabulary against a harvest already on
disk.

The resume stamp used to hold one hash over the whole spec file, so a single
new spelling of a term made all 1,082 documents stale at once, about 93 GPU
hours to re-read a corpus over one word. The ontology a spec is written against
keeps moving, so that cost would recur.

None of those hours actually re-read anything. The harvest keeps both halves of
every coordinate, the class in `<axis>` and the document's own wording in
`<axis>_raw`, so that mapping one onto the other is a pure function of the
files on disk. A new alias, a renamed label, or an option moved to another
class is answered by running that function again, with no model, no GPU, and no
index.

Four cases stop the pass from settling a coordinate, and each is counted rather
than silently dropped. No wording: the model never sent `<axis>_raw`, so there
is nothing to map from and only the stored URI survives; the coordinate stays
open for a targeted top-up. Not listed: the wording is in neither the old list
nor the new one, so the model's own reading stands rather than being
overwritten with an empty cell. A refusal: a claim refused on this axis may map
once the list has grown, but only a re-harvest can turn it into a tuple. No
parameter: a row names a parameter the spec no longer has, so the pass leaves
it untouched and does not vouch for the document.

The stamp is carried forward only for what the pass could account for. An
answer space fully re-mapped in a document, `axis/<uri>/<name>` or
`value/<uri>` for a category parameter's own list, is written forward; every
other key keeps what the stamp already said. A document whose carrier list
moved and whose carrier wordings all resolved therefore comes out current,
while one with a wording nobody listed stays stale in that one key and nothing
else.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from .fields import CHOICE, axis_slots
from .spec import Spec, fold_label, own_evidence
from .trust import document_summary

log = logging.getLogger(__name__)

# The stamp keys this pass can ever earn: an answer space is what a wording is
# mapped against. A prompt or a model is not, and neither is a question.
SPACE_PREFIXES = ("axis/", "value/")

# "axis 'carrier': 'Klaergas' not in vocabulary and axis is required"
_AXIS_REASON = re.compile(r"axis '([^']+)'")
# The refusal families a grown list could turn back into a tuple.
_MAPPABLE = ("not in vocabulary", "not in enum")


def spaces_of(current: dict) -> set:
    return {k for k in current if k.startswith(SPACE_PREFIXES)}


def _resolve(label_to_uri: dict, wording) -> Optional[str]:
    """The class this wording names in the CURRENT list, or None."""
    if not isinstance(wording, str) or not wording.strip():
        return None
    return label_to_uri.get(fold_label(wording))


def remap_row(row: dict, parameter) -> tuple:
    """Re-map one tuple's coordinates. Returns (counts, spaces left open).

    Mutates `row`. The second element names the answer spaces this row could
    not settle, so the caller knows which stamp keys it may not write forward.
    """
    counts: Counter = Counter()
    open_spaces: set = set()

    def _one(space: str, key: str, label_to_uri: dict, required: bool):
        wording = row.get(f"{key}_raw")
        current = row.get(key)
        if wording is None:
            # Nothing recorded to map from. Only a coordinate that was read
            # is a gap; an empty one has nothing to re-map and hides nothing.
            if current is not None:
                counts["no wording"] += 1
                open_spaces.add(space)
            return
        uri = _resolve(label_to_uri, wording)
        if uri is None:
            # In no list, old or new. The model's own mapping stands: it is a
            # judgement call the spec did not foresee, and replacing it with
            # an empty cell would lose a reading rather than correct one.
            counts["not listed"] += 1
            open_spaces.add(space)
            return
        if uri == current:
            counts["unchanged"] += 1
            return
        if current is None:
            counts["newly mapped"] += 1
        elif required:
            # A required axis that already carries a class. The same
            # operation, counted apart because it moves a coordinate the
            # tuple could not have been accepted without.
            counts["remapped (required)"] += 1
        else:
            counts["remapped"] += 1
        row[key] = uri
        # The flags were written about the OLD list. Both of these say "the
        # spec did not foresee this wording", which just stopped being true.
        stale = (f"unmapped:{key}:", f"mapped:{key}:")
        kept = [f for f in (row.get("flags") or []) if not f.startswith(stale)]
        if kept:
            row["flags"] = kept
        else:
            row.pop("flags", None)
        row.pop(f"{key}_raw_foreign", None)

    if parameter.vocabulary or parameter.vocabulary_dynamic:
        _one(f"value/{parameter.uri}", "value", parameter.value_to_uri(), True)
    for slot in axis_slots(parameter):
        if slot.kind != CHOICE:
            continue
        axis = parameter.axes[slot.name]
        _one(f"axis/{parameter.uri}/{slot.name}", slot.name,
             axis.label_to_uri(), axis.required)
    return counts, open_spaces


def refused_spaces(refusals: list, spaces: set) -> set:
    """Answer spaces a refusal of this document may depend on.

    A claim refused because its wording was in no vocabulary can become a
    tuple once the list grows, and only a re-harvest can do that. Marking the
    space current would hide exactly the value the new option was added for.
    A refusal that cannot be attributed unsettles everything: guessing which
    space it belonged to would be the same mistake in a smaller place.
    """
    out: set = set()
    for row in refusals:
        reason = row.get("reason") or ""
        if not any(family in reason for family in _MAPPABLE):
            continue
        match = _AXIS_REASON.search(reason)
        uri = row.get("parameter")
        key = f"axis/{uri}/{match.group(1)}" if match and uri else None
        if key in spaces:
            out.add(key)
        else:
            return set(spaces)
    return out


def stamp_forward(stamp_path: Path, current: dict, settled: set) -> bool:
    """Write the stamp keys this pass earned; keep the rest. True if it wrote.

    Everything outside `settled` stays exactly as the old stamp had it, so a
    run that comes later still sees which question it has to redo.
    """
    if not stamp_path.is_file():
        return False
    try:
        stored = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    changed = {k for k, v in current.items() if stored.get(k) != v}
    earned = changed & settled
    if not earned:
        return False
    stored.update({k: current[k] for k in earned})
    # The whole-file sha is a coarse mirror of the keys under it. It may only
    # move once nothing else it stands for is still stale, or a document would
    # read as current while a changed prompt sits unaddressed.
    if "spec" in changed and not (changed - earned - {"spec"}):
        stored["spec"] = current["spec"]
    stamp_path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    return True


def stamp_path_of(path: Path) -> Path:
    return path.parent / (path.name[: -len(".jsonl")] + ".stamp.json")


def remap_file(path: Path, spec: Spec, current: dict) -> Counter:
    """Re-map one harvest file in place, then carry its stamp forward."""
    stats: Counter = Counter()
    lines: list = []
    tuples, refusals, document_id = [], [], None
    spaces = spaces_of(current)
    settled = set(spaces)
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
            # Kept verbatim, and only a refusal counted as one: the rebuilt
            # summary's refusal count is read as a model-error rate, and a
            # parameter_state line is a fact about the run.
            if row.get("kind") == "refusal":
                refusals.append(row)
            lines.append(line)
            continue
        parameter = spec.by_uri.get(row.get("parameter"))
        if parameter is None:
            # No list to map against, so nothing this pass may touch -- and
            # nothing it may vouch for either.
            stats["unknown parameter kept"] += 1
            settled = set()
            tuples.append(row)
            lines.append(line)
            continue
        stats["tuples"] += 1
        counts, open_spaces = remap_row(row, parameter)
        stats.update(counts)
        settled -= open_spaces
        tuples.append(row)
        lines.append(json.dumps(row, ensure_ascii=False))

    blocked = refused_spaces(refusals, spaces)
    stats["refusals may now map"] += len(blocked & settled)
    settled -= blocked

    if document_id is not None:
        # The levels are computed from the coordinates this pass just moved.
        lines.append(json.dumps(
            {"kind": "summary",
             **document_summary(document_id, tuples, refusals,
                                own=own_evidence(spec))},
            ensure_ascii=False))
    tmp = Path(path).with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    if stamp_forward(stamp_path_of(Path(path)), current, settled):
        stats["stamps carried forward"] += 1
    return stats


def run(harvest_dir: Path, spec: Spec, current: dict) -> Counter:
    """Re-map a whole harvest directory against the spec as it reads today.

    `current` is the stamp this run would write, so the pass can carry the
    keys it earned forward without knowing how a stamp is assembled.
    """
    stats: Counter = Counter()
    harvest_dir = Path(harvest_dir)
    for path in sorted(harvest_dir.glob("*.jsonl")):
        if path.name.endswith(".trace.jsonl"):
            continue
        stats.update(remap_file(path, spec, current))
        stats["documents"] += 1
    for key, value in sorted(stats.items()):
        log.info("remap: %-32s %d", key, value)
    return stats
