"""
evaluate.py: Holds a harvest against what people decided about it.

    docpipe evaluate HARVEST_DIR --gold gold.jsonl
    docpipe evaluate HARVEST_DIR --gold gold.jsonl --baseline OTHER_DIR
    docpipe evaluate HARVEST_DIR --gold gold.jsonl --min-precision 0.9

Precision is counted field by field over the rows somebody decided
(`gold.py`): of the values, units and coordinates a person looked at, how
many does the document say. Recall is counted only over the documents
somebody read whole for a parameter: of the values the document states,
how many does the harvest carry.

Every share comes with its 95 percent interval (Wilson). Forty decided
rows with two wrong are 95 percent, and anything between 84 and 99: a
change that moves precision inside that range has shown nothing, and the
interval is what says so. What nobody decided is counted as undecided and
is in no share.

The numbers are split by parameter, by the level the harvest gave a value
(`trust.py`) and by where it was read (text, table or figure), because
those are the splits a decision hangs on: whether level C may be left out
of a graph is a question about the precision of level C.

`--baseline` holds a second harvest of the same documents beside this one,
row by row: which rows both carry, which only one does, and what was
decided about those. That is the comparison a replayed run is made for.

Nothing here writes into a harvest or decides anything about a value.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional, Sequence

from ..profile import add_profile_argument, program, resolve_profile
from . import gold as golden
from . import trust

Z95 = 1.959963984540054


def wilson(hits: int, total: int, z: float = Z95) -> Optional[tuple]:
    """The interval the true share lies in, given *hits* of *total*."""
    if total <= 0:
        return None
    share = hits / total
    spread = z * z / total
    middle = share + spread / 2
    width = z * math.sqrt(share * (1 - share) / total
                          + spread / (4 * total))
    # The two ends are exact, not a rounding away from them.
    low = 0.0 if hits == 0 else max(0.0, (middle - width) / (1 + spread))
    high = 1.0 if hits == total else min(1.0, (middle + width) / (1 + spread))
    return low, high


class Count:
    """How many of something were decided correct, wrong, or not at all."""

    __slots__ = ("correct", "wrong", "undecided")

    def __init__(self):
        self.correct = self.wrong = self.undecided = 0

    def add(self, verdict: Optional[str]) -> None:
        if verdict == golden.CORRECT:
            self.correct += 1
        elif verdict == golden.WRONG:
            self.wrong += 1
        else:
            self.undecided += 1

    @property
    def decided(self) -> int:
        return self.correct + self.wrong

    @property
    def share(self) -> Optional[float]:
        return self.correct / self.decided if self.decided else None

    def as_dict(self) -> dict:
        interval = wilson(self.correct, self.decided)
        return {"correct": self.correct, "wrong": self.wrong,
                "undecided": self.undecided, "precision": self.share,
                "interval": list(interval) if interval else None}


def row_verdict(verdicts: dict) -> Optional[str]:
    """One row from its fields: wrong as soon as one field is, correct
    once every field was decided and none is wrong."""
    said = list(verdicts.values())
    if golden.WRONG in said:
        return golden.WRONG
    if said and all(verdict == golden.CORRECT for verdict in said):
        return golden.CORRECT
    return None


def _counts(table: dict, key) -> Count:
    if key not in table:
        table[key] = Count()
    return table[key]


def evaluate(rows_by_document: dict, gold: golden.Gold, *,
             transcribed: Sequence[str] = ()) -> dict:
    """The report of one harvest. *transcribed* names the documents whose
    pages a model transcribed: their values are level B at best."""
    fields: dict = {}
    parameters: dict = {}
    levels: dict = {}
    tiers: dict = {}
    rows_total = Count()
    recall: dict = {}

    for document, rows in sorted(rows_by_document.items()):
        covered: set = set()
        stated: set = set()         # what a found row says, each said once
        for row in rows:
            name = row.get("parameter")
            entry = parameters.setdefault(name, {
                "rows": Count(), "fields": {}})
            verdicts = {field: gold.verdict(document, row, field, rows)
                        for field in golden.fields_of(row)}
            for field, verdict in verdicts.items():
                _counts(fields, field).add(verdict)
                _counts(entry["fields"], field).add(verdict)
            whole = row_verdict(verdicts)
            entry["rows"].add(whole)
            rows_total.add(whole)
            level = trust.trust(
                row, transcribed=document in transcribed)["level"]
            _counts(levels, level).add(whole)
            _counts(tiers, row.get("tier")).add(whole)

            if not gold.is_checked(document, name):
                continue
            tally = recall.setdefault(name, {
                "documents": set(), "found": 0, "missed": 0,
                "undecided": 0})
            tally["documents"].add(document)
            facts = gold.missing_for(document, name)
            hit = [index for index, fact in enumerate(facts)
                   if golden.covers(fact, row)]
            # The whole row, as precision counts it: the right number
            # under the wrong year is not the value the document states.
            if whole == golden.WRONG:
                continue                # carried, and not what is stated
            if whole == golden.CORRECT or hit:
                # The document states a value once however often the
                # harvest read it: a second row that says the same thing
                # for the same coordinates is the same found value.
                said = (name, json.dumps(
                    [row.get(field) for field in golden.fields_of(row)],
                    sort_keys=True, default=str))
                if said not in stated:
                    stated.add(said)
                    tally["found"] += 1
                covered.update((name, index) for index in hit)
            else:
                tally["undecided"] += 1

        # What the document states and no row carries. Also for a
        # parameter the harvest has no row of at all in this document.
        for name in {fact["parameter"]
                     for fact in gold.missing if fact["document"] == document}:
            if not gold.is_checked(document, name):
                continue
            tally = recall.setdefault(name, {
                "documents": set(), "found": 0, "missed": 0,
                "undecided": 0})
            tally["documents"].add(document)
            tally["missed"] += sum(
                1 for index, _fact in enumerate(
                    gold.missing_for(document, name))
                if (name, index) not in covered)
    # A document read whole in which the harvest carries nothing and
    # nothing is missing still counts as read.
    for document, marks in gold.checked.items():
        if document not in rows_by_document:
            continue
        for name in marks:
            if name is not None and name not in recall:
                recall[name] = {"documents": {document}, "found": 0,
                                "missed": 0, "undecided": 0}
            elif name is not None:
                recall[name]["documents"].add(document)

    def recalled(tally: dict) -> dict:
        stated = tally["found"] + tally["missed"]
        interval = wilson(tally["found"], stated)
        return {"documents": len(tally["documents"]),
                "found": tally["found"], "missed": tally["missed"],
                "undecided": tally["undecided"],
                "recall": tally["found"] / stated if stated else None,
                "interval": list(interval) if interval else None}

    overall = {"documents": set(), "found": 0, "missed": 0, "undecided": 0}
    for tally in recall.values():
        overall["documents"] |= tally["documents"]
        for key in ("found", "missed", "undecided"):
            overall[key] += tally[key]

    return {
        "documents": len(rows_by_document),
        "rows": rows_total.as_dict(),
        "fields": {name: count.as_dict()
                   for name, count in sorted(fields.items())},
        "levels": {name: count.as_dict()
                   for name, count in sorted(levels.items())},
        "tiers": {str(name): count.as_dict() for name, count in sorted(
            tiers.items(), key=lambda item: str(item[0]))},
        "parameters": {
            str(name): {
                "rows": entry["rows"].as_dict(),
                "fields": {field: count.as_dict() for field, count
                           in sorted(entry["fields"].items())},
                "recall": recalled(recall[name]) if name in recall else None}
            for name, entry in sorted(parameters.items(),
                                      key=lambda item: str(item[0]))},
        "recall": recalled(overall),
        "recall_by_parameter": {str(name): recalled(tally) for name, tally
                                in sorted(recall.items(),
                                          key=lambda item: str(item[0]))},
    }


def compare(rows_by_document: dict, baseline: dict,
            gold: golden.Gold) -> dict:
    """This harvest beside another of the same documents, row by row.

    A row is the same row when its document, its name and its parameter
    are. Where several rows of a document share a name, those that read
    the same in every field are paired first, and what is left on both
    sides is a row read differently. What only one harvest carries is
    counted with what was decided about its value: a row that was correct
    and is gone is a loss, one that was wrong and is gone is not.
    """
    def named(harvest: dict) -> dict:
        found: dict = {}
        for document, rows in harvest.items():
            for row in rows:
                found.setdefault(golden.row_key(document, row),
                                 []).append(row)
        return found

    def reads_the_same(left: dict, right: dict) -> bool:
        return golden.same(left.get(golden.VALUE),
                           right.get(golden.VALUE)) \
            and golden.same_signature(golden.signature(left),
                                      golden.signature(right))

    now, before = named(rows_by_document), named(baseline)
    gained, lost, kept, changed = Count(), Count(), 0, 0
    for key in sorted(set(now) | set(before), key=str):
        mine, theirs = list(now.get(key, ())), list(before.get(key, ()))
        for row in list(mine):
            twin = next((index for index, other in enumerate(theirs)
                         if reads_the_same(row, other)), None)
            if twin is not None:
                del theirs[twin]
                del mine[next(index for index, own in enumerate(mine)
                              if own is row)]
                kept += 1
        paired = min(len(mine), len(theirs))
        kept += paired
        changed += paired
        for row in mine[paired:]:
            gained.add(gold.verdict(key[0], row, golden.VALUE,
                                    rows_by_document.get(key[0])))
        for row in theirs[paired:]:
            lost.add(gold.verdict(key[0], row, golden.VALUE,
                                  baseline.get(key[0])))
    return {"kept": kept, "changed": changed,
            "gained": gained.as_dict(), "lost": lost.as_dict()}


# ---------------------------------------------------------------- the command

def _share(entry: dict, key: str = "precision") -> str:
    share = entry.get(key)
    if share is None:
        return "    -          "
    low, high = entry["interval"]
    return f"{share:6.1%} [{low:4.0%},{high:5.0%}]"


def render(report: dict, comparison: Optional[dict] = None) -> str:
    lines = [f"{report['documents']} document(s)"]

    def line(label: str, entry: dict) -> str:
        return (f"  {label:<44.44} {_share(entry)}  "
                f"{entry['correct']:>5} correct {entry['wrong']:>5} wrong "
                f"{entry['undecided']:>6} undecided")

    lines += ["", "precision, whole rows", line("all", report["rows"])]
    for title, key in (("by level", "levels"), ("by origin", "tiers"),
                       ("by field", "fields")):
        lines += ["", f"precision {title}"]
        lines += [line(name, entry) for name, entry in report[key].items()]
    lines += ["", "precision by parameter (whole rows)"]
    lines += [line(name, entry["rows"])
              for name, entry in report["parameters"].items()]

    lines += ["", "recall, over the documents read whole"]
    overall = report["recall"]
    if not overall["documents"]:
        lines.append("  no document is marked as read whole: nothing is "
                     "known about what the harvest lacks")
    else:
        def recall_line(label: str, entry: dict) -> str:
            return (f"  {label:<44.44} {_share(entry, 'recall')}  "
                    f"{entry['found']:>5} found {entry['missed']:>5} missed "
                    f"in {entry['documents']} document(s)")
        lines.append(recall_line("all", overall))
        lines += [recall_line(name, entry) for name, entry
                  in report["recall_by_parameter"].items()]

    if comparison is not None:
        gained, lost = comparison["gained"], comparison["lost"]
        lines += ["", "against the baseline",
                  f"  {comparison['kept']} row(s) in both, "
                  f"{comparison['changed']} of them with another content",
                  f"  gained {gained['correct'] + gained['wrong'] + gained['undecided']}: "
                  f"{gained['correct']} correct, {gained['wrong']} wrong, "
                  f"{gained['undecided']} undecided",
                  f"  lost   {lost['correct'] + lost['wrong'] + lost['undecided']}: "
                  f"{lost['correct']} correct, {lost['wrong']} wrong, "
                  f"{lost['undecided']} undecided"]
    return "\n".join(lines)


def below(report: dict, min_precision: Optional[float],
          min_recall: Optional[float]) -> list:
    """What the report falls short of. A share nobody can count (nothing
    decided, nothing read whole) falls short of a floor that was asked
    for: a floor that passes on no evidence is not one."""
    short = []
    if min_precision is not None:
        got = report["rows"]["precision"]
        if got is None or got < min_precision:
            short.append(f"precision is "
                         f"{'not known' if got is None else format(got, '.3f')}"
                         f", the floor is {min_precision}")
    if min_recall is not None:
        got = report["recall"]["recall"]
        if got is None or got < min_recall:
            short.append(f"recall is "
                         f"{'not known' if got is None else format(got, '.3f')}"
                         f", the floor is {min_recall}")
    return short


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.extraction.evaluate"),
        description="Precision and recall of a harvest, counted against "
                    "the decisions people made about it.")
    add_profile_argument(parser)
    parser.add_argument("harvest", type=Path, help="harvest directory")
    parser.add_argument("--gold", type=Path,
                        help=f"decisions file (default: {golden.FILE_NAME} "
                             f"beside the harvest directory)")
    parser.add_argument("--baseline", type=Path,
                        help="another harvest of the same documents to "
                             "hold this one against")
    parser.add_argument("--db", type=Path,
                        help="corpus database, for the documents whose "
                             "pages were transcribed (default: the "
                             "profile's, when it is there)")
    parser.add_argument("--json", type=Path, dest="json_out",
                        help="also write the report as JSON")
    parser.add_argument("--min-precision", type=float,
                        help="exit with 1 when the precision of whole rows "
                             "is below this share")
    parser.add_argument("--min-recall", type=float,
                        help="exit with 1 when recall is below this share")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    profile = resolve_profile(args)
    harvest_dir = Path(args.harvest)
    if not harvest_dir.is_dir():
        raise SystemExit(f"{harvest_dir} is not a directory")
    # resolve(): "." has no name to stand beside, and ".." has its own.
    gold_path = args.gold or harvest_dir.resolve().with_name(
        golden.FILE_NAME)
    if not Path(gold_path).is_file():
        raise SystemExit(
            f"{gold_path} is not a file: without decisions there is "
            f"nothing to count a harvest against. The review page of the "
            f"chat app writes them.")
    db = args.db
    if db is None and profile is not None and Path(profile.db_path).is_file():
        db = Path(profile.db_path)

    rows = golden.harvest(harvest_dir)
    gold = golden.Gold.load(gold_path)
    report = evaluate(rows, gold, transcribed=trust.transcribed_documents(db))
    comparison = None
    if args.baseline:
        if not args.baseline.is_dir():
            raise SystemExit(f"{args.baseline} is not a directory")
        comparison = compare(rows, golden.harvest(args.baseline), gold)
        report["baseline"] = comparison
    print(render(report, comparison))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    short = below(report, args.min_precision, args.min_recall)
    for line in short:
        print(line, file=sys.stderr)
    return 1 if short else 0


if __name__ == "__main__":
    from docpipe.profile import bind_command_line
    bind_command_line()
    sys.exit(main())
