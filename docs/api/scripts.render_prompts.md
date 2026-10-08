# scripts.render_prompts

`scripts/render_prompts.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

render_prompts.py: What a change does to the prompts of a profile, read before
anything runs.

A prompt is the contract with the model, and a sentence that moves in it moves
every request of a run. A diff of the files shows the words somebody edited. It
does not show the text the loader makes of them, and not what that text does to
the window a run asks the server for. So both sides are rendered by their own
code and set next to each other:

  before   `git archive` of a ref, unpacked into a temporary folder and read by
           THAT tree's loader, in a process of its own
  after    the working tree, read by its own loader the same way

Per profile and prompt it writes the exact text of each side
(`<stage>/<name>.before.txt`, `.after.txt`), the sentences that differ
(`.sentences.diff`, one changed sentence per line) and, in `summary.md`, the
sizes, the sha256 of each side and what a run takes from the prompts: sources
per request and the window it asks the server for, each by the rule of its own
side. The tool reads files and imports the two trees. It does not touch the
repository, a model or `data/`, and it refuses an output folder inside the
repository.

The numbers rest on the settings' defaults. The environment's EXTRACT\_*
variables, a project file and a `.env` are not read, so two runs on two
machines give the same numbers.

    python scripts/render_prompts.py --profile kwp --profile scenarios --before HEAD
    python scripts/render_prompts.py --profile kwp --before main --out ../review
    python scripts/render_prompts.py --profile default --before HEAD~2 --what-if
    python scripts/render_prompts.py --profile kwp --before HEAD --check-domain r.json

`--check-domain FILE` holds a rewrite to "the domain stays word for word": the
file lists, per profile and prompt, the physical line numbers of the OLD file
(front matter counted) that are the core's contract wording and those that are
mixed:

    {"kwp": {"extraction/rows": {"contract": [[7, 7], [9, 9]],
                                 "mixed": [[37, 37]]}}}

Every other non-blank old line must stand verbatim in the new text, ignoring a
leading rule number ("12. "). A line that does not is named and the exit code
is 1. Mixed lines are listed with whether they stand verbatim, for a person to
read.

The summary lists the overrides and omissions of every composed prompt, and
`--what-if` also renders each block a profile leaves out back in. A loader that
composes prompts says so on `Prompt.composition`: None for a plain prompt,
else a mapping with `template`, `overrides` (block names a profile words
itself), `omitted` (block names it leaves out) and, for the what-if,
`what_if` ({omitted block: the prompt's text with that block put back}). A
loader that composes nothing has nothing to show, and the summary says so. One
that reports an omission and gives no text for it fails the run: the question
asked had an answer and it was not given.

Exit code: 0 when everything asked for was rendered, 1 when a prompt or a
profile could not be rendered or a domain line is missing, 2 when the request
cannot be carried out (an unknown ref, an output folder inside the repository).

Author: Felix Vossel

## Classes

### Refused

```python
class Refused(Exception)
```

A request that cannot be carried out. The message says why.

## Functions

### repo_root

```python
def repo_root(path: Path) -> Path
```

The top of the repository *path* lies in.

### resolve_ref

```python
def resolve_ref(root: Path, ref: str) -> str
```

The commit a ref names. A ref that starts with '-' is an option for
git, not a ref.

### head_state

```python
def head_state(root: Path) -> tuple
```

(HEAD, whether the working tree differs from it where prompts and the
loader live): the 'after' side is the working tree, not HEAD.

### extract_tree

```python
def extract_tree(root: Path, sha: str, dest: Path) -> None
```

The files of one commit that a loader needs, unpacked into *dest*.

Files and folders only: a link would be followed outside the temporary
folder or fail by the machine's rights, and either is a prompt that is
quietly not the one the commit holds.

### default_out

```python
def default_out() -> Path
```

### choose_out

```python
def choose_out(given: Optional[Path], root: Path) -> Path
```

The folder to write into: resolved, outside the repository, empty or
not there yet. Compared after resolving, so `..` and links do not get a
path inside past the check. A folder that already holds files is refused
because files of an earlier run would sit beside this one's and read as
its own.

### composition_of

```python
def composition_of(prompt) -> Optional[dict]
```

How a loader composed a prompt, or None for a plain one. See the module
docstring for the names it reads.

### probe

```python
def probe(tree: Path, name: str) -> dict
```

One profile as the loader of *tree* reads it: every prompt it has or
inherits, and what a run would take from them. Imports the tree, so it runs
in a process of its own and never in the caller's.

### probe_env

```python
def probe_env(scratch: Path, profile: str) -> dict
```

The environment of one probe: the caller's, minus what would move the
numbers, plus a place for everything a loader might write. Nothing is
written beside the code, so the repository stays as it was.

### run_probe

```python
def run_probe(tree: Path, profile: str, scratch: Path) -> dict
```

`probe` for one tree and profile, in a process whose working folder is
empty: a `.env` or a `docpipe.toml` of the tree must not be found.

### sentences

```python
def sentences(line: str) -> list
```

One line cut where a sentence ends: a stop, a space and a capital or an
opening quote or bracket. Not after a single letter ("z. B.", "d. h.") and
not after the number that opens a list item. The cut only decides what one
line of the diff is. The same rule runs on both sides, so a wrong cut shows
as two lines on each and never hides a change.

### units

```python
def units(text: str) -> list
```

The lines of a text, each cut into its sentences. A blank line is one
unit and the end of the text is one, so a change of paragraphs or of the
last newline is a change in the list.

### unified

```python
def unified(before: list, after: list, context: int = 2) -> list
```

The unified diff of two lists of units. Not `difflib.unified_diff`: its
matcher treats an item that repeats as junk once a list reaches 200
items, and blank lines repeat.

### pair

```python
def pair(before, after) -> str
```

One cell for a value that may have moved.

### status_of

```python
def status_of(before: Optional[dict], after: Optional[dict]) -> str
```

Whether a prompt is the same on both sides: its text, its parameters
and its sha256, which is what a stamp records.

### diff_text

```python
def diff_text(pid: str, before: Optional[dict], after: Optional[dict],
              names: tuple = ("before", "after")) -> str
```

The `.sentences.diff` of one prompt: the parameters that moved as
comment lines, then the sentences.

### read_ranges

```python
def read_ranges(path: Path) -> dict
```

The file `--check-domain` names, as {profile: {prompt: {"contract":
[(first, last)], "mixed": [...]}}}. A key it does not know is a mistake
that would leave a line unchecked, so it is refused.

### physical_lines

```python
def physical_lines(record: dict) -> list
```

[(line number in the file, text)] of a prompt, the front matter above
it counted. A text that is not the end of its file has no such numbers.

### check_domain

```python
def check_domain(old: dict, new: dict, contract: list, mixed: list) -> dict
```

The old lines outside the contract ranges against the new text.

A line passes when it stands in the new text exactly as written, apart
from a leading rule number and the whitespace at its ends. Contract lines
are not looked at: they are what the rewrite is meant to move. Mixed
lines are listed with the answer, for a person to decide.

### compare

```python
def compare(before: dict, after: dict) -> list
```

[(prompt id, status, before record, after record)], what a person looks
at first first.

### write_profile

```python
def write_profile(out: Path, name: str, rows: list, files: list,
                  labels: tuple) -> None
```

The files of one profile. A text is written as the loader gave it.

### read_sides

```python
def read_sides(root: Path, sha: str, profiles: list, scratch: Path) -> tuple
```

(HEAD, whether the working tree differs from it, {(side, profile): what
that side's own loader says}). All the reading is here: the commit is
unpacked and each side is probed in a process of its own.

### report

```python
def report(args, profiles: list, ranges: Optional[dict], sha: str, head: str,
           dirty: bool, sides: dict) -> tuple
```

(summary lines, the files to write per profile, number of problems) of
what the two sides say. Reads nothing and writes nothing.

### run

```python
def run(args) -> int
```

### main

```python
def main(argv: Optional[list] = None) -> int
```

[Back to the index](../README.md)
