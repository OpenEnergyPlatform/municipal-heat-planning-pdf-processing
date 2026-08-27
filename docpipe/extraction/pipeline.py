"""
pipeline.py – The harvest loop: sweep, dedup, verify, write.

Per document and parameter, the spec-generated queries probe retrieval in
rounds; every round excludes what earlier rounds saw, and the loop stops when
a full pass over the queries surfaces nothing new (bounded, because a stop
heuristic without a bound is an outage). Each surfaced owner — a section, a
table, a figure — is harvested exactly ONCE per parameter, however many
queries found it: that single rule is the whole dedup story for
query-overlap. Every claimed tuple then passes verify_tuple; refusals are
kept alongside the accepted, because a harvest that cannot say what it threw
away reads as complete when it is not.

The three expensive dependencies — retrieval, the harvesting LLM call, and
locating a quote on its PDF page — are injected callables. The loop's
correctness is a pure-code property and is tested without a GPU; the wiring
to the live inference stack lives with the CLI, not here.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import queries as queries_mod
from .spec import Spec
from .verify import Refusal, Verified, verify_tuple

log = logging.getLogger(__name__)

MAX_SWEEP_ROUNDS = 4


@dataclass
class Source:
    """One retrieval owner as the harvest needs it."""
    owner_kind: str                       # "section" | "table" | "figure"
    owner_id: int
    text: str                             # what the model will read
    provenance: dict = field(default_factory=dict)
    image_path: Optional[str] = None      # the crop, for tables and figures


@dataclass
class WorkItem:
    """One harvest request: read THIS source for THAT parameter."""
    document_id: int
    parameter: object
    source: Source


@dataclass
class DocumentReport:
    document_id: int
    tuples: list = field(default_factory=list)
    refusals: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    owners_harvested: int = 0
    sweep_rounds: dict = field(default_factory=dict)   # parameter uri -> rounds
    # parameter uri -> {"candidates": n, "leftover": m}. The running quality
    # metric of the retrieval sweep: how much of the deterministic candidate
    # set retrieval never surfaced. A growing leftover means the probes (or
    # the vocabularies they expand from) have a blind spot.
    fallback: dict = field(default_factory=dict)


def plan_document(
    document_id: int,
    spec: Spec,
    templates: list,
    *,
    extra_probes: Optional[dict] = None,
    retrieve: Callable,                   # (probes, document_id, exclude) -> [[Source]]
    candidates: Optional[Callable] = None,  # (document_id, Parameter) -> [Source]
    max_rounds: int = MAX_SWEEP_ROUNDS,
) -> tuple:
    """(work items, report skeleton) — the retrieval half, no model involved.

    The sweep's `seen` set is fed by retrieval alone: no round has ever
    depended on what the harvest replied. So the whole plan, for the whole
    corpus, can be built before the first request goes out — which is the
    point. One request at a time keeps a 4-GPU server idle; the batch path
    plans every document first and then hands vLLM thousands of requests to
    schedule at once.
    """
    report = DocumentReport(document_id=document_id)
    items: list = []
    for parameter in spec.parameters:
        probes = queries_mod.expand(templates, parameter)
        # The anchors the model wrote from this parameter's ontology
        # definition, beside the spec's own templates. A template says what to
        # look for; an anchor says how the sentence would READ in a plan, which
        # is what a similarity search actually matches against.
        probes += [p for p in (extra_probes or {}).get(parameter.uri, ())
                   if p and p not in probes]
        seen: set = set()
        rounds = 0
        while rounds < max_rounds:
            rounds += 1
            new_sources: list = []
            # Every probe of the round in one call: retrieval builds the
            # document's sub-index once and searches the probes as one matrix.
            # It grows the excluded set from probe to probe itself, which is
            # what the loop used to do by handing each probe a fresh snapshot.
            for sources in retrieve(probes, document_id, set(seen)):
                for source in sources:
                    key = (source.owner_kind, source.owner_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    new_sources.append(source)
            if not new_sources:
                rounds -= 1               # the empty pass is not a round of work
                break
            items.extend(WorkItem(document_id, parameter, s)
                         for s in new_sources)
        report.sweep_rounds[parameter.uri] = rounds

        if candidates is not None:
            # The decided division of labour: retrieval is the primary
            # harvest, the deterministic candidate set is the floor under it.
            # Whatever the probes never surfaced is harvested now and counted
            # loudly - the audit stays one sentence: every owner was either
            # seen by retrieval or processed by the fallback.
            pool = candidates(document_id, parameter) or []
            leftover = [s for s in pool
                        if (s.owner_kind, s.owner_id) not in seen]
            report.fallback[parameter.uri] = {
                "candidates": len(pool), "leftover": len(leftover)}
            for source in leftover:
                seen.add((source.owner_kind, source.owner_id))
                items.append(WorkItem(document_id, parameter, source))
    report.owners_harvested = len(items)
    return items, report


def harvest_document(
    document_id: int,
    spec: Spec,
    templates: list,
    *,
    retrieve: Callable,                   # (probes, document_id, exclude) -> [[Source]]
    harvest: Callable,                    # (Source, Parameter) -> [claim dict]
    locate: Optional[Callable] = None,    # (Source, quote) -> rects | None
    candidates: Optional[Callable] = None,  # (document_id, Parameter) -> [Source]
    max_rounds: int = MAX_SWEEP_ROUNDS,
) -> DocumentReport:
    """Plan and harvest one document, one request after another.

    The serial path: it keeps the loop's semantics in one readable piece and
    is what the tests own. Real runs go through plan_document + fold_claims,
    which do the same work with every request in flight at once.
    """
    items, report = plan_document(document_id, spec, templates,
                                  retrieve=retrieve, candidates=candidates,
                                  max_rounds=max_rounds)
    for item in items:
        fold_claims(item, harvest(item.source, item.parameter), report,
                    locate=locate)
    return report


def fold_claims(item: WorkItem, claims: Optional[list],
                report: DocumentReport, *,
                locate: Optional[Callable] = None) -> None:
    """Verify one source's claims into the report — the pure half of a harvest."""
    source, parameter = item.source, item.parameter
    for claim in claims or []:
        finder = ((lambda quote, s=source: locate(s, quote))
                  if locate is not None else None)
        outcome = verify_tuple(claim, parameter, source.text,
                               owner_kind=source.owner_kind, locate=finder)
        if isinstance(outcome, Refusal):
            report.refusals.append(
                {"parameter": parameter.uri, "reason": outcome.reason,
                 "claim": outcome.raw,
                 "owner": [source.owner_kind, source.owner_id]})
            continue
        row = dict(outcome.tuple)
        row["tier"] = outcome.tier
        if outcome.flags:
            # The flags ride on the row itself: a vocabulary review works
            # from the harvest files, not from a log line's count.
            row["flags"] = outcome.flags
        row["provenance"] = {
            **source.provenance,
            "owner_kind": source.owner_kind,
            "owner_id": source.owner_id,
        }
        # What a reader needs to check this value: the rectangles to highlight
        # for a passage in the text, the image itself for a table or figure.
        if outcome.rects:
            row["provenance"]["rects"] = outcome.rects
        if source.image_path:
            row["provenance"]["image"] = source.image_path
        report.tuples.append(row)
        report.flags.extend(outcome.flags)


def write_report(report: DocumentReport, out_path: Path) -> None:
    """Tuples and refusals as one JSONL, written atomically.

    Refusals are rows too (kind=refusal): the file is the audit trail, and an
    audit that only shows the survivors cannot answer why a value is missing.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=out_path.parent,
            suffix=".part", delete=False) as handle:
        for row in report.tuples:
            handle.write(json.dumps({"kind": "tuple", **row},
                                    ensure_ascii=False) + "\n")
        for refusal in report.refusals:
            handle.write(json.dumps({"kind": "refusal", **refusal},
                                    ensure_ascii=False) + "\n")
        temp = Path(handle.name)
    temp.replace(out_path)
    leftovers = {k.rsplit("/", 1)[-1]: v["leftover"]
                 for k, v in report.fallback.items()}
    log.info(
        "extraction: document %s -> %d tuple(s), %d refusal(s), %d flag(s), "
        "%d owner(s) harvested, sweep rounds %s, fallback leftovers %s",
        report.document_id, len(report.tuples), len(report.refusals),
        len(report.flags), report.owners_harvested,
        {k.rsplit("/", 1)[-1]: v for k, v in report.sweep_rounds.items()},
        leftovers or "-")
