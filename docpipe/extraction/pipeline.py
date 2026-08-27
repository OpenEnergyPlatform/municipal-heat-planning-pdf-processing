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
BATCH_SOURCES = 6
BATCH_CHARS = 14000


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
class Batch:
    """Several sources read in ONE request, for one parameter.

    A single source at a time is how the answer loop in the chat app works,
    and it is the wrong unit here: a plan states the carrier in the heading,
    the year in the caption and the number in the table, and a model shown
    only the table has to invent the other two or refuse. A batch puts the
    neighbouring passages in front of it at once, so a tuple can be assembled
    across them instead of guessed from one.

    Sources keep their label (`id`): the model names the label a value came
    from, and every claim is verified against THAT source's text. The batch
    widens what the model may read, not what a quote may be checked against.
    """
    document_id: int
    parameter: object
    items: list = field(default_factory=list)     # [WorkItem], label = index + 1

    @property
    def sources(self) -> list:
        return [item.source for item in self.items]

    def label(self, index: int) -> str:
        return f"Q{index + 1}"


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
    # parameter uri -> {"asked": n, "served": m}: how often the model said the
    # passages were not enough, and how often retrieval could answer that.
    followups: dict = field(default_factory=dict)


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


def group_items(items: list, *, max_sources: int = BATCH_SOURCES,
                max_chars: int = BATCH_CHARS) -> list:
    """Work items grouped into batches — one request reads several sources.

    Grouping is per document AND per parameter, in the order the sweep found
    them, so a batch holds passages retrieval considered close to the same
    question. It never mixes parameters: the choice lists differ per
    parameter, and a batch spanning two of them would have to carry both.
    """
    batches: list = []
    current: Optional[Batch] = None
    size = 0
    for item in items:
        text = len(item.source.text or "")
        # A source too long for a shared request rides alone rather than
        # pushing a neighbour out: split_long_sources has already cut what
        # cannot fit at all.
        if (current is not None
                and current.document_id == item.document_id
                and current.parameter is item.parameter
                and len(current.items) < max_sources
                and (size + text <= max_chars or not current.items)):
            current.items.append(item)
            size += text
            continue
        current = Batch(item.document_id, item.parameter, [item])
        size = text
        batches.append(current)
    return batches


def route_claims(batch: Batch, tuples: Optional[list]) -> list:
    """One claim list per work item — the label proposes, the quote decides.

    The model names the source a value came from, but a label is the easiest
    thing in a batch to get wrong, and a mislabelled tuple would be refused
    for a quote that is verbatim in the document. So the quote settles it:
    the claim goes to the source whose text actually carries it, and the
    label only breaks the tie when several do. A claim no source carries
    stays with its label and is refused by verify — which is the right
    outcome, because that quote is in none of the passages the model read.
    """
    routed: list = [[] for _ in batch.items]
    labels = {batch.label(i): i for i in range(len(batch.items))}
    for claim in tuples or []:
        if not isinstance(claim, dict):
            continue
        named = labels.get(str(claim.get("source") or "").strip())
        quote = claim.get("quote")
        holders = ([i for i, item in enumerate(batch.items)
                    if quote and quote in (item.source.text or "")]
                   if isinstance(quote, str) else [])
        if named is not None and named in holders:
            index = named
        elif holders:
            index = holders[0]
        elif named is not None:
            index = named
        else:
            index = 0
        claim.pop("source", None)
        routed[index].append(claim)
    return routed


def build_chains(items: list, *, max_sources: int = BATCH_SOURCES,
                 max_chars: int = BATCH_CHARS) -> list:
    """Batches grouped into the sequences that must be read in order.

    One chain per (document, parameter). Within a chain the batches share a
    `prior` that grows as they are read, so they run one after another; every
    chain is independent of every other, so the run's parallelism is the
    number of chains, not the number of requests. A group of 40 documents
    with three parameters is 120 chains — more than enough to keep the
    server's queue full, and the ordering constraint costs nothing.
    """
    chains: dict = {}
    for batch in group_items(items, max_sources=max_sources,
                             max_chars=max_chars):
        chains.setdefault((batch.document_id, batch.parameter.uri),
                          []).append(batch)
    return list(chains.values())


def run_chain(batches: list, harvest: Callable, *,
              more_sources: Optional[Callable] = None,
              rounds: int = 1,
              max_sources: int = BATCH_SOURCES,
              max_chars: int = BATCH_CHARS) -> list:
    """One chain, read in order — returns [(batch, reply)] including follow-ups.

    Three of the four things a batch may answer are handled here. "Found it"
    and "not in these passages" both just end the batch; "there is a value
    here but its context is elsewhere" is the one that does work: the model
    writes what to search for, retrieval answers with passages this document
    has not shown yet, and they become one more batch of the same chain. The
    fourth, the sandbox, is a turn inside the request and never reaches here.

    Follow-ups are bounded per chain, and the sources they add are excluded
    from any later round, so a model that keeps asking cannot loop.
    """
    out: list = []
    prior: list = []
    seen = {(it.source.owner_kind, it.source.owner_id)
            for b in batches for it in b.items}
    queue = list(batches)
    budget = rounds
    while queue:
        batch = queue.pop(0)
        reply = harvest(batch, list(prior))
        reply = reply if isinstance(reply, dict) else {}
        prior.extend(t for t in reply.get("tuples") or []
                     if isinstance(t, dict) and not t.get("_harvest_failed"))
        wanted = (reply.get("need_more")
                  if reply.get("status") == "partial" else None)
        if wanted and budget > 0 and more_sources is not None:
            budget -= 1
            extra = more_sources(batch.document_id, list(wanted), set(seen)) or []
            fresh = [s for s in extra if (s.owner_kind, s.owner_id) not in seen]
            for source in fresh:
                seen.add((source.owner_kind, source.owner_id))
            if fresh:
                reply["_served"] = True
                items = [WorkItem(batch.document_id, batch.parameter, s)
                         for s in fresh]
                queue.extend(group_items(items, max_sources=max_sources,
                                         max_chars=max_chars))
        out.append((batch, reply))
    return out


def harvest_document(
    document_id: int,
    spec: Spec,
    templates: list,
    *,
    retrieve: Callable,                   # (probes, document_id, exclude) -> [[Source]]
    harvest: Callable,                    # (Batch, prior) -> reply dict
    locate: Optional[Callable] = None,    # (Source, quote) -> rects | None
    candidates: Optional[Callable] = None,  # (document_id, Parameter) -> [Source]
    more_sources: Optional[Callable] = None,  # (doc, queries, exclude) -> [Source]
    max_rounds: int = MAX_SWEEP_ROUNDS,
    max_sources: int = BATCH_SOURCES,
    max_chars: int = BATCH_CHARS,
) -> DocumentReport:
    """Plan and harvest one document, one chain after another.

    The serial path: it keeps the loop's semantics in one readable piece and
    is what the tests own. Real runs call the same run_chain, with every
    chain of every document in flight at once.
    """
    items, report = plan_document(document_id, spec, templates,
                                  retrieve=retrieve, candidates=candidates,
                                  max_rounds=max_rounds)
    for chain in build_chains(items, max_sources=max_sources,
                              max_chars=max_chars):
        for batch, reply in run_chain(chain, harvest,
                                      more_sources=more_sources,
                                      max_sources=max_sources,
                                      max_chars=max_chars):
            fold_batch(batch, reply, report, locate=locate)
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


def fold_batch(batch: Batch, reply: Optional[dict], report: DocumentReport, *,
               locate: Optional[Callable] = None) -> None:
    """Verify one batch's reply into the report.

    The reply carries the tuples, and it carries what the model said about
    them: `complete` means these passages hold nothing else for this
    parameter, `partial` with `need_more` means a value is in here but its
    context is not. The second is the number that matters for the next
    sweep — it is the model telling us where retrieval was too narrow.
    """
    reply = reply if isinstance(reply, dict) else {}
    routed = route_claims(batch, reply.get("tuples"))
    for item, claims in zip(batch.items, routed):
        fold_claims(item, claims, report, locate=locate)
    counts = report.followups.setdefault(
        batch.parameter.uri, {"asked": 0, "served": 0})
    if reply.get("status") == "partial" and reply.get("need_more"):
        counts["asked"] += 1
    if reply.get("_served"):
        counts["served"] += 1


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
    asked = sum(v["asked"] for v in report.followups.values())
    served = sum(v["served"] for v in report.followups.values())
    log.info(
        "extraction: document %s -> %d tuple(s), %d refusal(s), %d flag(s), "
        "%d owner(s) harvested, sweep rounds %s, fallback leftovers %s, "
        "%d more-passages request(s), %d served",
        report.document_id, len(report.tuples), len(report.refusals),
        len(report.flags), report.owners_harvested,
        {k.rsplit("/", 1)[-1]: v for k, v in report.sweep_rounds.items()},
        leftovers or "-", asked, served)
