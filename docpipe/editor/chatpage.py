"""
chatpage.py: The drawing of the chat in the Flow tab (owner request
2026-11-14: "den Chat Flow so zu bearbeiten, wie auch der Extraktionsflow,
sodass man sich sehr einfach einen eigenen Chat Flow bauen kann").

The tab draws it as it draws a flow of a follow-up pass: the profile's own
`chat.json` where it has one, else the one it extends, else the one the
package brings (`inference.chatflow`), with the chat's library, the
conditions about its variables, what the check says and the variables
there before each step. A save writes the profile's own file only where
the drawing differs from what it inherits, and only where the file is as
the page loaded it.

A try runs one turn of the drawing on the page with made-up answers, and
nothing of the plan or the question is sent (`try_turn`): every request is
answered here in its own form ("nothing": each key empty; "example": the
example of its form), the search gives the passages of a document of the
corpus database (or of a plan made up from the examples of the spec) in the
document's order, no embedder, no reranker and no sandbox is asked, and the
harvest, the graph and the comparison of other plans say that they are not
there. The tokenizer that counts the batches is the chat's, loaded as the
chat loads it.
What comes back: each step with what it gave, each request with the step
that asked it, its prompt and the made-up answer, and the message the page
would show.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import json
import threading
from types import SimpleNamespace
from typing import Callable, Optional

from .. import prompts as prompt_files
from ..extraction import general
from ..inference import chatflow, config, llm_client
from .flow import CR, LF, _text, sha256

MODES = ("nothing", "example")
STAGE = "inference"
# What a try searches where the body names no parts: the parts a try can
# show, the descriptions of tables and figures and not their pictures.
TRY_SCOPES = (config.SCOPE_HEADINGS, config.SCOPE_TEXT,
              config.SCOPE_TABLES_TEXT, config.SCOPE_FIGURES_TEXT)
ROUTES = ("auto", "harvest", "graph", "documents")


class Refused(ValueError):
    """What cannot be tried, said."""


# -- the drawing ------------------------------------------------------------------

def library() -> dict:
    """The chat's library in the form of the flow's: its boxes, its one
    loop (each entry of a list), its variables, no presets, forms or
    targets."""
    from ..extraction import blocks
    whole = chatflow.catalogue()
    return {"flow": chatflow.FLOW, "boxes": whole["boxes"],
            "frames": whole["frames"],
            "each": {"list": chatflow.EACH_LIST},
            "each_titles": {"list": blocks.EACH_TITLES["list"]},
            "which": {}, "orders": {}, "order_words": {}, "arrows": {},
            "variables": whole["variables"],
            "items": {"list": ["item", None]}, "start": whole["start"],
            "presets": [], "forms": {}, "targets": {},
            "checks": whole["checks"]}


def drawn(profile, own_raw: Optional[bytes]) -> list:
    """The drawing the page starts from: the profile's own file where it
    has one, else the one it runs."""
    if own_raw is not None:
        return chatflow.parse(own_raw, str(chatflow.path_of(profile)))
    return chatflow.load(profile).tree


def below(profile) -> Optional[list]:
    """The drawing the profile would run without its own file."""
    found = chatflow.inherited(profile)
    return found.tree if found is not None else None


def prompt_ids(profile) -> list:
    """The prompts of the profile a box of the chat can name."""
    from . import prompts as prompt_page
    return sorted(row["id"] for row in prompt_page.listing(profile)
                  if str(row["id"]).startswith(STAGE + "/"))


def prompts_asked(profile) -> dict:
    """{request a box asks: {"id", "written", "owner"}} of every box of the
    chat whose request has a prompt of its own, as the flow's page says it
    (`flow._prompts`)."""
    from . import prompts as prompt_page
    owners = {row["id"]: row["owner"]
              for row in prompt_page.listing(profile)}
    out = {}
    for box in chatflow.LIBRARY.values():
        if box.asks and box.asks not in out:
            prompt_id = f"{STAGE}/{box.asks}"
            owner = owners.get(prompt_id)
            out[box.asks] = {"id": prompt_id, "written": owner is not None,
                             "owner": owner}
    return out


def view(profile, own_raw: Optional[bytes], shown: Callable) -> dict:
    """The drawing of the chat as the page draws it. *own_raw* are the
    bytes of the profile's own file, None where it has none; *shown(path)*
    a path as the user sees it."""
    tree = drawn(profile, own_raw)
    inherited = below(profile)
    owner = profile.name if own_raw is not None else next(
        (name for name, path in chatflow.line(profile)[1:]
         if path.is_file()), chatflow.DEFAULT_NAME)
    return {"file": shown(chatflow.path_of(profile)),
            "exists": own_raw is not None,
            "base": sha256(own_raw) if own_raw is not None else None,
            "starts_from": owner, "tree": tree, "inherited_tree": inherited,
            "library": library(),
            "conditions": chatflow.conditions_catalogue(),
            "problems": chatflow.problems(tree, profile),
            "available": chatflow.available_by_id(tree),
            "prompt_ids": prompt_ids(profile),
            "prompts": prompts_asked(profile),
            "routes": chatflow.routes_in(tree), "modes": list(MODES),
            "scopes": list(config.SCOPE_TO_EMBEDDING_TYPES),
            "try_scopes": list(TRY_SCOPES)}


def judge(profile, own_raw: Optional[bytes], shown_name: str,
          tree=None) -> dict:
    """What a save of the drawing *tree* would do: {"ok", "errors": [{"id",
    "message"}], "file", "writes", "diff", "text", "available",
    "routes"}. A drawing the run cannot do is refused with every reason,
    each at its step. A profile that extends another writes the file only
    where the drawing differs from what it inherits."""
    old = _text(own_raw)
    drawing = drawn(profile, own_raw) if tree is None else tree
    errors = [{"name": None, "id": one["id"], "message": one["message"]}
              for one in chatflow.problems(drawing, profile)]
    inherited = below(profile)
    newline = CR + LF if (CR + LF).encode() in (own_raw or b"") else LF
    if errors:
        new = old
    elif inherited is not None and drawing == inherited:
        new = None
    else:
        new = chatflow.dump(drawing)
    writes = ("unchanged" if new == old else "created" if old is None
              else "removed" if new is None else "changed")
    diff = [] if writes == "unchanged" else list(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(), shown_name,
        shown_name, lineterm=""))
    return {"ok": not errors, "errors": errors, "file": shown_name,
            "writes": writes, "diff": diff,
            "text": None if new is None else new.replace(LF, newline),
            "available": chatflow.available_by_id(drawing)
            if isinstance(drawing, list) else {},
            "routes": chatflow.routes_in(drawing)
            if isinstance(drawing, list) else []}


def save(profile, own_raw: Optional[bytes], base: Optional[str],
         shown_name: str, tree=None) -> tuple:
    """(what the page is told, the bytes to write or None, whether the file
    is to be removed): bytes come back only for a drawing the run can do,
    and only where the file is as the page loaded it (*base*, the sha256 of
    its bytes, None where it had none)."""
    report = judge(profile, own_raw, shown_name, tree)
    text = report.pop("text")
    if not report["ok"]:
        return {"saved": False, "reason": "invalid",
                "errors": report["errors"],
                "message": "; ".join(e["message"]
                                     for e in report["errors"])}, None, False
    if base != (sha256(own_raw) if own_raw is not None else None):
        return {"saved": False, "reason": "moved",
                "message": "the file changed on disk since the page loaded "
                           "it; reload it before saving"}, None, False
    told = {"saved": True, "writes": report["writes"], "file": shown_name}
    if report["writes"] == "unchanged":
        return {**told, "base": base}, None, False
    if text is None:
        return {**told, "base": None}, None, True
    written = text.encode("utf-8")
    return {**told, "base": sha256(written)}, written, False


# -- the try ----------------------------------------------------------------------

def nothing(schema):
    """The answer of the form *schema* that names nothing: every key of
    it, each empty (an empty list or text, 0, off, the last of a choice of
    words, the first of several forms)."""
    if not isinstance(schema, dict):
        return None
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            return nothing(schema[key][0])
    if "enum" in schema:
        return schema["enum"][-1] if schema["enum"] else None
    if "const" in schema:
        return schema["const"]
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if "object" in kinds or "properties" in schema:
        return {key: nothing(sub)
                for key, sub in (schema.get("properties") or {}).items()}
    if "array" in kinds:
        return []
    if "integer" in kinds or "number" in kinds:
        return 0
    if "boolean" in kinds:
        return False
    if "string" in kinds:
        return ""
    return None


def _message_text(messages: list) -> str:
    """The words of the last message a request sends; a picture is named,
    not shown."""
    if not messages:
        return ""
    content = messages[-1].get("content")
    if isinstance(content, str):
        return content
    parts = []
    for part in content or ():
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(part.get("text") or "")
        elif isinstance(part, dict):
            parts.append(f"[{part.get('type')}]")
    return "\n".join(parts)


class MadeUp:
    """The model of a try: answers each request in its own form, keeps
    what it was asked and by which step, and sends nothing."""

    def __init__(self, mode: str):
        self.mode = mode
        self.asked: list = []
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kw):
        shape = kw.get("response_format") or {}
        named = shape.get("json_schema") or {}
        schema = named.get("schema") if isinstance(named, dict) else None
        if isinstance(schema, dict):
            reply = (general.example_of(schema) if self.mode == "example"
                     else nothing(schema))
        else:
            reply = {}
        with self._lock:
            self.asked.append({
                "step": chatflow.STEP.get(),
                "request": named.get("name") or shape.get("type") or "text",
                "prompt": _message_text(kw.get("messages") or []),
                "reply": reply})
        content = json.dumps(reply, ensure_ascii=False)
        message = SimpleNamespace(content=content, reasoning=None,
                                  refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=message, finish_reason="stop")], usage=None)


EXAMPLE_LABEL = "Example plan"


def example_sources(spec=None) -> list:
    """The passages of a plan made up from the examples of *spec*
    (`flowtry.example_sources`); without a spec, one passage that says it
    is made up."""
    from ..extraction.pipeline import Source
    from . import flowtry
    if spec is not None:
        return flowtry.example_sources(spec)
    return [Source("section", 1, "Example plan, made up: this profile has "
                                 "no spec whose examples a try could read.",
                   {"document_id": 0, "page": 1,
                    "section_title": EXAMPLE_LABEL})]


def _hit(source, rank: int) -> dict:
    meta = source.provenance or {}
    return {"owner_kind": source.owner_kind, "owner_id": source.owner_id,
            "title": meta.get("section_title") or "", "text": source.text,
            "page_number": meta.get("page"), "image_path": None,
            "section_number": meta.get("section_number"),
            "section_title": meta.get("section_title"),
            "document_id": meta.get("document_id"),
            "score": round(1.0 - rank / 1000.0, 3)}


class _Ranker:
    """A reranker that keeps the search's order."""

    def scores(self, document_id, probe, views):
        return [float(len(views) - at) for at in range(len(views))]


def _not_run(code: str, context: Optional[dict] = None) -> dict:
    return {"ok": False, "stdout": "", "stderr": "", "exit_code": None,
            "error": "not run: a try runs no code", "sandbox": True}


class TryServices(chatflow.Services):
    """What a try's turn runs on: made-up passages, nothing else."""

    def __init__(self, profile, hits: list, label: str):
        from ..inference import wording
        self.profile = profile
        self.hits = hits
        self.label = label
        self.words = dict(wording.ui(profile))
        self.searched: list = []

    def corpus(self, image):
        from ..inference import answer

        def retrieve(conn, index, id_to_pos, document_id, embedding_types,
                     query_vec, top_k, text=None, lexical_index=None,
                     exclude=frozenset()):
            self.searched.append({"top_k": top_k, "words": text,
                                  "skipped": len(exclude)})
            found = [dict(one) for one in self.hits
                     if (one["owner_kind"], one["owner_id"]) not in exclude]
            return found[:top_k] if top_k else found

        return answer.Corpus(conn=None, index=None, id_to_pos={},
                             embed=lambda item: ([0.0], False),
                             resolve_image=lambda path: None, log_conn=None,
                             lexical=None,
                             document_label=lambda i: self.label,
                             retrieve=retrieve)

    def values_outcome(self, task, document_id, history, how="auto"):
        return None

    def values_reason(self, reason):
        return self.words.get("values_" + str(reason)) or str(reason)

    def kg_turn(self, task, document_id):
        return {"route": "kg_empty", "reason": "not_tried"}

    def kg_note(self, reason):
        return "a try asks no graph"

    def graph(self):
        try:
            from pyoxigraph import Store
        except ImportError:
            raise chatflow.Stop("a try of the graph needs pyoxigraph") \
                from None
        return Store(), {}

    def compare(self, task, documents, scopes, as_json, histories):
        return {"content": "a try compares no plans", "rows": []}

    def reranker(self):
        return _Ranker()

    def sandbox(self):
        return _not_run

    def prompt(self, prompt_id):
        return prompt_files.load(prompt_id, self.profile)


_ONE_AT_A_TIME = threading.Lock()


def _shown(value, most: int = 600):
    """A value as the try shows it: long texts cut, long lists counted."""
    if isinstance(value, str):
        return value if len(value) <= most else value[:most] + " ..."
    if isinstance(value, (list, tuple)):
        if len(value) > 12:
            return [_shown(one) for one in value[:12]] + [
                f"... {len(value) - 12} more"]
        return [_shown(one) for one in value]
    if isinstance(value, dict):
        return {key: _shown(one) for key, one in value.items()}
    return value


def try_turn(profile, tree: list, sources: list, *, question: str,
             route: str = "auto", as_json: bool = False,
             scopes: Optional[list] = None, mode: str = "nothing",
             label: str = EXAMPLE_LABEL) -> dict:
    """One turn of the drawing *tree* on the passages *sources*
    (`flowtry.sources_of`, `flowtry.example_sources`) with made-up answers;
    see the module's head. Refused where the drawing cannot run or the
    question is empty."""
    if mode not in MODES:
        raise Refused(f"mode is one of {', '.join(MODES)}")
    if not isinstance(question, str) or not question.strip():
        raise Refused("a try needs a question")
    said = chatflow.problems(tree, profile)
    if said:
        raise Refused("; ".join(f"{one['id']}: {one['message']}"
                                for one in said))
    hits = [_hit(one, rank) for rank, one in enumerate(sources)]
    document_id = hits[0]["document_id"] if hits else None
    services = TryServices(profile, hits, label)
    start = {"question": question.strip(), "history": [], "histories": {},
             "documents": [{"id": document_id, "label": label}],
             "document": {"id": document_id, "label": label},
             "scopes": list(scopes or TRY_SCOPES), "image": None,
             "image_only": False, "route": route or "auto",
             "as_json": bool(as_json)}
    model = MadeUp(mode)
    ran: list = []
    error = None
    reply = None
    with _ONE_AT_A_TIME, llm_client.answered_by(model):
        try:
            reply = chatflow.run(tree, start, services, trace=ran)
        except chatflow.ChatFlowError as exc:
            raise Refused(str(exc)) from None
        except Exception as exc:          # what the step did, said
            error = f"{type(exc).__name__}: {exc}"
    message = None
    if reply is not None:
        message = {key: _shown(value) for key, value in reply["message"].items()
                   if key in ("content", "extra", "citations", "faults",
                              "route", "phrase", "as_json")}
    return {"steps": [{"id": one.id, "box": one.box,
                       "gave": _shown(one.gave)} for one in ran],
            "requests": [{**one, "prompt": _shown(one["prompt"], 4000),
                          "reply": _shown(one["reply"])}
                         for one in model.asked],
            "searched": services.searched, "message": message,
            "error": error, "passages": len(hits),
            "routes": chatflow.routes_in(tree)}


__all__ = ["view", "judge", "save", "try_turn", "library", "MODES",
           "Refused", "nothing", "MadeUp", "example_sources",
           "EXAMPLE_LABEL"]
