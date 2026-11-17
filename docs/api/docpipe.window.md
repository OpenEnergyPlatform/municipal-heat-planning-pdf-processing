# docpipe.window

`docpipe/window.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

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

## Classes

### TooLong

```python
class TooLong(ValueError)
```

A text that no split makes fit: the lines every part has to show
leave no room for one word of it. Never cut instead.

### Window

```python
@dataclass
class Window
```

The tokens one request holds (*limit*), the tokens of its frame
around the text (*frame*), the exact tokens of a text where a tokenizer
is known (*count*) and the most tokens one picture costs (*picture*,
from the picture's path).

Fields:

- `limit: int`
- `frame: int = 0`
- `count: Optional[Callable[[str], int]] = None`
- `picture: Optional[Callable[[str], int]] = None`

#### Window.room

```python
def room(self, pictures: Sequence = ()) -> int
```

The tokens left for the text of a request with *pictures*.

#### Window.tokens

```python
def tokens(self, text: str, room: Optional[int] = None) -> int
```

At least what *text* costs: its UTF-8 bytes where they fit *room*,
no tokenizer is known or the tokenizer did not count it (None), else
its exact count.

#### Window.fits

```python
def fits(self, text: str, pictures: Sequence = ()) -> bool
```

### Part

```python
@dataclass(frozen=True)
class Part
```

One part of a piece: the piece's own lines it holds (*numbers*), the
text that stands for a line split at its sentences or words
(*replaced*: line number -> that text), and the text it is.

Fields:

- `numbers: tuple`
- `replaced: dict`
- `text: str`

#### Part.first

```python
@property
def first(self) -> Optional[int]
```

#### Part.last

```python
@property
def last(self) -> Optional[int]
```

## Functions

### split

```python
def split(numbers: Sequence[int], render: Callable[[list, dict], str],
          line: Callable[[int], str], fits: Callable[[str], bool],
          sentences: Callable[[str], list], name: str = "") -> list
```

[Part] of a piece whose own lines are *numbers*, each of which fits.

*render(numbers, replaced)* is the text of a part that shows the own
lines *numbers* with every line it carries, a line in *replaced* as the
text given there; *line(n)* is the whole text of line *n*; *fits* says
whether a text fits; *sentences* cuts a line at its sentence ends. The
whole piece is one part where it fits. *name* names the piece in a
`TooLong`.

### root_of

```python
def root_of(base_url: str) -> str
```

A server's address without the `/v1` an OpenAI client is given.

### served_limit

```python
def served_limit(base_url: str, model: str = "", api_key: str = "",
                 timeout: float = 30.0, get: Optional[Callable] = None
                 ) -> Optional[int]
```

The tokens one request of *model* holds on the server at
*base_url*, as its model card says (`max_model_len`, vLLM); None where
the server says none.

### server_counter

```python
def server_counter(base_url: str, model: str, api_key: str = "",
                   timeout: float = 60.0, post: Optional[Callable] = None
                   ) -> Optional[Callable[[str], int]]
```

count(text) -> the tokens of *text* by the tokenizer of the server at
*base_url* (`/tokenize`, vLLM), special tokens left out, None for a text
it did not count (the window then bounds it by its bytes, `Window.
tokens`); None where the server does not count (asked once with an empty
text).

### server_frame

```python
def server_frame(base_url: str, model: str, messages: list,
                 api_key: str = "", timeout: float = 60.0,
                 post: Optional[Callable] = None, **flags) -> Optional[int]
```

The tokens of a chat request of *messages* by the server's own
template (`/tokenize` with messages, vLLM), None where it does not
count. *flags* go with it as with the request (`continue_final_message`,
`add_generation_prompt`, `add_special_tokens`).

### picture_tokens

```python
def picture_tokens(path: str, factor: int, most: Optional[int] = None) -> int
```

At most the tokens a picture costs a Qwen vision processor: one per
*factor* x *factor* square of its pixels, a square more on each side for
the rounding, two more for its start and end, and never more than *most*
(the processor's own cap, where known); where the picture cannot be read,
*most*.

[Back to the index](../README.md)
