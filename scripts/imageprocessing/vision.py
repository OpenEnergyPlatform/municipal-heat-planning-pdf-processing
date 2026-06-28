"""
vision.py – vLLM (OpenAI-compatible) vision-model interaction layer.

Handles client creation, model availability checks, and the chat-completions
call with a base64 image + JSON response parsing.

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
)

log = logging.getLogger(__name__)


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
    Sends an image + prompt to the vision model via vLLM's chat-completions API.

    The wall-clock bound per request is the client timeout configured by
    create_client(); on a timeout the model is likely stuck in a repetition
    loop, so vLLM's repetition_penalty is escalated for the next attempt. On
    any failure the conversation is reset to the original system+image turn (so
    it cannot grow unboundedly), and for parse failures the raw response is fed
    back so the next attempt can self-correct. max_tokens caps output length.

    Returns:
        Parsed JSON dict, or None if all retries exhausted.
    """
    # Escalating repetition_penalty for timeout retries (vLLM extra_body).
    # First attempt: none (preserve table quality); after a timeout the model
    # is likely stuck repeating, so raise the penalty to break out of it.
    timeout_penalties = [None, 1.1, 1.3]
    extra_body: dict = {}
    if repetition_penalty is not None:
        extra_body["repetition_penalty"] = repetition_penalty

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

            # ── Parse failed → feed response back as context ─────────
            log.warning("  Attempt %d: JSON parsing failed (%s)", attempt, error_detail)

            if attempt < max_retries:
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
            # Escalate repetition_penalty to break a repetition loop next time.
            penalty_idx = min(attempt, len(timeout_penalties) - 1)
            penalty = timeout_penalties[penalty_idx]
            if penalty is not None:
                extra_body["repetition_penalty"] = penalty
                log.info("  Setting repetition_penalty=%.1f for next attempt", penalty)
        except openai.APIError as e:
            log.error("  vLLM APIError (attempt %d/%d): %s", attempt, max_retries, e)
            messages = list(base_messages)
        except Exception as e:
            log.error("  Error (attempt %d/%d): %s", attempt, max_retries, e)
            messages = list(base_messages)

        if attempt < max_retries:
            time.sleep(5 * attempt)

    return None


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _parse_json_response(raw: str) -> tuple[dict | None, str]:
    """
    Extracts a JSON object from model output.

    Handles <think> blocks, ```json fences, and bare JSON objects.

    Returns:
        (parsed_dict, error_detail)
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