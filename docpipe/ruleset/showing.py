"""
showing.py: What a request shows, cutting a document into chunks, the order of
the flow, conditions (addressed.py, units.py, engine.py, flow.py, blocks.py,
conditions.py, reading.py).
"""
from .kit import TAKING, rule

_r = rule

# The steps whose request may ask a list of its own (a wording against an
# entry list, a name against the names, a year against the plan's years).
LISTED = ("docfield", "works", "find", "coord", "quantity",
          "work_coordinate", "search", "last_year", "names")
# The steps whose request shows lines of a place of the document.
PLACED = ("docfield", "works", "find", "coord", "work_coordinate", "search",
          "last_year")
SHOWN = "What a request shows"
RULES: tuple = (
    # -- flow: what a request shows ---------------------------------------
    _r("show_title_page", "flow", SHOWN, "choice",
       "Whether a request shows the title page, the first lines of the "
       "document that tell the model which document it reads. Always: every "
       "request of the step shows it. First: only the first request of the "
       "step in a document does. Never: no request of the step does. Showing "
       "it costs room in every request and helps where a value depends on "
       "which plan it is read from.",
       choices=("always", "first", "never"), steps=PLACED,
       where="addressed.py (title_page_shown)"),
    _r("show_headings", "flow", SHOWN, "switch",
       "Whether a request shows the headings above the place it asks about, "
       "as many as the number of headings says. Headings tell the model "
       "which section a line belongs to. Off: no heading is shown.",
       steps=("works", "find", "coord", "work_coordinate", "search",
              "last_year", "phrase", "about"),
       where="addressed.py (show_value)"),
    _r("show_settled", "flow", SHOWN, "switch",
       "Whether a request shows what the plan settles for all its values, "
       "such as its base year or its municipality, beside the entries of a "
       "list and the place of a value. Off: the request shows none of it.",
       steps=(
           "docfield", "works", "find", "coord", "quantity", "work_coordinate",
           "search", "last_year", "each value"),
       where="addressed.py (show_value, settings_of)"),
    _r("show_known", "flow", SHOWN, "switch",
       "Whether the request for one dimension of a value shows what the "
       "value has already been read as, in the words of the plan. This helps "
       "the model to read the dimension that is left. Off: the request "
       "shows nothing of it. Decided on 2026-10-22.",
       steps=("coord", "search"), decided="2026-10-22",
       where="addressed.py (coord_payload, search_round)"),
    _r("show_example", "flow", SHOWN, "switch",
       "Whether a request shows an example of the reply it asks for. The "
       "example shows the form of the reply with a placeholder wording. Off: "
       "the request shows none, and the model must find the form in the "
       "instruction alone. Decided on 2026-11-09.",
       steps=(
           "docfield", "works", "find", "coord", "quantity", "work_coordinate",
           "search", "last_year", "names", "about", "each value"),
       decided="2026-11-09", where="addressed.py (shown_example)"),
    _r("show_empty_example", "flow", SHOWN, "switch",
       "Whether a request that finds values shows, besides the example with "
       "a find, the example of the reply where nothing shown holds a value. "
       "Off: only the example with a find is shown. Decided on 2026-11-09.",
       steps=("docfield", "works", "find", "coord", "quantity",
              "work_coordinate", "search", "last_year", "names", "about"),
       decided="2026-11-09", where="addressed.py (shown_example)"),
    _r("field_text", "flow", SHOWN, "choice",
       "How much of its description a request shows of the field it asks "
       "about. Short: the short description the spec gives, where it has "
       "one. Whole: the full description. A longer text explains the field "
       "better and takes more room.",
       choices=("short", "whole"),
       steps=("docfield", "works", "find", "coord", "work_coordinate",
              "search"), where="addressed.py (field_shown)"),
    _r("show_passage_page", "flow", SHOWN, "switch",
       "Whether a request shows the page of each chunk it shows. The page "
       "tells the model where in the document a chunk stands. Off: no page "
       "is shown.", steps=PLACED + ("about",),
       where="addressed.py (block_payload)"),
    _r("show_passage_title", "flow", SHOWN, "switch",
       "Whether a request shows the title of each table and figure chunk "
       "it shows. Off: only the lines of the chunk are shown, without a "
       "title of their own.", steps=PLACED + ("about",),
       where="addressed.py (block_payload)"),
    _r("rows_around", "flow", SHOWN, "whole",
       "How many rows above and below a value a request shows where the "
       "value stands in a table. 0 shows the row of the value and the "
       "title and head of the table only. A larger number shows the rows "
       "around the value too, so that the model sees its neighbours.",
       least=0,
       steps=("coord", "quantity", "work_coordinate", "search", "last_year",
              "phrase", "about"), where="addressed.py (show_value)"),
    _r("show_table_title", "flow", SHOWN, "switch",
       "Whether a request shows the title lines of a table with the table's "
       "rows. Off: the model sees the rows without their title.",
       steps=("docfield", "works", "find", "coord", "quantity",
              "work_coordinate", "search", "last_year", "phrase", "about"),
       where="units.py (own_lines, passage_lines)"),
    _r("show_table_head", "flow", SHOWN, "switch",
       "Whether a request shows the head lines of a table with the table's "
       "rows. Off: the model sees the rows without their column headings, "
       "although the run still knows the head of each column.",
       steps=("docfield", "works", "find", "coord", "quantity",
              "work_coordinate", "search", "last_year", "phrase", "about"),
       where="units.py (own_lines, passage_lines)"),
    _r("phrase_shows", "flow", SHOWN, "texts",
       "The parts the request that asks for the search sentence shows: the "
       "label and the description of the field, the document, the question, "
       "the value with its lines, the headings above it, and the sentences "
       "written before for the same value. A part that is left out is not "
       "shown.",
       choices=("label", "description", "document", "question", "value",
                "headings", "before"), steps=("phrase",),
       where="addressed.py (_sentence)"),
    _r("about_shows", "flow", SHOWN, "texts",
       "The parts the request shows that asks whether a find from another "
       "passage is about the value: the value, its passage, the headings "
       "above it, the question, the answer found and the place it was found "
       "in. A part that is left out is not shown.",
       choices=("value", "passage", "headings", "question", "answer",
                "place"), steps=("about",),
       where="addressed.py (about)"),
    _r("shown_block_order", "prompts", "How a place in the document is "
       "shown", "texts",
       "The order in which a request shows the blocks about a value: its "
       "place, the headings above it, the title page and what the plan "
       "settles. A block that is not named comes last in this order.",
       choices=("passage", "headings", "title_page", "settings"),
       steps=("coord", "work_coordinate", "search", "last_year"),
       where="addressed.py (blocks_in_order)"),
    # -- flow: chunks ------------------------------------------------------
    _r("bullet_marks", "flow", "Chunks", "chars",
       "The characters that mark an item of a list. A line is split before "
       "such a character when a space follows it, and a sentence may begin "
       "with one. Empty: no character marks a list item.", empty=True,
       steps=("split",),
       where="units.py (_bullet, _sentence_end)"),
    _r("split_bullets", "flow", "Chunks", "switch",
       "Whether a line is split before a list mark, so that each item of a "
       "list is a line of its own. A transcription often runs the items "
       "into one line. Off: such a line stays whole.",
       steps=("split",),
       where="units.py (_bullet)"),
    _r("split_ordinals", "flow", "Chunks", "switch",
       "Whether a point after a short number, as in \"3. October\", ends a "
       "sentence like any other point. Off: such a point ends no sentence.",
       steps=("split",),
       where="units.py (_ordinal)"),
    _r("ordinal_max_digits", "flow", "Chunks", "whole",
       "The most digits a number may have before a point so that the point "
       "ends no sentence, as in \"3. October\" or \"12. Section\". A larger "
       "number keeps more such points within a sentence.", least=1,
       steps=("split",),
       where="units.py (_ordinal)"),
    _r("abbreviation_lookahead_chars", "flow", "Chunks", "whole",
       "How many characters after a point the run looks at to recognize an "
       "abbreviation of two parts, such as \"z. B.\", whose first part ends "
       "a text. A longer look recognizes longer second parts.", least=0,
       steps=("split",),
       where="units.py (sentences_of)"),
    _r("cells_by_bar", "flow", "Chunks", "switch",
       "Whether a line that a vertical bar divides has cells, wherever it "
       "stands: a figure's line, a sentence, a row of a table. The model "
       "then names a cell by its number. Off: only the rows of a table have "
       "cells. Decided on 2026-11-09.", decided="2026-11-09",
       steps=("split",),
       where="units.py (line_cells)"),
    _r("table_title_lines", "flow", "Chunks", "switch",
       "Whether the lines above the head of a table count as lines of the "
       "table, its title lines, which every chunk of the table shows. Off: "
       "they are not lines of the table at all.",
       steps=("split",),
       where="units.py (table_lines)"),
    _r("table_head_lines", "flow", "Chunks", "switch",
       "Whether the head rows of a table count as lines of the table, "
       "which every chunk of the table shows. Off: the table has no head "
       "lines, and no cell has a column heading.",
       steps=("split",),
       where="units.py (table_lines)"),
    _r("table_rule_line", "flow", "Chunks", "switch",
       "Whether the rule under the head of a table counts as a line of "
       "its own. Off: it does not, so the first row under the head is the "
       "line after the last head line.", steps=("split",),
       where="units.py (table_lines)"),
    _r("figure_part", "flow", "Chunks", "choice",
       "Which chunks of a figure a field reads. By the kind of field: a "
       "field of numbers reads the chunks of its numbers and any other field "
       "the chunk of its caption. Caption: every field reads the caption. "
       "Numbers: every field reads the chunks of the numbers, each with the "
       "caption. Decided on 2026-11-09.",
       choices=("by_field", "caption", "numbers"), decided="2026-11-09",
       steps=(
           "sentences", "order", "docfield", "find", "beside",
           "search", "state", "works", "work_coordinate",
           "each field", "each piece"),
       where="addressed.py (Plan.part)"),
    _r("title_page_first", "flow", "Chunks", "whole",
       "The page whose first lines are tried first as the title page. The "
       "page of the rule \"the page whose first lines are the title page "
       "when the first page has none\" is tried after it. Decided on "
       "2026-11-08.", least=1, decided="2026-11-08", steps=("document",),
       where="units.py (title_page_of)"),
    _r("title_page_with_figures", "flow", "Chunks", "switch",
       "Whether the lines of a figure may be lines of the title page. Off: "
       "only text and tables are. Decided on 2026-11-08.",
       decided="2026-11-08", steps=("document",),
       where="units.py (title_page_of)"),
    _r("head_only_full_width", "prompts", "How a place in the document is "
       "shown", "switch",
       "Whether only a head line with as many cells as the rows of the "
       "table gives the heading of a column. Off: every head line does, "
       "also one with fewer cells, such as a heading over several columns. "
       "Decided on 2026-11-03.", decided="2026-11-03",
       steps=("docfield", "works", "find", "each value"),
       where="units.py (Passage.head_of)"),
    # -- flow: giving up on an answer that did not fit ---------------------
    _r("split_cut_off", "flow", "Asking again and giving up", "switch",
       "Whether a request whose answer was cut off at the limit is asked "
       "again in two halves. A cut-off answer is never read. Off: such a "
       "request is a hole at once. Decided on 2026-09-12.",
       decided="2026-09-12", steps=("find", "docfield"),
       where="addressed.py (Reader.halves)"),
    _r("split_by", "flow", "Asking again and giving up", "choice",
       "How a request is halved. Chunks then lines: first by its chunks, "
       "and a single chunk by its lines. Lines: by the lines of each chunk "
       "only.", choices=("chunks_then_lines", "lines"),
       steps=("find", "docfield"), where="addressed.py (Reader.halves)"),
    _r("split_most", "flow", "Asking again and giving up", "whole",
       "How often one request may be halved again and again. 0: until only "
       "a single line is left. A smaller number leaves larger parts as a "
       "hole.", least=0, steps=("find", "docfield"),
       where="addressed.py (Reader.halves)"),
    # -- flow: search -------------------------------------------------------
    _r("search_fallback", "flow", "Search", "choice",
       "What a search goes with where no sentence was written for it. Field "
       "sentence: the field's own search sentence, else its question, else "
       "its name. Question: the question of the dimension. Name: its name. "
       "None: no sentence, so the chunks keep the order of the document.",
       choices=("field_sentence", "question", "name", "none"),
       steps=("phrase",), where="addressed.py (fallback)"),
    _r("question_words", "flow", "Search", "texts",
       "The words that make a sentence of the search a question when it "
       "begins with one of them. A sentence that ends in a question mark is "
       "a question as well. A question is counted by the run, and is "
       "replaced by the sentence of the field where the rule that allows "
       "questions says no. Decided on 2026-11-08.",
       empty=True, decided="2026-11-08", steps=("phrase",),
       where="addressed.py (is_question)"),
    _r("rerank_least_pieces", "flow", "Search", "whole",
       "The least number of chunks the reranker orders. Fewer chunks keep "
       "their order. A larger number orders only larger searches.", least=1,
       steps=("order", "search", "docfield", "sentences"),
       where="addressed.py (shown_order, make_order)"),
    _r("search_finds_taken", "flow", "Search", "choice",
       "Which finds of the answer of a search are taken where the dimension "
       "has one value only. First: the first find. All: every find, so that "
       "a search can make several rows.", choices=("first", "all"),
       steps=("search",), where="addressed.py (search_round)"),
    _r("about_other", "flow", "Search", "choice",
       "Which finds of a search are checked as finds from another place. "
       "Passage: a find in a passage other than the value's own. Any: every "
       "find in a chunk the search shows, also in the value's own passage.",
       choices=("passage", "any"), steps=("search",),
       where="addressed.py (search_round)"),
    _r("about_no_reply", "flow", "Search", "choice",
       "What a find from another place is where the check whether it is "
       "about the value gets no answer. Reject: it is not about the value. "
       "Keep: it is kept.", choices=("reject", "keep"),
       steps=("about",),
       where="addressed.py (about)"),
    _r("beside_pieces", "flow", "Search", "whole",
       "How many chunks before and after the chunk of the value the step "
       "that shows the neighbours shows. 1 shows the chunk before and the "
       "chunk after. Decided on 2026-11-09.", least=0,
       decided="2026-11-09", steps=("beside",),
       where="addressed.py (Plan.beside)"),
    _r("reuse_stored_order", "flow", "Search", "switch",
       "Whether the order of the chunks that an earlier run stored is "
       "used again where the fields and the chunks are the same. Off: the "
       "chunks are ordered anew in every run. Decided on 2026-11-02.",
       decided="2026-11-02", steps=("sentences", "order"),
       where="addressed.py (Orders)"),
    _r("pattern_timeout_s", "flow", "Search", "number",
       "How many seconds a pattern the model wrote may search the chunks "
       "of a document before it is given up. A pattern that gives up finds "
       "nothing, so that it cannot hold up the run. A larger number lets a "
       "heavy pattern finish and makes a search over many chunks longer.",
       least=0.01, steps=("search", "compute"),
       where="addressed.py (Reader.matching), lookup.py (matching)"),
    # -- spec: taking an answer ---------------------------------------------
    _r("match_case", "spec", "What a quote must show", "switch",
       "Whether capital and small letters count where the words of a find "
       "are looked for in the line it names. Off: they do not.",
       steps=TAKING, where="addressed.py (resolve)"),
    _r("move_to_cell", "spec", "What a quote must show", "switch",
       "Whether a find whose words stand in one cell of its line only is "
       "read as that cell where the address names another cell. Off: the "
       "address of the model stays.", steps=TAKING,
       where="addressed.py (resolve)"),
    _r("words_need_number", "spec", "Numbers and years", "switch",
       "Whether the words of a find of a number must print a number. Off: "
       "words without a number are read as they stand.",
       steps=("docfield", "find"), where="addressed.py (_finds)"),
    _r("first_number_only", "spec", "Numbers and years", "switch",
       "Whether the words of a find of a number must print exactly one "
       "number. Off: where they print several, the first one counts, as in "
       "\"800 / 750\".", steps=("docfield", "find"),
       where="addressed.py (number_of)"),
    _r("years_in_words", "spec", "Spans of years and groups", "choice",
       "How the words of a find are read where they print several years. "
       "Span ends: a span such as \"2020 bis 2030\" is its first and last "
       "year, any other words their first year. First: always the first "
       "year. Decided on 2026-11-07.",
       choices=("span_ends", "first"), decided="2026-11-07",
       steps=("coord", "search"), where="addressed.py (answers)"),
    _r("after_follow_ups", "spec", "What a quote must show", "choice",
       "What an answer that still does not hold after the follow-up "
       "requests becomes. Unbacked: the dimension is marked as not backed "
       "by its quote. Discard: it stays as it was.",
       choices=("unbacked", "discard"), steps=("coord", "search"),
       where="addressed.py (take)"),
    _r("quote_extend_order", "spec", "What a quote must show", "choice",
       "In which direction a quote that is too short is extended. Before, "
       "then after: with the lines before it first and then, where those "
       "are not enough, the lines after it. After, then before: the other "
       "way round.",
       choices=("before_then_after", "after_then_before"),
       steps=(
           "docfield", "works", "find", "coord", "quantity", "search",
           "last_year", "work_coordinate", "each value"),
       where="units.py (short_quote, Shown.around)"),
    _r("quote_may_span_lines", "spec", "What a quote must show", "switch",
       "Whether a quote may stand over several of the lines a request "
       "showed. Off: a quote must stand in one line. Decided on 2026-11-05.",
       decided="2026-11-05",
       steps=("docfield", "works", "find", "coord", "quantity", "search",
              "last_year", "work_coordinate"),
       where="units.py (Shown.evidence)"),
    # -- flow: lists ---------------------------------------------------------
    _r("two_step_list", "flow", "Lists", "switch",
       "Whether a list longer than the number of entries shown with their "
       "meaning, whose entries belong to groups, is asked in two steps: the "
       "group first, then the entry. Off: such a list is shown by the names "
       "of its entries in one step. Decided on 2026-11-08.",
       decided="2026-11-08", steps=LISTED + ("each field", "each value"),
       where="addressed.py (listing)"),
    _r("group_without_entries", "flow", "Lists", "choice",
       "What happens where the group a find names has no entry in the "
       "list. All entries: the whole list is shown. None: no entry is "
       "chosen. Decided on 2026-11-08.", choices=("all_entries", "none"),
       decided="2026-11-08", steps=LISTED,
       where="addressed.py (Reader._entry)"),
    _r("group_picks_taken", "flow", "Lists", "choice",
       "Which groups of a list asked in two steps count where the answer "
       "names several. First: the first group named. All: every group "
       "named, and the entry is chosen among the entries of all of them. "
       "Decided on 2026-11-08.", choices=("first", "all"),
       decided="2026-11-08", steps=LISTED,
       where="addressed.py (Reader._entry)"),
    _r("same_name_two_entries", "spec", "Lists and wording", "switch",
       "Whether two equal names from two works are two entries of the "
       "document's list, told apart by the work in brackets. Off: equal "
       "names are one entry. Decided on 2026-11-08.", decided="2026-11-08",
       steps=("works", "coord", "search", "names", "work_coordinate"),
       where="addressed.py (Names.add)"),
    _r("names_list_order", "flow", "Lists", "choice",
       "In which order the names of the document's list are shown where "
       "they belong to works. By work: grouped by work. Found: in the "
       "order they were found in.", choices=("by_work", "found"),
       steps=("works", "coord", "search", "names", "work_coordinate"),
       where="addressed.py (Names.shown)"),
    _r("names_meanings", "flow", "Lists", "switch",
       "Whether the request that asks which entry of the document's list a "
       "name means shows what each fixed entry means. Off: it shows their "
       "names only.", steps=("works", "coord", "search", "names"),
       where="addressed.py (name_of)"),
    _r("year_list_quote", "flow", "Lists", "switch",
       "Whether the list of the plan's years shows, for each year, the "
       "line that says it is the plan's base or target year. Off: it shows "
       "the year and its state only.", steps=("coord", "search", "last_year"),
       where="addressed.py (years_listed)"),
    _r("same_find_by", "flow", "Asking again and giving up", "texts",
       "What makes two finds of a request and of its follow-up requests one "
       "find: the same line, the same cell, and the same words (without "
       "regard to capital letters). Take out a part and finds that differ "
       "only in it count as one. Decided on 2026-11-05.",
       choices=("line", "cell", "words"), decided="2026-11-05",
       steps=("docfield", "works", "find"), where="addressed.py (joined)"),
    _r("work_find_covers_piece", "flow", "Lists", "switch",
       "Whether a line of another work in a heading, in a table's title or "
       "head or in a figure's caption counts for the whole chunk it is "
       "shown with. Off: it counts for that line only. Decided on "
       "2026-11-09.", decided="2026-11-09", steps=("works",),
       where="addressed.py (covered)"),
    _r("quantity_words", "prompts", "How a place in the document is shown",
       "texts",
       "The words of the question that asks what a number is, in their "
       "order: its own designation, the heading of its column and its unit. "
       "A part that is left out is not asked with. Decided on 2026-11-08.",
       choices=("what", "head", "unit"), decided="2026-11-08",
       steps=("quantity",), where="addressed.py (quantity)"),
    _r("quantity_joiner", "prompts", "How a place in the document is shown",
       "text",
       "What joins the words of the question that asks what a number is. "
       "Decided on 2026-11-08.", decided="2026-11-08", steps=("quantity",),
       where="addressed.py (quantity)"),
    _r("document_name_fallback", "prompts", "How a place in the document is "
       "shown", "switch",
       "Whether the first line of the title page names the document where "
       "the profile gives no name of it to the request for the search "
       "sentence. Off: the request says nothing of the document. Decided on "
       "2026-11-09.", decided="2026-11-09", steps=("phrase",),
       where="addressed.py (_sentence)"),
)
