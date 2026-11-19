# docpipe.editor.staged

`docpipe/editor/staged.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

staged.py: A recorded request of stage 4 or 5, put together again from the
prompt files and sent once more.

The refinement (stage 4) and the visuals (stage 5) write the request log the
harvest writes (owner request 2026-11-19, A3: "Dann gelten Vorschau,
Ausprobieren und die Messsätze auch für sie"). Each request in it names what
its messages are made of (`made`: the parts of `docpipe.prompts.composed`),
and the head of the log holds the text of every prompt as the run read it
(`trace.stage_head`). What filled the parts is read back from the recorded
messages with those texts (`prompts.values_in`), and the messages are made
again with the files on disk and with the texts being edited: the preview
(`preview`, in the form `editor.prompts.preview` gives) and the try (`once`).

A picture is recorded as the file it is cut from (`vision.logged`) and read
from the document's folder again, a strip cut from it the same way
(`strips.strip_of`). The reply is read as the stage reads it, by the first
required key of its reply form (`requests.reply_key`, `reading.read`).

Author: Felix Vossel

## Exports

What `__all__` names, and where each name is defined:

- `ROLES`
- `ROLE_OF`

## Functions

### is_staged

```python
def is_staged(request: dict) -> bool
```

Whether *request* is one of a stage before the harvest: it names
what its messages are made of.

### role_of

```python
def role_of(head: Optional[dict], sent: Optional[dict] = None) -> str
```

Which model a request of a stage log asks: "vlm" for the visuals,
"llm" for the refinement; where the head names no stage, "vlm" for a
request that shows a picture.

### recorded

```python
def recorded(sent: dict) -> dict
```

{role: the text of the first message of that role} of the request
*sent*; a message made of parts gives its one text part. None for a
role whose text cannot be read.

### preview

```python
def preview(profile, request: dict, sent: dict, edits: dict, read: Callable,
            head: Optional[dict] = None) -> dict
```

What a recorded request of a stage would be sent with, in the form of
`editor.prompts.preview`: its instruction and its message as the files
on disk make them (`file`) and as the texts in *edits* ({prompt id:
text}) make them (`edit`). What filled them is read back from the
record with the texts the run read (the `prompts` of its log's *head*,
the files on disk for a prompt the head lacks). `lines` and `gone` mark
the changed sentences of the instruction, `user_lines` and `user_gone`
those of the message. Where the request cannot be put together again,
`why` says so and the rest is None.

### picture

```python
def picture(shown: dict, folder: Path, read_bytes: Callable) -> str
```

The data URL of a picture as a stage log names it (`vision.logged`):
the file *shown* names in the document's folder *folder*, read with
*read_bytes*, the strip cut from it where it names one. LookupError
where the strip cannot be cut again (the file changed since the run).

### messages_of

```python
def messages_of(sent: dict, view: dict, folder: Path,
                read_bytes: Callable) -> list
```

The messages of the recorded request *sent* with the instruction and
the message of *view* (`preview`) in place of the first of each role,
every picture read again (`picture`); the later messages of an attempt
(a reply and what was said about it) as they were sent.

### once

```python
def once(client, model: str, sent: dict, view: dict, folder: Path,
         read_bytes: Callable, profile=None) -> dict
```

One call: the recorded request *sent* with the instruction and the
message of *view*, its reply form, room and settings as recorded, and
what came back, read as the stage reads it.

[Back to the index](../README.md)
