"""
flowing.py: How the flow runs: its boxes and frames, the numbers each
step takes, the order things are asked in, what ends a round, and the
conditions (engine.py, flow.py, blocks.py, conditions.py, reading.py,
surveyed.py).

Every value here stood in the code, fixed, until 2026-11-11 (owner
decision 2026-11-11: "alles soll anpassbar sein"). Its standard is
today's value, set in the default profile's rules.json; a step or a
frame of the flow may give it a value of its own ("rules" of the box or
frame in flow.json).
"""
from .kit import rule

# The kinds of steps (`rules.step_kind`) that are frames.
FRAMES = ("each settled", "each field", "each piece", "each value",
          "each coordinate", "each list", "round", "if")
# Every box of the library: a condition is read wherever one stands.
BOXES = ("document", "transcribe", "split", "lists", "sentences", "order",
         "beside", "docfield", "works", "find", "coord", "quantity",
         "work_coordinate", "phrase", "search", "last_year", "names",
         "about", "check", "settle", "state", "write", "compute",
         "catalogue", "ask", "retrieve", "rerank", "set", "filter", "merge",
         "python")
EACH = tuple(kind for kind in FRAMES if kind.startswith("each"))

_STATES = ("read", "unstated", "unbacked", "exhausted", "unanswered",
           "derived", "out_of_slice")

from .taking import CHECKED  # noqa: E402

RULES = (
    # -- spec: what a quote must show -----------------------------------------
    rule("check_quote_shown", "spec", "What a quote must show", "switch",
         "On: the quote of an answer has to stand in what the request "
         "showed, a line or a cell of a line, or the answer is refused and "
         "asked again. Off: a quote that stands in nothing shown is looked "
         "for, character for character, in every passage of the document, "
         "and the first passage in the document's order that holds it is "
         "the value's place; a quote that stands nowhere falls all the "
         "same. An address that names no shown line is asked again either "
         "way: the switch is about the quote, not the address. This is the "
         "first of the two checks every answer passes. What happens when "
         "it is off was decided on 2026-11-12.",
         where="blocks.py (CHECKS), pipeline.py (place_of: merge_field), "
               "reading.py (passage_of), addressed.py (resolve), engine.py",
         steps=tuple(dict.fromkeys(("find", "docfield", "coord", "search")
                                   + CHECKED))),
    rule("check_answer_in_quote", "spec", "What a quote must show",
         "switch",
         "On: the words of an answer have to stand in the line or cell it "
         "names, a number as a number and a wording as text, or the answer "
         "is refused and asked again. Off: that check is left out and the "
         "words are taken as they are. This is the second of the two "
         "checks every answer passes.",
         where="blocks.py (CHECKS), addressed.py (resolve), pipeline.py "
               "(merge_field), verify.py",
         steps=tuple(dict.fromkeys(("find", "docfield", "coord", "search")
                                   + CHECKED))),
    # -- spec: lists and wording ----------------------------------------------
    # -- spec: numbers and years ----------------------------------------------
    rule("settled_years_taken", "spec", "Numbers and years", "choice",
         "Which years of the words found for the base or the target year "
         "of a document become that year. All: every year the words name. "
         "First: only the first year the words name, so that words such as "
         "\"2020 and 2019\" give one year. Decided on 2026-09-22 and "
         "2026-10-06.", choices=("all", "first"),
         decided="2026-09-22, 2026-10-06", where="engine.py (box_settle)",
         steps=("settle",)),
    # -- spec: spans ----------------------------------------------------------
    rule("link_range_ends", "spec", "Spans of years and groups", "switch",
         "On: when a text prints a range, the value read as its lower end "
         "and the next value read as its upper end are linked, if they "
         "have the same quote and the same answers to every other "
         "dimension, and both carry the two ends. Off: the two values stay "
         "apart. Decided on 2026-11-06.", decided="2026-11-06",
         where="reading.py (link_ranges)", steps=("each value",)),
    # -- flow: chunks ---------------------------------------------------------
    rule("split_across", "flow", "Chunks", "switch",
         "On: a chunk is filled up across the end of a section, table or "
         "figure, so it may hold lines of several of them. Off: every "
         "section, table and figure begins a new chunk. A value set at the "
         "box itself wins over this rule.",
         where="blocks.py (split), engine.py (cut)", steps=("split",)),
    rule("split_table_head", "flow", "Chunks", "switch",
         "On: every chunk of a table starts with the table's title and "
         "head, so a row is always read under its column headings. Off: "
         "only the first chunk of the table has them. A value set at the "
         "box itself wins over this rule. Decided on 2026-11-02.",
         decided="2026-11-02", where="blocks.py (split), engine.py (cut)",
         steps=("split",)),
    rule("split_caption", "flow", "Chunks", "switch",
         "On: every chunk of a figure starts with the figure's caption, so "
         "its numbers are read with title, axes and legend. Off: only the "
         "first chunk of the figure has the caption. A value set at the "
         "box itself wins over this rule.",
         where="blocks.py (split), engine.py (cut)", steps=("split",)),
    rule("split_figure_numbers", "flow", "Chunks", "switch",
         "On: the caption of a figure is a chunk of its own and its "
         "numbers are chunks of their own, each shown with the caption. "
         "Off: the lines of a figure are cut like any other lines. A value "
         "set at the box itself wins over this rule. Decided on "
         "2026-11-09.", decided="2026-11-09",
         where="blocks.py (split), engine.py (cut)", steps=("split",)),
    # -- flow: documents ------------------------------------------------------
    rule("include_kinds", "flow", "Documents", "texts",
         "Which kinds of passages of a document are read: text, tables and "
         "figures. A kind left out is neither cut into chunks nor shown in "
         "any request; a figure left out is not transcribed either. At "
         "least one kind must stay.",
         choices=("section", "table", "figure"),
         where="engine.py (plan)", steps=("document",)),
    rule("pages", "flow", "Documents", "range",
         "The pages of a document that are read, from the first to the "
         "last. Passages on other pages, and passages whose page is not "
         "known, are left out of every request. Empty: all pages are "
         "read.", empty=True, where="engine.py (plan)",
         steps=("document",)),
    rule("plans_kept", "flow", "Documents", "whole",
         "How many documents a pass over a stored harvest keeps in memory "
         "at once, each with its chunks. A larger number saves cutting a "
         "document again when a pass asks several batches of it, and uses "
         "more memory.", least=1,
         where="surveyed.py (plan_of, read_plan)"),
    # -- flow: search ---------------------------------------------------------
    rule("search_list_factor_on", "flow", "Search", "switch",
         "On: a field whose values are chosen from a list gets the number "
         "of chunks multiplied by the factor of the flow, because it has "
         "to choose among many entries. Off: it gets as many chunks as any "
         "other field. A value set at the box itself wins over this rule.",
         where="blocks.py (order), engine.py (_order)",
         steps=("order",)),
    rule("search_rest_after", "flow", "Search", "switch",
         "On: after the best chunks the remaining chunks of the document "
         "follow in the order of the search, so every chunk can still be "
         "shown. Off: only the best chunks are offered. A value set at the "
         "box itself wins over this rule.",
         where="blocks.py (order), engine.py (_order)", steps=("order",)),
    rule("phrase_anew", "flow", "Search", "switch",
         "On: from the second round on the model writes a new search "
         "sentence and sees the sentences of the earlier rounds, so it can "
         "try another wording. Off: the first sentence is used in every "
         "round. A value set at the box itself wins over this rule.",
         where="presets.py (phrase), shows.py (sentences_before)",
         steps=("phrase",)),
    rule("phrase_new_from_round", "flow", "Search", "whole",
         "From which round on a new search sentence is written, where "
         "writing a new sentence is on. Round 2 is the first round that can "
         "know an earlier sentence.", least=1,
         where="shows.py (sentences_before)", steps=("phrase",)),
    rule("search_skips_own_piece", "flow", "Search", "switch",
         "On: the chunk in which the value stands is left out of every "
         "search, because the first request about the dimension has shown "
         "it already. Off: the search may show that chunk again. Decided "
         "on 2026-11-09.", decided="2026-11-09",
         where="engine.py (locate)",
         steps=("order", "beside", "coord", "search", "state")),
    rule("fetch_after_found", "flow", "Search", "switch",
         "On: chunks that an answer asked to see are still fetched when "
         "the same answer already gave a value, or a value not backed by "
         "its quote. Off: such a request lapses as soon as a value is read "
         "or not backed. Decided on 2026-11-09.", decided="2026-11-09",
         where="targets.py (over_hits)", steps=("search",)),
    rule("supply_order", "flow", "Search", "texts",
         "The order in which a search shows the chunks it can show: "
         "\"fetched\" are the chunks an earlier answer asked to see, "
         "\"beside\" the chunks next to the value's own chunk, and "
         "\"ranked\" the best chunks of the search sentence. Chunks of the "
         "kinds before \"ranked\" are shown together first; the ranked "
         "chunks follow only where none of them is left. Chunks of a kind "
         "that is left out are never shown. Decided on 2026-11-09.",
         choices=("fetched", "beside", "ranked"), decided="2026-11-09",
         where="engine.py (SearchSupply)", steps=("search",)),
    rule("round_ends", "flow", "Search", "choice",
         "When a round that runs until its supply is used up ends. After a "
         "turn without a chunk: the round ends after any turn in which no "
         "question showed a chunk of the supply. When no chunks are left: "
         "the round ends only when a question found nothing left to "
         "show; a turn in which no question was reached does not end it. "
         "A round with no most of its own still ends after such a turn, so "
         "that it cannot run for ever.",
         choices=("no_chunk_shown", "supply_used_up"),
         where="engine.py (round)", steps=("round",)),
    # -- flow: asking again ---------------------------------------------------
    rule("hole_passage", "flow", "Asking again and giving up", "choice",
         "Where the hole of a field asked once per document stands, when "
         "no request for it came to a value: a hole names a passage. First "
         "passage: the first passage of the document. Last passage: the "
         "last passage of the document. First asked: the first passage the "
         "field's first request showed. Decided on 2026-09-12.",
         choices=("first_passage", "last_passage", "first_asked"),
         decided="2026-09-12", where="engine.py (after_items)",
         steps=("each field",)),
    # -- flow: order ----------------------------------------------------------
    rule("coordinate_order", "flow", "Order", "texts",
         "The order in which the dimensions of a value are asked. Empty: "
         "the order of the spec's groups. Otherwise the dimensions named "
         "here come first, in this order, and the other dimensions follow "
         "in the order of the spec's groups.", empty=True,
         where="engine.py (each_coordinate)", steps=("each coordinate",)),
    rule("names_first", "flow", "Order", "switch",
         "On: the values that name a scenario of the document are asked "
         "before all other values, so that the other values can name the "
         "scenarios found. Off: values are asked in the order they were "
         "found. A frame of values with an order of its own wins over "
         "this rule.", where="engine.py (each_value)",
         steps=("each value",)),
    rule("this_publication_first", "flow", "Lists", "switch",
         "On: the list of works of a document starts with the publication "
         "itself, as its first entry, and a value that says it is the "
         "publication's own is read onto that entry. Off: the list "
         "starts empty and holds only the works the document names, so "
         "that every work a value is read for is another work.",
         where="addressed.py (lists_of, take_work)",
         steps=("lists", "works", "coord", "search", "work_coordinate",
                "each value")),
    rule("publication_description", "flow", "Lists", "choice",
         "How the first entry of the list of works, the publication "
         "itself, is described to the model. With title: as this "
         "publication and the first line of the title page, which names "
         "it. Plain: as this publication alone.",
         choices=("with_title", "plain"),
         where="addressed.py (lists_of)", steps=("lists",)),
    rule("together_pooled", "flow", "Order", "switch",
         "On: a frame side by side whose only step is another frame side "
         "by side asks both in one pool, for example each field with each "
         "of its chunks. Off: the items of the outer frame are asked side "
         "by side and the items inside each of them one after the other.",
         where="engine.py (each)", steps=EACH),
    rule("settled_fields", "flow", "Fields of the whole document", "texts",
         "The fields of the whole document that the run keeps for every "
         "later request: \"settings\" are the document's settings, "
         "\"base_year\" and \"target_year\" its base and target years; "
         "any other entry is the name of a field of the spec, whose "
         "finds are then shown in the block of settings of every later "
         "request. A field left out is not asked before the reading and "
         "not shown.", where="engine.py (items)", steps=("each settled",)),
    # -- flow: states ---------------------------------------------------------
    rule("state_mode", "flow", "States", "choice",
         "The state this step gives a dimension that is still open. By the "
         "search hits: open if chunks of the search were never shown, "
         "else not stated in the document. Not stated in the document: it "
         "is marked so at once. No answer: a request about it got no "
         "answer in form. Not asked: it is marked as excluded by "
         "another dimension, unless it already has a state. A value set at "
         "the box itself wins over this rule.",
         choices=("by_supply", "unstated", "unanswered", "out_of_slice"),
         where="blocks.py (state), engine.py (box_state)",
         steps=("state",)),
    rule("open_states", "flow", "States", "texts",
         "The states of a dimension that count as still open: the "
         "dimension was not read and may still be read. A condition "
         "\"open\" holds for them, and a run that tops up open values "
         "reads them again. Decided on 2026-11-02.", choices=_STATES,
         decided="2026-11-02",
         where="fields.py (open_states), conditions.py, topup.py, stats.py",
         steps=FRAMES + BOXES + ("open", "summary")),
    # -- flow: calculation ----------------------------------------------------
    rule("hit_line_chars", "flow", "Calculation", "whole",
         "How many characters of the first line of a passage a list of "
         "hits shows to the calculation's request. A larger number "
         "shows more of each hit and makes the request longer.", least=1,
         where="reading.py (first_line)", steps=("compute",)),
)
