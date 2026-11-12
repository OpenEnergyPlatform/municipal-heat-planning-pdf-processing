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

# What an arrow carries: what the box before it gives, as the page says it.
ARROWS = {"document": "the document", "pieces": "chunks",
          "supply": "search hits", "answers": "answers", "fields": "fields",
          "values": "values", "coordinates": "dimensions", "rows": "rows"}

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
ASKING = ("find", "docfield", "coord", "search")

LIBRARY = {box.type: box for box in (
    # -- start ---------------------------------------------------------------
    Box("document", "Document", "start", "", "document",
        "This step is the document the run reads: its pages, lines, tables "
        "and figures, and its title page. The title page is the first "
        "lines of the first page, or of another page where the first page "
        "has none. Every later step starts from this document. To change "
        "it: set how many lines the title page has, and set in the rules "
        "drawer which page is used as title page where the first page has "
        "none (`title_page_also`).",
        "surveyed.SurveyedHarvest.plan_of",
        settings=(Setting("title_page_lines", NUMBER, "lines of the title "
                          "page", number="title_page_lines"),
                  Setting("title_page_also", RULE, "the page used as title "
                          "page where the first page has none",
                          help="Where the first page has no text, for "
                          "example because it is a cover picture, the "
                          "first lines of this page are the title page. "
                          "A larger number takes a later page.")),
        fixed="Every flow starts with the document, so this step cannot "
              "be removed or switched off.",
        switch=False, prepares=True, top=True),
    # -- prepare -------------------------------------------------------------
    Box("transcribe", "Transcribe the figures", "prepare", "document",
        "document",
        "Each figure that has an image is written out once per run as "
        "lines: its caption (title, axes and legend) and its numbers. No "
        "other request is sent the image, they all read these lines. To "
        "change it: switch the step off, and no figure is written out, so "
        "a request shows a figure as its description; set, with a "
        "condition on the figure, which figures are written out; or set "
        "the follow-up questions and the answers in the wrong form. The "
        "prompt `transcribe` in the Prompts tab sets how the model is "
        "asked to write a figure out, and the step Cut into chunks sets "
        "how the lines are cut.",
        "addressed.Transcripts", asks="transcribe", settings=NUMBERS,
        decided="2026-11-09", prepares=True, top=True),
    Box("split", "Cut into chunks", "prepare", "document", "pieces",
        "The document's lines are cut into chunks, the units that every "
        "request shows. A new chunk begins where a section, table or "
        "figure begins, where the chunk is full, and where your condition "
        "holds. A table's title and head and a figure's caption go with "
        "each of its chunks. To change it: set the lines of a chunk, add "
        "a condition for a new chunk, let a chunk hold several sections, "
        "tables or figures, or switch off what goes with each chunk.",
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
        fixed="Every request shows chunks, so this step cannot be removed "
              "or switched off.",
        switch=False, decided="2026-11-08", prepares=True, top=True),
    Box("lists", "Lists of the document", "prepare", "pieces", "pieces",
        "While a document is read, the run keeps a list of the scenarios "
        "it names and a list of the works it names (other studies or "
        "plans it presents, compares or cites). This publication is "
        "always the first work. Each name the model reads in a chunk is "
        "looked up in its list: a name the list has already gets that "
        "entry, and a new name becomes a new entry. To change it: which "
        "fields and dimensions build such a list is set by the key "
        "`merged` in the Spec tab, and what is asked about a new work is "
        "set under the works in the Spec tab.",
        "addressed.Reader.lists_of",
        fixed="Every name that the Spec merges becomes an entry of the "
              "document's list, so this step cannot be removed or "
              "switched off.",
        switch=False, prepares=True, top=True),
    # -- order ---------------------------------------------------------------
    Box("sentences", "Order the chunks for each field", "order", "pieces",
        "pieces",
        "For each field that is read chunk by chunk, the model writes a "
        "search sentence, a sentence as this document would print a value "
        "of the field, and the chunks are ordered best first by it. The "
        "order is stored with the harvest. Fields asked once per document "
        "are not part of this step. To change it: switch the step off, "
        "and every field reads its chunks in the document's order, or "
        "change the prompt `phrase` in the Prompts tab, which sets how "
        "the sentence is written.",
        "addressed.Orders", asks="phrase", settings=NUMBERS, top=True),
    Box("order", "Search the chunks", "order", "pieces", "supply",
        "The search finds the chunks that best match the search sentence. "
        "The best chunks of each kind are taken first, up to the share of "
        "tables, figures and text, then the best of the rest fill the "
        "total, and the reranker orders them once with the same sentence. "
        "Chunks already shown are left out. The result is the search "
        "hits. To change it: set the number of chunks, the three shares, "
        "whether a field with a list reads several times as many, "
        "whether the rest of the document follows, and whether the "
        "reranker orders them (`rerank`).",
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
    Box("beside", "Neighbouring chunks", "order", "pieces", "supply",
        "The chunks right before and after the chunk in which the value "
        "stands. They are shown together as search hits, so the model "
        "sees what surrounds the value. To change it: the step has no "
        "settings of its own. Switched off, the request shows only the "
        "hits of the search; you can also draw the step elsewhere in the "
        "flow.",
        "addressed.Plan.beside", needs=("coordinate",)),
    # -- ask -----------------------------------------------------------------
    Box("docfield", "Ask a field of the whole document", "ask", "supply",
        "answers",
        "This step asks a field that a document states once, or a field "
        "of the whole document such as its base year. A request shows the "
        "title page and a few search hits, and every find that passes the "
        "checks is kept. The model may ask to see a chapter a shown line "
        "points to, which comes first in the next request. To change it: "
        "set the chunks per request, whether the title page goes with the "
        "first request, the follow-up questions, the answers in the wrong "
        "form, up to how many entries a list shows what they mean and what "
        "the model may ask to see (`fetches`). Which fields are asked here "
        "is set by the key `once_per_document` in the Spec tab, and how "
        "they are asked by the prompt `docfield`.",
        "addressed.Reader.ask_window", asks="docfield",
        needs=("field", "settled"),
        settings=(PER_REQUEST,
                  Setting("title_page", SWITCH, "the title page with the "
                          "first request", True,
                          help="On: the first request of a field shows the "
                          "title page besides the search hits, which "
                          "suits what a title page states. Off: it shows "
                          "only the search hits.",
                          rule="docfield_title_page"), FOLLOW, REPLIES,
                  MEANINGS, FETCHES),
        decided="2026-11-08, 2026-11-12", marks=CHECKS),
    Box("works", "Ask the works of each chunk", "ask", "pieces", "values",
        "For each chunk the model says which lines speak of another work "
        "(a study or plan that is presented, compared or cited), and "
        "which line shows that the remaining lines belong to this "
        "publication. Each named work is matched against the document's "
        "list of works, and each new work is asked for its details. "
        "Where the chunk names a work only in short, the model may fetch "
        "the place that names it in full, such as the list of references, "
        "and the detail is asked again with it. To change it: set the "
        "follow-up questions, the answers in the wrong form and what the "
        "model may ask to see (`fetches`, `fetch_rounds`). What is asked "
        "about a new work is set under the works in the Spec tab, which "
        "this step needs.",
        "addressed.Reader.works", asks="work",
        settings=NUMBERS + (FETCHES, FETCH_ROUNDS),
        decided="2026-11-09, 2026-11-12", spec="works", top=True),
    Box("find", "Ask the values in a chunk", "ask", "pieces", "answers",
        "For one chunk and one field, the model reads the values: for "
        "each one the line number and its wording, and the entry where "
        "the field has a list. An answer too long for its token limit is "
        "asked again for each half of the chunk. The fixed checks shown "
        "here apply to every answer. To change it: set the follow-up "
        "questions, the answers in the wrong form and up to how many "
        "entries a list shows what they mean. The prompt `find` and the "
        "keys of the field in the Spec tab shape the question.",
        "addressed.Reader.find", asks="find", needs=("piece",),
        settings=(FOLLOW, REPLIES, MEANINGS), decided="2026-11-08",
        marks=CHECKS),
    Box("coord", "Ask a dimension where the value stands", "ask",
        "coordinates", "answers",
        "This step asks one dimension of a value (such as its year or "
        "energy carrier) at the place where the value stands. The request "
        "shows the value's line with the head of its table or the "
        "sentences around it, the headings above it, the title page and "
        "the fields of the whole document. The answer is a line number "
        "and its wording, or 0, and a list entry is asked once per "
        "wording. The model may ask to see what a shown line points to, "
        "such as \"see figure 12\", which the search shows first, and the "
        "picture of a figure it shows. To change it: set the follow-up "
        "questions, the answers in the wrong form, the list meanings, the "
        "sentences around the value and what the model may ask to see "
        "(`fetches`). The prompt `coord` shapes the question.",
        "addressed.Reader.ask_own_place", asks="coord",
        needs=("coordinate",),
        settings=(FOLLOW, REPLIES, MEANINGS,
                  Setting("lines_around", RULE,
                          "sentences around the value",
                          help="In running text a request shows this many "
                          "lines before and after the value's line, in a "
                          "table the value's row under the table head. A "
                          "larger number gives the model more context and "
                          "makes each request longer."), FETCHES),
        decided="2026-11-08, 2026-11-12", marks=CHECKS),
    Box("quantity", "Ask what a number is", "ask", "coordinates", "answers",
        "This step finds out what a number is, such as a demand or a "
        "share, from the words it was read with: its label, the head of "
        "its column and its unit. The model chooses the matching entry "
        "of the list. To change it: set up to how many entries the list "
        "shows what they mean, and edit the entries of the list in the "
        "Spec tab. The prompt `list` shapes the question.",
        "addressed.Reader.quantity", asks="list", needs=("coordinate",),
        settings=NUMBERS, decided="2026-11-08"),
    Box("work_coordinate", "Ask a value's work", "ask", "coordinates",
        "answers",
        "This step decides which work a value belongs to. If the line of "
        "the value names a work, that is its work. Otherwise the model "
        "chooses an entry of the document's list of works, and 0 means "
        "that the work is not stated. This step never searches the "
        "document. To change it: set the follow-up questions. The step "
        "needs the works in the Spec tab, and the prompt `coord` shapes "
        "the question.",
        "addressed.Reader.work_coordinate", asks="coord",
        needs=("coordinate",), settings=NUMBERS, decided="2026-11-09",
        spec="works"),
    Box("phrase", "Write the search sentence", "ask", "coordinates",
        "coordinates",
        "This step writes a sentence as the document would print the "
        "answer, once for each field, dimension and wording. The search "
        "uses it to find the chunks. To change it: switch on a new "
        "sentence from round 2, or decide whether a question may stand in "
        "for the sentence. The prompt `phrase` in the Prompts tab shapes "
        "how the sentence is written.",
        "addressed.Reader.search_sentence", asks="phrase",
        needs=("coordinate",),
        settings=(Setting("anew", SWITCH, "a new sentence from round 2, "
                          "written knowing the earlier ones", False,
                          help="On: from the second round on the model "
                          "writes a new sentence and sees the sentences "
                          "of the earlier rounds, so it can try another "
                          "wording. Off: the first sentence is used in "
                          "every round.",
                          rule="phrase_anew"),
                  Setting("question_as_sentence", RULE,
                          "a question may stand in for the sentence",
                          help="On: if the model writes a question "
                          "instead of a sentence, the search uses the "
                          "question, and the run counts it. Off: the "
                          "search then uses the field's own sentence."))
        + NUMBERS, decided="2026-11-09"),
    Box("search", "Ask over the search hits", "ask", "supply", "answers",
        "This step asks about one dimension of a value over the search "
        "hits. A request shows the value's own place and a few search "
        "hits. Chunks the model asks to see come first in the next "
        "request, and no chunk is shown twice; it may also ask once for "
        "the picture of a figure it shows. To change it: set the chunks "
        "per request, the follow-up questions, the answers in the wrong "
        "form and what the model may ask to see (`fetches`). The prompt "
        "`search` shapes the question.",
        "addressed.Reader.search_round, addressed.Reader.fetch",
        asks="search", needs=("round", "coordinate"),
        settings=(PER_REQUEST, FOLLOW, REPLIES, MEANINGS, FETCHES),
        decided="2026-11-09, 2026-11-12", marks=CHECKS),
    Box("last_year", "Ask the document's years", "ask", "coordinates",
        "answers",
        "A year that no earlier step found is asked last. The request "
        "shows the line of the value and the document's base and target "
        "years, and the model chooses the year the line means. To change "
        "it: switch the step off. The years come from the fields of the "
        "whole document, and the prompt `list` shapes the question.",
        "addressed.Reader.last_year", asks="list", needs=("coordinate",),
        settings=NUMBERS, decided="2026-11-07"),
    Box("names", "Ask the list entry of a name", "ask", "values", "values",
        "This step looks up a value that names a scenario in the "
        "document's list: either the entry it is, or a new entry where "
        "the name is not on the list yet. The model may also answer 0, "
        "then the value stays read without an entry. Words for several "
        "entries (\"all scenarios\") become one row per member where the "
        "field allows it. Where a short name is explained elsewhere, the "
        "model may fetch that place, and the name is asked again with it. "
        "To change it: what the model may ask to see (`fetches`, "
        "`fetch_rounds`) and the keys `merged` and `takes_group` of the "
        "field in the Spec tab, which this step needs.",
        "addressed.Reader.named_value", asks="names", needs=("value",),
        settings=NUMBERS + (FETCHES, FETCH_ROUNDS),
        decided="2026-11-08, 2026-11-12", spec="names"),
    # -- check ---------------------------------------------------------------
    Box("about", "Is the find about this value?", "check",
        "answers", "answers",
        "A find from another section, table or figure than the value's "
        "own is kept only where the model says that place is about this "
        "value. The step checks the answers of the search step before "
        "it. To change it: switch it off, then such finds are not "
        "checked by this question. The prompt `check` shapes the "
        "question.",
        "addressed.Reader.about", asks="check", needs=("coordinate",),
        attached=("search",), settings=NUMBERS, decided="2026-11-07"),
    Box("check", "Own check", "check", "answers", "answers",
        "This is a check of your own for the answers of the asking step "
        "before it. An answer is refused where your condition holds, and "
        "is asked again with your sentence. It can only add refusals "
        "and never accept what the fixed checks refuse. Its refusals are "
        "counted under check:<name>. To change it: set the name, the "
        "condition and the sentence, or switch the check off.",
        "engine.own_checks", attached=ASKING,
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
        "An answer that holds for the whole document, such as its "
        "settings, its base year or its target year, is kept here, and "
        "every later request shows it. To change it: switch the step "
        "off, then later requests do not show these answers. Which "
        "fields are fields of the whole document is set in the Spec "
        "tab.",
        "addressed.Reader.settle_found", needs=("settled",),
        decided="2026-11-08"),
    Box("state", "Set the state", "state", "coordinates", "coordinates",
        "This step gives a dimension that is still open here its final "
        "state. By the search hits it stays open where chunks are left "
        "that were never shown, and otherwise it is not stated in the "
        "document. A dimension that was not asked because another "
        "dimension excludes the value keeps that state. To change it: "
        "choose the state this step sets.",
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
    # -- end -----------------------------------------------------------------
    Box("write", "Write the harvest", "end", "rows", "rows",
        "The run writes the harvest: every row with the states of its "
        "dimensions, the summary and the stamp. This step stands once, at "
        "the "
        "end of the flow. To change it: nothing is set here, what is "
        "written follows from the steps before.",
        "runner, pipeline",
        fixed="A run always writes what it read, so this step cannot be "
              "removed or switched off.",
        switch=False, top=True),
    Box("compute", "Compute shares and sums", "end", "rows", "rows",
        "Once a document is read, the rows that passed the checks are "
        "gone through for what they leave open: the absolute number of a "
        "share, or the sum of parts. For each question the model writes "
        "code, the sandbox runs it, and a new row with the code, its "
        "output and its input numbers as proof comes out. To change it: "
        "switch the step off, then no number is computed. The step takes "
        "part only where the profile says what it computes (the profile "
        "kwp does); which shares and sums those are is set in the "
        "profile's code, not on this page. The prompt `compute` shapes "
        "the question.",
        "compute.py", asks="compute", settings=NUMBERS,
        decided="2026-11-02", spec="compute", top=True),
    Box("catalogue", "Look the publication up in a catalogue", "end",
        "rows", "rows",
        "Once a document is read and computed, what its front pages leave "
        "open of the publication's DOI, year and authors is looked up in "
        "an open catalogue of publications: by the DOI the corpus index "
        "holds for the file, by the DOI read in the document or by its "
        "title, in the order this step sets, and a hit by its title counts "
        "only where enough of its authors agree with the authors read. A "
        "value found there is written with the catalogue's record as its "
        "proof. To change it: switch the step off, then nothing is looked "
        "up; what is looked up and how is set at this step. The step takes "
        "part only where the profile says how its publications are looked "
        "up (the profile scenarios does).",
        "profiles/<name>/completion.py", decided="2026-11-04", top=True),
)}

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
    _pass("review", "Second reading", "rows", "answers",
          "Each row of the trust levels C and D is read a second time, "
          "over its own passage and the section above it, with the "
          "picture where there is one: one request for each row. The "
          "row only gets a mark, agree, disagree or unbacked, and what "
          "the second reading said goes into the working list. To "
          "change it: the rules `review_levels`, `review_once_per_row`, "
          "`review_shown_passages` and `review_limit` say which rows are "
          "read and how many; the prompt `review` shapes the question.",
          "review.review_row", "chain", after=("stored",), asks="review",
          decided="2026-09-13"),
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
    _pass("example", "Example for a field", "", "answers",
          "This is the request that proposes an example for a field "
          "while a spec is compiled. No run starts it. It stands here so "
          "that its answer room and its temperature are set like those "
          "of any request.",
          "compile.cli.ask_for_example", "run", asks="example"),
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
}
# ... and its name on the page
EACH_TITLES = {"settled": "For each field of the whole document",
               "field": "For each field", "piece": "For each chunk",
               "value": "For each value", "coordinate": "For each dimension"}
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


def catalogue() -> dict:
    """The library as the page shows it: the boxes of the main flow, and
    apart from them the boxes of the follow-up passes."""
    def setting(s: Setting) -> dict:
        return {"key": s.key, "kind": s.kind, "label": s.label,
                **({"default": s.default} if s.default is not None else {}),
                **({"number": s.number} if s.number else {}),
                **({"choices": list(s.choices)} if s.choices else {}),
                **({"words": dict(zip(s.choices, s.words))}
                   if s.words else {}),
                **({"help": s.help} if s.help else {}),
                **({"where": list(s.where)} if s.where else {}),
                **({"rule": s.rule} if s.rule else {})}

    def entry(b: Box) -> dict:
        return {"type": b.type, "label": b.label, "group": b.group,
                "takes": b.takes, "gives": b.gives, "says": b.says,
                "code": b.code, "asks": b.asks, "needs": list(b.needs),
                "settings": [setting(s) for s in b.settings],
                "fixed": b.fixed, "switch": b.switch,
                "decided": b.decided, "attached": list(b.attached),
                "prepares": b.prepares, "spec": b.spec, "top": b.top,
                "marks": list(b.marks)}

    return {
        "boxes": [entry(b) for b in LIBRARY.values() if not b.flow],
        "pass_boxes": [{**entry(b), "scope": b.scope,
                        "after": list(b.after), "inside": b.inside}
                       for b in LIBRARY.values() if b.flow],
        "each": EACH, "each_titles": EACH_TITLES, "which": WHICH,
        "orders": {k: list(v) for k, v in ORDERS.items()},
        "order_words": ORDER_WORDS, "arrows": ARROWS,
    }
