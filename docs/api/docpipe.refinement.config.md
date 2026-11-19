# docpipe.refinement.config

`docpipe/refinement/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

config.py – Configuration and system prompt for the text-refinement module.

Author: Felix Vossel

## Functions

### prompt_ids

```python
def prompt_ids() -> tuple
```

The prompts a run of this stage is made of, the ones its stored
results are versioned by. Only the window prompt actually in use is
named, or merely having the second one on disk would count as a change
against every stored result.

### refine_prompt

```python
def refine_prompt()
```

### system_prompt

```python
def system_prompt() -> str
```

### refine_prompt_id

```python
def refine_prompt_id() -> str
```

The prompt a window of this stage is asked with (`refine_prompt`).

### llm_temperature

```python
def llm_temperature() -> float
```

### llm_max_tokens

```python
def llm_max_tokens() -> int
```

### reply_tokens

```python
def reply_tokens(user_words: int) -> int
```

The max_tokens for one request, from what that request actually asks
the model to write. llm_max_tokens() stays the floor for small windows.

When the model returns corrections it does not scale at all: the reply is a
list of find/replace pairs, so its size follows the number of artefacts and
not the length of the section. That is the entire saving. The budget still
has to cover a bibliography, which is the one case that writes text out.

### largest_reply_tokens

```python
def largest_reply_tokens() -> int
```

The largest reply a request of this stage asks for: the one reply the
context budget counts.

### max_request_tokens

```python
def max_request_tokens() -> int
```

Worst case for one window: prompt + a full window of maximum-size
sections + the whole section before it as context (a section is at most
the rule section_max_words) + the largest reply we would ever ask for, once.

A section that cannot be split any further, whose reply was cut off, is
asked once more with more room, but the room is bounded by what the served
window leaves beyond this number (`further_room`), so the budget does not
count a second reply. Rests on split.py holding section_max_words on its
output. The one case it cannot hold, a single segment longer than the
limit, is logged there.

### further_room

```python
def further_room(asked: int)
```

The token limit of the one further attempt of a window or an outline
that was cut off at *asked* tokens and cannot be split, or None when the
served window leaves it no more room than it had. See
`llm_preflight.further_room`.

### dump_json_atomic

```python
def dump_json_atomic(data, path) -> None
```

Serialise *data* as UTF-8 JSON to *path* atomically (temp file in the same
directory + os.replace), so an interrupted write cannot leave a truncated
file behind. Atomic only within one filesystem.

[Back to the index](../README.md)
