"""
mhpkg.py: The MHPKG data shape this profile's graph is written in.

The shape is not mirrored here. It is the LinkML schema the OEKG repository
publishes (`mhpkg/schema/mhpkg_target_scenario.yaml`), pulled by every
`vocabulary --refresh` at its current version and kept beside the profile as
`mhpkg_schema.yaml`, so a machine without network reads the schema the last
run read. kg.py takes from it every predicate, every class and every closed
list, and the spec names schema slots instead of predicates
(`"schema_slot": "refers_to_energy_carrier"`, `resolve`).

The schema is a draft with open term requests: some of its slot_uris are not
yet in the pinned OEO or MHPO. They are written as the schema says and
counted (`missing_terms`), never a reason to stop a run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "mhpkg_schema.yaml"
# Where the refresh finds the schema in the OEKG repository.
SCHEMA_FILE = "mhpkg/schema/mhpkg_target_scenario.yaml"


class Shape:
    """One parsed schema: slots, classes, enums, prefixes."""

    def __init__(self, raw: dict):
        self.raw = raw or {}
        self.prefixes = {name: (iri if isinstance(iri, str)
                                else (iri or {}).get("prefix_reference"))
                         for name, iri in (self.raw.get("prefixes") or {}).items()}
        self.slots = self.raw.get("slots") or {}
        self.classes = self.raw.get("classes") or {}
        self.enums = self.raw.get("enums") or {}

    def slot(self, name: str) -> str:
        """The slot's predicate as a curie, `oeo:OEO_00370001`."""
        uri = (self.slots.get(name) or {}).get("slot_uri")
        if not uri:
            raise KeyError(f"the MHPKG schema has no slot {name!r} with a "
                           f"slot_uri")
        return uri

    def cls(self, name: str) -> str:
        """The class's curie, `mhpo:MHPO_00020007`."""
        uri = (self.classes.get(name) or {}).get("class_uri")
        if not uri:
            raise KeyError(f"the MHPKG schema has no class {name!r}")
        return uri

    def class_named(self, curie: str) -> Optional[str]:
        """The schema class whose class_uri is *curie*, or None."""
        for name, block in self.classes.items():
            if (block or {}).get("class_uri") == curie:
                return name
        return None

    def usage(self, cls: str, slot: str) -> dict:
        """The slot as this class uses it: its own block, the class's
        slot_usage over it."""
        block = dict(self.slots.get(slot) or {})
        block.update(((self.classes.get(cls) or {}).get("slot_usage") or {})
                     .get(slot) or {})
        return block

    def has_slot(self, cls: str, slot: str) -> bool:
        return slot in ((self.classes.get(cls) or {}).get("slots") or ())

    def required(self, cls: str) -> set:
        """The slots an instance of *cls* must carry."""
        return {slot for slot in ((self.classes.get(cls) or {}).get("slots")
                                  or ())
                if self.usage(cls, slot).get("required")}

    def ranges(self, cls: str, slot: str) -> list:
        """The ranges the slot takes on *cls*: its any_of, else its range."""
        block = self.usage(cls, slot)
        named = [part.get("range") for part in block.get("any_of") or ()
                 if isinstance(part, dict) and part.get("range")]
        return named or ([block["range"]] if block.get("range") else [])

    def enum(self, name: str) -> set:
        """The curies an enum admits (its `meaning`s)."""
        values = (self.enums.get(name) or {}).get("permissible_values") or {}
        return {(v or {}).get("meaning") for v in values.values()
                if (v or {}).get("meaning")}

    def admits(self, cls: str, slot: str, curie: str) -> bool:
        """Does *cls* take *curie* in *slot*? True for a slot whose range is
        no enum: the schema then closes nothing."""
        enums = [r for r in self.ranges(cls, slot) if r in self.enums]
        return not enums or any(curie in self.enum(e) for e in enums)

    def value_classes(self, container: str, slot: str) -> list:
        """The classes a container takes under *slot*."""
        return [r for r in self.ranges(container, slot) if r in self.classes]

    def curies(self) -> set:
        """Every class and predicate curie the schema names."""
        out = {b.get("slot_uri") for b in self.slots.values() if b}
        out |= {b.get("class_uri") for b in self.classes.values() if b}
        for name in self.enums:
            out |= self.enum(name)
        return {c for c in out if c}


_SHAPE: list = []


def load(path: Path = SCHEMA_PATH) -> Shape:
    """The schema the last refresh pulled, parsed once per process."""
    if path == SCHEMA_PATH and _SHAPE:
        return _SHAPE[0]
    if not Path(path).is_file():
        raise FileNotFoundError(
            f"{path} missing: `python -m profiles.kwp.vocabulary --refresh` "
            f"pulls the MHPKG schema")
    shape = Shape(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    if path == SCHEMA_PATH:
        _SHAPE[:] = [shape]
    return shape


def resolve(spec_raw: dict, shape: Shape) -> dict:
    """A copy of the spec whose `schema_slot` and `schema_class` entries carry
    the predicate and class the schema gives them, in the spec's own grammar
    (`prefix` + `predicate`, bare `class`), so every reader of the `kg`
    blocks reads the schema's terms without knowing it."""
    import copy

    def fill(block):
        if isinstance(block, dict):
            for key, value in list(block.items()):
                fill(value)
            slot = block.get("schema_slot")
            if slot:
                prefix, _, local = shape.slot(slot).partition(":")
                block["prefix"], block["predicate"] = prefix, local
            cls = block.get("schema_class")
            if cls:
                block["class"] = shape.cls(cls).partition(":")[2]
        elif isinstance(block, list):
            for item in block:
                fill(item)
        return block

    return fill(copy.deepcopy(spec_raw))


def missing_terms(shape: Shape, terms: dict) -> list:
    """The schema's oeo/mhpo curies the pinned snapshot does not know: its
    open term requests, counted where a run reports them."""
    out = []
    for curie in sorted(shape.curies()):
        prefix, _, local = curie.partition(":")
        if prefix in ("oeo", "mhpo") and local not in terms:
            out.append(curie)
    return out
