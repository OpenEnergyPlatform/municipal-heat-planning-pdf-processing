"""
found.py: Where the harvests before this run found something.

A run starts from nothing: it writes its anchors, takes the top of the ranking
once per document and once per pair, and reads the rest of the plan, although
the harvest before it says which passages carried anything. Of the 24,308
passages of corpus_m7_100, 7,229 gave a tuple.

`--start-at` begins at those. A found place is a passage a stored row stands
in, a stored row was refused in, or a coordinate of a stored row was read in.
Only the place is taken and never an answer, so it outlives a change of a
prompt, the ontology or the graph: the model reads the passage again and the
checks run as ever. The frame and the rows are read over these passages alone.
A coordinate is first asked where it was read last time for a row of the same
passage, and what is still open then is searched as in any run, so `unstated`
keeps its meaning.

A number in a passage no harvest found anything in stays unread. The stamp
says so (`PASS`): a run without `--start-at` harvests such a document again,
and `--top-up-open` reads the passages its trace did not ask.

A found place stands only for the questions that were asked when it was
found. A parameter no stored harvest of the document was asked (its stamp has
no `parameter/<uri>` key) has no places, and is searched over the whole plan
as in any run (owner decision 2026-11-03).

A document has no found places when no stamped harvest holds it, when nothing
was found in it, or when it no longer holds every place: then it is planned
as in any run.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import fields
from .remap import stamp_path_of
from .topup import read_harvest
from .topup_parameter import gained as never_asked

log = logging.getLogger(__name__)

# The sweep stage and the plan's origin of a found place.
STAGE = "found"
# The stamp's name for a harvest read at its found places.
PASS = "harvest-found"


@dataclass
class Kept:
    """The found places of one document, by key: (owner kind, owner id)."""
    passages: set = field(default_factory=set)
    read_at: dict = field(default_factory=dict)   # axis -> {row's passage:
    #                                                       {passages}}


def own_passage(row: dict):
    """The passage a harvest line stands in, or None."""
    if row.get("kind") == "refusal":
        return tuple(row["owner"]) if row.get("owner") else None
    provenance = row.get("provenance") or {}
    kind, owner = provenance.get("owner_kind"), provenance.get("owner_id")
    return (kind, owner) if kind and owner is not None else None


def places_of(rows, kept: Kept) -> None:
    """Enter the tuples and refusals of a stored harvest into *kept*."""
    for row in rows:
        own = own_passage(row)
        if own is None:
            continue
        kept.passages.add(own)
        claim = row.get("claim") or {} if row.get("kind") == "refusal" else row
        for key, where in claim.items():
            axis = key[:-len("_source")]
            if (key.endswith("_source") and isinstance(where, (list, tuple))
                    and len(where) == 2
                    and claim.get(f"{axis}_state") == fields.READ):
                place = tuple(where)
                kept.passages.add(place)
                kept.read_at.setdefault(axis, {}).setdefault(
                    own, set()).add(place)


class Found:
    """The found places of a run's documents.

    *harvests* are the directories they are read from, *name_of* gives a
    document's file stem and *passages_of* is (document, exclude) -> every
    passage of it. Only the keys are kept per document; the passages are read
    again from the run's shared store.
    """

    def __init__(self, harvests, name_of: Callable, passages_of: Callable):
        self.harvests = [Path(harvest) for harvest in harvests]
        self.name_of = name_of
        self.passages_of = passages_of
        self._kept: dict = {}

    def kept(self, document_id: int) -> Kept:
        got = self._kept.get(document_id)
        if got is None:
            got = self._kept.setdefault(document_id, self._read(document_id))
        return got

    def _read(self, document_id: int) -> Kept:
        kept = Kept()
        name = self.name_of(document_id)
        for harvest in self.harvests:
            path = harvest / f"{name}.jsonl"
            # A file no stamp vouches for may be half written.
            if path.is_file() and stamp_path_of(path).is_file():
                stored = read_harvest(path)
                places_of([*stored.tuples, *stored.refusals], kept)
        gone = kept.passages - self._keys(document_id)
        if gone:
            log.info("found: %s no longer holds %d of its %d place(s), planned "
                     "in full", name, len(gone), len(kept.passages))
            return Kept()
        return kept

    def gained(self, document_id: int, spec) -> list:
        """The uris of the parameters of *spec* that no stamped harvest of
        the document was asked. A stamp without per-parameter keys says
        nothing and yields none, as for `--top-up-parameters`."""
        name = self.name_of(document_id)
        new = None
        for harvest in self.harvests:
            stamp = stamp_path_of(harvest / f"{name}.jsonl")
            if stamp.is_file():
                got = set(never_asked(stamp, spec))
                new = got if new is None else new & got
        return [p.uri for p in spec.parameters if p.uri in (new or ())]

    def _keys(self, document_id: int) -> set:
        return {(s.owner_kind, s.owner_id)
                for s in self.passages_of(document_id, set())}

    def passages(self, document_id: int) -> list:
        """Every found place of the document, in document order."""
        kept = self.kept(document_id).passages
        if not kept:
            return []
        return [s for s in self.passages_of(document_id, set())
                if (s.owner_kind, s.owner_id) in kept]

    def read_at(self, document_id: int, axes) -> dict:
        """{a row's passage: [the passages *axes* were read in for a row of
        that passage]}."""
        kept = self.kept(document_id)
        wanted = [kept.read_at[axis] for axis in axes if axis in kept.read_at]
        if not wanted:
            return {}
        passage = {(s.owner_kind, s.owner_id): s
                   for s in self.passages_of(document_id, set())}
        places: dict = {}
        for rows in wanted:
            for own, keys in rows.items():
                places.setdefault(own, []).extend(passage[key] for key in keys
                                                  if key in passage)
        return places
