"""
vision.py – Ollama vision-model interaction layer.

Handles client creation, model availability checks, and the chat call
with image input + JSON response parsing.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

import httpx
import ollama

from .config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_OPTIONS,
    OLLAMA_TIMEOUT,
    MAX_RETRIES,
)

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)


def create_client(host: str | None = None, timeout: float | None = None) -> ollama.Client:
    """Creates an Ollama client with an httpx timeout."""
    t = timeout or OLLAMA_TIMEOUT
    return ollama.Client(
        host=host or OLLAMA_HOST,
        timeout=httpx.Timeout(t, connect=30.0),
    )


def check_model_available(
    client: ollama.Client,
    model: str = OLLAMA_MODEL,
) -> bool:
    """Verifies that Ollama is reachable and the model is pulled."""
    try:
        model_list = client.list()
        available = [m.model for m in model_list.models]
        model_base = model.split(":")[0]

        for name in available:
            if name == model or name.startswith(model_base):
                log.info("Ollama: model '%s' available.", model)
                return True

        log.warning("Model '%s' not found. Available: %s", model, available)
        return False
    except Exception as e:
        log.error("Ollama not reachable: %s", e)
        return False


def call_vision(
    client: ollama.Client,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    *,
    model: str = OLLAMA_MODEL,
    max_retries: int = MAX_RETRIES,
    timeout: float | None = None,
    options: dict | None = None,
) -> dict | None:
    """
    Sends an image + prompt to the vision model via ollama.chat().

    On any failure (timeout, bad JSON, server error), the model's raw
    response is fed back as conversation context so the next attempt
    can correct itself.  num_predict in options caps output length,
    preventing infinite generation.

    Returns:
        Parsed JSON dict, or None if all retries exhausted.
    """
    opts = dict(options or OLLAMA_OPTIONS)
    wall_timeout = timeout or OLLAMA_TIMEOUT

    # Escalating repeat_penalty for timeout retries.
    # First attempt: no penalty (preserve table quality).
    # After timeout: model is likely stuck in repetition loop,
    # so we increase the penalty to break out of it.
    timeout_penalties = [None, 1.1, 1.3]

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": user_prompt,
            "images": [str(image_path)],
        },
    ]

    for attempt in range(1, max_retries + 1):
        try:
            log.debug("  Ollama (attempt %d/%d, timeout %ds) → %s",
                       attempt, max_retries, wall_timeout, image_path.name)

            future = _executor.submit(
                client.chat,
                model=model,
                messages=messages,
                options=opts,
            )
            try:
                response = future.result(timeout=wall_timeout)
            except FuturesTimeout:
                log.warning("  Attempt %d: timed out after %ds", attempt, wall_timeout)
                messages = messages[:2]

                # Escalate repeat_penalty for next attempt
                penalty_idx = min(attempt, len(timeout_penalties) - 1)
                penalty = timeout_penalties[penalty_idx]
                if penalty is not None:
                    opts["repeat_penalty"] = penalty
                    log.info("  Setting repeat_penalty=%.1f for next attempt", penalty)

                if attempt < max_retries:
                    time.sleep(5 * attempt)
                continue

            raw = response.message.content or ""
            parsed, error_detail = _parse_json_response(raw)

            if parsed is not None:
                return parsed

            # ── Failed → feed response back as context ───────────────
            log.warning("  Attempt %d: JSON parsing failed (%s)", attempt, error_detail)

            if attempt < max_retries:
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous response could not be parsed as JSON. "
                        "Error: %s\n\n"
                        "Please try again. Respond with ONLY a valid JSON "
                        "object — no markdown fences, no commentary, no "
                        "text before or after the JSON."
                    ) % error_detail,
                })

        except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            log.warning("  Attempt %d: HTTP timeout (%s)", attempt, e)
            messages = messages[:2]
        except ollama.ResponseError as e:
            log.error("  Ollama ResponseError (attempt %d/%d): %s", attempt, max_retries, e)
            messages = messages[:2]
        except Exception as e:
            log.error("  Error (attempt %d/%d): %s", attempt, max_retries, e)
            messages = messages[:2]

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