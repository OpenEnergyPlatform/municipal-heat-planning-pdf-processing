"""
general.py: The general steps of a flow (owner decision 2026-11-12, plan
of the general blocks, points 2 to 7) and "Ask the model", which every
step that asks the model is (owner decision 2026-11-12 evening: "alles
umbauen").

A flow can be built from steps that know nothing of a use case: ask the
model (`ask`), search the document's chunks (`search`), order a list of
chunks again (`rerank`), set a variable (`set`), keep the entries of a
list a condition holds for (`filter`), join lists (`merge`), run a piece of
Python (`python`), and go through any list (`each_list`). Each takes named
inputs and gives named outputs (`variables`): a variable the page makes
lives in the item it was made for, or for the whole document where its
step says so.

A step of "Ask the model" has five parts (`parts_of`): the request it is
in the log and whose rules it reads, its prompt, its inputs, the form of
its answer and its target; a preset (`presets`) gives all five for one
question the use cases ask, and whatever the step sets of its own wins.
What a request shows is built from its inputs (`shows`): each a key of the
message, the variable it comes from and how it is shown: as it is, as a
field with what it means, as numbered lines the answer can name, as the
title page or the headings, as the next search hits. An input whose key the
prompt names as {{key}} stands in the prompt and not in the message, so
that a prompt says each thing once. The answer is read in its form
(`forms`) and its target (`targets`) does with it what the question is
for: a variable, values of a field, a dimension of a value, a search
sentence, a list entry; an answer that names lines and words is checked as
every answer is (the line was shown, the words stand in it) and asked again
with what did not hold.

Author: Felix Vossel
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, is_dataclass
from typing import Optional

from .. import rules
from . import addressed, conditions

# The scope key of a variable the page made, and of the item of a loop over
# a list.
PAGE = "var:"


# -- what a variable holds ------------------------------------------------------

def _doc(scope):
    return scope.get("doc")


def raw(scope, name: str):
    """The object the variable *name* holds at *scope*, None where there
    is none: one of the page's (`PAGE`, the item's or the document's), or
    one the run keeps (`variables.VARIABLES`)."""
    if scope.has(PAGE + name):
        return scope.get(PAGE + name)
    doc = _doc(scope)
    if doc is not None and name in doc.made:
        return doc.made[name]
    plan = doc.plan if doc is not None else scope.get("plan")
    coord = scope.get("coord")
    value = scope.get("value")
    item = scope.get("field_item")
    if name == "document":
        return plan
    if name == "chunks":
        return list(plan.chunks) if plan is not None else []
    if name == "chunk":
        return scope.get("chunk")
    if name == "fields":
        return list(doc.parameters) if doc is not None else []
    if name == "field":
        return scope.get("parameter") or (
            item.parameter if item is not None else None)
    if name == "fact":
        return item
    if name == "facts":
        return {"settings": [line.text for line, _ in plan.settings],
                "years": [dict(b) for b in plan.bases]} \
            if plan is not None else {}
    if name == "lists":
        return {kind: [entry.name for entry in names.entries]
                for kind, names in plan.names.items()} \
            if plan is not None else {}
    if name == "order":
        return dict(doc.order_of) if doc is not None else {}
    if name == "hits":
        supply = scope.get("supply")
        return list(getattr(supply, "pieces", None)
                    or getattr(supply, "first", None) or []) \
            if supply is not None else []
    if name == "answer":
        return scope.owner().values.get("answer")
    if name == "values":
        return [claim for read in (doc.field_reads + doc.find_reads)
                for claim in read.claims] if doc is not None else []
    if name == "value":
        return value
    if name == "dimension":
        return coord
    if name == "dimensions":
        if value is None:
            return []
        from .reading import slots_of
        batch = value.read.batch
        return [slot.name for slot in slots_of(batch.spec, batch.parameter)]
    if name == "sentence":
        return coord.sentence if coord is not None else None
    if name == "round":
        return scope.get("round", 0)
    return None


def view(obj):
    """*obj* as JSON: a chunk with its numbered lines, a field with what it
    means, a value with its words and line, the answer of a question; a
    dict, list, text or number as it is."""
    from .units import Chunk
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(key): view(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [view(one) for one in obj]
    if isinstance(obj, Chunk):
        passage = obj.passage
        return {"kind": passage.kind, "page": passage.page,
                "title": passage.title or "",
                "lines": [{"number": line.number, "text": line.text}
                          for line in obj.lines()],
                "text": "\n".join(line.text for line in obj.lines())}
    if type(obj).__name__ == "Plan":
        return {"pages": max([(s.provenance or {}).get("page") or 0
                              for s in obj.sources] or [0]),
                "title_page": [line.text for line, _ in obj.title_page]}
    if hasattr(obj, "uri") and hasattr(obj, "label") \
            and hasattr(obj, "value_type"):
        from . import fields
        options = fields.value_choice(obj).options \
            if obj.value_type == "category" else None
        return {"uri": obj.uri, "name": obj.label,
                "means": obj.description or "",
                "unit": getattr(obj, "unit_target", "") or "",
                **({"list": [getattr(o, "label", str(o))
                             for o in options]} if options else {})}
    if type(obj).__name__ == "ValueItem":
        return _claim_view(obj.row.claim, obj.read.batch.parameter.uri)
    if type(obj).__name__ == "CoordItem":
        name = obj.slot.name
        claim = obj.row.claim
        return {"name": name, "value": view(claim.get(name)),
                "words": claim.get(f"{name}_raw") or "",
                "quote": claim.get(f"{name}_quote") or "",
                "state": claim.get(f"{name}_state") or ""}
    if type(obj).__name__ == "FieldItem":
        return {"key": obj.key, "found": len(obj.found)}
    if is_dataclass(obj):
        return view(asdict(obj))
    return str(obj)


def _claim_view(claim: dict, field_uri: str = "") -> dict:
    at = claim.get("at") or {}
    return {"field": field_uri or claim.get("parameter") or "",
            "value": view(claim.get("value")),
            "words": claim.get("value_raw") or "",
            "quote": claim.get("quote") or "",
            "line": at.get("line"),
            "dimensions": {key: view(value) for key, value in claim.items()
                           if not key.startswith(("value", "quote", "at",
                                                  "_"))
                           and "_" not in key}}


def get(scope, path: str):
    """The value at *path* ("answer.finds", "frage.jahr", "hits.0.text")
    as JSON, None where it leads nowhere."""
    if not isinstance(path, str) or not path:
        return None
    name, *rest = path.split(".")
    value = view(raw(scope, name))
    for key in rest:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() \
                and int(key) < len(value):
            value = value[int(key)]
        else:
            return None
    return value


def put(scope, name: str, value, lasting: bool = False) -> None:
    """The page's variable *name* set to *value*: for the item it was made
    for, or for the whole document (*lasting*)."""
    if lasting:
        _doc(scope).made[name] = value
    else:
        scope.put(PAGE + name, value)


# -- what a request shows ----------------------------------------------------------

# A request of "Ask the model" is built from its inputs (`shows`).

def _chunks_of(value) -> list:
    from .units import Chunk
    if isinstance(value, Chunk):
        return [value]
    if isinstance(value, (list, tuple)):
        return [one for one in value if isinstance(one, Chunk)]
    return []


_PLACE = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}")
# The places of a prompt that hold the example replies of its request
# (`runner.system_text`), never an input.
EXAMPLES = ("example", "nothing")


def placed(text: str) -> set:
    """The names a prompt writes as {{key}} or {{key.field}}, its example
    replies aside."""
    return set(_PLACE.findall(text or "")) - set(EXAMPLES)


def _at(value, path: list):
    for key in path:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() \
                and int(key) < len(value):
            value = value[int(key)]
        else:
            return None
    return value


def in_prompt(text: str, payload: dict) -> tuple:
    """(the prompt with each {{key}} and {{key.field}} of the message
    written in, the message without the keys the prompt holds whole): a
    prompt says each thing once (owner 2026-11-12: "die Prompts nicht
    überladen"). A place whose input shows nothing is empty."""
    names = placed(text)

    def fill(m):
        name = m.group(1)
        if name not in names:
            return m.group(0)
        root, *rest = name.split(".")
        return _as_text(_at(payload.get(root), rest))
    whole = {name for name in names if "." not in name}
    return _PLACE.sub(fill, text or ""), {
        key: value for key, value in payload.items() if key not in whole}


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return "\n".join(value)
    return json.dumps(value, ensure_ascii=False)


# -- the reply ----------------------------------------------------------------

def example_of(schema: dict):
    """An answer in the form of *schema*, for the request's prompt to show
    ({{example}}): each key with a value of its type, the first entry of a
    list of choices, one entry of an array."""
    if not isinstance(schema, dict):
        return None
    if schema.get("enum"):
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            return example_of(schema[key][0])
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((one for one in kind if one != "null"), "null")
    if kind == "object" or "properties" in schema:
        return {key: example_of(sub)
                for key, sub in (schema.get("properties") or {}).items()}
    if kind == "array":
        return [example_of(schema.get("items") or {"type": "string"})]
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return "..."


def first_key(schema: dict) -> str:
    """The key an answer must hold: the first the schema requires."""
    required = schema.get("required") or list(
        (schema.get("properties") or {}).keys())
    return str(required[0]) if required else ""


def schema_problem(schema) -> Optional[str]:
    """Why *schema* is no reply a request can ask for, None where it is
    one: an object with properties."""
    if not isinstance(schema, dict):
        return "the reply is a JSON schema"
    if schema.get("type") != "object":
        return "the reply is an object (type object)"
    props = schema.get("properties")
    if not isinstance(props, dict) or not props:
        return "the reply names its keys (properties)"
    for key in schema.get("required") or ():
        if key not in props:
            return f"the reply requires {key!r}, which it does not name"
    return None


# -- running Python of the page -------------------------------------------------

def python_problem(code) -> Optional[str]:
    """Why *code* is no Python step, None where it is one: Python that
    defines run(inputs) and returns a dict."""
    if not isinstance(code, str) or not code.strip():
        return "the code is empty"
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"the code is no Python: line {exc.lineno}: {exc.msg}"
    if not any(isinstance(node, ast.FunctionDef) and node.name == "run"
               for node in tree.body):
        return "the code defines run(inputs), which returns the outputs"
    return None


def run_python(code: str, inputs: dict) -> dict:
    """What run(inputs) of *code* returns, a dict of the outputs. The code
    runs in the run's own process, as a profile's own code does (owner
    decision 2026-11-12, point 12)."""
    space: dict = {"__name__": "docpipe_step"}
    exec(compile(code, "<step>", "exec"), space)
    out = space["run"](dict(inputs))
    if not isinstance(out, dict):
        raise TypeError("run(inputs) returns a dict of the outputs, not "
                        f"{type(out).__name__}")
    return out


# -- a condition about a variable -----------------------------------------------

def var_facts(scope, item=None, item_name: str = "item"
              ) -> conditions.Facts:
    """What a condition about variables (`conditions.VAR`) knows at
    *scope*, with *item* as the variable *item_name* (`filter`)."""
    def get_(subject: str, prop: str):
        if subject != conditions.VAR:
            raise LookupError(f"{subject} is not known here")
        name, *rest = prop.split(".")
        if item is not None and name == item_name:
            value = view(item)
            for key in rest:
                value = value.get(key) if isinstance(value, dict) else None
            return value
        return get(scope, prop)
    return conditions.Facts(get_)


def joined_facts(first: conditions.Facts, second: conditions.Facts
                 ) -> conditions.Facts:
    """Facts that ask *second* about variables and *first* about all
    else."""
    def get_(subject: str, prop: str):
        if subject == conditions.VAR:
            return second.get(subject, prop)
        return first.get(subject, prop)
    return conditions.Facts(get_)


def to_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# -- the steps --------------------------------------------------------------------

# The parts of "Ask the model" a step or its preset sets (owner decision
# 2026-11-12 evening, plan "modell_fragen", point 1): the request it is in
# the log, its prompt, its inputs, the form of its answer and its target.
PARTS = ("request", "prompt", "inputs", "reply", "into")
# The request of a step of the page's own: its prompt is the general one.
OWN = "own"


def preset_of(node: Optional[dict]):
    """The preset a step of "Ask the model" names, None where it names
    none (`presets`)."""
    from .presets import preset
    name = (node or {}).get("preset")
    return preset(name) if name else None


def default_prompt(request: str) -> str:
    """The prompt a request has where its step names none: the prompt of
    its kind (`extraction/<request>`), for a step of the page's own the
    general one (`extraction/ask`)."""
    return "extraction/ask" if request == OWN else f"extraction/{request}"


def into_of(into) -> dict:
    """The target of an answer as {"to": name, ...}: a step that names a
    field keeps values of it, one that names nothing a variable."""
    into = dict(into) if isinstance(into, dict) else {}
    if "to" not in into:
        into["to"] = "values" if into.get("field") else "var"
    if into["to"] == "values" and "keep" not in into:
        into["keep"] = "now"
    return into


def parts_of(node: Optional[dict]) -> dict:
    """The five parts of a step of "Ask the model": its own where it sets
    them, else its preset's, else the general step's."""
    node = node or {}
    found = preset_of(node)
    sets = node.get("set") or {}
    out: dict = {"request": OWN, "prompt": None, "inputs": [],
                 "reply": None, "into": {}}
    if found is not None:
        out.update(request=found.request, inputs=list(found.inputs),
                   reply=found.reply, into=dict(found.into))
    for key in PARTS:
        if key in sets and sets[key] is not None:
            out[key] = sets[key]
    out["into"] = into_of(out["into"])
    if not out["prompt"]:
        out["prompt"] = default_prompt(out["request"])
    if out["reply"] is None:
        out["reply"] = "finds" if out["into"]["to"] == "values" else {
            "type": "object", "properties": {"answer": {"type": "string"}},
            "required": ["answer"]}
    return out


def schema_with_more(schema: dict) -> dict:
    """*schema* with "more" beside its keys, where the step lets the model
    ask to see more (`addressed.with_more`)."""
    props = addressed.with_more(dict(schema.get("properties") or {}), True,
                                addressed.IMAGE in rules.get("fetches"))
    return {**schema, "properties": props}


class Ask:
    """One question a step of "Ask the model" asks: its parts
    (`parts_of`), where it stands (*scope*; with *values* the variables a
    target gives the request, `PAGE`), and how it asks. Its requests are
    built from its inputs (`shows.build`) and sent as the request its step
    is (`Reader._ask`), under the step's prompt where it is not the prompt
    of its kind (`addressed.PROMPT`)."""

    def __init__(self, engine, node: Optional[dict], scope,
                 values: Optional[dict] = None, plan=None,
                 document_id: Optional[int] = None):
        self.engine = engine
        self.reader = engine.reader
        self.node = node or {}
        self.parts = parts_of(self.node)
        self.kind = self.parts["request"]
        self.prompt = self.parts["prompt"]
        self.inputs = list(self.parts["inputs"] or ())
        self.reply = self.parts["reply"]
        self.into = self.parts["into"]
        self.scope = scope.child(True, **{PAGE + key: value for key, value
                                          in values.items()}) \
            if values else scope
        doc = self.scope.get("doc")
        self.doc = doc
        self.plan = plan if plan is not None else (
            doc.plan if doc is not None else self.scope.get("plan"))
        # The document asked for: the plan's, or given where it is not cut
        # yet (the figures are written out before).
        self.document_id = document_id if document_id is not None else (
            self.plan.document_id if self.plan is not None else None)

    # -- what the step sets ---------------------------------------------------

    def setting(self, key: str):
        return self.engine.setting(self.node, key, "ask")

    def number(self, key: str) -> int:
        return self.engine.number(self.node, key)

    @property
    def fetch(self) -> bool:
        """May the answer ask to see more (`fetches`)?"""
        return bool(self.setting("fetch"))

    @property
    def picture(self) -> bool:
        """May the answer ask for the picture of a figure it shows?"""
        return bool(self.setting("picture"))

    def holds(self, condition) -> bool:
        return self.engine.holds(condition, self.scope)

    def with_values(self, values: dict) -> "Ask":
        """The same question with *values* as variables of its request."""
        return Ask(self.engine, self.node, self.scope, values, self.plan,
                   self.document_id)

    # -- the request ----------------------------------------------------------

    def request(self, values: Optional[dict] = None, **over):
        """A request built from the step's inputs, with *values* as
        variables of its own and *over* as what it shows already (`batch`,
        `first`: the chunks of a half of the hits)."""
        from . import shows
        ask = self.with_values(values) if values else self
        req = shows.Request(ask)
        for key, value in over.items():
            setattr(req, key, value)
        shows.build(req, self.inputs, ask.holds)
        return req

    def chunk_input(self) -> Optional[dict]:
        """The input that shows the request's chunks."""
        return next((spec for spec in self.inputs
                     if isinstance(spec, dict) and spec.get("show")
                     in ("own_lines", "chunks", "lines", "next_chunks")),
                    None)

    def source(self, spec: Optional[dict]):
        """The variable an input comes from."""
        if not spec:
            return None
        path = str(spec.get("from") or "")
        return raw(self.scope, path) if "." not in path \
            else get(self.scope, path)

    def field(self):
        """The field of the Spec the answer reads values of: the one the
        target names, else the field of the step's frame."""
        uri = self.into.get("field")
        if uri and uri != "*":
            found = next((p for p in self.reader.spec.parameters
                          if p.uri == uri), None)
            if found is None:
                raise LookupError(f"{self.node.get('id')}: the Spec has no "
                                  f"field {uri!r}")
            return found
        return raw(self.scope, "field")

    @property
    def standard(self) -> bool:
        """Is the step's prompt the prompt of its kind of request?"""
        return self.prompt == addressed.PROMPT_IDS.get(self.kind)

    def prompting(self):
        """The step's prompt for the requests of its kind while it asks,
        where it is not the prompt of that kind (`addressed.PROMPT`)."""
        return addressed.prompting(self.kind,
                                   None if self.standard else self.prompt)

    def noted(self, noted: dict) -> dict:
        """What the log notes of a request: a step of the page's own is
        named by its id."""
        if self.kind == OWN:
            return {"step": self.node.get("id"), **noted}
        return noted

    def ask(self, req, shape: dict, example, counts, /, **noted):
        noted = self.noted(noted)
        with self.prompting():
            return self.reader._ask(self.kind, req.payload,
                                    self.document_id, shape, example,
                                    counts, **noted)

    def follow(self, req, shape: dict, example, reply, what: list,
               counts, /, **noted):
        noted = self.noted(noted)
        with self.prompting():
            return self.reader._follow(self.kind, req.payload,
                                       self.document_id, shape, example,
                                       reply, what, counts, **noted)

    def asks(self) -> bool:
        """Is there a prompt this question can be asked with: its own, or
        the profile's for its kind (`addressed.OPTIONAL`)?"""
        if not self.standard:
            return self.reader.asks.own is not None
        return getattr(self.reader.asks, self.kind, None) is not None


def nested(reader, target: str, plan, values: dict, node=None) -> Ask:
    """A question asked inside the answer of another (a list entry, a
    name, the year of a wording, whether a place speaks about the value):
    as the step after the asking question says that has this target, else
    the first of the flow, else its preset (owner decision 2026-11-12
    evening, plan "modell_fragen", point 7); built in the step that asks,
    as it always was."""
    engine = reader.engine
    if node is None:
        node = engine.nested_node(target)
    from .engine import Scope
    what = addressed.ASKING.get()
    scope = what.scope if what is not None and what.scope is not None \
        else Scope(None, True, plan=plan)
    return Ask(engine, node, scope, values, plan)


def ask_step(engine, node: dict, scope) -> None:
    """Ask the model as the step's parts say (owner decisions 2026-11-12):
    the request built from its inputs, the answer in its form, and what
    becomes of the answer as its target says (`targets.TARGETS`), with the
    ways the target goes (rounds over the search hits, halves of a request
    whose answer did not fit, what the answer asks to see, the picture of a
    figure, follow-up questions)."""
    from . import targets
    ask = Ask(engine, node, scope)
    target = targets.TARGETS.get(ask.into.get("to"))
    if target is None:
        raise LookupError(f"{node.get('id')}: no target "
                          f"{ask.into.get('to')!r}")
    if target.nested:
        return          # asked by the question before it, when it needs it
    with addressed.asking(engine.asking_of(node, scope, engine.after(node))), \
            engine.counted(ask.doc) as part:
        answer = target.run(ask, part)
    if answer is not None:
        scope.put("answer", answer)


def retrieve_step(engine, node: dict, scope) -> None:
    """The chunks of the document best for a text: the best of each kind
    first up to its share, then the best of the rest, ordered by the
    reranker where the rule `rerank` is on (`addressed.Reader.shown_order`).
    The hits become the step's variable."""
    reader = engine.reader
    plan = scope.get("doc").plan
    sets = node.get("set") or {}
    text = _as_text(get(scope, sets.get("query")))
    with addressed.asking(addressed.Asking(node["id"])):
        hits = reader.shown_order(plan, [text], plan.pieces(False),
                                  engine.number(node, "pieces"),
                                  engine.shares_of(node)) \
            if text.strip() else []
    put(scope, sets.get("into") or "hits", hits, False)


def rerank_step(engine, node: dict, scope) -> None:
    """A list of chunks ordered by how well each matches a text, best
    first (`addressed.Reader.rerank_left`)."""
    sets = node.get("set") or {}
    plan = scope.get("doc").plan
    chunks = _chunks_of(raw(scope, sets["list"]) if "." not in sets["list"]
                        else None)
    text = _as_text(get(scope, sets.get("query")))
    with addressed.asking(addressed.Asking(node["id"])):
        ordered = engine.reader.rerank_left(plan, [text], chunks) \
            if chunks and text.strip() else chunks
    put(scope, sets["into"], ordered, False)


def set_step(engine, node: dict, scope) -> None:
    sets = node.get("set") or {}
    if "from" in sets:
        path = sets["from"]
        value = raw(scope, path) if "." not in path else get(scope, path)
    else:
        value = sets.get("value")
    put(scope, sets["name"], value, bool(sets.get("lasting")))


def filter_step(engine, node: dict, scope) -> None:
    sets = node.get("set") or {}
    path = sets["list"]
    entries = to_list(raw(scope, path) if "." not in path
                      else get(scope, path))
    kept = []
    for entry in entries:
        facts = joined_facts(engine.facts(scope),
                             var_facts(scope, entry, "item"))
        if conditions.holds(sets["keep"], facts):
            kept.append(entry)
    put(scope, sets["into"], kept, False)


def merge_step(engine, node: dict, scope) -> None:
    sets = node.get("set") or {}
    out: list = []
    seen: set = set()
    for path in sets.get("lists") or ():
        for entry in to_list(raw(scope, path) if "." not in path
                             else get(scope, path)):
            key = json.dumps(view(entry), sort_keys=True, ensure_ascii=False,
                             default=str)
            if key not in seen:
                seen.add(key)
                out.append(entry)
    put(scope, sets["into"], out, bool(sets.get("lasting")))


def python_step(engine, node: dict, scope) -> None:
    sets = node.get("set") or {}
    inputs = {str(path).split(".")[-1]: get(scope, path)
              for path in sets.get("inputs") or ()}
    out = run_python(sets["code"], inputs)
    for name in sets.get("outputs") or ():
        put(scope, name, out.get(name), bool(sets.get("lasting")))


def list_items(node: dict, scope) -> list:
    """[(child scope values)] of a loop over a list: each entry under the
    name the loop gives it."""
    path = node.get("list") or ""
    entries = to_list(raw(scope, path) if "." not in path
                      else get(scope, path))
    name = node.get("as") or "item"
    return [{PAGE + name: entry} for entry in entries]
