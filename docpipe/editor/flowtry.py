"""
flowtry.py: A drawing of the flow tried on one document with made-up
answers: what each box would ask, nothing sent (owner decisions 2026-11-10
evening, section 12 of the plan).

"Try" reads a document as a run reads it, by the drawing on the page
(`extraction.engine`), with every request built in full, as it would go out
(its prompt, the parts of it the payload carries, its message), and kept
instead of sent. The answer comes from here, in one of two ways:

- "nothing": a find, and the question of a field the document has once,
  names the first number its piece prints where the field is a number
  (nothing where the piece prints none), else the piece's first word, so
  that there are values; every other answer is the empty answer of its
  request's own form (0, an empty list, an empty text, "no"): each
  coordinate goes through its whole search. It shows how far rounds and searches go at
  most. (Were the finds empty too, there would be no value to search for.)
- "first_line": every answer names the first line the request showed (its
  first number where it prints one, else its first word). It shows the
  shortest way.

No embedder and no reranker are asked either: a search orders the pieces
in the document's order, which a run never does instead of a search (owner
decision 2026-11-09); the page says so. The document is one of the corpus
database (its passages, some pages of them where asked) or, without one, a
plan made up from the examples of the profile's spec.

What comes back: per box the requests it asked and the first one in full,
the states the coordinates of the values ended in, and the pieces the
document was cut into.

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import json
import re
from typing import Optional

from docpipe import prompts as prompt_files
from ..extraction import addressed
from ..extraction import flow as flow_map
from ..extraction import runner
from ..extraction import thread as thread_map
from ..extraction.pipeline import Source

MODES = ("nothing", "first_line")
# A number as a line prints it: separators only between digits, so that
# the sentence's full stop or comma after it is not part of its words.
NUMBER = re.compile(r"-?\d+(?:[.,]\d+)*")
WORD = re.compile(r"[^\W\d_]{3,}")
ORDER_SAID = ("A dry run has no embedding model and no reranker. A search "
              "in it therefore shows the chunks in the order of the "
              "document, which a real run never does; a real run orders "
              "them by how well they fit the search sentence.")


class Refused(ValueError):
    """What cannot be tried, said."""


def example_sources(spec) -> list:
    """A plan made up from the examples of *spec*: a title page and one
    section per field's example."""
    meta = {"document_id": 0, "page": 1, "section_title": "Example"}
    out = [Source("section", 1, "Example plan, made up from the examples "
                                "of the spec.", dict(meta))]
    for i, parameter in enumerate(spec.parameters, start=2):
        example = getattr(parameter, "example", None) or {}
        text = example.get("source") if isinstance(example, dict) else None
        if not isinstance(text, str) or not text.strip():
            continue
        out.append(Source("section", i, text.replace("<<", "").replace(
            ">>", ""), {**meta, "page": 1 + i // 3,
                        "section_title": parameter.label}))
    return out


def _shown(payload: dict) -> list:
    """(address, text) of every line a payload shows, in order."""
    out = []

    def take(lines):
        for line in lines or ():
            if isinstance(line, str) and " " in line:
                address, _, text = line.partition(" ")
                out.append((address, text))
    if isinstance(payload.get("passage"), dict):
        take(payload["passage"].get("lines"))
    for block in (payload.get("passages") or {}).values():
        if isinstance(block, dict):
            take(block.get("lines"))
    for key in ("title_page", "headings", "settings"):
        if isinstance(payload.get(key), list):
            take(payload[key])
    return out


def _first(payload: dict, numbers: bool = False) -> tuple:
    """(address, words, text) of the first line a payload shows, its first
    word; where *numbers*, of the first line that prints a number, that
    number, and none where no line prints one."""
    lines = _shown(payload)
    if not lines:
        return None, None, None
    address, text = lines[0]
    if numbers:
        for one_address, one_text in lines:
            got = NUMBER.search(one_text)
            if got:
                return one_address, got.group(0), one_text
        return None, None, None
    got = WORD.search(text) or NUMBER.search(text)
    return address, got.group(0) if got else text.split()[0], text


def _schema(shape) -> dict:
    """The JSON schema of a request's answer form."""
    if not isinstance(shape, dict):
        return {}
    inner = shape.get("json_schema")
    if isinstance(inner, dict) and isinstance(inner.get("schema"), dict):
        return inner["schema"]
    return shape


def empty(schema: dict):
    """The answer of the form *schema* that names nothing: every key the
    form requires, each empty: an empty list, 0 for a number or an address,
    an empty text, the last of a choice of words (a check's "no"), the
    first of several forms (the number, not "new")."""
    if "anyOf" in schema:
        return empty(schema["anyOf"][0] if schema["anyOf"] else {})
    if "enum" in schema:
        return schema["enum"][-1] if schema["enum"] else None
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if "object" in kinds:
        properties = schema.get("properties") or {}
        return {key: empty(properties.get(key) or {})
                for key in schema.get("required") or ()}
    if "array" in kinds:
        return []
    if "integer" in kinds or "number" in kinds:
        return 0
    if "string" in kinds:
        return ""
    return None


def answer(kind: str, payload: dict, shape: dict, mode: str,
           numeric: bool = False):
    """The made-up answer of one request, in the request's own form; a find
    of a *numeric* field names a number."""
    schema = _schema(shape)
    text = json.dumps(schema)
    several = '"found"' in text and kind in ("coord", "search")
    finds = kind in ("find", "docfield")
    if mode == "nothing" and not finds:
        return empty(schema)
    at, words, line = _first(payload, finds and numeric)
    if at is None:
        return empty(schema)
    one = {"at": at, "words": words}
    if kind in ("find", "docfield"):
        return {"found": [{"entry": 1, **one} if '"entry"' in text
                          else one]}
    if kind in ("coord", "search"):
        if '"entry"' in text:
            return {"entry": 1, **one}
        return {"found": [one]} if several else one
    if kind == "list":
        return {"entry": [1] if '"array"' in text else 1,
                **(one if '"at"' in text else {})}
    if kind == "names":
        return {"entry": "new"}
    if kind == "check":
        return {"about": "yes"}
    if kind == "work":
        return {"found": [], "own": one}
    if kind == "phrase":
        return {"phrase": line}
    return {}


class Recorder:
    """The requests of a try: each built in full, kept by the box that
    asked it, answered from here."""

    def __init__(self, profile, mode: str, numeric=frozenset()):
        self.profile = profile
        self.mode = mode
        # the names of the fields whose values are numbers (the spec's)
        self.numeric = frozenset(numeric)
        self.parts: dict = {}
        self.by_box: dict = collections.OrderedDict()
        self.kinds: collections.Counter = collections.Counter()

    def _parts(self, kind: str):
        if kind not in self.parts:
            try:
                self.parts[kind] = thread_map.cut(prompt_files.load(
                    addressed.PROMPT_IDS[kind], self.profile))
            except (FileNotFoundError, LookupError):
                self.parts[kind] = None
        return self.parts[kind]

    def keep(self, kind: str, payload: dict, shape, example,
             follows: Optional[str] = None) -> None:
        box = addressed.asking_box() or "(no box)"
        entry = self.by_box.setdefault(box, {"requests": 0, "kinds":
                                             collections.Counter(),
                                             "first": None})
        entry["requests"] += 1
        entry["kinds"][follows and "follow" or kind] += 1
        self.kinds[kind] += 1
        if entry["first"] is None:
            parts = self._parts(follows or kind)
            system = runner.system_text(runner.request_prompt(
                parts, payload, shape), example) if parts is not None \
                else ""
            entry["first"] = {
                "kind": kind if not follows else f"follow of {follows}",
                "system": system,
                "message": json.dumps(payload, ensure_ascii=False,
                                      indent=1)}

    def asker(self, kind: str):
        def ask(payload, document_id, /, *, shape, example, **noted):
            self.keep(kind, payload, shape, example)
            return answer(kind, payload, shape, self.mode,
                          self.numeric_field(payload))
        return ask

    def numeric_field(self, payload) -> bool:
        field = payload.get("field") if isinstance(payload, dict) else None
        return isinstance(field, dict) and field.get("name") in self.numeric

    def follow(self, kind, payload, document_id, /, *, shape, example,
               **noted):
        self.keep("follow", payload, shape, example, follows=kind)
        return answer(kind, payload, shape, self.mode,
                      self.numeric_field(payload))

    def asks(self) -> addressed.Asks:
        def optional(kind):
            return self.asker(kind) if self._parts(kind) is not None \
                else None
        return addressed.Asks(
            find=self.asker("find"), docfield=self.asker("docfield"),
            coord=self.asker("coord"), list=self.asker("list"),
            search=self.asker("search"), follow=self.follow,
            names=optional("names"), check=optional("check"),
            work=optional("work"), phrase=optional("phrase"))


def in_order(document_id, sentences, chunks) -> list:
    return list(chunks)


def run(profile, spec, tree: list, numbers, sources: list,
        mode: str = "nothing") -> dict:
    """What the drawing *tree* asks of the document *sources* with the
    made-up answers of *mode*, nothing sent (see the module's head)."""
    if mode not in MODES:
        raise Refused(f"mode is one of {', '.join(MODES)}, not {mode!r}")
    from .. import rules
    said = flow_map.problems(tree, flow_map.known_rules(profile), profile)
    if said:
        raise Refused("the drawing cannot run: " + "; ".join(
            (f"{p['id']}: " if p["id"] else "") + p["message"]
            for p in said[:3]))
    if not sources:
        raise Refused("the document has no passages to read")
    recorder = Recorder(profile, mode, (
        parameter.label for parameter in spec.parameters
        if getattr(parameter, "is_numeric", False)))

    def sentence(parameter, document_id):
        recorder.keep("phrase", {"label": parameter.label}, None, None)
        return []
    reader = addressed.Reader(
        spec, recorder.asks(), in_order, probes=sentence,
        known=runner.row_context,
        plan_fields=spec.plan_fields, works=spec.works,
        frame_slots=runner.frame_slots_of(spec), numbers=numbers,
        flow=tree)
    engine = reader.engine
    document_id = sources[0].provenance.get("document_id", 0) \
        if sources[0].provenance else 0

    def transcripts(document_id, figures, each):
        return {}, 0
    plan, counts = engine.plan(document_id, sources, transcripts, None,
                               numbers)
    orders = addressed.Orders(in_order, lambda parameter, document_id: [],
                              None)
    reads = engine.read(plan, list(spec.parameters), None, counts, None,
                        lambda located: orders(plan, located,
                                               plan.cut.key()))
    states: dict = collections.defaultdict(collections.Counter)
    values = 0
    for read in reads:
        for claim in read.claims:
            values += 1
            for key, value in claim.items():
                if key.endswith("_state"):
                    states[key[:-6]][value] += 1
    return {"mode": mode, "said": ORDER_SAID,
            "requests": sum(e["requests"] for e in recorder.by_box.values()),
            "boxes": {box: {"requests": e["requests"],
                            "kinds": dict(e["kinds"]), "first": e["first"]}
                      for box, e in recorder.by_box.items()},
            "pieces": len(plan.chunks), "groups": len(plan.groups),
            "values": values,
            "states": {name: dict(c) for name, c in sorted(states.items())},
            "refused": dict(counts.failed)}


def sources_of(db_path, document_id: int,
               pages: Optional[tuple] = None) -> list:
    """The passages of a document of the corpus database, those of the
    pages *pages* (first, last) where given."""
    every = runner.make_rest_of_document(db_path)
    got = list(every(int(document_id), set()) or ())
    if pages:
        first, last = pages
        got = [s for s in got
               if first <= int((s.provenance or {}).get("page") or 0)
               <= last]
    return got


def documents(db_path, limit: int = 200) -> list:
    """[{"id", "title"}] of the documents of the corpus database, for the
    page's choice."""
    import sqlite3
    out = []
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            rows = db.execute("SELECT id, COALESCE(title, filename, '') "
                              "FROM documents ORDER BY id LIMIT ?",
                              (int(limit),)).fetchall()
    except sqlite3.Error:
        return out
    for ident, title in rows:
        out.append({"id": ident, "title": str(title)[:120]})
    return out


__all__ = ["run", "example_sources", "sources_of", "documents", "MODES",
           "Refused", "answer", "empty"]
