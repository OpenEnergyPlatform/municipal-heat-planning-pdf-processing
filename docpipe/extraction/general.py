"""
general.py: The general steps of a flow (owner decision 2026-11-12, plan
of the general blocks, points 2 to 7).

A flow can be built from steps that know nothing of a use case: ask the
model with a prompt of one's own (`ask`), and let it fetch what a shown
line points to (`ask` with tools), search the document's chunks
(`search`), order a list of chunks again (`rerank`), set a variable
(`set`), keep the entries of a list a condition holds for (`filter`), join
lists (`merge`), run a piece of Python (`python`), and go through any list
(`each_list`). Each takes named inputs and gives named outputs
(`variables`): a variable the page makes lives in the item it was made
for, or for the whole document where its step says so.

What a request shows is built from its inputs: each a key of the message,
the variable it comes from and how it is shown (`SHOWS`): as it is, as a
field with what it means, as numbered lines the answer can name, as the
title page or the headings. An input whose key the prompt names as
{{key}} stands in the prompt and not in the message, so that a prompt says
each thing once. The answer is read in the form of its JSON schema; an
answer that names lines and words is checked as every answer is (the line
was shown, the words stand in it), asked again with what did not hold, and
kept as values of a field of the Spec where the step says so.

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
from .units import Shown, letter_headings, letter_title_page, own_lines

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


# -- how a request shows an input -----------------------------------------------

class Request:
    """What one request shows: its lines by letter (`units.Shown`), the
    document, and the reading."""

    def __init__(self, plan, reader, scope):
        self.plan = plan
        self.reader = reader
        self.scope = scope
        self.shown = Shown()
        self.own = None             # the chunk shown as the request's own
        self.letters: list = []
        self.chunks: list = []      # every chunk it shows as lines


def _chunks_of(value) -> list:
    from .units import Chunk
    if isinstance(value, Chunk):
        return [value]
    if isinstance(value, (list, tuple)):
        return [one for one in value if isinstance(one, Chunk)]
    return []


def _show_as_is(req: Request, value):
    return view(value)


def _show_text(req: Request, value):
    shown = view(value)
    return shown if isinstance(shown, str) \
        else json.dumps(shown, ensure_ascii=False)


def _show_field(req: Request, value):
    return addressed.field_shown(value) if hasattr(value, "label") else None


def _show_list(req: Request, value):
    if not hasattr(value, "value_type"):
        return None
    listed = req.reader.listed(value)
    return listed[0] if listed else None


def _show_lines(req: Request, value):
    """One chunk as the request's own lines, numbered as in its passage;
    several chunks each under a letter of its own."""
    chunks = _chunks_of(value)
    if not chunks:
        return None
    req.chunks += [chunk for chunk in chunks if chunk not in req.chunks]
    if len(chunks) == 1 and req.own is None:
        chunk = chunks[0]
        req.own = chunk
        req.shown.add("", "passage", own_lines(chunk))
        return addressed.block_payload(chunk.passage, req.shown)
    out = {}
    for chunk in chunks:
        letter = req.shown.letter_for(chunk.owner)
        req.shown.add(letter, letter, own_lines(chunk))
        if letter not in req.letters:
            req.letters.append(letter)
        out[letter] = addressed.block_payload(chunk.passage, req.shown,
                                              letter)
    return out


def _show_headings(req: Request, value):
    chunks = _chunks_of(value)
    if not chunks or not rules.get("show_headings"):
        return None
    heads = req.plan.headings(chunks[0].owner)
    if not heads:
        return None
    req.shown.add(letter_headings(), "headings", heads, renumber=True)
    return req.shown.rendered(letter_headings())


def _show_title_page(req: Request, value):
    plan = req.plan
    if plan is None or not addressed.title_page_shown(plan):
        return None
    title = plan.title_page
    if not title:
        return None
    req.shown.add(letter_title_page(), "title_page", title, renumber=True)
    return req.shown.rendered(letter_title_page())


def _show_facts(req: Request, value):
    shown = addressed.settings_of(req.plan) if req.plan is not None else {}
    return shown.get("settings") or None


# name -> (what the page calls it, what it does, how)
SHOWS = {
    "as_is": ("as it is", "The variable as JSON.", _show_as_is),
    "text": ("as text", "The variable as one text.", _show_text),
    "field": ("the field and what it means",
              "The name of a field of the Spec and what a value of it is.",
              _show_field),
    "list": ("the field's list",
             "The entries a value of the field is chosen from, numbered, "
             "with what each means where the list is short.", _show_list),
    "lines": ("numbered lines",
              "A chunk as lines with their numbers, which the answer names; "
              "several chunks each under a letter.", _show_lines),
    "headings": ("the headings above it",
                 "The headings above the chunk's first line.",
                 _show_headings),
    "title_page": ("the title page",
                   "The first lines of the document's first page.",
                   _show_title_page),
    "facts": ("the facts of the document",
              "What holds for the whole document, as kept so far.",
              _show_facts),
}


def shows_catalogue() -> dict:
    return {name: {"label": label, "says": says}
            for name, (label, says, _how) in SHOWS.items()}


def payload_of(req: Request, inputs: list) -> dict:
    """The message of a request: each input under its key, shown as it
    says; an input that shows nothing is left out."""
    out: dict = {}
    for one in inputs or ():
        key, source = one.get("key"), one.get("from")
        how = SHOWS.get(one.get("show") or "as_is", SHOWS["as_is"])[2]
        name, *rest = str(source or "").split(".")
        value = raw(req.scope, name) if not rest else get(req.scope, source)
        part = how(req, value)
        if part is None or part == [] or part == {} or part == "":
            continue
        out[key] = part
    return out


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

def reply_schema(node: dict) -> dict:
    """The JSON schema the answer of an ask step has: its own, or for a
    step that keeps values of a field, the form of a find (line and words,
    the entry of a list)."""
    sets = node.get("set") or {}
    into = sets.get("into") or {}
    if into.get("field"):
        return {}
    schema = sets.get("reply")
    if isinstance(schema, dict) and schema:
        return schema
    return {"type": "object", "properties": {"answer": {"type": "string"}},
            "required": ["answer"]}


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

def _into(node: dict) -> dict:
    into = (node.get("set") or {}).get("into")
    return into if isinstance(into, dict) else {}


def _schema_with_more(schema: dict) -> dict:
    """*schema* with "more" beside its keys, where the step lets the model
    ask to see more (`addressed.with_more`)."""
    props = addressed.with_more(dict(schema.get("properties") or {}), True,
                                addressed.IMAGE in rules.get("fetches"))
    return {**schema, "properties": props}


def _fetched_again(engine, req: Request, prompt, payload: dict, reply,
                   shape: dict, example, counts, noted: dict) -> tuple:
    """(reply, payload) of a request asked again with the chunks its answer
    asked to see, each under a letter of its own, as often as the step's
    number says (owner decision 2026-11-12, "Modell mit Werkzeugen
    fragen")."""
    reader = engine.reader
    plan = req.plan
    anchor = list(req.chunks)
    seen = {chunk.key for chunk in req.chunks}
    for _ in range(int(rules.get("fetch_rounds"))):
        more = addressed.asked_more(reply)
        if not more or not anchor:
            break
        pieces = reader.fetch(plan, more, anchor, seen, False)
        if not pieces:
            break
        seen.update(chunk.key for chunk in pieces)
        blocks = reader.show_fetched(plan, req.shown, pieces)
        payload = {**payload, "passages": {
            **(payload.get("passages") or {}), **blocks}}
        again = reader.ask_own(prompt, payload, plan.document_id, shape,
                               example, counts, **noted,
                               fetched=len(pieces))
        if not isinstance(again, dict):
            break
        reply = again
    return reply, payload


def ask_step(engine, node: dict, scope) -> None:
    """Ask the model with the step's prompt, inputs and form of the answer
    (owner decision 2026-11-12): the answer becomes the step's variable,
    or the values of a field of the Spec, each with its line, checked as
    every value is and asked again with what did not hold."""
    from contextlib import nullcontext
    from .engine import Answer
    reader = engine.reader
    doc = scope.get("doc")
    plan = doc.plan
    sets = node.get("set") or {}
    into = _into(node)
    tools = [one for one in sets.get("tools") or () if one]
    lay = rules.in_step(rules.stepped(node, {
        "fetches": tools, "fetch_rounds": engine.number(node, "tool_rounds")
    })) if tools else nullcontext()
    # the step's prompt, or the general one of the default profile
    # (`extraction/ask`) where it names none
    prompt = engine.setting(node, "prompt")
    noted = {"step": node.get("id")}
    with lay:
        req = Request(plan, reader, scope)
        payload = payload_of(req, sets.get("inputs") or [])
        uri = into.get("field")
        if uri:
            parameter = next((p for p in reader.spec.parameters
                              if p.uri == uri), None)
            if parameter is None:
                raise LookupError(f"{node.get('id')}: the Spec has no field "
                                  f"{uri!r}")
            listed = reader.listed(parameter)
            if listed is not None and "list" not in payload:
                payload["list"] = listed[0]
            shape = addressed.found_format(listed is not None,
                                           more=bool(tools))
            example = addressed.find_example(
                req.shown, listed is not None,
                req.letters[0] if req.own is None and req.letters else "")
        else:
            schema = reply_schema(node)
            example = example_of(schema)
            if tools:
                schema = _schema_with_more(schema)
            shape = addressed.reply_format(schema)
        with addressed.asking(engine.asking_of(node, scope,
                                               engine.after(node))), \
                engine.counted(doc) as part:
            reply = reader.ask_own(prompt, payload, plan.document_id, shape,
                                   example, part, **noted)
            if tools and isinstance(reply, dict):
                reply, payload = _fetched_again(
                    engine, req, prompt, payload, reply, shape, example,
                    part, noted)
            if uri:
                answer = _kept_values(engine, doc, req, prompt, payload,
                                      reply, shape, example, part, noted,
                                      parameter, listed)
            else:
                answer = _kept_reply(engine, node, scope, req, prompt,
                                     payload, reply, shape, part, noted,
                                     into)
    scope.put("answer", Answer(*answer, **engine.came_to(part)))


def _kept_values(engine, doc, req: Request, prompt, payload: dict, reply,
                 shape: dict, example, counts, noted: dict, parameter,
                 listed) -> tuple:
    """The finds of an answer kept as values of *parameter*: each line and
    its words checked, what did not hold asked again with why, each value
    in the read of its passage (`Engine.keep`)."""
    reader = engine.reader
    plan = req.plan
    held, refused = reader._finds(plan, req.shown, reply, listed,
                                  parameter.is_numeric) \
        if isinstance(reply, dict) else ([], [])
    for _given, why in refused:
        counts.fail(why)
    for _ in range(reader.follow_ups()):
        if not refused or not isinstance(reply, dict):
            break
        reply = reader.follow_own(prompt, payload, plan.document_id, shape,
                                  example, reply,
                                  addressed.refusals(refused), counts,
                                  **noted)
        if not isinstance(reply, dict):
            break
        more, refused = reader._finds(plan, req.shown, reply, listed,
                                      parameter.is_numeric)
        for _given, why in refused:
            counts.fail(why)
        held = addressed.joined(held, more)
    claims = []
    for got in held:
        claim = reader.claim(plan, parameter, got, counts)
        if claim is not None:
            claims.append(claim)
    engine.keep(doc, parameter, claims)
    first = claims[0] if claims else {}
    return (isinstance(reply, dict), len(claims), not claims, False,
            str(first.get("value_raw") or first.get("value") or ""),
            str(first.get("quote") or ""))


def _kept_reply(engine, node: dict, scope, req: Request, prompt,
                payload: dict, reply, shape: dict, counts, noted: dict,
                into: dict) -> tuple:
    """The answer kept as the step's variable, after the step's own checks:
    one whose condition holds of the answer is asked again with its
    sentence, as often as the step's follow-ups say (owner 2026-11-12:
    "eine extra Prüfung ... auf einfachem Niveau")."""
    reader = engine.reader
    name = into.get("var") or node.get("id")
    checks = engine.own_checks(node)
    for _ in range(reader.follow_ups() + 1):
        if not isinstance(reply, dict):
            break
        put(scope, name, reply, False)
        facts = joined_facts(engine.facts(scope), var_facts(scope))
        failed = [(sentence, label) for label, condition, sentence, _i
                  in checks if conditions.holds(condition, facts)]
        if not failed:
            break
        for _sentence, label in failed:
            counts.fail(f"check:{label}")
        reply = reader.follow_own(
            prompt, payload, req.plan.document_id, shape,
            example_of(reply_schema(node)), reply,
            [{"why": sentence} for sentence, _label in failed], counts,
            **noted)
    value = reply if isinstance(reply, dict) else None
    put(scope, name, value, bool(into.get("lasting")))
    if bool(into.get("lasting")):
        scope.values.pop(PAGE + name, None)
    words = ""
    if isinstance(value, dict):
        first = next(iter(value.values()), "")
        words = first if isinstance(first, str) else json.dumps(
            first, ensure_ascii=False)
    return (value is not None, 1 if value else 0, not value, False, words,
            "")


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
