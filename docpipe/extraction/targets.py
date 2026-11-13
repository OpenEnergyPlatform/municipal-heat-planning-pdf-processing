"""
targets.py: What becomes of the answer of "Ask the model" (owner decision
2026-11-12 evening, plan "modell_fragen", point 5).

A step of "Ask the model" names its target (`Target`): a variable; values of
a field, kept at once or gathered over the rounds of a field of the whole
document; a dimension of a value, at its own place or over the search hits;
a search sentence; and the questions asked inside the answer of another, a
list entry, a name of the document's list, the plan's year of a wording,
whether a place speaks about the value. A target checks an answer as the
reading always has (the line was shown, the answer stands in it, a list's
answer is one of its entries) and asks again with what did not hold; it
adds no check and no reason of refusal.

A target goes the ways its question goes: the search hits taken a few a
request, a request whose answer did not fit its room asked in halves of its
chunks, what an answer asks to see shown first in the next request, the
picture of a figure asked once a value. A profile adds its own targets
(`profiles/<name>/blocks.py: TARGETS`).

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import json
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from .. import rules
from . import addressed, conditions, forms, shows
from .addressed import (Asking, CUT, NO_ANSWER, asked_more, joined,
                        refusals, resolve, second_ways)
from .fields import READ, UNBACKED
from .units import letters_others

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Target:
    """One target: its name and what the page calls it and says of it, the
    code that asks and takes the answer, run(ask, counts) -> what the
    question came to (`engine.Answer`) or None; *nested* for a question the
    target of another asks inside its answer, which no frame runs; the
    variables it gives the request besides those of the flow (*gives*), and
    the forms its answer may have (*forms*, () for any)."""
    name: str
    label: str
    says: str
    run: Optional[Callable] = None
    nested: bool = False
    gives: tuple = ()
    forms: tuple = ()
    profile: str = ""
    # What it makes for the steps after it (`flow.outputs_of`).
    outputs: tuple = ("answer",)
    # Its request is asked apart from the reading of a document, from what
    # it gives alone: the lines of a figure before the chunks are cut, the
    # sentence a field's chunks are ordered by.
    apart: bool = False
    # What a condition of its step tells of, where not what is known where
    # the step stands: the figure, for a step asked once a figure.
    facts: tuple = ()
    # What it does in the flow of a follow-up pass, pass_run(run, doc,
    # node) (`passflow.act_of`); None where no run starts it there.
    pass_run: Optional[Callable] = None


def _answer(*args, **kwargs):
    from .engine import Answer
    return Answer(*args, **kwargs)


def came_to(ask, counts) -> dict:
    return ask.engine.came_to(counts)


# -- a variable --------------------------------------------------------------------

def to_var(ask, counts):
    """The answer kept as the step's variable, after the step's own checks:
    one whose condition holds of the answer is asked again with its
    sentence, as often as the step's follow-ups say (owner 2026-11-12:
    "eine extra Prüfung ... auf einfachem Niveau"). Where the step lets
    the model ask to see more, it is asked again with what it asked to see
    (`fetched_again`)."""
    from .general import example_of, joined_facts, put, var_facts, PAGE
    engine, reader = ask.engine, ask.reader
    req = ask.request()
    shape, example = forms.of(ask.reply, req, more=ask.fetch)
    reply = ask.ask(req, shape, example, counts)
    if ask.fetch and isinstance(reply, dict):
        reply = fetched_again(ask, req, shape, example, reply, counts)
    name = ask.into.get("var") or ask.node.get("id")
    checks = engine.own_checks(ask.node)
    scope = ask.scope
    for _ in range(reader.follow_ups() + 1):
        if not isinstance(reply, dict):
            break
        put(scope, name, reply, False)
        facts = joined_facts(engine.facts(scope), var_facts(scope))
        failed = [(sentence, label) for label, condition, sentence, _i
                  in checks if conditions.holds(condition, facts)]
        if not failed:
            break
        for _sentence, label in failed:
            counts.fail(f"check:{label}")
        reply = ask.follow(req, shape, example_of(ask.reply)
                           if isinstance(ask.reply, dict) else example,
                           reply, [{"why": sentence} for sentence, _label
                                   in failed], counts)
    value = reply if isinstance(reply, dict) else None
    lasting = bool(ask.into.get("lasting"))
    put(scope, name, value, lasting)
    if lasting:
        scope.values.pop(PAGE + name, None)
    words = ""
    if isinstance(value, dict):
        first = next(iter(value.values()), "")
        words = first if isinstance(first, str) else json.dumps(
            first, ensure_ascii=False)
    return _answer(value is not None, 1 if value else 0, not value, False,
                   words, "", **came_to(ask, counts))


def fetched_again(ask, req, shape: dict, example, reply, counts):
    """A reply asked again with the chunks it asked to see, each under a
    letter of its own, as often as the rule `fetch_rounds` says (owner
    decision 2026-11-12: where the document points to a missing detail,
    the model may fetch that place itself)."""
    reader, plan = ask.reader, ask.plan
    anchor = list(req.chunks)
    seen = {chunk.key for chunk in req.chunks}
    for _ in range(int(rules.get("fetch_rounds"))):
        more = asked_more(reply)
        if not more or not anchor:
            break
        pieces = reader.fetch(plan, more, anchor, seen, False)
        if not pieces:
            break
        seen.update(chunk.key for chunk in pieces)
        blocks = reader.show_fetched(plan, req.shown, pieces)
        req.payload = {**req.payload, "passages": {
            **(req.payload.get("passages") or {}), **blocks}}
        again = ask.ask(req, shape, example, counts, fetched=len(pieces))
        if not isinstance(again, dict):
            break
        reply = again
    return reply


# -- values of a field ---------------------------------------------------------------

def chunk_notes(chunk) -> dict:
    """What the log notes of the chunk a request shows: its passage, its
    place and, for a piece of several passages, how many it has."""
    members = list(chunk) if isinstance(chunk, (list, tuple)) else None
    first = members[0] if members else chunk
    return {"kind": first.passage.kind,
            "owner": first.passage.source.owner_id, "chunk": first.index,
            **({"chunks": len(members)} if members else {})}


def values(ask, counts):
    """Values of a field: each the address of its line and its words,
    checked as every value is, what did not hold asked again with why.
    Kept at once in the read of the passage they stand in (*keep* "now",
    the values of a chunk), or gathered over the rounds of a field of the
    whole document and kept when its frame is through (*keep*
    "gathered")."""
    if ask.into.get("keep") == "gathered":
        return gathered(ask, counts)
    return at_once(ask, counts)


def at_once(ask, counts):
    """The values a chunk holds (`find`). A request whose answer did not
    fit its room is asked in halves of its own lines, each with the lines
    every piece of its passage shows, until a single line is a hole of its
    own (owner decision 2026-09-12: a request is split, never its answer
    rescued); a piece of several passages is halved by its passages
    first."""
    reader = ask.reader
    parameter = ask.field()
    spec = ask.chunk_input()
    name = str((spec or {}).get("from") or "chunk").split(".")[0]
    chunk = ask.source(spec)
    out = {"claims": [], "asked": 0, "failed": collections.Counter(),
           "lost": [], "elsewhere": [],
           "members": list(chunk) if isinstance(chunk, (list, tuple))
           else [chunk]}
    pending = [(list(chunk) if isinstance(chunk, (list, tuple))
                else [chunk], 0)]
    while pending:
        piece, depth = pending.pop(0)
        got = _values_once(ask, parameter, name,
                           piece[0] if len(piece) == 1 else piece, counts)
        out["asked"] += got["asked"]
        out["claims"] += got["claims"]
        out["elsewhere"] += got["elsewhere"]
        out["failed"].update(got["failed"])
        if got["lost"] == CUT:
            halves = reader.halves(piece, depth)
            if halves:
                pending[:0] = [(half, depth + 1) for half in halves]
                continue
        if got["lost"]:
            out["lost"].append(got["lost"])
    ask.engine.keep_finds(ask.scope, parameter, out)
    claims = out["claims"]
    return _answer(not out["lost"] or bool(claims), len(claims),
                   not claims, False,
                   str((claims[0].get("value_raw") or claims[0].get("value")
                        or "") if claims else ""),
                   claims[0].get("quote", "") if claims else "",
                   **came_to(ask, counts))


def _values_once(ask, parameter, name: str, chunk, counts) -> dict:
    """The values of one request over *chunk*: {"claims", "asked",
    "failed", "lost", "elsewhere"}. What does not hold is asked again with
    its reason (as often as the flow says), then left."""
    reader, plan = ask.reader, ask.plan
    req = ask.request({name: chunk})
    listed = req.listed
    shape, example = forms.of(ask.reply, req, closed=listed is not None,
                              more=ask.fetch,
                              at=ask.setting("example_at"))
    noted = {"parameter": parameter.uri, **chunk_notes(chunk)}
    out = {"claims": [], "asked": 1, "failed": collections.Counter(),
           "lost": None, "elsewhere": []}
    reply = ask.ask(req, shape, example, counts, **noted)
    if not isinstance(reply, dict):
        out["lost"] = CUT if reply == CUT else NO_ANSWER
        return out
    held, refused = reader._finds(plan, req.shown, reply, listed,
                                  parameter.is_numeric)
    out["failed"].update(why for _, why in refused)
    for _, why in refused:
        counts.fail(why)
    for _ in range(reader.follow_ups()):
        if not refused:
            break
        reply = ask.follow(req, shape, example, reply, refusals(refused),
                           counts, **noted)
        out["asked"] += 1
        if not isinstance(reply, dict):
            break
        more, refused = reader._finds(plan, req.shown, reply, listed,
                                      parameter.is_numeric)
        held = joined(held, more)
    for got in held:
        claim = reader.claim(plan, parameter, got, counts)
        if claim is not None:
            out["claims"].append(claim)
            if got.elsewhere:
                # Its place is another passage (`Found.elsewhere`).
                out["elsewhere"].append(claim)
    return out


def gathered(ask, counts):
    """A field of the whole document asked over its search hits, a few a
    request (`docfield`, owner decision 2026-11-08): what each request
    finds is gathered with what the requests before it found, and kept
    when the field's frame is through (`engine.Engine.field_reads`). A
    request whose answer did not fit its room is asked in halves, and what
    an answer asks to see comes first in the field's next request (owner
    decision 2026-11-12)."""
    reader, plan = ask.reader, ask.plan
    item = ask.scope.get("field_item")
    req = ask.request()
    if req.used_up or req.batch is None:
        ask.scope.used_up()
        return None
    batch = list(req.batch)
    item.asked_by = ask.node["id"]
    if item.first_source is None and batch:
        item.first_source = batch[0].passage.source
    held_all: list = []
    lost_all = None
    wanted: list = []
    pending = [(batch, 0, req)]
    while pending:
        piece, depth, one = pending.pop(0)
        if one is None:
            one = ask.request(batch=piece, first=req.first)
        held, lost, more = _gathered_once(ask, item, one, counts)
        if lost == CUT:
            halves = reader.halves(piece, depth)
            if halves:
                pending[:0] = [(half, depth + 1, None) for half in halves]
                continue
        if lost:
            lost_all = lost_all or lost
        held_all = joined(held_all, held)
        wanted += more
    if wanted:
        supply = ask.scope.get("supply")
        supply.fetched = reader.fetch(plan, wanted, batch, supply.seen,
                                      item.numbers)
    if lost_all is not None:
        item.lost = item.lost or lost_all
    # The finds of the parts that were read count even where another part
    # of the request was a hole (as at once).
    item.found = joined(item.found, held_all)
    return _answer(lost_all is None or bool(held_all), len(held_all),
                   not held_all, False,
                   held_all[0].words if held_all else "",
                   held_all[0].quote if held_all else "",
                   **came_to(ask, counts))


def _gathered_once(ask, item, req, counts) -> tuple:
    """([Found] that hold, lost, what it asks to fetch) of one request of a
    field of the whole document."""
    reader, plan = ask.reader, ask.plan
    listed = item.listed
    shape, example = forms.of(ask.reply, req, closed=listed is not None,
                              more=ask.fetch, at=ask.setting("example_at"))
    reply = ask.ask(req, shape, example, counts, parameter=item.key,
                    chunks=len(req.batch))
    if not isinstance(reply, dict):
        return [], (CUT if reply == CUT else NO_ANSWER), []
    wanted = asked_more(reply)
    held, refused = reader._finds(plan, req.shown, reply, listed,
                                  item.numbers)
    for _, why in refused:
        counts.fail(why)
    for _ in range(reader.follow_ups()):
        if not refused:
            break
        reply = ask.follow(req, shape, example, reply, refusals(refused),
                           counts, parameter=item.key)
        if not isinstance(reply, dict):
            break
        wanted += asked_more(reply)
        more, refused = reader._finds(plan, req.shown, reply, listed,
                                      item.numbers)
        held = joined(held, more)
    return held, None, wanted


# -- a dimension of a value -------------------------------------------------------

def coord_notes(coord) -> dict:
    """What the log notes of a request about a value's dimension."""
    claim = coord.row.claim
    return {"parameter": coord.read.batch.parameter.uri,
            "coordinate": coord.slot.name,
            "owner": ((claim.get("at") or {}).get("owner")
                      or [None, None])[1], "value": coord.row.label}


def dimension(ask, counts):
    """A dimension of a value read from the line an answer names: at the
    value's own place (*where* "own"), or over the search hits a few a
    request (*where* "hits"). Its finds are each read onto the value's row,
    one row per entry where several are named, and checked
    (`pipeline.merge_field`); what does not hold is asked again with its
    reason, then stays unbacked. The answer may ask for the picture of a
    figure the request shows, once a value (owner decision 2026-11-12)."""
    if ask.into.get("where") == "hits":
        return over_hits(ask, counts)
    return at_own_place(ask, counts)


def at_own_place(ask, counts):
    """A dimension asked at its value's own place (`coord`): its line with
    the head of its table or the sentences beside it, the headings up to
    it, the title page and the plan's settings; the answer an address and
    words, or 0. Not answered where the value has no place or no answer
    came. What the answer asks to see comes first in the search after it
    (owner decision 2026-11-12)."""
    reader, plan, engine = ask.reader, ask.plan, ask.engine
    coord = ask.scope.get("coord")
    read, row, slot = coord.read, coord.row, coord.slot
    noted = coord_notes(coord)
    answered, made, more = False, [], []
    if shows.has_place(plan, row.claim):
        req = ask.request()
        several = reader.several(slot)
        seen = coord.pictures
        pictures = reader.pictures(req.shown, seen) if ask.picture else {}
        shape, example = forms.of(ask.reply, req, several=several,
                                  more=ask.fetch, image=bool(pictures))
        reply = ask.ask(req, shape, example, counts, **noted)
        with ask.prompting():
            reply = reader.with_picture(ask.kind, req.payload,
                                        plan.document_id, several, example,
                                        counts, reply, pictures, seen, noted)
        if isinstance(reply, dict):
            with ask.prompting():
                made, held, more = reader.take(
                    plan, read, row, slot, req.shown, reply, req.payload,
                    ask.kind, example, counts, coord.clone, ("own", 1),
                    noted)
            answered = True
            more = [] if held else more
        else:
            coord.unanswered = True
    coord.made += made
    state = row.claim.get(f"{slot.name}_state")
    if more and state != READ:
        engine.locate(coord, plan)
        if coord.chunk is not None:
            coord.fetched = reader.fetch(plan, more, [coord.chunk],
                                         coord.seen,
                                         read.batch.parameter.is_numeric)
    return _answer(answered, 1 if state == READ else 0, state != READ,
                   False, **came_to(ask, counts))


def over_hits(ask, counts):
    """A dimension asked over the search hits (`search`): the value's place
    and the next hits under letters of their own. A find from another
    passage is kept only where the step after it that checks says the
    place speaks about the value (`keep_find`)."""
    from .engine import SearchSupply
    reader, plan, engine = ask.reader, ask.plan, ask.engine
    coord = ask.scope.get("coord")
    supply = ask.scope.get("supply")
    read, row, slot = coord.read, coord.row, coord.slot
    engine.locate(coord, plan)
    if not isinstance(supply, SearchSupply):
        ask.scope.used_up()
        return None
    req = ask.request()
    if req.used_up or not req.batch:
        ask.scope.used_up()
        return None
    batch, label = req.batch, req.label
    numbers = read.batch.parameter.is_numeric
    ways = sorted(set(coord.ways) | supply.ways)
    noted = {**coord_notes(coord), "shows": label,
             **second_ways(ways)}
    several = reader.several(slot)
    seen = coord.pictures
    pictures = reader.pictures(req.shown, seen) if ask.picture else {}
    shape, example = forms.of(ask.reply, req, several=several,
                              more=ask.fetch, image=bool(pictures))
    reply = ask.ask(req, shape, example, counts, **noted, chunks=len(batch))
    with ask.prompting():
        reply = reader.with_picture(ask.kind, req.payload, plan.document_id,
                                    several, example, counts, reply,
                                    pictures, seen,
                                    {**noted, "chunks": len(batch)})
    made, held, more = [], False, []
    if not isinstance(reply, dict):
        coord.unanswered = True
    if isinstance(reply, dict):
        own = tuple((row.claim.get("at") or {}).get("owner") or ())
        keeper = engine.attached_of(ask.node, "keep_find")
        kept = []
        for entry in reader.coord_finds(reply):
            got = resolve(req.shown, entry, plan.passages)
            if got.why is None and got.letter in letters_others() \
                    and got.source is not None \
                    and (rules.get("about_other") == "any"
                         or (got.source.owner_kind, got.source.owner_id)
                         != own) \
                    and keeper is not None \
                    and not keep_find(ask, keeper, got, counts, noted):
                continue
            kept.append(entry)
        more = asked_more(reply)
        if kept:
            # The first find alone is the answer where the rule says so:
            # the list of finds a reply may still carry is not read
            # besides it.
            answer = {**reply, "found": kept} \
                if several or rules.get("search_finds_taken") == "all" \
                else {**{key: value for key, value in reply.items()
                         if key != "found"}, **kept[0]}
            with ask.prompting():
                made, held, wanted = reader.take(
                    plan, read, row, slot, req.shown, answer, req.payload,
                    ask.kind, example, counts, coord.clone,
                    (supply.label, 1), noted)
            more = [] if held else wanted
    state = row.claim.get(f"{slot.name}_state")
    found = bool(held) or state == UNBACKED
    if found:
        coord.made += made
    if found and not rules.get("fetch_after_found"):
        supply.fetched = []
    else:
        supply.fetched = reader.fetch(
            plan, more, batch,
            {c.key for c in batch} if rules.get("show_twice")
            else coord.seen, numbers)
    return _answer(True, 1 if held else 0, not held, False,
                   **came_to(ask, counts))


def keep_find(ask, keeper: dict, got, counts, noted: dict) -> bool:
    """Does the place a find of another passage stands in speak about this
    value (`check`, owner decision 2026-11-07)? Asked as the step that
    checks says, in its own values (`about_no_reply`)."""
    from .general import Ask
    engine, reader, plan = ask.engine, ask.reader, ask.plan
    what = addressed.ASKING.get()
    with engine.step(keeper):
        sub = Ask(engine, keeper, ask.scope, {"find": got}, plan)
        if not sub.asks():
            return True
        req = sub.request()
        shape, example = forms.of(sub.reply, req)
        with addressed.asking(Asking(
                keeper.get("id"), follow_ups=what.follow_ups
                if what is not None else None, scope=ask.scope)):
            reply = sub.ask(req, shape, example, counts, **noted)
        if not isinstance(reply, dict):
            return rules.get("about_no_reply") == "keep"
        return reply.get("about") == "yes"


# -- a search sentence ------------------------------------------------------------------

def sentence(ask, counts):
    """The sentence the search of a dimension goes with (`phrase`, owner
    decision 2026-11-09): as the document would print the answer for this
    value (HyDE), written once per document, field, dimension and wording
    of the value; a question where the rule `question_as_sentence` takes
    none is the field's own sentence instead, and a question taken is
    counted. The rule `search_with` may take the dimension's question or
    name instead, with no request."""
    coord = ask.scope.get("coord")
    before = shows.sentences_before(ask, coord)
    written = search_sentence(ask, coord, counts, before or None)
    coord.sentence = written
    coord.sentences.append(written)
    if rules.get("search_with") != "phrase":
        coord.ways.append("search_with")
    return None


def search_sentence(ask, coord, counts, before: Optional[list]) -> str:
    reader, plan = ask.reader, ask.plan
    read, row, slot = coord.read, coord.row, coord.slot
    how = rules.get("search_with")
    if how == "question":
        return slot.question or slot.name
    if how == "name":
        return slot.name
    parameter = read.batch.parameter
    words = str(row.claim.get("value_raw") or row.claim.get("value") or "")
    key = ("phrase", parameter.uri, slot.name,
           addressed.flat(words).casefold(), tuple(before or ()))
    if not before:
        key = key[:4]
    with plan.key_lock(key):
        if key not in plan.lists:
            plan.lists[key] = _written(ask, coord, counts)
        written = plan.lists[key]
    if not written:
        written = reader.fallback(plan, parameter, slot)
    if addressed.is_question(written) \
            and not rules.get("question_as_sentence"):
        written = reader.field_sentence(plan, read, slot)
    if addressed.is_question(written):
        counts.question()
        log.info("   search of %s/%s in document %s with a question: %s",
                 parameter.uri, slot.name, plan.document_id, written)
    return written


def _written(ask, coord, counts) -> str:
    if not ask.asks():
        return ""
    req = ask.request()
    shape, example = forms.of(ask.reply, req)
    reply = ask.ask(req, shape, example, counts,
                    parameter=coord.read.batch.parameter.uri,
                    coordinate=coord.slot.name)
    phrase = reply.get("phrase") if isinstance(reply, dict) else ""
    return phrase.strip() if isinstance(phrase, str) else ""


# name -> Target; a profile's are added when the library is read
# -- what prepares the reading -----------------------------------------------

def figure_lines(ask, counts):
    """The lines of the figure in the variable "figure": its caption
    (title, axes, legend), then its numbers, written out once from its
    picture (owner decisions 2026-11-08, e, and 2026-11-09) and kept for
    the run (`addressed.Transcripts`, `engine.Engine.plan`): the reply, or
    None where its picture cannot be sent, for a figure is written out
    from its picture or not at all."""
    from .general import raw
    req = ask.request()
    if addressed.PICTURE not in req.payload:
        return None
    figure = raw(ask.scope, "figure")
    shape, example = forms.of(ask.reply, req)
    return ask.ask(req, shape, example, counts, kind="figure",
                   owner=figure.owner_id)


def chunk_order(ask, counts):
    """The order in which each field read chunk by chunk goes through the
    chunks: ranked by a sentence the model writes for the field as this
    document would print a value of it (owner decisions 2026-11-05 and
    2026-11-09), made once a field and kept with the harvest
    (`addressed.Orders`); its request (`runner.document_anchor`) is built
    from this step's inputs."""
    doc = ask.doc
    if doc is None or doc.order_fields is None:
        return None
    located = [p for p in doc.parameters
               if not getattr(p, "once_per_document", False)]
    if located:
        doc.order_of = dict(doc.order_fields(located) or {})
    return None


# -- after the reading, and in the passes -------------------------------------

def review_marks(run, doc, node) -> None:
    """Each row of the trust levels in the rule read a second time
    (`passboxes.box_review`), its request built from the step's inputs
    (`runner.make_review_asker`)."""
    from .passboxes import box_review
    box_review(run, doc, node)


TARGETS: dict = {target.name: target for target in (
    Target("var", "a variable",
           "The answer as a variable of the step's name, for this item or "
           "for the whole document; checked by the own checks after the "
           "step.", to_var),
    Target("figure_lines", "the lines of a figure",
           "The figure written out as lines, first its caption (title, "
           "axes, legend), then its numbers, once a run and kept with the "
           "harvest; later questions read the figure from these lines. "
           "Asked for each figure before the document is cut into chunks.",
           figure_lines, gives=("figure",), forms=("lines",),
           outputs=("figure_lines",), apart=True, facts=("figure",)),
    Target("chunk_order", "the order of the chunks of each field",
           "The chunks of each field read chunk by chunk, ordered by how "
           "well they match a sentence the model writes for the field, best "
           "first; made once a field and kept with the harvest. The "
           "sentence is asked from the field and what the document says of "
           "itself alone.", chunk_order, gives=("field", "context"),
           forms=("phrase",), outputs=("order",), apart=True),
    Target("computed", "a computed value",
           "A value the code the model writes works out of the document's "
           "values, with the code, its output and its input numbers as "
           "proof; asked once a document is read, for each question the "
           "profile computes, from the question alone.", gives=("question",),
           forms=("compute",), outputs=("rows",), apart=True),
    Target("review_marks", "the mark of a second reading",
           "A row read a second time over its passages: agree, disagree or "
           "unbacked, and what the second reading said in the working "
           "list; asked for each row of a pass, from the row alone.",
           gives=("row",), forms=("review",), outputs=(), apart=True,
           pass_run=review_marks),
    Target("example_proposal", "a proposed example",
           "The values one passage holds of a field of a draft spec, "
           "proposed as its example; asked while a spec is compiled, from "
           "the field and the passage alone.", gives=("field", "passage"),
           forms=("example",), outputs=(), apart=True),
    Target("values", "values of a field",
           "Values of a field of the Spec, each with the line it stands in, "
           "checked as every value is; kept at once, or gathered over the "
           "rounds of a field of the whole document.", values,
           forms=("finds",), outputs=("answer", "values")),
    Target("dimension", "a dimension of the value",
           "The dimension of the value the answer's line says, at the "
           "value's own place or over the search hits; checked as every "
           "dimension is, then its list entry or name; unbacked where the "
           "line does not carry it.", dimension, forms=("place",)),
    Target("sentence", "the search sentence",
           "The sentence the search of the dimension goes with, written "
           "once per field, dimension and wording.", sentence,
           forms=("phrase",), outputs=("sentence",)),
    Target("keep_find", "keep a find or not",
           "Whether a find from another place speaks about the value: the "
           "search keeps it only on yes.", nested=True,
           gives=("find",), forms=("yes_no",)),
    Target("entry", "the entry of a list",
           "The entry of a list the words of an answer mean, once per "
           "wording; a long list with groups in two steps.", nested=True,
           gives=("words", "find", "options", "earlier", "dimension"),
           forms=("entry",)),
    Target("plan_year", "the plan's year of a wording",
           "The year among the plan's base and target years that a "
           "wording such as \"Zieljahr\" means.", nested=True,
           gives=("words", "find", "options", "dimension"),
           forms=("entry",)),
    Target("name", "an entry of the document's list of names",
           "The entry of the document's list of names a name means, a new "
           "entry where it is not on the list yet, none for 0; once per "
           "name and work.", nested=True,
           gives=("words", "find", "work", "options"), forms=("name",)),
)}


def register(target: Target) -> None:
    """A target of a profile (`profiles/<name>/blocks.py: TARGETS`)."""
    held = TARGETS.get(target.name)
    if held is not None and held.profile != target.profile:
        raise ValueError(f"profile {target.profile!r} has a target "
                         f"{target.name!r}, which {held.profile or 'the core'}"
                         f" has already")
    TARGETS[target.name] = target


def targets_catalogue() -> dict:
    return {name: {"label": t.label, "says": t.says, "nested": t.nested,
                   "gives": list(t.gives), "forms": list(t.forms),
                   "profile": t.profile, "apart": t.apart,
                   "outputs": list(t.outputs)}
            for name, t in TARGETS.items()}
