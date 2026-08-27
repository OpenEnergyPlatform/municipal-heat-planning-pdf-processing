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
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import queries as queries_mod
from .spec import Spec
from .verify import Refusal, Verified, quote_in, verify_tuple

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
    # True for a batch the model asked for, which the plan never counted.
    followed_up: bool = False

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


def route_claims(batch: Batch, tuples: Optional[list]) -> tuple:
    """(one claim list per work item, unroutable claims).

    The model names the source a value came from, but a label is the easiest
    thing in a batch to get wrong, and a mislabelled tuple would be refused
    for a quote that is verbatim in the document. So the quote settles it:
    the claim goes to the source whose text actually carries it, and the
    label only breaks the tie when several do.

    A claim that neither carries a findable quote nor names a real label is
    NOT filed under the first source. It used to be, and that was a way to
    manufacture evidence: verify rebuilds a missing quote from the source it
    was handed whenever the value occurs there exactly once, so a claim read
    from the fourth passage could be accepted carrying the first passage's
    page, section and image as its provenance. It comes back as unroutable
    instead, and the caller refuses it.
    """
    routed: list = [[] for _ in batch.items]
    orphans: list = []
    labels = {batch.label(i): i for i in range(len(batch.items))}
    for claim in tuples or []:
        if not isinstance(claim, dict):
            continue
        named = labels.get(str(claim.get("source") or "").strip())
        quote = claim.get("quote")
        # quote_in, not `in`: the same whitespace-collapsed test verify runs.
        # Routing stricter than verification refuses claims verification
        # would have accepted, and a table row retyped without its padding is
        # the normal case, not the exception — 276 of one pilot's refusals.
        holders = ([i for i, item in enumerate(batch.items)
                    if quote_in(item.source.text or "", quote)]
                   if isinstance(quote, str) else [])
        if named is not None and named in holders:
            index = named
        elif holders:
            index = holders[0]
        elif named is not None:
            # The label is real but the quote is not verbatim anywhere. Verify
            # decides — it collapses whitespace where this does not, so a
            # reflowed quote still has its chance, and an invented one does not.
            index = named
        else:
            orphans.append(claim)
            continue
        claim.pop("source", None)
        routed[index].append(claim)
    return routed, orphans


class Sweep:
    """The shared state of one (document, parameter), across its batches.

    Batches used to be run one after another so that a later one could be
    told what the earlier ones had found. That made a chain the unit of
    scheduling, and the unit of scheduling is the unit of parallelism: a
    single-document run — which is exactly what the pilot's canary stage is —
    collapsed to one request per parameter, three at a time against a server
    sized for two hundred, and the canary that used to take three minutes was
    killed unfinished after nine.

    So the ordering is gone and the bookkeeping stays. `prior` is a hint that
    stops the model handing back a value a neighbouring passage already gave;
    a hint does not need to be deterministic, and paying two orders of
    magnitude of throughput to make it so is the wrong trade. Every batch
    reads whatever has been verified by the time it is dispatched.

    Verified, not claimed: a tuple that verification threw away used to be
    handed to the next batch as "already extracted", and the prompt tells the
    model not to repeat those — so a value refused once for a bad quote was
    suppressed everywhere else in the document, leaving neither a tuple nor a
    refusal behind.
    """

    __slots__ = ("seen", "prior", "budget", "lock")

    def __init__(self, seen: set, budget: int):
        self.seen = seen
        self.prior: list = []
        self.budget = budget
        self.lock = threading.Lock()

    def snapshot(self) -> list:
        with self.lock:
            return list(self.prior)

    def record(self, verified: list) -> None:
        if not verified:
            return
        with self.lock:
            self.prior.extend(verified)

    def take_followup(self, sources: list) -> list:
        """The passages of a follow-up this sweep has not already covered."""
        with self.lock:
            if self.budget <= 0:
                return []
            fresh = [s for s in sources
                     if (s.owner_kind, s.owner_id) not in self.seen]
            if not fresh:
                return []
            self.budget -= 1
            for source in fresh:
                self.seen.add((source.owner_kind, source.owner_id))
            return fresh


def build_sweeps(batches: list, rounds: int = 1) -> dict:
    """One Sweep per (document, parameter), keyed as the batches are."""
    sweeps: dict = {}
    for batch in batches:
        key = (batch.document_id, batch.parameter.uri)
        sweep = sweeps.get(key)
        if sweep is None:
            sweep = sweeps[key] = Sweep(set(), rounds)
        sweep.seen.update((it.source.owner_kind, it.source.owner_id)
                          for it in batch.items)
    return sweeps


def follow_up(batch: Batch, reply: dict, sweep: Sweep, more_sources: Callable,
              *, max_sources: int = BATCH_SOURCES,
              max_chars: int = BATCH_CHARS) -> list:
    """The extra batches a "there is more here, look for this" earns.

    The third of the four answers a batch may give. "Found it" and "not in
    these passages" end the batch; the sandbox is a turn inside the request
    and never reaches here. This one does work: the model writes what to
    search for, retrieval answers with passages this document has not shown
    yet, and they join the pool like any other batch. Bounded per sweep, and
    what arrives is excluded from every later round, so a model that keeps
    asking cannot loop.
    """
    if reply.get("status") != "partial" or not reply.get("need_more"):
        return []
    extra = more_sources(batch.document_id, list(reply["need_more"]),
                         set(sweep.seen)) or []
    fresh = sweep.take_followup(extra)
    if not fresh:
        return []
    reply["_served"] = True
    items = [WorkItem(batch.document_id, batch.parameter, s) for s in fresh]
    extra_batches = group_items(items, max_sources=max_sources,
                                max_chars=max_chars)
    for one in extra_batches:
        one.followed_up = True
    return extra_batches


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
    """Plan and harvest one document, one batch after another.

    The serial path: it keeps the loop's semantics in one readable piece and
    is what the tests own. Real runs do the same work with every batch of
    every document in flight at once, which is the whole reason a batch and
    not a chain is the unit here.
    """
    items, report = plan_document(document_id, spec, templates,
                                  retrieve=retrieve, candidates=candidates,
                                  max_rounds=max_rounds)
    queue = group_items(items, max_sources=max_sources, max_chars=max_chars)
    sweeps = build_sweeps(queue)
    while queue:
        batch = queue.pop(0)
        sweep = sweeps[(batch.document_id, batch.parameter.uri)]
        reply = harvest(batch, sweep.snapshot())
        reply = reply if isinstance(reply, dict) else {}
        # The follow-up runs first because it is what marks the reply as
        # served, and folding is what counts that.
        if more_sources is not None:
            queue.extend(follow_up(batch, reply, sweep, more_sources,
                                   max_sources=max_sources,
                                   max_chars=max_chars))
        before = len(report.tuples)
        fold_batch(batch, reply, report, locate=locate)
        # Only what survived verification becomes the next batch's `prior`:
        # the prompt tells the model not to repeat what is in there, so a
        # claim the verifier threw away would suppress the same value
        # everywhere else in the document and leave nothing behind.
        sweep.record(report.tuples[before:])
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
    routed, orphans = route_claims(batch, reply.get("tuples"))
    for item, claims in zip(batch.items, routed):
        fold_claims(item, claims, report, locate=locate)
    for claim in orphans:
        # Named no source of this batch and quoted none of them either. There
        # is no text to check it against, so there is no way to accept it.
        report.refusals.append(
            {"parameter": batch.parameter.uri, "reason": "claim names no source",
             "claim": claim,
             "owner": [batch.items[0].source.owner_kind,
                       batch.items[0].source.owner_id]})
    counts = report.followups.setdefault(
        batch.parameter.uri, {"asked": 0, "served": 0})
    if reply.get("status") == "partial" and reply.get("need_more"):
        counts["asked"] += 1
    if reply.get("_served"):
        counts["served"] += 1
    # Counted here, not frozen at plan time: a follow-up brings passages the
    # plan never knew about, and a report that says "N owners harvested"
    # while having read more than N cannot be used to audit coverage.
    if batch.followed_up:
        report.owners_harvested += len(batch.items)


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
