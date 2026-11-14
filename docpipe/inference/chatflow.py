"""
chatflow.py: One turn of the chat as the profile's drawing of it says
(owner request 2026-11-14: "den Chat Flow so zu bearbeiten, wie auch der
Extraktionsflow, sodass man sich sehr einfach einen eigenen Chat Flow bauen
kann", and "der Chat sollte aber auch ein paar Extra blöcke bekommen wie
outputformat etc., sodass man wirklich auch neue Routen implementieren
kann").

The drawing is `chat.json` of the profile, else of the profile it extends,
else the one the package brings (`builtin/default/chat.json`): a list of
steps, each a box of the library (`LIBRARY`) or a frame. "if" takes the
first way whose condition holds, else the last; "each" runs its steps for
each entry of a list, one after the other; "round" runs its steps again, at
most N times, until a condition holds; "together" runs every way at the
same time and goes on when all are done. The run does what the drawing says
and nothing else. The drawing the package brings is the turn as the code
asked it before there was a drawing, request for request.

A turn has variables (`VARIABLES`): what the page gives it (the question,
the turns before on the same document, the documents chosen, the parts
searched, an image, the route the sidebar chose, whether the answer is to
be JSON) and what its boxes give (the search sentence, the hits, the
statements, the answer, ...). A box takes its inputs from them and puts its
outputs into them; a condition reads them (`conditions` of the flow, its
subject "the variable"), and the check of a drawing refuses a box whose
input no step before it gives. What a box does is the code it names
(`answer`, `llm_client`, `values_route`, `kg_route`, `compare`); which box
runs when, for what and how often is the drawing's.

What the turn needs from where it runs (the corpus, the harvest, the graph,
the words of the page, the spinner) comes in as `Services`; the chat page
gives its own (`docpipe.app.app`), a test or the editor's try gives made-up
ones. The turn ends at "Show the answer" (`show`): what it shows is the
message the page draws.

Author: Felix Vossel
"""
from __future__ import annotations

import contextlib
import contextvars
import copy
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..extraction import conditions
from ..extraction.blocks import (CHOICE, CODE, CONDITION, JSON, NUMBER,
                                 PATH, PATHS, PROMPT, SCHEMA, SWITCH, TEXT,
                                 VARNAME, VARNAMES, Box, Setting, _box_entry)
from ..extraction.variables import Var

log = logging.getLogger(__name__)

FILE = "chat.json"
KEY = "chat"
DEFAULT = Path(__file__).resolve().parent.parent / "builtin" / "default" / FILE
DEFAULT_NAME = "default"
FLOW = "chat"
FRAMES = ("each", "round", "if", "together")
# What the loop of the chat does, as the page says it: one entry after
# another, never side by side (each entry is the same variable).
EACH_LIST = ("The steps inside run once for each entry of a list, such as "
             "the hits of a search or a list the model wrote, one entry "
             "after another; inside, the entry has the name you give it. "
             "To change it: choose the list, the name of its entry and a "
             "condition, or switch the loop off.")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A prompt setting that names a prompt file of the profile ("stage/name");
# any other text is the prompt itself.
PROMPT_ID = re.compile(r"[a-z_]+/[A-Za-z0-9_/]+")
# The step of the drawing that runs in this context, for whoever asks on its
# behalf (the editor's try names the step of each request).
STEP: contextvars.ContextVar = contextvars.ContextVar("chat_step",
                                                      default=None)


class ChatFlowError(ValueError):
    """A drawing the run cannot do; `problems` says every reason."""


# -- the variables of a turn ------------------------------------------------------

_TURN = {"type": "object", "properties": {
    "task": {"type": "string"}, "answer": {"type": "string"},
    "examined": {"type": "array"}, "recheck": {"type": "boolean"}}}
_DOCUMENT = {"type": "object", "properties": {
    "id": {"type": ["integer", "null"]}, "label": {"type": "string"}}}
_HIT = {"type": "object", "properties": {
    "owner_kind": {"enum": ["section", "table", "figure"]},
    "owner_id": {"type": "integer"}, "document_id": {"type": "integer"},
    "text": {"type": "string"}, "page": {"type": ["integer", "null"]}}}
_STATEMENT = {"type": "object", "properties": {
    "text": {"type": "string"}, "quote": {"type": "string"},
    "citation": {"type": "integer"}}}
_CITATION = {"type": "object", "properties": {
    "n": {"type": "integer"}, "quote": {"type": "string"},
    "page": {"type": ["integer", "null"]}, "visual": {"type": "boolean"}}}

VARIABLES = {var.name: var for var in (
    Var("question", "the question", "What the user typed: the task the "
        "answer is for.", {"type": "string"}),
    Var("history", "the turns before", "The turns before on the same "
        "document, the last five: question, search sentence, answer and the "
        "sources the model read. A follow-up question is read with them.",
        {"type": "array", "items": _TURN}),
    Var("histories", "the turns before, per document",
        "The turns before of every document, for a comparison.",
        {"type": "object"}),
    Var("documents", "the documents chosen", "The documents the user "
        "chose, each with its id and the name the page shows; more than one "
        "is a comparison.", {"type": "array", "items": _DOCUMENT}),
    Var("document", "the document", "The one document asked, its id None "
        "where the whole corpus is asked.", _DOCUMENT),
    Var("scopes", "the parts searched", "Which kinds of passages the user "
        "ticked: headings, text, tables and figures, each with or without "
        "its picture.", {"type": "array", "items": {"type": "string"}}),
    Var("image", "the image of the question", "A picture the user added to "
        "the question, or none.", {"type": "boolean"}),
    Var("image_only", "only the image", "Whether the picture alone is "
        "searched with, and not the words of the question.",
        {"type": "boolean"}),
    Var("route", "the route chosen", "What the sidebar chose: auto, "
        "harvest, graph or documents.",
        {"enum": ["auto", "harvest", "graph", "documents"]}),
    Var("as_json", "answer as JSON", "Whether the user asked for the answer "
        "as JSON.", {"type": "boolean"}),
    Var("phrase", "the search sentence", "A sentence as a document would "
        "print the answer; the search looks for passages like it.",
        {"type": "string"}),
    Var("recheck", "looks again", "Whether the question asks to look again "
        "(\"schau noch einmal nach\"): the search then skips the sources the "
        "turns before read.", {"type": "boolean"}),
    Var("vector", "the query's vector", "The search sentence (or the "
        "picture) as the embedding model writes it.", {"type": "array"}),
    Var("hits", "the hits", "The passages the search found, best first.",
        {"type": "array", "items": _HIT}),
    Var("batches", "the batches", "The best hits in batches that fit the "
        "model's context.", {"type": "array"}),
    Var("statements", "the statements", "What the model said about the "
        "sources, each statement with the quote it stands on; only those "
        "whose quote stands in their source are kept.",
        {"type": "array", "items": _STATEMENT}),
    Var("citations", "the citations", "The sources the kept statements "
        "stand on, numbered as the answer names them.",
        {"type": "array", "items": _CITATION}),
    Var("answer", "the answer", "What the page shows as the answer.",
        {"type": "string"}),
    Var("answer_text", "the answer as text", "The answer without list marks "
        "and citation numbers, as a follow-up question reads it.",
        {"type": "string"}),
    Var("harvest", "the answer from the harvest", "What the harvest holds "
        "for the question: the values and the answer read from their "
        "passages; none where it holds nothing.", {"type": "object"}),
    Var("harvest_reason", "why the harvest holds nothing", "no_store, "
        "no_parameter or no_values.", {"type": "string"}),
    Var("graph", "the answer from the graph", "The values of the graph for "
        "the question, or why it has none.", {"type": "object"}),
    Var("comparison", "the comparison", "One answer per document chosen, "
        "and the comparison of them.", {"type": "object"}),
    Var("rows", "the rows of a query", "What a query over the graph "
        "returned, one object per row.",
        {"type": "array", "items": {"type": "object"}}),
    Var("faults", "requests without a reply", "The requests of the turn "
        "that stayed unreadable, with their causes.",
        {"type": "array", "items": {"type": "object"}}),
    Var("item", "the entry", "One entry of the list a loop goes through.",
        {}),
    Var("round", "the round", "The number of the turn of a round.",
        {"type": "integer"}),
)}
# What a turn starts with: what the page gives.
START = ("question", "history", "histories", "documents", "document",
         "scopes", "image", "image_only", "route", "as_json")


def var(name: str) -> Optional[Var]:
    return VARIABLES.get(name)


def variables_catalogue() -> dict:
    return {name: {"label": one.label, "says": one.says,
                   "schema": one.schema, "lasting": True}
            for name, one in VARIABLES.items()}


# -- the library ----------------------------------------------------------------

def _s(key, kind, label, default=None, help="", choices=(), words=()):
    return Setting(key, kind, label, default=default, help=help,
                   choices=tuple(choices), words=tuple(words))


VISUAL = _s("visual", CHOICE, "kind of search sentence", "auto",
            "A search for tables and figures finds them better with a "
            "sentence like a caption. Auto: a caption where every part "
            "searched is a table or a figure, else a sentence of the text.",
            ("auto", "always", "never"),
            ("by the parts searched", "always like a caption",
             "always like the text"))
TOP_K = _s("top_k", NUMBER, "hits, at most", None,
           "How many passages the search returns, best first. Empty: the "
           "setting TOP_K of the installation (50).")
WORDS = _s("words", SWITCH, "search the words too", True,
           "On: the words of the question and the search sentence are "
           "searched in the word index as well, and the two rankings are "
           "merged. Off: the search is by meaning alone.")
SKIP = _s("skip_examined", SWITCH, "skip what was read before", True,
          "On: a question that asks to look again skips the sources the "
          "turns before read, back to the question it repeats.")
MOST = _s("most", NUMBER, "sources, at most", None,
          "How many of the best hits are read. Empty: the setting "
          "MAX_CHUNK_ATTEMPTS of the installation (10).")
CONTEXT = _s("context_tokens", NUMBER, "tokens per batch, at most", None,
             "How many tokens of sources one request shows. Empty: the "
             "setting ANSWER_CONTEXT_TOKENS of the installation (10000).")
UNTIL = _s("until_complete", SWITCH, "stop when the answer is complete",
           True, "On: a further batch is asked only while the model says "
           "the answer is not complete. Off: every batch is asked.")
READOFF_MOST = _s("most", NUMBER, "figures, at most", None,
                  "How many figures a value was read off are read again, "
                  "one by one. Empty: the setting READOFF_MAX_CALLS of the "
                  "installation (3).")
FORM = _s("form", CHOICE, "output format", "json_question",
          "JSON as the question asks: the model writes the checked answer "
          "in the shape the question describes. JSON by a schema: the model "
          "writes it in the shape of the schema set here. List: one line "
          "per statement with its citation. Table: a table of the "
          "statements and their sources. List and table ask no model.",
          ("json_question", "json_schema", "list", "table"),
          ("JSON as the question asks", "JSON by a schema", "list",
           "table"))
FORM_SCHEMA = _s("schema", SCHEMA, "schema of the JSON", None,
                 "The shape of the JSON, for the format \"JSON by a "
                 "schema\".")
FORM_FROM = _s("from", PATH, "text to format", "answer_text",
               "The variable whose text is put into the format: the answer "
               "as text, or what another step wrote.")
HOW = _s("how", CHOICE, "how the harvest is asked", "auto",
         "By meaning: the harvest's values are searched with the vector of "
         "the search sentence and the model picks among them. By questions: "
         "the model is asked which field and which dimensions the question "
         "names. Auto: by meaning where the harvest has its vectors, else "
         "by questions.", ("auto", "meaning", "questions"),
         ("by meaning where there are vectors, else by questions",
          "by meaning", "by questions"))
ALONE = _s("alone", SWITCH, "say why there is nothing", False,
           "On: where the harvest holds nothing for the question, the turn "
           "says why (nothing configured, no field named, no values). Off: "
           "nothing is said, as beside the search of the documents.")
QUERY = _s("query", PATH, "variable with the query", "query",
           "The variable that holds the query text (SPARQL), for instance "
           "what a step \"Ask the model\" wrote.")
INTO = _s("into", VARNAME, "into the variable", None,
          "The variable the result is put into.")
OPTIONS = _s("options", JSON, "the ways", None,
             "The ways the model chooses from: each a name and a sentence "
             "that says when it is the right one, as {\"name\": "
             "\"sentence\"}.")
LINE = _s("line", TEXT, "the question to the model",
          "Which of these ways fits the user's question?",
          "The one line the request asks.")
PROMPT_S = _s("prompt", PROMPT, "prompt", None,
              "The prompt of the request: the id of a prompt file of the "
              "profile, or a text of its own. {{name}} stands for the "
              "variable of that name.")
INPUTS_S = _s("inputs", VARNAMES, "variables shown", (),
              "The variables the request shows, each under its name.")
REPLY = _s("schema", SCHEMA, "form of the reply",
           {"type": "object", "properties": {"answer": {"type": "string"}},
            "required": ["answer"]},
           "The JSON schema of the reply; the model writes in it.")
TEMPERATURE = _s("temperature", NUMBER, "temperature", 0,
                 "0: the same request gets the same reply.")
CODE_S = _s("code", CODE, "code", None,
            "Python that defines run(inputs) and returns a dict of the "
            "outputs.")
CODE_FROM = _s("code_from", PATH, "variable with the code", None,
               "Where the code comes from instead: a variable, for instance "
               "what a step \"Ask the model\" wrote.")
OUTPUTS_S = _s("outputs", VARNAMES, "outputs", (),
               "The outputs run(inputs) returns, each a variable.")
SET_NAME = _s("name", VARNAME, "variable", None, "The variable that is set.")
SET_FROM = _s("from", PATH, "from the variable", None,
              "Where its value comes from: a variable or a part of one.")
SET_VALUE = _s("value", JSON, "or the value", None,
               "A value of its own, where no variable is named.")
LIST_S = _s("list", PATH, "the list", None, "The list that is filtered.")
KEEP = _s("keep", CONDITION, "keep where", None,
          "The condition an entry has to meet; it reads the entry as "
          "\"item\".")
LISTS = _s("lists", PATHS, "the lists", (), "The lists that are joined.")
TEXT_S = _s("text", TEXT, "text of its own", "",
            "A text to show instead of the answer; {{name}} stands for the "
            "variable of that name. Empty: the answer as the turn found it.")
SHOW_VARS = _s("values", VARNAMES, "variables shown below", (),
               "Variables shown below the answer as they are.")
LABEL = _s("label", TEXT, "what the spinner says", "",
           "The words beside the spinner while the ways run. Empty: the "
           "page's word for preparing.")

CHECKS = ("the quote stands in the source it names",
          "a quote is long enough to point to one place (12 characters)")


def _box(type_, label, group, says, code, inputs=(), outputs=(),
         settings=(), fixed="", switch=True, top=False, marks=(),
         asks=None):
    return Box(type_, label, group, takes="", gives="", says=says,
               code=code, asks=asks, settings=tuple(settings), fixed=fixed,
               switch=switch, top=top, marks=tuple(marks), flow=FLOW,
               inputs=tuple(inputs), outputs=tuple(outputs))


LIBRARY = {box.type: box for box in (
    _box("question", "The user's question", "start",
         "The question as the page gives it: the words, the turns before "
         "on the same document, the documents chosen, the parts searched, "
         "an image and the route the sidebar chose.",
         "docpipe/app/app.py (main)", outputs=START,
         fixed="Every turn starts with the question.", switch=False,
         top=True),
    # -- the routes
    _box("choose", "Choose a way", "routes",
         "The model chooses which of the ways set here fits the question; "
         "the name of the way goes into a variable, which a branching "
         "after it reads.", "docpipe/inference/llm_client.py (choose)",
         inputs=("question",), outputs=("way",),
         settings=(OPTIONS, LINE,
                   _s("prompt", PROMPT, "prompt", "inference/choose_way",
                      "The prompt of the request: the id of a prompt file "
                      "of the profile, or a text of its own."),
                   _s("into", VARNAME, "into the variable", "way",
                      "The variable the name of the way is put into.")),
         asks=None),
    _box("harvest", "Ask the harvest", "routes",
         "What the harvest holds for the question, and the answer read "
         "from the passages its values were read from, each statement "
         "checked against its passage.",
         "docpipe/inference/values_route.py, answer.answer_from_values",
         inputs=("question", "document", "history", "image_only"),
         outputs=("harvest", "harvest_reason"), settings=(HOW, ALONE),
         asks="pick_values"),
    _box("graph", "Ask the graph", "routes",
         "The model reads which field and which dimensions the question "
         "names, and the graph's values for them are shown with their "
         "evidence.", "docpipe/inference/kg_route.py (answer_from_graph)",
         inputs=("question", "document"), outputs=("graph",),
         asks=None),
    _box("graph_query", "Run a query on the graph", "routes",
         "A SPARQL query from a variable run on the graph; its rows go "
         "into a variable. With a step \"Ask the model\" before it that "
         "writes the query, this is a route of its own.",
         "docpipe/inference/kg_route.py (run_query)",
         inputs=("query",), outputs=("rows",),
         settings=(QUERY, _s("into", VARNAME, "into the variable", "rows",
                             "The variable the rows are put into."))),
    _box("compare", "Compare the documents", "routes",
         "The question to each document chosen, each with its own search "
         "and citations, then one request that compares the answers.",
         "docpipe/inference/compare.py (compare_documents)",
         inputs=("question", "documents", "scopes", "as_json",
                 "histories"), outputs=("comparison",), asks="compare"),
    # -- the search
    _box("phrase", "Write the search sentence", "search",
         "The model writes a sentence as a document would print the "
         "answer, with the turns before; it also says whether the question "
         "asks to look again. A question that is only an image needs "
         "none.", "docpipe/inference/answer.py (make_anchor)",
         inputs=("question", "scopes", "history", "image", "image_only"),
         outputs=("phrase", "recheck"), settings=(VISUAL,), asks="phrase"),
    _box("embed", "Embed the search sentence", "search",
         "The search sentence, the image or both as the embedding model "
         "writes them; the same words a second time come from the cache.",
         "docpipe/inference/answer.py (embed_anchor)",
         inputs=("phrase",), outputs=("vector",)),
    _box("search", "Search the corpus", "search",
         "The passages of the parts searched, of the document asked or of "
         "the whole corpus, by meaning and by words, best first.",
         "docpipe/inference/answer.py (search_hits)",
         inputs=("vector", "question", "phrase", "document", "scopes",
                 "history", "recheck"), outputs=("hits",),
         settings=(TOP_K, WORDS, SKIP)),
    _box("rerank", "Order the hits by a text", "search",
         "The reranker orders the hits again by the search sentence.",
         "docpipe/inference/rerank.py (Reranker)",
         inputs=("hits", "phrase"), outputs=("hits",),
         settings=(_s("most", NUMBER, "hits, at most", None,
                      "How many of the hits are ordered; the rest follow "
                      "as they were. Empty: all."),)),
    # -- the answer
    _box("pack", "Batches that fit the context", "answer",
         "The best hits in batches, each as large as the model's context "
         "takes.", "docpipe/inference/answer.py (pack)",
         inputs=("hits",), outputs=("batches",),
         settings=(MOST, CONTEXT)),
    _box("statements", "Ask for statements with evidence", "answer",
         "Each batch is asked for statements, each with the quote it "
         "stands on; a later batch is told the statements already checked "
         "and adds only new ones. A statement is kept only where its quote "
         "stands in its source.", "docpipe/inference/answer.py "
         "(ask_batches)", inputs=("question", "batches", "document",
                                  "history"),
         outputs=("statements", "faults"), settings=(UNTIL,),
         marks=CHECKS, asks="answer_head"),
    _box("repeats", "Take out repeated statements", "answer",
         "Where a batch was asked before the statements of the one before "
         "it were known, one request names the statements that say again "
         "what an earlier one said, and they are taken out.",
         "docpipe/inference/answer.py (drop_repeats)",
         inputs=("statements",), outputs=("statements",), asks="repeats"),
    _box("readoff", "Read figures again", "answer",
         "Each value read off a figure is read again in a request that "
         "shows that one figure alone.",
         "docpipe/inference/answer.py (refine_readoff)",
         inputs=("statements",), outputs=("citations",),
         settings=(READOFF_MOST,), asks="readoff"),
    _box("assemble", "The answer from the statements", "answer",
         "The kept statements in the order they were made, a sentence or "
         "a list, each with the number of its citation; where none was "
         "kept, the turn says why.",
         "docpipe/inference/answer.py (assemble)",
         inputs=("statements",),
         outputs=("answer", "answer_text", "citations")),
    _box("compute", "Compute in the sandbox", "answer",
         "Python run in the sandbox with variables as its inputs; what it "
         "prints goes into a variable.",
         "docpipe/inference/code_exec.py (run_code)",
         outputs=("computed",),
         settings=(CODE_S, CODE_FROM, INPUTS_S,
                   _s("into", VARNAME, "into the variable", "computed",
                      "The variable the run's output is put into."))),
    # -- the output
    _box("format", "Output format", "output",
         "The answer put into the form set here: JSON as the question "
         "describes it, JSON by a schema, a list or a table.",
         "docpipe/inference/answer.py (json_answer), "
         "llm_client.format_by_schema",
         inputs=("question",), outputs=("answer",),
         settings=(FORM, FORM_SCHEMA, FORM_FROM), asks="json_format"),
    _box("show", "Show the answer", "output",
         "What the page shows for the turn: the answer with its citations, "
         "the harvest's values, the graph's, the comparison, or why there "
         "is none; with a text of its own, that text.",
         "docpipe/inference/chatflow.py (compose)",
         settings=(TEXT_S, SHOW_VARS)),
    # -- logic
    _box("ask", "Ask the model", "logic",
         "One request with a prompt of its own, the variables it shows and "
         "the form of its reply; the reply goes into a variable.",
         "docpipe/inference/llm_client.py (_ask)",
         outputs=("reply",),
         settings=(PROMPT_S, INPUTS_S, REPLY, TEMPERATURE,
                   _s("into", VARNAME, "into the variable", "reply",
                      "The variable the reply is put into.")),
         asks=None),
    _box("set", "Set a variable", "logic",
         "A variable set from another one or to a value of its own.",
         "docpipe/inference/chatflow.py (_set)",
         settings=(SET_NAME, SET_FROM, SET_VALUE)),
    _box("filter", "Keep the entries that meet a condition", "logic",
         "The entries of a list that meet the condition, into a variable.",
         "docpipe/inference/chatflow.py (_filter)",
         settings=(LIST_S, KEEP, INTO)),
    _box("merge", "Join lists", "logic",
         "Lists joined into one, in order.",
         "docpipe/inference/chatflow.py (_merge)", settings=(LISTS, INTO)),
    _box("python", "Own step in Python", "logic",
         "Python that defines run(inputs) and returns its outputs; it runs "
         "in the chat's own process.",
         "docpipe/extraction/general.py (run_python)",
         settings=(CODE_S, INPUTS_S, OUTPUTS_S)),
)}

# The steps whose requests a turn counts as its own (`faults` of the turn):
# the others keep theirs with what they give (the harvest, the graph, the
# comparison).
OWN_FAULTS = {"choose", "phrase", "embed", "search", "rerank", "pack",
              "statements", "repeats", "readoff", "assemble", "compute",
              "format", "ask"}


def catalogue() -> dict:
    """The library of the chat as the page shows it: its boxes in the
    form of the flow's (`blocks._box_entry`), its frames, its variables
    and what a condition can be about (the variables alone)."""
    return {"boxes": [_box_entry(b) for b in LIBRARY.values()],
            "frames": list(FRAMES), "variables": variables_catalogue(),
            "start": list(START), "checks": list(CHECKS)}


def conditions_catalogue() -> list:
    return [one for one in conditions.catalogue()
            if one["name"] == conditions.VAR]


# -- the drawing ------------------------------------------------------------------

def path_of(profile) -> Path:
    """Where *profile* writes its drawing of the chat."""
    return Path(profile.package_dir) / FILE


def line(profile) -> list:
    """[(profile name, path)] of the files a profile's drawing can stand
    in, nearest first, the package's own last."""
    if profile is None or getattr(profile, "package_dir", None) is None:
        return [(DEFAULT_NAME, DEFAULT)]
    lineage = getattr(profile, "lineage", None)
    profiles = lineage() if callable(lineage) else [profile]
    out = [(one.name, path_of(one)) for one in profiles]
    if not any(path == DEFAULT for _name, path in out):
        out.append((DEFAULT_NAME, DEFAULT))
    return out


def parse(raw, where: str = FILE) -> list:
    """The drawing of the text *raw* of a chat file; ChatFlowError where it
    is none."""
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes)
                          else raw)
    except ValueError as exc:
        raise ChatFlowError(f"{where} is no JSON: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get(KEY), list):
        raise ChatFlowError(f"{where} is an object with the drawing under "
                            f"\"{KEY}\"")
    return data[KEY]


def dump(tree: list, newline: str = "\n") -> str:
    text = json.dumps({KEY: tree}, indent=2, ensure_ascii=False) + "\n"
    return text if newline == "\n" else text.replace("\n", newline)


@dataclass
class Drawing:
    tree: list
    owner: str          # the profile whose file it is
    path: Path


def load(profile=None) -> Drawing:
    """The drawing a turn of *profile* runs: the nearest file of its line."""
    for name, path in line(profile):
        if path.is_file():
            return Drawing(parse(path.read_bytes(), str(path)), name, path)
    raise LookupError("no drawing of the chat: the package's own is missing")


def inherited(profile) -> Optional[Drawing]:
    """The drawing *profile* would run without its own file."""
    for name, path in line(profile)[1:]:
        if path.is_file():
            return Drawing(parse(path.read_bytes(), str(path)), name, path)
    return None


# -- the check --------------------------------------------------------------------

BOX_KEYS = ("id", "box", "set", "when", "off", "note")
FRAME_KEYS = {"each": ("id", "each", "list", "as", "steps", "when", "off",
                       "note"),
              "round": ("id", "round", "stop", "steps", "when", "off",
                        "note"),
              "if": ("id", "if", "else", "off", "note"),
              "together": ("id", "together", "when", "off", "note")}


def kind_of(node) -> str:
    if not isinstance(node, dict):
        return ""
    for kind in ("box",) + FRAMES:
        if kind in node:
            return kind
    return ""


def ways_of(node: dict) -> list:
    """The lists of steps inside a frame: one for "each" and "round", one
    per way of "if" (and its else) and of "together"."""
    kind = kind_of(node)
    if kind in ("each", "round"):
        return [node.get("steps") or []]
    if kind == "if":
        out = [way.get("steps") or [] for way in node.get("if") or ()
               if isinstance(way, dict)]
        if "else" in node:
            out.append(node.get("else") or [])
        return out
    if kind == "together":
        return [way.get("steps") or [] for way in node.get("together") or ()
                if isinstance(way, dict)]
    return []


def walk(tree: list):
    for node in tree or ():
        yield node
        if isinstance(node, dict):
            for steps in ways_of(node):
                yield from walk(steps)


def routes_in(tree: list) -> list:
    """The routes a drawing branches on: every word one of its conditions
    compares the variable "route" with, in the order they stand. The
    sidebar of the chat offers these (and "auto")."""
    out: list = []
    for node in walk(tree):
        if not isinstance(node, dict):
            continue
        found = [way.get("when") for way in node.get("if") or ()
                 if isinstance(way, dict)]
        if "stop" in node:
            found.append(node["stop"])
        for condition in found:
            if not isinstance(condition, dict) or len(condition) != 1:
                continue
            (_joiner, rows), = condition.items()
            for row in rows if isinstance(rows, list) else ():
                if not isinstance(row, dict) or row.get("of") != \
                        conditions.VAR or row.get("is") != "route":
                    continue
                said = row.get("value")
                for one in said if isinstance(said, list) else [said]:
                    if isinstance(one, str) and one and one not in out:
                        out.append(one)
    return out


def setting(node: dict, key: str):
    """The value of a box's setting: its own, else the library's default."""
    own = node.get("set") or {}
    if key in own:
        return own[key]
    box = LIBRARY.get(node.get("box"))
    for one in (box.settings if box else ()):
        if one.key == key:
            return one.default
    return None


def gives(node: dict) -> set:
    """The variables a box gives, its settings for a name included."""
    box = LIBRARY.get(node.get("box"))
    if box is None:
        return set()
    out = set(box.outputs)
    for key in ("into", "name"):
        named = setting(node, key)
        if isinstance(named, str) and named:
            # the box's default name gives way to the one set
            out.discard(next((one.default for one in box.settings
                              if one.key == key), None))
            out.add(named)
    if box.type in ("python",):
        out.update(one for one in setting(node, "outputs") or ()
                   if isinstance(one, str))
    return out


def takes(node: dict) -> set:
    """The variables a box needs a step before it to give."""
    box = LIBRARY.get(node.get("box"))
    if box is None:
        return set()
    need = set(box.inputs)
    for key in ("query", "from", "code_from", "list"):
        named = setting(node, key)
        if isinstance(named, str) and named:
            need.discard(next((one.default for one in box.settings
                               if one.key == key), None))
            need.add(named.split(".")[0])
    if box.type in ("ask", "python", "compute"):
        need.update(str(one).split(".")[0]
                    for one in setting(node, "inputs") or ())
    if box.type == "merge":
        need.update(str(one).split(".")[0]
                    for one in setting(node, "lists") or ())
    if box.type == "phrase":
        need -= {"image", "image_only"}     # from the question, always
    return {one for one in need if one}


def _setting_problem(box: Box, key: str, value) -> Optional[str]:
    from ..extraction import general
    one = next((s for s in box.settings if s.key == key), None)
    if one is None:
        return f"{box.label} has no setting {key!r}"
    if value is None:
        return None
    kind = one.kind
    if kind == NUMBER and (isinstance(value, bool)
                           or not isinstance(value, (int, float))
                           or value < 0):
        return f"{one.label}: a number of 0 or more"
    if kind == SWITCH and not isinstance(value, bool):
        return f"{one.label}: on or off"
    if kind == CHOICE and value not in one.choices:
        return f"{one.label}: one of {', '.join(one.choices)}"
    if kind in (TEXT, PROMPT) and not isinstance(value, str):
        return f"{one.label}: a text"
    if kind == VARNAME and (not isinstance(value, str)
                            or not NAME.match(value)):
        return f"{one.label}: a name of letters, digits and _"
    if kind == PATH and not isinstance(value, str):
        return f"{one.label}: the name of a variable"
    if kind in (VARNAMES, PATHS) and (
            not isinstance(value, (list, tuple))
            or not all(isinstance(v, str) and v for v in value)):
        return f"{one.label}: names of variables"
    if kind == SCHEMA:
        return general.schema_problem(value)
    if kind == CODE:
        return general.python_problem(value)
    if kind == CONDITION:
        said = conditions.problems(value)
        return said[0] if said else None
    return None


def problems(tree, profile=None) -> list:
    """[{"id", "message"}]: every reason the drawing *tree* cannot run, at
    the step it is about; with *profile*, also each prompt it names that
    the profile does not have. [] where it can."""
    return _form_problems(tree, profile) or _inputs_problems(tree)


def available_by_id(tree) -> dict:
    """{id of a step: [the variables there before it], sorted} of every
    step, for the page's choice of a variable; {} for a drawing whose form
    the check refuses."""
    if _form_problems(tree):
        return {}
    seen: dict = {}
    _inputs_problems(tree, seen)
    return seen


def _form_problems(tree, profile=None) -> list:
    """What `problems` says before the inputs: the form of each step, its
    settings, the question at the top, a step that shows."""
    out: list = []

    def say(node, message):
        out.append({"id": node.get("id") if isinstance(node, dict) else None,
                    "message": message})

    if not isinstance(tree, list) or not tree:
        return [{"id": None, "message": "the drawing is a list of steps"}]
    seen: set = set()
    for node in walk(tree):
        if not isinstance(node, dict):
            out.append({"id": None, "message": "a step is an object"})
            continue
        ident = node.get("id")
        if not isinstance(ident, str) or not NAME.match(ident):
            say(node, "a step has an id of letters, digits and _")
        elif ident in seen:
            say(node, f"two steps are called {ident}")
        seen.add(ident)
        kind = kind_of(node)
        if not kind:
            say(node, "a step is a box or a frame (each, round, if, "
                      "together)")
            continue
        allowed = BOX_KEYS if kind == "box" else FRAME_KEYS[kind]
        for key in node:
            if key not in allowed:
                say(node, f"a step of this kind has no key {key!r}")
        if "when" in node and kind != "if":
            said = conditions.problems(node["when"])
            if said:
                say(node, said[0])
        if kind == "box":
            box = LIBRARY.get(node["box"])
            if box is None:
                say(node, f"no box {node['box']!r} in the chat's library")
                continue
            if node.get("off") and not box.switch:
                say(node, f"{box.label} cannot be switched off")
            own = node.get("set") or {}
            if not isinstance(own, dict):
                say(node, "the settings of a step are an object")
                own = {}
            for key, value in own.items():
                said = _setting_problem(box, key, value)
                if said:
                    say(node, said)
            for key in ("prompt",):
                if box.type == "ask" and not setting(node, key):
                    say(node, "the request needs a prompt")
            named = setting(node, "prompt") if any(
                one.key == "prompt" for one in box.settings) else None
            if profile is not None and isinstance(named, str) and \
                    PROMPT_ID.fullmatch(named):
                from .. import prompts
                if not prompts.path_for(named, profile).is_file():
                    say(node, f"the profile has no prompt {named}")
            if box.type == "ask" and not setting(node, "schema"):
                say(node, "the request needs the form of its reply")
            if box.type == "choose" and not isinstance(
                    setting(node, "options"), dict):
                say(node, "the model needs ways to choose from")
            if box.type == "choose" and not setting(node, "prompt"):
                say(node, "the request needs a prompt")
            if box.type == "set" and not setting(node, "name"):
                say(node, "the step names the variable it sets")
            if box.type in ("filter", "merge") and not setting(node,
                                                               "into"):
                say(node, "the step names the variable it fills")
            if box.type == "python" and not setting(node, "code"):
                say(node, "the step needs its code")
            if box.type == "compute" and not (setting(node, "code")
                                              or setting(node, "code_from")):
                say(node, "the step needs its code or a variable with it")
            if box.type == "format" and setting(node, "form") == \
                    "json_schema" and not setting(node, "schema"):
                say(node, "the format JSON by a schema needs the schema")
        elif kind == "each":
            if not isinstance(node.get("list"), str) or not node["list"]:
                say(node, "a loop names the list it goes through")
            if not isinstance(node.get("as"), str) or not NAME.match(
                    node.get("as") or ""):
                say(node, "a loop names its entry (as)")
        elif kind == "round":
            most = (node.get("round") or {}).get("most") \
                if isinstance(node.get("round"), dict) else None
            if not isinstance(most, int) or isinstance(most, bool) \
                    or most < 1:
                say(node, "a round runs at most N times, N 1 or more")
            if "stop" in node:
                said = conditions.problems(node["stop"])
                if said:
                    say(node, said[0])
        elif kind == "if":
            ways = node.get("if")
            if not isinstance(ways, list) or not ways:
                say(node, "a branching has one way at least")
            for way in ways or ():
                if not isinstance(way, dict) or "when" not in way:
                    say(node, "each way of a branching has its condition")
                    continue
                said = conditions.problems(way["when"])
                if said:
                    say(node, said[0])
        elif kind == "together":
            ways = node.get("together")
            if not isinstance(ways, list) or len(ways) < 2:
                say(node, "side by side runs two ways at least")
    first = tree[0] if isinstance(tree[0], dict) else {}
    if first.get("box") != "question":
        out.append({"id": first.get("id"), "message": "a turn starts with "
                    "the user's question"})
    questions = [n for n in walk(tree) if isinstance(n, dict)
                 and n.get("box") == "question"]
    if len(questions) > 1:
        for extra in questions[1:]:
            say(extra, "the question stands once, at the top")
    if not any(isinstance(n, dict) and n.get("box") == "show"
               and not n.get("off") for n in walk(tree)):
        out.append({"id": None, "message": "no step shows the answer"})
    return out


def _inputs_problems(tree: list, seen: Optional[dict] = None) -> list:
    """Every box whose input no step before it gives on every way to it,
    and every condition about a variable that is not there yet. *seen*, a
    dict, is given the variables there before each step."""
    out: list = []

    def where(have: set) -> set:
        return {f"var:{one}" for one in have}

    def steps(nodes: list, have: set) -> set:
        have = set(have)
        for node in nodes:
            if seen is not None:
                seen[node["id"]] = sorted(have)
            if node.get("off"):
                continue
            before = set(have)
            if "when" in node:
                said = conditions.problems(node["when"], where(have))
                if said:
                    out.append({"id": node["id"], "message": said[0]})
            have = step(node, have)
            if "when" in node:
                # a step that may not run gives nothing a later step can
                # count on
                have = before
        return have

    def step(node: dict, have: set) -> set:
        have = set(have)
        kind = kind_of(node)
        if kind == "box":
            missing = sorted(takes(node) - have)
            if missing:
                out.append({"id": node["id"], "message":
                            f"needs {', '.join(missing)}, which no step "
                            f"before it gives"})
            have |= gives(node)
        elif kind == "each":
            inner = have | {node["as"]}
            root = node["list"].split(".")[0]
            if root not in have:
                out.append({"id": node["id"], "message":
                            f"goes through {root}, which no step before "
                            f"it gives"})
            steps(node.get("steps") or [], inner)
        elif kind == "round":
            inner = steps(node.get("steps") or [], have | {"round"})
            said = conditions.problems(node["stop"], where(inner)) \
                if "stop" in node else []
            if said:
                out.append({"id": node["id"], "message": said[0]})
            have |= inner - {"round"}
        elif kind == "if":
            results = []
            for way in node.get("if") or ():
                said = conditions.problems(way["when"], where(have))
                if said:
                    out.append({"id": node["id"], "message": said[0]})
                results.append(steps(way.get("steps") or [], have))
            results.append(steps(node.get("else") or [], have))
            have = set.intersection(*results)
        elif kind == "together":
            results = [steps(way.get("steps") or [], have)
                       for way in node.get("together") or ()]
            have = set.union(have, *results)
        return have

    steps(tree, set())
    return out


# -- what a turn needs from where it runs -------------------------------------------

class Services:
    """What a turn needs from where it runs. The chat page gives its
    resources; a test or the editor's try gives made-up ones. A method a
    drawing never reaches is never called."""

    words: dict = {}

    def corpus(self, image: Optional[bytes]):
        raise NotImplementedError("this place has no corpus")

    def values_outcome(self, task: str, document_id, history,
                       how: str = "auto") -> Optional[dict]:
        return None

    def values_answer(self, task: str, got: dict, document_id, history,
                      corpus=None, progress=None) -> dict:
        raise NotImplementedError("this place has no harvest")

    def values_reason(self, reason: str) -> str:
        return reason

    def kg_turn(self, task: str, document_id) -> dict:
        raise NotImplementedError("this place has no graph")

    def kg_note(self, reason: str) -> str:
        return reason

    def graph(self):
        raise NotImplementedError("this place has no graph")

    def compare(self, task: str, documents: list, scopes: list,
                as_json: bool, histories: dict) -> dict:
        raise NotImplementedError("this place compares nothing")

    def reranker(self):
        """The reranker of the search (`rerank.make_reranker`), None where
        none is set up."""
        from . import rerank
        return rerank.make_reranker()

    def sandbox(self) -> Optional[Callable]:
        """Where code of the turn runs (`answer.sandbox`), None where
        nowhere."""
        from . import answer
        return answer.sandbox()

    def spinner(self, label: str):
        return contextlib.nullcontext()

    def in_this_run(self, work: Callable) -> Callable:
        return work

    def prompt(self, prompt_id: str):
        from .. import prompts
        from . import wording
        return prompts.load(prompt_id, wording.chat_profile())


# -- the turn -----------------------------------------------------------------------

class Stop(Exception):
    """A step the run cannot do where it stands."""


@dataclass
class Ran:
    """One step as a try reports it."""
    id: str
    box: str
    gave: dict


class Turn:
    """What one turn knows while its drawing runs."""

    def __init__(self, services: Services, start: dict, trace=None):
        from . import answer
        self.services = services
        self.vars = {name: start.get(name) for name in START}
        self.vars.update({k: v for k, v in start.items()
                          if k not in self.vars})
        self.vars["image"] = start.get("image")
        self.started = time.time()
        self.faults: list = []
        self.result = answer._empty(False, self.faults)
        self.message: Optional[dict] = None
        self.remember: list = []
        self.pending_log: Optional[dict] = None
        self.anchor = None
        self.asked = None
        self.repeated: set = set()
        self._corpus = None
        self._lock = threading.Lock()
        self.quiet = False          # inside a frame that shows one spinner
        self.trace = trace          # [Ran] for a try, None otherwise

    # -- variables
    def get(self, path: str):
        """The value at *path* ("hits.0.text", "documents.count")."""
        if not isinstance(path, str) or not path:
            return None
        name, *rest = path.split(".")
        value = self.vars.get(name)
        for key in rest:
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, (list, tuple)):
                if key == "count":
                    value = len(value)
                elif key.isdigit() and int(key) < len(value):
                    value = value[int(key)]
                else:
                    value = None
            else:
                value = None
        return value

    def put(self, name: str, value) -> None:
        self.vars[name] = value

    def facts(self, item=None, item_name: str = "item") -> conditions.Facts:
        def get_(subject: str, prop: str):
            if subject != conditions.VAR:
                raise LookupError(f"{subject} is not known in the chat")
            name, *rest = prop.split(".")
            if item is not None and name == item_name:
                value = item
                for key in rest:
                    value = value.get(key) if isinstance(value, dict) \
                        else None
                return value
            return self.get(prop)
        return conditions.Facts(get_)

    def holds(self, condition) -> bool:
        return conditions.holds(condition, self.facts())

    # -- what the turn runs on
    @property
    def document_id(self):
        document = self.vars.get("document") or {}
        return document.get("id") if isinstance(document, dict) else None

    @property
    def question(self) -> str:
        return self.vars.get("question") or ""

    def corpus(self):
        with self._lock:
            if self._corpus is None:
                self._corpus = self.services.corpus(self.vars.get("image"))
            return self._corpus

    def progress(self, label: str):
        if self.quiet:
            return contextlib.nullcontext()
        return self.services.spinner(label)

    @property
    def silent(self):
        from . import answer
        return answer._silent if self.quiet else self.progress


def run(tree: list, start: dict, services: Services, trace=None) -> dict:
    """The reply of one turn of the drawing *tree*: {"message": what the
    page shows, "result": the turn's answer as `answer_question` gives it,
    "remember": [(document id, result)] the follow-up context keeps, and
    "vars": the variables the turn ended with}."""
    from . import answer, pool
    said = problems(tree)
    if said:
        raise ChatFlowError("; ".join(f"{one['id']}: {one['message']}"
                                      for one in said))
    turn = Turn(services, start, trace)
    with pool.turn():
        run_steps(tree, turn)
    if turn.pending_log is not None:
        answer.log_answer(turn.corpus(), turn.document_id, turn.question,
                          turn.vars.get("scopes") or [], turn.result,
                          turn.faults, **turn.pending_log)
    turn.result["faults"] = list(turn.faults)
    if turn.message is None:
        turn.message = compose(turn)
    # What a follow-up reads: the harvest asked alone and the comparison
    # said theirs; the graph's route is no conversation; any other turn is
    # remembered with its answer, also one that found nothing.
    if not (turn.vars.get("harvest_alone") or turn.vars.get("comparison")
            is not None or turn.vars.get("graph") is not None):
        turn.remember.append((turn.document_id, turn.result))
    return {"message": turn.message, "result": turn.result,
            "remember": turn.remember, "vars": turn.vars}


def run_steps(steps: list, turn: Turn) -> None:
    for node in steps or ():
        if node.get("off"):
            continue
        if "when" in node and not turn.holds(node["when"]):
            continue
        run_node(node, turn)


def run_node(node: dict, turn: Turn) -> None:
    from . import llm_client
    kind = kind_of(node)
    if kind == "box":
        step = STEPS[node["box"]]
        token = STEP.set(node["id"])
        try:
            if node["box"] in OWN_FAULTS:
                with llm_client.collecting() as own:
                    step(node, turn)
                turn.faults.extend(own)
            else:
                with llm_client.collecting():
                    step(node, turn)
        except Exception as exc:
            if turn.trace is not None:
                turn.trace.append(Ran(node["id"], node["box"],
                                      {"error": f"{type(exc).__name__}: "
                                                f"{exc}"}))
            raise
        finally:
            STEP.reset(token)
        if turn.trace is not None:
            turn.trace.append(Ran(node["id"], node["box"], {
                name: _shown(turn.vars.get(name))
                for name in sorted(gives(node))}))
    elif kind == "if":
        for way in node.get("if") or ():
            if turn.holds(way["when"]):
                run_steps(way.get("steps") or [], turn)
                return
        run_steps(node.get("else") or [], turn)
    elif kind == "each":
        entries = turn.get(node["list"])
        name = node["as"]
        for entry in list(entries or ()):
            turn.put(name, entry)
            run_steps(node.get("steps") or [], turn)
    elif kind == "round":
        most = int((node.get("round") or {}).get("most") or 1)
        for number in range(1, most + 1):
            turn.put("round", number)
            run_steps(node.get("steps") or [], turn)
            if "stop" in node and turn.holds(node["stop"]):
                break
    elif kind == "together":
        _together(node, turn)


def _together(node: dict, turn: Turn) -> None:
    """Every way at the same time; one spinner for all of them, and the
    corpus opened before, where the ways can reach it."""
    from . import llm_client
    ways = [way.get("steps") or [] for way in node.get("together") or ()]
    if any(isinstance(n, dict) and n.get("box") in _CORPUS_STEPS
           for steps in ways for n in walk(steps)):
        turn.corpus()
    label = node.get("label") or turn.services.words.get("preparing", "")
    was = turn.quiet
    with turn.progress(label):
        turn.quiet = True
        try:
            llm_client.together([turn.services.in_this_run(
                (lambda steps=steps: run_steps(steps, turn)))
                for steps in ways])
        finally:
            turn.quiet = was


_CORPUS_STEPS = {"embed", "search", "statements", "readoff", "assemble",
                 "harvest"}


def _shown(value):
    """A variable as a try shows it: short."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= 400 else text[:400] + " …"


# -- the steps ----------------------------------------------------------------------

def _question(node, turn):
    turn.started = time.time()


def _phrase(node, turn):
    from . import answer
    visual = {"auto": None, "always": True, "never": False}[
        setting(node, "visual")]
    anchor = answer.make_anchor(
        turn.question, turn.vars.get("scopes") or [],
        image_bytes=turn.vars.get("image"),
        image_only=bool(turn.vars.get("image_only")),
        history=turn.vars.get("history"), visual=visual,
        progress=turn.silent)
    turn.anchor = anchor
    turn.put("phrase", anchor.phrase)
    turn.put("recheck", anchor.recheck)
    turn.result["phrase"] = anchor.phrase
    turn.result["recheck"] = anchor.recheck


def _embed(node, turn):
    from . import answer
    if turn.anchor is None:
        raise Stop("the search sentence is written before it is embedded")
    vector, cache_hit = answer.embed_anchor(turn.corpus(), turn.anchor,
                                            turn.silent)
    turn.put("vector", vector)
    turn.result["cache_hit"] = cache_hit


def _search(node, turn):
    from . import answer
    exclude = (answer.examined_before(turn.vars.get("history"))
               if turn.vars.get("recheck") and setting(node, "skip_examined")
               else set())
    turn.result["n_excluded"] = len(exclude)
    mode = turn.anchor.mode if turn.anchor is not None else "text"
    corpus = turn.corpus()
    with turn.silent("📚 Retrieval"):
        hits = answer.search_hits(
            turn.question, turn.vars.get("phrase"), turn.vars.get("vector"),
            corpus, turn.document_id, turn.vars.get("scopes") or [],
            image_only=mode == "image", exclude=exclude,
            top_k=setting(node, "top_k"), words=setting(node, "words"))
    turn.put("hits", hits)
    turn.result["n_hits"] = len(hits)
    if not hits:
        answer._log(corpus, turn.document_id,
                    turn.question or turn.vars.get("phrase") or "", mode,
                    turn.vars.get("scopes") or [], turn.started, n_hits=0,
                    error_message="No hits")


def _rerank(node, turn):
    """The hits ordered by the reranker's score for the search sentence;
    equal scores keep the search's order. Where no reranker is configured
    (rule `rerank_base_url`) the order stays and the turn says so among its
    faults."""
    from types import SimpleNamespace
    from . import llm_client
    hits = list(turn.vars.get("hits") or [])
    most = setting(node, "most")
    head, tail = (hits, []) if most is None else (hits[:most], hits[most:])
    ranker = turn.services.reranker()
    probe = turn.vars.get("phrase") or turn.question
    if ranker is None or not head or not probe:
        if ranker is None:
            llm_client.note_fault("rerank", "not_served")
        return
    views = [SimpleNamespace(text=one.get("text") or "",
                             owner_kind=one.get("owner_kind"),
                             owner_id=one.get("owner_id")) for one in head]
    scores = ranker.scores(turn.document_id, probe, views)
    order = sorted(range(len(head)), key=lambda at: -scores[at])
    turn.put("hits", [head[at] for at in order] + tail)


def _pack(node, turn):
    from . import answer
    packed = answer.pack(turn.vars.get("hits") or [],
                         setting(node, "most"),
                         setting(node, "context_tokens"))
    turn.packed = packed
    turn.put("batches", [[item.get("index") for item in batch.items]
                         for batch in packed.batches])


def _statements(node, turn):
    from . import answer
    packed = getattr(turn, "packed", None)
    if packed is None:
        raise Stop("the hits are put into batches before they are asked")
    asked = answer.ask_batches(
        turn.question, turn.corpus(), turn.document_id, packed, turn.faults,
        turn.result["compute"], history=turn.vars.get("history"),
        until_complete=bool(setting(node, "until_complete")),
        progress=turn.silent, code_runner=turn.services.sandbox())
    turn.asked = asked
    turn.result["n_batches"] = asked.batches
    turn.result["examined"] = sorted(asked.examined)
    turn.result["requested"] = [r["block_id"] for r in asked.requested]
    turn.put("statements", asked.shown)
    turn.put("faults", turn.faults)


def _repeats(node, turn):
    from . import answer
    if turn.asked is None:
        raise Stop("statements are asked before their repeats")
    turn.repeated |= answer.drop_repeats(turn.question, turn.asked,
                                         turn.silent)
    turn.put("statements", turn.asked.shown)
    turn.citations = None


def _readoff(node, turn):
    from . import answer, statements
    if turn.asked is None:
        raise Stop("statements are asked before their figures are read")
    citations = statements.citations_of(turn.asked.shown)
    answer.refine_readoff(turn.question, turn.corpus(), turn.asked.shown,
                          citations, setting(node, "most"), turn.silent)
    turn.citations = citations
    turn.put("citations", citations)


def _assemble(node, turn):
    from . import answer, statements
    if turn.asked is None:
        raise Stop("statements are asked before the answer is made of them")
    citations = getattr(turn, "citations", None)
    if citations is None:
        # What was asked for and not cited is not shown as evidence: a crop
        # the model asked for is a citation only where a statement stands
        # on it.
        citations = statements.citations_of(turn.asked.shown)
    mode = turn.anchor.mode if turn.anchor is not None else "text"
    scopes = turn.vars.get("scopes") or []
    ok = answer.assemble(turn.question, turn.corpus(), turn.document_id,
                         scopes, turn.asked, turn.repeated, citations,
                         turn.result, turn.faults, mode=mode,
                         phrase=turn.vars.get("phrase"),
                         start_time=turn.started)
    turn.put("answer", turn.result.get("answer"))
    turn.put("answer_text", turn.result.get("answer_text"))
    turn.put("citations", turn.result.get("citations") or [])
    if ok:
        turn.pending_log = {"mode": mode, "phrase": turn.vars.get("phrase"),
                            "start_time": turn.started}


def _format(node, turn):
    from . import answer, llm_client
    form = setting(node, "form")
    source = setting(node, "from") or "answer_text"
    text = turn.get(source)
    if text in (None, ""):
        return
    if form == "json_question":
        if source == "answer_text" and turn.result.get("answer_text"):
            # as the turn before the drawing did: `as_json` says whether
            # the reply was read
            answer.json_answer(turn.question, turn.result, turn.silent)
        else:
            formatted = _reshaped(llm_client.format_as_json, turn.question,
                                  str(text))
            if formatted is not None:
                _answer_is(turn, formatted, True)
    elif form == "json_schema":
        formatted = _reshaped(llm_client.format_by_schema, turn.question,
                              str(text), setting(node, "schema"))
        if formatted is not None:
            _answer_is(turn, formatted, True)
            # The JSON has no marks to refer to, so the citations carry no
            # number.
            for cit in turn.result.get("citations") or []:
                cit.pop("n", None)
    elif form in ("list", "table"):
        shown = turn.asked.shown if turn.asked is not None else []
        if not shown:
            return
        made = _as_list(shown) if form == "list" else _as_table(
            shown, turn.result.get("citations") or [])
        _answer_is(turn, made, False)
    turn.put("answer", turn.result.get("answer"))


def _reshaped(how: Callable, *args) -> Optional[str]:
    """What *how* wrote, None where its reply stayed unreadable (the fault
    list of the turn says so): the answer then stays as it was."""
    from . import llm_client
    try:
        return how(*args)
    except llm_client.ReplyError as unread:
        log.warning("the answer stays as it was: %s", unread)
        return None


def _answer_is(turn, text: str, as_json: bool) -> None:
    turn.result["answer"] = text
    turn.result["as_json"] = as_json
    if turn.result.get("answer_text") is None:
        turn.result["answer_text"] = text


def _as_list(shown: list) -> str:
    return "\n".join(f"- {one.get('text') or ''} [{one.get('citation')}]"
                     for one in shown)


def _as_table(shown: list, citations: list) -> str:
    pages = {cit.get("n"): cit.get("page") for cit in citations}
    rows = ["| | Statement | Page |", "|---|---|---|"]
    for one in shown:
        text = str(one.get("text") or "").replace("|", "\\|").replace(
            "\n", " ")
        page = pages.get(one.get("citation"))
        rows.append(f"| {one.get('citation')} | {text} | "
                    f"{'' if page is None else page} |")
    return "\n".join(rows)


def _harvest(node, turn):
    from . import answer
    how = setting(node, "how")
    image_only = bool(turn.vars.get("image_only"))
    history = turn.vars.get("history") or []
    if setting(node, "alone"):
        got = None if image_only else turn.services.values_outcome(
            turn.question, turn.document_id, history, how)
        if got is not None and got["route"] == "values":
            harvest = turn.services.values_answer(
                turn.question, got, turn.document_id, history)
            turn.put("harvest", {k: v for k, v in harvest.items()
                                 if k != "result"})
            turn.put("harvest_alone", True)
            turn.remember.append((turn.document_id, harvest["result"]))
        else:
            # A question that is only an image names no parameter.
            turn.put("harvest_reason", "no_parameter" if image_only
                     else "no_store" if got is None else got["reason"])
            turn.put("harvest_alone", True)
        return
    got = turn.services.values_outcome(turn.question, turn.document_id,
                                       history, how)
    if got is None or got["route"] != "values":
        turn.put("harvest", None)
        return
    harvest = turn.services.values_answer(
        turn.question, got, turn.document_id, history, corpus=turn.corpus(),
        progress=answer._silent)
    turn.put("harvest", {k: v for k, v in harvest.items() if k != "result"})


def _graph(node, turn):
    with turn.progress(turn.services.words.get("route_graph", "")):
        outcome = turn.services.kg_turn(turn.question, turn.document_id)
    turn.put("graph", outcome)


def _graph_query(node, turn):
    from . import kg_route
    text = turn.get(setting(node, "query"))
    if isinstance(text, dict):
        text = next((v for v in text.values() if isinstance(v, str)), None)
    if not isinstance(text, str) or not text.strip():
        turn.put(setting(node, "into") or "rows", [])
        return
    graph, _comments = turn.services.graph()
    turn.put(setting(node, "into") or "rows",
             kg_route.run_query(graph, text, {}))


def _compare(node, turn):
    documents = [(one.get("id"), one.get("label"))
                 for one in turn.vars.get("documents") or ()]
    outcome = turn.services.compare(
        turn.question, documents, turn.vars.get("scopes") or [],
        bool(turn.vars.get("as_json")), turn.vars.get("histories") or {})
    turn.put("comparison", outcome)
    for row in outcome.get("rows") or ():
        turn.remember.append((row["document_id"], row))


def _prompt_text(turn, node) -> tuple:
    """(text, temperature of its head) of a step's prompt: the id of a
    prompt file of the profile, or a text of its own."""
    said = setting(node, "prompt") or ""
    if PROMPT_ID.fullmatch(said):
        prompt = turn.services.prompt(said)
        return prompt.text, prompt.meta.get("temperature")
    return said, None


def _filled(text: str, turn: Turn) -> str:
    def fill(match):
        value = turn.get(match.group(1).strip())
        if value is None:
            return ""
        return value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, default=str)
    return re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}", fill, text)


def _choose(node, turn):
    from . import llm_client
    text, temperature = _prompt_text(turn, node)
    prompt = _Prompt(_filled(text, turn), {"temperature": temperature or 0})
    options = setting(node, "options") or {}
    chosen = llm_client.choose(prompt, turn.question,
                               setting(node, "line") or "", options)
    turn.put(setting(node, "into") or "way", chosen)


@dataclass
class _Prompt:
    text: str
    meta: dict = field(default_factory=dict)


def _ask(node, turn):
    from . import llm_client
    text, temperature = _prompt_text(turn, node)
    shown = {name: turn.get(name) for name in setting(node, "inputs") or ()}
    content = _filled(text, turn)
    if shown:
        content += "\n\n" + json.dumps(shown, ensure_ascii=False,
                                       default=str)
    own = setting(node, "temperature")
    reply = llm_client._ask(
        ("own_reply", setting(node, "schema")),
        [{"role": "user", "content": content}],
        temperature=float(own if own is not None else (temperature or 0)))
    turn.put(setting(node, "into") or "reply", reply)


def _compute(node, turn):
    from . import code_exec
    code = setting(node, "code")
    source = setting(node, "code_from")
    if source:
        code = turn.get(source)
        if isinstance(code, dict):
            code = next((v for v in code.values() if isinstance(v, str)),
                        None)
    context = {name.split(".")[-1]: turn.get(name)
               for name in setting(node, "inputs") or ()}
    runner = turn.services.sandbox()
    out = runner(code or "", context) if runner is not None \
        else code_exec.disabled()
    turn.put(setting(node, "into") or "computed", out)


def _set(node, turn):
    source = setting(node, "from")
    value = turn.get(source) if source else copy.deepcopy(
        setting(node, "value"))
    turn.put(setting(node, "name"), value)


def _filter(node, turn):
    entries = turn.get(setting(node, "list")) or []
    keep = setting(node, "keep")
    kept = [one for one in entries if keep is None
            or conditions.holds(keep, turn.facts(one))]
    turn.put(setting(node, "into"), kept)


def _merge(node, turn):
    out = []
    for path in setting(node, "lists") or ():
        value = turn.get(path)
        out.extend(value if isinstance(value, (list, tuple))
                   else [] if value is None else [value])
    turn.put(setting(node, "into"), out)


def _python(node, turn):
    from ..extraction import general
    inputs = {name.split(".")[-1]: copy.deepcopy(turn.get(name))
              for name in setting(node, "inputs") or ()}
    out = general.run_python(setting(node, "code"), inputs)
    for name in setting(node, "outputs") or ():
        turn.put(name, out.get(name))


def _show(node, turn):
    text = setting(node, "text") or ""
    message = compose(turn)
    if text:
        message = {"role": "assistant", "content": _filled(text, turn),
                   "faults": list(turn.faults)}
    extra = [{"name": name, "value": turn.get(name)}
             for name in setting(node, "values") or ()]
    if extra:
        message["extra"] = extra
    turn.message = message


STEPS = {"question": _question, "phrase": _phrase, "embed": _embed,
         "search": _search, "rerank": _rerank, "pack": _pack,
         "statements": _statements, "repeats": _repeats,
         "readoff": _readoff, "assemble": _assemble, "format": _format,
         "harvest": _harvest, "graph": _graph, "graph_query": _graph_query,
         "compare": _compare, "choose": _choose, "ask": _ask,
         "compute": _compute, "set": _set, "filter": _filter,
         "merge": _merge, "python": _python, "show": _show}


# -- what the page shows ----------------------------------------------------------

def unread_replies(result: dict) -> list:
    """The answer requests of a turn that stayed unreadable, where the turn
    made no statement at all: the model's replies could not be read, so the
    sources were not looked at, which is not the same as nothing standing
    in them. A turn that made statements has its answer, and says the rest
    in the faults under it."""
    from . import replies
    if result.get("statements_made"):
        return []
    return [f for f in result.get("faults") or []
            if f["request"] == replies.ANSWER]


def compose(turn: Turn) -> dict:
    """The message of the turn as the page draws it: the comparison, the
    graph's values, the harvest asked alone, or the answer of the documents
    with the harvest's beside it, by what the turn found."""
    from . import llm_client
    words = turn.services.words
    vars_ = turn.vars
    comparison = vars_.get("comparison")
    if comparison is not None:
        return {"role": "assistant", "content": "", **comparison}
    graph = vars_.get("graph")
    if graph is not None:
        if graph.get("route") == "kg":
            return {"role": "assistant", "content": "",
                    "kg_values": graph["values"], "route": "kg"}
        return {"role": "assistant", "route": "kg_empty",
                "content": turn.services.kg_note(graph.get("reason"))}
    if vars_.get("harvest_alone"):
        if vars_.get("harvest") is not None:
            return {"role": "assistant", "content": "",
                    "harvest": vars_["harvest"], "route": "harvest"}
        return {"role": "assistant", "route": "harvest_empty",
                "content": turn.services.values_reason(
                    vars_.get("harvest_reason"))}
    result = turn.result
    result["faults"] = list(turn.faults)
    recheck_note = None
    if result.get("recheck"):
        recheck_note = words.get("recheck", "").format(
            n=result["n_excluded"])
    answered = result["answer"] is not None
    if not answered and vars_.get("answer") not in (None, "") \
            and turn.asked is None and turn.anchor is None:
        # a route of the drawing's own, made without the documents' search
        result["answer"] = vars_["answer"] if isinstance(
            vars_["answer"], str) else json.dumps(vars_["answer"],
                                                  ensure_ascii=False)
        answered = True
    faults = list(result.get("faults") or [])
    unread = unread_replies(result)
    told: list = []
    if answered:
        reply = result["answer"]
    elif result["n_hits"] == 0:
        reply = (words.get("all_examined", "")
                 if result.get("recheck") and result.get("n_excluded")
                 else words.get("no_hits", ""))
    elif unread:
        reply = words.get("answer_unreadable", "").format(
            causes=llm_client.describe_faults(unread))
        told = unread
    else:
        reply = words.get("nothing_backed", "")
    return {
        "role": "assistant", "content": reply,
        "citations": result["citations"] if answered else [],
        "phrase": result.get("phrase"),
        "as_json": result["as_json"] if answered else False,
        "recheck_note": recheck_note, "route_note": None,
        "compute": result.get("compute", []), "harvest": vars_.get("harvest"),
        "made": result.get("statements_made", 0),
        "dropped": result.get("statements_dropped", 0),
        "faults": [f for f in faults if f not in told],
    }
