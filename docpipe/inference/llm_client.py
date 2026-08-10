"""
llm_client.py – Remote LLM (OpenAI-compatible) for search-phrase generation and
chunk-by-chunk question answering.

Two independent budgets (do not conflate):
  * MAX_CHUNK_ATTEMPTS  – how many content chunks are shown to the LLM (the
    outer loop, in app.py).
  * LLM_MAX_RETRIES     – re-tries of a *single* call on malformed JSON or a
    transport error (the inner loop here). Does not advance the chunk count.

Author: Felix Vossel
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from typing import Optional

from openai import OpenAI

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

from docpipe import prompts

from . import wording

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
# Everything the loop says around them comes from the same profile.
_W = wording.phrases()

PHRASE_SYSTEM_PROMPT = prompts.text("inference/phrase")

CHUNK_QA_SYSTEM_PROMPT = prompts.text("inference/chunk_qa")

IMAGE_PHRASE_SYSTEM_PROMPT = prompts.text("inference/image_phrase")

# Batched QA: the top sources are handed over together with a "prior" partial
# answer carried across batches. Every statement is tied to a source via a
# verbatim `quote` + `index`, validated by the caller. Assembled at call time
# with the answer-format spec spliced in, so the literal `{...}` braces here need
# no escaping.
_ANSWER_PROMPT_HEAD = prompts.text("inference/answer_head")
_ANSWER_PROMPT_TAIL = prompts.text("inference/answer_tail")

_ANSWER_SPEC_TEXT = prompts.text("inference/answer_spec_text")
_ANSWER_SPEC_JSON = prompts.text("inference/answer_spec_json")

JSON_FORMAT_PROMPT = prompts.text("inference/json_format")

# Appended to the answer prompt only when a code-exec sandbox is available: the
# model answers with an action object, the caller runs it and feeds the printed
# output back, then the model finalises.
_COMPUTE_HINT = prompts.text("inference/compute_hint")
# The model may ask for a crop the section text only points at; see db.request_item.
_IMAGE_HINT = prompts.text("inference/image_hint")


# ---------------------------------------------------------------------------
# Client + parsing helpers
# ---------------------------------------------------------------------------
_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    """Lazily build the OpenAI-compatible client (own retry loop → max_retries=0)."""
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            timeout=LLM_TIMEOUT,
            max_retries=0,
        )
    return _client


def _loads_json_object(text: str) -> dict:
    """Parse a JSON object, tolerating a non-JSON wrapper; fall back to {...}."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def _clean_raw(text: str) -> str:
    """Strip <think> blocks and stray markdown fences before json.loads."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return text


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


def _chat_json(messages: list, temperature: float) -> dict:
    """
    One chat completion returning a parsed JSON object, with a
    retry/self-correction loop. Raises RuntimeError if all retries fail.
    """
    client = get_client()
    base_messages = list(messages)
    convo = list(base_messages)

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        raw = ""
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=convo,
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=LLM_MAX_TOKENS,
            )
            raw = _clean_raw(response.choices[0].message.content or "")
            if not raw:
                convo = base_messages + [
                    {"role": "assistant", "content": ""},
                    {"role": "user", "content": _W["empty_reply"]},
                ]
                _backoff(attempt)
                continue
            return _loads_json_object(raw)
        except json.JSONDecodeError as e:
            log.warning("LLM JSON parse failed (attempt %d/%d): %s", attempt, LLM_MAX_RETRIES, e)
            convo = base_messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _W["parse_error"].format(error=e)},
            ]
            _backoff(attempt)
        except Exception as e:  # transport / timeout → reset conversation, back off
            log.warning("LLM call failed (attempt %d/%d): %s", attempt, LLM_MAX_RETRIES, e)
            convo = list(base_messages)
            _backoff(attempt)

    raise RuntimeError(f"LLM call failed after {LLM_MAX_RETRIES} attempts")


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
        lines = [f"- {_W['history_task']}: {task}"]
        anchor = str(turn.get("phrase", "")).strip()
        if anchor:
            lines.append(f"  {_W['history_phrase']}: {anchor}")
        answer = str(turn.get("answer", "")).strip()
        if answer:
            lines.append(f"  {_W['history_answer']}: {answer[:800]}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return f"\n\n{_W['history_heading']}:\n" + "\n".join(blocks)


# A search anchor is a HYPOTHETICAL, present-tense passage/caption. If the model
# slips into evaluating or refusing instead, the string is not an anchor at all;
# detect that and regenerate / fall back. Which words give that away is a
# property of the answer's language, so the profile supplies the pattern.
_NON_ANCHOR_RE = wording.non_anchor()

_ENVELOPE_CORRECTION = prompts.text("inference/envelope_correction")

_ANCHOR_CORRECTION = prompts.text("inference/anchor_correction")


def _is_off_envelope(parsed) -> bool:
    """True if the model replied with some other object instead of the answer envelope."""
    return isinstance(parsed, dict) and bool(parsed) and "found" not in parsed


def _looks_like_non_anchor(phrase: str) -> bool:
    """True if the 'phrase' reads as an evaluation/refusal instead of an anchor."""
    return bool(_NON_ANCHOR_RE.search(phrase or ""))


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
    prompt = IMAGE_PHRASE_SYSTEM_PROMPT if visual else PHRASE_SYSTEM_PROMPT
    base = f"{prompt}{_history_context(history)}\n\n{_W['task_heading']}:\n{task}"
    messages = [{"role": "user", "content": base}]
    # If the model evaluates/denies instead of anchoring, re-ask once with a
    # correction, then fall back to the raw task.
    for attempt in range(2):
        try:
            parsed = _chat_json(messages, temperature=LLM_TEMPERATURE)
        except Exception as e:
            log.warning("Search-phrase generation failed, using raw task: %s", e)
            return task.strip(), False
        phrase = str(parsed.get("phrase", "")).strip()
        if phrase and not _looks_like_non_anchor(phrase):
            return phrase, bool(parsed.get("repetition")) and bool(history)
        log.warning("Search phrase read as evaluation/denial, retrying: %r", phrase)
        messages = [{"role": "user", "content": f"{base}\n\n{_ANCHOR_CORRECTION}"}]
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
        {"role": "user", "content": f"{CHUNK_QA_SYSTEM_PROMPT}\n\n{payload}"},
    ]
    try:
        parsed = _chat_json(messages, temperature=LLM_TEMPERATURE)
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
        return f"{_W['exec_stdout']}:\n" + (s if s else _W["exec_empty"])
    err = (out.get("error") or (out.get("stderr") or "")).strip() or _W["exec_unknown"]
    return f"{_W['exec_failed']}:\n" + err[:1500] + "\n" + _W["exec_recover"]


def _compute_tail(compute: list, force: bool) -> str:
    """
    User-message suffix carrying prior code runs. The ReAct loop must stay
    SINGLE-TURN (no assistant echo of the action JSON) because some gateway
    agents reject a JSON-string assistant turn — so each round re-sends the
    accumulated results inside the user message.
    """
    if not compute:
        return ""
    done = "\n\n".join(f"{_W['code_heading']}:\n{c['code']}\n{_format_exec_result(c['output'])}"
                       for c in compute)
    guide = _W["compute_guide_final"] if force else _W["compute_guide"]
    return f"\n\n{_W['compute_heading']}:\n" + done + "\n\n" + guide


def _requested_tail(requested: list, force: bool) -> str:
    """
    User-message suffix listing the crops the model asked for. Same single-turn
    reason as _compute_tail: the images themselves ride along as message parts,
    this only tells the model which arrived and what it may still do.
    """
    if not requested:
        return ""
    done = "\n".join(f"- [{r['block_id']}] {r.get('title') or _W['image_uncaptioned']}"
                     f"{'' if r.get('delivered') else ' — ' + _W['image_unavailable']}"
                     for r in requested)
    guide = _W["image_guide_final"] if force else _W["image_guide"]
    return f"\n\n{_W['image_heading']}:\n" + done + "\n\n" + guide


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


READOFF_PROMPT = prompts.text("inference/readoff")

_READOFF_CORRECTION = prompts.text("inference/readoff_correction")

REVISE_PROMPT = prompts.text("inference/revise")


def read_off_image(task: str, image_path: str, hint: str) -> Optional[dict]:
    """
    Focused single-image read-off: one crop, one short question — the setting
    in which the model demonstrably reads charts correctly, unlike the big
    answer call whose many sources and images dilute attention (observed:
    total bar height returned as a single segment's value).

    Returns the parsed {"reading", "value", "unit", "confidence"} or None.
    Never raises.
    """
    if LLM_STUB_MODE:
        return None
    from .config import READOFF_IMAGE_MAX_SIDE
    part = _image_part(image_path, max_side=READOFF_IMAGE_MAX_SIDE, png=True)
    if part is None:
        return None
    text = (f"{READOFF_PROMPT}\n{_W['task_heading']}:\n{task}\n\n"
            f"{_W['readoff_heading']}:\n{hint}")
    # A format spec inside the task hijacks this schema too ({"amount": ...}
    # instead of {"reading": ...}) — re-ask once, same cure as the envelope.
    for attempt_text in (text, f"{text}\n\n{_READOFF_CORRECTION}"):
        try:
            parsed = _chat_json(
                [{"role": "user", "content": [{"type": "text", "text": attempt_text}, part]}],
                temperature=LLM_TEMPERATURE)
        except Exception as e:
            log.warning("Focused read-off failed, keeping the inline reading: %s", e)
            return None
        reading = str(parsed.get("reading") or "").strip()
        if reading:
            # The model sometimes echoes the hint as "reading" without the
            # number — the value then only exists in "value" and a revision fed
            # the bare sentence has nothing to correct with. Splice it in.
            value = parsed.get("value")
            if isinstance(value, (int, float)) and f"{value:g}" not in reading:
                unit = str(parsed.get("unit") or "").strip()
                reading = f"{reading} — abgelesener Wert: {value:g} {unit}".strip()
                parsed["reading"] = reading
            return parsed
        log.warning("Read-off ignored its schema (keys: %s), retrying", sorted(parsed)[:6])
    return None


def revise_with_readings(task: str, answer_text: str, readings: list[str]) -> str:
    """Fold the focused read-offs into the answer; the original on any failure."""
    if LLM_STUB_MODE or not readings:
        return answer_text
    payload = json.dumps({"task": task, "answer": answer_text,
                          "readings": readings}, ensure_ascii=False)
    try:
        parsed = _chat_json(
            [{"role": "user", "content": f"{REVISE_PROMPT}\n\n{payload}"}],
            temperature=LLM_TEMPERATURE)
    except Exception as e:
        log.warning("Answer revision failed, keeping the original: %s", e)
        return answer_text
    revised = str(parsed.get("answer") or "").strip()
    return revised or answer_text


def visual_reading(support: dict, attached_images: set) -> Optional[str]:
    """
    The read-off text of a valid image-based support, else None.

    Valid only when the cited index's crop was actually attached to the call —
    otherwise a "image" support could launder parametric knowledge past the
    grounding gate, which is exactly what the verbatim-quote rule exists to stop.
    """
    if not support.get("image"):
        return None
    try:
        idx = int(support.get("index"))
    except (TypeError, ValueError):
        return None
    reading = str(support.get("reading") or "").strip()
    if idx not in attached_images or len(reading) < 8:
        return None
    return reading


def answer_from_sources(task: str, chunk_items: list[dict],
                        prior: Optional[str] = None, as_json: bool = False,
                        code_runner=None, code_context: Optional[dict] = None,
                        max_compute: int = 0, history: Optional[list] = None,
                        images: Optional[dict] = None,
                        image_requester=None, max_image_requests: int = 0) -> dict:
    """
    Answer `task` from the given batch of sources, extending an optional `prior`
    partial answer. Returns:
        {"found": bool, "complete": bool, "answer": <str|dict>,
         "supports": [{"index", "quote"} | {"index", "image", "reading"}],
         "compute": [{"code", "output"}], "attached_images": [<int>, ...]}
    `complete=False` → more sources may be needed. The CALLER must validate each
    support against chunk_items (grounded_quote for text, visual_reading for
    image-based ones); this function does not.

    `images` maps an item index to a local crop path; those crops are attached
    to the call so the model can read values that exist only in a chart.
    `attached_images` lists the indices that actually made it into the request —
    the only ones a "image" support may legitimately cite.

    When `code_runner` is given and `max_compute > 0`, the model may reply with
    {"action":"python","code":...} to offload a calculation: `code_runner(code,
    code_context)` is called (→ {"ok","stdout","stderr","error"}), its printed
    output fed back, and the model finalises — up to `max_compute` runs.
    """
    if LLM_STUB_MODE:
        first = chunk_items[0] if chunk_items else {}
        ans = {"answer": f"[STUB] {first.get('source', 'n/a')}"} if as_json \
            else f"[STUB] answer based on: {first.get('source', 'n/a')}"
        return {"found": True, "complete": True, "answer": ans,
                "supports": [{"index": first.get("index", 0),
                              "quote": str(first.get("text", ""))[:120]}],
                "compute": [], "attached_images": []}

    spec = _ANSWER_SPEC_JSON if as_json else _ANSWER_SPEC_TEXT
    prompt = _ANSWER_PROMPT_HEAD + spec + _ANSWER_PROMPT_TAIL
    budget = max_compute if code_runner else 0
    if budget > 0:
        prompt = prompt + _COMPUTE_HINT
    if image_requester and max_image_requests > 0:
        prompt = prompt + _IMAGE_HINT
    payload = json.dumps({"task": task, "prior": prior, "excerpt": chunk_items},
                         ensure_ascii=False)
    base = f"{prompt}{_history_context(history)}\n\n{payload}"

    image_parts, attached = [], []
    for idx in sorted(images or {}):
        part = _image_part(images[idx])
        if part is not None:
            image_parts.append({"type": "text",
                                "text": _W["image_part"].format(index=idx) + ":"})
            image_parts.append(part)
            attached.append(idx)

    compute: list[dict] = []
    requested: list[dict] = []
    parsed: dict = {}
    actions = budget + (max_image_requests if image_requester else 0)
    for attempt in range(actions + 1):
        force = attempt == actions                   # last allowed call → must answer
        tail = _compute_tail(compute, force) + _requested_tail(requested, force)
        try:
            parsed = _chat_json(
                _answer_messages(base + tail, image_parts),
                temperature=LLM_TEMPERATURE)
        except Exception as e:
            log.warning("answer_from_sources produced no valid JSON, treating as not-found: %s", e)
            return {"found": False, "complete": False, "compute": compute}
        action = parsed.get("action") if isinstance(parsed, dict) else None
        if force:
            break
        if code_runner and action == "python" and parsed.get("code"):
            code = str(parsed["code"])
            out = code_runner(code, code_context) or {"ok": False, "error": "kein Ergebnis"}
            compute.append({"code": code, "output": out})
            continue
        # "image" is accepted alongside "image": the surrounding prompt is German
        # and models translate the value they are asked to echo often enough.
        if (image_requester and action in ("image", "image") and parsed.get("id")
                and len(requested) < max_image_requests):
            block_id = str(parsed["id"])
            if any(r["block_id"] == block_id for r in requested):
                # Asking twice for the same crop means it did not help; a third
                # round would only burn the budget it needs to answer with.
                log.info("Model re-requested %s — forcing the answer", block_id)
                break
            item = image_requester(block_id) or {}
            part = _image_part(item.get("image_path")) if item.get("image_path") else None
            if part is not None:
                image_parts.append({"type": "text",
                                    "text": f"Angefordertes Bild [{block_id}]: "
                                            f"{item.get('title') or ''}"})
                image_parts.append(part)
            requested.append({"block_id": block_id, "title": item.get("title"),
                              "delivered": part is not None,
                              "owner_kind": item.get("owner_kind"),
                              "owner_id": item.get("owner_id")})
            continue
        break

    # A format spec inside the user's task ("Antwort als JSON im Format {...}")
    # makes the model emit THAT schema instead of this envelope. The reply parses
    # fine but carries no "found", so it would read as an ordinary miss and be
    # reported as "nothing in the document". Re-ask once with a correction.
    if _is_off_envelope(parsed):
        log.warning("Answer ignored the response envelope (keys: %s), retrying",
                    sorted(parsed)[:8])
        try:
            parsed = _chat_json(
                _answer_messages(
                    f"{base}{_compute_tail(compute, True)}\n\n{_ENVELOPE_CORRECTION}",
                    image_parts),
                temperature=LLM_TEMPERATURE)
        except Exception as e:
            log.warning("Envelope retry produced no valid JSON: %s", e)
            return {"found": False, "complete": False, "compute": compute}
        if _is_off_envelope(parsed):
            log.error("Answer still off-envelope after retry (keys: %s) — discarded",
                      sorted(parsed)[:8])
            return {"found": False, "complete": False, "compute": compute,
                    "off_envelope": True}

    complete = bool(parsed.get("complete"))
    if not bool(parsed.get("found")):
        return {"found": False, "complete": complete, "compute": compute}
    answer = parsed.get("answer")
    if answer is None or (isinstance(answer, str) and not answer.strip()):
        return {"found": False, "complete": complete, "compute": compute}
    supports = parsed.get("supports", [])
    if not isinstance(supports, list):
        supports = []
    return {"found": True, "complete": complete, "answer": answer,
            "supports": supports, "compute": compute, "attached_images": attached,
            "requested": requested}


def format_as_json(task: str, answer_text: str) -> str:
    """Reformat a finished text answer as a pretty JSON string (schema from the task)."""
    if LLM_STUB_MODE:
        return json.dumps({"answer": answer_text}, ensure_ascii=False, indent=2)
    payload = json.dumps({"task": task, "answer": answer_text}, ensure_ascii=False)
    messages = [{"role": "user", "content": f"{JSON_FORMAT_PROMPT}\n\n{payload}"}]
    obj = _chat_json(messages, temperature=LLM_TEMPERATURE)
    return json.dumps(obj, ensure_ascii=False, indent=2)
