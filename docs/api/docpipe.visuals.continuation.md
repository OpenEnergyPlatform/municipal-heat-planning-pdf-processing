# docpipe.visuals.continuation

`docpipe/visuals/continuation.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

continuation.py: A table the layout cut in parts, and its parts joined to
their start (owner decision 2026-11-06).

A table that runs over a page break, or that the layout cut within a page,
came out of the transcription as parts, each with a caption and a head of its
own, invented where the part prints none: the parts of a table of municipal
buildings on three pages got a column "Kosten" and a unit no page prints. Now
the transcription of a table that may continue the table before it is shown
that table's caption and head and what stands between the two; the model says
whether it continues that table and, where it does, writes its rows under
that head and gives no caption. The merge before the database joins each such
part to the table it continues: one table, its parts' pages, crops and frames
kept beside it.

A table may continue the table right before it in reading order when that
table stands on its page or the page before and has a transcribed head.
Whatever stands between them (a heading, a page footer, a caption, a
paragraph, a figure) is shown to the model, which decides (owner decision
2026-11-07: also after a heading). The reading picks the same
tables by the same rule (`docpipe.extraction.lookup.continued`).

Author: Felix Vossel

## Functions

### is_rule

```python
def is_rule(line: str) -> bool
```

Is *line* the rule under a Markdown table's head ("| --- | --- |")?
The test `docpipe.extraction.lookup.head_of` closes a head with.

### head_lines

```python
def head_lines(markdown: Optional[str]) -> str
```

A transcribed table's head: its lines down to the rule, the rule
included, where a row of cells stands above the rule; "" where it has
none. A head as `docpipe.extraction.lookup.head_of` takes one.

### body_rows

```python
def body_rows(markdown: Optional[str]) -> list
```

The rows of a transcribed table under its head: its lines after the
rule, else all of them.

### links

```python
def links(sections: list) -> dict
```

{table id: {"after": the id of the table before it, "between": the
text between them}} for each table whose page lets it continue the table
right before it (see the module; whether that table has a head is known
once it is transcribed, `transcribe_run`); "" where nothing stands
between them.

### runs

```python
def runs(sections: list, found: dict) -> list
```

The tables of a document in reading order, in runs: a table that may
continue the one before it (*found*, `links`) is in that table's run.
Each run as [(section index, table index)], for a stage that asks a
run's tables in their order.

### before_of

```python
def before_of(start: dict, link: dict) -> dict
```

What the request of a table that may continue *start* is shown of it:
the id of the table right before it (*link*), *start*'s caption and head,
and what stands between them.

### transcribe_run

```python
def transcribe_run(items: list, found: dict, cached: dict,
                   transcribe: Callable) -> list
```

The tables of one run (`runs`) in their order, each transcribed or
taken from *cached* (by id): [result].

*transcribe(item, before)* is one request; *before* is what it is shown
of the table the item may continue (`before_of`), None for a table asked
on its own. The table a run starts with is shown to each later one until
one of them does not continue it, which is then shown to those after it;
one without a transcribed head (`head_lines`) is shown to none. A cached
table stands, unless it may continue a table that has a transcribed head
and was not asked against the table right before it (a transcription
from before this was asked, or of another table).

### join

```python
def join(sections: list) -> int
```

Each table the transcription found to continue the table before it
("continues", "after"), joined in place to the table its run started
with: its rows under that table's rows, and its id, page, crop, frame and
check in that table's "parts"; it leaves its section. A part whose start
has no transcription, or that has none itself, stays a table of its own.
Returns how many parts were joined.

[Back to the index](../README.md)
