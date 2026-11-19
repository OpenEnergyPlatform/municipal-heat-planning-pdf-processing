"""
requests.py: The model requests of an extraction trace, read from its events.

One dict per `*_ask` event with what was sent, what came back and what became
of it (taken, asked again, no answer, unreadable); the chain of one value; the
filter that picks requests; and `Traces`, which reads each trace of a harvest
folder once per state of its file. No page and no server in here. Moved out of
`scripts/chat_view.py` so that the script and the editor share one version.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from ..extraction import trace
from .prompts import STAGE_REQUESTS

NOTES = ("parameter", "coordinate", "owner", "value")
# The stages before the harvest that write a request log in each document's
# folder, by the name the log has there (`trace.open_stage`): those whose
# requests the editor knows (`prompts.STAGE_REQUESTS`).
STAGES = tuple(STAGE_REQUESTS)
CHAINED = ("coord", "search", "check", "follow")


def _text(content) -> str:
    if content is None:
        return ""
    if not isinstance(content, list):
        return str(content)
    parts = []
    for p in content:
        if isinstance(p, dict) and p.get("type") == "text":
            parts.append(str(p.get("text", "")))
        else:
            parts.append("[image]")
    return "\n".join(parts)


def _json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _entries(user) -> dict:
    """{number: label} of the "N label (means: ...)" lines of a request's list."""
    out = {}
    for line in (user or {}).get("list") or ():
        m = re.match(r"\s*(\d+)\s+(.*?)(?:\s*\(means:.*)?\s*$", str(line), re.S)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _spell(answer, user) -> list:
    """The entries an answer names, each written out as "N = label"."""
    if not isinstance(answer, dict) or "entry" not in answer:
        return []
    labels = _entries(user)
    picked = answer["entry"]
    picked = picked if isinstance(picked, list) else [picked]
    return [f"{n} = {labels[str(n)]}" if str(n) in labels else str(n)
            for n in picked]


def _words(answer) -> set:
    """The words an answer reads, from "words" or each of its "found"/"more"."""
    out = set()
    if isinstance(answer, dict):
        for item in [answer] + list(answer.get("found") or ()) + list(
                answer.get("more") or ()):
            if isinstance(item, dict) and item.get("words") not in (None, ""):
                out.add(str(item["words"]))
    return out


def _reasons(user) -> str:
    what = (user or {}).get("what")
    if isinstance(what, (dict, str)):
        what = [what]
    parts = []
    for w in what or ():
        if isinstance(w, dict):
            parts.append(str(w.get("why") or w.get("reason")
                             or json.dumps(w, ensure_ascii=False)))
        else:
            parts.append(str(w))
    return ", ".join(parts)


def requests_of(events: list, profile=None) -> list:
    """One dict per `*_ask` event, in trace order. A reply of a stage
    before the harvest is read with the sentences of *profile*
    (`stage_check`), the ambient one's where not given."""
    pieces = trace.pieces_of(events)
    out = []
    for i, e in enumerate(events):
        t = str(e.get("t", ""))
        if not t.endswith("_ask"):
            continue
        sent = trace.sent(e, pieces) or {}
        msgs = [[m.get("role"), _text(m.get("content"))]
                for m in sent.get("messages") or ()]
        system = next((m[1] for m in msgs if m[0] == "system"), "")
        rest = [m for m in msgs if m[0] != "system"]
        user_text = rest[0][1] if rest and rest[0][0] == "user" else ""
        user = _json(user_text)
        user = user if isinstance(user, dict) else None
        output = e.get("output") if isinstance(e.get("output"), dict) else {}
        content = output.get("content")
        answer_text = content if isinstance(content, str) and content.strip() else None
        answer = _json(answer_text) if answer_text else None
        value = (user or {}).get("value")
        req = {k: v for k, v in e.items() if k not in ("input", "output", "t", "kind")}
        if "kind" in e:
            req["note_kind"] = e["kind"]  # the passage's or list's kind
        req.update({
            "_reply": reply_key(sent.get("response_format")),
            "kind": t[:-4], "system": system, "messages": rest,
            "user": user_text, "answer": answer_text,
            "answer_json": answer if isinstance(answer, (dict, list)) else None,
            "finish": output.get("finish"), "error": output.get("error"),
            "spelled": _spell(answer, user),
            "at": value.get("at") if isinstance(value, dict) else None,
            "check": "", "_event": i, "_user": user,
        })
        out.append(req)
    _check(out, events, profile)
    for r in out:
        r.pop("_event")
        r.pop("_user")
        r.pop("_reply")
    return out


# The type of a reply's key as its schema names it.
_OF = {"array": list, "string": str, "object": dict, "boolean": bool,
       "integer": int, "number": (int, float)}


def reply_key(shape) -> Optional[tuple]:
    """(the key a stage before the harvest reads its reply by, the type it
    has to be) from the reply form *shape* a request was sent with: the
    first required key of its schema, as the stage reads it
    (`vision.reply_type`, `refine`); None where it names none."""
    form = shape.get("json_schema") if isinstance(shape, dict) else None
    schema = form.get("schema") if isinstance(form, dict) else None
    if not isinstance(schema, dict) or not schema.get("required"):
        return None
    key = schema["required"][0]
    kind = ((schema.get("properties") or {}).get(key) or {}).get("type")
    if isinstance(kind, list):
        kind = next((one for one in kind if one != "null"), None)
    return key, _OF.get(kind, object)


def stage_check(request: dict, profile=None) -> str:
    """What became of a request of a stage before the harvest, read as the
    stage reads its reply (`reading.read`, by the key of its reply form):
    "taken", or "unreadable: <cause>", a reply the stage asks again. The
    sentences of *profile* where it is not the ambient one."""
    import contextlib
    from .. import reading
    reply = request.get("_reply")
    choice = SimpleNamespace(
        message=SimpleNamespace(content=request.get("answer")),
        finish_reason=request.get("finish"))
    key, of = reply if reply else (None, list)
    frame = (reading.speaking(profile) if profile is not None
             else contextlib.nullcontext())
    try:
        with frame:
            _found, cause, _said = reading.read(choice, key=key, of=of)
    except LookupError:
        # No profile speaks here: the cause is all that is wanted, and
        # it is the same with any profile's sentences.
        from ..profile import load_profile
        with reading.speaking(load_profile("default")):
            _found, cause, _said = reading.read(choice, key=key, of=of)
    return "taken" if not cause else f"unreadable: {cause}"


def _same_notes(a, b) -> bool:
    return a.get("doc") == b.get("doc") and all(a.get(k) == b.get(k) for k in NOTES)


def _check(reqs: list, events: list, profile=None) -> None:
    """What became of each request: taken, asked again, no answer, unreadable."""
    for pos, r in enumerate(reqs):
        if r["answer"] is None:
            r["check"] = "no answer"
            continue
        if isinstance(r.get("made"), dict):
            r["check"] = stage_check(r, profile)
            continue
        nxt = next((x for x in events[r["_event"] + 1:]
                    if x.get("t") != trace.PIECE), None)
        if (nxt and nxt.get("t") == "error" and nxt.get("kind") == "unreadable"
                and nxt.get("where") == r["kind"]):
            r["check"] = f"unreadable: {nxt.get('cause')}"
            continue
        follow = next((x for x in reqs[pos + 1:] if x["kind"] == "follow"
                       and x.get("asked") == r["kind"] and _same_notes(x, r)), None)
        if follow is None:
            r["check"] = "taken"
        else:
            why = _reasons(follow["_user"])
            r["check"] = "asked again" + (f": {why}" if why else "")


def chain_of(requests: list, index: int) -> list:
    """Indexes of the requests of one value: the find of its parameter and
    passage, the readings and follow-ups, and the list entries asked for its words."""
    r = requests[index]
    kind = r.get("asked") if r["kind"] == "follow" else r["kind"]
    # A request that reads no value (a detail of a work, a field of the
    # document) is no link of a value's chain: what it shares with the other
    # such requests of its field is only that none of them names one.
    if kind not in CHAINED or r.get("value") is None:
        return [index]
    doc, par, own = r.get("doc"), r.get("parameter"), r.get("owner")
    members = [i for i, x in enumerate(requests)
               if x.get("doc") == doc and x.get("parameter") == par
               and x.get("owner") == own and x.get("value") == r.get("value")
               and (x["kind"] in ("coord", "search", "check")
                    or (x["kind"] == "follow" and x.get("asked") in CHAINED))]
    first = min(members + [index])
    finds = [i for i, x in enumerate(requests)
             if x["kind"] == "find" and x.get("doc") == doc
             and x.get("parameter") == par and x.get("owner") == own and i < first]
    words = set()
    for i in members:
        words |= _words(requests[i]["answer_json"])
    lists = []
    for i, x in enumerate(requests):
        if x["kind"] not in ("list", "names") or x.get("doc") != doc:
            continue
        if x.get("parameter") not in (None, par):
            continue
        u = _json(x["user"]) or {}
        if str(u.get("words", u.get("name"))) in words:
            lists.append(i)
    return sorted(set(finds[-1:] + members + lists))


def keep(request: dict, kinds=(), fields=(), owners=(), values=(),
         contains=()) -> bool:
    """Whether *request* passes the filter: one of *kinds* (`coord_ask` counts
    as `coord`), one of *fields*, *owners* and *values* (compared as strings),
    and every text of *contains* (any case) somewhere in its instruction,
    message or answer. An empty argument keeps everything."""
    r = request
    kinds = {k[:-4] if k.endswith("_ask") else k for k in kinds or ()}
    if kinds and r["kind"] not in kinds:
        return False
    if fields and r.get("parameter") not in fields:
        return False
    if owners and str(r.get("owner")) not in {str(o) for o in owners}:
        return False
    if values and str(r.get("value")) not in {str(v) for v in values}:
        return False
    blob = "\n".join([r["system"], r["user"], r["answer"] or ""]).casefold()
    return all(s.casefold() in blob for s in contains or ())


class Trace:
    """One trace file read once: its events, its pieces and its requests."""

    def __init__(self, path, events: list, profile=None):
        self.path = Path(path)
        self.events = events
        self.pieces = trace.pieces_of(events)
        # what the run was (`runner.run_head`, `trace.stage_head`)
        self.head = trace.head_of(events, self.pieces)
        self.requests = requests_of(events, profile)
        # the index in `events` of each request's event, in the same order
        self.event_of = [i for i, e in enumerate(events)
                         if str(e.get("t", "")).endswith("_ask")]
        self._carried: dict = {}

    def sent(self, index: int) -> Optional[dict]:
        """The request `requests[index]` reports, as it was sent."""
        return trace.sent(self.events[self.event_of[index]], self.pieces)

    def carried(self, index: int) -> tuple:
        """The fields the message of request *index* carries: the keys of
        its payload, and what its reply form offers ("more", "get_image"),
        () where it shows none. Which parts of its prompt a request is told
        hangs on them (`runner.request_prompt`)."""
        if index not in self._carried:
            from ..extraction import runner
            try:
                payload, _ = json.JSONDecoder().raw_decode(
                    self.requests[index]["user"])
            except ValueError:
                payload = None
            offers = runner.reply_offers(
                (self.sent(index) or {}).get("response_format"))
            self._carried[index] = (
                tuple(payload) + tuple(sorted(offers - set(payload)))
                if isinstance(payload, dict) else ())
        return self._carried[index]

    def kinds(self) -> list:
        return sorted({r["kind"] for r in self.requests})

    def fields(self) -> list:
        return sorted({r["parameter"] for r in self.requests
                       if r.get("parameter") is not None})


class Traces:
    """The traces of a harvest folder, and the request logs of the stages
    before the harvest in the documents' folders of *stages* (the processed
    folder: `<document>/<stage>.trace.jsonl.gz`, named "<document>/<stage>";
    owner request 2026-11-19, A3), each read at most once per state of its
    file."""

    def __init__(self, folder: Optional[Path], lines=trace.lines,
                 stages: Optional[Path] = None, profile=None):
        # *lines(path)* yields the events of a file; a caller that guards
        # its file reads passes its own
        self.folder = Path(folder) if folder is not None else None
        self.stages = Path(stages) if stages is not None else None
        # whose sentences read the replies of a stage log (`stage_check`)
        self.profile = profile
        self._lines = lines
        self._lock = threading.Lock()
        self._cache: dict = {}

    def _named(self) -> list:
        """[(name, path)] of every trace and stage log, harvest first."""
        out = []
        if self.folder is not None and self.folder.is_dir():
            out += [(trace.name_of(p), p) for p in trace.files(self.folder)]
        if self.stages is not None and self.stages.is_dir():
            for folder in sorted(p for p in self.stages.iterdir()
                                 if p.is_dir()):
                out += [(f"{folder.name}/{trace.name_of(p)}", p)
                        for p in trace.files(folder)
                        if trace.name_of(p) in STAGES]
        return out

    def names(self, which: Optional[str] = None) -> list:
        """The traces by name: every one, or for *which* "harvest" the
        harvest's only, for a stage's name ("refinement", "visuals") that
        stage's logs only."""
        out = []
        for name, path in self._named():
            stage = name.rpartition("/")[2] if "/" in name else None
            if which is None or (which == "harvest" and stage is None) \
                    or (which is not None and stage == which):
                out.append({"name": name, "file": path.name,
                            "bytes": path.stat().st_size, "stage": stage})
        return out

    def path_of(self, name: str) -> Optional[Path]:
        if self.folder is not None and self.folder.is_dir():
            for path in trace.files(self.folder):
                if trace.name_of(path) == name:
                    return path
        document, slash, stage = name.rpartition("/")
        if (slash and self.stages is not None and stage in STAGES
                and document and "/" not in document
                and document not in (".", "..")):
            return trace.path_of(self.stages / document, stage)
        return None

    def load(self, name: str) -> Trace:
        """The trace *name*; KeyError for a name the folder has not. The same
        object comes back until the file changes on disk."""
        path = self.path_of(name)
        if path is None:
            raise KeyError(name)
        with self._lock:
            stat = path.stat()
            key = (path, stat.st_mtime_ns, stat.st_size)
            hit = self._cache.get(name)
            if hit is None or hit[0] != key:
                hit = (key, Trace(path, list(self._lines(path)),
                                  self.profile))
                self._cache[name] = hit
            return hit[1]
