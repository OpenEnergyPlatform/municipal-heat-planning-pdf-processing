# docpipe.visuals.config

`docpipe/visuals/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

config.py – Central configuration for the imageprocessing module.

Author: Felix Vossel

## Functions

### dump_json_atomic

```python
def dump_json_atomic(data, path) -> None
```

Serialise *data* as UTF-8 JSON to *path* atomically (temp file +
os.replace). Atomic only within one filesystem.

### shown_bytes

```python
def shown_bytes(section_content: str = "", head: str = "",
                between: str = "") -> int
```

The UTF-8 bytes one request shows beside its prompts.

### longest_shown

```python
def longest_shown(sections: list) -> int
```

The most UTF-8 bytes one request of a document with *sections* shows
beside its prompts: its longest section text, the longest text between
two of its tables that may continue one another, and, for the head of
the table before, the longest PDF text of one of its tables (a head is
part of it).

### longest_in

```python
def longest_in(root, names: tuple = ()) -> int
```

`longest_shown` over every document the stage reads under *root*,
or over *root* itself where it is one document: the first of *names*
each has (the sections files the stage reads, the refined one first
where none are given); 0 where there are none or none can be read.

### max_request_tokens

```python
def max_request_tokens(shown: int | None = None) -> int
```

Worst case for one vision request: the longer of the two requests'
prompts with the texts they show, + one page image + the reply we ask
for, once. *shown* is the UTF-8 bytes the request shows beside its
prompts (`shown_bytes`; for the stage's preflight `longest_in` of the
documents the run reads, taken from the active profile's processed
folder where not given). A table's request counts the part it gets
where it may continue the table before it. A reply cut off at its limit
is asked once more with more room, but the room is bounded by what the
served window leaves beyond this number (vision.call_vision), so no
second reply is counted.

### table_system_prompt

```python
@prompts.per_profile
def table_system_prompt() -> str
```

### table_user_prompt

```python
@prompts.per_profile
def table_user_prompt() -> str
```

### table_continued_prompt

```python
@prompts.per_profile
def table_continued_prompt() -> str
```

### caption_keep_instruction

```python
@prompts.per_profile
def caption_keep_instruction() -> str
```

### caption_generate_table_instruction

```python
@prompts.per_profile
def caption_generate_table_instruction() -> str
```

### caption_generate_figure_instruction

```python
@prompts.per_profile
def caption_generate_figure_instruction() -> str
```

### figure_system_prompt

```python
@prompts.per_profile
def figure_system_prompt() -> str
```

### figure_user_prompt

```python
@prompts.per_profile
def figure_user_prompt() -> str
```

[Back to the index](../README.md)
