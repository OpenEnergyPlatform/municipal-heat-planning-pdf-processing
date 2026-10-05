"""
base.py: What every provider speaks towards the stages.

The stages were written against one client: `client.chat.completions.create`
with a model, messages, a token limit and a reply format, answered by an
object with `choices[0].message.content`, a `finish_reason` and a `usage`.
A failure is an exception with an HTTP `status_code` when there was one. That
stays the contract. A provider is whatever turns such a call into a request
of its API and the API's answer back into that object, so no stage knows
which API it is talking to.

Author: Felix Vossel
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional

from . import schema as schemas

# How a provider's own word for "why it stopped" reads to a stage.
STOP = "stop"
LENGTH = "length"
REFUSED = "content_filter"


class ProviderError(Exception):
    """A request the API did not serve.

    `status_code` is the HTTP status, or None when no reply came at all;
    `retry_after` the seconds the API asked to wait, when it said.
    """

    def __init__(self, message: str, status_code: Optional[int] = None,
                 retry_after: Optional[float] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class ProviderTimeout(ProviderError):
    """No answer within the request's time."""


@dataclass
class Endpoint:
    """Where one role's requests go."""
    role: str
    provider: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: Optional[float] = None
    thinking_room: int = 0
    options: dict = field(default_factory=dict)


def reply(text: str, finish: str, *, prompt_tokens: Optional[int] = None,
          completion_tokens: Optional[int] = None, model: Optional[str] = None,
          reasoning: Optional[str] = None) -> SimpleNamespace:
    """One answer, in the shape the stages read."""
    usage = None
    if isinstance(prompt_tokens, int) or isinstance(completion_tokens, int):
        prompt, completion = prompt_tokens or 0, completion_tokens or 0
        usage = SimpleNamespace(prompt_tokens=prompt,
                                completion_tokens=completion,
                                total_tokens=prompt + completion)
    message = SimpleNamespace(role="assistant", content=text,
                              reasoning_content=reasoning)
    return SimpleNamespace(
        choices=[SimpleNamespace(index=0, message=message,
                                 finish_reason=finish)],
        usage=usage, model=model)


def facade(create, models=None, embeddings=None) -> SimpleNamespace:
    """A client with the attribute paths the stages call."""
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    if models is not None:
        client.models = SimpleNamespace(list=models)
    if embeddings is not None:
        client.embeddings = SimpleNamespace(create=embeddings)
    return client


_DATA_URL = re.compile(r"^data:([^;,]+);base64,(.*)$", re.S)


def split_messages(messages) -> tuple:
    """(system text, turns) of an OpenAI-shaped conversation.

    A turn is (role, parts); a part is ("text", text) or ("image", media
    type, base64 data). System messages are joined: the APIs that take the
    system text beside the conversation take one.
    """
    system, turns = [], []
    for message in messages:
        role, content = message.get("role"), message.get("content")
        if role == "system":
            system.append(content if isinstance(content, str)
                          else "".join(p.get("text", "") for p in content
                                       if isinstance(p, dict)))
            continue
        parts = []
        if isinstance(content, str):
            parts.append(("text", content))
        else:
            for part in content or ():
                if part.get("type") == "text":
                    parts.append(("text", part.get("text") or ""))
                elif part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url") or ""
                    found = _DATA_URL.match(url)
                    if not found:
                        raise ProviderError(
                            "an image is sent as a data URL; this one is "
                            f"not: {url[:60]}", status_code=400)
                    parts.append(("image", found.group(1), found.group(2)))
                else:
                    raise ProviderError(
                        f"a message part of type {part.get('type')!r} has "
                        f"no place in this API", status_code=400)
        turns.append((role, parts))
    return "\n\n".join(text for text in system if text), turns


def image_bytes(data: str) -> bytes:
    return base64.b64decode(data)


def wanted_schema(response_format) -> Optional[tuple]:
    """(name, schema) of a reply format that carries a schema, else None.

    A request for "some JSON object" is refused: a hosted model is asked
    inside a schema or for plain text, never for JSON it may wrap in prose.
    """
    if response_format is None:
        return None
    kind = response_format.get("type")
    if kind == "json_schema":
        inner = response_format.get("json_schema") or {}
        return inner.get("name") or "reply", inner.get("schema") or {}
    raise ProviderError(
        f"reply format {kind!r} without a schema: a hosted model is only "
        f"asked for JSON inside a reply schema", status_code=400)


def enforced(response_format, dialect: str = schemas.ALL_REQUIRED,
             budget: Optional[tuple] = None) -> tuple:
    """(name, strict schema, decode) or (None, None, None)."""
    wanted = wanted_schema(response_format)
    if wanted is None:
        return None, None, None
    name, natural = wanted
    try:
        rewritten, decode = schemas.strict(natural, dialect, budget)
    except schemas.SchemaError as exc:
        raise ProviderError(f"reply schema {name}: {exc}",
                            status_code=400) from exc
    return name, rewritten, decode


def decoded(text: str, decode) -> str:
    return text if decode is None else schemas.decoder_text(decode, text)


def merge(into: dict, extra: dict) -> dict:
    """`extra` laid over `into`, table by table."""
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            merge(into[key], value)
        else:
            into[key] = value
    return into


# A sampling parameter some models refuse outright. Which ones is the
# API's to say and changes with every release, so it is learned: the first
# request a model refuses over it is sent again without, and no later one
# carries it.
_NO_TEMPERATURE: set = set()


def sends_temperature(provider: str, model: str) -> bool:
    return (provider, model) not in _NO_TEMPERATURE


def refused_temperature(provider: str, model: str, exc: BaseException) -> bool:
    """True when *exc* is the API refusing this model's temperature.

    For every request that carried one, not only the first to learn it: the
    requests that were under way when the first refusal came are refused
    the same way, and each is sent again without.
    """
    status = getattr(exc, "status_code", None)
    if status != 400 or "temperature" not in str(exc).lower():
        return False
    _NO_TEMPERATURE.add((provider, model))
    return True


def blank(text) -> bool:
    """A turn with nothing in it, which the hosted APIs refuse to take."""
    return not (text or "").strip()


# What stands in for a turn that said nothing: the turn stays a turn.
NO_REPLY = "(no reply)"


def seconds(text) -> Optional[float]:
    """A Retry-After header, or a duration such as "32s", as seconds."""
    if text is None:
        return None
    try:
        return max(0.0, float(str(text).strip().rstrip("s")))
    except ValueError:
        return None


def json_error(raw: bytes) -> str:
    """The message of an API's JSON error body, or the body's first line."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    try:
        body = json.loads(text)
    except ValueError:
        return text.strip().splitlines()[0][:300] if text.strip() else ""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or body)[:300]
