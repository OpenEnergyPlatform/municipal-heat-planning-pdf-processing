# docpipe.editor.start

`docpipe/editor/start.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

start.py: `docpipe edit` itself: it starts the server, and starts it again
with the profile the page switches to.

A process runs on one profile. A stage binds part of what its profile says
when it is imported, and `profile.resolve_profile` refuses to name another
profile after that rather than run on a mix of both. So the page does not
switch the profile inside the server. The command runs the server as a
process of its own (`python -m docpipe --profile NAME edit ... --switch-file
NOTE`, `server.serve_one`). A switch writes the profile and the server's
port into the note and ends the server with `RESTART` once its answer is
sent; the command then starts the server with that profile at the same port
and does not open the page again: the page waits for the server and loads
itself anew. A harvest given with `--harvest` belongs to the profile the
command was started with: the server is given it whenever it runs with that
profile, and never with another.

The server ends with the command. Ctrl+C reaches both, and a server whose
command is gone stops by itself: its standard input is a pipe the command
holds, and that pipe ends when the command does, also a command that was
killed.

Author: Felix Vossel

## Functions

### parser

```python
def parser() -> argparse.ArgumentParser
```

The arguments of `docpipe edit`, of the command and of each server it
starts.

### note_bytes

```python
def note_bytes(name: str, port: int) -> bytes
```

What a server writes into the note for a switch to profile *name*.

### read_note

```python
def read_note(note: Path) -> tuple
```

(profile, port) the server wrote into *note*.

### line

```python
def line(name: str, port: int, harvest: Optional[Path], browser: bool,
         note: Path) -> list
```

The command line of one server: profile *name* at *port*.

### loop

```python
def loop(name: str, port: int, harvest: Optional[Path], browser: bool,
         run: Callable[[list], int] = _run) -> int
```

Run the server with profile *name*, and again with each profile it
ends for, until it ends for no switch; the exit status of the last.

### main

```python
def main(rest: Sequence[str]) -> int
```

`docpipe edit`: the command, or one server it started.

[Back to the index](../README.md)
