"""
vision.py – Vision-model interaction layer (OpenAI-compatible API).

Client creation, model availability checks, and the chat-completions call with
a base64 image + JSON response parsing.

Author: Felix Vossel
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path

import openai

from .config import (
    VLM_BASE_URL,
    VLM_MODEL,
    VLM_API_KEY,
    VLM_TIMEOUT,
    VLM_TEMPERATURE,
    VLM_MAX_TOKENS,
    MAX_RETRIES,
    RUNAWAY_CELL_RUN,
    RETRY_PENALTIES,
)

log = logging.getLogger(__name__)

# A run of empty cells this long is the model losing count in a sparse grid,
# not a table. N cells means N + 1 pipes. This threshold is the detector's and
# sits below the stop sequence's: misjudging here only changes how we retry,
# while the stop sequence would cut content away.
_RUNAWAY = re.compile(r"(\|[ \t]*){%d,}" % (RUNAWAY_CELL_RUN + 1))


def looks_runaway(text: str) -> bool:
    """True if *text* carries the empty-cell run that precedes a truncated answer."""
    return bool(_RUNAWAY.search(text))


# ---------------------------------------------------------------------------
# Client management
# ---------------------------------------------------------------------------

def create_client(base_url: str | None = None, timeout: float | None = None) -> openai.OpenAI:
    """Creates an OpenAI client pointed at the vLLM server."""
    return openai.OpenAI(
        base_url=base_url or VLM_BASE_URL,
        api_key=VLM_API_KEY,
        timeout=timeout or VLM_TIMEOUT,
        max_retries=0,  # we run our own retry loop
    )


def check_model_available(
    client: openai.OpenAI,
    model: str = VLM_MODEL,
) -> bool:
    """Verifies that the vLLM endpoint is reachable and serves *model*."""
    try:
        available = [m.id for m in client.models.list().data]
        if model in available:
            log.info("vLLM: model '%s' available.", model)
            return True
        log.warning(
            "Model '%s' not found at the vLLM endpoint. Available: %s "
            "(set VLM_MODEL / --model to the server's --served-model-name)",
            model, available,
        )
        return False
    except Exception as e:
        log.error("vLLM endpoint not reachable: %s", e)
        return False


def _image_data_url(image_path: Path) -> str:
    """Reads an image file and returns it as a base64 data URL for the API."""
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Vision chat call
# ---------------------------------------------------------------------------

def call_vision(
    client: openai.OpenAI,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    *,
    model: str = VLM_MODEL,
    max_retries: int = MAX_RETRIES,
    temperature: float = VLM_TEMPERATURE,
    max_tokens: int = VLM_MAX_TOKENS,
    repetition_penalty: float | None = None,
) -> dict | None:
    """
    Sends an image + prompt to the vision model and parses the JSON response.

    The wall-clock bound per request is the client timeout set by
    create_client(), not *max_retries*.

    Returns:
        Parsed JSON dict, or None if all retries were exhausted.
    """
    # A timeout usually means the model is stuck in a repetition loop, so the
    # penalty is escalated per retry. First attempt: none, to preserve table
    # quality.
    def penalty_after(failed_attempt: int) -> float:
        """How hard to push back on repetition for the next try."""
        return RETRY_PENALTIES[min(failed_attempt, len(RETRY_PENALTIES) - 1)]

    current_penalty = repetition_penalty
    image_url = _image_data_url(image_path)
    base_messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]
    messages = list(base_messages)

    for attempt in range(1, max_retries + 1):
        try:
            log.debug("  vLLM chat (attempt %d/%d) → %s",
                      attempt, max_retries, image_path.name)

            # Built fresh per attempt: a dict carried across the loop and
            # mutated in place is one the caller cannot reason about.
            # Reasoning models must not spend the token budget on a <think>
            # block; that truncates the JSON answer.
            extra_body: dict = {"chat_template_kwargs": {"enable_thinking": False}}
            if current_penalty is not None:
                extra_body["repetition_penalty"] = current_penalty

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=extra_body or None,
            )

            raw = response.choices[0].message.content or ""
            parsed, error_detail = _parse_json_response(raw)

            if parsed is not None:
                return parsed

            log.warning("  Attempt %d: JSON parsing failed (%s)", attempt, error_detail)
            # The whole answer, every failed attempt. An excerpt of the last one
            # was not enough: it could not show whether a run breaks off with no
            # penalty in effect or only under a harsh one.
            log.warning("  %s attempt %d/%d (penalty=%s) raw response:\n%s",
                        image_path.name, attempt, max_retries, current_penalty, raw)

            if attempt < max_retries:
                if looks_runaway(raw):
                    # Not a formatting slip: the model lost count in a sparse
                    # grid and the stop sequence cut it off. Asking it to "fix
                    # the JSON" re-runs the same loop, so escalate the penalty
                    # and start over from the original prompt instead.
                    current_penalty = penalty_after(attempt)
                    log.warning("  Attempt %d: runaway empty cells – retrying with "
                                "repetition_penalty=%.1f", attempt, current_penalty)
                    messages = list(base_messages)
                else:
                    # A formatting slip → feed it back so the model can correct it.
                    messages = base_messages + [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response could not be parsed as JSON. "
                                "Error: %s\n\n"
                                "Please try again. Respond with ONLY a valid JSON "
                                "object — no markdown fences, no commentary, no "
                                "text before or after the JSON."
                            ) % error_detail,
                        },
                    ]

        except openai.APITimeoutError as e:
            log.warning("  Attempt %d: request timed out (%s)", attempt, e)
            messages = list(base_messages)
            current_penalty = penalty_after(attempt)
            if current_penalty is not None:
                log.info("  Setting repetition_penalty=%.1f for next attempt",
                         current_penalty)
        except openai.APIError as e:
            log.error("  vLLM APIError (attempt %d/%d): %s", attempt, max_retries, e)
            messages = list(base_messages)
        except Exception as e:
            log.error("  Error (attempt %d/%d): %s", attempt, max_retries, e)
            messages = list(base_messages)

        if attempt < max_retries:
            time.sleep(5 * attempt)

    return None


def call_vision_plain(
    client: openai.OpenAI,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    *,
    model: str = VLM_MODEL,
    temperature: float = VLM_TEMPERATURE,
    max_tokens: int = VLM_MAX_TOKENS,
    key: str = "markdown",
) -> str | None:
    """
    One unconstrained call: the answer as plain text, no JSON envelope.

    The last resort after call_vision has given up. Of 112 parse failures in the
    August 2026 run, 111 read "No JSON object found in response" on a 200 OK
    that came back within the same second — the model answers, it just will not
    wear the envelope. Discarding that answer loses information the model
    already produced.

    Returns the response text (``<think>`` stripped), or None if the call fails
    or comes back empty.
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url",
                         "image_url": {"url": _image_data_url(image_path)}},
                    ],
                },
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    except Exception as e:
        log.warning("  Plain-text rescue failed for %s: %s", image_path.name, e)
        return None

    raw = response.choices[0].message.content or ""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:markdown|json)?\s*|\s*```$", "", text).strip()

    # Asked for plain text, the model often still answers in JSON — and by then
    # it is complete rather than truncated, so it parses. Storing the envelope
    # raw would put `{"markdown": "…"}` into the index as if it were the table.
    parsed, _ = _parse_json_response(text)
    if isinstance(parsed, dict):
        inner = parsed.get(key)
        return inner.strip() or None if isinstance(inner, str) else None

    # An envelope cut off mid-string — by the stop sequence or the token limit —
    # has no closing brace, so json.loads has nothing to work with. The content
    # up to the cut is still good; take it rather than store the envelope raw.
    if text.lstrip().startswith("{"):
        return _salvage_truncated(text, key)

    return text or None


def _salvage_truncated(text: str, key: str) -> Optional[str]:
    """The value of *key* out of a JSON object that was never finished."""
    m = re.search(r'"%s"\s*:\s*"' % re.escape(key), text)
    if not m:
        return None

    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
    out: list[str] = []
    raw = text[m.end():]
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            out.append(escapes.get(raw[i + 1], raw[i + 1]))
            i += 2
            continue
        if ch == '"':          # the string did close after all
            break
        out.append(ch)
        i += 1
    return "".join(out).strip() or None


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _parse_json_response(raw: str) -> tuple[dict | None, str]:
    """
    Extracts a JSON object from model output, tolerating <think> blocks and
    ```json fences.

    Returns:
        (parsed_dict, error_detail); parsed_dict is None iff extraction failed.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    if not cleaned:
        return None, "Empty response after stripping <think> blocks"

    # 1) Direct parse
    try:
        return json.loads(cleaned), ""
    except json.JSONDecodeError as e:
        last_error = str(e)

    # 2) Fenced code block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1)), ""
        except json.JSONDecodeError as e:
            last_error = "Found ```json block but: %s" % e

    # 3) First { … }
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0)), ""
        except json.JSONDecodeError as e:
            last_error = "Found JSON-like block but: %s" % e
    else:
        last_error = "No JSON object found in response"

    return None, last_error