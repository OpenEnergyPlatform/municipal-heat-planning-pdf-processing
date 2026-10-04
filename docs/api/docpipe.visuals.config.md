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

### max_request_tokens

```python
def max_request_tokens() -> int
```

Worst case for one vision request: the longer of the two system
prompts + one page image + the reply we ask for.

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
