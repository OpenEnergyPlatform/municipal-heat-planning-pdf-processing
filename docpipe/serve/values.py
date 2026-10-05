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

The same files say more than their values. A harvest file holds, per
parameter, a state line (`kind: parameter_state`) and the claims that were
refused (`kind: refusal`), and these are read here too, once, with the
values. A missing value is then an answer and not a silence:

    read          values of the parameter were read and accepted
    unstated      the document was read and does not carry it
    exhausted     the run ended before the document was read through
    unbacked      values were offered and refused (`refusals` says why)
    never_asked   the file has state lines, and none for this parameter
    not_recorded  the file has no state line at all: it was written before
                  states were kept

The first four are the harvest's words, as it wrote them. The last two are
not a state of the document: they say that the harvest holds none, and are
kept apart from `unstated` because "the plan does not say it" is a finding
and "nobody asked" is not. A document or a parameter the harvest does not
have at all is an error (`NotFound`), never an empty answer.

Beware the name: a tuple's own `parameter_state` key is the state of its
`parameter` coordinate, which is another thing (`coordinates`, below).

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .. import jsonl
from ..extraction import identity, trust
from ..extraction.gold import coordinates as coordinate_names
from ..extraction.gold import same
from ..extraction.schema import PARAMETER_STATE_DOC

log = logging.getLogger(__name__)

LEVELS = (trust.LEVEL_A, trust.LEVEL_B, trust.LEVEL_C)
MAX_LIMIT = 1000

# What the harvest holds no line for. Not harvest states: see the docstring.
NEVER_ASKED = "never_asked"
NOT_RECORDED = "not_recorded"
STATES = tuple(trust.PARAMETER_STATES) + (NEVER_ASKED, NOT_RECORDED)
MEANINGS = {
    **{state: PARAMETER_STATE_DOC[state] for state in trust.PARAMETER_STATES},
    NEVER_ASKED: "the harvest of this document has state lines and none for "
                 "this parameter: it was not asked. Not a finding about the "
                 "document",
    NOT_RECORDED: "the harvest of this document has no state line at all, "
                  "so nothing is known about what was asked. Values and "
                  "refusals of it are served",
}
TRACE_SUFFIX = ".trace.jsonl"


class NotFound(LookupError):
    """A document or a parameter the harvest does not have."""


@dataclass
class Harvest:
    """What a harvest directory holds, by document name (the file's name
    without its ending)."""
    tuples: dict = field(default_factory=dict)      # accepted rows
    refusals: dict = field(default_factory=dict)    # refused claims
    states: dict = field(default_factory=dict)      # {parameter: state line}
    unreadable: int = 0     # lines that could not be used, counted not hidden


def read_harvest(harvest_dir) -> Harvest:
    """Read every document file of a harvest directory once.

    The one place that reads the files: the values, the states and the
    refusals served from here come out of the same pass, so they cannot
    describe two different states of the directory. A line that is not a
    JSON object, or a state line that names no parameter or no state, is
    skipped, said in the log and counted in `unreadable`. Where a file
    carries two state lines for one parameter the later one stands.
    """
    harvest_dir = Path(harvest_dir)
    if not harvest_dir.is_dir():
        raise FileNotFoundError(f"{harvest_dir} is not a directory")
    found = Harvest()
    for path in sorted(harvest_dir.glob("*.jsonl")):
        if path.name.endswith(TRACE_SUFFIX):
            continue                    # events of the run, not a document
        name = path.stem
        found.tuples[name], found.refusals[name] = [], []
        found.states[name] = {}
        for number, line in enumerate(jsonl.read(path), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                row = None
            if not isinstance(row, dict):
                found.unreadable += 1
                log.warning("harvest: %s line %d is not a JSON object, "
                            "skipped", path.name, number)
                continue
            kind = row.get("kind")
            if kind == "tuple":
                found.tuples[name].append(row)
            elif kind == "refusal":
                found.refusals[name].append(row)
            elif kind == "parameter_state":
                if isinstance(row.get("parameter"), str) \
                        and isinstance(row.get("state"), str):
                    found.states[name][row["parameter"]] = row
                else:
                    found.unreadable += 1
                    log.warning("harvest: %s line %d is a state line without "
                                "a parameter or a state, skipped", path.name,
                                number)
    return found


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


def _bounds(limit: Optional[int], offset: int) -> None:
    if (limit is not None and limit < 0) or offset < 0:
        raise ValueError("limit and offset are not negative")


def _page(found: list, key: str, limit: Optional[int], offset: int) -> dict:
    """One answer of a list: {total, offset, <key>: the part asked for}.
    *limit* None is all of it, for a caller that writes a file; a number is
    held to `MAX_LIMIT`, which is what one answer of a server carries."""
    shown = found[offset:] if limit is None \
        else found[offset:offset + min(limit, MAX_LIMIT)]
    return {"total": len(found), "offset": offset, key: shown}


class Values:
    """Every accepted value of a harvest, and what the harvest says about
    the parameters that have none.

    *rows_by_document* are the accepted rows; *refusals* and *states* are
    what `read_harvest` found beside them. Without them every document
    reads as `not_recorded` and has no refusal. *passages* is the handle of
    the passage search (`passages.py`), which reads the corpus database and
    not the harvest; None where there is no database.
    """

    def __init__(self, rows_by_document: dict, *, spec=None,
                 transcribed: Iterable[str] = (),
                 refusals: Optional[dict] = None,
                 states: Optional[dict] = None, passages=None,
                 unreadable: int = 0):
        self.spec = spec
        self.transcribed = set(transcribed)
        self.passages = passages
        self.unreadable = unreadable
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
        self._refusals = {name: list(rows)
                          for name, rows in (refusals or {}).items()}
        self._lines = {name: dict(lines)
                       for name, lines in (states or {}).items()}
        self.harvested = sorted(set(rows_by_document) | set(self._refusals)
                                | set(self._lines))
        self._columns = self._parameter_columns()
        self._named = self._columns + sorted(
            {row.get("parameter") for rows in self._refusals.values()
             for row in rows if isinstance(row.get("parameter"), str)}
            - set(self._columns))

    @classmethod
    def load(cls, harvest_dir, *, spec=None, db=None,
             passages=None) -> "Values":
        harvest = read_harvest(harvest_dir)
        return cls(harvest.tuples, spec=spec,
                   transcribed=trust.transcribed_documents(db),
                   refusals=harvest.refusals, states=harvest.states,
                   passages=passages, unreadable=harvest.unreadable)

    def _parameter_columns(self) -> list:
        """The parameters a coverage has a column for: those of the spec in
        its order, then any other that a state line or a value names. What
        only a refusal names is a claim and not a parameter."""
        columns = [p.uri for p in getattr(self.spec, "parameters", ())]
        seen = set(columns)
        more = {uri for lines in self._lines.values() for uri in lines}
        more |= {value["parameter"] for value in self._values}
        columns += sorted(uri for uri in more - seen if isinstance(uri, str))
        return columns

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
            # The passage this coordinate was read from, and where it has
            # one, the row's own passage that names its state (a base year).
            for served, key in (("quote", "_quote"), ("link_quote",
                                                      "_link_quote")):
                passage = row.get(f"{axis_name}{key}")
                if passage not in (None, ""):
                    entry[served] = passage
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
        _bounds(limit, offset)
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
        return _page(found, "values", limit, offset)

    # ------------------------------------------- what the harvest says it lacks

    def _label_of_parameter(self, uri) -> Optional[str]:
        parameter = self._parameter(uri)
        return parameter.label if parameter is not None else None

    def _documents_named(self, document: Optional[str]) -> list:
        if document is None:
            return list(self.harvested)
        if document not in self.harvested:
            raise NotFound(f"the harvest has no document {document!r}")
        return [document]

    def _parameter_named(self, parameter: str, among: list) -> str:
        """The name of the parameter that *parameter* (a name or a label)
        asks for. One the harvest does not have is an error: an empty answer
        would read as "the document does not say it"."""
        wanted = _text(parameter)
        for uri in among:
            if wanted in (_text(uri),
                          _text(self._label_of_parameter(uri) or "")):
                return uri
        raise NotFound(f"the harvest names no parameter {parameter!r}; the "
                       f"coverage lists the parameters it does")

    def _cell(self, document: str, parameter: str) -> dict:
        """One document and one parameter: the line the harvest wrote for
        the pair, or why there is none."""
        lines = self._lines.get(document) or {}
        line = lines.get(parameter)
        if line is not None:
            state, tuples, refusals = (line["state"], line.get("tuples"),
                                       line.get("refusals"))
        else:
            # Counts say what they count: with no line there is none.
            state = NEVER_ASKED if lines else NOT_RECORDED
            tuples = refusals = None
        return {"document": document, "parameter": parameter,
                "label": self._label_of_parameter(parameter),
                "state": state, "tuples": tuples, "refusals": refusals}

    @staticmethod
    def _meanings(states: Iterable[str]) -> dict:
        present = set(states)
        return {state: MEANINGS[state] for state in STATES
                if state in present}

    def states(self, *, document: Optional[str] = None,
               parameter: Optional[str] = None, state: Optional[str] = None,
               limit: Optional[int] = 50, offset: int = 0) -> dict:
        """What the harvest says about parameters of documents, one cell
        per pair, as {total, offset, states, meanings}.

        With a *document* the cells are its parameters, with a *parameter*
        (a name or a label) its documents, with both one cell, with neither
        all of them. *state* keeps the cells in that state. `meanings` says
        what each state of the page is. A document or parameter the harvest
        does not have raises `NotFound`; *limit* is as in `find`.
        """
        if state is not None and state not in STATES:
            raise ValueError(f"state is {state!r}, not one of "
                             f"{', '.join(STATES)}")
        _bounds(limit, offset)
        documents = self._documents_named(document)
        uris = self._columns if parameter is None else [
            self._parameter_named(parameter, self._columns)]
        cells = (self._cell(name, uri) for name in documents for uri in uris)
        found = [cell for cell in cells
                 if state is None or cell["state"] == state]
        answer = _page(found, "states", limit, offset)
        answer["meanings"] = self._meanings(c["state"]
                                            for c in answer["states"])
        return answer

    def coverage(self, *, document: Optional[str] = None,
                 parameter: Optional[str] = None,
                 limit: Optional[int] = 50, offset: int = 0) -> dict:
        """Documents by parameters, each cell the state of that pair:
        {parameters, total, offset, documents, tally, meanings}.

        `documents` is the page asked for, each as {document, states:
        {parameter: state}}. `tally` counts, per parameter, the documents
        in each state over all `total` documents and not only the page, so
        a page of fifty still says how the whole corpus stands.
        """
        _bounds(limit, offset)
        names = self._documents_named(document)
        uris = self._columns if parameter is None else [
            self._parameter_named(parameter, self._columns)]
        rows = [{"document": name,
                 "states": {uri: self._cell(name, uri)["state"]
                            for uri in uris}} for name in names]
        tally = {uri: {} for uri in uris}
        for row in rows:
            for uri, state in row["states"].items():
                tally[uri][state] = tally[uri].get(state, 0) + 1
        answer = _page(rows, "documents", limit, offset)
        answer["parameters"] = [{"parameter": uri,
                                 "label": self._label_of_parameter(uri)}
                                for uri in uris]
        answer["tally"] = tally
        answer["meanings"] = self._meanings(
            state for counted in tally.values() for state in counted)
        return answer

    @staticmethod
    def _refusal(document: str, row: dict) -> dict:
        claim = row.get("claim")
        owner = row.get("owner")
        failed = claim.get("_why") if isinstance(claim, dict) \
            and claim.get("_harvest_failed") else None
        return {"document": document, "parameter": row.get("parameter"),
                "reason": row.get("reason"), "failed": failed,
                "source": {"owner_kind": owner[0], "owner_id": owner[1]}
                if isinstance(owner, (list, tuple)) and len(owner) == 2
                else None,
                "claim": claim}

    def refusals(self, *, document: Optional[str] = None,
                 parameter: Optional[str] = None,
                 limit: Optional[int] = 50, offset: int = 0) -> dict:
        """The claims the harvest refused, as {total, offset, refusals}:
        why, from which passage, and the claim as the model returned it.
        `failed` is set where the claim is no claim but a request that was
        not served (`unreachable`, `unserved`, `no_answer`, `cut_off`).
        This is the reason behind an `unbacked` state. *parameter* may name
        what only a refusal names (a claim for no parameter of the spec)."""
        _bounds(limit, offset)
        documents = self._documents_named(document)
        wanted = None if parameter is None \
            else self._parameter_named(parameter, self._named)
        found = [self._refusal(name, row) for name in documents
                 for row in self._refusals.get(name, ())
                 if wanted is None or row.get("parameter") == wanted]
        return _page(found, "refusals", limit, offset)
