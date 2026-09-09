"""
llm_preflight.py: Asks the server what it can do, before the first
document.

A stage knows what one request costs it (`config.max_request_tokens()`);
the server knows how much context it was started with. Nothing compared
the two, so a `--max-model-len` set too small surfaced as a slow trickle
of truncated replies hours into a run, with 42 windows silently keeping
their raw text, instead of as a single error within the first second.

Two questions, both answered by `GET {base_url}/models`:
  * does the server serve the model the stage is about to request?
  * is its context at least as large as the worst-case request?
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


class PreflightError(RuntimeError):
    """The server cannot serve what this stage is about to ask of it."""


def _max_model_len(card) -> Optional[int]:
    """vLLM reports max_model_len on the model card; the OpenAI schema does
    not know the field, so it may land in the extras instead."""
    for value in (getattr(card, "max_model_len", None),
                  (getattr(card, "model_extra", None) or {}).get("max_model_len")):
        if isinstance(value, int) and value > 0:
            return value
    return None


def serving_limits(base_url: str, api_key: str, timeout: float = 30.0):
    """(served model ids, max_model_len or None) as the server reports them."""
    try:
        from openai import OpenAI
    except ImportError:                                     # pragma: no cover
        raise ImportError("openai package not installed.\n  pip install openai")

    client = OpenAI(base_url=base_url, api_key=api_key,
                    timeout=timeout, max_retries=1)
    try:
        cards = list(client.models.list().data)
    except Exception as exc:
        raise PreflightError(
            f"no answer from {base_url} — is the server up?\n  {exc}") from exc
    if not cards:
        raise PreflightError(f"{base_url} serves no model")
    lens = [n for n in (_max_model_len(c) for c in cards) if n]
    return [c.id for c in cards], (min(lens) if lens else None)


def assert_serving(base_url: str, api_key: str, model: str,
                   required_tokens: int, *, what: str = "this stage",
                   flag: str = "--max-model-len") -> None:
    """Raise PreflightError unless *base_url* serves *model* with room for
    *required_tokens*. Logs both numbers on success, so they end up in the
    job's output file where the next person can read them."""
    served, max_len = serving_limits(base_url, api_key)

    if model not in served:
        raise PreflightError(
            f"{base_url} does not serve {model!r}.\n"
            f"  it serves: {', '.join(served)}\n"
            f"  set LLM_MODEL/VLM_MODEL to one of those, or start the server "
            f"with --served-model-name {model}")

    if max_len is None:
        log.warning("%s: server does not report its context size; cannot "
                    "check the %d tokens %s needs", base_url, required_tokens, what)
        return

    if max_len < required_tokens:
        raise PreflightError(
            f"{what} needs up to {required_tokens} tokens per request, "
            f"{base_url} was started with {max_len}.\n"
            f"  raise the server's {flag} to at least {required_tokens}, or "
            f"lower the stage's window/max-tokens settings.\n"
            f"  (a request over the limit is rejected mid-run and the "
            f"document keeps its unrefined text)")

    log.info("Preflight ok: %s needs %d tokens, %s offers %d",
             what, required_tokens, model, max_len)
