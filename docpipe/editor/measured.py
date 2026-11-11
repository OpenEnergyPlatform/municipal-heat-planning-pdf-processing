"""
measured.py: What the requests of a harvest's traces say about the numbers of
the flow.

A number of the flow was set at least once without knowing what the runs
before did under it. The traces know (`extraction.trace`): every request of
a document with what it showed and what came back. This module counts from
them what bears on a number, and says it as a sentence that names what it
counts: after how many shown pieces a search ended with an answer that
names a place (so how many of those answers a smaller budget would have
come too late for), at which attempt a reply was read, how many answers
were asked again, how long the lists were that requests showed.

Nothing here reads a file: it takes the requests `requests.Trace` made of a
trace. Nothing here says whether an answer held; a trace does not record
that. So a sentence speaks of "an answer that names a place", never of a
value read.

Which pieces of a search count toward its budget is noted with each of its
requests since 2026-11-10 (`shows`: "found" for those of the budget, "near"
for the pieces beside the value, "fetched" for those the model asked for
itself). A trace written before says nothing of it; for such a trace the
pieces of every request of a search are counted, and `notes` says so.

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import json
import statistics
from typing import Optional

from ..extraction.spec import PLAN_FIELDS

# The notes that say which value's search a request belongs to.
SEARCH = ("doc", "parameter", "coordinate", "owner", "value")
# What a request of a search shows, its trace's `shows` (`engine.SearchSupply`).
FOUND, NEAR = "found", "near"


def step_of(request: dict) -> Optional[str]:
    """The box of the default drawing a recorded request that names no box
    of its own (`box`, written since 2026-11-11) was asked in, by its kind;
    None for a request of no box. A follow-up is its question's, which
    `facts` gives by the kind it follows."""
    kind = request.get("kind")
    if kind == "phrase":
        return "search_sentence" if request.get("coordinate") else "sentences"
    if kind == "docfield":
        return "settled" if request.get("parameter") in PLAN_FIELDS \
            else "document_fields"
    if kind == "search":
        return "beside" if request.get("shows") == NEAR else "search"
    if kind == "list":
        return "plan_years" if request.get("step") == "plan_years" \
            else "quantity"
    return {"transcribe": "figures", "work": "works", "find": "finds",
            "coord": "own_place", "check": "about", "names": "name",
            "compute": "compute"}.get(kind)


# Every id `step_of` can give, for the test that holds them to the default
# drawing.
STEPS = ("figures", "sentences", "settled", "works", "document_fields",
         "finds", "own_place", "beside", "search_sentence", "search", "about",
         "plan_years", "quantity", "name", "compute")


def names_place(answer) -> bool:
    """Does an answer name a line of what its request showed: an address
    other than 0, or a find with one?"""
    def place(at) -> bool:
        return at not in (None, "", 0, "0")
    if not isinstance(answer, dict):
        return False
    if isinstance(answer.get("found"), list):
        return any(isinstance(entry, dict) and place(entry.get("at"))
                   for entry in answer["found"])
    return place(answer.get("at"))


def _shown(request: dict) -> int:
    try:
        return int(request.get("chunks") or 0)
    except (TypeError, ValueError):
        return 0


def _list_shown(request: dict) -> Optional[int]:
    """How many entries the list has that a request shows, None where it
    shows none: as `light` noted it, else read from the request's message."""
    if "list_length" in request:
        return request["list_length"]
    try:
        payload, _ = json.JSONDecoder().raw_decode(request.get("user") or "")
    except ValueError:
        return None
    shown = payload.get("list") if isinstance(payload, dict) else None
    return len(shown) if isinstance(shown, list) else None


def light(events) -> list:
    """The requests among a trace's *events* as far as `facts` reads them,
    without putting any request back together (`requests.requests_of` does
    that, and holds every prompt and passage of a document for it): the
    notes of each, its answer, whether its reply could not be read, and how
    long the list is that its message shows. A harvest of many documents is
    counted from this."""
    out: list = []
    pieces: dict = {}
    before = None               # the event before, pieces aside
    for event in events:
        kind = str(event.get("t", ""))
        if kind == "piece":
            pieces[event.get("id")] = event.get("text")
            continue
        if kind == "error" and event.get("kind") == "unreadable" and out \
                and before is out[-1].get("_event") \
                and event.get("where") == out[-1]["kind"]:
            out[-1]["check"] = f"unreadable: {event.get('cause')}"
        before = event
        if not kind.endswith("_ask"):
            continue
        output = event.get("output")
        content = output.get("content") if isinstance(output, dict) else None
        answer = content if isinstance(content, str) and content.strip() \
            else None
        try:
            parsed = json.loads(answer) if answer else None
        except ValueError:
            parsed = None
        request = {key: value for key, value in event.items()
                   if key not in ("input", "output", "t", "kind")}
        request.update(kind=kind[:-4], answer=answer, check="",
                       answer_json=parsed if isinstance(parsed, (dict, list))
                       else None,
                       list_length=_list_in(event, pieces), _event=event)
        out.append(request)
    for request in out:
        request.pop("_event")
    return out


def _list_in(event: dict, pieces: dict) -> Optional[int]:
    """How many entries the list has in the message of a traced request,
    None where its message is no object with a list (`trace.sent`: a
    message that is a JSON object is traced by its keys, the long ones as
    references to pieces)."""
    given = event.get("input")
    for message in (given.get("messages") or ()) \
            if isinstance(given, dict) else ():
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        shown = None
        if isinstance(content, dict) and isinstance(content.get("json"),
                                                    dict):
            if "list" in (content.get("pieces") or {}):
                try:
                    shown = json.loads(
                        pieces.get(content["pieces"]["list"]) or "null")
                except ValueError:
                    shown = None
            else:
                shown = content["json"].get("list")
        elif isinstance(content, (str, dict)):
            text = content if isinstance(content, str) \
                else pieces.get(content.get("piece")) or ""
            try:
                payload, _ = json.JSONDecoder().raw_decode(text)
            except ValueError:
                payload = None
            shown = payload.get("list") if isinstance(payload, dict) \
                else None
        return len(shown) if isinstance(shown, list) else None
    return None


def after(positions, bound: int) -> int:
    """How many of *positions* lie beyond *bound*: the answers that came
    only after more than *bound* pieces (or attempts) and so would have
    come too late under it."""
    return sum(1 for position in positions if position > bound)


def facts(requests: list) -> dict:
    """What the requests of one trace say, counted once whatever the
    numbers asked about:

    - "requests": how many, and "steps": how many per box of the flow
      (the box a request names, else `step_of`);
    - "searches": one entry per search of a value's coordinate, in order:
      {"requests", "after" (pieces of its budget shown when it ended),
      "found" (its last request's answer names a place), "noted" (its
      requests say which pieces count)};
    - "docfields": the pieces shown when a request for a field the document
      has once found something, {"plain": [...], "listed": [...]} by
      whether the field has a list;
    - "read": {attempt: replies read at it}, "unreadable": {cause: replies
      that could not be read};
    - "follow": {kind of request: answers asked again};
    - "lists": the lengths of the lists that requests for an entry showed.
    """
    steps: collections.Counter = collections.Counter()
    by_search: dict = {}
    shown_of: collections.Counter = collections.Counter()
    docfields: dict = {"plain": [], "listed": []}
    read: collections.Counter = collections.Counter()
    unreadable: collections.Counter = collections.Counter()
    follow: collections.Counter = collections.Counter()
    lists: list = []
    for request in requests:
        # Since 2026-11-11 a request names the box of the flow that asked it
        # (`box`); an older one is counted at the box of the default
        # drawing its kind stands for, a follow-up at its question's.
        step = request.get("box") or step_of(
            {**request, "kind": request.get("asked")}
            if request.get("kind") == "follow" and request.get("asked")
            else request)
        if step is not None:
            steps[step] += 1
        kind = request.get("kind")
        check = request.get("check") or ""
        if check.startswith("unreadable"):
            unreadable[check.partition(": ")[2] or "unknown"] += 1
        elif request.get("answer") is not None:
            try:
                read[int(request.get("attempt") or 1)] += 1
            except (TypeError, ValueError):
                read[1] += 1
        if kind == "search":
            by_search.setdefault(tuple(request.get(key) for key in SEARCH),
                                 []).append(request)
        elif kind == "docfield" and step == "document_fields":
            key = (request.get("doc"), request.get("parameter"))
            shown_of[key] += _shown(request)
            if names_place(request.get("answer_json")):
                listed = _list_shown(request) is not None
                docfields["listed" if listed else "plain"].append(
                    shown_of[key])
        elif kind == "follow":
            follow[str(request.get("asked") or "?")] += 1
        elif kind == "list" and not request.get("step"):
            shown = _list_shown(request)
            if shown is not None:
                lists.append(shown)
    searches = []
    for asked in by_search.values():
        noted = all("shows" in request for request in asked)
        searches.append({
            "requests": len(asked), "noted": noted,
            "after": sum(_shown(request) for request in asked
                         if not noted or request.get("shows") == FOUND),
            "found": names_place(asked[-1].get("answer_json"))})
    return {"requests": len(requests), "steps": dict(steps),
            "searches": searches, "docfields": docfields,
            "read": dict(read), "unreadable": dict(unreadable),
            "follow": dict(follow), "lists": lists}


def joined(many: list) -> dict:
    """The facts of several traces as one."""
    out = {"requests": 0, "steps": collections.Counter(), "searches": [],
           "docfields": {"plain": [], "listed": []},
           "read": collections.Counter(),
           "unreadable": collections.Counter(),
           "follow": collections.Counter(), "lists": []}
    for one in many:
        out["requests"] += one["requests"]
        out["searches"] += one["searches"]
        out["lists"] += one["lists"]
        for key in ("plain", "listed"):
            out["docfields"][key] += one["docfields"][key]
        for key in ("steps", "read", "unreadable", "follow"):
            out[key].update(one[key])
    return {**out, **{key: dict(out[key])
                      for key in ("steps", "read", "unreadable", "follow")}}


def _count(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def _listed(counts: dict) -> str:
    return ", ".join(f"{name} {n:,}" for name, n
                     in sorted(counts.items(), key=lambda kv: -kv[1]))


def says(found: dict, numbers: dict) -> dict:
    """{number: [sentences]} of what the traces say about the numbers of the
    flow at the values *numbers* gives them, each sentence at the named
    number it measures. A number that is no whole number there says
    nothing, and a number the traces say nothing about has no entry."""
    def whole(name: str) -> Optional[int]:
        value = numbers.get(name)
        return value if isinstance(value, int) \
            and not isinstance(value, bool) else None

    out: dict = collections.defaultdict(list)
    searches = found["searches"]
    ended = [search["after"] for search in searches if search["found"]]
    budget, factor = whole("search_pieces"), whole("listed_field_factor")
    if budget is not None and searches:
        sentence = (f"Of {_count(len(searches), 'search', 'searches')} for "
                    f"an open coordinate, {len(ended):,} ended with an "
                    f"answer that names a place and "
                    f"{len(searches) - len(ended):,} without one.")
        if ended:
            # Only where every search noted it are these the budget's.
            pieces = "shown pieces of the budget" \
                if all(search["noted"] for search in searches) \
                else "shown pieces"
            sentence += (
                f" Those answers came after {min(ended):,} to "
                f"{max(ended):,} {pieces}, half of them "
                f"within {int(statistics.median(ended)):,}; "
                f"{after(ended, budget):,} came after more than "
                f"{budget:,}.")
        out["search_pieces"].append(sentence)
    plain, listed = found["docfields"]["plain"], found["docfields"]["listed"]
    if budget is not None and plain:
        out["search_pieces"].append(
            f"For fields the document has once, "
            f"{_count(len(plain), 'request')} found something; "
            f"{after(plain, budget):,} of them after more than {budget:,} "
            f"shown pieces.")
    if budget is not None and factor is not None and listed:
        out["listed_field_factor"].append(
            f"For fields the document has once that have a list, "
            f"{_count(len(listed), 'request')} found something; "
            f"{after(listed, budget * factor):,} of them after more than "
            f"{budget * factor:,} shown pieces ({budget:,} times "
            f"{factor:,}).")
    if whole("search_per_request") is not None and searches:
        sent = sum(search["requests"] for search in searches)
        out["search_per_request"].append(
            f"The {_count(len(searches), 'search', 'searches')} sent "
            f"{_count(sent, 'request')}, {sent / len(searches):.1f} each on "
            f"average.")
    if whole("follow_ups") is not None and found["requests"]:
        asked = sum(found["follow"].values())
        out["follow_ups"].append(
            f"{_count(asked, 'answer')} did not hold and "
            f"{'was' if asked == 1 else 'were'} asked again"
            + (f": {_listed(found['follow'])}." if asked else "."))
    replies = whole("replies")
    if replies is not None and found["read"]:
        read = found["read"]
        attempts = [attempt for attempt, n in read.items()
                    for _ in range(n)]
        by_attempt = ", ".join(
            f"{n:,} at attempt {attempt}"
            for attempt, n in sorted(read.items()))
        sentence = (f"{_count(len(attempts), 'reply', 'replies')} "
                    f"{'was' if len(attempts) == 1 else 'were'} read: "
                    f"{by_attempt}; {after(attempts, replies):,} only after "
                    f"more than {replies:,} attempts.")
        lost = sum(found["unreadable"].values())
        if lost:
            sentence += (f" {_count(lost, 'reply', 'replies')} could not be "
                         f"read ({_listed(found['unreadable'])}).")
        out["replies"].append(sentence)
    meanings = whole("list_meanings")
    if meanings is not None and found["lists"]:
        lists = found["lists"]
        out["list_meanings"].append(
            f"{_count(len(lists), 'request')} asked for the entry of a "
            f"list; {after(lists, meanings):,} of the lists shown had more "
            f"than {meanings:,} entries, which are shown by their names "
            f"only.")
    return dict(out)


def notes(found: dict) -> list:
    """What has to be said about how the traces were counted."""
    out = []
    if any(not search["noted"] for search in found["searches"]):
        out.append(
            "These traces were written before a search noted which of its "
            "pieces count toward its budget (the pieces beside the value "
            "and those the model fetched itself do not): for them the "
            "pieces of every request of a search are counted, so a place "
            "may be counted later than the budget saw it.")
    return out
