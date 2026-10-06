"""
llm_client.py – Remote LLM (OpenAI-compatible) for search-phrase generation and
batch-by-batch question answering.

Two independent budgets (do not conflate):
  * MAX_CHUNK_ATTEMPTS: how many content chunks are shown to the LLM (the
    outer loop, in answer.py).
  * LLM_MAX_RETRIES: attempts of a *single* call: a reply that cannot be
    read is asked again with its cause named, a transport error after a
    pause (the inner loop here). Does not advance the chunk count.

A reply is exactly one JSON object, read by `docpipe.reading`. Nothing is
repaired: no fence, no think block, no text around the object is removed, and
no bracket is closed. A reply that is not that object is classified, asked
again with the cause named, and where it stays unreadable the request ends
with a `ReplyError` that carries the cause. A reply cut off at its token
limit is not asked again as it stands: a batch of excerpts is halved, and a
single unit gets more room once.

Author: Felix Vossel
"""
from __future__ import annotations

import base64
import contextlib
import contextvars
import io
import json
import logging
import re
import time
from typing import Optional

from .config import (
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_API_KEY,
    LLM_TIMEOUT,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    LLM_MAX_RETRIES,
    LLM_STUB_MODE,
)

from docpipe import prompts, providers, reading
from docpipe.llm_preflight import request_extras
from docpipe.prompts import per_profile as prompts_per_profile

from . import replies, wording

log = logging.getLogger(__name__)

# How often a batch of excerpts whose reply was cut off is halved. The
# harvest's depth (`EXTRACT_SPLIT_DEPTH`): three halvings leave an eighth.
SPLIT_DEPTH = 3


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
# Read when first used, not when this module is imported: the app, a test
# and `--help` can import the answer loop before anybody has named a profile.
# Everything the loop says around the prompts comes from the same profile
# (`wording.phrases`), and is read the same way. Where none is named, that is
# the built-in one.
_PROMPTS = {
    "PHRASE_SYSTEM_PROMPT": "inference/phrase",
    "CHUNK_QA_SYSTEM_PROMPT": "inference/chunk_qa",
    "IMAGE_PHRASE_SYSTEM_PROMPT": "inference/image_phrase",
    "_ANSWER_PROMPT_HEAD": "inference/answer_head",
    "_ANSWER_PROMPT_TAIL": "inference/answer_tail",
    "JSON_FORMAT_PROMPT": "inference/json_format",
    "COMPARE_PROMPT": "inference/compare",
    "_COMPUTE_HINT": "inference/compute_hint",
    "_IMAGE_HINT": "inference/image_hint",
    "READOFF_PROMPT": "inference/readoff",
}
# What the loop loads, for whoever asks whether a profile has all of it.
PROMPT_IDS = tuple(_PROMPTS.values())


@prompts_per_profile
def _texts() -> dict:
    return {}


def _prompt(prompt_id: str) -> str:
    """One prompt of the profile in force, read once per profile; without
    one, of the built-in profile (`wording.chat_profile`)."""
    texts = _texts()
    if prompt_id not in texts:
        texts[prompt_id] = prompts.load(prompt_id,
                                        wording.chat_profile()).text
    return texts[prompt_id]


def __getattr__(name: str):
    """The prompts under the names they had as module constants."""
    if name in _PROMPTS:
        return _prompt(_PROMPTS[name])
    if name == "_W":
        return wording.phrases()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _w() -> dict:
    """What the loop says around the prompts, from the same profile."""
    return wording.phrases()


# answer_head / answer_tail: batched QA. The top sources are handed over
# together with a "prior" partial answer carried across batches. Every
# statement is tied to a source via a verbatim `quote` + `index`, validated by
# the caller. Assembled at call time with the answer-format spec spliced in,
# so the literal `{...}` braces there need no escaping.
#
# compare: one comparison over the finished per-document answers. Its own
# prompt: the answering prompt is written to stay inside one document, and
# the comparison has no document in front of it at all.
#
# compute_hint: appended to the answer prompt only when a code-exec sandbox is
# available: the model answers with an action object, the caller runs it and
# feeds the printed output back, then the model finalises.
#
# image_hint: the model may ask for a crop the section text only points at;
# see db.request_item.


# ---------------------------------------------------------------------------
# Client + parsing helpers
# ---------------------------------------------------------------------------
_client = None


def get_client():
    """Lazily build the client (own retry loop → max_retries=0)."""
    global _client
    if _client is None:
        _client = providers.client(
            "llm",
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            timeout=LLM_TIMEOUT,
            max_retries=0,
        )
    return _client


# Why a request of the chat ended without its reply: a cause of the shared
# reader (`reading.HOLE_CAUSES`), or that it was never sent because the
# provider cannot be asked for the shape in question.
NOT_ASKED = "not_asked"
FAULT_CAUSES = reading.HOLE_CAUSES + (NOT_ASKED,)


class ReplyError(RuntimeError):
    """A request that ended with no reply that could be read.

    *cause* is one of `reading.HOLE_CAUSES` (the last thing that went wrong:
    a reply that was not the one object, a reply cut off at its token limit,
    or a server that did not answer), *request* the name of the reply that
    was asked for. A RuntimeError, so what always caught the failure of a
    call still does; what is new is that it says why.
    """

    def __init__(self, cause: str, request: str, attempts: int = 1):
        if cause not in reading.HOLE_CAUSES:
            raise ValueError(f"{cause!r} is no cause of a reply that could "
                             f"not be read; one of: "
                             f"{', '.join(reading.HOLE_CAUSES)}")
        self.cause, self.request, self.attempts = cause, request, attempts
        super().__init__(f"{request}: no reply that could be read after "
                         f"{attempts} attempt(s), last cause: {cause}")


# The requests of one turn that left a hole, so a caller that swallows the
# error of a request (a search phrase, a read-off, a comparison) still leaves
# a record the reader of the page can be shown. Beside the arguments, like
# `_SHAPE`: `_chat_json(messages, temperature)` is the seam every test of the
# answer loop replaces.
_FAULTS: contextvars.ContextVar = contextvars.ContextVar("reply_faults",
                                                         default=None)


@contextlib.contextmanager
def collecting():
    """The faults of the requests made inside the block, as a list of
    {"request": the reply asked for, "cause": why there is none}."""
    faults: list = []
    token = _FAULTS.set(faults)
    try:
        yield faults
    finally:
        _FAULTS.reset(token)


def note_fault(request: str, cause: str) -> None:
    """Record that *request* has no reply, in the turn that is collecting."""
    if cause not in FAULT_CAUSES:
        raise ValueError(f"{cause!r} is no cause; one of: "
                         f"{', '.join(FAULT_CAUSES)}")
    faults = _FAULTS.get()
    if faults is not None:
        faults.append({"request": request, "cause": cause})


def describe_faults(faults: list) -> str:
    """"request: cause" per kind of fault, with "xN" where it happened N
    times, in the order the first of each happened."""
    counted: dict = {}
    for fault in faults:
        key = f"{fault['request']}: {fault['cause']}"
        counted[key] = counted.get(key, 0) + 1
    return ", ".join(key if n == 1 else f"{key} x{n}"
                     for key, n in counted.items())


def _backoff(attempt: int) -> None:
    if attempt < LLM_MAX_RETRIES:
        time.sleep(min(2 * attempt, 10))


# ---------------------------------------------------------------------------
# Grounding check — the anti-hallucination gate
# ---------------------------------------------------------------------------
_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    """Whitespace-collapsed, case-folded form for tolerant substring matching."""
    return _WS_RE.sub(" ", (s or "").casefold()).strip()


def _clean_quote(q) -> str:
    """Trim a supporting quote and strip one layer of wrapping quotation marks."""
    s = str(q or "").strip()
    for lq, rq in (('"', '"'), ("'", "'"), ("„", "“"), ("“", "”"), ("»", "«")):
        if len(s) >= 2 and s[0] == lq and s[-1] == rq:
            s = s[1:-1].strip()
            break
    return s


def _quote_is_grounded(quote: str, chunk_items: list[dict]) -> bool:
    """
    True iff `quote` is a verbatim (whitespace/case-tolerant) span of the excerpt.

    The guard against fabricated answers. A match under 12 chars is rejected too,
    so a stray common word (e.g. "GmbH") cannot pass as evidence.
    """
    q = _norm(quote)
    if len(q) < 12:
        return False
    haystack = _norm(" ".join(str(it.get("text", "")) for it in chunk_items))
    return q in haystack


# The reply the request under way asks for: (name, schema), or None. Beside
# the arguments and not among them, because `_chat_json(messages,
# temperature)` is the seam every test of the answer loop replaces.
_SHAPE: contextvars.ContextVar = contextvars.ContextVar("reply_shape",
                                                        default=None)
# The token limit of the request under way, where it is not the setting's: the
# room a reply that was cut off is given once.
_ROOM: contextvars.ContextVar = contextvars.ContextVar("reply_room",
                                                       default=None)


def _ask(shape, messages: list, temperature: float,
         splittable: bool = False) -> dict:
    """`_chat_json` for a request whose reply has this shape.

    A reply that was cut off at its token limit is asked for again as it
    stands only where the request cannot be made smaller: a single unit gets
    twice the room, once. Where *splittable* says the caller can ask for less
    (a batch of excerpts it can halve), the cut is the caller's to answer and
    is raised at once.

    A cut that is answered, by the caller's halves or by the room given here,
    is no hole: the note `_chat_json` made of it is taken back, so the fault
    list holds a request only where it was left without a reply.
    """
    token = _SHAPE.set(shape)
    faults = _FAULTS.get()
    noted = len(faults) if faults is not None else 0
    try:
        try:
            return _chat_json(messages, temperature=temperature)
        except ReplyError as cut:
            if cut.cause != "cut_off":
                raise
            if faults is not None:
                del faults[noted:]
            if splittable:
                raise
        room = _ROOM.get() or LLM_MAX_TOKENS
        log.warning("%s was cut off at %d tokens: asked again with %d tokens",
                    shape[0] if shape else "json_reply", room, 2 * room)
        more = _ROOM.set(2 * room)
        try:
            return _chat_json(messages, temperature=temperature)
        finally:
            _ROOM.reset(more)
    finally:
        _SHAPE.reset(token)


def _reply_format() -> dict:
    """The schema of the reply is the grammar of the request, on every
    provider: what the model may write is what the reader reads.

    LLM_SCHEMA widens what a server of one's own is asked in schema for (the
    harvest's other requests); it has no value that turns the grammar off,
    so there is none to honour here. A reply with no shape is the answer
    reshaped into the JSON the user's task describes in prose, and has only
    the one rule: one object.
    """
    shape = _SHAPE.get()
    if shape is None:
        return {"type": "json_object"}
    return providers.grammar(*shape)


def _read(choice, shape) -> tuple:
    """(object, "", "") for a reply that is the one object the shape asks for,
    else (None, cause, sentence for the retry). `docpipe.reading` says which,
    in the words of the profile the chat answers in."""
    key, kind, instead = replies.needs(shape)
    with reading.speaking(wording.chat_profile()):
        data, cause, said = reading.read(choice)
        if cause or not key:
            return data, cause, said
        if instead and instead in data:
            return data, "", ""
        return reading.read(choice, key=key, of=kind)


def _with_correction(messages: list, said: str) -> list:
    """The same single user turn, with what was wrong appended to it.

    No assistant turn is echoed: some gateways reject a JSON-string assistant
    turn, and the sentence carries the place and the text that broke the
    reply itself.
    """
    out = [dict(m) for m in messages]
    last = out[-1]
    content = last["content"]
    if isinstance(content, list):
        last["content"] = [*content, {"type": "text", "text": said}]
    else:
        last["content"] = f"{content}\n\n{said}"
    return out


def _chat_json(messages: list, temperature: float) -> dict:
    """One chat completion returning the one JSON object that was asked for.

    A transport error starts the call over from the original turn after a
    pause; a reply that is not the object is asked again at once with the
    cause named. A reply cut off at its token limit is not asked again as it
    stands (`_ask` decides what happens instead). When the attempts
    (LLM_MAX_RETRIES) are used up, or the reply was cut off, it raises a
    `ReplyError` with the last cause, and the turn's fault list notes it
    (`_ask` takes the note back of a cut that it or its caller answers).
    """
    client = get_client()
    shape = _SHAPE.get()
    request = shape[0] if shape else "json_reply"
    base_messages = list(messages)
    convo = list(base_messages)
    cause = "not_served"
    attempt = 0

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=convo,
                response_format=_reply_format(),
                temperature=temperature,
                max_tokens=_ROOM.get() or LLM_MAX_TOKENS,
                extra_body=request_extras(),
            )
        except Exception as e:  # transport / timeout: start over, back off
            log.warning("LLM call failed (attempt %d/%d): %s", attempt,
                        LLM_MAX_RETRIES, e)
            cause = "not_served"
            convo = list(base_messages)
            _backoff(attempt)
            continue
        choice = reading.first(response)
        data, cause, said = _read(choice, shape)
        if not cause:
            return data
        log.warning("%s: %s reply (attempt %d/%d, finish: %s)", request, cause,
                    attempt, LLM_MAX_RETRIES,
                    getattr(choice, "finish_reason", None))
        if cause == "cut_off":
            break
        convo = _with_correction(base_messages, said)

    note_fault(request, cause)
    raise ReplyError(cause, request, attempt)


def choose(prompt, task: str, question: str, options: dict) -> Optional[str]:
    """One closed question: the answer is a key of `options`, or None.

    The KG route's field request. `prompt` is the profile's, loaded by
    kg_route; the payload keys are the wire protocol and its prose is not.
    An answer outside the list is None and never the nearest key: the caller
    reads None as "no constraint", and a guessed key would filter the graph
    on something nobody asked. An empty list is a number slot, and any
    non-empty answer passes through for the caller to parse.
    """
    if LLM_STUB_MODE:
        return None
    payload = {"task": task, "question": question, "options": options}
    parsed = _ask(
        replies.CHOOSE,
        [{"role": "system", "content": prompt.text},
         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        temperature=float(prompt.meta.get("temperature", 0)))
    answer = parsed.get("answer")
    if answer is None:
        return None
    answer = str(answer).strip()
    if not answer or (options and answer not in options):
        return None
    return answer


def grounded_quote(quote, chunk_item: dict) -> Optional[str]:
    """Return the cleaned quote iff it is a grounded verbatim span of `chunk_item`."""
    q = _clean_quote(quote)
    return q if _quote_is_grounded(q, [chunk_item]) else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _history_context(history: Optional[list], limit: int = 5) -> str:
    """
    A compact block of the last `limit` turns (question, anchor, answer — never
    the retrieved excerpts) for resolving references in a follow-up. Framed
    strictly as reference-resolution help, never as a fact source, so grounding
    stays tied to the current excerpts. Empty string if there is no history.
    """
    if not history:
        return ""
    blocks = []
    for turn in history[-limit:]:
        task = str(turn.get("task", "")).strip()
        if not task:
            continue
        lines = [f"- {_w()['history_task']}: {task}"]
        anchor = str(turn.get("phrase", "")).strip()
        if anchor:
            lines.append(f"  {_w()['history_phrase']}: {anchor}")
        answer = str(turn.get("answer", "")).strip()
        if answer:
            lines.append(f"  {_w()['history_answer']}: {answer[:800]}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return f"\n\n{_w()['history_heading']}:\n" + "\n".join(blocks)




def make_search_phrase(task: str, visual: bool = False,
                       history: Optional[list] = None) -> tuple[str, bool]:
    """
    Turn a free-text extraction task into a HyDE-style search anchor: a short
    hypothetical passage written as it would appear IN a heat plan, rather than a
    question. `visual=True` produces a figure/caption-style anchor instead.

    Returns (phrase, recheck). `recheck` is True when the task re-asks an earlier
    question from the history ("schau noch einmal nach") — the caller then steers
    retrieval away from the sources that earlier attempt already examined. Only
    meaningful with history; forced False without one.

    Never raises: falls back to (raw task, False), which is always a safe
    retrieval probe. The anchor is only a retrieval probe — the answer still
    comes from the real retrieved text under the grounding gate.
    """
    if LLM_STUB_MODE:
        return task.strip(), False
    # No `system` role: the gateway's agent supplies a leading system message and
    # rejects a second one ("System message must be at the beginning"). Fold our
    # instructions into the user turn instead.
    prompt = _prompt("inference/image_phrase") if visual else _prompt("inference/phrase")
    base = f"{prompt}{_history_context(history)}\n\n{_w()['task_heading']}:\n{task}"
    messages = [{"role": "user", "content": base}]
    try:
        parsed = _ask(replies.PHRASE, messages, temperature=LLM_TEMPERATURE)
    except Exception as e:
        log.warning("Search-phrase generation failed, using raw task: %s", e)
        return task.strip(), False
    # Whatever sentence the model wrote is the anchor: no filter on it was
    # ever approved. Only an empty one is no sentence at all, and that is a
    # hole in the turn's record, not a quiet fallback.
    phrase = str(parsed.get("phrase", "")).strip()
    if phrase:
        return phrase, bool(parsed.get("repetition")) and bool(history)
    log.warning("Search phrase came back empty, using raw task")
    note_fault(replies.PHRASE[0], "wrong_shape")
    return task.strip(), False


def ask_chunk(task: str, chunk_items: list[dict]) -> dict:
    """
    Ask the LLM to answer `task` using only `chunk_items`.

    Returns {"found": True, "answer", "quote"} or {"found": False}. Never raises:
    a malformed response, an empty answer, or a quote that is not grounded in the
    excerpt all come back as {"found": False}.
    """
    if LLM_STUB_MODE:
        first = chunk_items[0] if chunk_items else {}
        return {
            "found": True,
            "answer": f"[STUB] answer based on: {first.get('source', 'n/a')}",
            "quote": str(first.get("text", ""))[:120],
        }

    # No `system` role — see make_search_phrase.
    payload = json.dumps({"task": task, "excerpt": chunk_items}, ensure_ascii=False)
    messages = [
        {"role": "user", "content": f"{_prompt('inference/chunk_qa')}\n\n{payload}"},
    ]
    try:
        parsed = _ask(replies.CHUNK, messages, temperature=LLM_TEMPERATURE)
    except Exception as e:
        log.warning("Chunk QA produced no valid JSON, treating as not-found: %s", e)
        return {"found": False}

    found = bool(parsed.get("found"))
    if not found:
        return {"found": False}

    answer = str(parsed.get("answer", "")).strip()
    if not answer:
        log.warning("Chunk QA claimed found=true but gave empty answer, treating as not-found")
        return {"found": False}

    # Anti-hallucination gate: the answer must be backed by a verbatim quote that
    # actually occurs in the excerpt.
    quote = _clean_quote(parsed.get("quote", ""))
    if not _quote_is_grounded(quote, chunk_items):
        log.warning("Chunk QA answer not backed by a verbatim quote from the excerpt "
                    "(likely fabricated), treating as not-found")
        return {"found": False}

    return {"found": True, "answer": answer, "quote": quote}


def _format_exec_result(out: dict) -> str:
    """The user-turn text fed back to the model after a sandbox run."""
    if out.get("ok"):
        s = (out.get("stdout") or "").strip()
        return f"{_w()['exec_stdout']}:\n" + (s if s else _w()["exec_empty"])
    err = (out.get("error") or (out.get("stderr") or "")).strip() or _w()["exec_unknown"]
    return f"{_w()['exec_failed']}:\n" + err[:1500] + "\n" + _w()["exec_recover"]


def _compute_tail(compute: list, force: bool) -> str:
    """
    User-message suffix carrying prior code runs. The ReAct loop must stay
    SINGLE-TURN (no assistant echo of the action JSON) because some gateway
    agents reject a JSON-string assistant turn — so each round re-sends the
    accumulated results inside the user message.
    """
    if not compute:
        return ""
    # Numbered, so that a statement about a calculated value can name the run
    # that printed it. The numbers restart with every call.
    done = "\n\n".join(
        f"{_w()['code_heading']} {n}:\n{c['code']}\n"
        f"{_format_exec_result(c['output'])}"
        for n, c in enumerate(compute, start=1))
    guide = _w()["compute_guide_final"] if force else _w()["compute_guide"]
    return f"\n\n{_w()['compute_heading']}:\n" + done + "\n\n" + guide


def _requested_tail(requested: list, force: bool) -> str:
    """
    User-message suffix listing the crops the model asked for. Same single-turn
    reason as _compute_tail: the images themselves ride along as message parts,
    this only tells the model which arrived and what it may still do.
    """
    if not requested:
        return ""
    done = "\n".join(f"- [{r['block_id']}] {r.get('title') or _w()['image_uncaptioned']}"
                     f"{'' if r.get('delivered') else ' — ' + _w()['image_unavailable']}"
                     for r in requested)
    guide = _w()["image_guide_final"] if force else _w()["image_guide"]
    return f"\n\n{_w()['image_heading']}:\n" + done + "\n\n" + guide


def _image_part(path: str, max_side: int = None, png: bool = False) -> Optional[dict]:
    """
    Downscaled data-URL image part for a chat message, or None if unreadable.

    `png=True` for the focused read-off call: charts are synthetic graphics with
    thin lines and small axis labels, exactly what JPEG artefacts blur first.
    """
    from .config import ANSWER_IMAGE_MAX_SIDE
    max_side = max_side or ANSWER_IMAGE_MAX_SIDE
    try:
        from PIL import Image
        img = Image.open(path)
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        if png:
            img.save(buf, format="PNG")
            mime = "image/png"
        else:
            img.convert("RGB").save(buf, format="JPEG", quality=88)
            mime = "image/jpeg"
    except Exception as e:
        log.warning("Crop not attachable (%s): %s", path, e)
        return None
    url = f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()
    return {"type": "image_url", "image_url": {"url": url}}


def _answer_messages(text: str, image_parts: list) -> list:
    """One user message: plain string, or a content array when crops ride along."""
    if not image_parts:
        return [{"role": "user", "content": text}]
    return [{"role": "user", "content": [{"type": "text", "text": text}, *image_parts]}]






def read_off_image(task: str, image_path: str, hint: str) -> Optional[dict]:
    """
    Focused single-image read-off: one crop, one short question — the setting
    in which the model demonstrably reads charts correctly, unlike the big
    answer call whose many sources and images dilute attention (observed:
    total bar height returned as a single segment's value).

    Returns the parsed {"reading", "value", "unit", "confidence"} or None.
    Never raises. None leaves the turn's record a fault: a reply that could
    not be read is the request's `ReplyError`, a reading that came back blank
    is noted here.
    """
    if LLM_STUB_MODE:
        return None
    from .config import READOFF_IMAGE_MAX_SIDE
    part = _image_part(image_path, max_side=READOFF_IMAGE_MAX_SIDE, png=True)
    if part is None:
        return None
    text = (f"{_prompt('inference/readoff')}\n{_w()['task_heading']}:\n{task}\n\n"
            f"{_w()['readoff_heading']}:\n{hint}")
    try:
        parsed = _ask(
            replies.READOFF,
            [{"role": "user", "content": [{"type": "text", "text": text}, part]}],
            temperature=LLM_TEMPERATURE)
    except Exception as e:
        log.warning("Focused read-off failed, keeping the inline reading: %s", e)
        return None
    sentence = str(parsed.get("reading") or "").strip()
    if not sentence:
        log.warning("Focused read-off came back blank, keeping the inline reading")
        note_fault(replies.READOFF[0], "wrong_shape")
        return None
    # The model sometimes echoes the hint as "reading" without the number --
    # the value then only exists in "value", and the reading is what the
    # reader is shown as the statement. Splice it in.
    value = parsed.get("value")
    if isinstance(value, (int, float)) and f"{value:g}" not in sentence:
        unit = str(parsed.get("unit") or "").strip()
        sentence = _w()["readoff_value"].format(
            reading=sentence, value=f"{value:g}", unit=unit).strip()
    parsed["reading"] = sentence
    return parsed


def crop_id(block) -> str:
    """A crop a model names (as a statement's `block`, or as the `id` it asked
    for) as a block id: the model quotes what it saw, and what it saw was
    [p17_img1]."""
    return str(block or "").strip().strip("[]").strip()


def visual_reading(statement: dict, attached_images: set,
                   delivered=frozenset()) -> Optional[str]:
    """
    The read-off text of a valid image-based statement, else None.

    Valid only when the crop it names was actually in front of the model: the
    cited index's crop was attached to the call, or the block is one the model
    asked for and got (`delivered`); otherwise an "image" statement could
    launder parametric knowledge past the grounding gate, which is exactly
    what the verbatim-quote rule exists to stop. The reading has to say what
    was read (8 characters at least).
    """
    if statement.get("basis") != "image":
        return None
    sentence = str(statement.get("reading") or "").strip()
    if len(sentence) < 8:
        return None
    block = crop_id(statement.get("block"))
    if block:
        return sentence if block in delivered else None
    index = statement.get("index")
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    return sentence if index in attached_images else None


def _joined(first: dict, second: dict) -> dict:
    """The answers of two halves of one batch as the answer of the batch.

    Excerpt indices are those of the whole retrieval, so statements need no
    relabelling. Run numbers are not: each half numbers its own code runs from
    1, so the second half's statements are shifted past the first half's.
    """
    shift = len(first["compute"])
    moved = []
    for statement in second["statements"]:
        run = statement.get("run") if isinstance(statement, dict) else None
        if isinstance(run, int) and not isinstance(run, bool):
            statement = {**statement, "run": run + shift}
        moved.append(statement)
    return {"statements": [*first["statements"], *moved],
            "complete": bool(first["complete"] and second["complete"]),
            "compute": [*first["compute"], *second["compute"]],
            "attached_images": sorted({*first["attached_images"],
                                       *second["attached_images"]}),
            "requested": [*first["requested"], *second["requested"]],
            "fault": first["fault"] or second["fault"]}


def answer_from_sources(task: str, chunk_items: list[dict],
                        prior: Optional[list] = None,
                        code_runner=None, code_context: Optional[dict] = None,
                        max_compute: int = 0, history: Optional[list] = None,
                        images: Optional[dict] = None,
                        image_requester=None, max_image_requests: int = 0,
                        _depth: int = 0) -> dict:
    """
    Answer `task` from the given batch of sources with statements, each with
    its own evidence (`replies.answer`). `prior` is the texts of the
    statements already checked in earlier batches, or None; only new
    statements come back. Returns:
        {"statements": [<what the model wrote>], "complete": bool,
         "compute": [{"code", "output"}], "attached_images": [<int>, ...],
         "requested": [{"block_id", "delivered", ...}], "fault": cause | None}
    `complete=False` → more sources may be needed. The CALLER checks every
    statement against its source (`statements.back`); this function does not.
    There is no `found`: a batch said something if `statements` is not empty.

    `fault` is None when a reply was read. A request that stays unreadable
    leaves `statements` empty and names the cause (and is noted in the turn's
    fault list); it is a hole, never "nothing found". A reply cut off at its
    token limit halves the batch (up to SPLIT_DEPTH times) and joins what the
    halves say; a single excerpt gets more room once, then it is a hole.

    `images` maps an item index to a local crop path; those crops are attached
    to the call so the model can read values that exist only in a chart.
    `attached_images` lists the indices that actually made it into the request —
    the only ones an "image" statement may legitimately cite by index.

    When `code_runner` is given and `max_compute > 0`, the model may reply with
    {"action":"python","code":...} to offload a calculation: `code_runner(code,
    code_context)` is called (→ {"ok","stdout","stderr","error"}), its printed
    output fed back, and the model finalises, up to `max_compute` runs. The
    runs are numbered from 1 in every call, which is what a "computed"
    statement names as its `run`.
    """
    if LLM_STUB_MODE:
        first = chunk_items[0] if chunk_items else None
        stub = [] if first is None else [{
            "statement": f"[STUB] answer based on: {first.get('source', 'n/a')}",
            "basis": "text", "index": first.get("index", 0),
            "quote": str(first.get("text", ""))[:120]}]
        return {"statements": stub, "complete": True, "compute": [],
                "attached_images": [], "requested": [], "fault": None}

    prompt = _prompt("inference/answer_head") + _prompt("inference/answer_tail")
    budget = max_compute if code_runner else 0
    if budget > 0:
        prompt = prompt + _prompt("inference/compute_hint")
    if image_requester and max_image_requests > 0:
        prompt = prompt + _prompt("inference/image_hint")
    payload = json.dumps({"task": task, "prior": prior or None,
                          "excerpt": chunk_items}, ensure_ascii=False)
    base = f"{prompt}{_history_context(history)}\n\n{payload}"

    image_parts, attached = [], []
    for idx in sorted(images or {}):
        part = _image_part(images[idx])
        if part is not None:
            image_parts.append({"type": "text",
                                "text": _w()["image_part"].format(index=idx) + ":"})
            image_parts.append(part)
            attached.append(idx)

    compute: list[dict] = []
    requested: list[dict] = []
    actions = budget + (max_image_requests if image_requester else 0)
    splittable = len(chunk_items) > 1 and _depth < SPLIT_DEPTH

    def call(force: bool) -> dict:
        tail = _compute_tail(compute, force) + _requested_tail(requested, force)
        return _ask(replies.answer(actions=not force),
                    _answer_messages(base + tail, image_parts),
                    temperature=LLM_TEMPERATURE, splittable=splittable)

    try:
        reply: dict = {}
        forced = False
        for attempt in range(actions + 1):
            force = attempt == actions               # last allowed call → must answer
            reply = call(force)
            if force:
                forced = True
                break
            action = reply.get("action")
            if code_runner and action == "python" and reply.get("code"):
                code = str(reply["code"])
                out = code_runner(code, code_context) or {
                    "ok": False, "error": _w()["exec_none"]}
                compute.append({"code": code, "output": out})
                continue
            # "image" is accepted alongside "image": the surrounding prompt is German
            # and models translate the value they are asked to echo often enough.
            if (image_requester and action in ("image", "image") and reply.get("id")
                    and len(requested) < max_image_requests):
                block_id = str(reply["id"])
                if any(r["block_id"] == block_id for r in requested):
                    # Asking twice for the same crop means it did not help; a third
                    # round would only burn the budget it needs to answer with.
                    log.info("Model re-requested %s — forcing the answer", block_id)
                    break
                item = image_requester(block_id) or {}
                part = _image_part(item.get("image_path")) if item.get("image_path") else None
                if part is not None:
                    image_parts.append({"type": "text", "text": _w()[
                        "image_requested"].format(
                            id=block_id, title=item.get("title") or "")})
                    image_parts.append(part)
                requested.append({"block_id": block_id, "title": item.get("title"),
                                  "delivered": part is not None,
                                  "owner_kind": item.get("owner_kind"),
                                  "owner_id": item.get("owner_id")})
                continue
            break
        if not isinstance(reply.get("statements"), list) and not forced:
            # An action that could not be used: the answer is still owed.
            reply = call(True)
        if not isinstance(reply.get("statements"), list):
            # The reader hands on no reply without its list. A reply that
            # got here without the reader is no answer, and says so.
            note_fault(replies.ANSWER, "missing_key")
            raise ReplyError("missing_key", replies.ANSWER)
    except ReplyError as unread:
        if unread.cause == "cut_off" and splittable:
            cut = len(chunk_items) // 2
            log.warning("answer_from_sources: cut off with %d excerpt(s); "
                        "asked again as %d and %d excerpt(s)",
                        len(chunk_items), cut, len(chunk_items) - cut)
            halves = []
            for part in (chunk_items[:cut], chunk_items[cut:]):
                kept = {item["index"] for item in part}
                halves.append(answer_from_sources(
                    task, part, prior=prior, code_runner=code_runner,
                    code_context=code_context, max_compute=max_compute,
                    history=history,
                    images={i: path for i, path in (images or {}).items()
                            if i in kept} or None,
                    image_requester=image_requester,
                    max_image_requests=max_image_requests, _depth=_depth + 1))
            return _joined(*halves)
        return {"statements": [], "complete": False, "compute": compute,
                "attached_images": attached, "requested": requested,
                "fault": unread.cause}

    return {"statements": reply["statements"],
            "complete": bool(reply.get("complete")), "compute": compute,
            "attached_images": attached, "requested": requested, "fault": None}


def format_as_json(task: str, answer_text: str) -> Optional[str]:
    """Reformat a finished text answer as a pretty JSON string (schema from the task).

    None where this model cannot be asked for it: the shape is the user's own
    and exists only as prose in the task, so there is no schema to generate
    in, and a model that is asked inside schemas only is not asked for it.
    That is noted as a fault of the turn, so the reader is told that the
    answer stays prose, where it used to get a JSON that was only the answer
    wrapped in a key. A request that stays unreadable raises `ReplyError`.
    """
    if LLM_STUB_MODE:
        return json.dumps({"answer": answer_text}, ensure_ascii=False, indent=2)
    if providers.enforces_schema("llm"):
        log.warning("the answer is not reformatted as JSON: this model is "
                    "only asked inside a reply schema, and the task's own "
                    "shape is none")
        note_fault("json_format", NOT_ASKED)
        return None
    payload = json.dumps({"task": task, "answer": answer_text}, ensure_ascii=False)
    messages = [{"role": "user", "content": f"{_prompt('inference/json_format')}\n\n{payload}"}]
    obj = _ask(None, messages, temperature=LLM_TEMPERATURE)
    return json.dumps(obj, ensure_ascii=False, indent=2)


def compare_answers(task: str, plans: list) -> Optional[str]:
    """Compare the finished answers of several documents. None on any failure.

    `plans` is [{"label", "answer"}] and that is all the call gets: no source
    text, no quotes, no pages. With the passages in front of it the model can
    ground a claim about one document in another document's sentence, and the
    citations shown under the table are per document -- they would not show
    it. An entry whose answer is None found nothing grounded, which the prompt
    is told to report rather than fill in.

    A failure leaves a fault in the collecting turn: a request that stays
    unreadable through `_chat_json`, a comparison that came back blank here.
    """
    if LLM_STUB_MODE:
        return "\n".join(f"{p['label']}: {p['answer'] or '-'}" for p in plans)
    payload = json.dumps({"task": task, "documents": plans}, ensure_ascii=False)
    try:
        parsed = _ask(
            replies.COMPARE,
            [{"role": "user", "content": f"{_prompt('inference/compare')}\n\n{payload}"}],
            temperature=LLM_TEMPERATURE)
    except Exception as e:
        log.warning("Comparison failed, keeping the per-document answers: %s", e)
        return None
    comparison = str(parsed.get("comparison") or "").strip()
    if not comparison:
        note_fault(replies.COMPARE[0], "wrong_shape")
    return comparison or None
