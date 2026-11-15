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
each entry of a list (`RUNS`: one after the other in the turn, side by side
each with variables of its own, or ahead of being needed and taken in
order, the way the batches of an answer are asked); "round" runs its steps
again, at most N times, until a condition holds; "together" runs every way
at the same time and goes on when all are done; "part" runs its steps with
variables of its own and gives back only those it names. The run does what
the drawing says and nothing else. The drawing the package brings is the
turn as the code asked it before there was a drawing, request for request
(owner request 2026-11-14 evening: "wenn die Blöcke etwas feiner wären ...
Auch schleifen und Logik inklusive Sandbox berechnung"): each box does one
thing, a request, a search, a run in the sandbox or a reshaping, and every
loop, every end of one and every joining stands in the drawing.

A step that runs "when a request asks" (the sandbox, a crop) is a tool: it
does not run where it stands, the request beside it in the same frame calls
it when its model asks to compute or to see a crop.

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
FRAMES = ("each", "round", "if", "together", "part")
# How a loop of the chat goes through its list: one entry after another in
# the turn's own variables; side by side, each entry with variables of its
# own (the documents of a comparison); or each entry started ahead of being
# needed with the variables there when it starts, and taken in order, until
# the loop stops (the batches of an answer, `pool.in_order`).
RUNS = ("in_turn", "side_by_side", "ahead")
RUN_WORDS = ("one after another", "side by side, each with its own variables",
             "ahead, taken in order")
EACH_LIST = ("The steps inside run once for each entry of a list, such as "
             "the hits of a search, the batches of an answer or the "
             "documents chosen; inside, the entry has the name you give it. "
             "They run one after another, side by side each with variables "
             "of its own, or ahead of being needed and taken in order. To "
             "change it: choose the list, the name of its entry, how it "
             "runs, at most how many entries, a condition that stops it and "
             "what it collects, or switch the loop off.")
PART = ("The steps inside run with variables of their own: what they set "
        "stays inside, and only the variables it gives back are there after "
        "it, such as the answer of the harvest beside the answer of the "
        "documents. To change it: name what it gives back, or put steps "
        "into it.")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A prompt setting that names a prompt file of the profile ("stage/name");
# any other text is the prompt itself.
PROMPT_ID = re.compile(r"[a-z_]+/[A-Za-z0-9_/]+")
# The step of the drawing that runs in this context, for whoever asks on its
# behalf (the editor's try names the step of each request).
STEP: contextvars.ContextVar = contextvars.ContextVar("chat_step",
                                                      default=None)
# The steps of the frame the running step stands in: where a request finds
# the tools beside it.
HERE: contextvars.ContextVar = contextvars.ContextVar("chat_here",
                                                      default=())
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")


class ChatFlowError(ValueError):
    """A drawing the run cannot do; `problems` says every reason."""


# -- the variables of a turn ------------------------------------------------------

_TURN = {"type": "object", "properties": {
    "task": {"type": "string"}, "answer": {"type": "string"},
    "examined": {"type": "array"}, "recheck": {"type": "boolean"}}}
_DOCUMENT = {"type": "object", "properties": {
    "id": {"type": ["integer", "null"]}, "label": {"type": "string"},
    "history": {"type": "array", "items": _TURN}}}
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
        "chose, each with its id, the name the page shows and the turns "
        "before on it; more than one is a comparison.",
        {"type": "array", "items": _DOCUMENT}),
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
        "model's context, each with its number, the sources it shows and "
        "its tables.", {"type": "array"}),
    Var("batch", "the batch", "One batch of a loop over the batches: its "
        "number, the sources it shows and its tables, which the sandbox is "
        "given.", {"type": "object"}),
    Var("complete", "the answer is complete", "Whether the model said, for "
        "the batch taken last, that the answer is complete.",
        {"type": "boolean"}),
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
    Var("answered", "the answer with its citations", "The answer, the "
        "answer as text and the citations together, as answers are joined.",
        {"type": "object"}),
    Var("values_found", "the values chosen", "What \"Choose values of the "
        "harvest\" found: the values with their quotes and how many "
        "matched, or why there are none.", {"type": "object"}),
    Var("harvest", "the answer from the harvest", "What the harvest holds "
        "for the question: the values and the answer read from their "
        "passages; none where it holds nothing.", {"type": "object"}),
    Var("harvest_reason", "why the harvest holds nothing", "no_store, "
        "no_parameter or no_values.", {"type": "string"}),
    Var("harvest_alone", "the harvest answers alone", "Whether the harvest "
        "answers the turn alone and says why where it holds nothing.",
        {"type": "boolean"}),
    Var("plan", "the plan in the graph", "The IRI of the plan asked in the "
        "graph, none where the graph does not hold it.", {"type": "string"}),
    Var("coordinates", "the field and its dimensions", "What the question "
        "names: the field and the dimensions the graph is asked for.",
        {"type": "object"}),
    Var("query", "the query", "The text of a query over the graph (SPARQL).",
        {"type": "string"}),
    Var("bindings", "the values of the query", "The values a query is asked "
        "with, each for a variable of it.", {"type": "object"}),
    Var("graph", "the answer from the graph", "The values of the graph for "
        "the question, or why it has none.", {"type": "object"}),
    Var("compared", "the documents compared", "The documents a comparison "
        "asks, at most as many as it takes.",
        {"type": "array", "items": _DOCUMENT}),
    Var("dropped", "the documents left out", "The names of the documents "
        "beyond the most a comparison takes.",
        {"type": "array", "items": {"type": "string"}}),
    Var("row", "the answer of a document", "One document's answer as a row "
        "of the comparison.", {"type": "object"}),
    Var("comparison", "the comparison", "One answer per document chosen, "
        "and the comparison of them.", {"type": "object"}),
    Var("rows", "the rows", "What a query over the graph returned, one "
        "object per row, or the answers of the documents of a comparison.",
        {"type": "array", "items": {"type": "object"}}),
    Var("way", "the way chosen", "The name of the way the model chose.",
        {"type": "string"}),
    Var("reply", "the reply", "What a step \"Ask the model\" got back.",
        {"type": "object"}),
    Var("computed", "what the sandbox printed", "The output of a run in the "
        "sandbox: whether it ran, what it printed and its error.",
        {"type": "object"}),
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
READOFF_MOST = _s("most", NUMBER, "figures, at most", None,
                  "How many figures a value was read off are read again, "
                  "one by one. Empty: the setting READOFF_MAX_CALLS of the "
                  "installation (3).")
IMAGES_MOST = _s("images", NUMBER, "pictures attached, at most", None,
                 "How many pictures of the batch's tables and figures go "
                 "along with the request. Empty: the setting "
                 "ANSWER_MAX_IMAGES of the installation (4).")
BATCH_S = _s("batch", PATH, "the batch", "batch",
             "The variable that holds the batch asked: the entry of a loop "
             "over the batches.")
RUNS_S = _s("runs", CHOICE, "runs", "in_order",
            "In order: where it stands in the drawing. When a request asks: "
            "only when the model of a request beside it, in the same frame, "
            "asks to compute; what it prints goes back to that request.",
            ("in_order", "asked"), ("in order", "when a request asks"))
COMPUTE_MOST = _s("most", NUMBER, "runs per request, at most", None,
                  "When a request asks: how many runs one request may ask "
                  "for. Empty: the setting CODE_EXEC_MAX_ROUNDS of the "
                  "installation (2).")
CROP_MOST = _s("most", NUMBER, "crops per request, at most", None,
               "How many crops one request may ask for. Empty: the setting "
               "REQUEST_IMAGE_MAX of the installation (2).")
COMPARE_MOST = _s("most", NUMBER, "documents, at most", None,
                  "How many of the documents chosen are compared, in the "
                  "order chosen. Empty: the setting COMPARE_MAX_DOCUMENTS of "
                  "the installation (5).")
BINDINGS_S = _s("bindings", PATH, "variable with the values of the query",
                None, "The variable whose values the query is asked with, as "
                "\"Build the query\" gives them. Empty: none.")
STATEMENTS_S = _s("statements", PATH, "the statements", "statements",
                  "The variable with the statements.")
TEMPLATE_S = _s("text", TEXT, "the format", "{{answer}}",
                "The text of the answer: {{name}} stands for the variable of "
                "that name; a list stands one entry per line, a citation or "
                "a statement with its number. No model is asked.")
INSTRUCTION_S = _s("instruction", TEXT, "how the answer is reshaped", "",
                   "What the model is to do with the answer, for instance "
                   "\"at most three points, then a conclusion\". The numbers "
                   "of the citations stay with their statements.")
RESHAPE_FROM = _s("from", PATH, "text to reshape", "answer",
                  "The variable whose text is reshaped: the answer, or what "
                  "another step wrote.")
ANSWERS_S = _s("answers", PATHS, "the answers", (),
               "The variables with the answers that are joined, each an "
               "answer with its citations (the answer of the documents, of "
               "the harvest, a row of a comparison) or a text.")
JOIN_HOW = _s("how", CHOICE, "how they are joined", "in_order",
              "One after another: each answer below the one before, the "
              "citations numbered on. By the model: one request writes one "
              "answer from them, with the numbers of the citations.",
              ("in_order", "model"), ("one after another", "by the model"))
REPEATS_S = _s("repeats", SWITCH, "take out repeated statements", True,
               "On: one request names the statements that say again what an "
               "earlier one said, and they are taken out.")
STATEMENT_LISTS = _s("lists", PATHS, "the lists of statements", (),
                     "The variables with the statements that are joined.")
FORM_SCHEMA = _s("schema", SCHEMA, "schema of the JSON", None,
                 "The shape of the JSON the model writes the answer in.")
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
    _box("values_pick", "Choose values of the harvest", "routes",
         "The values the harvest holds for the question: by meaning, the "
         "values nearest to the search sentence put before the model, which "
         "chooses; by questions, the field and the dimensions the question "
         "names asked one by one and looked up. Where there are none, it "
         "says why.", "docpipe/app/app.py (values_outcome), "
         "values_route.answer_from_index, values_route.answer_from_values",
         inputs=("question", "document", "history", "image_only"),
         outputs=("values_found", "harvest", "harvest_reason",
                  "harvest_alone"), settings=(HOW, ALONE),
         asks="pick_values"),
    _box("graph_plan", "Find the plan in the graph", "routes",
         "The node of the document asked in the graph; where the graph does "
         "not hold it, the answer of the graph says so.",
         "docpipe/inference/chatflow.py (_graph_plan)",
         inputs=("document",), outputs=("plan", "graph")),
    _box("graph_coordinates", "Read the field and its dimensions", "routes",
         "The model is asked, one closed question each over the spec's own "
         "lists, which field the question asks for and which of its "
         "dimensions it names; where it names no quantity, scenario or "
         "year, the answer of the graph says so.",
         "docpipe/inference/kg_route.py (to_coordinates)",
         inputs=("question",), outputs=("coordinates", "graph"), asks=None),
    _box("graph_build", "Build the query", "routes",
         "The profile's query over the graph with the field and the "
         "dimensions read as its values, and the plan.",
         "docpipe/inference/chatflow.py (_graph_build)",
         inputs=("plan", "coordinates"), outputs=("query", "bindings")),
    _box("graph_query", "Run a query on the graph", "routes",
         "A SPARQL query from a variable run on the graph, with the values "
         "of another; its rows go into a variable. With a step \"Ask the "
         "model\" before it that writes the query, this is a route of its "
         "own.", "docpipe/inference/kg_route.py (run_query)",
         inputs=("query",), outputs=("rows",),
         settings=(QUERY, BINDINGS_S,
                   _s("into", VARNAME, "into the variable", "rows",
                      "The variable the rows are put into."))),
    _box("graph_values", "The values with their evidence", "routes",
         "Each row of the query with the lines the graph writes above its "
         "value: its evidence and its trust. Where there is no row, or a "
         "value without its trust line, the answer of the graph says so.",
         "docpipe/inference/chatflow.py (_graph_values)",
         inputs=("rows", "coordinates"), outputs=("graph",)),
    _box("compare_kept", "Documents for the comparison", "routes",
         "The documents chosen that are compared, in the order chosen, and "
         "the names of those beyond the most it takes.",
         "docpipe/inference/chatflow.py (_compare_kept)",
         inputs=("documents",), outputs=("compared", "dropped"),
         settings=(COMPARE_MOST,)),
    _box("document_answer", "The answer of the document", "routes",
         "What a document's turn came to, as a row of the comparison: its "
         "answer, its citations, its counts and its faults, with the id "
         "and the name of the document.",
         "docpipe/inference/chatflow.py (_document_answer)",
         inputs=("document",), outputs=("row",)),
    _box("compare_answers", "Compare the answers", "routes",
         "One request compares the answers of the documents, given nothing "
         "but each document's name and its checked answer; below two "
         "answers there is nothing to compare.",
         "docpipe/inference/chatflow.py (_compare_answers), "
         "llm_client.compare_answers",
         inputs=("question", "rows"), outputs=("comparison",),
         asks="compare"),
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
    _box("values_passages", "Fetch the passages of the values", "search",
         "The passages the chosen values of the harvest were read from, "
         "each once, as the hits the answer is read from.",
         "docpipe/inference/chatflow.py (_values_passages)",
         inputs=("values_found",), outputs=("hits",)),
    # -- the answer
    _box("pack", "Batches that fit the context", "answer",
         "The best hits in batches, each as large as the model's context "
         "takes; the statements of a new answer start empty.",
         "docpipe/inference/answer.py (pack)",
         inputs=("hits",), outputs=("batches", "statements"),
         settings=(MOST, CONTEXT)),
    _box("ask_batch", "Ask a batch for statements", "answer",
         "One batch is asked for statements, each with the quote it stands "
         "on; it is told the statements already checked and adds only new "
         "ones. A statement is kept only where its quote stands in its "
         "source. Beside it in the same frame, the sandbox and the crops "
         "are what its model may ask for.",
         "docpipe/inference/answer.py (ask_batches), "
         "llm_client.answer_from_sources",
         inputs=("question", "batch", "history", "statements"),
         outputs=("statements", "complete", "faults"),
         settings=(BATCH_S, IMAGES_MOST), marks=CHECKS,
         asks="answer_head"),
    _box("crop", "Show a crop the model asks for", "answer",
         "When the model of a request beside it asks to see a table or a "
         "figure by its id, the crop is sent along with the next request.",
         "docpipe/inference/answer.py (_image_requester)",
         settings=(CROP_MOST,)),
    _box("compute", "Compute in the sandbox", "answer",
         "Python run in the sandbox with variables as its inputs; what it "
         "prints goes into a variable. When a request asks: the code is "
         "what the model of the request beside it writes, and what it "
         "prints goes back to that request.",
         "docpipe/inference/code_exec.py (run_code)",
         outputs=("computed",),
         settings=(RUNS_S, CODE_S, CODE_FROM, INPUTS_S, COMPUTE_MOST,
                   _s("into", VARNAME, "into the variable", "computed",
                      "The variable the run's output is put into."))),
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
    _box("merge_statements", "Join statements", "answer",
         "Lists of statements joined into the statements the answer is made "
         "of, in order; a statement that says again what an earlier one "
         "said can be taken out.",
         "docpipe/inference/chatflow.py (_merge_statements)",
         outputs=("statements",), settings=(STATEMENT_LISTS, REPEATS_S),
         asks="repeats"),
    _box("assemble", "The answer from the statements", "answer",
         "The kept statements in the order they were made, a sentence or "
         "a list, each with the number of its citation; where none was "
         "kept, the turn says why.",
         "docpipe/inference/answer.py (assemble)",
         inputs=("statements",),
         outputs=("answer", "answer_text", "citations", "answered")),
    _box("values_answer", "The answer of the harvest", "answer",
         "The answer read from the passages of the chosen values and the "
         "values it stands on, as the page shows the harvest.",
         "docpipe/inference/chatflow.py (_values_answer)",
         inputs=("values_found",), outputs=("harvest",)),
    # -- the output
    _box("format_json", "JSON as the question describes it", "output",
         "One request writes the checked answer as JSON in the shape the "
         "question describes; nothing checks what it wrote, the citations "
         "stand below.", "docpipe/inference/answer.py (json_answer)",
         inputs=("question",), outputs=("answer",), settings=(FORM_FROM,),
         asks="json_format"),
    _box("format_schema", "JSON by a schema", "output",
         "One request writes the checked answer as JSON in the shape of the "
         "schema set here; the schema is the grammar of the request.",
         "docpipe/inference/llm_client.py (format_by_schema)",
         inputs=("question",), outputs=("answer",),
         settings=(FORM_SCHEMA, FORM_FROM), asks="schema_format"),
    _box("format_list", "As a list", "output",
         "One line per statement with the number of its citation; no model "
         "is asked.", "docpipe/inference/chatflow.py (_as_list)",
         outputs=("answer",), settings=(STATEMENTS_S,)),
    _box("format_table", "As a table", "output",
         "A table of the statements with the number and the page of their "
         "citation; no model is asked.",
         "docpipe/inference/chatflow.py (_as_table)",
         outputs=("answer",), settings=(STATEMENTS_S,)),
    _box("format_template", "A format of your own", "output",
         "The answer as a text of your own, the variables put into it; no "
         "model is asked.", "docpipe/inference/chatflow.py (_rendered)",
         outputs=("answer",), settings=(TEMPLATE_S,)),
    _box("format_model", "Reshaped by the model", "output",
         "One request reshapes the answer as your instruction says, without "
         "changing what it says; the numbers of the citations stay with "
         "their statements, and nothing checks what it wrote.",
         "docpipe/inference/llm_client.py (reshape_answer)",
         inputs=("question",), outputs=("answer",),
         settings=(INSTRUCTION_S, RESHAPE_FROM, TEMPERATURE),
         asks="reshape"),
    _box("merge_answers", "Join answers", "output",
         "Answers of several steps joined into the answer of the turn: one "
         "after another with their citations numbered on, or written as "
         "one by a request that keeps the numbers.",
         "docpipe/inference/chatflow.py (_merge_answers), "
         "llm_client.merge_answers",
         inputs=("question",), outputs=("answer", "citations"),
         settings=(ANSWERS_S, JOIN_HOW), asks="merge_answers"),
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
# the others keep theirs with what they give (the harvest's choice, the
# graph, the comparison). A batch adds its own when it is taken
# (`_take_batch`), in the order of the batches.
OWN_FAULTS = {"choose", "phrase", "embed", "search", "rerank", "pack",
              "repeats", "readoff", "assemble", "compute", "format_json",
              "format_schema", "format_model", "merge_answers",
              "merge_statements", "ask"}
# The steps that only run when a request beside them asks for them.
TOOLS = ("crop",)


def is_tool(node: dict) -> bool:
    """Whether the step is a tool: it runs when a request beside it asks,
    not where it stands."""
    box = node.get("box") if isinstance(node, dict) else None
    return box in TOOLS or (box == "compute"
                            and setting(node, "runs") == "asked")


TEMPLATES = DEFAULT.parent / "chat_templates.json"


def templates() -> list:
    """The templates of the chat's library (`chat_templates.json` beside
    the package's drawing): each a name, a label, what it does, its group
    and the steps one click puts into the drawing. The coarse steps the
    chat had before are templates of the fine ones."""
    return json.loads(TEMPLATES.read_text(encoding="utf-8"))["templates"]


def catalogue() -> dict:
    """The library of the chat as the page shows it: its boxes in the
    form of the flow's (`blocks._box_entry`), its frames, how a loop can
    run, its templates, its variables and what a condition can be about
    (the variables alone)."""
    return {"boxes": [_box_entry(b) for b in LIBRARY.values()],
            "frames": list(FRAMES), "variables": variables_catalogue(),
            "start": list(START), "checks": list(CHECKS),
            "runs": [{"value": value, "label": words}
                     for value, words in zip(RUNS, RUN_WORDS)],
            "part": PART, "templates": templates()}


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
                       "note", "run", "most", "stop", "collect", "label"),
              "round": ("id", "round", "stop", "steps", "when", "off",
                        "note"),
              "if": ("id", "if", "else", "off", "note"),
              "together": ("id", "together", "when", "off", "note",
                           "label"),
              "part": ("id", "part", "steps", "when", "off", "note",
                       "label")}


def kind_of(node) -> str:
    if not isinstance(node, dict):
        return ""
    for kind in ("box",) + FRAMES:
        if kind in node:
            return kind
    return ""


def ways_of(node: dict) -> list:
    """The lists of steps inside a frame: one for "each", "round" and
    "part", one per way of "if" (and its else) and of "together"."""
    kind = kind_of(node)
    if kind in ("each", "round", "part"):
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
    """The variables a box gives, its settings for a name included; a tool
    gives nothing where it stands."""
    box = LIBRARY.get(node.get("box"))
    if box is None or is_tool(node):
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
    for key in ("query", "from", "code_from", "list", "bindings", "batch",
                "statements"):
        named = setting(node, key)
        if isinstance(named, str) and named:
            need.discard(next((one.default for one in box.settings
                               if one.key == key), None))
            need.add(named.split(".")[0])
    if box.type in ("ask", "python", "compute"):
        need.update(str(one).split(".")[0]
                    for one in setting(node, "inputs") or ())
    if box.type in ("merge", "merge_statements"):
        need.update(str(one).split(".")[0]
                    for one in setting(node, "lists") or ())
    if box.type == "merge_answers":
        need.update(str(one).split(".")[0]
                    for one in setting(node, "answers") or ())
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
                      "together, part)")
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
            if box.type == "compute" and setting(node, "runs") != "asked" \
                    and not (setting(node, "code")
                             or setting(node, "code_from")):
                say(node, "the step needs its code or a variable with it")
            if box.type == "format_schema" and not setting(node, "schema"):
                say(node, "the format JSON by a schema needs the schema")
            if box.type == "format_model" and not str(
                    setting(node, "instruction") or "").strip():
                say(node, "the model needs the instruction how to reshape "
                          "the answer")
            if box.type == "merge_answers" and not setting(node, "answers"):
                say(node, "the step names the answers it joins")
            if box.type == "merge_statements" and not setting(node,
                                                              "lists"):
                say(node, "the step names the statements it joins")
        elif kind == "each":
            if not isinstance(node.get("list"), str) or not node["list"]:
                say(node, "a loop names the list it goes through")
            if not isinstance(node.get("as"), str) or not NAME.match(
                    node.get("as") or ""):
                say(node, "a loop names its entry (as)")
            run = node.get("run", "in_turn")
            if run not in RUNS:
                say(node, f"a loop runs {', '.join(RUNS)}")
            most = node.get("most")
            if most is not None and (not isinstance(most, int)
                                     or isinstance(most, bool) or most < 1):
                say(node, "a loop takes at most N entries, N 1 or more")
            if "stop" in node:
                if run == "side_by_side":
                    say(node, "a loop side by side runs every entry at once "
                              "and has nothing to stop")
                else:
                    said = conditions.problems(node["stop"])
                    if said:
                        say(node, said[0])
            collect = node.get("collect")
            if collect is not None and not (
                    isinstance(collect, dict) and set(collect) ==
                    {"from", "into"} and all(
                        isinstance(collect[key], str)
                        and NAME.match(collect[key])
                        for key in ("from", "into"))):
                say(node, "a loop collects a variable of each entry (from) "
                          "into a list (into)")
            if "label" in node and not isinstance(node["label"], str):
                say(node, "the words beside the spinner are a text")
        elif kind == "part":
            part = node.get("part")
            named = part.get("gives") if isinstance(part, dict) else None
            if not isinstance(part, dict) or set(part) != {"gives"} \
                    or not isinstance(named, list) or not all(
                        isinstance(one, str) and NAME.match(one)
                        for one in named):
                say(node, "a part names the variables it gives back")
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
            collect = node.get("collect") or {}
            # the list it collects is there from its start, growing
            inner = have | {node["as"]} | ({collect["into"]}
                                          if collect.get("into") else set())
            root = node["list"].split(".")[0]
            if root not in have:
                out.append({"id": node["id"], "message":
                            f"goes through {root}, which no step before "
                            f"it gives"})
            body = steps(node.get("steps") or [], inner)
            said = conditions.problems(
                node["stop"], where(body | {collect.get("into")} - {None})) \
                if "stop" in node else []
            if said:
                out.append({"id": node["id"], "message": said[0]})
            if collect.get("from") and collect["from"] not in (
                    inner | given_inside(node.get("steps") or [])):
                out.append({"id": node["id"], "message":
                            f"collects {collect['from']}, which no step "
                            f"inside it gives"})
            # What the steps inside give counts after the loop only as the
            # list it collects: the loop may go through no entry at all.
            if collect.get("into"):
                have.add(collect["into"])
        elif kind == "part":
            steps(node.get("steps") or [], have)
            inside = given_inside(node.get("steps") or [])
            for name in (node.get("part") or {}).get("gives") or ():
                if name not in inside | have:
                    out.append({"id": node["id"], "message":
                                f"gives back {name}, which no step inside "
                                f"it gives"})
                have.add(name)
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


def given_inside(nodes: list) -> set:
    """Every variable a step somewhere inside *nodes* gives, on any way:
    what a part can give back and a loop can collect."""
    out: set = set()
    for node in walk(nodes):
        if not isinstance(node, dict):
            continue
        out |= gives(node)
        if kind_of(node) == "each":
            out.add(node.get("as"))
            out.add((node.get("collect") or {}).get("into"))
        if kind_of(node) == "part":
            out.update((node.get("part") or {}).get("gives") or ())
    out.discard(None)
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
        """The values the harvest holds for *task* (`app.values_outcome`),
        None where there is no harvest."""
        return None

    def values_reason(self, reason: str) -> str:
        return reason

    def kg_hooks(self):
        """What the profile contributes to the graph (`kg_route.Hooks`),
        None where it asks none."""
        return None

    def kg_plan(self, document_id) -> Optional[str]:
        """The IRI of the plan *document_id* in the graph, None where the
        graph does not hold it."""
        return None

    def kg_note(self, reason: str) -> str:
        return reason

    def graph(self):
        """(the graph, {value IRI: its comment lines})."""
        raise NotImplementedError("this place has no graph")

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


class _Shared:
    """What a turn and the turns of its loops and parts share: the corpus,
    opened once."""

    def __init__(self):
        self.corpus = None
        self.lock = threading.Lock()


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
        self.result = answer._empty(bool(self.vars.get("as_json")),
                                    self.faults)
        self.message: Optional[dict] = None
        self.remember: list = []
        self.pending_log: Optional[dict] = None
        self.anchor = None
        self.mode = "text"          # how the passages were found
        self.packed = None          # answer.Packed of the batches
        self.asked = None           # answer.Asked: the statements so far
        self.citations = None
        self.repeated: set = set()
        self.takers = None          # of an entry asked ahead: what is taken
        self._shared = _Shared()
        self.quiet = False          # inside a frame that shows one spinner
        self.trace = trace          # [Ran] for a try, None otherwise

    def child(self, put: dict, *, fresh: bool) -> "Turn":
        """A turn with variables of its own for an entry of a loop or a
        part: the variables there now, and *put*. It shares what the turn
        runs on (the services, the corpus, the trace, what a follow-up
        reads). *fresh*: an answer of its own (a document of a comparison,
        the harvest); else a piece of this turn's answer, which reads its
        batches and statements (a batch asked ahead)."""
        from . import answer
        kid = Turn.__new__(Turn)
        kid.services = self.services
        snapshot = self.vars.copy()       # one step under the GIL
        kid.vars = {name: list(value) if isinstance(value, list) else value
                    for name, value in snapshot.items()}
        kid.vars.update(put)
        kid.started = time.time() if fresh else self.started
        kid.faults = []
        kid.result = answer._empty(bool(kid.vars.get("as_json")), kid.faults)
        kid.message = None
        kid.remember = self.remember
        kid.pending_log = None
        kid.anchor = None if fresh else self.anchor
        kid.mode = "text" if fresh else self.mode
        kid.packed = None if fresh else self.packed
        kid.asked = None if fresh else self.asked
        kid.citations = None
        kid.repeated = set()
        kid.takers = None
        kid._shared = self._shared
        kid.quiet = self.quiet
        kid.trace = self.trace
        return kid

    def close(self) -> None:
        """The end of a turn of its own: the log line of its answer, where
        it has one, and its faults in its result (as `run` ends the
        turn)."""
        from . import answer
        if self.pending_log is not None:
            answer.log_answer(self.corpus(), self.document_id, self.question,
                              self.vars.get("scopes") or [], self.result,
                              self.faults, **self.pending_log)
            self.pending_log = None
        self.result["faults"] = list(self.faults)

    def take(self, work: Callable) -> None:
        """*work(turn)* done on the turn that takes this one: later, in
        order, where this is an entry asked ahead; now otherwise."""
        if self.takers is not None:
            self.takers.append(work)
        else:
            work(self)

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
        shared = self._shared
        with shared.lock:
            if shared.corpus is None:
                shared.corpus = self.services.corpus(self.vars.get("image"))
            return shared.corpus

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
    token = HERE.set(steps or ())
    try:
        for node in steps or ():
            if node.get("off"):
                continue
            if "when" in node and not turn.holds(node["when"]):
                continue
            run_node(node, turn)
    finally:
        HERE.reset(token)


def run_node(node: dict, turn: Turn) -> None:
    from . import llm_client
    kind = kind_of(node)
    if kind == "box":
        if is_tool(node):
            return      # it runs when a request beside it asks
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
        _each(node, turn)
    elif kind == "round":
        most = int((node.get("round") or {}).get("most") or 1)
        for number in range(1, most + 1):
            turn.put("round", number)
            run_steps(node.get("steps") or [], turn)
            if "stop" in node and turn.holds(node["stop"]):
                break
    elif kind == "together":
        _together(node, turn)
    elif kind == "part":
        _part(node, turn)


def _each(node: dict, turn: Turn) -> None:
    """The steps of a loop for each entry of its list, at most `most` of
    them, as its `run` says (`RUNS`), until `stop` holds. What it collects
    of each entry is a list that grows as the entries are taken, so `stop`
    can read it, and is there after the loop."""
    from . import llm_client, pool
    entries = list(turn.get(node["list"]) or ())
    most = node.get("most")
    if most is not None:
        entries = entries[:most]
    name, steps = node["as"], node.get("steps") or []
    run = node.get("run") or "in_turn"
    collect = node.get("collect") or {}
    gathered: list = []

    def gather(value) -> None:
        if collect:
            gathered.append(value)
            turn.put(collect["into"], list(gathered))

    if collect:
        turn.put(collect["into"], [])
    label = node.get("label")
    with turn.progress(label) if label else contextlib.nullcontext():
        if run == "in_turn":
            for entry in entries:
                turn.put(name, entry)
                run_steps(steps, turn)
                gather(turn.get(collect["from"]) if collect else None)
                if "stop" in node and turn.holds(node["stop"]):
                    break
        elif run == "side_by_side":
            kids = [turn.child({name: entry}, fresh=True)
                    for entry in entries]
            llm_client.together([turn.services.in_this_run(
                (lambda kid=kid: run_steps(steps, kid))) for kid in kids])
            for kid in kids:
                kid.close()
                gather(kid.vars.get(collect["from"]) if collect else None)
        else:
            # Each entry starts with the variables there when it starts
            # (what the entries before it gave, as far as they were taken)
            # and is taken in order; leaving the loop withdraws what has
            # not been sent, and what was sent comes back to nobody.
            def prepare(at: int) -> Turn:
                kid = turn.child({name: entries[at]}, fresh=False)
                kid.takers = []
                return kid

            def ask(kid: Turn) -> Turn:
                turn.services.in_this_run(lambda: run_steps(steps, kid))()
                return kid

            with contextlib.closing(pool.in_order(len(entries), prepare,
                                                  ask)) as done:
                for kid in done:
                    for work in kid.takers:
                        work(turn)
                    gather(kid.vars.get(collect["from"]) if collect else None)
                    if "stop" in node and turn.holds(node["stop"]):
                        break


def _part(node: dict, turn: Turn) -> None:
    """The steps of a part with variables of their own; only those it
    names come back."""
    kid = turn.child({}, fresh=True)
    label = node.get("label")
    with turn.progress(label) if label else contextlib.nullcontext():
        run_steps(node.get("steps") or [], kid)
    kid.close()
    for name in (node.get("part") or {}).get("gives") or ():
        if name in kid.vars:
            turn.put(name, kid.vars[name])


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


_CORPUS_STEPS = {"embed", "search", "ask_batch", "readoff", "assemble",
                 "values_passages"}


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
    turn.mode = anchor.mode
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
    mode = turn.mode
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
    """The batches of a new answer, and its statements, none yet."""
    from . import answer
    packed = answer.pack(turn.vars.get("hits") or [],
                         setting(node, "most"),
                         setting(node, "context_tokens"))
    turn.packed = packed
    turn.asked = answer.Asked()
    turn.repeated = set()
    turn.citations = None
    turn.put("batches", [
        {"number": at,
         "sources": [item.get("index") for item in batch.items],
         "tables": answer._code_context(batch.items,
                                        packed.top_hits)["tables"]}
        for at, batch in enumerate(packed.batches)])
    turn.put("statements", turn.asked.shown)


def _beside(node: dict, box: str) -> Optional[dict]:
    """The tool *box* in the frame the step *node* stands in."""
    for one in HERE.get():
        if one is not node and isinstance(one, dict) and not one.get("off") \
                and one.get("box") == box and is_tool(one):
            return one
    return None


def _sandbox_beside(node: dict, turn: Turn) -> tuple:
    """(code runner, what the code is given, runs at most) of the sandbox
    beside the request *node*; no runner where there is none or the sandbox
    is not set up."""
    from . import config
    tool = _beside(node, "compute")
    runner = turn.services.sandbox() if tool is not None else None
    if runner is None:
        return None, None, config.CODE_EXEC_MAX_ROUNDS
    context = {name.split(".")[-1]: turn.get(name)
               for name in setting(tool, "inputs") or ()}
    most = setting(tool, "most")

    def run_code(code, given):
        out = runner(code, given)
        if turn.trace is not None:
            turn.trace.append(Ran(tool["id"], "compute",
                                  {"computed": _shown(out)}))
        return out

    return run_code, context, (config.CODE_EXEC_MAX_ROUNDS if most is None
                               else int(most))


def _crop_beside(node: dict, turn: Turn, items: list, top_hits: list,
                 corpus) -> tuple:
    """(the crops' lookup, crops at most) of the tool beside the request
    *node*; none where there is no such tool."""
    from . import answer, config
    tool = _beside(node, "crop")
    if tool is None:
        return None, 0
    most = setting(tool, "most")
    lookup = answer._image_requester(
        corpus, turn.document_id,
        tuple(top_hits[it["index"]].get("document_id") for it in items))

    def crop(block_id):
        item = lookup(block_id)
        if turn.trace is not None:
            turn.trace.append(Ran(tool["id"], "crop",
                                  {"crop": block_id,
                                   "found": item is not None}))
        return item

    return crop, (config.REQUEST_IMAGE_MAX if most is None else int(most))


def _ask_batch(node, turn):
    """One batch asked (`answer._ask_batch`): told the statements there
    when it is asked, with the pictures of its sources, the sandbox and the
    crops beside it. What it said is checked and added when it is taken
    (`_take_batch`)."""
    from functools import partial
    from . import config, llm_client
    from . import statements as told
    packed = turn.packed
    if packed is None or turn.asked is None:
        raise Stop("the hits are put into batches before a batch is asked")
    entry = turn.get(setting(node, "batch") or "batch")
    number = entry.get("number") if isinstance(entry, dict) else entry
    if isinstance(number, bool) or not isinstance(number, int) \
            or not 0 <= number < len(packed.batches):
        raise Stop("a batch is asked inside a loop over the batches")
    chunk = packed.batches[number]
    items, top_hits = chunk.items, packed.top_hits
    corpus = turn.corpus()
    prior = told.texts(turn.vars.get("statements") or []) or None
    most = setting(node, "images")
    most = config.ANSWER_MAX_IMAGES if most is None else int(most)
    images = {}
    for it in items:
        if len(images) >= most:
            break
        img = corpus.resolve_image(top_hits[it["index"]].get("image_path"))
        if img is not None:
            images[it["index"]] = str(img)
    code_runner, code_context, rounds = _sandbox_beside(node, turn)
    crop, crops = _crop_beside(node, turn, items, top_hits, corpus)
    with llm_client.collecting() as own:
        out = llm_client.answer_from_sources(
            turn.question, items, prior=prior, code_runner=code_runner,
            code_context=code_context, max_compute=rounds,
            history=turn.vars.get("history"), images=images or None,
            image_requester=crop, max_image_requests=crops)
    turn.take(partial(_take_batch, chunk=chunk, prior=prior, out=out,
                      own=list(own), top_hits=top_hits, corpus=corpus,
                      document_id=turn.document_id))


def _take_batch(turn, *, chunk, prior, out, own, top_hits, corpus,
                document_id) -> None:
    """A batch taken, in the order of the batches (`answer.ask_batches`):
    its faults, the sources it read, the crops it was given, its code runs
    and the statements whose quote stands in their source; the rest are
    counted as dropped."""
    from . import answer, db, llm_client
    from . import statements as told
    asked = turn.asked
    items = chunk.items
    turn.faults.extend(own)
    asked.ahead = asked.ahead or (prior or []) != told.texts(asked.shown)
    # The sources the model read; a re-check of the same question searches
    # past exactly these. A batch whose reply stayed unreadable was not read.
    if not out.get("fault"):
        asked.examined.update((top_hits[it["index"]]["owner_kind"],
                               top_hits[it["index"]]["owner_id"])
                              for it in items)
    wrote = out.get("statements") or []
    wanted = told.blocks_named(wrote)
    delivered = {}
    for req in out.get("requested") or []:
        if req.get("delivered") and req.get("owner_kind"):
            asked.requested.append(req)
            asked.examined.add((req["owner_kind"], req["owner_id"]))
            block = llm_client.crop_id(req["block_id"])
            if block in wanted:
                hit = db.fetch_owner_content(corpus.conn, req["owner_kind"],
                                             req["owner_id"])
                if hit is not None:
                    if document_id is None:
                        hit["document_label"] = answer._whose(
                            corpus, hit.get("document_id"))
                    delivered[block] = {**req, "hit": hit}
    # Code runs are numbered from 1 in each request; a statement names its
    # run in that numbering, and is shown under the turn's.
    compute = turn.result["compute"]
    offset = len(compute)
    compute.extend(out.get("compute") or [])
    got, lost = told.back(
        wrote, items={it["index"]: it for it in items}, hits=top_hits,
        attached=set(out.get("attached_images") or []), delivered=delivered,
        runs=out.get("compute") or [], run_offset=offset)
    asked.shown.extend(got)
    asked.made += len(got) + len(lost)
    asked.dropped += len(lost)
    for row in lost:
        log.info("batch %d: statement dropped (%s): %.80s",
                 asked.batches + 1, row["why"], str(row.get("statement")))
    asked.batches += 1
    turn.result["n_batches"] = asked.batches
    turn.result["examined"] = sorted(asked.examined)
    turn.result["requested"] = [r["block_id"] for r in asked.requested]
    turn.put("statements", asked.shown)
    turn.put("complete", bool(out.get("complete")))
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


def _merge_statements(node, turn):
    """The statements of several lists, in order, as the statements the
    answer is made of; with `repeats`, those that say again what an earlier
    one said are taken out by one request."""
    from . import answer, llm_client, statements as told
    merged = []
    for path in setting(node, "lists") or ():
        value = turn.get(path)
        if isinstance(value, list):
            merged.extend(dict(one) for one in value if isinstance(one, dict))
    asked = answer.Asked(shown=merged, made=len(merged))
    repeated: set = set()
    if setting(node, "repeats") and len(merged) > 1:
        with turn.silent("🧹 Repeats"):
            repeated = told.repeated(
                llm_client.repeats_among(turn.question, told.texts(merged)),
                len(merged))
        asked.shown[:] = [one for at, one in enumerate(merged)
                          if at not in repeated]
    turn.asked = asked
    turn.repeated = repeated
    turn.citations = None
    turn.put("statements", asked.shown)


def _assemble(node, turn):
    from . import answer, statements
    if turn.asked is None:
        raise Stop("statements are asked before the answer is made of them")
    citations = turn.citations
    if citations is None:
        # What was asked for and not cited is not shown as evidence: a crop
        # the model asked for is a citation only where a statement stands
        # on it.
        citations = statements.citations_of(turn.asked.shown)
    mode = turn.mode
    scopes = turn.vars.get("scopes") or []
    ok = answer.assemble(turn.question, turn.corpus(), turn.document_id,
                         scopes, turn.asked, turn.repeated, citations,
                         turn.result, turn.faults, mode=mode,
                         phrase=turn.vars.get("phrase"),
                         start_time=turn.started)
    turn.put("answer", turn.result.get("answer"))
    turn.put("answer_text", turn.result.get("answer_text"))
    turn.put("citations", turn.result.get("citations") or [])
    turn.put("answered", _answered(turn))
    if ok:
        turn.pending_log = {"mode": mode, "phrase": turn.vars.get("phrase"),
                            "start_time": turn.started}


def _answered(turn) -> dict:
    return {"answer": turn.result.get("answer"),
            "answer_text": turn.result.get("answer_text"),
            "citations": list(turn.result.get("citations") or [])}


# -- the output ---------------------------------------------------------------------

def _text_of(turn, path: str):
    value = turn.get(path)
    if value in (None, ""):
        return None
    return value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, default=str)


def _format_json(node, turn):
    from . import answer, llm_client
    source = setting(node, "from") or "answer_text"
    text = _text_of(turn, source)
    if text is None:
        return
    if source == "answer_text" and turn.result.get("answer_text"):
        # as the turn before the drawing did: `as_json` says whether the
        # reply was read
        answer.json_answer(turn.question, turn.result, turn.silent)
    else:
        formatted = _reshaped(llm_client.format_as_json, turn.question, text)
        if formatted is not None:
            _answer_is(turn, formatted, True)
    _answer_out(turn)


def _format_schema(node, turn):
    from . import llm_client
    text = _text_of(turn, setting(node, "from") or "answer_text")
    if text is None:
        return
    formatted = _reshaped(llm_client.format_by_schema, turn.question, text,
                          setting(node, "schema"))
    if formatted is not None:
        _answer_is(turn, formatted, True)
        # The JSON has no marks to refer to, so the citations carry no
        # number.
        for cit in turn.result.get("citations") or []:
            cit.pop("n", None)
    _answer_out(turn)


def _statements_of(node, turn) -> list:
    value = turn.get(setting(node, "statements") or "statements")
    return [one for one in value or () if isinstance(one, dict)]


def _format_list(node, turn):
    shown = _statements_of(node, turn)
    if shown:
        _answer_is(turn, _as_list(shown), False)
    _answer_out(turn)


def _format_table(node, turn):
    shown = _statements_of(node, turn)
    if shown:
        _answer_is(turn, _as_table(shown, turn.result.get("citations")
                                   or []), False)
    _answer_out(turn)


def _format_template(node, turn):
    _answer_is(turn, _rendered(setting(node, "text") or "", turn), False)
    _answer_out(turn)


def _format_model(node, turn):
    from . import llm_client
    text = _text_of(turn, setting(node, "from") or "answer")
    if text is None:
        return
    own = setting(node, "temperature")
    reshaped = _reshaped(llm_client.reshape_answer, turn.question, text,
                         setting(node, "instruction") or "",
                         float(own if own is not None else 0))
    if reshaped is not None:
        _answer_is(turn, reshaped, False)
    _answer_out(turn)


def _answer_out(turn) -> None:
    """The variable "answer" as the turn's answer is now; where a step
    wrote none (its reply could not be read), it stays as it was."""
    if turn.result.get("answer") is not None:
        turn.put("answer", turn.result["answer"])


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


def _merge_answers(node, turn):
    """The answers named joined into the turn's answer: their citations
    numbered on, one answer after another, or one request that writes one
    answer of them with those numbers."""
    from . import llm_client
    parts = []
    for path in setting(node, "answers") or ():
        value = turn.get(path)
        if isinstance(value, str) and value.strip():
            parts.append((value, []))
        elif isinstance(value, dict):
            text = value.get("answer") if isinstance(
                value.get("answer"), str) else None
            text = text or value.get("answer_text")
            if isinstance(text, str) and text.strip():
                parts.append((text, [dict(one) for one in
                                     value.get("citations") or ()
                                     if isinstance(one, dict)]))
    if not parts:
        return
    texts, citations, shift = [], [], 0
    for text, cited in parts:
        texts.append(_numbered_on(text, shift))
        numbers = [one["n"] for one in cited if isinstance(one.get("n"), int)]
        for one in cited:
            if isinstance(one.get("n"), int):
                one["n"] += shift
            citations.append(one)
        shift += max(numbers, default=0)
    joined = None
    if setting(node, "how") == "model" and len(texts) > 1:
        joined = _reshaped(llm_client.merge_answers, turn.question, texts)
    text = joined if joined is not None else "\n\n".join(texts)
    turn.result.update(answer=text, answer_text=text, citations=citations,
                       as_json=False, n_findings=len(citations))
    turn.put("answer", text)
    turn.put("citations", citations)
    turn.put("answered", _answered(turn))


def _numbered_on(text: str, shift: int) -> str:
    """*text* with the numbers of its citation marks ([3]) moved by
    *shift*."""
    if not shift:
        return text
    return re.sub(r"\[(\d+)\]", lambda m: f"[{int(m.group(1)) + shift}]",
                  text)


# -- the harvest --------------------------------------------------------------------

def _values_pick(node, turn):
    """The values the harvest holds for the question (`app.values_outcome`);
    asked alone, a question that is only an image names no field."""
    alone = bool(setting(node, "alone"))
    image_only = bool(turn.vars.get("image_only"))
    if alone and image_only:
        got = None
    else:
        got = turn.services.values_outcome(
            turn.question, turn.document_id, turn.vars.get("history") or [],
            setting(node, "how"))
    turn.put("values_found", got)
    if alone:
        turn.put("harvest_alone", True)
    if got is None or got.get("route") != "values":
        turn.put("harvest", None)
        turn.put("harvest_reason", "no_parameter" if alone and image_only
                 else "no_store" if got is None else got.get("reason"))


def _values_passages(node, turn):
    """The passages the chosen values were read from, each once, as the
    hits an answer is read from: the harvest decides which passages are read,
    the model which of their numbers answer the question, and each statement
    stands its check against its passage as in a turn of the documents."""
    from . import answer, db
    got = turn.get("values_found") or {}
    corpus = turn.corpus()
    hits, seen = [], set()
    for value in got.get("values") or ():
        source = value.get("source") or {}
        key = (source.get("owner_kind"), source.get("owner_id"))
        if None in key or key in seen:
            continue
        seen.add(key)
        hit = db.fetch_owner_content(corpus.conn, *key)
        if hit is None:
            continue
        if turn.document_id is None:
            hit["document_label"] = answer._whose(corpus,
                                                  hit.get("document_id"))
        hits.append(hit)
    turn.mode = "harvest"
    turn.anchor = None
    turn.put("hits", hits)
    turn.result["n_hits"] = len(hits)
    if not hits:
        answer._log(corpus, turn.document_id, turn.question, "harvest", [],
                    turn.started, n_hits=0,
                    error_message="No passage of the values")


def _values_answer(node, turn):
    """The answer of the harvest as the page shows it (`app.run_values_
    answer`): the answer read from the passages of the values and the
    values it stands on. Asked alone, it is what a follow-up reads."""
    from . import values_route
    got = turn.get("values_found") or {}
    values = got.get("values") or []
    result = turn.result
    result["faults"] = list(turn.faults)
    turn.put("harvest", {
        "answer": result["answer"], "answer_text": result["answer_text"],
        "citations": result["citations"],
        "made": result.get("statements_made", 0),
        "dropped": result.get("statements_dropped", 0),
        "faults": list(result.get("faults") or []),
        "unread": unread_replies(result),
        "values": values_route.used_values(values, result["statements"]),
        "shown": len(values), "total": got.get("total") or 0})
    if turn.vars.get("harvest_alone"):
        turn.remember.append((turn.document_id, result))


# -- the graph ----------------------------------------------------------------------

def _hooks(turn):
    hooks = turn.services.kg_hooks()
    if hooks is None:
        raise Stop("this profile asks no graph")
    return hooks


def _graph_plan(node, turn):
    from . import kg_route
    if turn.services.kg_hooks() is None:
        turn.put("plan", None)
        turn.put("graph", kg_route._fallback("no_graph"))
        return
    plan = turn.services.kg_plan(turn.document_id)
    turn.put("plan", plan)
    if plan is None:
        turn.put("graph", kg_route._fallback("no_plan"))


def _graph_coordinates(node, turn):
    from . import kg_route, llm_client
    hooks = _hooks(turn)

    def ask(task, slot):
        return llm_client.choose(hooks.prompt, task, slot.question,
                                 slot.answerable() if slot.is_closed else {})

    with turn.progress(turn.services.words.get("route_graph", "")):
        coordinates = kg_route.to_coordinates(turn.question, hooks.spec,
                                              hooks.axes, ask)
    turn.put("coordinates", coordinates)
    if not any(axis in coordinates for axis in kg_route.DECIDING_AXES):
        turn.put("graph", kg_route._fallback("no_coordinates", coordinates))


def _graph_build(node, turn):
    from . import kg_route
    hooks = _hooks(turn)
    text, bindings = hooks.bindings(turn.get("coordinates") or {})
    turn.put("query", hooks.query.replace(kg_route.CONSTRAINTS_MARKER, text))
    turn.put("bindings", dict(bindings, PLAN=("iri", turn.get("plan"))))


def _graph_query(node, turn):
    from . import kg_route
    into = setting(node, "into") or "rows"
    text = turn.get(setting(node, "query"))
    if isinstance(text, dict):
        text = next((v for v in text.values() if isinstance(v, str)), None)
    if not isinstance(text, str) or not text.strip():
        turn.put(into, [])
        return
    named = setting(node, "bindings")
    bindings = turn.get(named) if named else None
    graph, _comments = turn.services.graph()
    turn.put(into, kg_route.run_query(graph, text, dict(bindings or {})))


def _graph_values(node, turn):
    """Each row with its evidence and its trust line; fails closed: a value
    with no trust line would be shown as one the run stands behind."""
    from . import kg_route
    coordinates = turn.get("coordinates") or {}
    rows = turn.get("rows") or []
    if not rows:
        turn.put("graph", kg_route._fallback("no_rows", coordinates))
        return
    _graph, comments = turn.services.graph()
    values = []
    for row in rows:
        lines = comments.get(row.get("value") or "")
        if not lines:
            turn.put("graph", kg_route._fallback("no_trust", coordinates))
            return
        values.append(dict(row, evidence=lines[:-1], trust=lines[-1]))
    turn.put("graph", {"route": "kg", "reason": None, "values": values,
                       "coordinates": coordinates})


# -- the comparison -----------------------------------------------------------------

def _compare_kept(node, turn):
    from . import config
    documents = list(turn.vars.get("documents") or ())
    most = setting(node, "most")
    most = config.COMPARE_MAX_DOCUMENTS if most is None else int(most)
    turn.put("compared", documents[:most])
    turn.put("dropped", [one.get("label") for one in documents[most:]
                         if isinstance(one, dict)])


def _document_answer(node, turn):
    document = turn.vars.get("document") or {}
    turn.result["faults"] = list(turn.faults)
    turn.put("row", {**turn.result, "document_id": document.get("id"),
                     "label": document.get("label")})


def _compare_answers(node, turn):
    """One request over the checked answers of the documents, and nothing
    else of them (`compare.plan_answers`): handed the passages, the model could
    ground a claim about one plan in a sentence of another. A document that
    answered nothing keeps its row; below two answers there is nothing to
    compare."""
    from . import compare, llm_client, pool
    rows = [one for one in turn.get("rows") or () if isinstance(one, dict)]
    answers = compare.plan_answers(rows)
    outcome = {"task": turn.question, "rows": rows, "comparison": None,
               "answered": sum(1 for one in answers if one["answer"]),
               "as_json": bool(turn.vars.get("as_json")), "faults": [],
               "dropped": list(turn.get("dropped") or [])}
    if outcome["answered"] >= 2:
        with pool.turn(), turn.progress("⚖️ Comparison"), \
                llm_client.collecting() as faults:
            outcome["comparison"] = llm_client.compare_answers(turn.question,
                                                               answers)
        outcome["faults"] = list(faults)
    turn.put("comparison", outcome)
    for row in rows:
        turn.remember.append((row.get("document_id"), row))


# -- requests and logic of the drawing's own ---------------------------------------

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
    return PLACEHOLDER.sub(fill, text)


def _rendered(text: str, turn: Turn) -> str:
    """*text* with each {{name}} the value of that variable: a text as it
    is, a list one entry per line (a citation or a statement with its
    number), anything else as JSON."""
    def entry(one) -> str:
        if not isinstance(one, dict):
            return str(one)
        words = one.get("text") or one.get("title") or one.get("label") \
            or one.get("answer")
        if words is None:
            return json.dumps(one, ensure_ascii=False, default=str)
        number = one.get("n", one.get("citation"))
        return (f"[{number}] " if number is not None else "") + str(words)

    def fill(match):
        value = turn.get(match.group(1).strip())
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return "\n".join(entry(one) for one in value)
        return json.dumps(value, ensure_ascii=False, default=str)
    return PLACEHOLDER.sub(fill, text)


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
         "ask_batch": _ask_batch, "repeats": _repeats, "readoff": _readoff,
         "merge_statements": _merge_statements, "assemble": _assemble,
         "format_json": _format_json, "format_schema": _format_schema,
         "format_list": _format_list, "format_table": _format_table,
         "format_template": _format_template, "format_model": _format_model,
         "merge_answers": _merge_answers, "values_pick": _values_pick,
         "values_passages": _values_passages,
         "values_answer": _values_answer, "graph_plan": _graph_plan,
         "graph_coordinates": _graph_coordinates,
         "graph_build": _graph_build, "graph_query": _graph_query,
         "graph_values": _graph_values, "compare_kept": _compare_kept,
         "document_answer": _document_answer,
         "compare_answers": _compare_answers, "choose": _choose,
         "ask": _ask, "compute": _compute, "set": _set, "filter": _filter,
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
