"""
vision.py: Vision model interaction layer over an OpenAI compatible
API.

Creates the client, checks model availability, and makes the chat
completions call that sends a base64 encoded image and reads the one
JSON object that comes back. The reply schema is the grammar of the
request; the reply is read as exactly one object (see
docpipe/reading.py): nothing is stripped, cut out, closed or salvaged,
and no second, unconstrained request fills in for a reply that could
not be read.

Author: Felix Vossel
"""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

import openai

from docpipe import providers, reading, usage
from docpipe.llm_preflight import further_room, request_extras, served_window
from docpipe.reading import Hole

from .config import (
    VLM_BASE_URL,
    VLM_MODEL,
    VLM_API_KEY,
    VLM_TIMEOUT,
    VLM_TEMPERATURE,
    VLM_MAX_TOKENS,
    MAX_RETRIES,
    RETRY_PENALTIES,
)

log = logging.getLogger(__name__)


def _http_status(exc: Exception) -> int | None:
    """The HTTP status behind an API error, if it carries one."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def _is_client_error(status: int | None) -> bool:
    """True for a status that says THIS request is wrong, not that the server is busy.

    A 4xx (image too large, context exceeded, bad parameter) answers every
    identical retry identically; 429 and 5xx are worth waiting out.
    """
    return status is not None and 400 <= status < 500 and status != 429


# ---------------------------------------------------------------------------
# Client management
# ---------------------------------------------------------------------------

def create_client(base_url: str | None = None, timeout: float | None = None):
    """The client of the vision model, for the provider it is set to."""
    return providers.client(
        "vlm",
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
    reply: tuple,
    model: str = VLM_MODEL,
    max_retries: int = MAX_RETRIES,
    temperature: float = VLM_TEMPERATURE,
    max_tokens: int = VLM_MAX_TOKENS,
    repetition_penalty: float | None = None,
    budget: int | None = None,
) -> dict | Hole:
    """
    Sends an image + prompt to the vision model and reads the one JSON object
    it answers with.

    The wall-clock bound per request is the client timeout set by
    create_client(), not *max_retries*. *reply* is the (name, schema) of the
    object asked for (see `replies`): the grammar of every request, and its
    one required key (the item's `markdown`, `description`) has to be in the
    reply as text.

    A reply that is not that object is asked again with its cause named, the
    answer echoed back. A reply that was cut off at its token limit is not
    asked again as it stands: an image has no halves, so it is asked once more
    from the original prompt with more room and the next repetition penalty (a
    runaway grid is what ends at the limit), without a word about the cut. The
    room is twice *max_tokens* or as much as the served window leaves,
    whichever is smaller (`llm_preflight.further_room`); where it leaves none
    the item is a hole at once and nothing more is sent. If the further
    attempt is cut off too, the item is a hole.

    *budget* is the largest request, in tokens, of the stage this call belongs
    to: the prompt, the largest input and ONE reply of *max_tokens*, which its
    preflight checked the window against. Without it the room is twice.

    Returns:
        The parsed JSON dict, or a Hole that names why there is none:
        "refused" for a request the server rejected itself (a 4xx, which no
        retry would change), "not_served" when the last attempt got no answer,
        "error" for a failure of our own after the reply arrived, or the cause
        the reply was unreadable for (see `reading`).
    """
    # A timeout usually means the model is stuck in a repetition loop, so the
    # penalty is escalated per retry. First attempt: none, to preserve table
    # quality.
    def penalty_after(failed_attempt: int) -> float:
        """How hard to push back on repetition for the next try."""
        return RETRY_PENALTIES[min(failed_attempt, len(RETRY_PENALTIES) - 1)]

    name, schema = reply
    (key,) = schema["required"]
    shape = providers.grammar(name, schema)
    current_penalty = repetition_penalty
    room = max_tokens
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
    # What the last attempt came to: the last attempt decides.
    outcome = Hole("not_served")

    for attempt in range(1, max_retries + 1):
        # Waiting is for a server that needs time. A reply that cannot be read
        # comes back 200 OK within the second, so the next attempt starts at
        # once; only a timeout, a 429 or a 5xx buys the sleep. Page
        # transcription has eight slots, so an idle one is throughput gone.
        server_needs_time = False
        response = None
        try:
            log.debug("  vLLM chat (attempt %d/%d) → %s",
                      attempt, max_retries, image_path.name)

            # Built fresh per attempt: a dict carried across the loop and
            # mutated in place is one the caller cannot reason about.
            # Reasoning models must not spend the token budget on a <think>
            # block; that truncates the JSON answer.
            extra_body: dict = request_extras()
            if current_penalty is not None:
                extra_body["repetition_penalty"] = current_penalty

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format=shape,
                temperature=temperature,
                max_tokens=room,
                extra_body=extra_body or None,
            )
        except (openai.APITimeoutError, providers.ProviderTimeout) as e:
            log.warning("  Attempt %d: request timed out (%s)", attempt, e)
            outcome = Hole("not_served", "timeout")
            messages = list(base_messages)
            current_penalty = penalty_after(attempt)
            if current_penalty is not None:
                log.info("  Setting repetition_penalty=%.1f for next attempt",
                         current_penalty)
            server_needs_time = True
        except (openai.APIError, providers.ProviderError) as e:
            status = _http_status(e)
            if _is_client_error(status):
                # The request is what the server refused, not the moment. Three
                # more of it would be refused the same way.
                log.error("  vLLM rejected %s (HTTP %d): %s — giving up",
                          image_path.name, status, e)
                return Hole("refused", f"HTTP {status}")
            log.error("  vLLM APIError (attempt %d/%d): %s", attempt, max_retries, e)
            outcome = Hole("not_served", f"HTTP {status}" if status else "")
            messages = list(base_messages)
            server_needs_time = True
        except Exception as e:
            log.error("  Error (attempt %d/%d): %s", attempt, max_retries, e)
            outcome = Hole("not_served", type(e).__name__)
            messages = list(base_messages)
            server_needs_time = True

        if response is not None:
            # The reply is in. What goes wrong from here is the reply's or
            # ours, never the server's.
            try:
                usage.reply(response, model)
                choice = reading.first(response)
                found, cause, said = reading.read(choice, key=key, of=str)
                if not cause:
                    return found
            except Exception as e:
                log.exception("  %s: reading the reply failed in the stage "
                              "itself", image_path.name)
                return Hole("error", f"{type(e).__name__}: {e}")

            message = getattr(choice, "message", None)
            raw = getattr(message, "content", None)
            raw = raw if isinstance(raw, str) else ""
            log.warning("  Attempt %d: %s reply (finish: %s)", attempt, cause,
                        getattr(choice, "finish_reason", None))
            # The whole answer, every failed attempt. An excerpt of the last
            # one was not enough: it could not show whether a run breaks off
            # with no penalty in effect or only under a harsh one.
            log.warning("  %s attempt %d/%d (penalty=%s) raw response:\n%s",
                        image_path.name, attempt, max_retries, current_penalty,
                        raw)
            outcome = Hole(cause)

            if cause == "cut_off":
                if room != max_tokens:
                    log.warning("  %s: cut off again at %d tokens, with the "
                                "room it was given: no content",
                                image_path.name, room)
                    return Hole("cut_off", f"{room} tokens")
                more = further_room(max_tokens, reply=max_tokens,
                                    budget=budget, role="vlm")
                if more is None:
                    log.warning("  %s: cut off at %d tokens, and the served "
                                "window of %d tokens leaves no more room: no "
                                "content", image_path.name, max_tokens,
                                served_window("vlm"))
                    return Hole("cut_off", f"{max_tokens} tokens")
                # Not a formatting slip: the answer ran to its limit, a grid
                # losing count is the usual reason. Telling the model its
                # answer was too long re-runs the same loop, so start over
                # from the original prompt with more room and a stronger
                # push against repetition.
                room = more
                current_penalty = penalty_after(attempt)
                log.warning("  Attempt %d: cut off at %d tokens, asking again "
                            "with %d tokens (%d tokens before), "
                            "repetition_penalty=%s", attempt, max_tokens,
                            room, max_tokens, current_penalty)
                messages = list(base_messages)
            elif attempt < max_retries:
                # A reply that is not the object → feed it back, with what was
                # wrong with it, so the model can correct it.
                messages = base_messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": said},
                ]

        if server_needs_time and attempt < max_retries:
            time.sleep(5 * attempt)

    return outcome
