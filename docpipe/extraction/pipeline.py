"""
pipeline.py: The harvest loop that turns a document's retrieved passages into
verified value tuples.

`plan_document` builds one retrieval plan per document rather than per
parameter: every table and every figure, taken whole because being a table or a
figure predicts a value better than any similarity ranking does, plus the best
ranked prose sections. `group_items` folds the plan into batches read in one
request each. A batch stays inside one document and one parameter, or the whole
document when the plan is not split by parameter, so it never mixes what a
different parameter's choice list would need. Every claimed tuple, whichever
request produced it, passes `verify_tuple`; refusals are kept alongside the
accepted tuples, because a harvest that cannot say what it threw away reads as
complete when it is not.

`Sweep` and `build_sweeps` carry the tuples a document's batches have already
verified forward as a hint to later batches, and grant a bounded follow-up
budget when a reply says more passages are needed (`follow_up`). `fold_claims`,
`fold_batch` and `fold_fieldwise` verify a reply's claims into a
`DocumentReport`; `write_report` writes that report's tuples, refusals,
per-parameter states and one summary line to one JSONL file, atomically.

The three expensive dependencies, retrieval, the harvesting LLM call, and
locating a quote on its PDF page, are injected callables. The module's own
correctness is a pure-code property and is tested without a GPU; the wiring to
the live inference stack lives in `runner.py`.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import queries as queries_mod
from .spec import Spec, fold_label
from .fields import (CHOICE, NUMBER, READ, SAID_UNSTATED, UNANSWERED,
                     UNBACKED, UNSTATED)
from .verify import (MIN_QUOTE_CHARS, Refusal, Verified, canonical_number,
                     flat, numbers_in, quote_in, verify_tuple)
from .trust import document_summary

log = logging.getLogger(__name__)

MAX_SWEEP_ROUNDS = 4
BATCH_SOURCES = 6
BATCH_CHARS = 14000
# How many prose sections a document is planned from. Tables and figures are
# not capped: they are taken whole, because structure predicts a value better
# than any ranking does.
PROSE_TOP = 50
VISUAL_KINDS = ("table", "figure")


@dataclass
class Source:
    """One retrieval owner as the harvest needs it."""
    owner_kind: str                       # "section" | "table" | "figure"
    owner_id: int
    text: str                             # what the model will read
    provenance: dict = field(default_factory=dict)
    image_path: Optional[str] = None      # the crop, for tables and figures
    # The transcription without the heading prefixed to `text`, for the quote
    # repair alone — that repair needs the value to occur exactly once.
    body: Optional[str] = None


@dataclass
class WorkItem:
    """One harvest request: read THIS source.

    `parameter` is None for a document-level plan, where which quantity a
    value is gets asked for instead of assumed. It stays for the callers that
    still plan per parameter.

    `rank` and `origin` are carried, not recomputed: every knob this stage has
    is a cut through a ranking, and a cut can only be measured if the number
    it cuts at is written down next to what came out.
    """
    document_id: int
    parameter: object
    source: Source
    rank: Optional[int] = None            # position in the fused ranking
    origin: str = ""                      # "structure" | "retrieval"


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
    # Which of the document's (scenario, year) pairs this request asks for,
    # and its index. The same passages are read once per pair: a table with
    # four year columns is four requests, each one asking for one column,
    # which is what takes the coordinate out of the model's hands.
    frame: Optional[dict] = None
    frame_index: int = 0
    # Every pair of the document, so a passage that carries more than one of
    # them can be recognised as one: a table with a column per year names
    # three pairs and belongs to none of them alone.
    frame_all: tuple = ()
    # The sentences this request's passages were searched with. They say, in
    # the plan's own words, what the request asks for, so the pair reaches
    # the model as a question and not only as a field.
    anchors: tuple = ()

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
    # What the plan was built from, so a run can be read back against the
    # settings it ran under instead of against the ones in the file today.
    planned: dict = field(default_factory=dict)


def plan_document(
    document_id: int,
    spec: Spec,
    templates: list,
    *,
    extra_probes: Optional[dict] = None,
    retrieve: Callable,                 # (probes, document_id, exclude) -> [Source]
    structure: Optional[Callable] = None,   # (document_id) -> [Source]
    prose_top: int = PROSE_TOP,
    top: Optional[int] = None,
) -> tuple:
    """(work items, report skeleton) — the retrieval half, no model involved.

    One plan per DOCUMENT, not one per parameter. Which quantity a number is,
    is a coordinate the field sweep asks for like every other, so a table is
    read once instead of once per parameter.

    Two sets go in, and they are picked by different rules because the values
    sit in them for different reasons:

    * every table and every figure, from structure alone. Measured over 65
      documents, 12,094 of 15,082 values came from one of those, and "is a
      table" is a better predictor of holding a number than any similarity to
      any question. There are about 110 per document, so reading all of them
      is affordable exactly once the parameter stopped tripling the plan.
    * the best `prose_top` sections by retrieval. Prose carries the other
      fifth of the values and there are 125 sections per document, so this is
      the half where a ranking has to earn its keep.

    The probes are the HyDE anchors and nothing else. The query templates used
    to ride along and they were measured as harmful: with them the source a
    value was really read from sat at median rank 84, without them at 26. A
    template names the thing, an anchor says the sentence as a plan would
    write it, and a similarity search matches sentences.

    No rounds. The old loop asked retrieval again with everything it had
    already returned excluded, which walks down the ranking until the document
    is exhausted — 277 planned sources against 234 owners, three times over.
    That is a full scan wearing a vector store as a hat.

    `top` replaces both rules with one. The plan is then the fused top `top`
    in rank order, tables figures and prose together, and the structural floor
    is not a source of items any more. It is still CALLED, and what it knows
    and the ranking missed is reported as `leftover` — the number that says
    whether the floor has to come back, which can only be taken while the
    floor is still there to ask. Without `top` nothing about this function
    changes.
    """
    report = DocumentReport(document_id=document_id)
    probes: list = []
    for parameter in spec.parameters:
        for probe in (extra_probes or {}).get(parameter.uri, ()):
            if probe and probe not in probes:
                probes.append(probe)
    if not probes:
        # No anchors written for this spec. Falling back to the templates is
        # worse retrieval, and silently worse retrieval is what this whole
        # rewrite is about, so it is said out loud.
        log.warning("extraction: document %s planned from query templates, "
                    "no anchors — expect the ranking to be poor", document_id)
        for parameter in spec.parameters:
            for probe in queries_mod.expand(templates, parameter):
                if probe not in probes:
                    probes.append(probe)

    ranked = retrieve(probes, document_id, set()) or []
    rank_of = {(s.owner_kind, s.owner_id): i for i, s in enumerate(ranked)}

    if top is not None:
        taken = ranked[:max(0, top)]
        kept = {(s.owner_kind, s.owner_id) for s in taken}
        known = [s for s in (structure(document_id) if structure else ())
                 if s.owner_kind in VISUAL_KINDS]
        # One origin, because there is one list. It used to name which of two
        # lists a source landed in, and with the floor gone every source is a
        # retrieval hit — saying "structure" about a table would be a claim
        # about where it came from that is no longer true.
        items = [WorkItem(document_id, None, source,
                          rank=rank_of.get((source.owner_kind, source.owner_id)),
                          origin="retrieval")
                 for source in taken]
        report.sweep_rounds["document"] = 1
        report.fallback["document"] = {
            "candidates": len(known),
            "leftover": sum(1 for s in known
                            if (s.owner_kind, s.owner_id) not in kept)}
        report.owners_harvested = len(items)
        report.planned = {
            "visual": sum(1 for s in taken if s.owner_kind in VISUAL_KINDS),
            "prose": sum(1 for s in taken if s.owner_kind not in VISUAL_KINDS),
            "ranked": len(ranked), "probes": len(probes), "top": len(taken)}
        return items, report

    visual = [s for s in (structure(document_id) if structure else ())
              if s.owner_kind in VISUAL_KINDS]
    # Ranked ones first and in their order, the rest behind them: a table no
    # probe matched is still worth reading, and still worth reading last.
    visual.sort(key=lambda s: rank_of.get((s.owner_kind, s.owner_id), 10 ** 9))
    seen = {(s.owner_kind, s.owner_id) for s in visual}

    # What the ranking found and the structural set does not already hold.
    # A table among them is kept whatever the cap says: the cap exists because
    # there are 125 prose sections and a fifth of the values, and it has no
    # business dropping a table the structural query missed.
    prose: list = []
    for source in ranked:
        key = (source.owner_kind, source.owner_id)
        if key in seen:
            continue
        if source.owner_kind in VISUAL_KINDS:
            seen.add(key)
            visual.append(source)
            continue
        if len(prose) >= max(0, prose_top):
            continue
        seen.add(key)
        prose.append(source)

    items: list = []
    for source in visual:
        key = (source.owner_kind, source.owner_id)
        items.append(WorkItem(document_id, None, source,
                              rank=rank_of.get(key), origin="structure"))
    for source in prose:
        key = (source.owner_kind, source.owner_id)
        items.append(WorkItem(document_id, None, source,
                              rank=rank_of.get(key), origin="retrieval"))

    unranked = sum(1 for s in visual
                   if (s.owner_kind, s.owner_id) not in rank_of)
    report.sweep_rounds["document"] = 1
    report.fallback["document"] = {"candidates": len(visual),
                                   "leftover": unranked}
    report.owners_harvested = len(items)
    report.planned = {"visual": len(visual), "prose": len(prose),
                      "ranked": len(ranked), "probes": len(probes),
                      "prose_top": prose_top}
    return items, report


def group_items(items: list, *, max_sources: int = BATCH_SOURCES,
                max_chars: int = BATCH_CHARS) -> list:
    """Work items grouped into batches — one request reads several sources.

    Grouping is per document AND per parameter, in the order the plan built
    them, so a batch holds passages that were ranked next to each other. It
    never mixes parameters: the choice lists differ per parameter, and a batch
    spanning two of them would have to carry both.

    A document-level plan has `parameter is None` on every item, so the rule
    still holds and the grouping is simply per document. Which parameter each
    value belongs to is asked for afterwards, per row, with its own evidence.
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


@dataclass
class Row:
    """One value found in one source, before its coordinates are filled.

    A row is created by the value request and by nothing else. Every later
    request fills a column of rows that already exist, so no field request can
    invent a value and none can quietly drop one: the count is fixed before
    the first coordinate is asked for.
    """
    label: str                            # "R1", the id a field answer names
    item_index: int                       # which source of the batch it sits in
    claim: dict = field(default_factory=dict)


def row_label(index: int) -> str:
    return f"R{index + 1}"


def cell_index(quote: str, value) -> Optional[tuple]:
    """(cell holding this value, cells in the row), 1-based, or None.

    The one thing a field request should not have to work out for itself. A
    table row quoted whole carries three numbers under three year columns, and
    which year applies is decided by which cell the number sits in — a fact
    that is already known here, because the value and the row it was quoted
    from are both in hand. Handing it over turns "count the cells" into a
    given and leaves the model the part that actually needs reading: which
    year the header's nth cell names.

    None whenever it is not certain: no table row, the value in no cell, or
    the same number in two of them. A wrong column is worse than none.
    """
    if not isinstance(quote, str) or "|" not in quote:
        return None
    line = next((l for l in quote.splitlines() if l.count("|") >= 2), None)
    if line is None:
        return None
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    wanted = canonical_number(value)
    if wanted is None:
        return None
    hits = [i for i, cell in enumerate(cells, start=1)
            if wanted in numbers_in(cell)]
    return (hits[0], len(cells)) if len(hits) == 1 else None


def column_answer(quote: str, cell: Optional[tuple]) -> Optional[str]:
    """What the cited passage prints in THIS row's own column, or None.

    A table's header is one line with one cell per column, and the line the
    value was quoted from has the same number of cells. So the answer that
    belongs to a value is the header's cell at the value's own position, and
    an answer naming a different cell is naming another column. That is what
    `answer_in_quote` cannot see: the header prints 2030 and 2045 in the same
    line, so either of them verifies against it for either row.

    None when nothing lines up: no cell, no line of the same width, or a
    header cell that prints no answer at all (a sector column, a label). A
    check that cannot be evaluated refuses nothing.
    """
    if not cell:
        return None
    index, count = cell
    for line in (quote or "").splitlines():
        if line.count("|") < 2:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != count or not 1 <= index <= count:
            continue
        printed = cells[index - 1]
        if numbers_in(printed):
            return printed
    return None


def _invented_wording(claim: dict) -> bool:
    """A non-numeric value that its own quote does not contain.

    Numbers are left to the verifier: it collapses whitespace, repairs a
    retyped table row and knows the German decimal mark, and duplicating any
    of that here would refuse claims the verifier would have taken. A wording
    needs none of it — either the passage says it or the model wrote it down
    from somewhere else.
    """
    value = claim.get("value")
    if not isinstance(value, str) or canonical_number(value) is not None:
        return False
    # value_raw first, exactly as value_in_quote does it. A choice carries
    # the class in `value` and the document's own wording in `value_raw`, and
    # holding the class name against the passage would refuse every correctly
    # evidenced choice in the corpus.
    wording = claim.get("value_raw") or value
    quote = claim.get("quote")
    if not isinstance(quote, str):
        return True
    return flat(str(wording)).casefold() not in flat(quote).casefold()



def names_pair(source, pair: Optional[dict], slots: list) -> bool:
    """Does this passage print the scenario and the year of this pair?

    The whole passage, not a line of it. Where the year stands is the plan's
    business: a column header, a caption, a sentence above the table.
    """
    text = (getattr(source, "text", "") or "")
    for slot in slots:
        if slot.name not in (pair or {}):
            continue
        if not answer_in_quote(slot, pair[slot.name],
                               pair.get(f"{slot.name}_raw"), text):
            return False
    return True


def frame_reading(source, pair: Optional[dict], index: int,
                  pairs, slots: list) -> tuple:
    """(read it, coordinates not to project) for one passage of one request.

    The frame is a request, not a reading: `apply_frame` writes the pair onto
    every row the request produced, and nothing else ever asks. Three cases,
    and only the first one was handled.

    A passage that prints none of this pair belongs to another one, and the
    request for THAT pair is where its values are found. Measured on Kassel,
    where nothing checked it: the frame had two pairs, 193 rows were stamped
    2040 and 152 were stamped 2024, and of the 234 table tuples the hand
    reading covers, 60 carried the year the table prints.

    A passage that prints exactly this pair is this request's, and the
    coordinate is projected onto every row it produced.

    A passage that prints several of the frame's pairs, which is what a table
    with a column per year is, belongs to all of them and to none of them
    alone. It is read once, in the request of the first pair it names, so its
    cells are not harvested twice, and the coordinates its pairs disagree
    about are left open: `open_rows` then hands those rows to the per-row
    sweep, which is given the cell each value sits in (`cell_index`) and can
    tell the columns apart. Projecting instead is what stamped 39 cells of
    one table with one year.
    """
    if not pair or not slots:
        return True, ()
    if not names_pair(source, pair, slots):
        return False, ()
    fits = [i for i, other in enumerate(pairs or ())
            if names_pair(source, other, slots)]
    if fits and index != fits[0]:
        return False, ()
    blind = tuple(slot.name for slot in slots
                  if len({(pairs or ())[i].get(slot.name) for i in fits}) > 1)
    return True, blind


def rows_from_reply(batch: Batch, reply: Optional[dict],
                    frame_axes: Optional[list] = None) -> tuple:
    """(rows, orphans) from the value request - the only request that counts.

    Routing is the same as for a whole tuple: the quote decides which source a
    value belongs to, the label breaks a tie, and a claim that neither quotes
    nor names any source of the batch is an orphan.
    """
    reply = reply if isinstance(reply, dict) else {}
    routed, orphans = route_claims(batch, reply.get("tuples"))
    rows: list = []
    for item_index, claims in enumerate(routed):
        source = batch.items[item_index].source
        take, _blind = frame_reading(source, batch.frame, batch.frame_index,
                                     batch.frame_all, frame_axes or [])
        if claims and not take:
            # Another pair's passage, or a passage of several pairs that the
            # first of them already reads. Refused here rather than swept: the
            # coordinates would all be paid for and the row would then be
            # stamped with a year its own passage does not print.
            why = ("passage is not of this pair"
                   if not names_pair(source, batch.frame, frame_axes or [])
                   else "passage is read for its first pair")
            orphans.extend(dict(claim, _why=why) for claim in claims)
            continue
        for claim in claims:
            if _invented_wording(claim):
                # A wording that is not in the passage it cites is not a
                # reading, and the cheapest place to say so is here, before
                # it becomes a row. It used to become one and was refused at
                # the very end, after every coordinate had been swept for it:
                # measured on Kassel, the office name the prompt's own
                # example suggested cost 24 windows and 80.3 seconds and
                # reached the graph never. The claim still travels on and is
                # still refused with its own reason, it just costs nothing.
                orphans.append(dict(claim, _why="text value not in its quote"))
                continue
            rows.append(Row(label=row_label(len(rows)),
                            item_index=item_index, claim=dict(claim)))
    return rows, orphans

def answer_in_quote(slot, given, wording: Optional[str], quote: str) -> bool:
    """Does the coordinate actually stand in the passage cited for it?

    Both halves of a quote's job, and the second one is the one that was
    missing. A passage that sits in the source proves the model read
    something; only a passage that CONTAINS the answer proves it read this.
    Measured on the corpus run that had the first half alone: 27.6% of years
    cited a passage with no year in it, one of them the caption "Tabelle 1:
    Bestehende Wärmenetze und Heiz(kraft)werke" offered as evidence for 1990.

    A number is compared as a number, a wording as text — the same split
    value_in_quote makes for the value itself, because these are the same
    question asked one level down.
    """
    if slot.kind == NUMBER:
        return canonical_number(given) in numbers_in(quote)
    shown = wording if wording else str(given)
    return flat(shown).casefold() in flat(quote).casefold()


# Where one word ends and the next begins, for a language that writes ae
# with an umlaut and joins nouns with a hyphen.
_WORD_EDGE = re.compile(r"[^0-9A-Za-zÀ-ɏ]+")
# Past this a "wording" is a sentence that happens to contain the label. The
# longest spelling any kwp axis lists is 44 characters ("Gewerbe, Handel,
# Dienstleistungen" and "Reduktion gegenueber einem Vergleichsjahr"), so 80
# leaves room for a compound the spec did not foresee and refuses a footnote.
MAX_WORDING_CHARS = 80


def _tokens(text: str) -> list:
    return [t for t in _WORD_EDGE.split(fold_label(text)) if t]


def wording_names_option(slot, given, wording) -> bool:
    """Does `value_raw` name the option the answer chose?

    field.md rule 2 says the wording is what the mapping is checked against,
    and until now nothing checked it. A reply could answer "Biogas" with the
    wording "Klärgas" and the quote would verify -- the passage really does
    say Klärgas -- while the graph carried Biogas on the strength of it.

    Whole tokens, not substrings: "Gas" inside "Erdgas" is a different word,
    and a containment test would call every carrier evidence for every other.
    A wording longer than a label is not one either; measured on Kassel, the
    rounding footnote was offered as `value_raw` 15 times.

    This is a COUNT, not a refusal. 29 of Kassel's carrier readings map
    Klärgas onto Biogas and 17 map "Holzige Festbrennstoffe" onto woody
    biomass, and both are right: the model is allowed to decide that a
    document's word belongs to a class the spec spells differently. What we
    have no measurement of is how often it decides wrongly, and that is
    exactly what this counter is for.
    """
    if slot.kind != CHOICE or not slot.options or not wording:
        return True
    if len(wording) > MAX_WORDING_CHARS:
        return False
    chosen = next((o for o in slot.options if fold_label(o.label)
                   == fold_label(given)), None)
    if chosen is None:
        return True                 # not one of the options: another check's
    said = _tokens(wording)
    for spelling in (chosen.label,) + tuple(chosen.synonyms):
        want = _tokens(spelling)
        if want and any(said[i:i + len(want)] == want
                        for i in range(len(said) - len(want) + 1)):
            return True
    return False


def evidence_is_local(slot, found, own) -> bool:
    """May this passage be the evidence for a coordinate of THIS row?

    A row label and a column header are read off the table the row is in. A
    scenario is usually named in the section around it or a page earlier. A
    class is argued in a methods chapter that can be anywhere. So the answer
    depends on the axis, and the axis says which of the three it is.

    The measured need: 370 of Kassel's 455 year readings cited a passage
    outside the row's own table and its section, 146 of them the annotated
    placeholder of a different table, and every one of those verified --
    the passage was real, it was shown, and it carried a year. It was just
    not this row's year.
    """
    rule = getattr(slot, "evidence", None) or "any"
    if rule == "any" or own is None or found is None:
        return True
    if (found.owner_kind, found.owner_id) == (own.owner_kind, own.owner_id):
        return True
    parent = (own.provenance or {}).get("parent_section")
    if (parent is not None and found.owner_kind == "section"
            and found.owner_id == parent):
        return True
    if rule == "local":
        here = (own.provenance or {}).get("page")
        there = (found.provenance or {}).get("page")
        if isinstance(here, int) and isinstance(there, int):
            return abs(here - there) <= 1
    return False


def merge_field(rows: list, sources: list, slot, reply: Optional[dict],
                *, window: Optional[tuple] = None,
                owner_of: Optional[dict] = None) -> dict:
    """Fold one field's answers. Returns {"filled", "unquoted", "unbacked"}.

    *window* is (stage, index) and is written next to each coordinate this
    call reads, together with the source the passage was found in. Which
    passage proved a coordinate is the one thing a later audit cannot
    reconstruct: measured on Kassel, 370 of 455 year readings cited a passage
    outside the row's own table and its section, and none of them said so.

    Every answer brings its own passage, and that passage has to pass exactly
    what the value's own quote passes: it sits verbatim in one of the sources
    that were SHOWN, AND it contains the answer. A field that fails either is
    left empty rather than written unbacked — the point of asking per field is
    that each coordinate is evidenced, and an answer that cannot show where it
    read the year is exactly the answer a whole-tuple request used to hide
    inside a tuple the value's quote had already justified.

    Shown, not the row's own source: the year of a table is in its caption and
    the scenario is in the section heading, so a coordinate's evidence is
    routinely in a different passage than the number's. Checking it against
    the row's own source would refuse exactly the readings this stage exists
    to collect.
    """
    reply = reply if isinstance(reply, dict) else {}
    pairs: list = []
    answers = reply.get("answers")
    if isinstance(answers, dict):
        pairs.extend(answers.items())
    # One answer for many rows. A table's thirteen rows share one reference
    # year and one caption to prove it, and repeating that caption thirteen
    # times is how a reply runs into the token wall and is lost whole.
    for group in reply.get("groups") or ():
        if not isinstance(group, dict):
            continue
        for label in group.get("rows") or ():
            pairs.append((label, group))
    by_label = {row.label: row for row in rows}
    # One answer for many rows is how a table's thirteen rows share one
    # caption. It is not how they share a column: rows the payload showed as
    # different cells of the same quoted line have different column headers
    # over them, and one number that stands in the quote stands in it for
    # every one of them. `answer_in_quote` cannot tell those apart, because
    # the header prints 2030 and 2045 in the same line the check runs over.
    conflicted: set = set()
    if slot.kind == NUMBER:
        for group in reply.get("groups") or ():
            if not isinstance(group, dict):
                continue
            labels = [str(label).strip() for label in group.get("rows") or ()]
            cells = {cell_index(by_label[label].claim.get("quote"),
                                by_label[label].claim.get("value"))
                     for label in labels if label in by_label}
            quote = group.get("quote")
            if (len({cell[0] for cell in cells if cell}) > 1
                    and len(numbers_in(quote if isinstance(quote, str)
                                       else "")) > 1):
                conflicted.update(labels)
    filled = unquoted = unbacked = unstated = raw_missing = raw_foreign = 0
    # Not just how many failed but which, and why. A model that is told "R7:
    # the passage you cited is in none of the sources" can fix R7; a model
    # that is told nothing repeats itself, and the same window is worth
    # asking again only if the second ask differs from the first.
    failed: list = []
    for label, answer in pairs:
        row = by_label.get(str(label).strip())
        if row is None or not isinstance(answer, dict):
            continue
        if row.claim.get(f"{slot.name}_state") == READ:
            # Read and backed once, and that is the reading. A later window
            # shows other passages, and letting the last speaker win is how
            # table 10 of Kassel lost its class and its carrier to the
            # appendix: 7 value nodes carried what a second window had put
            # there, 10 more collided with the first reading and took their
            # whole identity down with them. The state belongs to the
            # coordinate, not to whoever answered most recently.
            continue
        if row.label in conflicted:
            # Open, not written: the next window can be asked again, and the
            # answer it needs is one group per column rather than one for all
            # of them.
            row.claim[f"{slot.name}_state"] = UNBACKED
            failed.append({"row": row.label, "why": "one answer, two columns",
                           "reason": (
                "Diese Zeilen stehen in verschiedenen Spalten derselben "
                "Tabellenzeile, und dein \"quote\" enthält mehrere Zahlen. "
                "Gib je Spalte eine eigene Gruppe mit ihrer eigenen Antwort.")})
            unbacked += 1
            continue
        given = answer.get("value")
        if given is None or (isinstance(given, str) and not given.strip()):
            noticed = answer.get("value_raw")
            if isinstance(noticed, str) and noticed.strip():
                # The reply shape field.md asks for when the document says
                # something the list has no entry for: the wording, and no
                # answer. Dropped silently until now, so the one case the
                # vocabulary needs to hear about was the one that left no
                # trace. Kept as what it is, a wording nobody could map.
                row.claim[f"{slot.name}_seen"] = noticed.strip()
                row.claim[f"{slot.name}_state"] = SAID_UNSTATED
                unstated += 1
            continue
        if str(given).strip() == UNSTATED:
            # "Not stated" needs no passage, and the model sometimes supplies
            # one anyway — usually the row's own label. That is not evidence
            # and is not treated as any, but it is not noise either: it is the
            # wording the model looked at and found no class for. A CCS unit
            # in a sector column is a gap in the vocabulary, not a silent plan,
            # and the two are the same empty cell unless the wording is kept.
            noticed = answer.get("value_raw")
            if isinstance(noticed, str) and noticed.strip():
                row.claim[f"{slot.name}_seen"] = noticed.strip()
            # No passage is asked for and none could be given: there is no
            # sentence in a document that says a thing is not in it. This is
            # the one answer that carries no evidence, and it is why the row
            # can still be required to answer.
            row.claim[f"{slot.name}_state"] = SAID_UNSTATED
            unstated += 1
            continue
        quote = answer.get("quote")
        # WHICH source, not whether any. The passage a coordinate was read in
        # decides whether the reading is local to the row or borrowed from
        # somewhere else in the document, and that question cannot be asked
        # afterwards from a boolean.
        found = None
        if isinstance(quote, str):
            found = next((s for s in sources if quote_in(s.text or "", quote)),
                         None)
        if found is None:
            row.claim[f"{slot.name}_state"] = UNBACKED
            failed.append({"row": row.label, "why": "quote_not_in_source",
                           "reason": (
                "Dein \"quote\" steht in keiner der gezeigten Quellen. "
                "Kopiere eine Passage Zeichen für Zeichen aus \"sources\" "
                "oder aus dem \"quote\" der Zeile selbst.")})
            unquoted += 1
            continue
        if not evidence_is_local(slot, found, (owner_of or {}).get(row.label)):
            # Refused, and the row stays OPEN. The passage is real and it
            # carries the answer -- it just carries somebody else's. The next
            # window shows other passages, so this is a reason to ask again
            # and not a reason to write the coordinate off.
            row.claim[f"{slot.name}_state"] = UNBACKED
            failed.append({"row": row.label, "why": "quote_not_local",
                           "reason": (
                "Dein \"quote\" steht in einer anderen Quelle als der Zeile "
                "selbst. Zitier aus der Quelle, in der die Zeile steht, oder "
                "aus dem Abschnitt, in dem diese Quelle steht.")})
            unbacked += 1
            continue
        if len(quote.strip()) < MIN_QUOTE_CHARS:
            row.claim[f"{slot.name}_state"] = UNBACKED
            failed.append({"row": row.label, "why": "quote_too_short",
                           "reason": (
                f"Dein \"quote\" ist zu kurz, um eine Stelle zu benennen "
                f"(mindestens {MIN_QUOTE_CHARS} Zeichen). Zitier den ganzen "
                f"Satz oder die ganze Zeile, in der die Antwort steht.")})
            unbacked += 1
            continue
        printed = (column_answer(quote, cell_index(row.claim.get("quote"),
                                                   row.claim.get("value")))
                   if slot.kind == NUMBER else None)
        if (printed is not None
                and quote.strip() != str(row.claim.get("quote") or "").strip()
                and canonical_number(given) not in numbers_in(printed)):
            # The answer is a number this passage prints, and it prints it
            # over a different column than the one the value sits in. Open,
            # not written: the next window is asked again, and this is the
            # question it has to answer.
            row.claim[f"{slot.name}_state"] = UNBACKED
            failed.append({"row": row.label, "why": "wrong column",
                           "given": given, "reason": (
                f"Der Wert dieser Zeile steht in der Spalte, ueber der "
                f"{printed!r} steht, nicht {given!r}. Antworte mit dem, was "
                f"ueber der Spalte DIESES Wertes steht.")})
            unbacked += 1
            continue
        wording = answer.get("value_raw")
        wording = wording.strip() if isinstance(wording, str) and wording.strip() \
            else None
        if not answer_in_quote(slot, given, wording, quote):
            row.claim[f"{slot.name}_state"] = UNBACKED
            shown_answer = wording or given
            failed.append({"row": row.label, "why": "answer_not_in_quote",
                           "given": given, "raw": wording, "reason": (
                f"Dein \"quote\" enthält {shown_answer!r} nicht. Zitier die "
                f"Stelle, an der es wirklich steht, oder antworte mit "
                f"\"{UNSTATED}\".")})
            unbacked += 1
            continue
        row.claim[f"{slot.name}_state"] = READ
        row.claim[slot.name] = given
        if wording:
            row.claim[f"{slot.name}_raw"] = wording
            if not wording_names_option(slot, given, wording):
                # The wording does not say the option that was chosen. Kept,
                # counted and marked, because a mapping the spec did not
                # foresee is the model doing its job and a mapping onto the
                # wrong class is the failure this whole run is about -- and
                # from one corpus run of these we can tell which is which
                # without guessing at the ratio now.
                row.claim[f"{slot.name}_raw_foreign"] = True
                raw_foreign += 1
        elif slot.kind == CHOICE:
            # A choice without the words it was read from cannot be re-mapped
            # when the vocabulary moves: the URI is all that survives, and
            # which wording the model resolved to it is gone. That is the
            # difference between minutes of re-mapping and 93 GPU hours of
            # re-harvesting the corpus, so it is counted rather than shrugged
            # at. The absence of the key IS the marker a later top-up looks
            # for; nothing is invented to fill it.
            raw_missing += 1
        # The passage this one coordinate was read in, kept next to it. A
        # value and its year are two findings, and a graph that cites one
        # sentence for both is citing the wrong one for at least one of them.
        row.claim[f"{slot.name}_quote"] = quote
        row.claim[f"{slot.name}_source"] = [found.owner_kind, found.owner_id]
        if window is not None:
            row.claim[f"{slot.name}_window"] = list(window)
        filled += 1
    return {"filled": filled, "unquoted": unquoted, "unbacked": unbacked,
            "unstated": unstated, "raw_missing": raw_missing,
            "raw_foreign": raw_foreign, "failed": failed}



def line_naming(slot, given, wording, text: str) -> Optional[str]:
    """The line of this passage that carries the answer, or None.

    So that a projected coordinate cites the passage the row itself was read
    from rather than the passage the frame was read from. Both are true, and
    only one of them tells a reader whether the row's own table says it.
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) >= 8 and answer_in_quote(slot, given, wording, line):
            return line
    return None


def apply_frame(rows: list, pair: Optional[dict], index: int,
                slots: list, sources: Optional[list] = None,
                pairs=None) -> int:
    """Write the document's frame onto these rows. Returns coordinates written.

    The pair was read once, for the document, and every row this request
    produced is a row of that pair: the request asked for it by name and
    `in_frame` refused the passages that do not carry it. So the coordinate is
    not asked again per row, it is projected, and the window says `frame` so a
    reader can tell a coordinate that was read for the document from one that
    was read for the row.

    Cited on the row's own passage where that passage names the answer, and on
    the frame's passage otherwise. `read`, not `derived`: `derived` means the
    SPEC decides a coordinate without anybody reading anything, and this is a
    model reading with a passage behind it.

    A coordinate already read is left alone. The frame is what the request
    asked for, but if the row itself carried a better answer the row wins,
    the same rule `merge_field` has and for the same reason.
    """
    if not pair or not slots:
        return 0
    written = 0
    for row in rows:
        source = None
        if sources and 0 <= row.item_index < len(sources):
            source = sources[row.item_index]
        _take, blind = frame_reading(source, pair, index, pairs, slots)
        for slot in slots:
            if slot.name not in pair or slot.name in blind:
                continue
            if row.claim.get(f"{slot.name}_state") == READ:
                continue
            row.claim[slot.name] = pair[slot.name]
            row.claim[f"{slot.name}_state"] = READ
            wording = pair.get(f"{slot.name}_raw")
            if wording:
                row.claim[f"{slot.name}_raw"] = wording
                if (slot.kind == CHOICE
                        and not wording_names_option(slot, pair[slot.name],
                                                     wording)):
                    row.claim[f"{slot.name}_raw_foreign"] = True
            own = line_naming(slot, pair[slot.name], wording,
                              getattr(source, "text", "") or "")
            if own:
                row.claim[f"{slot.name}_quote"] = own
                row.claim[f"{slot.name}_source"] = [source.owner_kind,
                                                    source.owner_id]
            else:
                row.claim[f"{slot.name}_quote"] = pair[f"{slot.name}_quote"]
                row.claim[f"{slot.name}_source"] = list(
                    pair[f"{slot.name}_source"])
            row.claim[f"{slot.name}_window"] = ["frame", index]
            written += 1
    return written

def open_rows(rows: list, slot) -> list:
    """The rows this field still has no reading for.

    Both the never-answered and the answered-with-"not stated": the second is
    only a statement about the passages that were shown, and the next window
    shows different ones. It becomes a statement about the document when the
    windows run out, and not before.
    """
    return [row for row in rows
            if row.claim.get(f"{slot.name}_state") in (None, SAID_UNSTATED,
                                                       UNBACKED)]


def window_sources(pool: list, size: int, overlap: int):
    """Walk a source pool in short overlapping windows.

    Short, not wide. A coordinate that is not in the passage the value came
    from is somewhere else in the plan, and the way to it is more requests
    with little context each, not one request with all of it: the window that
    holds the answer holds it whether or not ninety other passages ride along,
    and the ninety cost the attention that finds it.

    The overlap is why a caption is never cut off from the table it belongs
    to, which is the seam the year lives on.
    """
    size = max(1, size)
    step = max(1, size - max(0, overlap))
    for start in range(0, max(len(pool), 1), step):
        window = pool[start:start + size]
        if not window:
            break
        yield window
        if start + size >= len(pool):
            break


def mark_unanswered(rows: list, slots: list) -> int:
    """Every coordinate no field reply mentioned, named as such. Returns how many.

    The number this exists to expose. Before it, a coordinate the model had
    skipped and a coordinate the document does not state were the same empty
    cell — 16% to 34% of every axis on the 1079-document run, and no way to
    tell which half was the corpus and which half was the harvest. A row that
    reaches this with no state was asked and did not answer, and that is a
    defect of the run, not a property of the plan.
    """
    unanswered = 0
    for row in rows:
        for slot in slots:
            if row.claim.get(f"{slot.name}_state"):
                continue
            row.claim[f"{slot.name}_state"] = UNANSWERED
            unanswered += 1
    return unanswered


def rows_by_item(batch: Batch, rows: list) -> list:
    """The finished claims, grouped back into one list per source."""
    out: list = [[] for _ in batch.items]
    for row in rows:
        out[row.item_index].append(row.claim)
    return out


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


def sweep_key(batch: Batch) -> tuple:
    """What one follow-up budget and one `prior` belong to.

    The document, its parameter and the frame pair the request asks for. The
    same passages are read once per pair, so telling the request for 2035 that
    the request for 2040 already has these numbers tells it to skip its own:
    `prior` says "do not repeat", and two pairs of the same table are not a
    repeat.
    """
    return (batch.document_id, batch_uri(batch), batch.frame_index)


def build_sweeps(batches: list, rounds: int = 1) -> dict:
    """One Sweep per (document, parameter, frame pair), keyed as the batches
    are.

    A document-level plan has no parameter, so the key is the document and the
    follow-up budget is the document's.
    """
    sweeps: dict = {}
    for batch in batches:
        key = sweep_key(batch)
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
    # A query is a sentence a plan could print. "Einheit" is not one:
    # it matches everything and ranks nothing, and retrieval has no way to
    # say so. The same floor the field sweep applies to its own follow-ups.
    asked = [q for q in reply["need_more"]
             if isinstance(q, str) and len(q.strip()) > 20]
    if not asked:
        return []
    extra = more_sources(batch.document_id, asked,
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
    retrieve: Callable,                   # (probes, document_id, exclude) -> [Source]
    harvest: Callable,                    # (Batch, prior) -> reply dict
    locate: Optional[Callable] = None,    # (Source, quote) -> rects | None
    structure: Optional[Callable] = None,   # (document_id) -> [Source]
    more_sources: Optional[Callable] = None,  # (doc, queries, exclude) -> [Source]
    extra_probes: Optional[dict] = None,
    prose_top: int = PROSE_TOP,
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
                                  extra_probes=extra_probes,
                                  retrieve=retrieve, structure=structure,
                                  prose_top=prose_top)
    queue = group_items(items, max_sources=max_sources, max_chars=max_chars)
    sweeps = build_sweeps(queue)
    while queue:
        batch = queue.pop(0)
        sweep = sweeps[sweep_key(batch)]
        reply = harvest(batch, sweep.snapshot())
        reply = reply if isinstance(reply, dict) else {}
        # The follow-up runs first because it is what marks the reply as
        # served, and folding is what counts that.
        if more_sources is not None:
            queue.extend(follow_up(batch, reply, sweep, more_sources,
                                   max_sources=max_sources,
                                   max_chars=max_chars))
        before = len(report.tuples)
        fold_batch(batch, reply, report, locate=locate, spec=spec)
        # Only what survived verification becomes the next batch's `prior`:
        # the prompt tells the model not to repeat what is in there, so a
        # claim the verifier threw away would suppress the same value
        # everywhere else in the document and leave nothing behind.
        sweep.record(report.tuples[before:])
    return report


def fold_claims(item: WorkItem, claims: Optional[list],
                report: DocumentReport, *,
                locate: Optional[Callable] = None,
                spec: Optional[Spec] = None) -> None:
    """Verify one source's claims into the report — the pure half of a harvest.

    The parameter comes from the claim when the plan did not fix one: a
    document-level plan reads a passage once and the field sweep decides, per
    row and with its own quote, which quantity the number is. A claim that
    names no parameter the spec knows cannot be verified against anything and
    is refused rather than folded under a guess.
    """
    source = item.source
    for claim in claims or []:
        parameter = item.parameter
        if parameter is None:
            parameter = (spec.by_uri.get(str(claim.get("parameter") or ""))
                         if spec is not None else None)
        if parameter is None:
            report.refusals.append(
                {"parameter": claim.get("parameter"),
                 "reason": "claim names no parameter of the spec",
                 "claim": claim,
                 "owner": [source.owner_kind, source.owner_id]})
            continue
        finder = ((lambda quote, s=source: locate(s, quote))
                  if locate is not None else None)
        outcome = verify_tuple(claim, parameter, source.text,
                               owner_kind=source.owner_kind, locate=finder,
                               repair_text=source.body)
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


def batch_uri(batch: Batch) -> Optional[str]:
    """The parameter a batch was planned for, or None for a document plan.

    Public because the parallel scheduler in the runner keys the same sweeps
    by the same thing. It was not, and the runner reached through
    `batch.parameter.uri` in three places, which is how a plan that had
    correctly dropped 825 sources to 162 died on its first batch.
    """
    return batch.parameter.uri if batch.parameter is not None else None


def fold_batch(batch: Batch, reply: Optional[dict], report: DocumentReport, *,
               locate: Optional[Callable] = None,
               spec: Optional[Spec] = None) -> None:
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
        fold_claims(item, claims, report, locate=locate, spec=spec)
    for claim in orphans:
        # Named no source of this batch and quoted none of them either. There
        # is no text to check it against, so there is no way to accept it.
        report.refusals.append(
            {"parameter": batch_uri(batch), "reason": "claim names no source",
             "claim": claim,
             "owner": [batch.items[0].source.owner_kind,
                       batch.items[0].source.owner_id]})
    counts = report.followups.setdefault(
        batch_uri(batch) or "document", {"asked": 0, "served": 0})
    if reply.get("status") == "partial" and reply.get("need_more"):
        counts["asked"] += 1
    if reply.get("_served"):
        counts["served"] += 1
    # Counted here, not frozen at plan time: a follow-up brings passages the
    # plan never knew about, and a report that says "N owners harvested"
    # while having read more than N cannot be used to audit coverage.
    if batch.followed_up:
        report.owners_harvested += len(batch.items)


def fold_fieldwise(batch: Batch, rows: list, orphans: list,
                   report: DocumentReport, *,
                   locate: Optional[Callable] = None,
                   spec: Optional[Spec] = None) -> None:
    """Verify a field-wise batch into the report.

    By the time this runs the rows carry every coordinate a field request
    could evidence, so what is left is exactly what fold_batch does: hand each
    source its claims and let verify decide. The difference is upstream — a
    coordinate that is empty here is empty because a request asked for it and
    the passage did not say, not because a sixteen-field answer skipped it.
    """
    for item, claims in zip(batch.items, rows_by_item(batch, rows)):
        fold_claims(item, claims, report, locate=locate, spec=spec)
    for claim in orphans:
        claim = dict(claim)
        why = claim.pop("_why", "claim names no source")
        report.refusals.append(
            {"parameter": batch_uri(batch), "reason": why,
             "claim": claim,
             "owner": [batch.items[0].source.owner_kind,
                       batch.items[0].source.owner_id]})
    if batch.followed_up:
        report.owners_harvested += len(batch.items)


def write_report(report: DocumentReport, out_path: Path,
                 own: Optional[frozenset] = None,
                 states: Optional[list] = None) -> None:
    """Tuples, refusals, parameter states and one summary, written atomically.

    Refusals are rows too (kind=refusal): the file is the audit trail, and an
    audit that only shows the survivors cannot answer why a value is missing.

    The last line (kind=summary) is the distribution over this document's own
    values, so "how much of this plan can I use" has an answer that does not
    require reading 559 rows. It goes last because it is computed from
    everything above it. `own` names the axes whose evidence rule is
    `own` (spec.own_evidence); without it the summary holds every coordinate
    to the row's own source, which over-reports on a harvest written under
    the rule.

    `states` is one line per PARAMETER (kind=parameter_state). Every other
    state in this file belongs to a row, so a parameter that produced no row
    left nothing behind at all, and "the document does not carry it" read
    exactly like "we never got round to asking".
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
        for record in states or ():
            handle.write(json.dumps(
                {"kind": "parameter_state",
                 "document_id": report.document_id, **record},
                ensure_ascii=False) + "\n")
        handle.write(json.dumps(
            {"kind": "summary",
             **document_summary(report.document_id, report.tuples,
                                report.refusals, own=own)},
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
