"""
providers: Which API a stage's requests go to.

Every stage asks through one client shape (see `base`). `client(role, ...)`
builds it for the provider the role is set to:

    openai-compatible   a server of one's own (vLLM and the like): the OpenAI
                        client as the stages always built it, nothing between
    openai              the hosted OpenAI API
    anthropic           the Anthropic API
    gemini              the Google Gemini API

A role is what a request is for: `llm` (text: repair, extraction, chat),
`vlm` (tables, figures, scanned pages) and `embedding`. Each has its own
provider setting, so a corpus can be read by a hosted model and embedded by
a local one.

A hosted model is asked for JSON only inside a reply schema, which the API
enforces while it generates (`reply_format`). A server of one's own gets the
schema where it always got one, and everywhere with LLM_SCHEMA=all. The
requests of refinement, of the visuals stage and of page transcription send
theirs as the grammar of the reply on every provider (`grammar`).

Author: Felix Vossel
"""
from __future__ import annotations

import json
import os
from typing import Optional

from . import cassette, governor
from .base import Endpoint, ProviderError, ProviderTimeout

OPENAI_COMPATIBLE = "openai-compatible"
HOSTED = ("openai", "anthropic", "gemini")
PROVIDERS = (OPENAI_COMPATIBLE, *HOSTED)

# The environment names of each role. Spelled out, so the settings list can
# hold them against the code.
ROLES = {
    "llm": {"provider": "LLM_PROVIDER", "base_url": "LLM_BASE_URL",
            "options": "LLM_REQUEST_OPTIONS"},
    "vlm": {"provider": "VLM_PROVIDER", "base_url": "VLM_BASE_URL",
            "options": "VLM_REQUEST_OPTIONS"},
    "embedding": {"provider": "EMBEDDING_PROVIDER",
                  "base_url": "EMBEDDING_BASE_URL", "options": None},
}
# Keys that are placeholders for "the server checks none".
NO_KEY = ("", "EMPTY")


def provider(role: str) -> str:
    """The provider a role is set to."""
    name = (os.environ.get(ROLES[role]["provider"]) or "").strip().lower()
    name = name or OPENAI_COMPATIBLE
    if name not in PROVIDERS:
        raise ValueError(
            f"{ROLES[role]['provider']}={name!r} is no provider; "
            f"one of: {', '.join(PROVIDERS)}")
    return name


def hosted(role: str) -> bool:
    return provider(role) in HOSTED


def enforces_schema(role: str) -> bool:
    """Whether every JSON request of this role goes out with its schema."""
    if hosted(role):
        return True
    return os.environ.get("LLM_SCHEMA", "auto").strip().lower() == "all"


def grammar(name: str, schema: dict) -> dict:
    """The `response_format` that makes *schema* the grammar of a reply.

    For a request that always sends its schema, whatever the server is: the
    server of one's own and the hosted API get the same dict, and the hosted
    adapter makes it strict itself (see `base.enforced`). `reply_format` is
    this, for a request that sends it only where the installation says so.
    """
    return {"type": "json_schema",
            "json_schema": {"name": name, "schema": schema}}


def reply_format(role: str, name: str, schema: dict, otherwise=None):
    """The `response_format` of a request whose reply is *schema*.

    *otherwise* is what the request sent before there were reply schemas for
    it: nothing, or `{"type": "json_object"}`. A server of one's own keeps
    getting that unless LLM_SCHEMA=all.
    """
    if enforces_schema(role):
        return grammar(name, schema)
    return otherwise


def formatted(role: str, name: str, schema: dict, otherwise=None) -> dict:
    """`reply_format` as keyword arguments: empty when nothing is sent."""
    shape = reply_format(role, name, schema, otherwise)
    return {} if shape is None else {"response_format": shape}


def request_options(role: str) -> dict:
    """What an installation adds to every request body of this role."""
    name = ROLES[role]["options"]
    text = (os.environ.get(name) or "").strip() if name else ""
    if not text:
        return {}
    try:
        options = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{name} is not JSON: {exc}") from exc
    if not isinstance(options, dict):
        raise ValueError(f"{name} must be a JSON object")
    return options


def endpoint(role: str, *, base_url: Optional[str] = None,
             api_key: Optional[str] = None,
             timeout: Optional[float] = None) -> Endpoint:
    """Where a hosted role's requests go.

    The address a stage passes is its own default when the installation set
    none, and that default is a local server. So the address counts only when
    the installation set it; otherwise the provider's own applies. A
    placeholder key means "use the key the provider's own variable holds".
    """
    said = (os.environ.get(ROLES[role]["base_url"]) or "").strip()
    return Endpoint(
        role=role, provider=provider(role),
        base_url=(base_url or said) if said else None,
        api_key=None if (api_key or "") in NO_KEY else api_key,
        timeout=timeout,
        thinking_room=int(os.environ.get("LLM_THINKING_ROOM", "8192")),
        options=request_options(role))


def _adapter(name: str):
    if name == "openai":
        from .openai_api import OpenAIChat
        return OpenAIChat
    if name == "anthropic":
        from .anthropic_api import AnthropicChat
        return AnthropicChat
    from .gemini_api import GeminiChat
    return GeminiChat


def client(role: str, **kwargs):
    """The client a stage sends this role's requests through.

    For a server of one's own this is `openai.OpenAI(**kwargs)` and nothing
    else, as each stage built it before. For a hosted provider it is that
    provider's adapter behind the endpoint's gate (see `governor`).

    A run that replays a cassette gets its player and no client at all; a
    run that records one gets its client with the recorder around it (see
    `cassette`). Neither is set in a run that names no cassette.
    """
    if cassette.replaying():
        return cassette.player()
    made = _client(role, kwargs)
    if cassette.recording():
        return cassette.Recorder(made, cassette.recording())
    return made


def _client(role: str, kwargs: dict):
    name = provider(role)
    if name == OPENAI_COMPATIBLE:
        import openai
        return openai.OpenAI(**kwargs)
    where = endpoint(role, base_url=kwargs.get("base_url"),
                     api_key=kwargs.get("api_key"),
                     timeout=kwargs.get("timeout"))
    adapter = _adapter(name)(where)
    return governor.Governed(adapter.client(),
                             governor.gate_for(name, where.base_url))


def replaying() -> bool:
    """Whether this run takes its answers from a cassette: there is then no
    server to ask, to watch or to steer by."""
    return bool(cassette.replaying())


def gate(role: str):
    """The gate of a hosted role's endpoint, or None for one's own server."""
    name = provider(role)
    if name == OPENAI_COMPATIBLE:
        return None
    return governor.gate_for(name, endpoint(role).base_url)


def timed_out(exc: BaseException) -> bool:
    """A request that got no answer within its time, whatever sent it."""
    if isinstance(exc, ProviderTimeout):
        return True
    try:
        import openai
    except ImportError:                     # pragma: no cover - a core package
        return False
    return isinstance(exc, openai.APITimeoutError)


__all__ = ["HOSTED", "OPENAI_COMPATIBLE", "PROVIDERS", "ROLES", "Endpoint",
           "ProviderError", "ProviderTimeout", "client", "endpoint",
           "enforces_schema", "formatted", "gate", "grammar", "hosted",
           "provider", "replaying", "reply_format", "request_options",
           "timed_out"]
