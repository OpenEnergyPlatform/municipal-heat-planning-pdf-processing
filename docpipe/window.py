"""
window.py: What one request of a model holds, and how a text that does not
fit is split so that nothing of it is cut (owner decision 2026-11-17:
"**Nichts** kürzen, einfach ggf. clever aufteilen und darauf achten, dass
die Zuordnung zu Sektion und Seite etc. nicht verlieren gehen").

A window is the number of tokens one request of a server holds, as the
server reports it (`max_model_len` on its model card and in the answer of
`/tokenize`, as vLLM gives both), else the length the deployment says its
model takes. Of that, the frame of a request (its instruction and its turns)
and its pictures take their share; the rest is the room for the text.

What a text costs is bounded from above first: the tokenizers of these
models are byte-level, so a token holds at least one byte, and a text whose
UTF-8 bytes fit the room fits. Only a text whose bytes do not fit is counted
exactly, by the server's own tokenizer (`/tokenize`) or a local one. A window
without a tokenizer counts bytes: it splits a text that would have fitted,
and never cuts one.

`split` cuts a piece into parts that each fit. The lines every part shows
(a title, a head, a heading) go into each part; the piece's own lines are
taken in their order, as many as fit; a line that does not fit with the
carried lines alone is split at its sentence ends, a sentence that does not
fit at its words. Every word of the piece stands in exactly one part, and
each part names the lines it holds. A piece whose carried lines leave no
room for a single word cannot be split, and `TooLong` says which.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

log = logging.getLogger(__name__)


class TooLong(ValueError):
    """A text that no split makes fit: the lines every part has to show
    leave no room for one word of it. Never cut instead."""


@dataclass
class Window:
    """The tokens one request holds (*limit*), the tokens of its frame
    around the text (*frame*), the exact tokens of a text where a tokenizer
    is known (*count*) and the most tokens one picture costs (*picture*,
    from the picture's path)."""
    limit: int
    frame: int = 0
    count: Optional[Callable[[str], int]] = None
    picture: Optional[Callable[[str], int]] = None
    # Texts counted exactly, kept: a text is asked once however often a
    # split looks at it.
    _counted: dict = field(default_factory=dict, repr=False, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False,
                                  compare=False)

    def room(self, pictures: Sequence = ()) -> int:
        """The tokens left for the text of a request with *pictures*."""
        used = self.frame
        for picture in pictures:
            if picture is None:
                continue
            if self.picture is None:
                raise ValueError("this window knows no cost of a picture")
            used += int(self.picture(picture))
        return int(self.limit) - used

    def tokens(self, text: str, room: Optional[int] = None) -> int:
        """At least what *text* costs: its UTF-8 bytes where they fit *room*,
        no tokenizer is known or the tokenizer did not count it (None), else
        its exact count."""
        size = len((text or "").encode("utf-8"))
        if self.count is None or (room is not None and size <= room):
            return size
        with self._lock:
            known = self._counted.get(text)
        if known is None:
            counted = self.count(text)
            if counted is None:
                return size
            known = int(counted)
            with self._lock:
                self._counted[text] = known
        return known

    def fits(self, text: str, pictures: Sequence = ()) -> bool:
        room = self.room(pictures)
        return room >= 0 and self.tokens(text, room) <= room


@dataclass(frozen=True)
class Part:
    """One part of a piece: the piece's own lines it holds (*numbers*), the
    text that stands for a line split at its sentences or words
    (*replaced*: line number -> that text), and the text it is."""
    numbers: tuple
    replaced: dict
    text: str

    @property
    def first(self) -> Optional[int]:
        return min(self.numbers) if self.numbers else None

    @property
    def last(self) -> Optional[int]:
        return max(self.numbers) if self.numbers else None


def split(numbers: Sequence[int], render: Callable[[list, dict], str],
          line: Callable[[int], str], fits: Callable[[str], bool],
          sentences: Callable[[str], list], name: str = "") -> list:
    """[Part] of a piece whose own lines are *numbers*, each of which fits.

    *render(numbers, replaced)* is the text of a part that shows the own
    lines *numbers* with every line it carries, a line in *replaced* as the
    text given there; *line(n)* is the whole text of line *n*; *fits* says
    whether a text fits; *sentences* cuts a line at its sentence ends. The
    whole piece is one part where it fits. *name* names the piece in a
    `TooLong`."""
    numbers = list(numbers)
    whole = render(numbers, {})
    if fits(whole):
        return [Part(tuple(numbers), {}, whole)]
    if not numbers:
        raise TooLong(f"{name or 'a piece'}: the lines every part of it "
                      f"shows do not fit")
    parts: list = []
    current: list = []
    for number in numbers:
        trial = render(current + [number], {})
        if fits(trial):
            current.append(number)
            continue
        if current:
            parts.append(Part(tuple(current), {}, render(current, {})))
            current = []
        alone = render([number], {})
        if fits(alone):
            current = [number]
            continue
        parts.extend(_line_parts(number, line(number), render, fits,
                                 sentences, name))
    if current:
        parts.append(Part(tuple(current), {}, render(current, {})))
    return parts


def _line_parts(number: int, text: str, render, fits, sentences,
                name: str) -> list:
    """The parts of one line that does not fit with the lines carried
    beside it: its sentences as many as fit, a sentence that does not fit
    alone in its words."""
    def made(words: list) -> Part:
        said = " ".join(words)
        return Part((number,), {number: said}, render([number], {number: said}))

    def greedy(units: list, then: Optional[Callable]) -> list:
        out: list = []
        current: list = []
        for unit in units:
            trial = current + [unit]
            if fits(render([number], {number: " ".join(trial)})):
                current = trial
                continue
            if current:
                out.append(made(current))
                current = []
            if fits(render([number], {number: unit})):
                current = [unit]
                continue
            if then is None:
                raise TooLong(f"{name or 'a piece'}: line {number} holds a "
                              f"word that does not fit beside the lines "
                              f"every part of it shows")
            out.extend(then(unit))
        if current:
            out.append(made(current))
        return out

    def by_words(sentence: str) -> list:
        return greedy(sentence.split(), None)

    pieces = sentences(text) or [text]
    return greedy(pieces, by_words)


# -- servers ------------------------------------------------------------------

# A server that did not say its window or did not count is asked again after
# this many seconds, not at every request (the chat's, the reranker's and the
# stages' windows).
ASK_AGAIN_S = 60.0


def root_of(base_url: str) -> str:
    """A server's address without the `/v1` an OpenAI client is given."""
    base = (base_url or "").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key or 'EMPTY'}"}


def served_limit(base_url: str, model: str = "", api_key: str = "",
                 timeout: float = 30.0, get: Optional[Callable] = None
                 ) -> Optional[int]:
    """The tokens one request of *model* holds on the server at
    *base_url*, as its model card says (`max_model_len`, vLLM); None where
    the server says none."""
    url = root_of(base_url) + "/v1/models"
    try:
        if get is None:
            import httpx
            answer = httpx.get(url, headers=_headers(api_key),
                               timeout=timeout)
            answer.raise_for_status()
            data = answer.json()
        else:
            data = get(url)
    except Exception as exc:
        log.warning("window: %s does not say its window: %s", url, exc)
        return None
    cards = data.get("data") if isinstance(data, dict) else None
    lens = [card.get("max_model_len") for card in cards or ()
            if isinstance(card, dict)
            and (not model or card.get("id") == model)]
    lens = [n for n in lens if isinstance(n, int) and n > 0]
    return min(lens) if lens else None


def server_counter(base_url: str, model: str, api_key: str = "",
                   timeout: float = 60.0, post: Optional[Callable] = None
                   ) -> Optional[Callable[[str], int]]:
    """count(text) -> the tokens of *text* by the tokenizer of the server at
    *base_url* (`/tokenize`, vLLM), special tokens left out, None for a text
    it did not count (the window then bounds it by its bytes, `Window.
    tokens`); None where the server does not count (asked once with an empty
    text)."""
    url = root_of(base_url) + "/tokenize"

    def ask(body: dict) -> dict:
        if post is not None:
            return post(url, body)
        import httpx
        answer = httpx.post(url, json=body, headers=_headers(api_key),
                            timeout=timeout)
        answer.raise_for_status()
        return answer.json()

    try:
        ask({"model": model, "prompt": "", "add_special_tokens": False})
    except Exception as exc:
        log.warning("window: %s counts no tokens (%s); texts are bounded by "
                    "their bytes", url, exc)
        return None

    def count(text: str) -> Optional[int]:
        try:
            data = ask({"model": model, "prompt": text,
                        "add_special_tokens": False})
        except Exception as exc:
            log.warning("window: %s did not count a text of %d characters "
                        "(%s); it is bounded by its bytes", url, len(text),
                        exc)
            return None
        value = data.get("count")
        if not isinstance(value, int):
            value = len(data.get("tokens") or ())
        return int(value)
    return count


def server_frame(base_url: str, model: str, messages: list,
                 api_key: str = "", timeout: float = 60.0,
                 post: Optional[Callable] = None, **flags) -> Optional[int]:
    """The tokens of a chat request of *messages* by the server's own
    template (`/tokenize` with messages, vLLM), None where it does not
    count. *flags* go with it as with the request (`continue_final_message`,
    `add_generation_prompt`, `add_special_tokens`)."""
    url = root_of(base_url) + "/tokenize"
    body = {"model": model, "messages": messages, **flags}
    try:
        if post is not None:
            data = post(url, body)
        else:
            import httpx
            answer = httpx.post(url, json=body, headers=_headers(api_key),
                                timeout=timeout)
            answer.raise_for_status()
            data = answer.json()
    except Exception as exc:
        log.warning("window: %s counts no chat (%s)", url, exc)
        return None
    value = data.get("count")
    if not isinstance(value, int):
        value = len(data.get("tokens") or ())
    return int(value)


def picture_tokens(path: str, factor: int, most: Optional[int] = None) -> int:
    """At most the tokens a picture costs a Qwen vision processor: one per
    *factor* x *factor* square of its pixels, a square more on each side for
    the rounding, two more for its start and end, and never more than *most*
    (the processor's own cap, where known); where the picture cannot be read,
    *most*."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            width, height = image.size
    except Exception:
        if most is None:
            raise
        return int(most)
    tokens = (-(-height // factor) + 1) * (-(-width // factor) + 1) + 2
    return int(min(tokens, most)) if most is not None else int(tokens)
