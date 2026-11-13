"""
shapemodel.py: The graph a writer produces, as the shapes it is held to say.

A serializer used to carry the shapes a second time: the paths it writes,
which of them may occur once, which must occur at all and what class sits at
the end of each. Copied by hand, every one of those drifted from the file it
was copied from, and a shapes file that moved on was only noticed in a
validation report nobody had to read.

Here the shapes the last refresh pulled are read when the writer is built,
and the writer asks them: which property of this class leads to nodes of
that class, or takes entries of that list, or values of that datatype; how
often may it occur, must it. A question with no answer, or with two, is a
`SchemaError` and never a default: a path the shapes no longer have stops
the writer before it produces a graph, which is what a renamed or dropped
property looks like from here.

What is read is what `docpipe.compile.shapes` reads: one record per
property shape with a single path. Several shapes on one class (a generated
file and a hand-written one beside it) are one set of constraints, and
several property shapes on one path are one slot with the tightest bounds.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from docpipe.compile import shapes as _shapes

XSD = "http://www.w3.org/2001/XMLSchema#"


class SchemaError(ValueError):
    """The shapes do not answer what a writer asks of them."""


@dataclass(frozen=True)
class Slot:
    """One property of a class, as every shape on that class constrains it."""
    path: str
    min_count: int = 0
    max_count: Optional[int] = None
    classes: tuple = ()
    choices: tuple = ()
    datatype: Optional[str] = None

    @property
    def required(self) -> bool:
        return self.min_count >= 1

    @property
    def single(self) -> bool:
        return self.max_count == 1


def _merge(path: str, records: list) -> Slot:
    mins = [r.min_count for r in records if r.min_count is not None]
    maxes = [r.max_count for r in records if r.max_count is not None]
    classes, choices = [], []
    for record in records:
        classes += [c for c in record.classes if c not in classes]
        choices += [c for c in record.choices if c not in choices]
    datatype = next((r.datatype for r in records if r.datatype), None)
    return Slot(path=path, min_count=max(mins) if mins else 0,
                max_count=min(maxes) if maxes else None,
                classes=tuple(classes), choices=tuple(choices),
                datatype=datatype)


class Model:
    """What the shapes say about each class they target.

    *ancestors* gives the classes above a class, nearest first, as full
    IRIs. A class no shape targets is held to the nearest one above it that
    a shape does target, so a CO2 emission value finds the shape of the
    greenhouse gas emission value it is one of.
    """

    def __init__(self, shapes: list,
                 ancestors: Optional[Callable[[str], Iterable[str]]] = None):
        records: dict = {}
        for shape in shapes:
            if shape.target_class:
                bucket = records.setdefault(shape.target_class, {})
                for prop in shape.properties:
                    bucket.setdefault(prop.path, []).append(prop)
        self._slots = {cls: {path: _merge(path, found)
                             for path, found in by_path.items()}
                       for cls, by_path in records.items()}
        self._ancestors = ancestors or (lambda iri: ())

    @classmethod
    def load(cls, paths, ancestors=None) -> "Model":
        """From shapes files on disk."""
        found, _prefixes = _shapes.read(paths)
        return cls(found, ancestors)

    @classmethod
    def from_graph(cls, graph, ancestors=None) -> "Model":
        """From shapes already parsed into an rdflib graph."""
        return cls(_shapes.shapes_of(graph), ancestors)

    @classmethod
    def parse(cls, *texts: str, ancestors=None) -> "Model":
        """From Turtle text, one or several files' worth."""
        from rdflib import Graph
        graph = Graph(bind_namespaces="none")
        for text in texts:
            graph.parse(data=text, format="turtle")
        return cls.from_graph(graph, ancestors)

    def classes(self) -> list:
        return sorted(self._slots)

    def shaped(self, cls: str) -> Optional[str]:
        """*cls* if a shape targets it, else the nearest class above it one
        does, else None."""
        if cls in self._slots:
            return cls
        for above in self._ancestors(cls):
            if above in self._slots:
                return above
        return None

    def slots(self, cls: str) -> dict:
        """{path: Slot} of the shape *cls* is held to; empty without one."""
        return dict(self._slots.get(self.shaped(cls) or "", {}))

    def has(self, cls: str, path: str) -> bool:
        return path in self.slots(cls)

    def _reaches(self, slot: Slot, target: str) -> bool:
        return target in slot.classes or any(
            above in slot.classes for above in self._ancestors(target))

    def slot(self, cls: str, *, path: Optional[str] = None,
             to_class: Optional[str] = None, members: Iterable = (),
             datatype: Optional[str] = None) -> Slot:
        """The one property of *cls* that answers the question.

        By its path; by the class at its end (*to_class* or a class above
        it); by the entries of its list (the slot whose sh:in holds the most
        of *members*); by its datatype. Several criteria narrow together.
        """
        shaped = self.shaped(cls)
        if shaped is None:
            raise SchemaError(f"no shape targets {cls} or a class above it")
        found = list(self._slots[shaped].values())
        asked = []
        if path is not None:
            asked.append(f"path {path}")
            found = [s for s in found if s.path == path]
        if to_class is not None:
            asked.append(f"objects of class {to_class}")
            found = [s for s in found if self._reaches(s, to_class)]
        if datatype is not None:
            asked.append(f"datatype {datatype}")
            found = [s for s in found if s.datatype == datatype]
        wanted = set(members or ())
        if wanted:
            asked.append(f"entries like {sorted(wanted)[:3]}")
            overlap = {s.path: len(wanted & set(s.choices)) for s in found}
            best = max(overlap.values(), default=0)
            found = [s for s in found if best and overlap[s.path] == best]
        where = f"the shape of {shaped}" + (
            f" (held to for {cls})" if shaped != cls else "")
        if not found:
            raise SchemaError(f"{where} has no property with "
                              f"{' and '.join(asked) or 'anything'}")
        if len(found) > 1:
            raise SchemaError(f"{where} has {len(found)} properties with "
                              f"{' and '.join(asked)}: "
                              f"{', '.join(s.path for s in found)}")
        return found[0]


def snapshot_ancestors(snapshot: dict, base: str) -> Callable:
    """`ancestors` over a vocabulary snapshot, nearest first, as IRIs.

    The snapshot names terms by their bare id and its parents the same way;
    *base* is the namespace a bare id stands in.
    """
    terms = snapshot.get("terms") or {}

    def ancestors(iri: str) -> list:
        start = iri[len(base):] if iri.startswith(base) else iri
        out, seen, queue = [], {start}, [start]
        while queue:
            for parent in (terms.get(queue.pop(0)) or {}).get("parents") or ():
                if parent not in seen:
                    seen.add(parent)
                    queue.append(parent)
                    out.append(parent if "://" in parent else base + parent)
        return out

    return ancestors
