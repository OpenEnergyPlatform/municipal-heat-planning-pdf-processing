"""
openai_api.py: The hosted OpenAI API.

The same client the stages always used, minus what only a server of one's
own takes: the chat-template switch and the repetition penalty are left out,
the token limit goes by its current name and includes the room the model
may think in, and a reply schema is sent as a strict one.

Author: Felix Vossel
"""
from __future__ import annotations

import logging

from . import base

log = logging.getLogger(__name__)
NAME = "openai"


class OpenAIChat:
    def __init__(self, endpoint: base.Endpoint):
        import openai
        self.endpoint = endpoint
        kwargs: dict = {"max_retries": 0}
        if endpoint.base_url:
            kwargs["base_url"] = endpoint.base_url
        if endpoint.api_key:
            kwargs["api_key"] = endpoint.api_key
        if endpoint.timeout:
            kwargs["timeout"] = endpoint.timeout
        self._sdk = openai.OpenAI(**kwargs)

    def client(self):
        return base.facade(self.create, models=self._sdk.models.list,
                           embeddings=self._sdk.embeddings.create)

    def create(self, *, model, messages, max_tokens=None, temperature=None,
               response_format=None, extra_body=None, timeout=None):
        name, schema, decode = base.enforced(response_format)
        extras: dict = {}
        if max_tokens is not None:
            extras["max_completion_tokens"] = (int(max_tokens)
                                               + self.endpoint.thinking_room)
        effort = (extra_body or {}).get("reasoning_effort")
        if effort:
            extras["reasoning_effort"] = effort
        base.merge(extras, self.endpoint.options)
        body: dict = {"model": model, "messages": messages}
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True,
                                "schema": schema}}
        if timeout:
            body["timeout"] = timeout
        if extras:
            body["extra_body"] = extras
        with_temperature = (temperature is not None
                            and base.sends_temperature(NAME, model))
        try:
            response = self._sdk.chat.completions.create(
                **body, **({"temperature": temperature}
                           if with_temperature else {}))
        except Exception as exc:
            if not (with_temperature
                    and base.refused_temperature(NAME, model, exc)):
                raise
            log.info("%s takes no temperature; not sending it again", model)
            response = self._sdk.chat.completions.create(**body)
        choice = response.choices[0]
        text = getattr(choice.message, "content", None) or ""
        finish = choice.finish_reason
        if getattr(choice.message, "refusal", None):
            text, finish = "", base.REFUSED
        usage = getattr(response, "usage", None)
        details = getattr(usage, "prompt_tokens_details", None)
        return base.reply(
            base.decoded(text, decode), finish,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            cached_tokens=getattr(details, "cached_tokens", None),
            model=getattr(response, "model", model))
