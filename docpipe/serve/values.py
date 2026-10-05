"""
values.py: The harvested values of a corpus, as something that can be asked.

A harvest is one JSONL file per document, written for the run that made it.
Whoever wants a number out of it (a table, another program, an assistant,
the chat) wants the same few things: which documents, which parameters,
the values that match, and for each one what backs it. This module is that
one reading of a harvest, and the export, the HTTP API, the MCP server and
the chat all answer from it, so they cannot say different things.

A value is served as the harvest holds it, with what the harvest knows
about it and nothing added:

    id            its name (`identity.tuple_ids`): the document, the quote
                  and the value as written. The same after a new build of
                  the database and after a new harvest that reads the same.
    value, unit   as read, and converted into the parameter's unit where
                  the harvest did that
    coordinates   each with what was read, the wording it was read from and
                  how the reading ended (`fields.py`)
    quote, page   the words of the document the value stands in, and where
    level         A, B or C with the reasons (`trust.py`)

Nothing is filtered: a value of level C is served like one of level A, and
says that it is one. Leaving a level out is the asker's decision
(`level="B"` asks for B and better).

Author: Felix Vossel
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from ..extraction import identity, trust
from ..extraction.gold import coordinates as coordinate_names
from ..extraction.gold import same

LEVELS = (trust.LEVEL_A, trust.LEVEL_B, trust.LEVEL_C)
MAX_LIMIT = 1000


def _same_number(left: dict, right: dict) -> bool:
    """Whether two rows state the same number. Held in the unit the
    parameter is kept in where both were converted to it: 241 GWh and
    241000 MWh are one reading, written twice."""
    here, there = left.get("value_target"), right.get("value_target")
    if here is not None and there is not None:
        return same(here, there)
    return same(left.get("value"), right.get("value")) \
        and same(left.get("unit"), right.get("unit"))


def _text(content) -> str:
    return " ".join(str(content).split()).casefold()


class Values:
    """Every accepted value of a harvest."""

    def __init__(self, rows_by_document: dict, *, spec=None,
                 transcribed: Iterable[str] = ()):
        self.spec = spec
        self.transcribed = set(transcribed)
        self._values: list = []
        self._by_id: dict = {}
        for document in sorted(rows_by_document):
            rows = rows_by_document[document]
            contested = self._contested(rows)
            for name, row in zip(identity.tuple_ids(document, rows), rows):
                value = self._value(document, name, row,
                                    conflict=id(row) in contested)
                self._values.append(value)
                self._by_id[name] = value

    @classmethod
    def load(cls, harvest_dir, *, spec=None, db=None) -> "Values":
        from ..extraction.serialize import collect
        harvest_dir = Path(harvest_dir)
        if not harvest_dir.is_dir():
            raise FileNotFoundError(f"{harvest_dir} is not a directory")
        return cls(collect(harvest_dir), spec=spec,
                   transcribed=trust.transcribed_documents(db))

    # ------------------------------------------------------------ one value

    @staticmethod
    def _contested(rows: list) -> set:
        """The rows of one document that claim the same thing with another
        number: the same parameter and the same coordinates."""
        claims: dict = {}
        for row in rows:
            key = (row.get("parameter"),
                   tuple((name, _text(row.get(name)))
                         for name in coordinate_names(row)))
            claims.setdefault(key, []).append(row)
        contested = set()
        for claimants in claims.values():
            first = claimants[0]
            if any(not _same_number(row, first) for row in claimants[1:]):
                contested.update(id(row) for row in claimants)
        return contested

    def _parameter(self, uri):
        return self.spec.by_uri.get(uri) if self.spec is not None else None

    def _label_of(self, vocabulary: Optional[dict], content):
        """The first spelling the spec lists for a chosen entry."""
        if not isinstance(vocabulary, dict) or not isinstance(content, str):
            return None
        spellings = vocabulary.get(content)
        if isinstance(spellings, (list, tuple)) and spellings:
            return spellings[0]
        return None

    def _value(self, document: str, name: str, row: dict, *,
               conflict: bool) -> dict:
        parameter = self._parameter(row.get("parameter"))
        verdict = trust.trust(row, conflict=conflict,
                              transcribed=document in self.transcribed)
        coordinates = {}
        for axis_name in coordinate_names(row):
            axis = (parameter.axes or {}).get(axis_name) \
                if parameter is not None else None
            entry = {"value": row.get(axis_name),
                     "state": row.get(f"{axis_name}_state")}
            raw = row.get(f"{axis_name}_raw")
            if raw not in (None, ""):
                entry["wording"] = raw
            label = self._label_of(getattr(axis, "vocabulary", None),
                                   row.get(axis_name))
            if label:
                entry["label"] = label
            coordinates[axis_name] = entry
        provenance = row.get("provenance") or {}
        value = {
            "id": name,
            "document": document,
            "parameter": row.get("parameter"),
            "label": parameter.label if parameter is not None else None,
            "value": row.get("value"),
            "unit": row.get("unit"),
            "coordinates": coordinates,
            "quote": row.get("quote"),
            "page": provenance.get("page"),
            "source": {key: provenance.get(key) for key in
                       ("owner_kind", "owner_id", "title", "section_number",
                        "section_title", "image")
                       if provenance.get(key) not in (None, "")},
            "level": verdict["level"],
            "reasons": verdict["reasons"],
            "from_image": verdict["image_origin"],
        }
        for key in ("value_raw", "unit_raw", "value_target"):
            if row.get(key) not in (None, ""):
                value[key] = row[key]
        if parameter is not None and row.get("value_target") is not None:
            value["unit_target"] = parameter.unit_target
        chosen = self._label_of(getattr(parameter, "vocabulary", None),
                                row.get("value"))
        if chosen:
            value["value_label"] = chosen
        if row.get("flags"):
            value["flags"] = list(row["flags"])
        return value

    # ------------------------------------------------------------- asking

    def __len__(self) -> int:
        return len(self._values)

    def get(self, name: str) -> Optional[dict]:
        return self._by_id.get(name)

    def documents(self) -> list:
        """Every document with a value, and how many it has."""
        found: dict = {}
        for value in self._values:
            entry = found.setdefault(value["document"], {
                "document": value["document"], "values": 0,
                "parameters": set()})
            entry["values"] += 1
            entry["parameters"].add(value["parameter"])
        return [{**entry, "parameters": len(entry["parameters"])}
                for entry in found.values()]

    def parameters(self) -> list:
        """Every parameter the harvest has a value of: how many, in how
        many documents, in which units and with which coordinates. Under
        `coordinates` each one lists what was read there and how often, so
        an asker sees what can be asked for before asking."""
        found: dict = {}
        for value in self._values:
            entry = found.setdefault(value["parameter"], {
                "parameter": value["parameter"], "label": value["label"],
                "values": 0, "documents": set(), "units": {},
                "coordinates": {}})
            entry["values"] += 1
            entry["documents"].add(value["document"])
            if value["unit"] not in (None, ""):
                unit = str(value["unit"])
                entry["units"][unit] = entry["units"].get(unit, 0) + 1
            for name, coordinate in value["coordinates"].items():
                content = coordinate.get("value")
                if content in (None, ""):
                    continue
                counted = entry["coordinates"].setdefault(name, {})
                key = str(content)
                seen = counted.setdefault(key, {"value": content,
                                                "count": 0})
                if coordinate.get("label"):
                    seen["label"] = coordinate["label"]
                seen["count"] += 1
        out = []
        for entry in found.values():
            out.append({
                **entry, "documents": len(entry["documents"]),
                "coordinates": {
                    name: sorted(counted.values(),
                                 key=lambda item: (-item["count"],
                                                   str(item["value"])))
                    for name, counted in sorted(
                        entry["coordinates"].items())}})
        return sorted(out, key=lambda item: str(item["parameter"]))

    @staticmethod
    def _matches(coordinate: Optional[dict], wanted) -> bool:
        if coordinate is None:
            return False
        if same(coordinate.get("value"), wanted):
            return True
        label = coordinate.get("label")
        return label is not None and _text(label) == _text(wanted)

    def find(self, *, document: Optional[str] = None,
             parameter: Optional[str] = None, level: Optional[str] = None,
             coordinates: Optional[dict] = None, text: Optional[str] = None,
             limit: Optional[int] = 50, offset: int = 0) -> dict:
        """The values that match everything asked for, as {total, values}.
        *limit* None is every one of them, for a caller that writes a
        file; a number is held to `MAX_LIMIT`, which is what one answer of
        a server carries.

        *parameter* is a parameter's name or its label. *level* is the
        worst level still wanted. A coordinate is asked for by what was
        read there or by its label. *text* is looked for in the quote, the
        label and the wordings, without regard to case.
        """
        if level is not None and level not in LEVELS:
            raise ValueError(f"level is {level!r}, not one of "
                             f"{', '.join(LEVELS)}")
        if (limit is not None and limit < 0) or offset < 0:
            raise ValueError("limit and offset are not negative")
        allowed = LEVELS[:LEVELS.index(level) + 1] if level else LEVELS
        needle = _text(text) if text else None
        wanted = None
        if parameter is not None:
            wanted = _text(parameter)
        found = []
        for value in self._values:
            if document is not None and value["document"] != document:
                continue
            if wanted is not None and wanted not in (
                    _text(value["parameter"]), _text(value["label"] or "")):
                continue
            if value["level"] not in allowed:
                continue
            if any(not self._matches(value["coordinates"].get(name), content)
                   for name, content in (coordinates or {}).items()):
                continue
            if needle is not None:
                hay = [value.get("quote"), value.get("label"),
                       value.get("value_raw"), value.get("value_label"),
                       value.get("unit_raw")]
                hay += [part for coordinate in value["coordinates"].values()
                        for part in (coordinate.get("wording"),
                                     coordinate.get("label"))]
                if not any(needle in _text(part) for part in hay
                           if part not in (None, "")):
                    continue
            found.append(value)
        shown = found[offset:] if limit is None \
            else found[offset:offset + min(limit, MAX_LIMIT)]
        return {"total": len(found), "offset": offset, "values": shown}
