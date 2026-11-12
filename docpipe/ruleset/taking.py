"""
taking.py: Taking an answer, checking it, folding, states and trust
(pipeline.py, fields.py, verify.py, trust.py, schema.py, spec.py, lookup.py).

Owner, 2026-11-11: "alles soll anpassbar sein". Each rule below stood in the
code as a constant, a fixed branch or a fixed order. Where a rule is one of
the owner's own decisions, its standard is his decision (`decided`); a
second way the code does not have yet is not allowed yet (`choices` holds
today's way only).

Author: Felix Vossel
"""
from .kit import TAKING, TRUSTING, WRITING, rule

# The steps that hold an answer to its quote, and the calculation, which
# holds its number to its quote and its inputs.
CHECKED = TAKING + ("compute",)
# The steps that ask which entry of a list a wording means.
LISTED = ("docfield", "find", "coord", "quantity", "work_coordinate",
          "search", "names", "each value", "list")

STATES = ("read", "unstated", "unbacked", "exhausted", "unanswered",
          "derived", "out_of_slice")

RULES = (
    # -- spec: what a quote must show -----------------------------------------
    rule("sign_belongs", "spec", "What a quote must show", "choice",
         "On: a printed sign belongs to the number, so the quote "
         "\"-1.155\" backs -1155, and \"1.155\" does not. Off: the sign "
         "stays outside the number, so a quote backs a number of either "
         "sign, and \"1.155\" backs -1155 as well as 1155. Decided on "
         "2026-11-01.", choices=("on", "off"),
         decided="2026-11-01", steps=CHECKED,
         where="verify.py (numbers_in, _times_number)"),
    rule("refused_keeps_quote", "spec", "What a quote must show", "choice",
         "Dropped: a value that does not survive its checks loses its "
         "quote and its source, and its state changes from read to not "
         "backed. Kept: it keeps the quote it was answered with, and the "
         "source that quote stands in where one was found, and its state "
         "still says it is not backed. Decided on 2026-09-12.",
         choices=("dropped", "kept"), decided="2026-09-12", steps=CHECKED,
         where="verify.py (verify_tuple)"),
    # -- spec: numbers and years ----------------------------------------------
    rule("thousands_spaces", "spec", "Numbers and years", "chars",
         "The spaces that group the thousands of a number, as in "
         "\"1 234 567\": the narrow no-break space, the no-break space and "
         "the plain space. A number written with one of them is read as "
         "one number. Remove a character and a number grouped with it is "
         "read as several. Empty: no space groups digits.", empty=True,
         steps=CHECKED, where="verify.py (canonical_number, numbers_in)"),
    rule("year_as_digit_run", "spec", "Numbers and years", "switch",
         "On: a year must stand in its quote as a run of digits of its "
         "own, so that \"2.022 MWh\" does not back the year 2022, while a "
         "date such as \"31.12.2022\" does. Off: a whole number is "
         "compared like every other number, with its thousands grouping "
         "read as a grouping. Decided on 2026-09-23.",
         decided="2026-09-23", steps=CHECKED, where="pipeline.py "
         "(answer_in_quote)"),
    rule("number_axis_whole_only", "spec", "Numbers and years", "switch",
         "On: a number that answers a coordinate such as a year must be a "
         "whole number inside the range of years, and an answer such as "
         "\"2030-2045\" or 2045.5 is refused and asked again. Off: a "
         "number with decimals is accepted as it is; the range of years "
         "and the rule that the answer is a number still hold.",
         steps=TAKING, where="pipeline.py (_wrong_type)"),
    rule("keep_unlisted_unit", "spec", "Numbers and years", "choice",
         "A number whose unit is no entry of the field's list is not "
         "refused: it stays read with the unit as the plan prints it and "
         "without a converted value, and it is flagged. This is the only "
         "way that exists for now. Decided on 2026-11-07.",
         choices=("kept",), decided="2026-11-07", steps=TAKING,
         where="verify.py (_check_value), pipeline.py (printed_only)"),
    rule("flag_missing_period", "spec", "Numbers and years", "switch",
         "On: a number of a field that is an amount over a time span, "
         "whose unit names no time span, is flagged as having no period. "
         "The value is read either way. Off: no flag is set.",
         steps=CHECKED, where="verify.py (verify_tuple)"),
    rule("plan_year_states", "spec", "Numbers and years", "texts",
         "The states of a plan that a word such as \"Basisjahr\" or "
         "\"Zieljahr\" may mean, in the order their years are shown to the "
         "model and matched: base is the plan's own state and target is "
         "its target scenario. A year that both states carry stands under "
         "each and is cited from the first. Remove a state and its years "
         "are not offered. Decided on 2026-09-22 and 2026-10-06.",
         choices=("base", "target"), empty=True,
         decided="2026-09-22, 2026-10-06", steps=TAKING,
         where="pipeline.py (named_years)"),
    # -- spec: lists and wording ----------------------------------------------
    rule("outside_list", "spec", "Lists and wording", "choice",
         "What an answer to a closed list does that is none of its "
         "entries. Ask again: it is refused with the reason, asked again "
         "and never read, which is the standard. Keep: it is kept with its "
         "own wording where its quote is shown and holds that wording, its "
         "entry stays empty, and the wording is noted for the vocabulary "
         "review; the graph writes a node for it only where a rule of the "
         "graph knows the kind, such as regions. Decided on 2026-09-11.",
         choices=("ask_again", "keep"), decided="2026-09-11",
         steps=TAKING, where="pipeline.py (merge_field), addressed.py "
         "(_finds)"),
    rule("answer_in_quote_spellings", "spec", "Lists and wording", "switch",
         "On: where an answer gives no wording, a choice is looked for in "
         "its quote under its name and under every spelling the spec "
         "lists for it. Off: only its name is looked for. Decided on "
         "2026-09-13.", decided="2026-09-13", steps=CHECKED,
         where="pipeline.py (answer_in_quote)"),
    rule("longest_entry_wins", "spec", "Lists and wording", "switch",
         "On: an entry of a list is backed only where no longer entry of "
         "the same list stands at the same place, so that \"MWh\" in "
         "\"MWh/a\" backs the second one only. Off: a shorter entry is "
         "backed wherever its letters stand. Decided on 2026-09-23.",
         decided="2026-09-23", steps=CHECKED,
         where="pipeline.py (stands_in)"),
    rule("mark_foreign_wording", "spec", "Lists and wording", "switch",
         "On: a wording that does not name the chosen entry in whole words "
         "is counted and the row is marked with it; the value stays read. "
         "Off: wordings are not compared with the chosen entry, and no row "
         "is marked. Decided on 2026-09-13.", decided="2026-09-13",
         steps=TAKING, where="pipeline.py (merge_field)"),
    rule("entry_once_per_wording", "spec", "Lists and wording", "switch",
         "On: the entry of a list that a wording means is asked once for "
         "each document, field, dimension and wording, and every place the "
         "wording stands in takes that answer. Off: it is asked again for "
         "every place the wording stands in, so two places of one wording "
         "may get two entries and each is a request. Decided on "
         "2026-11-08 and 2026-11-09.", decided="2026-11-08, 2026-11-09",
         steps=LISTED, where="addressed.py (entry)"),
    rule("list_shows_earlier", "spec", "Lists and wording", "switch",
         "Off: the question that asks an entry of a list shows the list "
         "and the words, and never the wordings it settled before. On: it "
         "also shows the wordings of this document already settled for the "
         "same list, each with its entry, so the model answers alike for "
         "alike wordings; an earlier answer may then steer later ones. "
         "Decided on 2026-11-09.", decided="2026-11-09", steps=LISTED,
         where="addressed.py (_entry)"),
    rule("name_may_be_none", "spec", "Lists and wording", "switch",
         "On: the question that asks which entry of the document's list a "
         "name means may answer 0, none, and the name then has no entry. "
         "Off: 0 counts as an answer outside the list, so the question is "
         "asked again with its reason. Decided on 2026-11-09.",
         decided="2026-11-09", steps=LISTED + ("works",),
         where="addressed.py (_name_picks)"),
    rule("work_without_line", "spec", "Lists and wording", "switch",
         "Off: a value takes the work of the line it stands in only where "
         "a line names that work, and otherwise asks for its work. On: a "
         "value also takes the one work its piece names, or this "
         "publication where the piece names none, with the value's own "
         "line as its quote; a piece that names two works leaves the value "
         "to ask. Decided on 2026-11-09.", decided="2026-11-09",
         steps=("work_coordinate",), where="addressed.py (inherit_work)"),
    # -- spec: defaults where the spec says nothing ---------------------------
    rule("derive_from_unit", "spec", "Defaults where the spec says nothing",
         "choice",
         "How a coordinate that the spec derives from the unit is read. "
         "Ask first, then derive: the coordinate is asked, and only where "
         "no answer is read does the unit set it, with the state derived. "
         "Ask only: the unit never sets it, and an unanswered coordinate "
         "stays open. Decided on 2026-11-07.",
         choices=("ask_first_then_derive", "ask_only"),
         decided="2026-11-07", steps=TAKING + ("state",),
         where="fields.py (derives)"),
    rule("parameter_from_unit", "spec", "Defaults where the spec says "
                                         "nothing", "switch",
         "On: where exactly one field accepts the unit of a number, the "
         "unit alone decides which field the number is, and the "
         "coordinate is not asked; a wording belongs to the one text "
         "field. Off: the field of every number is asked. Decided on "
         "2026-11-05.", decided="2026-11-05",
         steps=TAKING + ("state", "classify", "derive"),
         where="fields.py (derive_parameter, parameter_undecidable)"),
    # -- flow: reading from the quote -----------------------------------------
    rule("unstated_needs_no_quote", "flow", "Reading from the quote",
         "switch",
         "On: the answer \"not stated\" needs no quote, because no "
         "sentence says that a thing is not in the document; the "
         "coordinate ends as not stated, and a wording the model "
         "noticed is kept beside it. Off: \"not stated\" must cite a "
         "shown line like any other answer, and without one it is not "
         "backed. Decided on 2026-11-06.", decided="2026-11-06",
         steps=TAKING, where="pipeline.py (merge_field)"),
    rule("reading_wins", "flow", "Reading from the quote", "choice",
         "Which answer a coordinate keeps when a later request answers it "
         "again after it was read and backed. First: the first backed "
         "answer stays. Later backed: a later answer that is backed "
         "takes its place, and one that is not backed changes nothing. "
         "Keeping both is not available.",
         choices=("first", "later_backed"), steps=TAKING,
         where="pipeline.py (merge_field)"),
    rule("check_accepts", "flow", "Reading from the quote", "choice",
         "What an own check of the flow may do. It adds refusals to the "
         "fixed checks and never accepts what they refuse. Accepting "
         "what the fixed checks refuse is not available.",
         choices=("only_refuses",), steps=TAKING, where="engine.py "
         "(own_checks)"),
    # -- flow: reading from images --------------------------------------------
    rule("read_off_figures", "flow", "Reading from images", "switch",
         "On: a number that a figure only draws, as a bar or a point of a "
         "curve, may be read off the image where no text states it, and "
         "the sentence of what was read is its evidence; the value is an "
         "estimate. Off: such a number needs its quote like any other. "
         "Decided on 2026-11-05 and 2026-11-07.",
         decided="2026-11-05, 2026-11-07", steps=TAKING,
         where="verify.py (read_off)"),
    # -- flow: calculation ----------------------------------------------------
    rule("computed_from_inputs", "flow", "Calculation", "choice",
         "On: a calculated number counts only where it follows from the "
         "numbers it names, a share times its whole or the sum of its "
         "parts, to the rounding of its printed places. Off: it counts "
         "when the code printed it and its quote shows its inputs, "
         "whether or not the inputs make it. Decided on 2026-11-03.",
         choices=("on", "off"), decided="2026-11-03", steps=CHECKED,
         where="verify.py (computed_from_inputs)"),
    rule("computed_rounding_half_units", "flow", "Calculation", "number",
         "How far a calculated number may lie from what its inputs make, "
         "as a share of the unit of its last printed place: 0.5 is half "
         "of that unit, so 116.1 stands for anything from 116.05 to "
         "116.15. A larger share accepts more. 0 accepts only equal "
         "numbers, apart from the floating point noise.", least=0,
         decided="2026-11-03", steps=CHECKED,
         where="verify.py (printed_rounding)"),
    rule("computed_float_noise", "flow", "Calculation", "number",
         "The share of the larger number that two calculated numbers may "
         "differ by because a computer adds the same parts in another "
         "order. It is added to the rounding of the printed places.",
         least=0, decided="2026-11-03", steps=CHECKED,
         where="verify.py (computed_from_inputs)"),
    rule("compute_fetch_pages", "flow", "Calculation", "number",
         "How many pages of text a calculation shows of a passage it asked "
         "to see. A longer passage is cut to this many pages, measured by "
         "the plan's mean page. A figure's description is never cut.",
         least=0.1, steps=("compute",),
         where="lookup.py (two_pages), runner.py (make_computer)"),
    rule("compute_used_if_none", "flow", "Calculation", "choice",
         "Which numbers a calculated row names as its inputs when the "
         "model names none. All: every number the question showed. None: "
         "no number, and the row has no inputs to stand on. Decided on "
         "2026-11-03.", choices=("all", "none"), decided="2026-11-03",
         steps=("compute",), where="compute.py (used_numbers)"),
    # -- flow: search ---------------------------------------------------------
    rule("pattern_hit_chars", "flow", "Search", "whole",
         "How many characters of text stand on each side of the hit of a "
         "pattern search in the answer the model gets back. A larger "
         "number shows more around each hit and fits fewer hits in the "
         "answer.", least=0, steps=("search", "compute"),
         where="lookup.py (matching)"),
    rule("fetch_next", "flow", "Search", "whole",
         "How many sections an ask for the next or the previous section "
         "brings in one go. A larger number shows more text of the plan "
         "per ask.", least=1, steps=("search", "compute"),
         where="lookup.py (fetch_run)"),
    # -- flow: chunks ---------------------------------------------------------
    rule("table_continues_pages", "flow", "Chunks", "whole",
         "How many pages back a table that has lost its head may look for "
         "the table it continues. A table that stands on the same page "
         "or up to this many pages after a table with a head is marked as "
         "its continuation, and inherits its title, head and unit. 0: "
         "only a table on the same page. Decided on 2026-11-06 and "
         "2026-11-07.", least=0, decided="2026-11-06, 2026-11-07",
         steps=("split", "document"), where="lookup.py (continued)"),
    # -- flow: documents ------------------------------------------------------
    rule("trace_quote_chars", "flow", "Documents", "whole",
         "The most characters of the quote of a refused answer that the "
         "log's schema allows. A longer quote is not valid for the schema.",
         least=1, steps=WRITING, where="schema.py (build)"),
    rule("found_stale_fallback", "flow", "Documents", "choice",
         "What a run that starts at the places an earlier harvest found "
         "does when the document no longer holds one of them. Plan in "
         "full: the document is planned from scratch as a whole. Stop: "
         "the document fails with the reason. A harvest without a stamp "
         "is never read. Decided on 2026-11-02.",
         choices=("plan_in_full", "stop"), decided="2026-11-02",
         where="found.py (_read)"),
    rule("stale_keys", "flow", "Documents", "texts",
         "Which questions of the spec decide that a stored harvest is out "
         "of date: a field, a coordinate, the list of a field, the question "
         "for the field of a number and the question for its unit. The "
         "hash of the whole spec file decides only where a harvest has "
         "none of these keys. A kind you remove no longer makes a "
         "document stale.",
         choices=("parameter", "axis", "value", "parameter_slot",
                  "unit_slot"), empty=True,
         steps=("classify", "write"), where="spec.py (fingerprints)"),
    rule("route_claims_by", "flow", "Documents", "choice",
         "How a combined answer for several passages is sorted into its "
         "passages. Quote first: the passage that holds the quote gets "
         "the claim, and the label the model named decides only where "
         "several do. Label first: the passage the model named gets the "
         "claim whenever the name is real. Decided on 2026-11-05.",
         choices=("quote_first", "label_first"), decided="2026-11-05",
         where="pipeline.py (route_claims)"),
    # -- flow: states ---------------------------------------------------------
    rule("state_rules", "flow", "States", "map",
         "The state a coordinate or a field ends in, for each case: "
         "skipped is a coordinate no reply mentioned; "
         "answered_not_stated is the answer \"not stated\"; refused is an "
         "answer that failed its checks; parameter_refused is a field "
         "with no value of which an answer was refused; parameter_cut is "
         "a field with no value whose request was cut; parameter_silent "
         "is a field with no value and nothing refused; out_of_slice is a "
         "dimension that is never asked because the answer to another "
         "dimension left its row out of this run; unstated_after_combing "
         "is a dimension whose search found nothing and left no chunk "
         "unread; exhausted is a dimension whose search ended with chunks "
         "left unread. The states are read, unstated, unbacked, exhausted, "
         "unanswered, derived and "
         "out_of_slice.", of="text", steps=TAKING + ("each value", "state"),
         where="pipeline.py, trust.py (parameter_states), verify.py, "
               "engine.py (box_state)"),
    # -- flow: writing --------------------------------------------------------
    rule("drop_repeats", "flow", "Writing", "switch",
         "On: a row that is the same as another row of its document, "
         "except for the parts named in the rule for repeats, is written "
         "once, and the first one is kept. Off: every row is written, "
         "also a repeated one.", steps=WRITING,
         where="pipeline.py (drop_repeats)"),
    rule("repeat_key", "flow", "Writing", "texts",
         "The parts of a row that are left out when two rows are compared "
         "to find a repeat. Everything else of the row must be equal. The "
         "place a row was read from is left out, because it says how the "
         "row was found and not what it says.", empty=True,
         steps=WRITING, where="pipeline.py (repeat_key)"),
    rule("write_checks_schema", "flow", "Writing", "switch",
         "On: every row a document writes is held against the published "
         "schema, and a row the schema refuses is counted and logged; it "
         "is written all the same. Off: the check is not made.",
         steps=WRITING, where="runner.py (check_against_schema)"),
    # -- graph: trust ---------------------------------------------------------
    rule("trust_reason_levels", "graph", "Trust", "map",
         "The reasons a value is not trusted fully, each with the level "
         "it gives the value, from A, the best, to D. A reason that is "
         "not listed is not counted. The worst level of its reasons is "
         "the level of a value; a value without reasons is at the level "
         "of its origin. Not backed, computed, not located, from a "
         "catalogue, a second reading that disagrees and a conflict are "
         "D, a coordinate nobody read and a number read off an image are "
         "C. The same table is read when the harvest is written and when "
         "the graph is. Decided on 2026-11-02, 2026-11-04 and 2026-11-07.",
         of="text", decided="2026-11-02, 2026-11-04, 2026-11-07",
         steps=TRUSTING, where="trust.py (trust, reasons)"),
    rule("trust_image_cap", "graph", "Trust", "choice",
         "The best level a value can have that comes out of a table or "
         "figure transcribed by a model, or out of a document whose pages "
         "had no text and were transcribed. A is no limit.",
         choices=("A", "B", "C", "D"), steps=TRUSTING,
         where="trust.py (trust)"),
    rule("review_levels", "graph", "Trust", "texts",
         "The trust levels whose values are looked at again: such a value "
         "gets the line \"review\" in the graph's comment, and the second "
         "reading asks it again with a narrower window. By default the two "
         "lowest; a value whose dimensions were all read and whose quote "
         "needed no repair has nothing for a narrower window to find.",
         choices=("A", "B", "C", "D"), empty=True,
         steps=("write", "review"),
         where="trust.py (marks), review.py (rows_to_review)"),
    rule("evidence_tiers", "graph", "Trust", "map",
         "How well a place of the document backs a value, by the kind of "
         "the place. Text located: the document's own prose, which the "
         "value can be shown highlighted in. Visual source: a table, a "
         "caption or a figure's description, which a model read from a "
         "picture. A kind that is not listed counts as a visual source.",
         of="text", steps=CHECKED, where="verify.py (verify_tuple)"),
)
