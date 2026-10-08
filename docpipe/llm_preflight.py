"""
llm_preflight.py: Asks the server what it can do, before the first
document.

A stage knows what one request costs it (`config.max_request_tokens()`);
the server knows how much context it was started with. Nothing compared
the two, so a `--max-model-len` set too small surfaced as a slow trickle
of truncated replies hours into a run, with 42 windows silently keeping
their raw text, instead of as a single error within the first second.

Two questions, both answered by the provider's list of models:
  * does it serve the model the stage is about to request?
  * is its context at least as large as the worst-case request?

A hosted API is asked a third: does the model answer inside a reply schema?
That is the only way a hosted model is asked for JSON (see `providers`), so
a model that cannot is refused here and not after the first document.

A stage that sends its reply schema as the grammar of every request
(refinement, the visuals stage, page transcription) has each of its schemas
put to the server once, as that stage will send it (`assert_reply_schemas`): a
server that refuses one refuses every request of the run.

What the preflight learns about the window stays with the run: a unit whose
reply was cut off and that cannot be split is asked once more with as much
room as the window leaves (`further_room`), and the stage that asks has the
number from here and not from a second request to the server.

And one thing every stage agrees with the server about before it asks
anything: `request_extras`, the reasoning settings. They live here because
they are the same for every stage and because getting them wrong fails the
same way a window set too small does: hours in, as replies whose JSON was
truncated by the think block in front of it.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from docpipe import providers
from docpipe.providers.governor import status_of

log = logging.getLogger(__name__)


class PreflightError(RuntimeError):
    """The server cannot serve what this stage is about to ask of it."""


# The flag a self-hosted server is started with to set its context size.
CONTEXT_FLAG = "--max-model-len"

# The window each role's server reported at its preflight, in tokens, None
# where it reported none. Written by `assert_serving` and by nothing else;
# read where a unit whose reply was cut off is given more room. A stage that
# was never preflighted has no entry, which reads as not known.
_WINDOWS: dict = {}


def _keep_window(role: str, window: Optional[int]) -> Optional[int]:
    _WINDOWS[role] = window
    return window


def served_window(role: str = "llm") -> Optional[int]:
    """The window, in tokens, that the server of *role* reported at this run's
    preflight. None where it reported none (a hosted model whose window is its
    own) and where nothing was asked (a caller that ran no preflight)."""
    return _WINDOWS.get(role)


def further_room(asked: int, *, reply: int, budget: Optional[int],
                 role: str = "llm") -> Optional[int]:
    """The token limit of the one further attempt of a unit whose reply was cut
    off at *asked* tokens and that cannot be split: twice what it asked, or as
    much as the served window leaves, whichever is smaller. None when the
    window leaves no more room than the request had; nothing is sent then.

    *budget* is the stage's largest request in tokens (the prompt, the largest
    input and ONE largest reply, *reply* tokens), which the preflight checked
    the window against. What the window holds beyond it is free for every
    request of the run, so a request may have the reply the budget counts plus
    that slack, and never more than twice what it asked:
    min(2 * asked, reply + window - budget). A request that asked for less than
    *reply* is doubled out of the reply alone.

    Where the window is not known, or the caller has no budget, the room is
    twice."""
    window = served_window(role)
    if window is None or budget is None:
        return 2 * asked
    more = min(2 * asked, reply + window - budget)
    return more if more > asked else None


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


def serving_limits(base_url: str, api_key: str, timeout: float = 30.0,
                   role: str = "llm"):
    """(served model ids, max_model_len or None) as the server reports them."""
    try:
        client = providers.client(role, base_url=base_url, api_key=api_key,
                                  timeout=timeout, max_retries=1)
    except ImportError as exc:                              # pragma: no cover
        if providers.hosted(role):
            raise
        raise ImportError(
            "openai package not installed.\n  pip install openai") from exc
    try:
        cards = list(client.models.list().data)
    except Exception as exc:
        raise PreflightError(
            f"no answer from {base_url} — is the server up?\n  {exc}") from exc
    if not cards:
        raise PreflightError(f"{base_url} serves no model")
    lens = [n for n in (_max_model_len(c) for c in cards) if n]
    return [c.id for c in cards], (min(lens) if lens else None)


def _hosted_serving(base_url: str, api_key: str, model: str,
                    required_tokens: int, *, what: str,
                    role: str) -> Optional[int]:
    """`assert_serving` for a hosted API."""
    name = providers.provider(role)
    client = providers.client(role, base_url=base_url, api_key=api_key,
                              timeout=30.0, max_retries=1)
    try:
        cards = {card.id: _max_model_len(card)
                 for card in client.models.list().data}
    except Exception as exc:
        raise PreflightError(
            f"no answer from the {name} API — is the key set?\n  {exc}") \
            from exc
    if model not in cards:
        import difflib
        near = difflib.get_close_matches(model, list(cards), n=5, cutoff=0.4)
        raise PreflightError(
            f"the {name} API does not serve {model!r}.\n"
            f"  nearest of the {len(cards)} it serves: "
            f"{', '.join(near) or 'none'}")
    window = cards[model]
    if window is not None and window < required_tokens:
        raise PreflightError(
            f"{what} needs up to {required_tokens} tokens per request, "
            f"{model} takes {window}.\n"
            f"  lower the stage's window/max-tokens settings, or set a "
            f"model with a larger context")
    if window is None:
        log.warning("%s: the API does not report the context size of %s; "
                    "cannot check the %d tokens %s needs", name, model,
                    required_tokens, what)
    else:
        log.info("Preflight ok: %s needs %d tokens, %s offers %d",
                 what, required_tokens, model, window)
    assert_reply_schema(base_url, api_key, model, what=what, role=role)
    from docpipe.providers import cassette
    cassette.note_limits(model, window)
    return window


PROBE_SCHEMA = {"type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"]}


def assert_reply_schema(base_url: str, api_key: str, model: str, *,
                        what: str = "this stage",
                        role: str = "llm") -> Optional[str]:
    """Raise PreflightError unless *model* answers inside a reply schema.

    One small request, with the reasoning settings every request carries. A
    model that takes no schema, or refuses a setting, refuses every request
    of the run; here it says so once, with the variable that changes it.

    None when it did. When the API could not be asked there is no verdict:
    why, as a sentence, and the run asks anyway.
    """
    name = providers.provider(role)
    client = providers.client(role, base_url=base_url, api_key=api_key,
                              timeout=60.0, max_retries=0)
    try:
        answer = client.chat.completions.create(
            model=model, max_tokens=32, temperature=0,
            messages=[{"role": "user",
                       "content": 'Answer with the JSON object {"ok": true}.'}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "probe",
                                             "schema": PROBE_SCHEMA}},
            extra_body=request_extras())
    except Exception as exc:
        status = status_of(exc)
        if not (isinstance(status, int) and 400 <= status < 500
                and status != 429):
            log.warning("%s: could not probe the reply schema (%s); asking "
                        "anyway", name, exc)
            return f"the probe request was not answered: {exc}"
        raise PreflightError(
            f"the {name} API refuses what {what} sends to {model}.\n"
            f"  {exc}\n"
            f"  a hosted model is asked inside a reply schema, so the model "
            f"has to take one. If it is the effort it refuses, set "
            f"LLM_REASONING_EFFORT=off; what else the model needs goes into "
            f"{providers.ROLES[role]['options']}") from exc
    text = answer.choices[0].message.content or ""
    try:
        inside = isinstance(json.loads(text).get("ok"), bool)
    except (ValueError, AttributeError):
        inside = False
    if not inside:
        raise PreflightError(
            f"{model} did not answer inside the reply schema: {text[:120]!r}"
            f" (finish: {answer.choices[0].finish_reason})")
    log.info("Preflight ok: %s answers inside a reply schema", model)
    return None


def assert_reply_schemas(base_url: str, api_key: str, model: str,
                         shapes: dict, *, what: str = "this stage",
                         role: str = "llm") -> Optional[str]:
    """Raise PreflightError unless the server takes every reply schema in
    *shapes* ({name: schema}) as the grammar of a request.

    A stage that sends its schema with every request has no other way to ask
    for JSON, so a server that refuses the schema refuses every request of
    the run. One request of 32 tokens per shape, with the stage's own schema
    and the reasoning settings every request carries; that the capped reply
    is cut short is no matter, it is not read. Only a 4xx that is not a 429
    is a refusal: a server that is busy or down gives no verdict, and the run
    asks anyway.

    None when every shape was taken; else why one could not be asked.
    """
    client = providers.client(role, base_url=base_url, api_key=api_key,
                              timeout=60.0, max_retries=0)
    unasked = []
    for name, schema in shapes.items():
        try:
            client.chat.completions.create(
                model=model, max_tokens=32, temperature=0,
                messages=[{"role": "user",
                           "content": "Answer with a JSON object."}],
                response_format=providers.grammar(name, schema),
                extra_body=request_extras())
        except Exception as exc:
            status = status_of(exc)
            if not (isinstance(status, int) and 400 <= status < 500
                    and status != 429):
                log.warning("%s: could not probe the reply schema %s (%s); "
                            "asking anyway", base_url, name, exc)
                unasked.append(f"{name}: {exc}")
                continue
            raise PreflightError(
                f"{base_url} refuses the reply schema {name!r} that {what} "
                f"sends to {model} (HTTP {status}).\n  {exc}\n"
                f"  the server has to take a JSON schema as the "
                f"response_format of a request: {what} asks for JSON in no "
                f"other way, so every one of its requests would be refused") \
                from exc
    if unasked:
        return "the probe was not answered: " + "; ".join(unasked)
    log.info("Preflight ok: %s takes the %d reply schema(s) %s sends: %s",
             model, len(shapes), what, ", ".join(shapes))
    return None


def assert_serving(base_url: str, api_key: str, model: str,
                   required_tokens: int, *, what: str = "this stage",
                   flag: str = CONTEXT_FLAG,
                   role: str = "llm",
                   shapes: Optional[dict] = None) -> Optional[int]:
    """Raise PreflightError unless *base_url* serves *model* with room for
    *required_tokens*. Logs both numbers on success, so they end up in the
    job's output file where the next person can read them. Returns the
    server's window, or None when it does not report one; such a server is
    asked the request fields all the same. The window is kept for the run
    (`served_window`).

    *shapes* ({name: schema}) are the reply schemas the stage is about to send
    as the grammar of its requests: the server is asked each one before the
    first document (`assert_reply_schemas`)."""
    if providers.replaying():
        # No server: the window is the one the recorded run was planned
        # for, and the run is planned for it again.
        from docpipe.providers import cassette
        return _keep_window(role, cassette.player().window(model))
    if providers.hosted(role):
        window = _hosted_serving(base_url, api_key, model, required_tokens,
                                 what=what, role=role)
        if shapes:
            assert_reply_schemas(base_url, api_key, model, shapes, what=what,
                                 role=role)
        return _keep_window(role, window)
    served, max_len = serving_limits(base_url, api_key, role=role)

    if model not in served:
        raise PreflightError(
            f"{base_url} does not serve {model!r}.\n"
            f"  it serves: {', '.join(served)}\n"
            f"  set LLM_MODEL/VLM_MODEL to one of those, or start the server "
            f"with --served-model-name {model}")

    if max_len is None:
        log.warning("%s: server does not report its context size; cannot "
                    "check the %d tokens %s needs", base_url, required_tokens, what)
    elif max_len < required_tokens:
        raise PreflightError(
            f"{what} needs up to {required_tokens} tokens per request, "
            f"{base_url} was started with {max_len}.\n"
            f"  raise the server's {flag} to at least {required_tokens}, or "
            f"lower the stage's window/max-tokens settings.\n"
            f"  (a request over the limit is rejected mid-run and the "
            f"document keeps its unrefined text)")
    else:
        log.info("Preflight ok: %s needs %d tokens, %s offers %d",
                 what, required_tokens, model, max_len)
    # Every server is asked the request fields, one that reports no context
    # size too: it is the likeliest to refuse them (a gateway, a local
    # runner).
    assert_request_extras(base_url, api_key, model, what=what, role=role)
    if shapes:
        assert_reply_schemas(base_url, api_key, model, shapes, what=what,
                             role=role)
    from docpipe.providers import cassette
    cassette.note_limits(model, max_len)
    return _keep_window(role, max_len)


def assert_request_extras(base_url: str, api_key: str, model: str, *,
                          what: str = "this stage",
                          role: str = "llm") -> Optional[str]:
    """Raise PreflightError unless the server accepts the reasoning settings.

    One request of one token. A server that refuses `reasoning_effort`
    refuses every request of the run, and without this it says so as a 400
    per document for as long as the job lives. Named here with the variable
    that turns it off, because that is a restart and not a release.

    None when the server took them. A server that could not be asked (down,
    busy, a 5xx) gives no verdict: why, as a sentence, and the settings go out
    anyway. The two are told apart so that a caller who reports "accepted"
    knows it was.
    """
    extras = request_extras()
    client = providers.client(role, base_url=base_url, api_key=api_key,
                              timeout=60.0, max_retries=0)
    try:
        client.chat.completions.create(
            model=model, max_tokens=1, temperature=0,
            messages=[{"role": "user", "content": "ok"}], extra_body=extras)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        # 429 says not now, which is no answer about the fields.
        if not (isinstance(status, int) and 400 <= status < 500
                and status != 429):
            log.warning("%s: could not probe the reasoning settings (%s); "
                        "sending them anyway", base_url, exc)
            return f"the one-token request was not answered: {exc}"
        raise PreflightError(
            f"{base_url} refuses the reasoning settings {what} sends "
            f"({extras}).\n  {exc}\n"
            f"  set LLM_REASONING_EFFORT=off to stop sending the effort, or "
            f"LLM_ENABLE_THINKING=1 if this model has no thinking switch") \
            from exc
    log.info("Preflight ok: %s accepts %s", model, extras)
    return None


def assert_request_accepted(base_url: str, api_key: str, model: str, *,
                            what: str = "this stage",
                            role: str = "llm") -> Optional[str]:
    """The probe of the request fields that `assert_serving` sends for this
    role's kind of server: the reply schema of a hosted API, the reasoning
    settings of one's own. For the doctor, which asks it on its own.

    Raises PreflightError on a refusal; returns None when the server
    accepted, and a sentence when it could not be asked.
    """
    if providers.hosted(role):
        return assert_reply_schema(base_url, api_key, model, what=what,
                                   role=role)
    return assert_request_extras(base_url, api_key, model, what=what,
                                 role=role)
