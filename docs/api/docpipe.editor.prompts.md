# docpipe.editor.prompts

`docpipe/editor/prompts.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

prompts.py: What the editor does with a profile's prompts.

It lists them with the profile each file belongs to, cuts a file into the
pieces a person edits (the settings on top, what every request is told, each
part only some requests are told), checks a text before it is written, and
makes the instruction of a recorded request from a text that is not written
yet, so that a changed sentence is seen in the requests that would carry it.

Nothing here knows how a prompt is read or put together: that is the
loader's (`docpipe.prompts.made`), the cut at the markers is the run's
(`extraction.thread.cut`), and the instruction of a request is made by the
two functions every request of the harvest passes (`runner.request_prompt`,
`runner.system_text`). The one thing a record does not carry is the example
reply the run wrote into the instruction; it is read back out of the
recorded instruction (`_places`).

A text is refused where a run would fail on it: a front matter the loader
cannot read, a parts file its template does not take, a part marked twice, a
follow-up part the file had and lost, and a `{{name}}` the file on disk does
not have or one it has that is gone, since the code fills exactly the names
that are there. And where a run would send what was not meant: a marker of a
part that the text adds and the run would take for text, because it does not
stand on a line of its own.

Author: Felix Vossel

## Classes

### Refused

```python
class Refused(ValueError)
```

Something the editor does not do, said in one sentence.

## Functions

### concerns

```python
def concerns(prompt_id: str, request: dict) -> bool
```

Whether the prompt has a say in a recorded request: it makes its
instruction, or it is the follow-up prompt and the request is one
asked once more.

### kinds_of

```python
def kinds_of(prompt_id: str) -> list
```

The kinds of recorded requests a prompt has a say in: the requests
of its own kind, and for the follow-up prompt those asked once more.

### listing

```python
def listing(profile) -> list
```

Every prompt the profile runs with, its own and those of the
profiles it extends, by stage and name.

### segments

```python
def segments(raw: str) -> dict
```

*raw* cut without loss: `front` (the settings between the two rules,
"" where the file has none), `common` (what every request is told) and
`parts`, each with the line that marks it (`mark`), its kind, the
fields it is about and its text. `joined` puts them back character for
character.

### joined

```python
def joined(cut: dict) -> str
```

### on_disk

```python
def on_disk(profile, prompt_id: str, read: Callable) -> dict
```

The file a run loads for *prompt_id*: the profile that owns it, its
path, its bytes (*read(path)*), its text with "\n" line ends and the
line ends it has. FileNotFoundError where no profile of the line has
it.

### target_of

```python
def target_of(profile, prompt_id: str) -> Path
```

Where the profile's own file of *prompt_id* is, or would be.

### detail

```python
def detail(profile, prompt_id: str, read: Callable) -> dict
```

What the page shows of one prompt.

### problem

```python
def problem(profile, prompt_id: str, raw: str, disk: dict) -> Optional[str]
```

Why the text *raw* is not written as the profile's file of
*prompt_id*: a run would fail on it, or send what was not meant. None
where neither holds. *disk* is the file a run loads today
(`on_disk`).

### judge

```python
def judge(profile, prompt_id: str, raw: str, disk: dict) -> dict
```

Everything the page shows after "Check" for the text *raw*; nothing
is written.

### save

```python
def save(profile, prompt_id: str, raw: str, disk: dict) -> tuple
```

(the report of `judge`, the bytes to write or None, where to write
them). Nothing to write where the check fails (`reason: "check"`) or
the text is the file's (`reason: "same"`).

### prompt_of

```python
def prompt_of(request: dict) -> Optional[str]
```

The prompt that makes the instruction of a recorded request (one of
`requests.requests_of`): that of its kind, for a request asked once
more that of the request it follows; None for a kind the editor cannot
put together again.

### payload_of

```python
def payload_of(sent: dict) -> tuple
```

(the payload the first user message of *sent* shows, where it ends
in that message's text, that text); (None, 0, "") where it shows
none.

### marked

```python
def marked(before: str, after: str) -> dict
```

*after* by line and sentence, each sentence with whether *before*
does not have it there (`lines`), and the sentences of *before* that
*after* lost (`gone`). A sentence stands in `lines` with the blanks
that follow it, so the pieces of a line are the line character for
character.

### preview

```python
def preview(profile, request: dict, sent: dict, edits: dict,
            read: Callable) -> dict
```

What a recorded request would be sent with: the instruction, and for
a request asked once more its message, as the files on disk make them
(`file`) and as the texts in *edits* ({prompt id: text}) make them
(`edit`).

`same_as_recorded` says whether the files on disk give the record
character for character, `changed` whether the edit changes this
request at all, `lines` the edit's instruction by line and sentence
with the changed ones marked. Where the request cannot be put together
again, `why` says so and the rest is None.

[Back to the index](../README.md)
