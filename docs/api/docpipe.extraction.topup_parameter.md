# docpipe.extraction.topup_parameter

`docpipe/extraction/topup_parameter.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

topup_parameter.py: Appends the rows of a parameter the spec has gained to a
harvest that is already on disk, instead of harvesting the document again.

A parameter added to the spec leaves every stored document without that
parameter's key in its stamp, and the resume can only answer that by reading
the whole document again. What the new parameter needs is smaller: the
document searched for it, one rows request that offers it and nothing else,
and the coordinates of the rows that request produced. The old parameters'
rows, and the coordinate sweeps that took most of the first run, are not
asked again.

The stamp is what says the pass may be taken: the key `parameter/<uri>` is
absent for the new parameter and nothing else moved but what the addition
moves (`addition`). A reworded, renamed or removed parameter, a grown value
list or a moved question is not an addition and the document stays stale as a
whole, as it does for every such change; so does a document whose stored rows
were decided under another derivation of their parameter because of the new
one (`derivation_moved`).

What the pass writes is kept apart from what was there. Every stored line goes
back as the same bytes in the same order, and the new tuples, refusals and one
`parameter_state` line per new parameter follow, with a summary that describes
the file as it now stands. The summary says nothing new about the refusals of
the first pass: they are not revisited, and the pass says so in its log.
Nothing stored ever becomes a `Row`, so no request can touch it.

A pass that did not read the parameter completely writes nothing, neither the
file nor the stamp, and its document counts as failed: an appended half
reading and its state line would be indistinguishable from a finished one, and
the stamp would then vouch for it. The one window the pass has is between the
file and the stamp; a file that already holds the state line of every new
parameter gets its stamp and no request (`applied`).

The checks are the harvest's own, because the rows go through the harvest's
own fold (`runner.fold_answers`): the quote stands in a shown passage, the
answer stands in the quote, and the quote has its minimum length. This module
decides no value and refuses none.

Author: Felix Vossel

## Classes

### Addition

```python
@dataclass
class Addition
```

What a stored stamp says about the parameters the spec gained.

`owned` are the keys of the new parameters, stored or current: the pass
answers for them. `shared` are the keys of the questions that belong to no
parameter and that the addition alone moved: the pass answers for them
with the rest. `unexplained` is every other key the stamp and the spec
still differ in. An empty list is "nothing but the addition moved".

Fields:

- `stored: dict`
- `new: list = field(default_factory=list)`
- `owned: set = field(default_factory=set)`
- `shared: set = field(default_factory=set)`
- `unexplained: list = field(default_factory=list)`

#### Addition.explained

```python
@property
def explained(self) -> set
```

### Verdict

```python
@dataclass
class Verdict
```

What the pass does with one stored document.

`kind` is one of: "none" (no new parameter), "blocked" (the document
stays stale as a whole, not a failure), "failed" (the pass cannot be
taken and the run says so in its exit code), "applied" (the file already
holds every new parameter's state line, only the stamp is missing) and
"new" (read the document for the new parameters).

Fields:

- `kind: str`
- `why: str = ""`
- `new: list = field(default_factory=list)`
- `owned: set = field(default_factory=set)`
- `shared: set = field(default_factory=set)`
- `stored: object = None`: the harvest file, read, when it was needed

### DocumentPass

```python
class DocumentPass
```

`harvest_document(document_id, filename) -> (written, failures)` for the
run's own loop (`runner.harvest_documents`), with what it counted.

The loop calls it from several threads, one document each; the counts are
added under a lock.

#### DocumentPass.\_\_init\_\_

```python
def __init__(self, out_dir: Path, spec: Spec, current: dict, deps: dict)
```

#### DocumentPass.report

```python
def report(self) -> None
```

One line per count, each with what it counts.

## Functions

### owned_keys

```python
def owned_keys(uri: str, keys) -> set
```

The stamp keys of one parameter among *keys*: its own, its list and
every one of its axes.

### without

```python
def without(spec: Spec, new) -> Spec
```

The spec as it read before these parameters were added.

### addition

```python
def addition(stamp_path: Path, current: dict, spec: Spec) -> tuple
```

(Addition or None, why it could not be told).

New is told from reworded by the stamp keys alone: a parameter whose
`parameter/<uri>` the stored stamp has never seen is new, one whose key is
there and differs is reworded, and that is the whole difference. Stored
`axis/<uri>/..` and `value/<uri>` keys of a parameter are ignored for it
on purpose: `--remap` writes them for every parameter of the spec, read
or not, so they say nothing about whether anybody read the parameter.

None when the stamp cannot vouch for anything: it is not there or not
readable (`stale` returns every key of the run for it, and every
parameter would look new), or it predates the per-parameter keys.

### gained

```python
def gained(stamp_path: Path, spec: Spec) -> list
```

The uris of the parameters of *spec* a stored stamp has never seen.

Only a stamp that carries per-parameter keys can say so: one that
predates them, or none at all, says nothing and yields none.

### explained_keys

```python
def explained_keys(stamp_path: Path, current: dict, spec: Spec) -> set
```

The keys of *current* that only the parameters the spec gained moved.

What a pass for coordinates (`topup.top_up_file`) takes out of its list
before it asks what blocks it: these are this pass's to answer, and it
writes none of them.

### derivation_moved

```python
def derivation_moved(spec: Spec, new, tuples: list) -> bool
```

Did the new parameters change which parameter a stored row derives to?

A numeric parameter that shares a unit with a stored one leaves a unit two
parameters accept, and a second text parameter leaves a wording two
parameters could hold (`fields.derive_parameter`). The stored rows were
decided without it. The rows of the new parameters are not asked: they are
this pass's own.

### classify

```python
def classify(stamp_path: Path, current: dict, spec: Spec, harvest_path: Path,
             *, doc_spec_of: Callable, frame_names=(),
             dynamic_ok: bool = True) -> Verdict
```

The verdict for one stored document, by the rules in this order.

A document with no stamp, or one that predates the per-parameter keys, is
blocked. One with no new parameter has nothing to append. Then what the
document is asked through has to be what it was, apart from the
addition: a key that is not a coordinate of an old parameter blocks
(`topup.actionable`, the rule the coordinate pass uses), and a key that
is one is left to that pass and never written by this one. The marker of
an earlier pass of this one comes before the derivation, because the
rows it appended are not rows decided under the old one.

The harvest file is read, and *doc_spec_of* closes the document's lists,
only when a rule needs them, so a corpus with nothing to append reads
nothing but its stamps. A verdict that goes on to read the document
carries the file it read.

### drop_stored_repeats

```python
def drop_stored_repeats(rows: list, stored: list) -> tuple
```

(rows that are new, how many were a stored tuple again).

A row equal to a stored tuple in everything but its provenance, whatever
its parameter, is that tuple and is not written a second time. Not a
check on a value: it says nothing the stored one did not. Stored tuples
are never compared with each other and none is removed, so a file that
already holds a repeat keeps both. A stored row carries `kind` and a
report row does not, and who read a coordinate says nothing about what was
read: both are left out of the key, or no repeat would ever be found.

### point

```python
def point(row: dict, position: Optional[int]) -> None
```

Say that this pass wrote every coordinate of this row: each
`<axis>_producer` is the position of its entry in the stamp's list.

### appended_lines

```python
def appended_lines(stored, document_id, rows: list, refusals: list,
                   states: list) -> list
```

The file as it stands after the pass: every stored line as it was,
then the new tuples, refusals and parameter states, the summary last.

The stored tuples are not dumped again, they are the strings they were,
so no key moves, no number is spelled another way and no character is
escaped. Only the old summary is replaced.

### not_read

```python
def not_read(cause: str, found: int, of: int) -> str
```

What `runner.not_happened` counted, said in the unit it counted.

### append_document

```python
def append_document(document_id: int, filename: str, out_dir: Path,
                    spec: Spec, current: dict, deps: dict) -> tuple
```

(written, failures, stats) for one stored document.

`deps` is what the run supplies: "document_spec" (id -> this document's
spec, None when a list it closes cannot be), "plan" (the run's
`plan_batches`, everything but the document bound), "harvest" (the run's
`harvest_batches` over its pools, everything but the batches and the
unfinished set bound), "questions" (name -> the sentences this document
was searched with, taken), "locate", "frame_axes", "frame_names",
"dynamic_ok" and "halted".

Nothing is written unless the new parameters were read: a document the
server did not serve, a frame or a plan that raised, or one the run halted
in leaves the file and the stamp as they were.

### with_harvest

```python
def with_harvest(documents: list, out_dir: Path) -> tuple
```

(the documents that have a harvest file, how many have none).

A document nobody has harvested has nothing to append to; the harvest
itself reads it, with every parameter.

[Back to the index](../README.md)
