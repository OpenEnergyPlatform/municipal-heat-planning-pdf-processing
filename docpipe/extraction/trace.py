"""
trace.py: Records what the harvest did as one JSON event per line, so it can be
counted after the run.

A text log tells a human reading it live what happened. It cannot answer
questions about a distribution over many requests, such as at which rank a
value was found, in which window a coordinate closed, or whether a retry
helped. Every setting this stage has, including `top_k`, the window budget, and
the batch thread count, was chosen at least once without such a distribution,
and every one of those choices was wrong.

Each document therefore gets a second file next to its harvest, with one JSON
object per event and nothing aggregated. Aggregation is left to the report
script, which can be rewritten when the question changes; the trace itself
cannot be rewritten after the fact.

Every event that reports a model request also carries the request as it was
sent (`input`) and what came back (`output`: the reply, or the error the
request ended in), so that a run can be read back request by request (owner
decision 2026-11-05). The request is taken where every request of the stage
passes (`scheduler.Repeats`, `exchanged`) and goes into the next event of the
same thread that reports it: one that carries `prompt_tokens`, or an error of
kind `exception`. With it go the request's times, to the millisecond
(`asked_at`, `sent_at`, `answered_at`: when the caller asked, when it left
the run's queue for the server, when its answer or error came), and `once`
where the answer is that of the same request sent before in the document
and nothing was sent (owner decision 2026-11-07).

Nothing repeated is written twice. A text longer than a reference to it -- a
system prompt, a reply format, a passage, a parameter's description, a list of
options, a picture -- is written once per document as a `piece` event and
referenced by its hash; a payload that is a JSON object is split at its
top-level keys first, and put back with the writing that made it, so `sent`
returns each message character for character. The file is compressed
(`<name>.trace.jsonl.gz`). `lines` reads it, and a trace an earlier run wrote
uncompressed (`<name>.trace.jsonl`), and ends quietly where a killed run left
it.

The rule `trace_on` (setting `EXTRACT_TRACE=0` turns it off) decides whether
a run traces at all: off, every call to record an event returns immediately.
`trace_requests` says whether an event carries its request and reply;
`trace_compress`, `trace_time_places` and `trace_piece_min_chars` the file's
form (owner decision 2026-11-11). Each is read where it is used.

Author: Felix Vossel
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import threading
import zlib
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from .. import rules
from ..ruleset.passes import run_value

log = logging.getLogger(__name__)


def enabled() -> bool:
    """Whether the run traces (rule `trace_on`), read when asked: a run's
    value, whatever step is writing."""
    return bool(run_value("trace_on"))


# A trace file, and the name traces had before they carried their requests,
# which is still read.
SUFFIX = ".trace.jsonl.gz"
PLAIN = ".trace.jsonl"
# The event a repeated text is written as, once per document.
PIECE = "piece"
# The ways this stage writes a JSON payload, tried in turn: a payload put back
# with the one that wrote it is the payload that was sent.
DUMPS = ({"ensure_ascii": False, "indent": 2}, {"ensure_ascii": False},
         {"indent": 2}, {})

_lock = threading.Lock()
_files: dict = {}
_written: dict = {}             # document id -> the pieces its file holds
_root: Optional[Path] = None
_name_of: Optional[Callable] = None
_thread = threading.local()


def open_trace(directory, name_of: Callable) -> None:
    """Start writing traces under `directory`, naming files via `name_of(id)`."""
    global _root, _name_of
    if not enabled():
        return
    # A file opened under an earlier directory would go on taking the events
    # of its document, and this directory would never see them.
    close()
    _root = Path(directory)
    _root.mkdir(parents=True, exist_ok=True)
    _name_of = name_of


def _handle(document_id: int):
    """The open file for this document, started anew the first time it is
    asked for.

    Anew, not appended: a document harvested a second time in the same run is
    a document being redone, and a trace holding both attempts cannot be
    counted without knowing which line belongs to which.
    """
    handle = _files.get(document_id)
    if handle is not None:
        return handle
    name = (_name_of(document_id) if _name_of else None) or f"doc{document_id}"
    path = _root / f"{name}{SUFFIX if compressed() else PLAIN}"
    # What an earlier run traced is kept, not truncated (archive.py); one it
    # wrote under the other name (plain or compressed) is kept the same way
    # and then replaced, as a trace of this name always was.
    from . import archive
    archive.keep(path)
    earlier = _root / f"{name}{PLAIN if compressed() else SUFFIX}"
    if earlier.is_file():
        archive.keep(earlier)
        earlier.unlink()
    if compressed():
        handle = gzip.open(path, "wt", encoding="utf-8")
    else:
        handle = open(path, "wt", encoding="utf-8", newline="\n")
    _files[document_id] = handle
    _written[document_id] = set()
    return handle


def compressed() -> bool:
    """Whether a trace is written compressed (rule `trace_compress`)."""
    return bool(run_value("trace_compress"))


def exchanged(request: dict, response=None, error=None, *,
              times: Optional[tuple] = None, once: bool = False) -> None:
    """The request the calling thread has just sent, with the reply that came
    back or the error it ended in, for the event that reports it (`event`).
    A thread's next request takes the place of one no event reported.
    *times* are (asked, sent, answered) in seconds since the epoch, sent
    None where no queue held the request; *once* says the answer is that of
    the same request sent before and nothing was sent
    (`scheduler.Once`)."""
    if not enabled() or _root is None:
        return
    if not rules.get("trace_requests"):
        # The step that sent it does not record its requests: whatever
        # request the thread held for an event is gone with it.
        _thread.exchange = None
        return
    _thread.exchange = (request, response, error, times, once)


def _times(times: Optional[tuple]) -> dict:
    """A request's times as its event carries them, to the millisecond."""
    if not times:
        return {}
    asked, sent, answered = times
    places = run_value("trace_time_places")
    out = {"asked_at": round(asked, places)}
    if sent is not None:
        out["sent_at"] = round(sent, places)
    out["answered_at"] = round(answered, places)
    return out


def _reports(kind: str, fields: dict) -> bool:
    """Whether an event reports the request its thread sent last: it carries
    what the reply cost, or the error that left it without one."""
    return "prompt_tokens" in fields or (
        kind == "error" and fields.get("kind") == "exception")


def event(kind: str, document_id: Optional[int] = None, /, **fields) -> None:
    """One line of trace. Never raises: a broken trace must not kill a harvest.

    Both arguments are positional-only: an event's own fields are free-form
    and several of them are called `kind` or `status`, which would otherwise
    collide with the signature rather than land in the record.
    """
    pending = None
    if _reports(kind, fields):
        pending = getattr(_thread, "exchange", None)
        _thread.exchange = None
    if not enabled() or _root is None or document_id is None:
        return
    try:
        record = {"t": kind, "doc": document_id}
        record.update(fields)
        pieces: dict = {}
        if pending is not None:
            request, response, error, times, once = pending
            record["input"] = _input(request, pieces)
            record["output"] = _output(response, error)
            record.update(_times(times))
            if once:
                record["once"] = True
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            handle = _handle(document_id)
            written = _written[document_id]
            for key, text in pieces.items():
                if key not in written:
                    handle.write(json.dumps(
                        {"t": PIECE, "doc": document_id, "id": key,
                         "text": text}, ensure_ascii=False) + "\n")
                    written.add(key)
            handle.write(line + "\n")
    except Exception as exc:                      # pragma: no cover - defensive
        log.debug("trace: %s dropped: %s", kind, exc)


def flush(document_id: Optional[int] = None) -> None:
    """Push what is buffered to disk, for one document or for all of them."""
    if not enabled() or _root is None:
        return
    with _lock:
        targets = ([_files[document_id]] if document_id in _files
                   else list(_files.values()) if document_id is None else [])
        for handle in targets:
            try:
                handle.flush()
            except Exception:                     # pragma: no cover - defensive
                pass


def close() -> None:
    """Close every open trace. Safe to call twice."""
    with _lock:
        for handle in _files.values():
            try:
                handle.close()
            except Exception:                     # pragma: no cover - defensive
                pass
        _files.clear()
        _written.clear()


# -- a request, without what repeats --------------------------------------------

def _ref(text: str, pieces: dict) -> Optional[str]:
    """The reference *text* is written under, or None where the text is no
    longer than `trace_piece_min_chars` (by default the length of a
    reference)."""
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    if len(text) <= run_value("trace_piece_min_chars"):
        return None
    pieces[key] = text
    return key


def _split(obj: dict, pieces: dict) -> tuple:
    """(*obj* with every value a reference stands for set to None, {key:
    reference})."""
    kept, refs = {}, {}
    for key, value in obj.items():
        ref = _ref(json.dumps(value, ensure_ascii=False, default=str), pieces)
        if ref is None:
            kept[key] = value
        else:
            kept[key] = None
            refs[key] = ref
    return kept, refs


def _text(text: str, pieces: dict):
    """A message text: as it is, a reference to it, or a JSON object split at
    its keys with the writing that made it."""
    if text.lstrip().startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            for dump in DUMPS:
                if json.dumps(obj, **dump) == text:
                    kept, refs = _split(obj, pieces)
                    return {"json": kept, "dump": dump, "pieces": refs}
    ref = _ref(text, pieces)
    return text if ref is None else {"piece": ref}


def _message(message, pieces: dict):
    if not isinstance(message, dict):
        return message
    out = dict(message)
    content = message.get("content")
    if isinstance(content, str):
        out["content"] = _text(content, pieces)
    elif isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" \
                    and isinstance(part.get("text"), str):
                parts.append({**part, "text": _text(part["text"], pieces)})
                continue
            # A picture: its data travels once, whatever asks about it.
            ref = _ref(json.dumps(part, ensure_ascii=False, default=str),
                       pieces)
            parts.append(part if ref is None else {"piece": ref})
        out["content"] = parts
    return out


def _input(request: dict, pieces: dict) -> dict:
    """The request as sent: its messages each without what repeats, and every
    other argument a reference stands for set to None and named under
    `pieces`."""
    rest = {k: v for k, v in request.items() if k != "messages"}
    kept, refs = _split(rest, pieces)
    out = dict(kept)
    out["messages"] = [_message(m, pieces)
                       for m in request.get("messages") or ()]
    if refs:
        out["pieces"] = refs
    return out


def _output(response, error) -> dict:
    """What came back: the reply's text and why it ended, and its reasoning
    where the server sent one; or the error the request ended in."""
    if error is not None:
        return {"error": f"{type(error).__name__}: {error}"}
    try:
        choice = response.choices[0]
    except (AttributeError, IndexError, TypeError):
        return {"error": "no choice in the reply"}
    message = choice.message
    out = {"content": getattr(message, "content", None),
           "finish": getattr(choice, "finish_reason", None)}
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        out["reasoning"] = reasoning
    return out


# -- reading ------------------------------------------------------------------

def is_trace(path) -> bool:
    name = Path(path).name
    return name.endswith(SUFFIX) or name.endswith(PLAIN)


def name_of(path) -> str:
    """The document name a trace file is written under."""
    name = Path(path).name
    for suffix in (SUFFIX, PLAIN):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return Path(path).stem


def path_of(directory, name: str) -> Optional[Path]:
    """The trace of *name* in *directory*, or None where there is none."""
    for suffix in (SUFFIX, PLAIN):
        path = Path(directory) / f"{name}{suffix}"
        if path.is_file():
            return path
    return None


def files(directory) -> list:
    """Every trace in *directory*, one per name in name order; where a name
    has both files, the compressed one, which is the later run's."""
    found: dict = {}
    for path in sorted(Path(directory).glob(f"*{PLAIN}*")):
        if not is_trace(path):
            continue
        name = name_of(path)
        if name not in found or path.name.endswith(SUFFIX):
            found[name] = path
    return [found[name] for name in sorted(found)]


def lines(path, kinds: Optional[Iterable[str]] = None) -> Iterator[dict]:
    """The events of a trace file of either kind, pieces among them; none for
    a file that is not there. A run that was killed leaves a last line cut
    short or a compressed stream without its end: reading stops there, with
    everything before it.

    *kinds*, where given, are the only events read. A line that does not name
    one of them anywhere is passed over without being parsed, which spares
    the requests and pieces that make most of a trace; the order of an
    event's keys decides nothing."""
    path = Path(path)
    opener = gzip.open if path.name.endswith(".gz") else open
    wanted = set(kinds) if kinds is not None else None
    marks = (tuple(json.dumps(kind) for kind in wanted)
             if wanted is not None else ())
    try:
        handle = opener(path, "rt", encoding="utf-8")
    except OSError:
        return
    with handle:
        try:
            for line in handle:
                if wanted is not None and not any(mark in line
                                                  for mark in marks):
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict) or (
                        wanted is not None and record.get("t") not in wanted):
                    continue
                yield record
        except (EOFError, zlib.error, OSError):
            return


def pieces_of(events) -> dict:
    """{reference: text} of the pieces among *events*."""
    return {e["id"]: e.get("text") for e in events
            if e.get("t") == PIECE and isinstance(e.get("id"), str)}


def _back(value, refs: dict, pieces: dict):
    out = dict(value)
    for key, ref in refs.items():
        out[key] = json.loads(pieces[ref])
    return out


def _text_back(value, pieces: dict):
    if isinstance(value, str):
        return value
    if "piece" in value:
        return pieces[value["piece"]]
    obj = _back(value["json"], value.get("pieces") or {}, pieces)
    return json.dumps(obj, **(value.get("dump") or {}))


def sent(record: dict, pieces: dict) -> Optional[dict]:
    """The request *record* reports, as it was sent, or None where it carries
    none. *pieces* are the pieces of its file (`pieces_of`)."""
    given = record.get("input")
    if not isinstance(given, dict):
        return None
    rest = {k: v for k, v in given.items() if k not in ("messages", "pieces")}
    out = _back(rest, given.get("pieces") or {}, pieces)
    messages = []
    for message in given.get("messages") or ():
        message = dict(message)
        content = message.get("content")
        if isinstance(content, list):
            message["content"] = [
                json.loads(pieces[part["piece"]])
                if isinstance(part, dict) and set(part) == {"piece"}
                else ({**part, "text": _text_back(part["text"], pieces)}
                      if isinstance(part, dict) and part.get("type") == "text"
                      else part)
                for part in content]
        elif content is not None:
            message["content"] = _text_back(content, pieces)
        messages.append(message)
    out["messages"] = messages
    return out
