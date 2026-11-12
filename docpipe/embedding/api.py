"""
api.py: Embeds items by calling an embeddings API.

ApiEmbedder is for deployments without a GPU, or for a deployment
where the embedding model is served centrally. Which API it calls is
the provider of the `embedding` role (EMBEDDING_PROVIDER, see
docpipe/providers): an OpenAI-compatible /v1/embeddings endpoint, or
a hosted one. It batches items into groups of batch_size before
calling it, and asks a hosted API again that answers "not now".

The OpenAI request has no place for an image, so in that form
(EMBEDDING_API_FORMAT=input) embed() is text only: an item carrying an
image is refused with a ValueError rather than silently embedded as
text. A vLLM server also takes the item as a chat
(EMBEDDING_API_FORMAT=messages): the instruction, the picture and the
text in the turns the model's own code builds (`conversation`), which
embeds a figure with its picture.

Author: Felix Vossel
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from docpipe import providers, usage
from docpipe.providers import governor

from . import config

log = logging.getLogger(__name__)

# Attempts at one batch for a hosted API that answers "not now".
HOSTED_ATTEMPTS = 6

# The instruction an item is embedded under when it names none, as the
# model's own code sets it (Qwen3VLEmbedder in chunking/qwen3_vl_embedding.py).
DEFAULT_INSTRUCTION = "Represent the user's input."

# How long one request of the messages form may take, the OpenAI client's
# own default, which the input form waits with.
REQUEST_SECONDS = 600.0


def data_uri(image) -> str:
    """A picture as the URL a chat message carries: a file as a data URI, a
    URL as it is."""
    if isinstance(image, str) and image.startswith(("http://", "https://",
                                                    "data:")):
        return image
    path = Path(image)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return (f"data:{mime};base64,"
            + base64.b64encode(path.read_bytes()).decode("ascii"))


def conversation(item: dict) -> list:
    """The chat one item is embedded as, in the messages form.

    The turns of Qwen3VLEmbedder.format_model_input: the instruction as the
    system turn (a full stop added where it ends without punctuation), the
    picture before the text in the user turn, "NULL" for an item with
    neither. The empty assistant turn is continued by the request
    (`continue_final_message`), so the prompt ends where the model's own code
    ends it with `add_generation_prompt`, and the pooled last token is the
    same one.
    """
    instruction = (item.get("instruction") or "").strip()
    if instruction and not unicodedata.category(instruction[-1]).startswith("P"):
        instruction += "."
    content: list = []
    if item.get("image"):
        content.append({"type": "image_url",
                        "image_url": {"url": data_uri(item["image"])}})
    if item.get("text"):
        content.append({"type": "text", "text": str(item["text"])})
    if not content:
        content.append({"type": "text", "text": "NULL"})
    return [
        {"role": "system",
         "content": [{"type": "text", "text": instruction or DEFAULT_INSTRUCTION}]},
        {"role": "user", "content": content},
        {"role": "assistant", "content": [{"type": "text", "text": ""}]},
    ]


def unit_rows(vectors) -> list:
    """Each vector scaled to length one: the index is an inner-product index
    of unit vectors, and the model's own code hands out unit vectors."""
    array = np.asarray(vectors, dtype=np.float32)
    lengths = np.linalg.norm(array, axis=1, keepdims=True)
    return (array / np.where(lengths == 0, 1.0, lengths)).tolist()


class ApiEmbedder:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None, batch_size: Optional[int] = None,
                 form: Optional[str] = None, post=None):
        self.base_url = base_url or config.EMBEDDING_BASE_URL
        self.api_key = api_key or config.EMBEDDING_API_KEY
        self.model = model or config.EMBEDDING_MODEL
        self.batch_size = batch_size or config.EMBEDDING_BATCH_SIZE
        self.form = (form or config.EMBEDDING_API_FORMAT).strip()
        if self.form not in ("input", "messages"):
            raise ValueError(f"EMBEDDING_API_FORMAT is {self.form!r}: "
                             f"'input' or 'messages'")
        if not self.base_url and not providers.hosted("embedding"):
            raise ValueError("EMBEDDING_BASE_URL is required for the api backend")
        if self.form == "messages" and not self.base_url:
            raise ValueError("the messages form needs EMBEDDING_BASE_URL, the "
                             "server that takes it")
        self._client = None
        self._post = post

    @property
    def text_only(self) -> bool:
        """Whether a picture has no place in this embedder's requests."""
        return self.form != "messages"

    def client(self):
        if self._client is None:
            self._client = providers.client(
                "embedding", base_url=self.base_url, api_key=self.api_key)
        return self._client

    def _create(self, batch: list):
        """The vectors of one batch.

        A hosted API that says "not now" is asked again: its gate has made
        every request wait by then (docpipe/providers/governor.py), so the
        next attempt goes out when the API said it may. A server of one's
        own is asked once, as before; its client retries by itself.
        """
        attempts = HOSTED_ATTEMPTS if providers.hosted("embedding") else 1
        for attempt in range(1, attempts + 1):
            try:
                return self.client().embeddings.create(model=self.model,
                                                       input=batch)
            except Exception as exc:
                limited = governor.limited_statuses()
                again = (governor.status_of(exc) in limited
                         or providers.timed_out(exc))
                if attempt == attempts or not again:
                    raise
                log.warning("embeddings: attempt %d of %d not served (%s)",
                            attempt, attempts, exc)

    def _post_json(self, body: dict) -> dict:
        """One request of the messages form, its JSON answer."""
        if self._post is not None:
            return self._post(body)
        import httpx
        response = httpx.post(
            self.base_url.rstrip("/") + "/embeddings", json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=REQUEST_SECONDS)
        response.raise_for_status()
        return response.json()

    def _embed_message(self, item: dict) -> list:
        answer = self._post_json({
            "model": self.model,
            "messages": conversation(item),
            "continue_final_message": True,
            "add_special_tokens": True,
            "encoding_format": "float",
        })
        tokens = (answer.get("usage") or {}).get("prompt_tokens")
        if isinstance(tokens, int):
            usage.add(self.model, embedding_tokens=tokens, requests=1)
        return answer["data"][0]["embedding"]

    def embed(self, items: Sequence[dict]) -> list:
        if self.form == "messages":
            # One chat per request, all of a call in flight at once: the
            # server batches them, the caller sizes the call.
            if not items:
                return []
            with ThreadPoolExecutor(max_workers=len(items)) as pool:
                return unit_rows(list(pool.map(self._embed_message, items)))

        visual = [i for i, it in enumerate(items) if it.get("image")]
        if visual:
            raise ValueError(
                f"item(s) {visual} carry an image; the OpenAI embeddings API is "
                f"text-only. Use EMBEDDING_API_FORMAT=messages with a vLLM "
                f"server, or EMBEDDING_BACKEND=local, for *_vl embeddings.")

        out = []
        texts = [str(it.get("text") or "") for it in items]
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            response = self._create(batch)
            out.extend(d.embedding for d in response.data)
            tokens = getattr(getattr(response, "usage", None), "prompt_tokens", None)
            if isinstance(tokens, int):
                usage.add(self.model, embedding_tokens=tokens, requests=len(batch))
        return out

    def embed_one(self, item: dict) -> list:
        return self.embed([item])[0]
