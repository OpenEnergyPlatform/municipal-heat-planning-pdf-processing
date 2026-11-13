"""
presets.py: The presets of "Ask the model" (owner decision 2026-11-12
evening: "Umbauen", and for the scope "alles umbauen"; plan "modell_fragen",
point 6).

Every step that asks the model is "Ask the model" (`blocks.LIBRARY["ask"]`)
with a preset: the request it is in the log and whose settings it reads, its
prompt, its inputs, the form of its answer and its target, and the ways it
goes (`Preset`). A step of the drawing names its preset; whatever it sets of
its own wins over the preset (`general.parts_of`). The presets are the
questions the two use cases ask; a profile adds its own
(`profiles/<name>/blocks.py: PRESETS`).

The inputs of each preset are what its request always showed, in the order
it showed them, so that every request stays word for word as it was.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass

from .addressed import PICTURE
from .blocks import PER_REQUEST, RULE, SWITCH, Setting


@dataclass(frozen=True)
class Preset:
    """One preset of "Ask the model": its name and what the page calls it
    and says of it, the request it is (*request*), its inputs, the form of
    its answer (*reply*), its target (*into*), the values of the step's
    other settings (*values*), the settings only it has (*settings*), the
    frames it stands in, whether it stands at the top or prepares the
    document, whether it is a question inside the answer of another
    (*attached*: the requests it follows), the profile it belongs to and the
    date of the owner's decision."""
    name: str
    label: str
    says: str
    request: str
    inputs: tuple
    reply: object
    into: dict
    values: dict = None
    settings: tuple = ()
    needs: tuple = ()
    top: bool = False
    prepares: bool = False
    attached: tuple = ()
    profile: str = ""
    decided: str = ""
    spec: str = ""
    # The kind of step whose rules and numbers it reads (`rules.step_kind`):
    # the step it was before every question became "Ask the model".
    rules_as: str = ""
    # Where it runs besides the reading of a document: "end" for a step the
    # run does once a document is read; for a step of the flow of a
    # follow-up pass (`passflow`) the flow "pass", what it runs for
    # (`blocks.Box.scope`) and the steps that stand before it.
    group: str = ""
    flow: str = ""
    scope: str = ""
    after: tuple = ()

    @property
    def kind(self) -> str:
        return self.rules_as or self.name


def i(key: str, source: str, show: str, **more) -> dict:
    """One input: the key of the message, the variable it comes from and
    how it is shown."""
    return {"key": key, "from": source, "show": show, **more}


# The inputs every question about a value's dimension shows of its place:
# the value, the lines around it, the headings above it, the title page and
# what the document settles, in this order; a value without a place shows
# none of them.
VALUE_PLACE = (
    i("value", "value", "value"),
    i("passage", "value", "value_lines"),
    i("headings", "value", "value_headings"),
    i("title_page", "value", "title_page"),
    i("settings", "value", "settings"),
)
# The questions whose answers a list entry is chosen for.
ASKING = ("find", "docfield", "coord", "search", "own")

ANEW = Setting("anew", SWITCH, "a new sentence from round 2, written "
               "knowing the earlier ones", False,
               help="On: from the second round on the model writes a new "
               "sentence and sees the sentences of the earlier rounds, so it "
               "can try another wording. Off: the first sentence is used in "
               "every round.", rule="phrase_anew")
QUESTION_AS_SENTENCE = Setting(
    "question_as_sentence", RULE, "a question may stand in for the sentence",
    help="On: if the model writes a question instead of a sentence, the "
    "search uses the question, and the run counts it. Off: the search then "
    "uses the field's own sentence.")
LINES_AROUND = Setting("lines_around", RULE, "sentences around the value",
                       help="In running text a request shows this many "
                       "lines before and after the value's line, in a table "
                       "the value's row under the table head. A larger "
                       "number gives the model more context and makes each "
                       "request longer.")

PRESETS = {preset.name: preset for preset in (
    Preset(
        "transcribe", "Write out the figures",
        "The model looks at the picture of each figure once and writes it "
        "out as lines: first its caption (title, axes, legend), then its "
        "numbers. Later questions read a figure from these lines, not from "
        "its picture. The lines are kept with the harvest and written again "
        "only for a new picture, model, prompt, input or answer form. "
        "Example: a bar chart of the heat demand becomes lines such as "
        "\"2030 | Gas | 245 GWh\". To change it: switch it off (a figure is "
        "then shown by its description only), set with a condition which "
        "figures are written out, the inputs (the figure's title and "
        "description, its picture, without which nothing is written out), "
        "or the prompt `transcribe`.",
        "transcribe",
        (i("figure", "figure", "figure_text"),
         i(PICTURE, "figure", "picture")),
        "lines", {"to": "figure_lines"},
        top=True, prepares=True, decided="2026-11-09", group="prepare"),
    Preset(
        "compute", "Compute shares and sums",
        "Once a document is read, its values that passed the checks are gone "
        "through for what they leave open: the absolute number of a share, or "
        "the sum of parts. For each question the model writes code, the "
        "sandbox runs it, and a new value comes out with the code, its output "
        "and its input numbers as proof. Example: a share of 40 % of 600 GWh "
        "gives 240 GWh. Unlike \"Own step in Python\", where you write the "
        "code, here the model writes it for each question. To change it: "
        "switch it off; which shares and sums are computed is set in the "
        "profile's code; the inputs (what is wanted, the numbers and their "
        "passages) and the prompt `compute` shape the question.",
        "compute",
        (i("wanted", "question", "compute_wanted"),
         i("numbers", "question", "compute_numbers"),
         i("sources", "question", "compute_sources")),
        "compute", {"to": "computed"},
        group="end", top=True, spec="compute", decided="2026-11-02"),
    Preset(
        "review", "Second reading",
        "Each row of the trust levels C and D is read a second time, over "
        "its own passage and the section above it, with the picture where "
        "there is one: one request for each row. The row only gets a mark, "
        "agree, disagree or unbacked, and what the second reading said goes "
        "into the working list. To change it: the rules `review_levels`, "
        "`review_once_per_row`, `review_shown_passages` and `review_limit` "
        "say which rows are read and how many; the inputs (the passages, the "
        "row, the dimensions asked) and the prompt `review` shape the "
        "question.",
        "review",
        (i("sources", "row", "review_sources"),
         i("row", "row", "review_row"),
         i("fields", "row", "review_fields")),
        "review", {"to": "review_marks"},
        group="pass", flow="pass", scope="chain", after=("stored",),
        decided="2026-09-13"),
    Preset(
        "example", "Example for a field",
        "This is the request that proposes an example for a field while a "
        "spec is compiled. No run starts it. It stands here so that its "
        "answer room, its temperature, its inputs (the field as the draft "
        "writes it, one passage) and its prompt `example` are set like those "
        "of any request.",
        "example",
        (i("parameter", "field", "draft_field"),
         i("passage", "passage", "always")),
        "example", {"to": "example_proposal"},
        group="pass", flow="pass", scope="run"),
    Preset(
        "sentences", "Order the chunks for each field",
        "For each field read chunk by chunk, the model writes one sentence as "
        "this document would print a value of the field, and the chunks are "
        "ordered by how well they match it, best first. The questions of the "
        "field then go through the chunks in this order; a field of the "
        "whole document searches with the same sentence. Example: for the "
        "heat demand, \"The heat demand of the town was 245 GWh in 2021.\" "
        "Unlike \"Find the best chunks for a question\", which searches for "
        "one question, this order is made once per field and kept with the "
        "harvest. To change it: switch it off (every field then reads the "
        "chunks in the document's order), the inputs (the field's name, what "
        "it means, the names of its list, what the document says of itself) "
        "or the prompt `phrase`.",
        "phrase",
        (i("label", "field", "label"),
         i("description", "field", "description"),
         i("names", "field", "vocabulary"),
         i("document", "context", "as_is")),
        "phrase", {"to": "chunk_order"},
        top=True, decided="2026-11-05, 2026-11-09", group="order"),
    Preset(
        "docfield", "Ask a field once for the whole document",
        "Asks a field the document states once, such as its title, its "
        "authors or its base year, over the best search hits for the field; "
        "the first request also shows the title page. Out come the values of "
        "the field, each with its line, gathered over the rounds; every "
        "value that passes the checks is kept. Example: the authors from the "
        "title page and the imprint. Unlike \"Ask for the values in a "
        "chunk\", which goes through every chunk, this step asks the field "
        "once with the best chunks. To change it: the inputs (without the "
        "title page, no request shows it), the chunks per request, the "
        "follow-up questions and what the model may ask to see (`fetches`); "
        "which fields are asked here is set by the key `once_per_document` "
        "in the Spec tab, how they are asked by the prompt `docfield`.",
        "docfield",
        (i("field", "fact", "field"),
         i("list", "fact", "list"),
         i("title_page", "document", "title_page", first_only=True),
         i("passages", "hits", "next_chunks")),
        "finds", {"to": "values", "keep": "gathered"},
        values={"fetch": True, "example_at": "title_page"},
        settings=(PER_REQUEST,), needs=("field", "settled"),
        decided="2026-11-08, 2026-11-12"),
    Preset(
        "find", "Ask for the values in a chunk",
        "Shows the model one chunk and one field and asks for every value of "
        "the field the chunk prints: for each the number of its line, its "
        "words, and the entry where the field has a list. Every value that "
        "passes the checks is kept. An answer too long for its room is asked "
        "again for each half of the chunk. Example: in a table of the heat "
        "demand by energy carrier, the numbers of its five rows. Unlike \"Ask "
        "a field once for the whole document\", this step goes through every "
        "chunk. To change it: the inputs, the follow-up questions, the "
        "answers in the wrong form and up to how many entries a list shows "
        "what they mean; the prompt `find` and the keys of the field in the "
        "Spec tab shape the question.",
        "find",
        (i("field", "field", "field"),
         i("list", "field", "list"),
         i("headings", "chunk", "headings"),
         i("title_page", "document", "title_page"),
         i("passage", "chunk", "own_lines"),
         i("passages", "chunk", "chunks", several_only=True)),
        "finds", {"to": "values", "keep": "now"},
        needs=("piece",), decided="2026-11-08"),
    Preset(
        "coord", "Ask a dimension at the value's line",
        "Asks one dimension of a value, such as its year or its energy "
        "carrier, where the value stands: the request shows its line with the "
        "head of its table or the sentences around it, the headings above it, "
        "the title page and what holds for the whole document. The answer is "
        "the number of the line that says it and its words, or 0 where no "
        "shown line says it. Example: the year 2021 from the head of the "
        "value's column. Unlike \"Ask a dimension over the search hits\", "
        "this step looks only at the value's own place. To change it: the "
        "inputs, the follow-up questions, the answers in the wrong form, the "
        "sentences around the value and what the model may ask to see "
        "(`fetches`); the prompt `coord` shapes the question.",
        "coord",
        VALUE_PLACE + (
            i("field", "field", "field"),
            i("question", "dimension", "question"),
            i("known", "dimension", "known")),
        "place", {"to": "dimension", "where": "own"},
        values={"fetch": True, "picture": True},
        settings=(LINES_AROUND,), needs=("coordinate",),
        decided="2026-11-08, 2026-11-12"),
    Preset(
        "phrase", "Write a search sentence",
        "The model writes a sentence as the document would print the missing "
        "answer, once for each field, dimension and wording; the search after "
        "it looks for chunks like this sentence. Example: for the missing "
        "year of a heat demand, \"In 2021 the heat demand was 245 GWh.\" To "
        "change it: the inputs, a new sentence from round 2 on and whether a "
        "question may stand in for a sentence; the prompt `phrase` shapes the "
        "sentence.",
        "phrase",
        (i("label", "field", "label"),
         i("description", "field", "description"),
         i("document", "document", "about_document"),
         i("question", "dimension", "question"),
         i("value", "value", "words_lines"),
         i("headings", "value", "heading_texts"),
         i("before", "dimension", "sentences_before")),
        "phrase", {"to": "sentence"},
        settings=(ANEW, QUESTION_AS_SENTENCE), needs=("coordinate",),
        decided="2026-11-09"),
    Preset(
        "search", "Ask a dimension over the search hits",
        "Asks one dimension of a value over the search hits, a few chunks per "
        "request, until a line says it or the hits run out. The request shows "
        "the value's own place and the hits; chunks the model asks to see "
        "come first in the next request, and no chunk is shown twice. "
        "Example: the scenario of a value, found in the introduction of its "
        "chapter. Unlike \"Ask a dimension at the value's line\", this step "
        "looks elsewhere in the document. To change it: the inputs, the "
        "chunks per request, the follow-up questions and what the model may "
        "ask to see (`fetches`); the prompt `search` shapes the question.",
        "search",
        (VALUE_PLACE[0], VALUE_PLACE[1],
         i("headings", "value", "value_headings",
           when={"all": [{"of": "coordinate", "is": "name", "op": "is",
                          "value": "work", "not": True}]}),
         VALUE_PLACE[3], VALUE_PLACE[4],
         i("field", "field", "field"),
         i("question", "dimension", "question"),
         i("known", "dimension", "known"),
         i("passages", "hits", "next_chunks")),
        "place", {"to": "dimension", "where": "hits"},
        values={"fetch": True, "picture": True},
        settings=(PER_REQUEST,), needs=("round", "coordinate"),
        decided="2026-11-09, 2026-11-12"),
    Preset(
        "about", "Check that a find is about this value",
        "A find of the search that stands in another section, table or figure "
        "than the value is kept only where the model says that place speaks "
        "about this value. It checks the answers of the search step before "
        "it. Example: a line \"base year 2021\" from another chapter is "
        "refused for a value of a table about 2030. To change it: the inputs, "
        "or switch it off, then such finds are kept unchecked; the prompt "
        "`check` shapes the question.",
        "check",
        (i("value", "value", "value_or_none"),
         i("passage", "value", "value_passage"),
         i("question", "dimension", "question"),
         i("answer", "find", "find_words"),
         i("place", "find", "find_lines")),
        "yes_no", {"to": "keep_find"},
        needs=("coordinate",), attached=("search",), decided="2026-11-07",
        group="check"),
    Preset(
        "list", "Choose the list entry",
        "Where the words of an answer have to be an entry of a list, such "
        "as an energy carrier or a sector, the model chooses the entry the "
        "words mean, once for each wording; a long list with groups is asked "
        "in two steps, first the group, then the entry. This step stands "
        "after the question whose list entries it chooses and says how that "
        "is asked; one asked where no such step stands is asked as the first "
        "of them in the flow says. Example: the words \"heat from the grid\" "
        "become the entry district heating. To change it: the inputs, the "
        "answer room and the temperature of the request, the follow-up "
        "questions, up to how many entries the list shows what they mean, "
        "and the prompt `list`.",
        "list",
        (i("words", "words", "always"),
         i("question", "dimension", "question"),
         i("lines", "find", "find_lines_if"),
         i("table", "find", "find_table"),
         i("settings", "document", "settings_text"),
         i("list", "options", "always"),
         i("earlier", "earlier", "as_is")),
        "entry", {"to": "entry"},
        attached=ASKING, decided="2026-11-12", group="check"),
    Preset(
        "plan_year_words", "Choose the plan's year of a wording",
        "A year a find names only by the plan's word for its state "
        "(\"Basisjahr\", \"Zieljahr\") is chosen among the plan's base and "
        "target years: the request shows the words, their line, the question "
        "and the years. It stands after the question whose finds it reads; "
        "one asked where no such step stands is asked as the first of them "
        "in the flow says. Example: \"im Zieljahr\" means 2045. To change "
        "it: the inputs and the prompt `list`.",
        "list",
        (i("words", "words", "always"),
         i("lines", "find", "find_lines"),
         i("question", "dimension", "question"),
         i("list", "options", "always")),
        "entry", {"to": "plan_year"},
        attached=("coord", "search"), decided="2026-11-07", rules_as="list",
        group="check"),
    Preset(
        "name", "Choose the entry of a name",
        "A name the document gives a thing, such as a scenario or a work, is "
        "looked up in the document's list of such names: the entry it is, a "
        "new entry where it is not on the list yet, or 0 where the words name "
        "no such thing. Each name is asked once per document and work. It "
        "stands after the question whose answers name such things; one asked "
        "where no such step stands is asked as the first of them in the flow "
        "says. Example: \"NDC\" is the entry \"Nationally Determined "
        "Contributions\" named in chapter 2. To change it: the inputs, what "
        "the model may ask to see (`fetches`, `fetch_rounds`) and the prompt "
        "`names`.",
        "names",
        (i("name", "words", "always"),
         i("lines", "find", "find_lines_if"),
         i("work", "work", "as_is"),
         i("list", "options", "always")),
        "name", {"to": "name"},
        values={"fetch": True},
        attached=ASKING, decided="2026-11-08, 2026-11-12", spec="names",
        rules_as="names"),
)}

for _preset in PRESETS.values():
    assert _preset.request, _preset.name


def preset(name: str):
    """The preset *name*, of the core or of a profile, None where there is
    none."""
    from .blocks import LIBRARY
    LIBRARY.get("ask")          # the profiles' presets are read with it
    return PRESETS.get(name)


def register(one: Preset) -> None:
    """A preset of a profile (`profiles/<name>/blocks.py: PRESETS`)."""
    held = PRESETS.get(one.name)
    if held is not None and held.profile != one.profile:
        raise ValueError(f"profile {one.profile!r} has a preset "
                         f"{one.name!r}, which {held.profile or 'the core'} "
                         f"has already")
    PRESETS[one.name] = one
