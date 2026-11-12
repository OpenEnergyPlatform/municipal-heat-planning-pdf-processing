"""
rules.py: The rules a run follows, read from a file of the profile.

Every rule of the reading that is a value stood in the code until
2026-11-10: a number ("a quote has at least 8 characters"), a switch, a
choice ("the documents write the decimal with a comma"), a list of words or
characters ("the abbreviations whose point ends no sentence"), a table. Since
then each stands in a file of the profile, beside its spec, its prompts and
its flow, so that `docpipe edit` shows and sets it in the tab it belongs to
(owner, 2026-11-10: "Alle Regeln etc. sollen auch immer über die GUI
Editierbar sein"):

    <profile folder>/rules.json

The code knows of each rule its name, its kind, its bounds and what it does
with it (`RULES`); its value stands in the file and nowhere in the code. The
default profile's file names every rule of the core. A profile that extends
it writes only the rules it sets differently, laid over the default's rule by
rule, as the numbers of its flow are (`flow.py`). A profile whose own code
follows rules the core does not know declares them (`profiles/<name>/
rules.py: RULES`), and its file is the one they start from. A rule that has
a setting (`Rule.env`) is set by it where it is set: the environment, then
the project file, then the file.

A run reads with the rules of its profile (`use`; `current` takes the
ambient profile's where no run said which). A step of the flow and the
frames around it may set a rule for themselves (`"rules"` of a box or frame
in `flow.json`, owner 2026-11-11: "alles soll anpassbar sein"): while the
step runs, its values lie over the run's (`STEP`, set by
`engine.Engine.step`), the innermost frame's over the outer ones', so a
value is read in this order: the step, its frames from the inside out, the
setting of the start, the file. `get` is the one way a rule is read.
Nothing here decides whether a harvest is current: a pass names the sha256
of its rules in its entry of the stamp for a reader, as it names its
prompts and its flow (owner decision 2026-09-10: a stamp rests on the
questions of the spec alone).

Author: Felix Vossel
"""
from __future__ import annotations

import contextvars
import difflib
import hashlib
import json
import os
import threading
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

FILE = "rules.json"
DEFAULT_NAME = "default"
DEFAULT = Path(__file__).resolve().parent / "builtin" / DEFAULT_NAME / FILE

# What a rule is, its tabs and kinds and the kinds of steps that read
# rules stand in ruleset/kit.py, which the ruleset's modules import
# while this module gathers their rules (below).
from .ruleset.kit import (ASKING, KINDS, SHOWING, TABS,  # noqa: F401
                          TAKING, WRITING, Rule, rule, with_general,
                          SEARCH_GROUP)


class RuleError(ValueError):
    """A rules file or a value a run cannot read. It names the file or the
    rule."""


_r = rule

# Every rule of the core, in the order a file writes them and a tab shows
# them. What each is stands in the default profile's file.
RULES = (
    # -- spec: what a quote must show -----------------------------------------
    _r("quote_min_chars", "spec", "What a quote must show", "whole",
       "A quote must have at least this many characters, so that it names "
       "one place in the document and not a phrase that occurs everywhere. A "
       "quote that is too short is extended with the lines around it; if it "
       "is still too short, the answer is refused. A larger number makes "
       "quotes more precise and refuses more answers.", least=1,
       where="verify.py, units.py (short_quote)"),
    _r("word_joiners", "spec", "What a quote must show", "chars",
       "These characters join a name to a longer one. A wording that stands "
       "next to a letter or digit, or next to one of these characters and "
       "then a letter or digit, is only part of a longer name and does not "
       "count as stated, so \"OECD\" is not found in \"non-OECD\". Every "
       "character you add makes this check stricter. Empty: only a letter or "
       "digit directly beside the wording makes it part of a longer name.",
       empty=True,
       where="verify.py (_alone)"),
    _r("minus_signs", "spec", "What a quote must show", "chars",
       "These characters count as the minus sign of a number, because a PDF "
       "prints one sign and a model retypes another. A printed sign belongs "
       "to the number: the quote \"-1.155\" backs -1155, but \"1.155\" does "
       "not. A dash after a letter, a digit or a separator joins two things, "
       "as in \"2020-2030\", and is no sign. A character you remove is no "
       "longer read as a minus sign. Decided on 2026-11-01.",
       decided="2026-11-01",
       where="verify.py (numbers_in, canonical_number)"),
    _r("dotted_date_year", "spec", "What a quote must show", "switch",
       "On: the year at the end of a date written with dots, such as \"Stand "
       "09.12.2025\", counts as a number the quote prints, so that quote "
       "backs the year 2025. Off: only a year that stands as a number of its "
       "own counts, and a year that only a dotted date prints is not found "
       "in its quote.",
       where="verify.py (numbers_in)"),
    _r("same_characters", "spec", "What a quote must show", "map",
       "Characters that count as the same when a quote is compared with its "
       "source. Before the check, each key is replaced by its value on both "
       "sides, for example curly quotation marks by the straight one, dashes "
       "by a hyphen and the soft hyphen by nothing. Only keys of one "
       "character are used, and this is no check of its own. Add a pair when "
       "a PDF prints a character that the model retypes differently. Empty: "
       "no characters are treated as the same.",
       empty=True,
       where="verify.py (flat)"),
    # -- spec: numbers and years ----------------------------------------------
    _r("decimal_mark", "spec", "Numbers and years", "choice",
       "How the documents write the decimal mark. It matters only where the "
       "digits leave it open: \"3,251\" is 3.251 with a decimal comma and "
       "3251 with a decimal point. Comma: a point groups thousands, as in "
       "German plans. Point: a comma groups thousands, as in English texts.",
       choices=(",", "."),
       where="verify.py (decimal_mark)"),
    _r("year_range", "spec", "Numbers and years", "range",
       "The range a year of a value can lie in, from the first to the last "
       "year. A number outside it is refused as a year, such as a zone "
       "number like 169002, and the model is asked again. Empty: any number "
       "can be a year.",
       empty=True,
       decided="2026-11-01", where="pipeline.py (year rules)"),
    _r("year_words", "spec", "Numbers and years", "range",
       "The range of years looked for when the words of a find name a year "
       "or a span, such as \"bis 2045\". Only a number of four digits inside "
       "this range counts as a year. A wider range finds more years and also "
       "more numbers that are none.", decided="2026-11-07",
       where="addressed.py (years_in)"),
    _r("unit_factor_places", "spec", "Numbers and years", "whole",
       "The number of decimal places a value keeps after it is converted "
       "into the unit of its field. A larger number keeps the converted "
       "value more exact. 0 rounds it to a whole number.",
       least=0, where="verify.py (_check_value)"),
    _r("year_by_plan_word", "spec", "Numbers and years", "switch",
       "On: a year that the quote does not print is still read when it is "
       "one of the document's base or target years and the quote has the "
       "document's word for it, such as \"Basisjahr\" or \"Zieljahr\". The "
       "model chooses among those years. Off: a year counts only when its "
       "quote prints it as a number.",
       decided="2026-09-22, 2026-10-06", where="pipeline.py (named_year)"),
    # -- spec: lists and wording ----------------------------------------------
    _r("wording_most_chars", "spec", "Lists and wording", "whole",
       "The most characters a wording may have to count as naming the list "
       "entry that was chosen. A longer wording, usually a footnote and no "
       "label, does not count: the row is kept, marked and counted, and not "
       "refused. A larger number accepts longer wordings as naming the "
       "entry.", least=1,
       where="pipeline.py (_raw_foreign)"),
    # -- spec: spans of years and groups --------------------------------------
    _r("span_words", "spec", "Spans of years and groups", "texts",
       "Words that make a span of years when the wording of a find has them "
       "and names two years, such as \"bis 2045\". A value stated for a span "
       "is read for every year of it. Add a word to recognise more spans. "
       "Empty: only the dashes of `span_dashes` make a span.", empty=True,
       decided="2026-11-07", where="addressed.py (span)"),
    _r("span_dashes", "spec", "Spans of years and groups", "chars",
       "Dashes that make a span of years when the wording of a find has one "
       "and names two years, such as \"2030-2045\". A value stated for a "
       "span is read for every year of it. Empty: only the words of "
       "`span_words` make a span; with both empty, only the first year is "
       "read.",
       empty=True, decided="2026-11-07", where="addressed.py (span)"),
    _r("span_marks", "spec", "Spans of years and groups", "map",
       "What the rows of a value stated for a span of years are marked with, "
       "as dimension -> entry. Each row of the span that read nothing for "
       "that dimension gets the entry, marked as derived, with the wording "
       "and quote of the span as its evidence. For example, qualifier -> "
       "out:approximate marks every year of the span as approximate. Empty: "
       "the rows get no mark. Decided on 2026-11-07.",
       empty=True, decided="2026-11-07",
       where="runner.py (span rows)"),
    # -- spec: defaults where the spec says nothing ---------------------------
    _r("default_takes_group", "spec", "Defaults where the spec says nothing",
       "switch",
       "On: words that name several entries, such as \"all scenarios\", "
       "become one row per member, for every field whose Spec does not say "
       "otherwise. Off: such words stay one row. A single field can override "
       "this with its key `takes_group` in the Spec tab.",
       decided="2026-11-08",
       where="spec.py (Parameter), addressed.py"),
    _r("description_least_words", "spec", "Defaults where the spec says "
                                          "nothing",
       "whole", "The fewest words the description of a field may have. A "
       "shorter description is refused when the Spec is loaded, because the "
       "description is the definition the model reads. A larger number "
       "demands fuller descriptions. 0 accepts any.", least=0,
       where="spec.py (load)"),
    _r("example_least_words", "spec", "Defaults where the spec says nothing",
       "whole",
       "The fewest words the source text of a field's example may have. A "
       "shorter text is refused when the Spec is loaded, because an example "
       "must be a real snippet and no placeholder. A larger number demands "
       "longer examples. 0 accepts any.", least=0,
       where="spec.py (load)"),
    # -- prompts: how a place in the document is shown ------------------------
    _r("lines_around", "prompts", "How a place in the document is shown",
       "whole",
       "How many sentences a request shows before and after the line of a "
       "value in running text. In a table it shows the value's row under the "
       "table head instead. A larger number gives the model more context and "
       "makes every request longer. 0 shows only the value's own line.",
       least=0,
       decided="2026-11-08", where="addressed.py (show_value)"),
    _r("letter_title_page", "prompts", "How a place in the document is shown",
       "text",
       "The letter put before the line numbers of the title page in a "
       "request, so that \"T3\" names the third line of the title page. The "
       "model cites a line by this letter and number. Use a letter that no "
       "other block uses.",
       decided="2026-11-08",
       where="units.py"),
    _r("letter_headings", "prompts", "How a place in the document is shown",
       "text",
       "The letter put before the line numbers of the headings above the "
       "value in a request, so that \"H2\" names the second heading shown. "
       "The model cites a line by this letter and number. Use a letter that "
       "no other block uses.",
       decided="2026-11-08",
       where="units.py"),
    _r("letter_settings", "prompts", "How a place in the document is shown",
       "text",
       "The letter put before the line numbers of the fields of the whole "
       "document in a request, such as its base year or municipality, so "
       "that \"F1\" names the first of them. The model cites a line by this "
       "letter and number. Use a letter that no other block uses.",
       decided="2026-11-08", where="units.py"),
    _r("letters_others", "prompts", "How a place in the document is shown",
       "chars",
       "The letters put before the line numbers of the other chunks a "
       "request shows, one letter for each chunk, in this order. The letters "
       "of the title page, the headings and the fields of the whole document "
       "are skipped.", decided="2026-11-08",
       where="units.py"),
    _r("head_joiner", "prompts", "How a place in the document is shown",
       "text",
       "What joins the words of a table head when several head rows stand "
       "above one cell, such as \"2030 / Bestand\". The request shows the "
       "joined words as the head of that cell. Change it to the separator "
       "the model should read between them.",
       where="units.py (head_of)"),
    # -- prompts: examples ----------------------------------------------------
    _r("example_words", "prompts", "Examples", "text",
       "What the example answer of a request gives as the wording of a "
       "value. It is a placeholder, so that the model cannot copy a real "
       "wording from the example. A real word here would be copied into "
       "answers.",
       decided="2026-11-06, 2026-11-07", where="fields.py"),
    _r("example_year", "prompts", "Examples", "text",
       "What the example answer of a request gives as a year. It is a "
       "placeholder, so that the model cannot copy a real year from the "
       "example. A real year here would be copied into answers.",
       decided="2026-11-06",
       where="fields.py"),
    _r("example_cell", "prompts", "Examples", "whole",
       "Which cell of a table row the example answer of a request names, "
       "counted from 1. A row with fewer cells gets its last cell, and a row "
       "with one cell gets no cell. A different number only changes the "
       "example, not how answers are read.", least=1,
       decided="2026-11-09", where="addressed.py (first_address)"),
    # -- prompts: defaults where the prompt says nothing ----------------------
    _r("temperature", "prompts", "Defaults where the prompt says nothing",
       "number",
       "The temperature of a request whose prompt sets none. It decides how "
       "much the model's answers vary: 0 makes them repeatable, a larger "
       "number up to 2 varies them. A prompt that sets its own temperature "
       "wins.", least=0,
       most=2, where="runner.py"),
    _r("max_tokens", "prompts", "Defaults where the prompt says nothing",
       "whole",
       "The longest answer, in tokens, of a request whose prompt sets none. "
       "A larger number lets long answers finish and makes every request "
       "reserve more room in the model's window. An answer that is cut off "
       "at the limit is not read, and the run splits the request where it "
       "can.",
       least=1,
       where="runner.py"),
    _r("retry_temperature_step", "prompts", "Defaults where the prompt says "
                                            "nothing",
       "number", "How much the temperature rises for the next attempt after "
       "each answer that could not be read. A request asked again at "
       "temperature 0 comes back the same, so every faulty answer raises the "
       "temperature by this step. A larger number changes the repeats more. "
       "0 asks every attempt the same way.", least=0,
       env="EXTRACT_RETRY_TEMPERATURE_STEP", where="runner.py"),
    _r("retry_temperature_most", "prompts", "Defaults where the prompt says "
                                            "nothing",
       "number", "The highest temperature an attempt is raised to; the rises "
       "of `retry_temperature_step` stop here. A lower number keeps repeats "
       "closer to the first answer. A higher number lets a stubborn request "
       "vary more.",
       least=0, most=2, where="runner.py"),
    _r("image_max_side", "prompts", "Defaults where the prompt says nothing",
       "whole",
       "The most pixels the longer side of the image of a table or figure is "
       "sent with; a larger image is scaled down. A larger number shows the "
       "model more detail and uses more of its window, one image token for "
       "every 28 by 28 pixels. A smaller number saves room and loses fine "
       "print.",
       least=28, env="EXTRACT_IMAGE_MAX_SIDE", decided="2026-11-08",
       where="runner.py"),
    _r("heading_in_front_chars", "prompts", "Defaults where the prompt says "
                                            "nothing",
       "whole", "A section's heading is put in front of its text, so that a "
       "quote may cite it, unless it already stands within this many first "
       "characters of the text. A larger number leaves more headings where "
       "they are, because they stand early in the text. 0 always puts the "
       "heading in front.", least=0,
       where="runner.py"),
    # -- flow: chunks ---------------------------------------------------------
    _r("sentence_marks", "flow", "Chunks", "chars",
       "Marks that end a sentence when a space and then a capital letter or "
       "a digit follow. A sentence is the unit of a numbered line in running "
       "text, and a chunk holds a number of them. Fewer marks make longer "
       "lines, more marks split the text finer. A number with a point, such "
       "as \"12.\", never ends a sentence.",
       decided="2026-11-08", where="units.py"),
    _r("abbreviations", "flow", "Chunks", "texts",
       "Abbreviations, as the documents print them, whose full stop does not "
       "end a sentence, such as \"z. B.\" or \"Abb.\". Text that ends in one "
       "of them is not split there. Add the abbreviations of your documents. "
       "Empty: every full stop before a capital letter ends a sentence.",
       empty=True, decided="2026-11-08",
       where="units.py"),
    _r("title_page_also", "flow", "Chunks", "whole",
       "The page whose first lines are the title page when the first page "
       "has none. The first page is tried first. A document with a cover "
       "page of no text can name its second page here.",
       least=1, decided="2026-11-08", where="units.py"),
    # -- flow: search ---------------------------------------------------------
    _r("rerank", "flow", "Search", "switch",
       "On: the reranker orders the chunks a search found once, with the "
       "search sentence, and the best come first. Off: they stay in the "
       "order of the embedding search. Only a search with at least two "
       "chunks is ordered.",
       decided="2026-11-06, 2026-11-08", where="addressed.py"),
    _r("fetches", "flow", "Search", "texts",
       "What an answer may ask to see besides the chunks shown. `next` and "
       "`previous` are the chunk after the last and before the first one "
       "shown, `item` is a table or figure it names, `search` is the chunks "
       "that match a pattern, and `similar` is the chunks closest to a text "
       "it writes. Chunks asked for this way come first in the next request, "
       "and no chunk is shown twice. `image` lets a question about a "
       "dimension ask once for the picture of a figure it shows: the same "
       "question is then asked again with the picture, and its answer is "
       "still a shown line. Besides the search, the question at the value's "
       "place, a field of the whole document, the list entry of a name and "
       "the details of a cited work may ask to see more; a name or a detail "
       "is then asked again with what it asked for. Each of these steps has "
       "a value of its own. Remove an entry to forbid it. Empty: the model "
       "sees only what the step shows.",
       choices=("next", "previous", "item", "search", "similar", "image"),
       empty=True, decided="2026-11-07, 2026-11-09, 2026-11-12",
       where="addressed.py"),
    _r("fetch_rounds", "flow", "Search", "whole",
       "How often the list entry of a name or a detail of a cited work is "
       "asked again with the chunks its answer asked to see, such as the "
       "place that explains a short scenario name or the entry of the list "
       "of references. 0: such an answer is taken as it is and nothing is "
       "fetched.",
       least=0, decided="2026-11-12", where="addressed.py"),
    _r("question_as_sentence", "flow", "Search", "switch",
       "On: a search sentence that is a question is used, and the run counts "
       "it. Off: such a sentence is replaced by the field's own search "
       "sentence. A question is a sentence that ends in a question mark or "
       "starts with a question word.",
       decided="2026-11-08", where="addressed.py"),
    # -- flow: asking again and giving up -------------------------------------
    _r("retry_wait_s", "flow", "Asking again and giving up", "number",
       "The seconds the run waits before it asks again after an answer that "
       "could not be read. The wait is this number times the number of the "
       "attempt, up to `retry_wait_most_s`. A larger number slows the "
       "repeats and spares the server. 0 asks again at once.",
       least=0, env="EXTRACT_RETRY_WAIT", where="runner.py"),
    _r("retry_wait_most_s", "flow", "Asking again and giving up", "number",
       "The most seconds the run waits before it asks again after an answer "
       "that could not be read. The waits of `retry_wait_s` grow by attempt "
       "and stop here. A larger number lets later attempts wait longer.",
       least=0, env="EXTRACT_RETRY_WAIT_MAX", where="runner.py"),
    _r("transport_wait_s", "flow", "Asking again and giving up", "number",
       "The seconds the run waits after the first failure to reach the "
       "server. The wait doubles with every further failed attempt, up to "
       "`transport_wait_most_s`. A larger number gives a restarting server "
       "more time to come back.", least=0, env="EXTRACT_TRANSPORT_WAIT",
       where="runner.py"),
    _r("transport_wait_most_s", "flow", "Asking again and giving up",
       "number", "The most seconds the run waits between two attempts to "
       "reach the server. The waits of `transport_wait_s` double and stop "
       "here. A larger number lets a long outage be waited out with fewer "
       "attempts.", least=0, env="EXTRACT_TRANSPORT_WAIT_MAX",
       where="runner.py"),
    _r("repeat_timeout_s", "flow", "Asking again and giving up", "number",
       "The seconds a repeated request waits for its answer, at least, after "
       "a request has timed out. The first attempt keeps the run's own time "
       "limit. A larger number gives a slow server more time and holds one "
       "thread longer. A smaller number gives up on such a request sooner.",
       least=1,
       env="EXTRACT_RETRY_TIMEOUT", where="runner.py"),
    _r("server_dead_after_s", "flow", "Asking again and giving up",
       "number", "The seconds without any answer from the model server after "
       "which the run ends at once. What was read so far is written and "
       "stamped, and a later run picks up there. A larger number waits "
       "longer for a restarting server. This applies to the run's own "
       "server, not to a hosted one.",
       least=1, env="EXTRACT_SERVER_DEAD_AFTER",
       where="runner.py"),
    _r("server_probe_every_s", "flow", "Asking again and giving up",
       "number",
       "The seconds between two checks whether the model server answers. A "
       "failed check starts the clock of `server_dead_after_s`, and an "
       "answer stops it. A smaller number finds a dead server sooner and "
       "sends more checks.", least=1,
       where="runner.py"),
    _r("unreachable_share", "flow", "Asking again and giving up", "number",
       "The share of a document's sections, tables and figures whose "
       "requests never reached the server, above which the document counts "
       "as not read. Such a document gets no stamp, so a later run reads it "
       "again. A larger number tolerates more lost requests. 1 never counts "
       "a document as not read for this reason.", least=0, most=1,
       where="runner.py"),
    _r("least_answer_tokens", "flow", "Asking again and giving up", "whole",
       "The fewest tokens a request must leave for its answer in the model's "
       "window. With less room the request is not sent and counts as an "
       "answer that was cut off. A larger number refuses requests with long "
       "prompts sooner. A smaller number sends them and risks a cut-off "
       "answer.",
       least=1, where="runner.py"),
    # -- flow: reading a document again ---------------------------------------
    _r("question_keys", "flow", "Reading a document again", "texts",
       "The beginnings of the stamp keys that decide whether a document is "
       "read again. Each such key records one question of the Spec, such as "
       "a field, a list of entries or a dimension. A document is read again "
       "when one of these questions has changed since its stamp. The model, "
       "the prompts, the flow and the rules are never compared. Remove an "
       "entry to stop changes of that kind from causing a new reading.",
       decided="2026-09-10", where="runner.py (stale)"),
    # -- flow: calculation ----------------------------------------------------
    _r("code_rounds", "flow", "Calculation", "whole",
       "The most code runs a calculation may use before it must answer. Each "
       "run executes the code the model wrote and shows it the output. A "
       "larger number gives the model more tries to get a calculation right "
       "and costs more requests. A smaller number ends calculations sooner.",
       least=1,
       env="EXTRACT_CODE_ROUNDS", decided="2026-11-03", where="runner.py"),
    _r("code_output_chars", "flow", "Calculation", "whole",
       "The most characters of the output of a code run that the model is "
       "shown. Longer output is cut off. A larger number shows more of a "
       "long result and makes the next request longer.", least=1,
       where="runner.py"),
    _r("compute_shown", "flow", "Calculation", "map",
       "How many of the best search hits the search tools of a calculation "
       "show, for each kind: sections, tables and figures. A larger number "
       "gives the calculation more to find numbers in and makes its requests "
       "longer. 0 shows none of that kind.", of="whole", decided="2026-11-04",
       where="reading.py"),
    # -- flow: documents ------------------------------------------------------
    _r("largest_first", "flow", "Documents", "switch",
       "On: the documents of a run are read largest first, by their number "
       "of sections, so that the end of the run is not one long document "
       "alone. Off: they are read in the order of their names.",
       where="runner.py"),
    _r("same_request_once", "flow", "Documents", "switch",
       "On: a request that a document has already sent word for word is "
       "answered with the first answer, and it is not sent again. Off: every "
       "request is sent. Requests that belong to no document are always "
       "sent.", decided="2026-11-07",
       where="scheduler.py"),
)
# Which steps read each rule: where the proof noted a read (the smoke
# probes of both profiles) and where the code reads it on ways the probes
# do not take. A rule no step reads is the run's: it is set at the start or
# in the file, never at a step.
STEPS = {
    "quote_min_chars": TAKING + ("each value", "compute"),
    "unreachable_share": WRITING,
    "question_keys": ("changed", "classify"),
    "word_joiners": TAKING,
    "minus_signs": TAKING,
    "dotted_date_year": TAKING,
    "same_characters": TAKING + ("split", "phrase"),
    "decimal_mark": TAKING,
    "year_range": TAKING,
    "year_words": TAKING,
    "unit_factor_places": TAKING,
    "year_by_plan_word": TAKING,
    "wording_most_chars": TAKING,
    "span_words": TAKING,
    "span_dashes": TAKING,
    "span_marks": TAKING,
    "default_takes_group": ("docfield", "find", "coord", "quantity",
                            "search", "names", "classify", "write"),
    "lines_around": ("coord", "quantity", "work_coordinate", "phrase",
                     "search", "last_year", "about"),
    "letter_title_page": SHOWING,
    "letter_headings": SHOWING,
    "letter_settings": SHOWING,
    "letters_others": SHOWING,
    "head_joiner": SHOWING + ("each value",),
    "example_words": SHOWING,
    "example_year": SHOWING,
    "example_cell": SHOWING,
    "temperature": ASKING + ("each value",),
    "max_tokens": ASKING + ("each value",),
    "retry_temperature_step": ASKING + ("each value",),
    "retry_temperature_most": ASKING + ("each value",),
    "image_max_side": ASKING + ("each value",),
    "heading_in_front_chars": ASKING,
    "sentence_marks": ("split",),
    "abbreviations": ("split",),
    "title_page_also": ("document",),
    "rerank": ("order", "search"),
    "fetches": ("search", "coord", "docfield", "names", "works"),
    # A name is asked where its value or coordinate is read, too.
    "fetch_rounds": ("names", "works", "coord", "search"),
    "question_as_sentence": ("sentences", "order", "phrase"),
    "retry_wait_s": ASKING + ("each value",),
    "retry_wait_most_s": ASKING + ("each value",),
    "transport_wait_s": ASKING + ("each value",),
    "transport_wait_most_s": ASKING + ("each value",),
    "repeat_timeout_s": ASKING + ("each value",),
    "least_answer_tokens": ASKING + ("each value",),
    "code_rounds": ("compute",),
    "code_output_chars": ("compute",),
    "compute_shown": ("compute",),
    "same_request_once": ASKING + ("each value",),
}
RULES = tuple(replace(one, steps=STEPS.get(one.name, one.steps))
              for one in RULES)
# The rules of the reading that stood in its code until 2026-11-11
# (owner decision 2026-11-11), one module per part of the run.
from .ruleset import MORE as _MORE  # noqa: E402

RULES = RULES + _MORE
# A general step reads what the steps whose work it does read (owner
# decision 2026-11-12, ruleset/kit.py STANDS_FOR).
RULES = tuple(replace(one, steps=with_general(
    one.steps, one.group == SEARCH_GROUP)) for one in RULES)
BY_NAME = {one.name: one for one in RULES}
if len(BY_NAME) != len(RULES):
    raise AssertionError("rules.RULES names a rule twice")
for _one in RULES:
    if _one.tab not in TABS or _one.kind not in KINDS:
        raise AssertionError(f"rules.RULES: {_one.name} has no tab or kind "
                             f"of this module")


@dataclass(frozen=True)
class Rules:
    """The rules one run reads with, and where each comes from."""
    values: dict                    # name -> value, in the order of RULES
    owners: dict                    # name -> "rules.json of <profile>" or
                                    #         what set its setting
    files: tuple = ()               # ((profile name, path)), farthest first
    sha256: str = ""                # of the files' rules, settings left out
    state: str = ""                 # of the values in effect, settings in

    def __getitem__(self, name: str):
        try:
            return self.values[name]
        except KeyError:
            raise RuleError(f"{name!r} is no rule"
                            f"{_nearest(name, self.values)}") from None

    def get(self, name: str, default=None):
        return self.values.get(name, default)


# -- one value ----------------------------------------------------------------

def _nearest(name, known) -> str:
    close = difflib.get_close_matches(str(name), list(known), n=3, cutoff=0.6)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def problem(name: str, value, known: Optional[dict] = None) -> Optional[str]:
    """Why *value* is not the rule *name*, None where it is. *known* are
    the rules the profile's line knows (`registry`), the core's where not
    given."""
    known = BY_NAME if known is None else known
    one = known.get(name)
    if one is None:
        return f"{name!r} is no rule{_nearest(name, known)}"
    kind = one.kind

    def bounded(number) -> Optional[str]:
        if one.least is not None and number < one.least:
            return f"{name} must be at least {one.least:g}, not {number}"
        if one.most is not None and number > one.most:
            return f"{name} must be at most {one.most:g}, not {number}"
        return None
    if kind == "whole":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{name} must be a whole number, not {value!r}"
        return bounded(value)
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{name} must be a number, not {value!r}"
        return bounded(value)
    if kind == "switch":
        if not isinstance(value, bool):
            return f"{name} must be true or false, not {value!r}"
        return None
    if kind == "choice":
        if value not in one.choices:
            return (f"{name} must be one of "
                    f"{', '.join(repr(c) for c in one.choices)}, not "
                    f"{value!r}")
        return None
    if kind in ("text", "chars"):
        if not isinstance(value, str):
            return f"{name} must be a text, not {value!r}"
        if not value and not one.empty:
            return f"{name} must not be empty"
        if kind == "chars" and len(set(value)) != len(value):
            return f"{name} names a character twice: {value!r}"
        return None
    if kind == "texts":
        if not isinstance(value, list) \
                or not all(isinstance(part, str) and part for part in value):
            return f"{name} must be a list of texts, none of them empty"
        if not value and not one.empty:
            return f"{name} must not be empty"
        if len(set(value)) != len(value):
            return f"{name} names an entry twice"
        stray = [part for part in value
                 if one.choices and part not in one.choices]
        if stray:
            return (f"{name}: {', '.join(stray)} is none of "
                    f"{', '.join(one.choices)}")
        return None
    if kind == "map":
        if not isinstance(value, dict) or not all(
                isinstance(key, str) and key for key in value):
            return f"{name} must be an object of named entries"
        if not value and not one.empty:
            return f"{name} must not be empty"
        for key, part in value.items():
            if one.of == "texts":
                good = isinstance(part, list) and all(
                    isinstance(word, str) and word for word in part)
                said = "a list of texts"
            elif one.of == "whole":
                good = isinstance(part, int) and not isinstance(part, bool) \
                    and part >= 0
                said = "a whole number of at least 0"
            else:
                good = isinstance(part, str)
                said = "a text"
            if not good:
                return f"{name}: {key!r} must be {said}, not {part!r}"
        return None
    if kind == "table":
        if not isinstance(value, list):
            return f"{name} must be a list of rows"
        for row in value:
            if not isinstance(row, dict) or set(row) != set(one.columns) \
                    or not all(isinstance(cell, str) for cell in row.values()):
                return (f"{name}: every row has the texts "
                        f"{', '.join(one.columns)}, not {row!r}")
        if not value and not one.empty:
            return f"{name} must not be empty"
        return None
    if kind == "range":
        if value is None:
            return None if one.empty else f"{name} must be two numbers"
        if not (isinstance(value, list) and len(value) == 2
                and all(isinstance(part, int) and not isinstance(part, bool)
                        for part in value)):
            return f"{name} must be two whole numbers or empty, not {value!r}"
        if value[0] > value[1]:
            return f"{name}: {value[0]} is after {value[1]}"
        return None
    return f"{name} is of no kind this module reads"


def checked(where, name: str, value, known: Optional[dict] = None):
    said = problem(name, value, known)
    if said is not None:
        raise RuleError(f"{where}: {said}")
    return value


# How a setting that is a flag says "off"; any other spelling is "on".
OFF = ("0", "false", "no", "off", "")


def _setting(one: Rule, raw: str):
    """The value of a rule as its setting spells it: a number, a text, one of
    its choices, or, for a setting that is a flag (`env_flag`), the value
    the flag stands for."""
    if one.env_flag:
        value = one.env_flag[raw.strip().lower() not in OFF]
    elif one.kind in ("text", "choice"):
        value = raw.strip()
    else:
        try:
            value = int(raw.strip()) if one.kind == "whole" else float(raw)
        except ValueError:
            raise RuleError(f"{one.env} must be a number, not {raw!r}") \
                from None
    said = problem(one.name, value, {one.name: one})
    if said is not None:
        raise RuleError(f"{one.env}: {said}")
    return value


# -- the files ----------------------------------------------------------------

def declared(profile) -> list:
    """[(profile name, its own rules, the file beside them)] of *profile*'s
    line, farthest first: the rules a profile declares for its own code
    (`profiles/<name>/rules.py: RULES`), which the core does not know, and
    the rules.json beside that module, which they start from."""
    if profile is None or not callable(getattr(profile, "lineage", None)):
        return []
    out = []
    for one in reversed(profile.lineage()):
        own = one.own("rules", "RULES") if hasattr(one, "own") else None
        if own:
            import importlib
            module = importlib.import_module(
                f"profiles.{one.name}.rules")
            beside = Path(module.__file__).resolve().parent / FILE
            out.append((one.name, tuple(own), beside))
    return out


def registry(profile=None) -> dict:
    """{name: Rule} of every rule a run of *profile* reads: the core's and
    those its line declares, in the order a file writes them."""
    known = dict(BY_NAME)
    for owner, own, _beside in declared(profile):
        for one in own:
            if not isinstance(one, Rule):
                raise RuleError(f"profile {owner!r} declares {one!r}, which "
                                f"is no Rule")
            if one.name in known:
                raise RuleError(f"profile {owner!r} declares the rule "
                                f"{one.name!r} again")
            if one.tab not in TABS or one.kind not in KINDS:
                raise RuleError(f"profile {owner!r}: {one.name} has no tab "
                                f"or kind this module reads")
            known[one.name] = one
    return known


def parse(raw: str, where, known: Optional[dict] = None,
          needed: tuple = ()) -> dict:
    """{name: value} of the text *raw*, read strictly against the rules
    *known* (the core's where not given). *needed* are the rules the file
    has to name: those it is the first file of."""
    known = BY_NAME if known is None else known

    def once(pairs: list) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise RuleError(f"{where}: {key!r} stands twice")
            out[key] = value
        return out
    try:
        data = json.loads(raw, object_pairs_hook=once)
    except RuleError:
        raise
    except ValueError as exc:
        raise RuleError(f"{where}: {exc}") from exc
    if not isinstance(data, dict) or set(data) - {"rules"}:
        raise RuleError(f"{where}: a rules file is one JSON object with "
                        f"\"rules\", the name of a rule -> its value")
    rules = data.get("rules", {})
    if not isinstance(rules, dict):
        raise RuleError(f"{where}: rules must be an object, the name of a "
                        f"rule -> its value")
    read = {name: checked(where, name, value, known)
            for name, value in rules.items()}
    missing = [name for name in needed if name not in read]
    if missing:
        raise RuleError(f"{where}: names no {', '.join(missing)}; this is "
                        f"the file these rules start from")
    return read


def dump(rules: dict, newline: str = "\n", known: Optional[dict] = None) \
        -> str:
    """A rules file's text in the one form it is written in: the rules in
    the order of the registry."""
    known = BY_NAME if known is None else known
    ordered = {name: rules[name] for name in known if name in rules}
    ordered.update({name: value for name, value in rules.items()
                    if name not in ordered})
    text = json.dumps({"rules": ordered}, ensure_ascii=False, indent=2) + "\n"
    # A character nobody sees (a thin space, the soft hyphen) is written as
    # its code, so that the file says which it is.
    text = "".join(f"\\u{ord(ch):04x}" if ch != " " and
                   unicodedata.category(ch) in ("Zs", "Cf", "Zl", "Zp")
                   else ch for ch in text)
    return text if newline == "\n" else text.replace("\n", newline)


def path_of(profile) -> Path:
    return Path(profile.package_dir) / FILE


def line(profile) -> list:
    """[(profile name, path)] of the files a profile's rules can stand in,
    nearest first, the default's last."""
    if profile is None or getattr(profile, "package_dir", None) is None:
        return [(DEFAULT_NAME, DEFAULT)]
    lineage = getattr(profile, "lineage", None)
    profiles = lineage() if callable(lineage) else [profile]
    out = [(one.name, path_of(one)) for one in profiles]
    if not any(Path(path) == DEFAULT for _, path in out):
        out.append((DEFAULT_NAME, DEFAULT))
    return out


_loaded: dict = {}
_LOADED_KEPT = 16


def _merged(profile, skip_own: bool = False) -> tuple:
    """(values, owners, files, sha256) of *profile*'s rules files: the
    default's names every rule of the core, the file beside the rules a
    profile declares names every one of them, and every file of the
    profile's line is laid over the farther ones rule by rule. *skip_own*
    leaves the profile's own file and its own rules out: what it has where
    its own file says nothing."""
    known = registry(profile)
    places = line(profile)
    mine = places[0][0]
    starts = declared(profile)
    if skip_own:
        places = places[1:]
        for owner, own, _beside in starts:
            if owner == mine:
                for one in own:
                    known.pop(one.name, None)
        starts = [start for start in starts if start[0] != mine]
    order: list = [(DEFAULT_NAME, DEFAULT, tuple(BY_NAME))]
    placed = {Path(path).resolve() for _, path in places
              if Path(path).is_file()}
    for owner, own, beside in starts:
        if beside.resolve() not in placed:
            order.append((owner, beside, tuple(one.name for one in own)))
    first_of = {owner: tuple(one.name for one in own)
                for owner, own, beside in starts
                if beside.resolve() in placed}
    for name, path in reversed(places):
        if Path(path) == DEFAULT:
            continue
        order.append((name, Path(path), first_of.get(name, ())))
    present = [(name, Path(path), needed) for name, path, needed in order
               if Path(path).is_file()]
    key = (skip_own, tuple(known), tuple(
        (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        for _, path, _needed in present))
    if key in _loaded:
        return _loaded[key]
    if not present or present[0][1] != DEFAULT:
        raise RuleError(f"{DEFAULT} is missing: the rules start from it")
    values: dict = {}
    owners: dict = {}
    for name, path, needed in present:
        for one, value in parse(path.read_text(encoding="utf-8"), path,
                                known, needed).items():
            values[one], owners[one] = value, name
    lost = [name for name in known if name not in values]
    if lost:
        raise RuleError(f"no rules file names {', '.join(lost)}: the file "
                        f"beside the rules a profile declares is the one they "
                        f"start from")
    values = {name: values[name] for name in known}
    sha = hashlib.sha256(json.dumps(values, ensure_ascii=False,
                                    sort_keys=True).encode("utf-8")
                         ).hexdigest()
    made = (values, owners, tuple((name, path) for name, path, _ in present),
            sha)
    while len(_loaded) >= _LOADED_KEPT:
        _loaded.pop(next(iter(_loaded)))
    _loaded[key] = made
    return made


def load(profile=None, environ=None) -> Rules:
    """The rules of *profile* (the default's where None): its files laid
    over each other, and over them the settings that are set (*environ*,
    the environment where not given)."""
    values, owners, files, sha = _merged(profile)
    values = dict(values)
    owners = {name: f"{FILE} of {owner}" for name, owner in owners.items()}
    own = environ is None
    environ = os.environ if own else environ
    for one in registry(profile).values():
        raw = environ.get(one.env) if one.env else None
        if raw is not None:
            values[one.name] = _setting(one, raw)
            if own:
                from . import settings
                owners[one.name] = settings.origin(one.env)
            else:
                owners[one.name] = "environment"
    return Rules(values, owners, files, sha, _state(values))


def _state(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")
                          ).hexdigest()


def inherited(profile) -> Optional[Rules]:
    """The rules *profile* has where its own file says nothing, no setting
    applied: those of the files of the profiles it extends. None for the
    default profile."""
    if profile is None or len(line(profile)) < 2:
        return None
    values, owners, files, sha = _merged(profile, skip_own=True)
    return Rules(dict(values), {name: f"{FILE} of {owner}"
                                for name, owner in owners.items()},
                 files, sha, _state(values))


def default() -> Rules:
    """The default profile's rules, no setting applied."""
    return load(None, environ={})


# -- the rules a run reads with -----------------------------------------------

_lock = threading.Lock()
# What a run took (`use`): (ambient profile name, Rules).
_taken: Optional[tuple] = None
# The ambient profile's rules, by (its name, the settings that win).
_ambient: dict = {}
_derived: dict = {}
ENVS = tuple(one.env for one in RULES if one.env)


def use(profile=None, environ=None) -> Rules:
    """Read with the rules of *profile* from here on, while it is the
    ambient profile (`DOCPIPE_PROFILE` names it); returned."""
    global _taken
    made = load(profile, environ)
    with _lock:
        _taken = (getattr(profile, "name", None) or "", made)
        _derived.clear()
    return made


def reset() -> None:
    """Forget the rules taken and read, so that the next read takes the
    files as they are now (for tests, and after a rules file was written)."""
    global _taken
    with _lock:
        _taken = None
        _ambient.clear()
        _derived.clear()
        _loaded.clear()
        _owned.clear()


def current() -> Rules:
    """The rules a run reads with: those a run took (`use`) for the
    ambient profile, else the ambient profile's (`DOCPIPE_PROFILE`), else
    the default's."""
    ambient = os.environ.get("DOCPIPE_PROFILE") or ""
    taken = _taken
    if taken is not None and taken[0] == ambient:
        return taken[1]
    key = (ambient, tuple(os.environ.get(env) for env in ENVS))
    made = _ambient.get(key)
    if made is None:
        from .profile import active_profile
        made = load(active_profile())
        with _lock:
            if len(_ambient) > 32:
                _ambient.clear()
            _ambient[key] = made
    return made


_owned: dict = {}


# -- the values of a step -----------------------------------------------------


@dataclass(frozen=True)
class Step:
    """The values a step of the flow and its frames set for themselves,
    laid over each other (the innermost wins), while it runs."""
    kind: str                       # of the innermost node (`step_kind`)
    ident: str                      # its id in the drawing
    values: dict                    # name -> value: rules and numbers of
                                    # the flow
    owners: dict                    # name -> "step <id>" or "frame <id>"
    state: str = ""                 # of the values, "" where there are none


STEP: contextvars.ContextVar = contextvars.ContextVar("step", default=None)


def step_kind(node: dict) -> str:
    """How a node of a flow is named where a rule says which steps read it:
    a box by its kind ("find"), a frame as "each <what>", "round" or
    "if"."""
    if "box" in node:
        return str(node["box"])
    if "each" in node:
        return f"each {node['each']}"
    return "round" if "round" in node else "if"


def stepped(node: dict, values: dict) -> "Step":
    """The step of *node* with its own *values* laid over the step it
    stands in."""
    outer = STEP.get()
    ident = str(node.get("id") or "")
    owner = ("step " if "box" in node else "frame ") + ident
    merged = dict(outer.values) if outer is not None else {}
    owners = dict(outer.owners) if outer is not None else {}
    for name, value in values.items():
        merged[name], owners[name] = value, owner
    return Step(step_kind(node), ident, merged, owners,
                _state(merged) if merged else "")


class in_step:
    """Read with *step*'s values while the block runs (`STEP`)."""

    def __init__(self, step: Step):
        self.step = step

    def __enter__(self) -> Step:
        self._token = STEP.set(self.step)
        return self.step

    def __exit__(self, *exc) -> None:
        STEP.reset(self._token)


# The reads a run made while `recording`: (the kind of
# step that read, the rule or number), "run" outside every step.
_reads: Optional[set] = None


class recording:
    """Note every read of a rule or a number of the flow while the block
    runs, in every thread: {(step kind, name)}."""

    def __enter__(self) -> set:
        global _reads
        self._before = _reads
        _reads = set()
        return _reads

    def __exit__(self, *exc) -> None:
        global _reads
        _reads = self._before


def noted(name: str) -> None:
    """Note a read of *name* where `recording` asks for it."""
    reads = _reads
    if reads is not None:
        step = STEP.get()
        reads.add((step.kind if step is not None else "run", name))


def stepped_value(name: str):
    """(True, the step's own value of *name*) where the step that runs or
    a frame around it sets one, else (False, None). Noted as a read."""
    noted(name)
    step = STEP.get()
    if step is not None and name in step.values:
        return True, step.values[name]
    return False, None


def get(name: str, owner: Optional[str] = None):
    """The value of the rule *name* in the rules a run reads with: the own
    value of the step that runs or of a frame around it (`STEP`), else the
    run's. A profile's own code names itself as *owner*: where the ambient
    profile's line does not declare the rule, it is *owner*'s (a test of
    the scenario profile's regions run under another ambient profile)."""
    own, value = stepped_value(name)
    if own:
        return value
    rules = current()
    if owner is None or name in rules.values:
        return rules[name]
    key = (owner, tuple(os.environ.get(env) for env in ENVS))
    made = _owned.get(key)
    if made is None:
        from .profile import load_profile
        made = load(load_profile(owner))
        with _lock:
            _owned[key] = made
    return made[name]


def derived(key: str, build: Callable):
    """What *build* makes of the rules in effect, made once per state of
    the rules and of the step's own values: a pattern compiled from a list
    of words."""
    step = STEP.get()
    slot = (key, current().state, step.state if step is not None else "")
    made = _derived.get(slot)
    if made is None:
        made = build()
        with _lock:
            if len(_derived) > 512:
                _derived.clear()
            _derived[slot] = made
    return made


def of_tab(tab: str, profile=None) -> list:
    """The rules of *tab* a run of *profile* reads, in their order."""
    return [one for one in registry(profile).values() if one.tab == tab]


class overlaid:
    """The rules a run reads with, with *values* laid over them, while the
    block runs: for a test that wants one rule set otherwise.

        with rules.overlaid(year_range=None):
            ...
    """

    def __init__(self, **values):
        self.values = values

    def __enter__(self) -> Rules:
        global _taken
        base = current()
        for name, value in self.values.items():
            if name in BY_NAME:
                checked("overlaid", name, value)
        values = {**base.values, **self.values}
        made = Rules(values, {**base.owners,
                              **{name: "overlaid" for name in self.values}},
                     base.files, base.sha256, _state(values))
        with _lock:
            self._before = _taken
            _taken = (os.environ.get("DOCPIPE_PROFILE") or "", made)
            _derived.clear()
        return made

    def __exit__(self, *exc) -> None:
        global _taken
        with _lock:
            _taken = self._before
            _derived.clear()
