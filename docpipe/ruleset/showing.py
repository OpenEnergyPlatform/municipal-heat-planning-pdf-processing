"""
showing.py: What a request shows, cutting a document into chunks, the order of
the flow, conditions (addressed.py, units.py, engine.py, flow.py, blocks.py,
conditions.py, reading.py).
"""
from .kit import ASKING, TAKING, rule

_r = rule

# The steps whose request may ask a list of its own (a wording against an
# entry list, a name against the names, a year against the plan's years).
LISTED = ("docfield", "works", "find", "coord", "quantity",
          "work_coordinate", "search", "last_year", "names", "list")
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
       "which document it is read from.",
       choices=("always", "first", "never"), steps=PLACED,
       where="addressed.py (title_page_shown)",
       title="Show the title page"),
    _r("message_first", "flow", SHOWN, "texts",
       "The fields a request's message shows first, in this order; every "
       "other field follows in the order of the step's inputs. What stays "
       "the same over the requests of a field or of a document stands "
       "first: the list, the field and its question, then the title page "
       "and what the document settles; the value's place and the chunks "
       "come after it. The server computes a beginning that two requests "
       "share only once, so a list of a hundred entries asked for twenty "
       "chunks is read once instead of twenty times. Every request shows "
       "the same fields as before. Empty: every field in the order of the "
       "step's inputs.",
       empty=True, steps=ASKING, decided="2026-11-19",
       where="runner.py (make_asks: first_shown), flowtry.py",
       title="Fields shown first"),
    _r("show_headings", "flow", SHOWN, "switch",
       "Whether a request shows the headings above the place it asks about, "
       "all of them in reading order, the nearest last. Headings tell the "
       "model which section a line belongs to. Off: no heading is shown.",
       steps=("works", "find", "coord", "work_coordinate", "search",
              "last_year", "phrase", "about"),
       where="shows.py (_headings, _value_headings), "
             "addressed.py (show_value)",
       title="Show the headings"),
    _r("show_settled", "flow", SHOWN, "switch",
       "Whether a request shows what the document settles for all its "
       "values, such as its base year or its municipality, beside the "
       "entries of a list and the place of a value. Off: the request shows "
       "none of it.",
       steps=(
           "docfield", "works", "find", "coord", "quantity", "work_coordinate",
           "search", "last_year", "each value"),
       where="shows.py (_settings), addressed.py (show_value, settings_of)",
       title="Show what the document settles"),
    _r("show_known", "flow", SHOWN, "switch",
       "Whether the request for one dimension of a value shows what the "
       "value has already been read as, in the words of the document. This "
       "helps the model to read the dimension that is left. Off: the request "
       "shows nothing of it.",
       steps=("coord", "search"), decided="2026-10-22",
       where="shows.py (_known)",
       title="Show the value's earlier reading"),
    _r("show_example", "flow", SHOWN, "switch",
       "Whether a request shows an example of the reply it asks for. The "
       "example shows the form of the reply with a placeholder wording. Off: "
       "the request shows none, and the model must find the form in the "
       "instruction alone.",
       steps=(
           "docfield", "works", "find", "coord", "quantity", "work_coordinate",
           "search", "last_year", "names", "about", "each value"),
       decided="2026-11-09", where="addressed.py (shown_example)",
       title="Show an example reply"),
    _r("show_empty_example", "flow", SHOWN, "switch",
       "Whether a request that finds values shows, besides the example with "
       "a find, the example of the reply where nothing shown holds a value. "
       "Off: only the example with a find is shown.",
       steps=("docfield", "works", "find", "coord", "quantity",
              "work_coordinate", "search", "last_year", "names", "about"),
       decided="2026-11-09", where="addressed.py (shown_example)",
       title="Show an empty example too"),
    _r("field_text", "flow", SHOWN, "choice",
       "How much of its description a request shows of the field it asks "
       "about. Short: the short description the spec gives, where it has "
       "one. Whole: the full description. A longer text explains the field "
       "better and takes more room.",
       choices=("short", "whole"),
       steps=("docfield", "works", "find", "coord", "work_coordinate",
              "search", "phrase", "sentences"),
       where="addressed.py (field_shown), shows.py (_description)",
       title="How much of a field's description"),
    _r("show_passage_page", "flow", SHOWN, "switch",
       "Whether a request shows the page of each chunk it shows. The page "
       "tells the model where in the document a chunk stands. Off: no page "
       "is shown.", steps=PLACED + ("about",),
       where="addressed.py (block_payload)",
       title="Show the page of each chunk"),
    _r("show_passage_title", "flow", SHOWN, "switch",
       "Whether a request shows the title of each table and figure chunk "
       "it shows. Off: only the lines of the chunk are shown, without a "
       "title of their own.", steps=PLACED + ("about",),
       where="addressed.py (block_payload)",
       title="Show the title of each chunk"),
    _r("rows_around", "flow", SHOWN, "whole",
       "How many rows above and below a value a request shows where the "
       "value stands in a table. 0 shows the row of the value and the "
       "title and head of the table only. A larger number shows the rows "
       "around the value too, so that the model sees its neighbours.",
       least=0,
       steps=("coord", "quantity", "work_coordinate", "search", "last_year",
              "phrase", "about"),
       where="shows.py (around), addressed.py (show_value)",
       title="Rows shown around a value"),
    _r("show_table_title", "flow", SHOWN, "switch",
       "Whether a request shows the title lines of a table with the table's "
       "rows. Off: the model sees the rows without their title.",
       steps=("docfield", "works", "find", "coord", "quantity",
              "work_coordinate", "search", "last_year", "phrase", "about"),
       where="units.py (own_lines, passage_lines)",
       title="Show the table title"),
    _r("show_table_head", "flow", SHOWN, "switch",
       "Whether a request shows the head lines of a table with the table's "
       "rows. Off: the model sees the rows without their column headings, "
       "although the run still knows the head of each column.",
       steps=("docfield", "works", "find", "coord", "quantity",
              "work_coordinate", "search", "last_year", "phrase", "about"),
       where="units.py (own_lines, passage_lines)",
       title="Show the table head"),
    # -- flow: chunks ------------------------------------------------------
    _r("bullet_marks", "flow", "Chunks", "chars",
       "The characters that mark an item of a list. A line is split before "
       "such a character when a space follows it, and a sentence may begin "
       "with one. Empty: no character marks a list item.", empty=True,
       steps=("split",),
       where="units.py (_bullet, _sentence_end)",
       title="Marks of list items"),
    _r("split_bullets", "flow", "Chunks", "switch",
       "Whether a line is split before a list mark, so that each item of a "
       "list is a line of its own. A transcription often runs the items "
       "into one line. Off: such a line stays whole.",
       steps=("split",),
       where="units.py (_bullet)",
       title="Split lines before list marks"),
    _r("split_ordinals", "flow", "Chunks", "switch",
       "Whether a point after a short number, as in \"3. October\", ends a "
       "sentence like any other point. Off: such a point ends no sentence.",
       steps=("split",),
       where="units.py (_ordinal)",
       title="Point after number ends sentence"),
    _r("ordinal_max_digits", "flow", "Chunks", "whole",
       "The most digits a number may have before a point so that the point "
       "ends no sentence, as in \"3. October\" or \"12. Section\". A larger "
       "number keeps more such points within a sentence.", least=1,
       steps=("split",),
       where="units.py (_ordinal)",
       title="Longest number before an ordinal point"),
    _r("abbreviation_lookahead_chars", "flow", "Chunks", "whole",
       "How many characters after a point the run looks at to recognize an "
       "abbreviation of two parts, such as \"z. B.\", whose first part ends "
       "a text. A longer look recognizes longer second parts.", least=0,
       steps=("split",),
       where="units.py (sentences_of)",
       title="Look-ahead for two-part abbreviations"),
    _r("cells_by_bar", "flow", "Chunks", "switch",
       "Whether a line that a vertical bar divides has cells, wherever it "
       "stands: a figure's line, a sentence, a row of a table. The model "
       "then names a cell by its number. Off: only the rows of a table have "
       "cells.", decided="2026-11-09",
       steps=("split",),
       where="units.py (line_cells)",
       title="Cells in bar-divided lines"),
    _r("table_title_lines", "flow", "Chunks", "switch",
       "Whether the lines above the head of a table count as lines of the "
       "table, its title lines, which every chunk of the table shows. Off: "
       "they are not lines of the table at all.",
       steps=("split",),
       where="units.py (table_lines)",
       title="Table title lines count as lines"),
    _r("table_head_lines", "flow", "Chunks", "switch",
       "Whether the head rows of a table count as lines of the table, "
       "which every chunk of the table shows. Off: the table has no head "
       "lines, and no cell has a column heading.",
       steps=("split",),
       where="units.py (table_lines)",
       title="Table head rows count as lines"),
    _r("table_rule_line", "flow", "Chunks", "switch",
       "Whether the rule under the head of a table counts as a line of "
       "its own. Off: it does not, so the first row under the head is the "
       "line after the last head line.", steps=("split",),
       where="units.py (table_lines)",
       title="Rule under head is a line"),
    _r("table_foot_lines", "flow", "Chunks", "switch",
       "Whether the lines under a table, its notes such as \"* ohne "
       "Industrie\" or \"Angaben in MWh/a\", go with every chunk of the "
       "table, all of them, as the title and the head do, and so with "
       "every request about one of its values and with every entry of the "
       "table in the index: what such a line says holds for each number of "
       "the table. Off: a line under a table is shown in its own chunk "
       "only.", decided="2026-11-17", steps=("split",),
       where="units.py (table_lines)",
       title="Table notes go with every chunk"),
    _r("table_parent_rows", "flow", "Chunks", "switch",
       "Whether a row of a table is shown with the rows it stands under "
       "wherever it is shown: in each of its chunks, in every request "
       "about one of its values and in every entry of the table in the "
       "index. A row stands under the row above it whose first cell it is "
       "indented under, by spaces or a mark such as \"└\", so that \"└ "
       "Erdgas\" says under \"Wohngebäude\" whose gas it is; and under the "
       "group row above it, a row that fills its first cell only (\"AT\", "
       "\"2030\"), up to the next group row. Off: a row is shown alone, and "
       "the rows above it only where they stand in the same chunk.",
       decided="2026-11-17", steps=("split",),
       where="units.py (group_row, row_parents, Chunk.shown, "
             "passage_lines)",
       title="Show parent rows with a row"),
    _r("figure_part", "flow", "Chunks", "choice",
       "Which chunks of a figure a field reads. By the kind of field: a "
       "field of numbers reads the chunks of its numbers and any other field "
       "the chunk of its caption. Caption: every field reads the caption. "
       "Numbers: every field reads the chunks of the numbers, each with the "
       "caption.",
       choices=("by_field", "caption", "numbers"), decided="2026-11-09",
       steps=(
           "sentences", "order", "docfield", "find", "beside", "coord",
           "search", "state", "names", "works", "work_coordinate",
           "each field", "each piece"),
       where="addressed.py (Plan.part)",
       title="Figure chunks a field reads"),
    _r("title_page_first", "flow", "Chunks", "whole",
       "The page whose lines are tried first as the title page, all of "
       "them. The page of the rule \"the page whose lines are the title "
       "page when the first page has none\" is tried after it.", least=1,
       decided="2026-11-08", steps=("document",),
       where="units.py (title_page_of)",
       title="Page tried first as title page"),
    _r("title_page_with_figures", "flow", "Chunks", "switch",
       "Whether the lines of a figure may be lines of the title page. Off: "
       "only text and tables are.",
       decided="2026-11-08", steps=("document",),
       where="units.py (title_page_of)",
       title="Figures may form the title page"),
    _r("head_only_full_width", "prompts", "How a place in the document is "
       "shown", "switch",
       "Whether only a head line with as many cells as the rows of the "
       "table gives the heading of a column. Off: every head line does, "
       "also one with fewer cells, such as a heading over several columns.", decided="2026-11-03",
       steps=("docfield", "works", "find", "each value"),
       where="units.py (Passage.head_of)",
       title="Only full-width head lines"),
    # -- flow: giving up on an answer that did not fit ---------------------
    _r("split_cut_off", "flow", "Asking again and giving up", "switch",
       "Whether a request whose answer was cut off at the limit is asked "
       "again in two halves. A cut-off answer is never read. Off: such a "
       "request is a hole at once.",
       decided="2026-09-12", steps=("find", "docfield"),
       where="addressed.py (Reader.halves)",
       title="Halve after a cut-off reply"),
    _r("split_by", "flow", "Asking again and giving up", "choice",
       "How a request is halved. Chunks then lines: first by its chunks, "
       "and a single chunk by its lines. Lines: by the lines of each chunk "
       "only.", choices=("chunks_then_lines", "lines"),
       steps=("find", "docfield"), where="addressed.py (Reader.halves)",
       title="How a request is halved"),
    _r("split_most", "flow", "Asking again and giving up", "whole",
       "How often one request may be halved again and again. 0: until only "
       "a single line is left. A smaller number leaves larger parts as a "
       "hole.", least=0, steps=("find", "docfield"),
       where="addressed.py (Reader.halves)",
       title="Most times a request is halved"),
    # -- flow: search -------------------------------------------------------
    _r("search_fallback", "flow", "Search", "choice",
       "What a search goes with where no sentence was written for it. Field "
       "sentence: the field's own search sentence, else its question, else "
       "its name. Question: the question of the dimension. Name: its name. "
       "None: no sentence, so the chunks keep the order of the document.",
       choices=("field_sentence", "question", "name", "none"),
       steps=("phrase",), where="addressed.py (fallback)",
       title="Search when no sentence was written"),
    _r("question_words", "flow", "Search", "texts",
       "The words that make a sentence of the search a question when it "
       "begins with one of them. A sentence that ends in a question mark is "
       "a question as well. A question is counted by the run, and is "
       "replaced by the sentence of the field where the rule that allows "
       "questions says no.",
       empty=True, decided="2026-11-08", steps=("phrase",),
       where="addressed.py (is_question)",
       title="Words that make a question"),
    _r("rerank_least_pieces", "flow", "Search", "whole",
       "The least number of chunks the reranker orders. Fewer chunks keep "
       "their order. A larger number orders only larger searches.", least=1,
       steps=("order", "search", "docfield", "sentences"),
       where="addressed.py (shown_order, make_order)",
       title="Fewest chunks the reranker orders"),
    _r("search_finds_taken", "flow", "Search", "choice",
       "Which finds of the answer of a search are taken where the dimension "
       "has one value only. First: the first find. All: every find, so that "
       "a search can make several rows.", choices=("first", "all"),
       steps=("search",), where="targets.py (over_hits)",
       title="Finds taken from a search"),
    _r("about_other", "flow", "Search", "choice",
       "Which finds of a search are checked as finds from another place. "
       "Passage: a find in a passage other than the value's own. Any: every "
       "find in a chunk the search shows, also in the value's own passage.",
       choices=("passage", "any"), steps=("search",),
       where="targets.py (over_hits)",
       title="Finds checked as from another place"),
    _r("about_no_reply", "flow", "Search", "choice",
       "What a find from another place is where the check whether it is "
       "about the value gets no answer. Reject: it is not about the value. "
       "Keep: it is kept.", choices=("reject", "keep"),
       steps=("about",),
       where="targets.py (keep_find)",
       title="Unanswered other-place check"),
    _r("beside_pieces", "flow", "Search", "whole",
       "How many chunks before and after the chunk of the value the step "
       "that shows the neighbours shows. 1 shows the chunk before and the "
       "chunk after.", least=0,
       decided="2026-11-09", steps=("beside",),
       where="addressed.py (Plan.beside)",
       title="Neighbour chunks shown"),
    _r("sibling_places", "flow", "Search", "whole",
       "How many chunks the step that shows the neighbours adds where the "
       "same dimension was already read for another value of the same "
       "table or section, such as the paragraph before a table that names "
       "the scenario of its numbers. The chunk most of these values read it "
       "in comes first. Each value is still asked for itself and answers "
       "with an address of its own; nothing is taken over. 0: the "
       "neighbours alone.", least=0,
       decided="2026-11-17", steps=("beside",),
       where="engine.py (Engine.read_near), addressed.py (Plan.read_near)",
       title="Chunks added from sibling values"),
    _r("item_labels", "flow", "Search", "texts",
       "The words that label a table or a figure in its title line and in "
       "the text, such as \"Tabelle 7\" or \"Abb. 3\". The label and the "
       "number of a title line are found with them. A text names the item "
       "where it prints the same number as a word (\"Tabelle 4\" is not "
       "\"Tabelle 41\") after the title's label or an abbreviation of it "
       "or the label the title abbreviates (one label without its final "
       "period is the beginning of the other: Tab., Tab and Tabelle name "
       "each other). Tables and figures are numbered each by themselves, "
       "so \"Abbildung 4\" does not name \"Tabelle 4\".",
       decided="2026-11-17", steps=("beside",),
       where="addressed.py (Plan.mentioning)",
       title="Labels of tables and figures"),
    _r("mentioning_pieces", "flow", "Search", "whole",
       "How many text pieces that name the table or figure of the value by "
       "its label and number (\"Tabelle 7 zeigt das Szenario ...\") the "
       "step that shows the neighbours adds after the pieces where the "
       "same dimension was read for the table's other values. Standard 2. "
       "0: none.", least=0,
       decided="2026-11-17", steps=("beside",),
       where="engine.py (Engine.mention_pieces), addressed.py "
             "(Plan.mentioning)",
       title="Text chunks that name the table"),
    _r("reuse_stored_order", "flow", "Search", "switch",
       "Whether the order of the chunks that an earlier run stored is "
       "used again where the fields and the chunks are the same. Off: the "
       "chunks are ordered anew in every run.",
       decided="2026-11-02", steps=("sentences", "order"),
       where="addressed.py (Orders)",
       title="Reuse the stored chunk order"),
    _r("pattern_timeout_s", "flow", "Search", "number",
       "How many seconds a pattern the model wrote may search the chunks "
       "of a document before it is given up. A pattern that gives up finds "
       "nothing, so that it cannot hold up the run. A larger number lets a "
       "heavy pattern finish and makes a search over many chunks longer.",
       least=0.01, steps=("search", "compute"),
       where="addressed.py (Reader.matching), lookup.py (matching)",
       title="Time limit of a search pattern"),
    # -- spec: taking an answer ---------------------------------------------
    _r("match_case", "spec", "What a quote must show", "switch",
       "Whether capital and small letters count where the words of a find "
       "are looked for in the line it names. Off: they do not.",
       steps=TAKING, where="addressed.py (resolve)",
       title="Match capital letters"),
    _r("move_to_cell", "spec", "What a quote must show", "switch",
       "Whether a find whose words stand in one cell of its line only is "
       "read as that cell where the address names another cell. Off: the "
       "address of the model stays.", steps=TAKING,
       where="addressed.py (resolve)",
       title="Read a find as one cell"),
    _r("words_need_number", "spec", "Numbers and years", "switch",
       "Whether the words of a find of a number must print a number. Off: "
       "words without a number are read as they stand.",
       steps=("docfield", "find"), where="addressed.py (_finds)",
       title="Wording must print a number"),
    _r("first_number_only", "spec", "Numbers and years", "switch",
       "Whether the words of a find of a number must print exactly one "
       "number. Off: where they print several, the first one counts, as in "
       "\"800 / 750\".", steps=("docfield", "find"),
       where="addressed.py (number_of)",
       title="Wording must print exactly one number"),
    _r("years_in_words", "spec", "Spans of years and groups", "choice",
       "How the words of a find are read where they print several years. "
       "Span ends: a span such as \"2020 bis 2030\" is its first and last "
       "year, any other words their first year. First: always the first "
       "year.",
       choices=("span_ends", "first"), decided="2026-11-07",
       steps=("coord", "search"), where="addressed.py (answers)",
       title="Reading several years in a wording"),
    _r("after_follow_ups", "spec", "What a quote must show", "choice",
       "What an answer that still does not hold after the follow-up "
       "requests becomes. Unbacked: the dimension is marked as not backed "
       "by its quote. Discard: it stays as it was.",
       choices=("unbacked", "discard"), steps=("coord", "search"),
       where="addressed.py (take)",
       title="Answer failing after follow-ups"),
    _r("quote_extend_order", "spec", "What a quote must show", "choice",
       "In which direction a quote that is too short is extended. Before, "
       "then after: with the lines before it first and then, where those "
       "are not enough, the lines after it. After, then before: the other "
       "way round.",
       choices=("before_then_after", "after_then_before"),
       steps=(
           "docfield", "works", "find", "coord", "quantity", "search",
           "last_year", "work_coordinate", "each value"),
       where="units.py (short_quote, Shown.around)",
       title="Direction a short quote is extended"),
    _r("quote_may_span_lines", "spec", "What a quote must show", "switch",
       "Whether a quote may stand over several of the lines a request "
       "showed. Off: a quote must stand in one line.",
       decided="2026-11-05",
       steps=("docfield", "works", "find", "coord", "quantity", "search",
              "last_year", "work_coordinate"),
       where="units.py (Shown.evidence)",
       title="A quote may span lines"),
    # -- flow: lists ---------------------------------------------------------
    _r("group_without_entries", "flow", "Lists", "choice",
       "What happens where the group a find names has no entry in the "
       "list. All entries: the whole list is shown, every entry with what "
       "it means. None: no entry is chosen.",
       choices=("all_entries", "none"),
       decided="2026-11-08", steps=LISTED,
       where="addressed.py (Reader._entry)",
       title="Group without entries"),
    _r("same_name_two_entries", "spec", "Lists and wording", "switch",
       "Whether two equal names from two works are two entries of the "
       "document's list, told apart by the work in brackets. Off: equal "
       "names are one entry.", decided="2026-11-08",
       steps=("works", "coord", "search", "names", "work_coordinate"),
       where="addressed.py (Names.add)",
       title="Equal names from two works"),
    _r("names_list_order", "flow", "Lists", "choice",
       "In which order the names of the document's list are shown where "
       "they belong to works. By work: grouped by work. Found: in the "
       "order they were found in.", choices=("by_work", "found"),
       steps=("works", "coord", "search", "names", "work_coordinate"),
       where="addressed.py (Names.shown)",
       title="Order of the names list"),
    _r("names_meanings", "flow", "Lists", "switch",
       "Whether the request that asks which entry of the document's list a "
       "name means shows what each fixed entry means. Off: it shows their "
       "names only.", steps=("works", "coord", "search", "names"),
       where="addressed.py (name_of)",
       title="Show what entries mean"),
    _r("year_list_quote", "flow", "Lists", "switch",
       "Whether the list of the document's years shows, for each year, the "
       "line that says it is the document's base or target year. Off: it "
       "shows the year and its state only.", steps=("coord", "search", "last_year"),
       where="addressed.py (years_listed)",
       title="Show the line of a document's year"),
    _r("same_find_by", "flow", "Asking again and giving up", "texts",
       "What makes two finds of a request and of its follow-up requests one "
       "find: the same line, the same cell, and the same words (without "
       "regard to capital letters). Take out a part and finds that differ "
       "only in it count as one.",
       choices=("line", "cell", "words"), decided="2026-11-05",
       steps=("docfield", "works", "find"), where="addressed.py (joined)",
       title="What makes two finds one"),
    _r("work_find_covers_piece", "flow", "Lists", "switch",
       "Whether a line of another work in a heading, in a table's title or "
       "head or in a figure's caption counts for the whole chunk it is "
       "shown with. Off: it counts for that line only.", decided="2026-11-09", steps=("works",),
       where="addressed.py (covered)",
       title="Work in heading covers chunk"),
    _r("quantity_words", "prompts", "How a place in the document is shown",
       "texts",
       "The words of the question that asks what a number is, in their "
       "order: its own designation, the heading of its column and its unit. "
       "A part that is left out is not asked with.",
       choices=("what", "head", "unit"), decided="2026-11-08",
       steps=("quantity",), where="addressed.py (quantity)",
       title="Words asking what a number is"),
    _r("quantity_joiner", "prompts", "How a place in the document is shown",
       "text",
       "What joins the words of the question that asks what a number is.", decided="2026-11-08", steps=("quantity",),
       where="addressed.py (quantity)",
       title="Joiner of those words"),
    _r("document_name_fallback", "prompts", "How a place in the document is "
       "shown", "switch",
       "Whether the first line of the title page names the document where "
       "the profile gives no name of it to the request for the search "
       "sentence. Off: the request says nothing of the document.", decided="2026-11-09", steps=("phrase",),
       where="shows.py (_about_document)",
       title="First title line as document name"),
)
