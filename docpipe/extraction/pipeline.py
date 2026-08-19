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

The three expensive dependencies — retrieval, the harvesting LLM call, the
native-PDF text lookup — are injected callables. The loop's correctness is a
pure-code property and is tested without a GPU; the wiring to the live
inference stack lives with the CLI, not here.

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
    readoff: bool = False                 # figure descriptions / chart reads


@dataclass
class DocumentReport:
    document_id: int
    tuples: list = field(default_factory=list)
    refusals: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    owners_harvested: int = 0
    sweep_rounds: dict = field(default_factory=dict)   # parameter uri -> rounds


def harvest_document(
    document_id: int,
    spec: Spec,
    templates: list,
    *,
    retrieve: Callable,                   # (query, document_id, exclude) -> [Source]
    harvest: Callable,                    # (Source, Parameter) -> [claim dict]
    pdf_text: Optional[Callable] = None,  # (Source) -> Optional[str]
    max_rounds: int = MAX_SWEEP_ROUNDS,
) -> DocumentReport:
    report = DocumentReport(document_id=document_id)
    for parameter in spec.parameters:
        probes = queries_mod.expand(templates, parameter)
        seen: set = set()
        rounds = 0
        while rounds < max_rounds:
            rounds += 1
            new_sources: list = []
            for query in probes:
                for source in retrieve(query, document_id, set(seen)):
                    key = (source.owner_kind, source.owner_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    new_sources.append(source)
            if not new_sources:
                rounds -= 1               # the empty pass is not a round of work
                break
            for source in new_sources:
                report.owners_harvested += 1
                for claim in harvest(source, parameter) or []:
                    lookup = (lambda s=source: pdf_text(s)) if pdf_text else None
                    outcome = verify_tuple(
                        claim, parameter, source.text,
                        pdf_text=lookup, readoff=source.readoff)
                    if isinstance(outcome, Refusal):
                        report.refusals.append(
                            {"parameter": parameter.uri, "reason": outcome.reason,
                             "claim": outcome.raw,
                             "owner": [source.owner_kind, source.owner_id]})
                        continue
                    row = dict(outcome.tuple)
                    row["tier"] = outcome.tier
                    row["provenance"] = {
                        **source.provenance,
                        "owner_kind": source.owner_kind,
                        "owner_id": source.owner_id,
                    }
                    report.tuples.append(row)
                    report.flags.extend(outcome.flags)
        report.sweep_rounds[parameter.uri] = rounds
    return report


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
    log.info(
        "extraction: document %s -> %d tuple(s), %d refusal(s), %d flag(s), "
        "%d owner(s) harvested, sweep rounds %s",
        report.document_id, len(report.tuples), len(report.refusals),
        len(report.flags), report.owners_harvested,
        {k.rsplit("/", 1)[-1]: v for k, v in report.sweep_rounds.items()})
