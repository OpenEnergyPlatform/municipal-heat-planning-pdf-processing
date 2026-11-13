# profiles.kwp.mhpkg

`profiles/kwp/mhpkg.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

mhpkg.py: The MHPKG data shape this profile's graph is written in.

The shape is not mirrored here. It is the LinkML schema the OEKG repository
publishes (`mhpkg/schema/mhpkg_target_scenario.yaml`), pulled by every
`vocabulary --refresh` at its current version and kept beside the profile as
`mhpkg_schema.yaml`, so a machine without network reads the schema the last
run read. kg.py takes from it every predicate, every class and every closed
list.

The schema is a draft with open term requests: some of its slot_uris are not
yet in the pinned OEO or MHPO. They are written as the schema says and
counted (`missing_terms`), never a reason to stop a run.

## Classes

### Shape

```python
class Shape
```

One parsed schema: slots, classes, enums, prefixes.

#### Shape.\_\_init\_\_

```python
def __init__(self, raw: dict)
```

#### Shape.slot

```python
def slot(self, name: str) -> str
```

The slot's predicate as a curie, `oeo:OEO_00370001`.

#### Shape.cls

```python
def cls(self, name: str) -> str
```

The class's curie, `mhpo:MHPO_00020007`.

#### Shape.class_named

```python
def class_named(self, curie: str) -> Optional[str]
```

The schema class whose class_uri is *curie*, or None.

#### Shape.usage

```python
def usage(self, cls: str, slot: str) -> dict
```

The slot as this class uses it: its own block, the class's
slot_usage over it.

#### Shape.has_slot

```python
def has_slot(self, cls: str, slot: str) -> bool
```

#### Shape.required

```python
def required(self, cls: str) -> set
```

The slots an instance of *cls* must carry.

#### Shape.ranges

```python
def ranges(self, cls: str, slot: str) -> list
```

The ranges the slot takes on *cls*: its any_of, else its range.

#### Shape.enum

```python
def enum(self, name: str) -> set
```

The curies an enum admits (its `meaning`s).

#### Shape.admits

```python
def admits(self, cls: str, slot: str, curie: str) -> bool
```

Does *cls* take *curie* in *slot*? True for a slot whose range is
no enum: the schema then closes nothing.

#### Shape.value_classes

```python
def value_classes(self, container: str, slot: str) -> list
```

The classes a container takes under *slot*.

#### Shape.curies

```python
def curies(self) -> set
```

Every class and predicate curie the schema names.

## Functions

### load

```python
def load(path: Path = SCHEMA_PATH) -> Shape
```

The schema the last refresh pulled, parsed once per process.

### missing_terms

```python
def missing_terms(shape: Shape, terms: dict) -> list
```

The schema's oeo/mhpo curies the pinned snapshot does not know: its
open term requests, counted where a run reports them.

[Back to the index](../README.md)
