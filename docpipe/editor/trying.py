"""
trying.py: A recorded request sent once more with a changed prompt, and what
the new answer is worth.

"Try" takes requests of a trace, makes each one's instruction from the text
being edited (`prompts.preview`) and sends it as it was recorded otherwise:
the same message, reply form and settings, to the model the installation
names for it. One request is one call, never repeated, and a click sends
`LIMIT` at most (owner decision 2026-11-10: "nicht mit 20, max 3"). Nothing
is sent by anything else in the editor.

The new answer is read as the run reads one (`runner._loads_object`,
`runner._lacking`), and each address it names is held against the lines the
request showed with the run's own check (`addressed.resolve`). The lines
are those of the recorded message, so a line's cells are taken from its
text: a row of a table as the run cuts one, any other line where "|"
divides it in two or more.

Where the model is: EDIT_TRY_BASE_URL, EDIT_TRY_API_KEY and EDIT_TRY_MODEL;
without the first, the text model of the run (LLM_BASE_URL, LLM_API_KEY,
LLM_MODEL) where the environment names one. With neither, nothing is sent
and the reason is said.

Author: Felix Vossel
"""
from __future__ import annotations

import os
import re
import time
from types import SimpleNamespace
from typing import Callable, Optional
from urllib.parse import urlsplit

from . import prompts

LIMIT = 3
TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "180"))
NO_MODEL = ("No model is set up for Try, so no request can be sent. To "
            "set one up, set EDIT_TRY_BASE_URL together with "
            "EDIT_TRY_API_KEY and EDIT_TRY_MODEL, or set LLM_BASE_URL for "
            "the text model of the run.")
# A line as a request shows it: a block's letter, its number, its text.
_SHOWN = re.compile(r"^([A-Z]?)(\d+) (.*)$", re.S)
# The key of a message under which the entries of a list stand, each under
# its number: numbered like lines, and no lines.
OPTIONS = "list"


class Refused(ValueError):
    """A try that is not sent, said in one sentence."""


def settings() -> dict:
    """Where a try goes: `configured`, and then `base_url`, `api_key`,
    `model` and the `host` to show; else `why` not."""
    env = os.environ
    if env.get("EDIT_TRY_BASE_URL"):
        base, key = env["EDIT_TRY_BASE_URL"], env.get("EDIT_TRY_API_KEY")
        model = env.get("EDIT_TRY_MODEL") or env.get("LLM_MODEL")
    elif env.get("LLM_BASE_URL"):
        base, key = env["LLM_BASE_URL"], env.get("LLM_API_KEY")
        model = env.get("LLM_MODEL")
    else:
        return {"configured": False, "why": NO_MODEL, "limit": LIMIT}
    if not model:
        from ..extraction import runner
        model = runner.llm_model()
    return {"configured": True, "why": None, "limit": LIMIT,
            "base_url": base, "api_key": key or "EMPTY", "model": model,
            "host": urlsplit(base).hostname or base}


def client_of(config: dict):
    """The run's client for the text model, at the address of *config*.
    It repeats nothing."""
    from .. import providers
    return providers.client("llm", base_url=config["base_url"],
                            api_key=config["api_key"], timeout=TIMEOUT,
                            max_retries=0)


# -- what a request showed, and whether an answer's addresses hold ------------------

def shown_of(payload) -> object:
    """The lines a message shows, as the run keeps them (`units.Shown`):
    every text in *payload* that starts with an address, under the letter
    of its block."""
    from ..extraction import units
    blocks: dict = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key != OPTIONS:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, str):
                    hit = _SHOWN.match(value)
                    if hit:
                        blocks.setdefault(hit.group(1), {})[
                            int(hit.group(2))] = hit.group(3)
                else:
                    walk(value)

    walk(payload)
    shown = units.Shown()
    for letter, lines in blocks.items():
        source = SimpleNamespace(owner_kind="shown", owner_id=letter)
        shown.add(letter, letter, [
            (units.Line(number, text,
                        units.cells_of(text) if units._ROW.match(text)
                        else units.line_cells(text)), source)
            for number, text in sorted(lines.items())])
    return shown


def _named(answer) -> list:
    """Every part of an answer that names an address."""
    out: list = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if "at" in node:
                out.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(answer)
    return out


def addresses(answer, payload) -> list:
    """Each address *answer* names, with whether it holds against what
    *payload* showed: `holds` None for the answer that nothing shown says
    it (0), else whether the run's check takes it, with its reason
    (`why`) where it does not."""
    from ..extraction import addressed, units
    shown = shown_of(payload)
    out = []
    for entry in _named(answer):
        at = entry.get("at")
        row = {"at": at, "words": entry.get("words"), "holds": None,
               "why": None}
        if units.address_of(at) is not None or at not in (0, "0", None, ""):
            found = addressed.resolve(shown, entry, {})
            row["holds"] = found.why is None
            row["why"] = found.why
        out.append(row)
    return out


# -- sending --------------------------------------------------------------------------

def once(client, model: str, request: dict, sent: dict, view: dict) -> dict:
    """One call: the recorded request *sent* with the instruction (and,
    for a request asked again, the message) of *view*
    (`prompts.preview`), and what came back."""
    from ..extraction import runner
    kind = request.get("asked") if request["kind"] == prompts.FOLLOW \
        else request["kind"]
    messages = [dict(message) for message in sent.get("messages") or ()]
    first_user = True
    for message in messages:
        if message.get("role") == "system":
            message["content"] = view["edit"]["system"]
        elif message.get("role") == "user" and first_user:
            first_user = False
            if request["kind"] == prompts.FOLLOW \
                    and isinstance(message.get("content"), str):
                message["content"] = view["edit"]["user"]
    asked = runner.asked_values(kind)
    if kind == "phrase":
        limit = asked["max_tokens"]
    else:
        limit = runner.answer_room(view["edit"]["system"], messages[1:],
                                   asked["max_tokens"])
    extra = {key: sent[key] for key in ("response_format", "extra_body")
             if sent.get(key) is not None}
    out = {"answer": None, "answer_json": None, "finish": None,
           "error": None, "ms": None, "prompt_tokens": None,
           "completion_tokens": None, "max_tokens": limit}
    started = time.time()
    try:
        response = client.chat.completions.create(
            model=model, temperature=asked["temperature"],
            max_tokens=limit, messages=messages, **extra)
        choice = response.choices[0]
    except Exception as exc:        # whatever the server or the wire says
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["ms"] = int((time.time() - started) * 1000)
        return out
    out["ms"] = int((time.time() - started) * 1000)
    usage = getattr(response, "usage", None)
    out["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
    out["completion_tokens"] = getattr(usage, "completion_tokens", None)
    out["finish"] = getattr(choice, "finish_reason", None)
    out["answer"] = getattr(choice.message, "content", None)
    answer = runner._loads_object(out["answer"])
    missing = runner._lacking(answer, sent.get("response_format"))
    out["answer_json"] = answer
    out["in_form"] = isinstance(answer, dict) and missing is None
    out["fault"] = None
    if not out["in_form"]:
        try:
            out["fault"] = runner._reply_fault(
                choice, limit, key=missing
                or runner.ASK_KEYS.get(kind, ""))[0]
        except Exception:           # the sentences of a profile not in force
            out["fault"] = "missing_key" if missing else "unreadable"
    return out


def _same(old: dict, new: dict) -> bool:
    """Whether the new answer is the recorded one: as objects where both
    are one, else as texts."""
    if old.get("answer_json") is not None and new["answer_json"] is not None:
        return old["answer_json"] == new["answer_json"]
    return (old.get("answer") or "").strip() == (new["answer"] or "").strip()


def run(profile, trace, indexes: list, edits: dict, read: Callable, *,
        config: Optional[dict] = None,
        make_client: Optional[Callable] = None) -> dict:
    """The requests *indexes* of *trace* (`requests.Trace`), each sent once
    with the texts of *edits*. `Refused` where nothing may be sent: more
    than `LIMIT` requests, none, or no model named. A request whose
    instruction cannot be put together is not sent and says why."""
    indexes = list(indexes)
    if not indexes:
        raise Refused("Choose at least one request to send.")
    if len(indexes) > LIMIT:
        raise Refused(f"One click on Try sends {LIMIT} requests at most, "
                      f"but {len(indexes)} were chosen.")
    config = config or settings()
    if not config.get("configured"):
        raise Refused(config.get("why") or NO_MODEL)
    client = None
    results = []
    for index in indexes:
        if not isinstance(index, int) \
                or not 0 <= index < len(trace.requests):
            raise Refused(f"The request log has no request {index!r}.")
        request, sent = trace.requests[index], trace.sent(index)
        old = {"answer": request.get("answer"),
               "answer_json": request.get("answer_json"),
               "check": request.get("check")}
        view = prompts.preview(profile, request, sent or {}, edits, read)
        if view["why"]:
            results.append({"index": index, "sent": False,
                            "why": view["why"], "old": old, "new": None})
            continue
        if client is None:
            client = (make_client or client_of)(config)
        new = once(client, config["model"], request, sent, view)
        row = {"index": index, "sent": True, "why": None, "old": old,
               "new": new, "changed_request": view["changed"],
               "same": None, "addresses": [], "holds": None}
        if new["error"] is None:
            row["same"] = _same(old, new)
            payload, _, _ = prompts.payload_of(sent)
            row["addresses"] = addresses(new["answer_json"], payload) \
                if new["answer_json"] is not None else []
            held = [one["holds"] for one in row["addresses"]
                    if one["holds"] is not None]
            row["holds"] = all(held) if held else None
        results.append(row)
    sent_rows = [row for row in results if row["sent"]]
    answered = [row for row in sent_rows if row["new"]["error"] is None]
    return {
        "model": config["model"], "host": config.get("host"),
        "results": results,
        "counts": {
            "named": len(indexes), "sent": len(sent_rows),
            "failed": len(sent_rows) - len(answered),
            "same": sum(row["same"] is True for row in answered),
            "different": sum(row["same"] is False for row in answered),
            "out_of_form": sum(not row["new"]["in_form"]
                               for row in answered),
            "addresses_hold": sum(row["holds"] is True for row in answered),
            "addresses_fail": sum(row["holds"] is False
                                  for row in answered)}}
