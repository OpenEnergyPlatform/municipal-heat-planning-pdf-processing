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


FOLLOW = Setting("follow_ups", NUMBER, "follow-up questions",
                 number="follow_ups",
                 help="How often an answer that failed a check is asked "
                 "again. Each time the request shows the answer and what "
                 "failed, so the model can correct it. With 0 an answer "
                 "that fails a check is not asked again.")
REPLIES = Setting("replies", RULE, "answers in the wrong form, at most",
                  number="replies",
                  help="An answer that does not come back in the expected "
                  "form is asked again with the reason. This is how many "
                  "such answers a request accepts before it is left "
                  "without an answer. The run setting EXTRACT_MAX_RETRIES "
                  "overrides this number.")
PER_REQUEST = Setting("per_request", NUMBER, "chunks per request",
                      number="search_per_request")
MEANINGS = Setting("list_meanings", RULE, "show what each list entry "
                   "means, up to", number="list_meanings",
                   help="A list with at most this many entries is shown "
                   "with what each entry means. A longer list shows only "
                   "the names of its entries, and a list with groups is "
                   "asked in two steps, first the group, then the entry.")
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
        "change it: the step itself has no setting, but the prompt "
        "`transcribe` in the Prompts tab sets how the model is asked to "
        "write a figure out, and the step Cut into chunks sets how the "
        "lines are cut.",
        "addressed.Transcripts", asks="transcribe",
        fixed="Every request shows a figure as these lines and never as "
              "the image, so this step cannot be removed or switched off.",
        switch=False, decided="2026-11-09", prepares=True, top=True),
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
                          "table and figure begins a new chunk."),
                  Setting("table_head", SWITCH, "a table's title and head "
                          "go with each of its chunks", True,
                          help="On: every chunk of a table starts with the "
                          "table's title and head, so a row is always read "
                          "under its column headings. Off: only the first "
                          "chunk of the table has them. Decided on "
                          "2026-11-02."),
                  Setting("caption", SWITCH, "a figure's caption goes with "
                          "each of its chunks", True,
                          help="On: every chunk of a figure starts with the "
                          "figure's caption, so its numbers are read with "
                          "title, axes and legend. Off: only the first "
                          "chunk of the figure has the caption."),
                  Setting("figure_numbers", SWITCH, "a figure's numbers in "
                          "chunks of their own, its caption in one", True,
                          help="On: the caption of a figure is a chunk of "
                          "its own and its numbers are chunks of their "
                          "own, each shown with the caption. Off: the "
                          "lines of a figure are cut like any other lines. "
                          "Decided on 2026-11-09."),
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
        "addressed.Orders", asks="phrase", top=True),
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
                          "chunks as any other field."),
                  Setting("factor", NUMBER, "times as many for a field with "
                          "a list", number="listed_field_factor",
                          where=("field",)),
                  Setting("rest_after", SWITCH, "after them the rest of the "
                          "document", False, where=("field", "settled"),
                          help="On: after the best chunks the remaining "
                          "chunks of the document follow in the order of "
                          "the search, so every chunk can still be shown. "
                          "Off: only the best chunks are offered."),
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
        "checks is kept. To change it: set the chunks per request, "
        "whether the title page goes with the first request, the "
        "follow-up questions, the answers in the wrong form and up to "
        "how many entries a list shows what they mean. Which fields are "
        "asked here is set by the key `once_per_document` in the Spec "
        "tab, and how they are asked by the prompt `docfield`.",
        "addressed.Reader.ask_window", asks="docfield",
        needs=("field", "settled"),
        settings=(PER_REQUEST,
                  Setting("title_page", SWITCH, "the title page with the "
                          "first request", True,
                          help="On: the first request of a field shows the "
                          "title page besides the search hits, which "
                          "suits what a title page states. Off: it shows "
                          "only the search hits."), FOLLOW, REPLIES,
                  MEANINGS),
        decided="2026-11-08", marks=CHECKS),
    Box("works", "Ask the works of each chunk", "ask", "pieces", "values",
        "For each chunk the model says which lines speak of another work "
        "(a study or plan that is presented, compared or cited), and "
        "which line shows that the remaining lines belong to this "
        "publication. Each named work is matched against the document's "
        "list of works, and each new work is asked for its details. To "
        "change it: set the follow-up questions and the answers in the "
        "wrong form. What is asked about a new work is set under the "
        "works in the Spec tab, which this step needs.",
        "addressed.Reader.works", asks="work",
        settings=(FOLLOW, REPLIES), decided="2026-11-09", spec="works",
        top=True),
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
        "wording. To change it: set the follow-up questions, the answers "
        "in the wrong form, the list meanings and the sentences around "
        "the value. The prompt `coord` shapes the question.",
        "addressed.Reader.ask_own_place", asks="coord",
        needs=("coordinate",),
        settings=(FOLLOW, REPLIES, MEANINGS,
                  Setting("lines_around", RULE,
                          "sentences around the value",
                          help="In running text a request shows this many "
                          "lines before and after the value's line, in a "
                          "table the value's row under the table head. A "
                          "larger number gives the model more context and "
                          "makes each request longer.")),
        decided="2026-11-08", marks=CHECKS),
    Box("quantity", "Ask what a number is", "ask", "coordinates", "answers",
        "This step finds out what a number is, such as a demand or a "
        "share, from the words it was read with: its label, the head of "
        "its column and its unit. The model chooses the matching entry "
        "of the list. To change it: set up to how many entries the list "
        "shows what they mean, and edit the entries of the list in the "
        "Spec tab. The prompt `list` shapes the question.",
        "addressed.Reader.quantity", asks="list", needs=("coordinate",),
        settings=(MEANINGS,), decided="2026-11-08"),
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
        needs=("coordinate",), settings=(FOLLOW,), decided="2026-11-09",
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
                          "every round."),
                  Setting("question_as_sentence", RULE,
                          "a question may stand in for the sentence",
                          help="On: if the model writes a question "
                          "instead of a sentence, the search uses the "
                          "question, and the run counts it. Off: the "
                          "search then uses the field's own sentence.")),
        decided="2026-11-09"),
    Box("search", "Ask over the search hits", "ask", "supply", "answers",
        "This step asks about one dimension of a value over the search "
        "hits. A request shows the value's own place and a few search "
        "hits. Chunks the model asks to see come first in the next "
        "request, and no chunk is shown twice. To change it: set the "
        "chunks per request, the follow-up questions, the answers in the "
        "wrong form and what the model may ask to see (`fetches`). The "
        "prompt `search` shapes the question.",
        "addressed.Reader.search_round, addressed.Reader.fetch",
        asks="search", needs=("round", "coordinate"),
        settings=(PER_REQUEST, FOLLOW, REPLIES,
                  Setting("fetches", RULE, "what the model may ask to "
                          "see",
                          help="The ways in which an answer may ask for "
                          "more chunks: the next or previous chunk, a "
                          "table or figure it names, a search for a "
                          "pattern and chunks similar to one shown. "
                          "Chunks fetched this way do not count against "
                          "the chunks of the search. Removing an entry "
                          "forbids that way.")),
        decided="2026-11-09", marks=CHECKS),
    Box("last_year", "Ask the document's years", "ask", "coordinates",
        "answers",
        "A year that no earlier step found is asked last. The request "
        "shows the line of the value and the document's base and target "
        "years, and the model chooses the year the line means. To change "
        "it: switch the step off. The years come from the fields of the "
        "whole document, and the prompt `list` shapes the question.",
        "addressed.Reader.last_year", asks="list", needs=("coordinate",),
        decided="2026-11-07"),
    Box("names", "Ask the list entry of a name", "ask", "values", "values",
        "This step looks up a value that names a scenario in the "
        "document's list: either the entry it is, or a new entry where "
        "the name is not on the list yet. The model may also answer 0, "
        "then the value stays read without an entry. Words for several "
        "entries (\"all scenarios\") become one row per member where the "
        "field allows it. To change it: the keys `merged` and "
        "`takes_group` of the field in the Spec tab, which this step "
        "needs.",
        "addressed.Reader.named_value", asks="names", needs=("value",),
        decided="2026-11-08", spec="names"),
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
        attached=("search",), decided="2026-11-07"),
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
                          "dimension, unless it already has a state."),)),
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
        "compute.py", asks="compute", decided="2026-11-02", spec="compute",
        top=True),
)}

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
    """The library as the page shows it."""
    def setting(s: Setting) -> dict:
        return {"key": s.key, "kind": s.kind, "label": s.label,
                **({"default": s.default} if s.default is not None else {}),
                **({"number": s.number} if s.number else {}),
                **({"choices": list(s.choices)} if s.choices else {}),
                **({"words": dict(zip(s.choices, s.words))}
                   if s.words else {}),
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
        "each": EACH, "each_titles": EACH_TITLES, "which": WHICH,
        "orders": {k: list(v) for k, v in ORDERS.items()},
        "order_words": ORDER_WORDS, "arrows": ARROWS,
    }
