# docpipe.extraction.topup_rest

`docpipe/extraction/topup_rest.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

topup_rest.py: Reads the passages of a stored harvest that were never asked
for values, and appends what they hold.

A harvest asked the passages its searches kept, and on a long plan most
values stand below that cut: the rest was read only when a follow-up happened
to walk it (`runner.plan_batches`). This pass reads the rest of a document
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

## Classes

### RestPass

```python
class RestPass
```

`harvest_document(document_id, filename) -> (written, failures)` for
the run's own loop, with what it counted.

#### RestPass.\_\_init\_\_

```python
def __init__(self, out_dir: Path, deps: dict)
```

#### RestPass.report

```python
def report(self) -> None
```

## Functions

### owners_in

```python
def owners_in(lines) -> set
```

{(owner_kind, owner_id)} the rows requests among these trace lines were
shown.

### read_owners

```python
def read_owners(trace_path: Path) -> set
```

`owners_in` over a trace file; empty when there is none.

### read_to_end

```python
def read_to_end(stamp_path: Path) -> bool
```

Whether this pass has already read the document to its end.

### append_rest

```python
def append_rest(document_id: int, filename: str, out_dir: Path,
                deps: dict) -> tuple
```

(written, failures, stats) for one stored document.

`deps` holds what the run supplies: "plan" (`plan_batches` with the rest
reader bound), "harvest" (`harvest_batches` over the run's pools),
"locate", "frame_axes", "halted" and "fold" (`runner.fold_answers`),
"not_happened", "unserved" (`runner.UNSERVED.of`), "producer"
(`runner.producer`) and "model".

[Back to the index](../README.md)
