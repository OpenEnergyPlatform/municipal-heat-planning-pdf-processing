# docpipe.extraction.remap

`docpipe/extraction/remap.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

remap.py: Re-resolves a moved or grown vocabulary against a harvest already on
disk.

The resume stamp used to hold one hash over the whole spec file, so a single
new spelling of a term made all 1,082 documents stale at once, about 93 GPU
hours to re-read a corpus over one word. The ontology a spec is written against
keeps moving, so that cost would recur.

None of those hours actually re-read anything. The harvest keeps both halves of
every coordinate, the class in `<axis>` and the document's own wording in
`<axis>_raw`, so that mapping one onto the other is a pure function of the
files on disk. A new alias, a renamed label, or an option moved to another
class is answered by running that function again, with no model, no GPU, and no
index.

Four cases stop the pass from settling a coordinate, and each is counted rather
than silently dropped. No wording: the model never sent `<axis>_raw`, so there
is nothing to map from and only the stored URI survives; the coordinate stays
open for a targeted top-up. Not listed: the wording is in neither the old list
nor the new one, so the model's own reading stands rather than being
overwritten with an empty cell. A refusal: a claim refused on this axis may map
once the list has grown, but only a re-harvest can turn it into a tuple. No
parameter: a row names a parameter the spec no longer has, so the pass leaves
it untouched and does not vouch for the document.

The stamp is carried forward only for what the pass could account for. An
answer space fully re-mapped in a document, `axis/<uri>/<name>` or
`value/<uri>` for a category parameter's own list, is written forward; every
other key keeps what the stamp already said. A document whose carrier list
moved and whose carrier wordings all resolved therefore comes out current,
while one with a wording nobody listed stays stale in that one key and nothing
else.

Author: Felix Vossel

## Functions

### spaces_of

```python
def spaces_of(current: dict) -> set
```

### remap_row

```python
def remap_row(row: dict, parameter) -> tuple
```

Re-map one tuple's coordinates. Returns (counts, spaces left open).

Mutates `row`. The second element names the answer spaces this row could
not settle, so the caller knows which stamp keys it may not write forward.

### refused_spaces

```python
def refused_spaces(refusals: list, spaces: set) -> set
```

Answer spaces a refusal of this document may depend on.

A claim refused because its wording was in no vocabulary can become a
tuple once the list grows, and only a re-harvest can do that. Marking the
space current would hide exactly the value the new option was added for.
A refusal that cannot be attributed unsettles everything: guessing which
space it belonged to would be the same mistake in a smaller place.

### stamp_forward

```python
def stamp_forward(stamp_path: Path, current: dict, settled: set) -> bool
```

Write the stamp keys this pass earned; keep the rest. True if it wrote.

Everything outside `settled` stays exactly as the old stamp had it, so a
run that comes later still sees which question it has to redo.

### stamp_path_of

```python
def stamp_path_of(path: Path) -> Path
```

### remap_file

```python
def remap_file(path: Path, spec: Spec, current: dict) -> Counter
```

Re-map one harvest file in place, then carry its stamp forward.

### run

```python
def run(harvest_dir: Path, spec: Spec, current: dict) -> Counter
```

Re-map a whole harvest directory against the spec as it reads today.

`current` is the stamp this run would write, so the pass can carry the
keys it earned forward without knowing how a stamp is assembled.

[Back to the index](../README.md)
