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

from dataclasses import dataclass
from typing import Optional

# What an arrow carries: what the box before it gives.
ARROWS = {"document": "document", "pieces": "pieces", "supply": "supply",
          "answers": "answers", "fields": "fields", "values": "values",
          "coordinates": "coordinates", "rows": "rows"}

NUMBER, COUNT, SWITCH, CHOICE, CONDITION, TEXT, RULE = (
    "number", "count", "switch", "choice", "condition", "text", "rule")


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


FOLLOW = Setting("follow_ups", NUMBER, "follow-ups", number="follow_ups",
                 help="Times an answer that did not hold is asked again "
                 "with what did not hold.")
REPLIES = Setting("replies", RULE, "replies out of form at most",
                  number="replies",
                  help="A reply out of its form is asked again with the "
                  "cause; a setting of the run (EXTRACT_MAX_RETRIES) wins.")
PER_REQUEST = Setting("per_request", NUMBER, "pieces a request",
                      number="search_per_request")
MEANINGS = Setting("list_meanings", RULE, "a list shows what each entry "
                   "means up to", number="list_meanings",
                   help="A longer list shows its names only; one whose "
                   "entries name groups is asked group first.")
CHECKS = ("the quote is a line the request showed",
          "the answer stands in its quote",
          "a quote names a place (quote_min_chars)",
          "an answer to a list is one of its entries")
ASKING = ("find", "docfield", "coord", "search")

LIBRARY = {box.type: box for box in (
    # -- start ---------------------------------------------------------------
    Box("document", "Document", "start", "", "document",
        "Its pages, lines, tables and figures, and its title page: the "
        "first lines of its first page, else of the page the rule "
        "title_page_also names.",
        "surveyed.SurveyedHarvest.plan_of",
        settings=(Setting("title_page_lines", NUMBER, "lines of the title "
                          "page", number="title_page_lines"),
                  Setting("title_page_also", RULE, "the page that is the "
                          "title page where the first has none")),
        fixed="every flow starts with the document", switch=False,
        prepares=True, top=True),
    # -- prepare -------------------------------------------------------------
    Box("transcribe", "Transcribe the figures", "prepare", "document",
        "document",
        "Each figure with an image is transcribed once per run into lines: "
        "its caption (title, axes, legend) and its numbers. No other "
        "request is sent its image.",
        "addressed.Transcripts", asks="transcribe",
        fixed="every request shows the lines a figure is transcribed into",
        switch=False, decided="2026-11-09", prepares=True, top=True),
    Box("split", "Cut into pieces", "prepare", "document", "pieces",
        "The document's lines cut into pieces: a new piece where a passage "
        "begins (unless a piece may hold several), where the piece holds "
        "its number of lines, and where the condition says so. A table's "
        "title and head and a figure's caption go with every piece of "
        "them.",
        "units.chunks_of, units.pieces_for",
        settings=(Setting("lines", NUMBER, "lines of a piece at most",
                          number="piece_lines"),
                  Setting("new_piece", CONDITION, "also a new piece"),
                  Setting("across", SWITCH, "a piece may hold several "
                          "passages", False),
                  Setting("table_head", SWITCH, "a table's title and head "
                          "go with each of its pieces", True,
                          help="owner decision 2026-11-02"),
                  Setting("caption", SWITCH, "a figure's caption goes with "
                          "each of its pieces", True),
                  Setting("figure_numbers", SWITCH, "a figure's numbers in "
                          "pieces of their own, its caption one", True,
                          help="owner decision 2026-11-09"),
                  Setting("headings", NUMBER, "headings shown up to a place",
                          number="headings")),
        fixed="every request shows pieces", switch=False,
        decided="2026-11-08", prepares=True, top=True),
    Box("lists", "Lists of the document", "prepare", "pieces", "pieces",
        "The document's list of scenarios and of works, built while it is "
        "read; this publication is the first work.",
        "addressed.Reader.lists_of",
        fixed="a name the spec merges is an entry of the document's list",
        switch=False, prepares=True, top=True),
    # -- order ---------------------------------------------------------------
    Box("sentences", "Order each field's pieces", "order", "pieces",
        "pieces",
        "Each field read in pieces gets a sentence written as this document "
        "would print a value of it, and its pieces are ordered best first "
        "for it; the order is kept under the harvest (survey/).",
        "addressed.Orders", asks="phrase", top=True),
    Box("order", "Order the pieces", "order", "pieces", "supply",
        "The pieces a search finds best for the sentence: the best of each "
        "kind up to its share (tables, figures, text), then the best of "
        "the rest, ordered once by the reranker (rule rerank); pieces "
        "already shown stay out.",
        "addressed.Reader.shown_order, addressed.budgeted",
        needs=("coordinate", "field", "settled"),
        settings=(Setting("pieces", NUMBER, "pieces", number="search_pieces"),
                  Setting("tables", NUMBER, "share of tables",
                          number="search_tables"),
                  Setting("figures", NUMBER, "share of figures",
                          number="search_figures"),
                  Setting("text", NUMBER, "share of text",
                          number="search_text"),
                  Setting("list_factor", SWITCH, "a field with a list reads "
                          "as many times more", False, where=("field",)),
                  Setting("factor", NUMBER, "times more for a field with a "
                          "list", number="listed_field_factor",
                          where=("field",)),
                  Setting("rest_after", SWITCH, "after them the rest of the "
                          "document", False, where=("field", "settled")),
                  Setting("rerank", RULE, "ordered by the reranker")),
        decided="2026-11-09"),
    Box("beside", "Pieces beside", "order", "pieces", "supply",
        "The pieces right before and after the value's, shown together.",
        "addressed.Plan.beside", needs=("coordinate",)),
    # -- ask -----------------------------------------------------------------
    Box("docfield", "Ask a field of the document", "ask", "supply",
        "answers",
        "A field the document has once, or what it settles: the title page "
        "and the pieces of the supply, a few a request; every find that "
        "holds is kept.",
        "addressed.Reader.ask_window", asks="docfield",
        needs=("field", "settled"),
        settings=(PER_REQUEST,
                  Setting("title_page", SWITCH, "the title page with the "
                          "first request", True), FOLLOW, REPLIES,
                  MEANINGS),
        decided="2026-11-08", marks=CHECKS),
    Box("works", "Ask each piece's works", "ask", "pieces", "values",
        "Which lines of each piece speak of another work and which shows "
        "that the rest are this publication's own; each name of a work "
        "asked against the document's list of works, each new work its "
        "details.",
        "addressed.Reader.works", asks="work",
        settings=(FOLLOW, REPLIES), decided="2026-11-09", spec="works",
        top=True),
    Box("find", "Ask the values of a piece", "ask", "pieces", "answers",
        "The values of a field in one piece: an address and its words, and "
        "the entry where the field has a list. An answer that does not fit "
        "its room is asked again in halves of the piece.",
        "addressed.Reader.find", asks="find", needs=("piece",),
        settings=(FOLLOW, REPLIES, MEANINGS), decided="2026-11-08",
        marks=CHECKS),
    Box("coord", "Ask at the value's own place", "ask", "coordinates",
        "answers",
        "The coordinate at its value's own place: its line with the head of "
        "its table or the sentences beside it (rule lines_around), the "
        "headings up to it, the title page and what the document settles. "
        "The answer is an address and words, or 0; an entry of a list is "
        "asked once per wording.",
        "addressed.Reader.ask_own_place", asks="coord",
        needs=("coordinate",),
        settings=(FOLLOW, REPLIES, MEANINGS,
                  Setting("lines_around", RULE,
                          "sentences beside the value")),
        decided="2026-11-08", marks=CHECKS),
    Box("quantity", "Ask what a number is", "ask", "coordinates", "answers",
        "What a number is, by the words it was read with: its designation, "
        "the head of its column and its unit go to the list.",
        "addressed.Reader.quantity", asks="list", needs=("coordinate",),
        settings=(MEANINGS,), decided="2026-11-08"),
    Box("work_coordinate", "Ask a value's work", "ask", "coordinates",
        "answers",
        "The work of the line the value stands in, else asked as an entry "
        "of the document's list of works; never searched.",
        "addressed.Reader.work_coordinate", asks="coord",
        needs=("coordinate",), settings=(FOLLOW,), decided="2026-11-09",
        spec="works"),
    Box("phrase", "Write the search sentence", "ask", "coordinates",
        "coordinates",
        "A sentence of how the document would print the answer, written "
        "once per field, coordinate and wording; the search goes with it.",
        "addressed.Reader.search_sentence", asks="phrase",
        needs=("coordinate",),
        settings=(Setting("anew", SWITCH, "a new sentence from round 2, "
                          "shown the sentences before", False),
                  Setting("question_as_sentence", RULE,
                          "a question may stand for a sentence")),
        decided="2026-11-09"),
    Box("search", "Ask over the supply", "ask", "supply", "answers",
        "The value's place and pieces of the supply, a few a request, the "
        "pieces the model fetches itself first in the next request; no "
        "piece is shown twice.",
        "addressed.Reader.search_round, addressed.Reader.fetch",
        asks="search", needs=("round", "coordinate"),
        settings=(PER_REQUEST, FOLLOW, REPLIES,
                  Setting("fetches", RULE, "what the model may fetch")),
        decided="2026-11-09", marks=CHECKS),
    Box("last_year", "Ask the plan's years", "ask", "coordinates",
        "answers",
        "A year nothing found, asked last with the document's base and "
        "target years.",
        "addressed.Reader.last_year", asks="list", needs=("coordinate",),
        decided="2026-11-07"),
    Box("names", "Ask the entry of a name", "ask", "values", "values",
        "A value that is a name of the document's list of scenarios: the "
        "entry it is, a new one where it is not on the list yet. Words for "
        "several entries become one row per member where the field takes "
        "groups (takes_group).",
        "addressed.Reader.named_value", asks="names", needs=("value",),
        decided="2026-11-08", spec="names"),
    # -- check ---------------------------------------------------------------
    Box("about", "Does the place speak about the value?", "check",
        "answers", "answers",
        "A find from another passage is kept only where the model says the "
        "place it stands in speaks about this value.",
        "addressed.Reader.about", asks="check", needs=("coordinate",),
        attached=("search",), decided="2026-11-07"),
    Box("check", "Check", "check", "answers", "answers",
        "An own check: an answer is refused where the condition holds and "
        "asked again with the sentence; it only refuses, never takes what "
        "the fixed checks refuse. Its refusals count under check:<name>.",
        "engine.own_checks", attached=ASKING,
        settings=(Setting("name", TEXT, "name"),
                  Setting("refuse", CONDITION, "refuse when"),
                  Setting("sentence", TEXT, "asked again with")),
        decided="2026-11-10"),
    # -- remember and state --------------------------------------------------
    Box("settle", "Remember for the document", "remember", "answers",
        "document",
        "What an answer settles for the whole document (its settings, its "
        "base and target years); every request after it shows it.",
        "addressed.Reader.settle_found", needs=("settled",),
        decided="2026-11-08"),
    Box("state", "State", "state", "coordinates", "coordinates",
        "The state of a coordinate still open here: by the supply "
        "(exhausted where pieces are left, else unstated), or fixed. A "
        "state already set stays where it is out of the slice.",
        "engine.Engine.state", needs=("coordinate",),
        settings=(Setting("mode", CHOICE, "state", "by_supply", choices=
                          ("by_supply", "unstated", "out_of_slice")),)),
    # -- end -----------------------------------------------------------------
    Box("write", "Write", "end", "rows", "rows",
        "The rows with their states, folded, with the summary and the "
        "stamp. Stands at the end, once.",
        "runner, pipeline", fixed="a run writes what it read",
        switch=False, top=True),
    Box("compute", "Compute", "end", "rows", "rows",
        "What the checked rows of a document leave open is computed: a "
        "share without its absolute number, parts without their sum. The "
        "model writes the code and the sandbox runs it.",
        "compute.py", asks="compute", decided="2026-11-02", spec="compute",
        top=True),
)}

# What each kind of frame iterates and what it takes.
EACH = {
    "settled": "each thing the document settles (its settings, base and "
               "target years), where the spec asks it",
    "field": "each field",
    "piece": "each piece of the field, in its order",
    "value": "each value",
    "coordinate": "each coordinate of the value, in the order of the spec's "
                  "groups",
}
WHICH = {"once": "the fields the document has once",
         "pieces": "the fields read in pieces",
         "all": "every field"}
ORDERS = {"piece": ("best_first", "document"),
          "value": ("names_first", "document"),
          "coordinate": ("groups",),
          "settled": ("spec",), "field": ("spec",)}
FRAMES = ("each", "round", "if")


def box(type_: str) -> Box:
    return LIBRARY[type_]


def catalogue() -> dict:
    """The library as the page shows it."""
    def setting(s: Setting) -> dict:
        return {"key": s.key, "kind": s.kind, "label": s.label,
                **({"default": s.default} if s.default is not None else {}),
                **({"number": s.number} if s.number else {}),
                **({"choices": list(s.choices)} if s.choices else {}),
                **({"help": s.help} if s.help else {}),
                **({"where": list(s.where)} if s.where else {})}
    return {
        "boxes": [{"type": b.type, "label": b.label, "group": b.group,
                   "takes": b.takes, "gives": b.gives, "says": b.says,
                   "code": b.code, "asks": b.asks, "needs": list(b.needs),
                   "settings": [setting(s) for s in b.settings],
                   "fixed": b.fixed, "switch": b.switch,
                   "decided": b.decided, "attached": list(b.attached),
                   "prepares": b.prepares, "spec": b.spec, "top": b.top,
                   "marks": list(b.marks)}
                  for b in LIBRARY.values()],
        "each": EACH, "which": WHICH,
        "orders": {k: list(v) for k, v in ORDERS.items()},
    }
