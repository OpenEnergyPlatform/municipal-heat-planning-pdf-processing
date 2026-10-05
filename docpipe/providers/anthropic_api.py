"""
anthropic_api.py: The Anthropic API, through its SDK.

A stage's request becomes one Messages request. The system prompt goes
beside the conversation and is marked for the prompt cache, since thousands
of requests of a run share it. A reply schema goes out as the output format
the API generates in. The request is streamed and read as one message, so a
long answer does not run into an HTTP timeout.

The models that can decline a request for safety reasons are asked with the
API's own fallback: a declined request is answered by the model the API
names for it, and the reply says which model that was. A reply the whole
chain declined comes back as refused, which a stage reads as "no answer".

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from . import base

log = logging.getLogger(__name__)
NAME = "anthropic"
# The models the API can answer for when they decline, and the beta that
# asks for it.
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                   "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
STOPS = {"end_turn": base.STOP, "stop_sequence": base.STOP,
         "max_tokens": base.LENGTH, "refusal": base.REFUSED}
# What the API compiles of a schema: optional properties, and properties
# with alternatives.
BUDGET = (24, 16)
# An error that arrives inside a stream comes after the status line said
# 200. What kind it is, is in its body.
STREAMED = {"overloaded_error": 529, "rate_limit_error": 429,
            "api_error": 500, "timeout_error": 504}


def _sdk():
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            'the anthropic provider needs the Anthropic SDK:\n'
            '  pip install "docpipe[anthropic]"') from exc
    return anthropic


def _content(parts) -> list:
    out = []
    for part in parts:
        if part[0] == "text":
            # The API refuses an empty text block; an empty turn stays a turn.
            out.append({"type": "text", "text": base.NO_REPLY
                        if base.blank(part[1]) else part[1]})
        else:
            out.append({"type": "image",
                        "source": {"type": "base64", "media_type": part[1],
                                   "data": part[2]}})
    return out or [{"type": "text", "text": base.NO_REPLY}]


def _status(exc) -> int:
    """The status of a failed request, also when it failed inside a stream."""
    status = exc.status_code
    if isinstance(status, int) and status >= 400:
        return status
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    kind = error.get("type") if isinstance(error, dict) else None
    return STREAMED.get(kind, 500)


def _answer(message) -> str:
    """The text of the answer: what stands after the last hand-over, when a
    model declined part-way and another one answered."""
    said: list = []
    for block in message.content:
        if block.type == "fallback":
            said = []
        elif block.type == "text":
            said.append(block.text)
    return "".join(said)


class AnthropicChat:
    def __init__(self, endpoint: base.Endpoint):
        self._anthropic = _sdk()
        self.endpoint = endpoint
        kwargs: dict = {"max_retries": 0}
        if endpoint.base_url:
            kwargs["base_url"] = endpoint.base_url
        if endpoint.api_key:
            kwargs["api_key"] = endpoint.api_key
        if endpoint.timeout:
            kwargs["timeout"] = endpoint.timeout
        # Without a key of its own the SDK finds the credentials itself.
        self._sdk_client = self._anthropic.Anthropic(**kwargs)

    def client(self):
        return base.facade(self.create, models=self.models,
                           embeddings=self.embeddings)

    def embeddings(self, **_):
        raise base.ProviderError(
            "the Anthropic API has no embeddings; set EMBEDDING_PROVIDER to "
            "another provider or EMBEDDING_BACKEND=local", status_code=400)

    def models(self):
        cards = [SimpleNamespace(
            id=card.id, max_model_len=getattr(card, "max_input_tokens", None))
            for card in self._sdk_client.models.list()]
        return SimpleNamespace(data=cards)

    def _body(self, model, messages, max_tokens, temperature, schema,
              extra_body) -> dict:
        system, turns = base.split_messages(messages)
        body: dict = {
            "model": model,
            "max_tokens": int(max_tokens or 0) + self.endpoint.thinking_room,
            "messages": [{"role": role, "content": _content(parts)}
                         for role, parts in turns],
        }
        if system:
            body["system"] = [{"type": "text", "text": system,
                               "cache_control": {"type": "ephemeral"}}]
        if temperature is not None:
            body["temperature"] = temperature
        output: dict = {}
        if schema is not None:
            output["format"] = {"type": "json_schema", "schema": schema}
        effort = (extra_body or {}).get("reasoning_effort")
        if effort:
            output["effort"] = effort
        if output:
            body["output_config"] = output
        return base.merge(body, self.endpoint.options)

    def _send(self, body: dict, timeout):
        sdk = self._sdk_client.with_options(timeout=timeout) if timeout \
            else self._sdk_client
        # The fallback is the API's own and not every gateway passes it on.
        if body["model"] in FALLBACK_MODELS and not self.endpoint.base_url:
            stream = sdk.beta.messages.stream(
                **body, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            stream = sdk.messages.stream(**body)
        with stream as events:
            return events.get_final_message()

    def create(self, *, model, messages, max_tokens=None, temperature=None,
               response_format=None, extra_body=None, timeout=None):
        _, schema, decode = base.enforced(response_format,
                                          base.schemas.OPTIONAL, BUDGET)
        if temperature is not None and not base.sends_temperature(NAME,
                                                                  model):
            temperature = None
        body = self._body(model, messages, max_tokens, temperature, schema,
                          extra_body)
        errors = self._anthropic
        try:
            try:
                message = self._send(body, timeout)
            except errors.APIStatusError as exc:
                if not ("temperature" in body
                        and base.refused_temperature(NAME, model, exc)):
                    raise
                log.info("%s takes no temperature; not sending it again",
                         model)
                body.pop("temperature")
                message = self._send(body, timeout)
        except errors.APITimeoutError as exc:
            raise base.ProviderTimeout(str(exc)) from exc
        except errors.APIStatusError as exc:
            headers = getattr(exc.response, "headers", None) or {}
            raise base.ProviderError(
                str(exc), status_code=_status(exc),
                retry_after=base.seconds(headers.get("retry-after"))) from exc
        except errors.APIConnectionError as exc:
            raise base.ProviderError(str(exc)) from exc
        except TypeError as exc:
            # an SDK from before a parameter this request needs
            raise base.ProviderError(
                f"the installed anthropic SDK does not take this request "
                f"({exc}); pip install -U anthropic", status_code=400) from exc
        except Exception as exc:
            # the transport under the SDK, giving up while the stream is read
            if "timeout" in type(exc).__name__.lower():
                raise base.ProviderTimeout(str(exc)) from exc
            raise
        text = _answer(message)
        usage = message.usage
        read = sum(getattr(usage, name, None) or 0 for name in (
            "input_tokens", "cache_creation_input_tokens",
            "cache_read_input_tokens"))
        return base.reply(
            base.decoded(text, decode),
            STOPS.get(message.stop_reason, base.STOP),
            prompt_tokens=read,
            completion_tokens=getattr(usage, "output_tokens", None),
            model=getattr(message, "model", model))
