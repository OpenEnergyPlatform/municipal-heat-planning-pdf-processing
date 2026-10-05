"""
gemini_api.py: The Google Gemini API, over its REST interface.

A stage's request becomes one `generateContent` call: the system prompt as
the system instruction, the conversation as contents, an image as inline
data, a reply schema as the JSON schema the API generates in. Text
embeddings go through `batchEmbedContents`.

Author: Felix Vossel
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Optional

from . import base

NAME = "gemini"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
STOPS = {"STOP": base.STOP, "MAX_TOKENS": base.LENGTH}
ROLES = {"assistant": "model", "user": "user"}
EMBED_BATCH = 100
# For a request nobody gave a time: an answer that never comes must not hold
# a thread for good.
TIMEOUT = 600.0


def _parts(parts) -> list:
    out = []
    for part in parts:
        if part[0] == "text":
            # The API refuses an empty text part; an empty turn stays a turn.
            out.append({"text": base.NO_REPLY if base.blank(part[1])
                        else part[1]})
        else:
            out.append({"inlineData": {"mimeType": part[1], "data": part[2]}})
    return out or [{"text": base.NO_REPLY}]


def _retry_delay(body: bytes) -> Optional[float]:
    """The wait a refusal names in its details ("retryDelay": "32s")."""
    try:
        details = json.loads(body).get("error", {}).get("details") or ()
    except (ValueError, AttributeError):
        return None
    for detail in details:
        if isinstance(detail, dict) and detail.get("retryDelay"):
            return base.seconds(detail["retryDelay"])
    return None


class GeminiChat:
    def __init__(self, endpoint: base.Endpoint, *, opener=None):
        self.endpoint = endpoint
        self.base_url = (endpoint.base_url or BASE_URL).rstrip("/")
        self._open = opener or urllib.request.urlopen

    def client(self):
        return base.facade(self.create, models=self.models,
                           embeddings=self.embeddings)

    def _key(self) -> str:
        key = (self.endpoint.api_key or os.environ.get("GEMINI_API_KEY")
               or os.environ.get("GOOGLE_API_KEY"))
        if not key:
            raise base.ProviderError(
                "no API key for Gemini: set the role's API key or "
                "GEMINI_API_KEY", status_code=401)
        return key

    def _call(self, method: str, path: str, body: Optional[dict] = None,
              timeout: Optional[float] = None) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/{path}", method=method,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"x-goog-api-key": self._key(),
                     "Content-Type": "application/json"})
        try:
            with self._open(request, timeout=timeout or self.endpoint.timeout
                            or TIMEOUT) as got:
                return json.loads(got.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            wait = base.seconds((exc.headers or {}).get("Retry-After"))
            raise base.ProviderError(
                f"HTTP {exc.code}: {base.json_error(raw)}",
                status_code=exc.code,
                retry_after=wait if wait is not None
                else _retry_delay(raw)) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise base.ProviderTimeout(f"no answer in time: {exc}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise base.ProviderTimeout(
                    f"no answer in time: {exc.reason}") from exc
            raise base.ProviderError(f"no connection: {exc.reason}") from exc
        except (http.client.HTTPException, OSError, ValueError) as exc:
            # a connection that broke while the answer was read, or an answer
            # that is no JSON: not served, and no status to say why
            raise base.ProviderError(
                f"no readable answer: {type(exc).__name__}: {exc}") from exc

    def models(self):
        listed = self._call("GET", "models?pageSize=1000").get("models") or ()
        return SimpleNamespace(data=[SimpleNamespace(
            id=str(card.get("name", "")).split("/", 1)[-1],
            max_model_len=card.get("inputTokenLimit")) for card in listed])

    def create(self, *, model, messages, max_tokens=None, temperature=None,
               response_format=None, extra_body=None, timeout=None):
        _, schema, decode = base.enforced(response_format,
                                          base.schemas.OPTIONAL)
        system, turns = base.split_messages(messages)
        generation: dict = {}
        if max_tokens is not None:
            generation["maxOutputTokens"] = (int(max_tokens)
                                             + self.endpoint.thinking_room)
        if temperature is not None:
            generation["temperature"] = temperature
        if schema is not None:
            generation["responseMimeType"] = "application/json"
            generation["responseJsonSchema"] = schema
        body: dict = {
            "contents": [{"role": ROLES.get(role, "user"),
                          "parts": _parts(parts)} for role, parts in turns],
            "generationConfig": generation,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        base.merge(body, self.endpoint.options)
        got = self._call("POST", f"models/{model}:generateContent", body,
                         timeout)
        candidates = got.get("candidates") or ()
        text, finish = "", base.REFUSED    # no candidate: the prompt was blocked
        if candidates:
            first = candidates[0]
            text = "".join(
                part.get("text", "")
                for part in (first.get("content") or {}).get("parts") or ()
                if not part.get("thought"))
            finish = STOPS.get(first.get("finishReason"), base.REFUSED)
        usage = got.get("usageMetadata") or {}
        return base.reply(
            base.decoded(text, decode), finish,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=((usage.get("candidatesTokenCount") or 0)
                               + (usage.get("thoughtsTokenCount") or 0))
            if usage else None,
            cached_tokens=usage.get("cachedContentTokenCount"),
            model=got.get("modelVersion") or model)

    def embeddings(self, *, model, input):
        texts = [input] if isinstance(input, str) else list(input)
        vectors = []
        for start in range(0, len(texts), EMBED_BATCH):
            requests = [{"model": f"models/{model}",
                         "content": {"parts": [{"text": text}]}}
                        for text in texts[start:start + EMBED_BATCH]]
            got = self._call("POST", f"models/{model}:batchEmbedContents",
                             {"requests": requests})
            vectors.extend(item.get("values") or ()
                           for item in got.get("embeddings") or ())
        return SimpleNamespace(
            data=[SimpleNamespace(index=i, embedding=list(vector))
                  for i, vector in enumerate(vectors)],
            usage=None, model=model)
