"""
cassette.py: The answers of a run, kept, so the run can be made again
without a model.

A change to the code moves what the harvest finds, and whether it moved
for the better is only seen on documents. With a model that costs a GPU and
an afternoon. A cassette is the answers of one run, each filed under what
was asked. Replayed, every request that is asked again in the same words
gets the answer it got, and the run ends where the code now takes it, on a
machine that has no model: which is what a test server is.

That holds the model still and shows the code: how an answer is read, what
is accepted, how rows are settled. It does not show a new prompt or a new
spec. Those ask in other words, and for other words there is no answer
here.

    DOCPIPE_CASSETTE_RECORD=file    a run with a model writes its answers
    DOCPIPE_CASSETTE_REPLAY=file    a run takes its answers from the file

A request is filed under its messages and the reply format it names. Not
under the model, the temperature or the room for the answer: those are the
installation's, and a replay has none. An image is filed under its pixels,
so the same picture encoded again is the same request, and under its bytes
only where it cannot be decoded. A request the file does not hold is not
answered and counted,
and it stops the stage like a server that is gone: a replay that asks
something new is the finding, not a fault to work around.

A cassette holds the text of the documents the run read. So recording is
refused for a profile that does not say its documents may be passed on
(`Profile(documents_shareable=True)`).

Author: Felix Vossel
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from .. import jsonl
from . import base

log = logging.getLogger(__name__)

RECORD_ENV = "DOCPIPE_CASSETTE_RECORD"
REPLAY_ENV = "DOCPIPE_CASSETTE_REPLAY"
HEADER, CHAT, EMBEDDING = "header", "chat", "embedding"


class CassetteMiss(LookupError):
    """A request the cassette holds no answer for."""


def recording() -> Optional[str]:
    return (os.environ.get(RECORD_ENV) or "").strip() or None


def replaying() -> Optional[str]:
    return (os.environ.get(REPLAY_ENV) or "").strip() or None


def _picture(data: str) -> dict:
    """What an image of a request is filed under: its pixels.

    The data URL holds what an encoder made of them, and another build of
    the encoder writes other bytes for the same picture: filed under those,
    a recording would be answered only on the machine that made it. What
    is no picture that can be opened here is filed under its text.
    """
    head, marker, body = data.partition(";base64,")
    if head.startswith("data:") and marker:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(base64.b64decode(body))) as image:
                image.load()
                digest = hashlib.sha256(
                    repr((image.mode, image.size)).encode("utf-8"))
                digest.update(image.tobytes())
            return {"type": "image_url", "pixels": digest.hexdigest()}
        except Exception:       # not a picture, or no library to open one
            pass
    return {"type": "image_url", "sha256": hashlib.sha256(
        data.encode("utf-8")).hexdigest()}


def _stable(node):
    """A request part as it is filed: an image by its pixels."""
    if isinstance(node, dict):
        url = node.get("image_url")
        if node.get("type") == "image_url" and isinstance(url, dict):
            return _picture(str(url.get("url") or ""))
        return {key: _stable(value) for key, value in node.items()}
    if isinstance(node, (list, tuple)):
        return [_stable(item) for item in node]
    return node


def chat_key(kwargs: dict) -> str:
    """What a chat request is filed under."""
    shape = kwargs.get("response_format") or {}
    named = (shape.get("json_schema") or {}).get("name") \
        if isinstance(shape, dict) else None
    filed = {"messages": _stable(kwargs.get("messages") or []),
             "reply": named or (shape.get("type")
                                if isinstance(shape, dict) else None)}
    blob = json.dumps(filed, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _texts(kwargs: dict) -> list:
    texts = kwargs.get("input")
    return [texts] if isinstance(texts, str) else list(texts or [])


def embedding_key(text: str) -> str:
    """What the vector of one text is filed under: the text, not the batch
    it happened to travel in."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _may_record() -> None:
    from ..profile import active_profile
    profile = active_profile()
    if profile is None or not getattr(profile, "documents_shareable", False):
        name = profile.name if profile is not None else None
        raise ValueError(
            f"{RECORD_ENV} is set, and a cassette holds the text of the "
            f"documents a run reads. Profile {name!r} does not say its "
            f"documents may be passed on "
            f"(Profile(documents_shareable=True)), so nothing is recorded.")


class Recorder:
    """A client whose answers are also written to a file."""

    _lock = threading.Lock()

    def __init__(self, client, path):
        _may_record()
        self._client = client
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _write(self, record: dict) -> None:
        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @property
    def chat(self):
        def create(**kwargs):
            answer = self._client.chat.completions.create(**kwargs)
            choice = answer.choices[0]
            usage = getattr(answer, "usage", None)
            self._write({
                "kind": CHAT, "key": chat_key(kwargs),
                "content": choice.message.content,
                "reasoning": getattr(choice.message, "reasoning_content",
                                     None),
                "finish": choice.finish_reason,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens",
                                             None)})
            return answer
        return SimpleNamespace(completions=SimpleNamespace(create=create))

    @property
    def embeddings(self):
        def create(**kwargs):
            answer = self._client.embeddings.create(**kwargs)
            for text, item in zip(_texts(kwargs), answer.data):
                self._write({"kind": EMBEDDING, "key": embedding_key(text),
                             "vector": list(item.embedding)})
            return answer
        return SimpleNamespace(create=create)


def note_limits(model: str, max_model_len: Optional[int]) -> None:
    """Write down what the server of a recorded run offered. A replay plans
    its requests for that window, or it would ask other ones."""
    path = recording()
    if not path:
        return
    from .. import __version__
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Recorder._lock, open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "kind": HEADER, "model": model, "max_model_len": max_model_len,
            "docpipe": __version__}) + "\n")


class Player:
    """A client that answers from a file and from nothing else."""

    def __init__(self, path):
        self.path = Path(path)
        self.header: dict = {}
        self.limits: dict = {}
        self._chat: dict = {}
        self._embeddings: dict = {}
        self.replayed = self.missed = 0
        try:
            lines = jsonl.read(self.path)
        except OSError as exc:
            raise CassetteMiss(f"{REPLAY_ENV} names {str(self.path)!r}, "
                               f"which cannot be read: {exc}") from exc
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            kind = record.get("kind")
            if kind == HEADER:
                self.header = record
                self.limits[record.get("model")] = record.get("max_model_len")
            elif kind == CHAT:
                # The same question asked twice got two answers: they are
                # given back in the order they came.
                self._chat.setdefault(record["key"], []).append(record)
            elif kind == EMBEDDING:
                self._embeddings[record["key"]] = record
        self._lock = threading.Lock()

    def _miss(self, what: str, key: str):
        self.missed += 1
        raise CassetteMiss(f"{self.path.name} holds no answer to this "
                           f"{what} ({key[:12]}): the run asks something "
                           f"the recorded one did not")

    @property
    def chat(self):
        def create(**kwargs):
            key = chat_key(kwargs)
            with self._lock:
                held = self._chat.get(key)
                if not held:
                    self._miss("request", key)
                record = held.pop(0) if len(held) > 1 else held[0]
                self.replayed += 1
            return base.reply(
                record.get("content"), record.get("finish") or base.STOP,
                prompt_tokens=record.get("prompt_tokens"),
                completion_tokens=record.get("completion_tokens"),
                model=self.header.get("model"),
                reasoning=record.get("reasoning"))
        return SimpleNamespace(completions=SimpleNamespace(create=create))

    @property
    def embeddings(self):
        def create(**kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(index=i, embedding=self.vector(text))
                      for i, text in enumerate(_texts(kwargs))],
                usage=None, model=self.header.get("model"))
        return SimpleNamespace(create=create)

    def vector(self, text: str) -> list:
        key = embedding_key(text)
        record = self._embeddings.get(key)
        if record is None:
            self._miss("text to embed", key)
        self.replayed += 1
        return record["vector"]

    def window(self, model: Optional[str] = None) -> Optional[int]:
        """The context size the recorded run was planned for."""
        if model in self.limits:
            return self.limits[model]
        return self.header.get("max_model_len")

    @property
    def models(self):
        cards = [SimpleNamespace(id=model, max_model_len=window)
                 for model, window in self.limits.items()]
        return SimpleNamespace(list=lambda: SimpleNamespace(data=cards))


class ReplayEmbedder:
    """The embedder of a replay. A run that searched with a model on its
    own machine left its query vectors in the query cache, which goes with
    the cassette; one that embedded through an API left them in the
    cassette. What neither holds is not embedded: there is no model."""

    def embed(self, items) -> list:
        held = player()
        for item in items:
            if item.get("image"):
                # Counted like every request the cassette cannot answer.
                held._miss("item with an image",
                           embedding_key(str(item.get("text") or "")))
        return [held.vector(str(item.get("text") or "")) for item in items]

    def embed_one(self, item: dict) -> list:
        return self.embed([item])[0]


_players: dict = {}
_players_lock = threading.Lock()


def player(path: Optional[str] = None) -> Player:
    """The one player of a file: every stage of a run reads the same one,
    so an answer that was given is not given twice."""
    path = path or replaying()
    with _players_lock:
        if path not in _players:
            _players[path] = Player(path)
        return _players[path]
