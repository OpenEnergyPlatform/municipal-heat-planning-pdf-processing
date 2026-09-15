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

And one thing every stage agrees with the server about before it asks
anything: `request_extras`, the reasoning settings. They live here because
they are the same for every stage and because getting them wrong fails the
same way a window set too small does: hours in, as replies whose JSON was
truncated by the think block in front of it.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


class PreflightError(RuntimeError):
    """The server cannot serve what this stage is about to ask of it."""


# What every chat request of this pipeline carries. Thinking off, and where
# the server takes it the smallest reasoning effort: what these stages want
# back is a quote and a number, and a think block in front of that truncates
# the JSON around it -- one pilot lost 1,093 of 16,102 harvests that way,
# HTTP 200 every one. Both are env-overridable and read at call time, because
# a setting the server refuses refuses EVERY request of a run, and the fix
# then has to be a variable rather than a release.
def thinking_enabled() -> bool:
    return os.environ.get("LLM_ENABLE_THINKING", "0").strip().lower() in (
        "1", "true", "yes", "on")


def reasoning_effort() -> str:
    """"" when the server is not to be told one at all."""
    effort = os.environ.get("LLM_REASONING_EFFORT", "low").strip()
    return "" if effort.lower() in ("", "off", "none") else effort


def request_extras() -> dict:
    """The `extra_body` of every chat request this pipeline sends."""
    extras: dict = {"chat_template_kwargs":
                    {"enable_thinking": thinking_enabled()}}
    effort = reasoning_effort()
    if effort:
        extras["reasoning_effort"] = effort
    return extras


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
    assert_request_extras(base_url, api_key, model, what=what)


def assert_request_extras(base_url: str, api_key: str, model: str, *,
                          what: str = "this stage") -> None:
    """Raise PreflightError unless the server accepts the reasoning settings.

    One request of one token. A server that refuses `reasoning_effort`
    refuses every request of the run, and without this it says so as a 400
    per document for as long as the job lives. Named here with the variable
    that turns it off, because that is a restart and not a release.
    """
    from openai import OpenAI

    extras = request_extras()
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0,
                    max_retries=0)
    try:
        client.chat.completions.create(
            model=model, max_tokens=1, temperature=0,
            messages=[{"role": "user", "content": "ok"}], extra_body=extras)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if not (isinstance(status, int) and 400 <= status < 500):
            log.warning("%s: could not probe the reasoning settings (%s); "
                        "sending them anyway", base_url, exc)
            return
        raise PreflightError(
            f"{base_url} refuses the reasoning settings {what} sends "
            f"({extras}).\n  {exc}\n"
            f"  set LLM_REASONING_EFFORT=off to stop sending the effort, or "
            f"LLM_ENABLE_THINKING=1 if this model has no thinking switch") \
            from exc
    log.info("Preflight ok: %s accepts %s", model, extras)
