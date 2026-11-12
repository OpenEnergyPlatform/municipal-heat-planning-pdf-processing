# docpipe.extraction.topup_rest

`docpipe/extraction/topup_rest.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

topup_rest.py: Reads the passages of a stored harvest that were never asked
for values, and appends what they hold.

A harvest asked the passages its searches kept, and on a long plan most
values stand below that cut: the rest was read only when a follow-up happened
to walk it. This pass reads the rest of a document
that was harvested before the rest was read, without harvesting it again.

Which passages were asked is in the harvest's trace: every `rows` event names
its sources. Those are left out, everything else of the document is read
under the pair it prints, with the pairs the stored rows carry and under the
index they carry them, and the rows it finds are asked every coordinate as in
the harvest. They follow the stored lines, which stay as they are, and a row
equal to a stored tuple is not written again.

A document without a trace is skipped and counted: what it read cannot be
told, and reading all of it again is the harvest's job. A document this pass
has read to its end says so in its stamp's list of producers and is not read
again; its own trace goes beside the harvest's (`TRACE_DIR`), since a trace is
truncated by the next pass that writes it.

Author: Felix Vossel

## Functions

### owners_in

```python
def owners_in(events) -> set
```

{(owner_kind, owner_id)} the rows requests among these trace events
were shown.

### read_owners

```python
def read_owners(directory: Path, name: str) -> set
```

`owners_in` over the trace of *name* in *directory*, read for its rows
requests alone; empty when there is none.

### skips_unknown_reading

```python
def skips_unknown_reading() -> bool
```

Whether a document whose earlier readings cannot be told (no record,
no survey) is skipped and not read whole (rule
`rest_without_trace`).

### done_to_end

```python
def done_to_end(stamp_path: Path) -> bool
```

Whether the pass for the rest of the plan reads the document no more
because it has read it to its end (rule `rest_once_per_document`).

### read_to_end

```python
def read_to_end(stamp_path: Path) -> bool
```

Whether this pass has already read the document to its end.

[Back to the index](../README.md)
