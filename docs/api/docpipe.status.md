# docpipe.status

`docpipe/status.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

status.py: `docpipe status`, which stage left what for each document.

    docpipe status

One line per document and one column per stage `docpipe run` starts, an x
where that stage's output for the document is there, then how many documents
each stage has output for. A document is every name the corpus knows: a row
of the database, a PDF in the profile's folder, a directory in its processed
folder.

"There" is what the stage itself calls done, asked of the stage's own code
where it has a function for it and of its own file names where the rule is
the file:

  ingest      a Documents row for the file (what ingest skips)
  preprocess  pages.json and sections.json (what preprocessing resumes on)
  refine      sections_refined.json, and no unfinished pass beside it
  visuals     visuals.json, and every table and figure of its input in it
              with the markdown or description the stage looks for
  chunk       document.json not older than its inputs, and an embedding
              recorded in the database for a section, table or figure of it
              (which takes its Sections rows)
  lexical     a word index that is current and holds a passage of it

Nothing here writes. The database and the word index are opened for reading
only, and a stage that has not run (no database, no processed folder) is a
column of dashes, not an error.

Author: Felix Vossel

## Classes

### Report

```python
@dataclass
class Report
```

Fields:

- `profile: str`
- `root: Path`
- `database: Path`
- `documents: list = field(default_factory=list)`
- `there: dict = field(default_factory=dict)`: stage -> the documents it has output for
- `word_index: str = "missing"`: current, stale or missing: the word index belongs to the corpus

#### Report.count

```python
def count(self, stage: str) -> int
```

## Functions

### key_of

```python
def key_of(filename: str) -> str
```

The name a document's processed directory has: its file name without
the suffix, as chunking looks a directory up in the database.

### collect

```python
def collect(profile) -> Report
```

What each stage has left for each document of *profile*.

### render

```python
def render(report: Report) -> str
```

### main

```python
def main(rest: Sequence[str]) -> int
```

[Back to the index](../README.md)
