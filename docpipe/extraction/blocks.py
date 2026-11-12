"""
blocks.py: The library of a flow's boxes and frames (owner decisions
2026-11-10 evening: the flow is a drawing of boxes and frames, a library to
take them from, and the run does exactly what the drawing says).

Each box (`Box`) says what it takes and what it gives (the arrow before and
after it: document, pieces, supply, answers, ...), its settings with their
defaults (`Setting`), the frames it has to stand in, why it is fixed where
it cannot be removed or switched off, the date of the owner's decision where
the code names one, and where it runs in the code. What a box does with an
answer stays code (`engine.py`, `addressed.Reader`); a box of a new kind, or
a property the run does not know yet, comes as code and appears here.

A setting that takes a number of the flow (`flow.NUMBERS`) takes the named
number unless the box has an own value for it ("only here"); a setting of
the run wins over the named number, never over an own value
(`flow.Numbers`, `engine.Box.number`).

Three frames hold boxes (`FRAMES`): "each" (for each piece of the plan's
settlement, field, piece, value or coordinate, optionally only where a
condition holds, side by side, in an order), "round" (at most N times or
until the supply is used up, stopping where a condition holds), "if" (ways
side by side, each under its condition, the last without one, which join
again below it).

Author: Felix Vossel
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Callable, Optional

from . import variables

# What an arrow carries: what the box before it gives, as the page says it.
ARROWS = {"document": "the document", "pieces": "chunks",
          "supply": "search hits", "answers": "answers", "fields": "fields",
          "values": "values", "coordinates": "dimensions", "rows": "rows"}

NUMBER, COUNT, SWITCH, CHOICE, CONDITION, TEXT, RULE = (
    "number", "count", "switch", "choice", "condition", "text", "rule")
# The settings of the general steps (`general`, owner decision 2026-11-12):
# a prompt (the id of a prompt file or a text of its own), the inputs of a
# request, a JSON schema, where an answer goes, the name of a variable, the
# path to a variable or part of it, several of them, a value in JSON, a
# piece of Python, several choices.
(PROMPT, INPUTS, SCHEMA, INTO, VARNAME, PATH, PATHS, VARNAMES, JSON, CODE,
 MULTI) = ("prompt", "inputs", "schema", "into", "varname", "path", "paths",
           "varnames", "json", "code", "multi")


@dataclass(frozen=True)
class Setting:
    """One setting of a box. A "number" takes the named number of the flow
    (*number*) unless the box gives it a value of its own; a "rule" is a
    rule of `rules.json` shown at the box, set where the rules are."""
    key: str
    kind: str
    label: str
    default: object = None
    number: Optional[str] = None
    choices: tuple = ()
    help: str = ""
    where: tuple = ()           # the frames it applies in, () = everywhere
    words: tuple = ()           # what the page shows for each choice
    rule: str = ""              # the rule that gives its value where the
                                # box has none of its own (`set`): the
                                # step's, its frames', the run's


@dataclass(frozen=True)
class Box:
    """One kind of box of the library."""
    type: str
    label: str
    group: str
    takes: str
    gives: str
    says: str
    code: str
    asks: Optional[str] = None
    needs: tuple = ()               # frames it stands in, innermost first
    settings: tuple = ()
    fixed: str = ""                 # why it cannot be removed
    switch: bool = True             # whether it may be switched off
    decided: str = ""
    attached: tuple = ()            # the boxes whose answers it checks
    prepares: bool = False          # a step of the document's preparation
    spec: Optional[str] = None      # the switch of the spec it needs
    top: bool = False               # stands at the top of the drawing only
    marks: tuple = ()               # fixed checks shown at the box
    # A box of a follow-up pass (`passflow`) says "pass" here: the main
    # flow does not take it, and a pass does not take the others. Its
    # *scope* is "files" or "documents" where it starts what runs for each
    # document (a harvest file, or a document of the run), "chain" where it
    # runs for that document after the start, "run" where it runs once. Its
    # *after* are the boxes one of which stands before it, and *inside* the
    # frame it stands in.
    flow: str = ""
    scope: str = ""
    after: tuple = ()
    inside: str = ""
    # What it takes and gives by name (`variables.VARIABLES`): an input
    # "a|b" takes one of them, one ending in "?" is taken where a step
    # before it gives it (owner decision 2026-11-12: what may stand where
    # follows from the inputs and outputs alone).
    inputs: tuple = ()
    outputs: tuple = ()
    # A box of a profile (profiles/<name>/blocks.py, owner decision
    # 2026-11-12): the profile it belongs to, and the code of its step,
    # run(engine, node, scope). A box of the core has neither; its step is
    # the engine's `box_<type>`.
    profile: str = ""
    run: Optional[Callable] = None


FOLLOW = Setting("follow_ups", NUMBER, "follow-up questions",
                 number="follow_ups",
                 help="How often an answer that failed a check is asked "
                 "again. Each time the request shows the answer and what "
                 "failed, so the model can correct it. With 0 an answer "
                 "that fails a check is not asked again.")
REPLIES = Setting("replies", NUMBER, "answers in the wrong form, at most",
                  number="replies",
                  help="An answer that does not come back in the expected "
                  "form is asked again with the reason. This is how many "
                  "such answers a request accepts before it is left "
                  "without an answer. A value of its own set here wins "
                  "over the number of the flow and over the setting of "
                  "the run.")
PER_REQUEST = Setting("per_request", NUMBER, "chunks per request",
                      number="search_per_request")
MEANINGS = Setting("list_meanings", NUMBER, "show what each list entry "
                   "means, up to", number="list_meanings",
                   help="A list with at most this many entries is shown "
                   "with what each entry means. A longer list shows only "
                   "the names of its entries, and a list with groups is "
                   "asked in two steps, first the group, then the entry.")
# What every step that asks the model takes (plan 2026-11-11, 5.2).
NUMBERS = (FOLLOW, REPLIES, MEANINGS)
# What a question may ask to see besides what it shows (owner decision
# 2026-11-12: where the document says a missing detail at another place or
# points to it, the model may fetch that place itself), each step its own.
FETCHES = Setting("fetches", RULE, "what the model may ask to see",
                  help="The ways in which an answer may ask to see more "
                  "chunks: the next or previous chunk, a table or figure "
                  "it names, a search for a pattern and chunks similar to "
                  "a text it writes; a question about a dimension may also "
                  "ask once for the picture of a figure it shows. What is "
                  "fetched comes first in the next request, or the "
                  "question is asked again with it, and it does not count "
                  "against the chunks of a search. Removing an entry "
                  "forbids that way; empty, the step fetches nothing.")
FETCH_ROUNDS = Setting("fetch_rounds", RULE, "asked again with what was "
                       "fetched, at most",
                       help="How often this question is asked again with "
                       "the chunks its answer asked to see. 0: the answer "
                       "is taken as it is.")
CHECKS = ("the quote is a line the request showed",
          "the answer is in its quote",
          "a quote is long enough to point to one place (quote_min_chars)",
          "an answer to a list is one of its entries")
# The requests whose answers read a value or a dimension: an own check and
# a list entry stand after them.
QUESTIONS = ("find", "docfield", "coord", "search", "own")
# What a request of "Ask the model" may be in the log (`addressed.KINDS`,
# the general step's own "own"), and the prompts of the other requests a
# run sends.
REQUESTS = ("find", "docfield", "coord", "search", "phrase", "check",
            "list", "names", "work", "transcribe", "compute", "review",
            "example", "own")

LIBRARY = {box.type: box for box in (
    # -- start ---------------------------------------------------------------
    Box("document", "Load the document", "start", "", "document",
        "Loads one PDF as the preprocessing left it: its pages with their "
        "lines of text, its tables and its figures. The first lines of its "
        "first page are its title page, which later questions can show. Every "
        "other step works on what this step loads. Example: a heat plan of 80 "
        "pages with 30 tables. To change it: set how many lines the title "
        "page has, and which page counts as the title page where the first "
        "page has none (rule `title_page_also`).",
        "surveyed.SurveyedHarvest.plan_of",
        settings=(Setting("title_page_lines", NUMBER, "lines of the title "
                          "page", number="title_page_lines"),
                  Setting("title_page_also", RULE, "the page used as title "
                          "page where the first page has none",
                          help="Where the first page has no text, for "
                          "example because it is a cover picture, the "
                          "first lines of this page are the title page. "
                          "A larger number takes a later page.")),
        prepares=True, top=True),
    # -- prepare -------------------------------------------------------------
    Box("split", "Split the document into chunks", "prepare",
        "document", "pieces",
        "Splits the document into chunks of at most eight lines (or as many "
        "as set) and gives each line a number. The model sees these chunks in "
        "every question and answers with the number of a line, so that every "
        "answer points to one place. A table's title and head go with each of "
        "its chunks. Example: a table of 40 rows becomes five chunks of eight "
        "rows, each with the head of the table. The chunks of the "
        "preprocessing are something else: they serve the search only. To "
        "change it: the lines of a chunk, a condition that starts a new "
        "chunk, whether a chunk may hold several sections, and what goes with "
        "each chunk.",
        "units.chunks_of, units.pieces_for",
        settings=(Setting("lines", NUMBER, "lines of a chunk, at most",
                          number="piece_lines"),
                  Setting("new_piece", CONDITION, "also a new chunk",
                          help="A condition on the next line of the "
                          "document. Where it holds, a new chunk begins "
                          "before that line, even if the chunk is not "
                          "full yet. Without a condition a chunk ends "
                          "only where the other rules say so."),
                  Setting("across", SWITCH, "a chunk may hold several "
                          "sections, tables or figures", False,
                          help="On: a chunk is filled up across the end of "
                          "a section, table or figure, so it may hold "
                          "lines of several of them. Off: every section, "
                          "table and figure begins a new chunk.",
                          rule="split_across"),
                  Setting("table_head", SWITCH, "a table's title and head "
                          "go with each of its chunks", True,
                          help="On: every chunk of a table starts with the "
                          "table's title and head, so a row is always read "
                          "under its column headings. Off: only the first "
                          "chunk of the table has them. Decided on "
                          "2026-11-02.",
                          rule="split_table_head"),
                  Setting("caption", SWITCH, "a figure's caption goes with "
                          "each of its chunks", True,
                          help="On: every chunk of a figure starts with the "
                          "figure's caption, so its numbers are read with "
                          "title, axes and legend. Off: only the first "
                          "chunk of the figure has the caption.",
                          rule="split_caption"),
                  Setting("figure_numbers", SWITCH, "a figure's numbers in "
                          "chunks of their own, its caption in one", True,
                          help="On: the caption of a figure is a chunk of "
                          "its own and its numbers are chunks of their "
                          "own, each shown with the caption. Off: the "
                          "lines of a figure are cut like any other lines. "
                          "Decided on 2026-11-09.",
                          rule="split_figure_numbers"),
                  Setting("headings", NUMBER, "headings shown above a line",
                          number="headings")),
        decided="2026-11-08", prepares=True, top=True),
    Box("lists", "Start the lists of names", "prepare", "pieces", "pieces",
        "Starts, for each document, the lists of names that are read across "
        "the whole document: the scenarios it names and the works it "
        "presents, compares or cites (this publication is always the first "
        "work). A name read later is looked up in its list: a name the list "
        "has gets its entry, a new name becomes a new entry. Example: the "
        "scenario \"Reference\", named in chapter 2 and again in a table, is "
        "one entry. To change it: which fields and dimensions build such a "
        "list is set by the key `merged` in the Spec tab.",
        "addressed.Reader.lists_of",
        prepares=True, top=True),
    # -- order ---------------------------------------------------------------
    Box("order", "Find the best chunks for a question", "order",
        "pieces", "supply",
        "Searches the document for the chunks that best match the search "
        "sentence of a field or a dimension: first the best of each kind "
        "(tables, figures, text) up to its share, then the best of the rest, "
        "ordered once more by the reranker. Chunks already shown are left "
        "out. Out come the search hits, which the question after it shows a "
        "few at a time. Example: 50 chunks for the year of a value, 20 of "
        "them tables. Unlike \"Search the document with a text\", which "
        "searches with any text you choose, this step searches with the "
        "sentence of the field or dimension it stands in. To change it: the "
        "number of chunks, the three shares, whether a field with a list "
        "reads more, whether the rest of the document follows, and the "
        "reranker (`rerank`).",
        "addressed.Reader.shown_order, addressed.budgeted",
        needs=("coordinate", "field", "settled"),
        settings=(Setting("pieces", NUMBER, "chunks", number="search_pieces"),
                  Setting("tables", NUMBER, "share of tables",
                          number="search_tables"),
                  Setting("figures", NUMBER, "share of figures",
                          number="search_figures"),
                  Setting("text", NUMBER, "share of text",
                          number="search_text"),
                  Setting("list_factor", SWITCH, "a field with a list reads "
                          "several times as many", False, where=("field",),
                          help="On: a field whose values are chosen from a "
                          "list gets the number of chunks multiplied by "
                          "the next setting, because it has to choose "
                          "among many entries. Off: it gets as many "
                          "chunks as any other field.",
                          rule="search_list_factor_on"),
                  Setting("factor", NUMBER, "times as many for a field with "
                          "a list", number="listed_field_factor",
                          where=("field",)),
                  Setting("rest_after", SWITCH, "after them the rest of the "
                          "document", False, where=("field", "settled"),
                          help="On: after the best chunks the remaining "
                          "chunks of the document follow in the order of "
                          "the search, so every chunk can still be shown. "
                          "Off: only the best chunks are offered.",
                          rule="search_rest_after"),
                  Setting("rerank", RULE, "ordered by the reranker",
                          help="On: the reranker orders the chosen chunks "
                          "once, by the search sentence. Off: they keep "
                          "the order of the search by embedding, best "
                          "match first.")),
        decided="2026-11-09"),
    Box("beside", "Take the neighbouring chunks", "order", "pieces", "supply",
        "Takes the chunk right before and the one right after the chunk the "
        "value stands in, as search hits. The question after it shows them "
        "first, so that the model sees what surrounds the value. Example: the "
        "sentence before a table that says which year the table is about. To "
        "change it: there is nothing to set; switched off, only the hits of "
        "the search are shown.",
        "addressed.Plan.beside", needs=("coordinate",)),
    # -- ask -----------------------------------------------------------------
    # -- check ---------------------------------------------------------------
    Box("check", "Own check of an answer", "check", "answers", "answers",
        "Your own check of the answers of the question step before it: where "
        "your condition holds, the answer is refused and asked again with "
        "your sentence. It can only refuse more and never accepts what the "
        "fixed checks refuse; its refusals are counted under check:<name>. "
        "Example: refuse a year before 1990 with \"The year must be 1990 or "
        "later.\" To change it: the name, the condition and the sentence.",
        "engine.own_checks", attached=QUESTIONS,
        settings=(Setting("name", TEXT, "name",
                          help="The name of the check. Its refusals are "
                          "counted in the run's statistics under "
                          "check: followed by this name."),
                  Setting("refuse", CONDITION, "refuse when",
                          help="A condition on the answer. Where it "
                          "holds, the answer is refused and asked again."),
                  Setting("sentence", TEXT, "asked again with",
                          help="The sentence that the new request shows "
                          "to tell the model what was wrong with its "
                          "answer.")),
        decided="2026-11-10"),
    # -- remember and state --------------------------------------------------
    Box("settle", "Keep for the whole document", "remember", "answers",
        "document",
        "Keeps an answer that holds for the whole document, such as its "
        "settings, its base year or its target year, so that every later "
        "request shows it. Example: the base year 2021, shown in every "
        "question about the year of a value. To change it: switch it off, "
        "then later requests do not show these answers; which fields hold for "
        "the whole document is set in the Spec tab.",
        "addressed.Reader.settle_found", needs=("settled",),
        decided="2026-11-08"),
    Box("state", "Set the state of a dimension", "state",
        "coordinates", "coordinates",
        "Gives a dimension that is still open here its final state: by the "
        "search hits, it stays open where hits were never shown, else it "
        "counts as not stated in the document. Example: a year that no shown "
        "line says becomes \"not stated\". To change it: choose the state "
        "this step sets.",
        "engine.Engine.state", needs=("coordinate",),
        settings=(Setting("mode", CHOICE, "state", "by_supply", choices=
                          ("by_supply", "unstated", "out_of_slice"),
                          words=("by the search hits",
                                 "not stated in the document",
                                 "not asked: another dimension excludes "
                                 "the value"),
                          help="By the search hits: the dimension is open "
                          "if chunks of the search were never shown, "
                          "else not stated in the document. Not stated "
                          "in the document: it is marked so at once. Not "
                          "asked: it is marked as excluded by another "
                          "dimension, unless it already has a state.",
                          rule="state_mode"),)),
    # -- general (owner decision 2026-11-12) ----------------------------------
    Box("ask", "Ask the model", "ask", "answers", "answers",
        "Sends a request to the model: its prompt, the inputs you choose, "
        "each shown as you say, and the form of its answer. What becomes of "
        "the answer is its target: a variable, values of a field of the "
        "Spec, a dimension of a value, a list entry, a search sentence and "
        "more, each checked as the reading checks it. Every question of the "
        "flow is this step with a preset (owner decision 2026-11-12), which "
        "fills in its parts; whatever the step sets of its own wins. "
        "Example: \"Which year does the table speak of?\" with the chunk as "
        "numbered lines, answered as {\"year\": 2021}. To change it: the "
        "request, the prompt, the inputs, the form of the answer, the target "
        "and the ways it goes.",
        "general.ask_step",
        settings=(Setting("request", TEXT, "request",
                          help="What the request is in the log, and whose "
                          "settings it reads (its answer room and "
                          "temperature): find, docfield, coord, search, "
                          "phrase, check, list, names, work, transcribe, "
                          "compute, review, example, or own for a question "
                          "of your own."),
                  Setting("prompt", PROMPT, "prompt",
                          help="The id of a prompt of the profile, such as "
                          "extraction/find, or a text of its own. Without "
                          "one, the prompt of its request. An input whose "
                          "key the prompt names as {{key}} is written into "
                          "the prompt and not into the message; "
                          "{{key.field}} writes in one field of it. "
                          "{{example}} shows an answer in the form of the "
                          "answer."),
                  Setting("inputs", INPUTS, "what the request shows",
                          help="Each input is a key of the message, the "
                          "variable it comes from and how it is shown, "
                          "optionally only where a condition holds. They "
                          "stand in the message in this order."),
                  Setting("reply", SCHEMA, "form of the answer",
                          help="A form the reading knows (values with their "
                          "lines, a place, a list entry, ...) or a JSON "
                          "schema of your own. It goes to the model as its "
                          "grammar."),
                  Setting("into", INTO, "where the answer goes",
                          help="The target: a variable of its own name, for "
                          "this item or for the whole document; the values "
                          "of a field of the Spec, each with its line; a "
                          "dimension of the value; and the targets of the "
                          "presets."),
                  Setting("fetch", SWITCH, "the model may ask to see more",
                          False,
                          help="On: an answer may ask to see what a shown "
                          "line points to, in the ways the rule fetches "
                          "allows; it is shown first in the next request, "
                          "or the question is asked again with it (rule "
                          "fetch_rounds). Off: the model answers from what "
                          "it is shown."),
                  Setting("picture", SWITCH, "the model may ask for the "
                          "picture of a figure", False,
                          help="On: a question about a dimension may ask "
                          "once for the picture of a figure it shows, and "
                          "is asked again with it (the entry image of the "
                          "rule fetches)."),
                  Setting("example_at", CHOICE, "the example answer names",
                          "own", choices=("own", "title_page"),
                          words=("the request's own lines",
                                 "the title page where it is shown"),
                          help="Which lines the example of a request that "
                          "finds values points to."),
                  FETCHES, FETCH_ROUNDS, FOLLOW, REPLIES, MEANINGS),
        decided="2026-11-12", marks=CHECKS),
    Box("retrieve", "Search the document with a text", "order",
        "answers", "supply",
        "Searches the document for the chunks that best match a text you "
        "choose, such as a sentence the model wrote: the best of each kind "
        "first, then the best of the rest, ordered once more by the reranker. "
        "Out come the hits as a variable. Example: search with \"The town "
        "plans a district heating network.\" for the chunks about district "
        "heating. Unlike \"Find the best chunks for a question\", the text "
        "can be any variable. To change it: the text it searches with, how "
        "many chunks it takes and the share of each kind.",
        "general.retrieve_step",
        settings=(Setting("query", PATH, "search with",
                          help="The variable whose text the search looks "
                          "for, such as a sentence the model wrote."),
                  Setting("pieces", NUMBER, "chunks", number="search_pieces"),
                  Setting("tables", NUMBER, "share of tables",
                          number="search_tables"),
                  Setting("figures", NUMBER, "share of figures",
                          number="search_figures"),
                  Setting("text", NUMBER, "share of text",
                          number="search_text"),
                  Setting("into", VARNAME, "name of the hits", "hits")),
        decided="2026-11-12"),
    Box("rerank", "Order chunks by a text", "order", "supply", "supply",
        "Orders a list of chunks by how well each matches a text, best first, "
        "with the reranker. Out comes the ordered list. Example: order the "
        "neighbouring chunks by the question, so that the best comes first. "
        "To change it: the list, the text and the name of the ordered list.",
        "general.rerank_step",
        settings=(Setting("list", PATH, "the chunks"),
                  Setting("query", PATH, "ordered by"),
                  Setting("into", VARNAME, "name of the ordered list")),
        decided="2026-11-12"),
    Box("set", "Set a variable", "logic", "answers", "answers",
        "Gives a variable a value: the value of another variable or a part of "
        "it, or a value you write. Example: keep the first hit of a search as "
        "\"best\". To change it: the name, where the value comes from, and "
        "whether it holds for the whole document.",
        "general.set_step",
        settings=(Setting("name", VARNAME, "variable"),
                  Setting("from", PATH, "takes the value of"),
                  Setting("value", JSON, "or this value"),
                  Setting("lasting", SWITCH, "holds for the whole document",
                          False)),
        decided="2026-11-12"),
    Box("filter", "Keep the entries that meet a condition", "logic", "answers",
        "answers",
        "Keeps the entries of a list for which a condition holds; in the "
        "condition the entry is called item. Out comes the shorter list. "
        "Example: keep the hits whose kind is table. To change it: the list, "
        "the condition and the name of the list it keeps.",
        "general.filter_step",
        settings=(Setting("list", PATH, "the list"),
                  Setting("keep", CONDITION, "keep where"),
                  Setting("into", VARNAME, "name of the list it keeps")),
        decided="2026-11-12"),
    Box("merge", "Join lists", "logic", "answers", "answers",
        "Joins several lists into one, each entry once, in their order. "
        "Example: the neighbouring chunks and the search hits as one list. To "
        "change it: the lists and the name of the joined list.",
        "general.merge_step",
        settings=(Setting("lists", PATHS, "the lists"),
                  Setting("into", VARNAME, "name of the joined list"),
                  Setting("lasting", SWITCH, "holds for the whole document",
                          False)),
        decided="2026-11-12"),
    Box("python", "Own step in Python", "logic", "answers", "answers",
        "Runs a piece of Python you write: run(inputs) gets the variables you "
        "choose as a dict and returns a dict whose keys become variables. It "
        "runs in the run itself, like a profile's own code. Example: compute "
        "a share from two numbers read before. Unlike \"Compute shares and "
        "sums\", where the model writes code, you write it here once. To "
        "change it: the code, its inputs and its outputs.",
        "general.python_step",
        settings=(Setting("code", CODE, "code",
                          help="Python that defines run(inputs) and returns "
                          "a dict of the outputs."),
                  Setting("inputs", PATHS, "inputs"),
                  Setting("outputs", VARNAMES, "outputs"),
                  Setting("lasting", SWITCH, "holds for the whole document",
                          False)),
        decided="2026-11-12"),
    # -- end -----------------------------------------------------------------
    Box("write", "Write the harvest", "end", "rows", "rows",
        "Writes what was read: every value with its dimensions and their "
        "states, the summary and the stamp. It stands once, at the end of the "
        "flow. Example: one line of the harvest is the heat demand 245 GWh "
        "with its year 2021, read. To change it: nothing is set here; what is "
        "written follows from the steps before.",
        "runner, pipeline",
        fixed="A run always writes what it read, so this step cannot be "
              "removed or switched off.",
        switch=False, top=True),
    Box("catalogue", "Look the publication up in a catalogue", "end",
        "rows", "rows",
        "Once a document is read, what its front pages leave open of the "
        "publication's DOI, year and authors is looked up in an open "
        "catalogue of publications: by a DOI or by the title, and a hit by "
        "its title counts only where enough of its authors agree with the "
        "authors read. A value found there is written with the catalogue's "
        "record as its proof. Example: the year of publication 2019 from the "
        "record of its DOI. To change it: switch it off, or set what is "
        "looked up and in which order; the step takes part only where the "
        "profile says how its publications are looked up.",
        "profiles/<name>/completion.py", decided="2026-11-04", top=True),
)}

# What each box of the main flow takes and gives (`variables`); a step of
# "Ask the model" takes what its inputs name and gives what its target
# makes (`flow.inputs_of`, `flow.outputs_of`).
IO = {
    "document": (("document",), ("document",)),
    "split": (("document", "figure_lines?"), ("chunks",)),
    "lists": (("chunks",), ("lists",)),
    "order": (("field|fact|dimension", "chunks"), ("hits",)),
    "beside": (("dimension", "chunks"), ("hits",)),
    "check": (("answer",), ("answer",)),
    "settle": (("fact", "answer"), ("facts",)),
    "state": (("dimension",), ()),
    "write": (("values",), ("rows",)),
    "catalogue": (("rows",), ("rows",)),
}
LIBRARY = {kind: dataclasses.replace(box, inputs=IO[kind][0],
                                     outputs=IO[kind][1])
           if kind in IO else box for kind, box in LIBRARY.items()}

# The preset a question inside an answer is asked as where no step after
# the asking question says otherwise (`engine.Engine.nested_node`), by its
# target.
NESTED_PRESETS = {"entry": "list", "plan_year": "plan_year_words",
                  "name": "name", "keep_find": "about"}


def preset_of(node: Optional[dict]):
    """The preset a step of "Ask the model" names (`presets`), None for
    any other step."""
    if not isinstance(node, dict) or node.get("box") != "ask" \
            or not node.get("preset"):
        return None
    from .presets import preset
    return preset(node["preset"])


def box_of(node: Optional[dict]) -> Optional[Box]:
    """The box a step is, seen through its preset: a step of "Ask the
    model" with a preset has the preset's name, explanation, frames,
    settings and request; None where the library has no such box."""
    kind = LIBRARY.get((node or {}).get("box")) \
        if isinstance(node, dict) else None
    if kind is None or kind.type != "ask":
        return kind
    from .general import parts_of
    parts = parts_of(node)
    found = preset_of(node)
    if found is None:
        return dataclasses.replace(kind, asks=parts["request"])
    return dataclasses.replace(
        kind, label=found.label, says=found.says, asks=parts["request"],
        needs=found.needs, top=found.top, prepares=found.prepares,
        attached=found.attached, settings=kind.settings + found.settings,
        profile=found.profile, decided=found.decided or kind.decided,
        spec=found.spec or None, group=found.group or kind.group,
        flow=found.flow, scope=found.scope, after=found.after)


def label_of(kind: str) -> str:
    """What the page calls a kind of step (`rules.step_kind`): a box of
    the library, or the preset of "Ask the model" that stands for it."""
    box = LIBRARY.get(kind)
    if box is not None:
        return box.label
    from .presets import PRESETS
    found = next((one for one in PRESETS.values() if one.kind == kind),
                 None)
    return found.label if found is not None else kind


def settings_of(node: dict) -> tuple:
    """The settings of a step: its box's, and its preset's."""
    kind = box_of(node)
    return kind.settings if kind is not None else ()


def is_attached(node: dict) -> bool:
    """Is *node* applied to the answers of the question before it (an own
    check, a list entry, whether a place speaks about the value), so that
    no frame runs it?"""
    kind = box_of(node)
    return kind is not None and bool(kind.attached)


def target_of(node: dict) -> Optional[str]:
    """The target of a step of "Ask the model" (`targets`), None for any
    other step."""
    if not isinstance(node, dict) or node.get("box") != "ask":
        return None
    from .general import parts_of
    return parts_of(node)["into"].get("to")


def asks_of(node: dict) -> Optional[str]:
    """The request a step sends, None where it sends none."""
    kind = box_of(node)
    return kind.asks if kind is not None else None



class _Library(dict):
    """The boxes of the core, and the first time it is read those of every
    profile (`profiles/<name>/blocks.py: BOXES`), each with the profile it
    belongs to (`Box.profile`). A profile's box of the same type as one of
    the core is an error, so that no profile changes a step of another."""

    def __init__(self, *args):
        super().__init__(*args)
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        from ..profile import available_profiles, load_profile
        for name in available_profiles():
            try:
                profile = load_profile(name)
            except (LookupError, TypeError, ValueError):
                continue
            for b in profile.own("blocks", "BOXES") or ():
                if b.type in self and self[b.type].profile != name:
                    raise ValueError(f"profile {name!r} has a box "
                                     f"{b.type!r}, which "
                                     f"{self[b.type].profile or 'the core'}"
                                     f" has already")
                dict.__setitem__(self, b.type,
                                 dataclasses.replace(b, profile=name))
            # What a profile's presets of "Ask the model" need: its
            # presets, targets, shows and forms (owner decision 2026-11-12
            # evening, plan "modell_fragen").
            from . import forms, presets, shows, targets
            for one in profile.own("blocks", "SHOWS") or ():
                shows.register(*one)
            for one in profile.own("blocks", "FORMS") or ():
                forms.register(*one)
            for one in profile.own("blocks", "TARGETS") or ():
                targets.register(dataclasses.replace(one, profile=name))
            for one in profile.own("blocks", "PRESETS") or ():
                presets.register(dataclasses.replace(one, profile=name))
            for target, preset_name in (profile.own(
                    "blocks", "NESTED_PRESETS") or {}).items():
                NESTED_PRESETS.setdefault(target, preset_name)

    def __getitem__(self, key):
        self._load()
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._load()
        return super().get(key, default)

    def __contains__(self, key):
        self._load()
        return super().__contains__(key)

    def __iter__(self):
        self._load()
        return super().__iter__()

    def __len__(self):
        self._load()
        return super().__len__()

    def keys(self):
        self._load()
        return super().keys()

    def values(self):
        self._load()
        return super().values()

    def items(self):
        self._load()
        return super().items()


# -- the boxes of the follow-up passes (`passflow`) ---------------------------

_TRACE = Setting("trace", TEXT, "folder of the record",
                 help="The folder beside the harvest that the record of "
                 "this pass is written into. A pass never writes into the "
                 "record of the harvest, and two passes that write into "
                 "one folder do not run together. Empty: no record is "
                 "opened here.")
_ARCHIVE = Setting("archive", TEXT, "name of the archive",
                   help="What this pass replaces is kept in the archive "
                   "under this name, and a run of it is told apart by "
                   "it. Empty: the run keeps its name.")
_LABEL = Setting("label", TEXT, "name in the log",
                 help="The name the log of this pass gives its counts.")


def _pass(type_: str, label: str, takes: str, gives: str, says: str,
          code: str, scope: str, **more) -> Box:
    return Box(type_, label, "pass", takes, gives, says, code, flow="pass",
               scope=scope, **more)


LIBRARY.update({box.type: box for box in (
    _pass("stored", "Stored harvest", "", "rows",
          "The pass takes each harvest file of the folder in turn: its "
          "rows, its refusals and the lines it keeps as they are, and the "
          "document's own lists, which are closed from the corpus. A file "
          "whose lists cannot be closed is left alone and counted. To "
          "change it: choose which files are taken (all, those of the "
          "documents the run names, those the run would harvest), whether "
          "documents are read side by side as far as the server has room, "
          "and the names of the record, the archive and the log.",
          "passboxes.box_stored", "files",
          settings=(Setting("files", CHOICE, "files taken", "all",
                            choices=("all", "documents", "to_harvest"),
                            words=("every file of the folder",
                                   "the files of the documents the run "
                                   "names, all where it names none",
                                   "the files of the documents the run "
                                   "would harvest"),
                            help="Which harvest files of the folder the "
                            "pass takes."),
                    Setting("parallel", SWITCH, "documents side by side",
                            False,
                            help="On: documents are read side by side, as "
                            "many as the server has room for. Off: one "
                            "after the other."),
                    _TRACE, _ARCHIVE, _LABEL)),
    _pass("changed", "Changed questions", "rows", "rows",
          "The stamp of the file says which of the questions of the spec "
          "moved since the file was written. The questions that only a "
          "parameter the spec has gained moved are left to the pass that "
          "appends it. A file with no question moved is left as it is. To "
          "change it: switch the step off, then no question is taken as "
          "moved and the file is left alone.",
          "passboxes.box_changed", "chain", after=("stored",)),
    _pass("movable", "Questions that may be read again", "rows", "rows",
          "Of the questions that moved, those that name one dimension of "
          "one field are read again. A question that decides which rows "
          "exist, which passages were read or which model read them, "
          "blocks the file: it stays as it is and is counted. To change "
          "it: the rules `reread_blocks_frame` and "
          "`reread_blocks_dynamic_list` say which of the questions block.",
          "topup.actionable", "chain", after=("changed",)),
    _pass("open", "Open dimensions", "rows", "rows",
          "Every dimension that is still open in some row (budget ended, "
          "no answer, or the answer not carried by its passage) is read "
          "again, each with a search to the end of the plan. The "
          "dimensions are taken in the order of the spec. To change it: "
          "the rule `open_states` says which states are open.",
          "topup.open_coordinates", "chain", after=("stored",)),
    _pass("take_back", "Take the dimension back", "rows", "answers",
          "For one dimension, the rows' answer is taken off and the "
          "dimension is asked again as a harvest asks it, over the "
          "passages its rows were read in. The old answer is kept aside "
          "for the next step. To change it: switch the step off, then no "
          "dimension is read again.",
          "topup.sweep_ask", "chain", inside="dimension",
          after=("movable", "open")),
    _pass("better", "Better than before", "answers", "rows",
          "The new answer replaces the old one only where it is better: "
          "where its state is one the rules `reread_keep_states` and "
          "`reread_improves_states` name. Otherwise the old answer "
          "returns. A row that no longer passes the checks becomes a "
          "refusal, or keeps its old answer, as the rule "
          "`reread_refused_becomes_refusal` says.",
          "topup.sweep_decide", "chain", inside="dimension",
          after=("take_back",)),
    _pass("derive", "Derive from the unit", "rows", "rows",
          "Where the spec decides a dimension from the unit of a number, "
          "the answer is taken from the unit unless the new reading "
          "found one. To change it: switch the step off, then such a "
          "dimension keeps what the reading found.",
          "fields.apply_derived", "chain", inside="dimension",
          after=("better",)),
    _pass("reopen_closed", "Open closed rows", "rows", "rows",
          "Rows that the gate of the slice had closed and that may now "
          "stay were never asked their other dimensions. They are asked "
          "now, like a dimension that moved. To change it: the rule "
          "`reread_reopen_closed_rows` switches it, and the step can be "
          "switched off.",
          "topup.reopened_by_gate", "chain", after=("stored",)),
    _pass("demote", "Demote the refused", "rows", "rows",
          "A row that does not pass the checks after a dimension was read "
          "again is a refusal now, in the file and in the summary. To "
          "change it: switch the step off, then such a row stays among "
          "the rows.",
          "passboxes.box_demote", "chain", after=("stored",)),
    _pass("summary", "Summary", "rows", "rows",
          "The summary line of the file is made again from the rows as "
          "they stand now. The old summary is left out. To change it: "
          "switch the step off, then the file is written without one.",
          "trust.document_summary", "chain", after=("stored",)),
    _pass("replace", "Replace or append the harvest", "rows", "rows",
          "The harvest file is replaced, after a copy of it is kept in the "
          "archive, or the new rows are appended after the stored lines, "
          "which stay as they are. The pass enters itself into the list "
          "of the stamp, so that each dimension it read can say who read "
          "it. To change it: choose whether the file is replaced or "
          "appended to, and the name the pass enters.",
          "passboxes.box_replace", "chain",
          after=("summary", "read_parameters", "unread"),
          settings=(Setting("how", CHOICE, "the file is", "replace",
                            choices=("replace", "append"),
                            words=("replaced", "appended to"),
                            help="Replace: the file is written anew from "
                            "its lines. Append: the stored lines stay as "
                            "they are and the new rows follow."),
                    Setting("producer", TEXT, "name entered in the stamp",
                            help="The name this pass enters into the list "
                            "of who wrote into the harvest. Empty: none "
                            "is entered."))),
    _pass("carry_stamp", "Carry the stamp on", "rows", "rows",
          "The stamp keys that the pass could account for are written "
          "forward and every other key stays as it was, so that a later "
          "run still sees what it has to redo. The stamp goes on only "
          "where no request of the pass went unserved (a 429, a 5xx, a "
          "timeout), was refused to the end or failed in our own code. To "
          "change it: switch the step off, then no key is carried "
          "forward and the next run reads the file again.",
          "remap.stamp_forward", "chain", after=("replace",),
          settings=(Setting("producer", TEXT, "name entered in the stamp",
                            help="The name this step enters into the "
                            "stamp's list where it carries keys forward. "
                            "Empty: none is entered here."),)),
    _pass("remap", "Map the lists again", "rows", "rows",
          "No model is asked. Each row's recorded wording is mapped onto "
          "the lists as the spec reads them today, first the value, then "
          "each dimension that is a choice. A refusal that a grown list "
          "could turn into a row holds the stamp key of its dimension "
          "back. To change it: the rules `remap_unlisted`, "
          "`remap_overwrite_class` and `remap_refusals_block_stamp` say "
          "what happens to a wording no list holds, to a class that is "
          "already there and to the refusals.",
          "remap.remap_row", "chain", after=("stored",)),
    _pass("recheck", "Check the quotes again", "rows", "rows",
          "No model is asked. Every dimension of every row is held to "
          "the rule that its answer stands in its quote. An empty "
          "dimension is unanswered, a derived one stays, one without a "
          "quote or whose answer is not in its quote falls, the others "
          "are read. To change it: the rules `recheck_keeps_derived`, "
          "`recheck_drop_without_quote` and `recheck_dropped_state` "
          "say how.",
          "recheck.recheck_row", "chain", after=("stored",)),
    _pass("worklist", "Working list", "rows", "rows",
          "What the second reading said, one line for each field it "
          "asked, is written into the working list `review.csv` beside "
          "the harvest, after a copy of the old one is kept. To change "
          "it: the rule `review_cell_chars` sets how much of a passage "
          "a cell holds.",
          "review.run", "run", after=("review",)),
    _pass("clear_stamps", "Clear the stamps", "rows", "rows",
          "A harvest that a rule it never saw has rewritten is not the "
          "output its stamp names. The stamps are deleted, after a copy "
          "of each is kept, so that the next run reads the documents "
          "again. A file left alone keeps its stamp. To change it: the "
          "rule `recheck_clear_stamps` switches it.",
          "recheck.run", "run", after=("recheck",)),
    _pass("classify", "Classify the new parameter", "", "rows",
          "The stamp of each document says whether a parameter was added "
          "to the spec and nothing else moved that the addition does not "
          "explain. A document whose stamp cannot be read, that has no "
          "new parameter, whose spec cannot be closed, where another "
          "question moved, or whose stored rows were decided under "
          "another derivation of their parameter, stays as it is and is "
          "counted. A file that already holds the new parameter and "
          "lacks only its stamp gets the stamp. To change it: the rule "
          "`parameter_pass_blocks_on_derivation` switches the last "
          "check.",
          "topup_parameter.classify", "documents",
          settings=(_TRACE, _ARCHIVE, _LABEL)),
    _pass("read_parameters", "Read the plan for the new parameters", "rows",
          "rows",
          "The whole plan is read for the new parameters alone, as a "
          "harvest reads it, and the rows are folded and checked. Where "
          "the reading was not complete, nothing is written and the "
          "document counts as failed (the rule "
          "`parameter_pass_all_or_nothing`).",
          "passboxes.box_read_parameters", "chain", after=("classify",)),
    _pass("unread", "Unread passages", "", "rows",
          "The passages that no reading of the harvest answered, and the "
          "passages where a parameter's reading came to nothing, are "
          "read, and their rows are appended after the stored lines. A "
          "document that this pass has read to its end is not read "
          "again. To change it: the rules `rest_once_per_document` and "
          "`rest_without_trace` say what happens to a document read "
          "before and to one that has no trace.",
          "surveyed.append_unread", "documents",
          settings=(_TRACE, _LABEL)),
    _pass("places", "Places of an earlier harvest", "", "",
          "Each document starts at the passages that stored harvests "
          "found something in, and not at a search: no anchors, no "
          "ranking, no rest of the plan. Only the places are taken, the "
          "model reads them again. A field that no stored harvest was "
          "asked is read over the whole plan.",
          "found.Found", "run", settings=(_ARCHIVE,)),
    _pass("main_flow", "Read the documents", "", "rows",
          "Each document is read with the flow of the profile and its "
          "harvest is written. Where the step Places of an earlier "
          "harvest stands before it, a document starts at those places.",
          "runner.harvest_documents", "documents",
          settings=(_TRACE, _LABEL)),
)})

# What each kind of frame iterates and what it takes.
EACH = {
    "settled": "The steps inside run once for each field of the whole "
               "document, such as its settings and its base and target "
               "years, where the Spec asks for it. To change it: set a "
               "condition, the order, whether its items are asked side by "
               "side, or switch the loop off.",
    "field": "The steps inside run once for each field of the Spec. To "
             "change it: choose which fields (the fields asked once per "
             "document, the fields read chunk by chunk, or every field), "
             "set a condition and the order, or switch the loop off.",
    "piece": "The steps inside run once for each chunk of the field, in "
             "its order. To change it: choose the order (best first or as "
             "in the document), set a condition, ask the chunks side by "
             "side, or switch the loop off.",
    "value": "The steps inside run once for each value that was found. "
             "To change it: choose the order (names first or as in the "
             "document), set a condition, ask the values side by side, or "
             "switch the loop off.",
    "coordinate": "The steps inside run once for each dimension of the "
                  "value, in the order of the Spec's groups. To change it: "
                  "set a condition, ask the dimensions side by side, or "
                  "switch the loop off.",
    "list": "The steps inside run once for each entry of a list, such as "
            "the hits of a search or a list the model wrote; inside, the "
            "entry has the name you give it. To change it: choose the "
            "list, the name of its entry and a condition, ask the entries "
            "side by side, or switch the loop off.",
}
# ... and its name on the page
EACH_TITLES = {"settled": "For each field of the whole document",
               "field": "For each field", "piece": "For each chunk",
               "value": "For each value", "coordinate": "For each dimension",
               "list": "For each entry of a list"}
WHICH = {"once": "the fields asked once per document",
         "pieces": "the fields read chunk by chunk",
         "all": "every field"}
ORDERS = {"piece": ("best_first", "document"),
          "value": ("names_first", "document"),
          "coordinate": ("groups",),
          "settled": ("spec",), "field": ("spec",)}
ORDER_WORDS = {"best_first": "best first", "document": "as in the document",
               "names_first": "names first",
               "groups": "by the spec's groups", "spec": "as in the spec"}
FRAMES = ("each", "round", "if")


def box(type_: str) -> Box:
    return LIBRARY[type_]


def offered(b: Box, profile=None) -> bool:
    """Does the page offer *b* where *profile* (a profile or its name) is
    open: a box of the core always, a box of a profile where *profile* is
    that profile or extends it. Without a profile, every box."""
    if not b.profile or profile is None:
        return True
    if isinstance(profile, str):
        from ..profile import load_profile
        try:
            profile = load_profile(profile)
        except LookupError:
            return b.profile == profile
    return b.profile in {one.name for one in profile.lineage()}


def _setting_entry(s: Setting) -> dict:
    """A setting as the page shows it."""
    return {"key": s.key, "kind": s.kind, "label": s.label,
            **({"default": s.default} if s.default is not None else {}),
            **({"number": s.number} if s.number else {}),
            **({"choices": list(s.choices)} if s.choices else {}),
            **({"words": dict(zip(s.choices, s.words))}
               if s.words else {}),
            **({"help": s.help} if s.help else {}),
            **({"where": list(s.where)} if s.where else {}),
            **({"rule": s.rule} if s.rule else {})}


def _box_entry(b: Box) -> dict:
    """A box as the page shows it."""
    return {"type": b.type, "label": b.label, "group": b.group,
            "takes": b.takes, "gives": b.gives, "says": b.says,
            "code": b.code, "asks": b.asks, "needs": list(b.needs),
            "settings": [_setting_entry(s) for s in b.settings],
            "fixed": b.fixed, "switch": b.switch,
            "decided": b.decided, "attached": list(b.attached),
            "prepares": b.prepares, "spec": b.spec, "top": b.top,
            "marks": list(b.marks), "inputs": list(b.inputs),
            "outputs": list(b.outputs), "profile": b.profile}


def catalogue(profile=None) -> dict:
    """The library as the page shows it where *profile* is open: the
    boxes of the main flow, those of the core and those of the profile
    (`offered`), the presets of "Ask the model" its flow takes, and apart
    from them the boxes of the follow-up passes."""
    entry = _box_entry
    from . import forms, shows, targets
    return {
        "boxes": [entry(b) for b in LIBRARY.values()
                  if not b.flow and offered(b, profile)],
        "pass_boxes": [{**entry(b), "scope": b.scope,
                        "after": list(b.after), "inside": b.inside}
                       for b in LIBRARY.values() if b.flow],
        "each": EACH, "each_titles": EACH_TITLES, "which": WHICH,
        "orders": {k: list(v) for k, v in ORDERS.items()},
        "order_words": ORDER_WORDS, "arrows": ARROWS,
        "variables": variables.catalogue(),
        "items": {k: list(v) for k, v in variables.ITEMS.items()},
        "start": list(variables.START),
        "presets": [one for one in presets_catalogue(profile)
                    if not one["flow"]],
        "shows": shows.shows_catalogue(),
        "forms": forms.forms_catalogue(),
        "targets": targets.targets_catalogue(),
        "requests": list(REQUESTS),
    }


def presets_catalogue(profile=None) -> list:
    """The presets of "Ask the model" the page offers where *profile* is
    open, in the order of the library: each as the box it is
    (`box_of`: its name, explanation, settings, frames and where it runs)
    with its five parts and the values of its settings."""
    from .presets import PRESETS
    LIBRARY.get("ask")
    out = []
    for one in PRESETS.values():
        if one.profile and profile is not None and not offered(
                dataclasses.replace(LIBRARY["ask"], profile=one.profile),
                profile):
            continue
        box = box_of({"box": "ask", "preset": one.name})
        out.append({**_box_entry(box), "name": one.name, "kind": one.kind,
                    "request": one.request, "parts": {
                        "inputs": list(one.inputs), "reply": one.reply,
                        "into": dict(one.into)},
                    "values": dict(one.values or {}), "flow": one.flow,
                    "scope": one.scope, "after": list(one.after)})
    return out


# The library the flow, the engine and the page read: the core's boxes and,
# once it is read, those of the profiles (`_Library`).
LIBRARY = _Library(LIBRARY)
