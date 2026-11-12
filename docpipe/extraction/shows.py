"""
shows.py: What a request of "Ask the model" shows (owner decision
2026-11-12 evening: every step that asks the model is "Ask the model" with a
preset; plan "modell_fragen", points 1 to 3).

A request is built from the inputs of its step, in their order: each input
is a key of the message, the variable it comes from and how it is shown
(`SHOWS`), and where it says so a condition under which it is shown at all
(`when`). A show that has nothing to show leaves its key out (`OMIT`); a
show whose key always stands in the message gives its empty value.

Lines a request shows carry an address (`units.Shown`): a chunk of the
request's own under "", the title page, the headings and the settings each
under their letter, every other chunk under a letter of its own. The order
of the inputs is the order the blocks are added in, so that the addresses
come out as they always did.

What each show shows is set by the rules it reads (`show_headings`,
`show_title_page`, `show_settled`, `show_known`, `lines_around`, ...), as
the step that asks says (`rules.in_step`).

Author: Felix Vossel
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from .. import rules
from .units import (Chunk, Shown, letter_headings, letter_settings,
                    letter_title_page, own_lines, passage_lines)

# What a show gives where it has nothing to show: its key is left out.
OMIT = object()


class Request:
    """What one request shows: its lines by letter (`units.Shown`), the
    message (`payload`), the chunk shown as its own lines, the letters of
    the other chunks, every chunk it shows, the chunks it took from a
    supply and what they were (*label*), whether it is the first request
    over that supply, and the list a find names its entry in."""

    def __init__(self, ask):
        self.ask = ask
        self.plan = ask.plan
        self.reader = ask.reader
        self.scope = ask.scope
        self.shown = Shown()
        self.payload: dict = {}
        self.own = None
        self.letters: list = []
        self.chunks: list = []
        self.batch: Optional[list] = None
        self.label: Optional[str] = None
        self.first = False
        self.used_up = False
        self.listed = None
        self.place = True           # False: the value has no place

    def letter_blocks(self, chunks: list) -> dict:
        """{letter: block} of *chunks*, each under a letter of its own (the
        letter of its passage where one is shown already), as a request
        shows other chunks than its own."""
        from .addressed import block_payload
        letters: list = []
        for chunk in chunks:
            letter = self.shown.letter_for(chunk.owner)
            self.shown.add(letter, letter, own_lines(chunk))
            if letter not in letters:
                letters.append(letter)
            if letter not in self.letters:
                self.letters.append(letter)
            if chunk not in self.chunks:
                self.chunks.append(chunk)
        plan = self.plan
        return {letter: block_payload(plan.passages.get(
            (self.shown.blocks[letter].entries[0][2].owner_kind,
             self.shown.blocks[letter].entries[0][2].owner_id)),
            self.shown, letter) for letter in letters}


# -- what the shows read ------------------------------------------------------

def _chunks(value) -> list:
    if isinstance(value, Chunk):
        return [value]
    if isinstance(value, (list, tuple)):
        return [one for one in value if isinstance(one, Chunk)]
    return []


def _row(req: Request, value):
    """The row a show of a value shows: in a frame of dimensions the row
    asked (a value may have rows made beside it), else the value's."""
    coord = req.scope.get("coord")
    if coord is not None and (value is None or value is coord
                              or value is req.scope.get("value")):
        return coord.row
    row = getattr(value, "row", None)
    return row


def _placeless(req: Request, value) -> bool:
    """Is *value* a value (or a dimension of one) that stands in no
    passage? What is shown with its place is then not shown."""
    if getattr(value, "row", None) is None:
        return False
    return _place(req, value) is None


def _claim(req: Request, value) -> dict:
    row = _row(req, value)
    return row.claim if row is not None else {}


def _slot(value):
    """(the slot of a dimension, the name it is asked under)."""
    slot = getattr(value, "slot", None)
    if slot is None:
        return None, ""
    return slot, getattr(value, "name", None) or slot.name


def _place(req: Request, value):
    """(passage, first line, last line) of the value a show shows, None
    where it has no place."""
    claim = _claim(req, value)
    at = claim.get("at") or {}
    owner = tuple(at.get("owner") or ())
    passage = req.plan.passages.get(owner) if req.plan is not None else None
    if passage is None:
        return None
    first = int(at.get("line") or 1)
    last = int(at.get("last") or first)
    return passage, first, last


def around(passage, first: int, last: int) -> list:
    """The numbers of the lines shown around a value: its row and the rows
    the rule `rows_around` adds in a table, else the lines the rule
    `lines_around` adds."""
    if passage.kind == "table":
        rows = rules.get("rows_around")
        return list(range(max(1, first - rows), last + 1 + rows))
    around = rules.get("lines_around")
    return list(range(max(1, first - around), last + 1 + around))


# -- the shows ----------------------------------------------------------------

def _as_is(req, value, spec):
    from .general import view
    shown = view(value)
    if shown is None or shown == [] or shown == {} or shown == "":
        return OMIT
    return shown


def _text(req, value, spec):
    from .general import view
    shown = view(value)
    if shown is None or shown == [] or shown == {} or shown == "":
        return OMIT
    return shown if isinstance(shown, str) \
        else json.dumps(shown, ensure_ascii=False)


def _field(req, value, spec):
    """A field as a request shows it: its name and what a value of it is
    (rule `field_text`); a field of the whole document as its item says."""
    from .addressed import field_shown
    item = value
    if type(item).__name__ == "FieldItem":
        if item.shown is None and item.parameter is not None:
            item.shown = field_shown(item.parameter)
        return item.shown if item.shown is not None else OMIT
    if isinstance(value, dict) and "name" in value:
        return value
    if hasattr(value, "label") and hasattr(value, "description"):
        return field_shown(value)
    return OMIT


def _list(req, value, spec):
    """The entries a value of the field is chosen from, numbered."""
    if type(value).__name__ == "FieldItem":
        listed = value.listed
    elif hasattr(value, "value_type"):
        listed = req.reader.listed(value)
    else:
        listed = None
    req.listed = listed
    return listed[0] if listed else OMIT


def _lines(req, value, spec):
    """One chunk as the request's own lines, several each under a letter
    (a step of the page, `general`)."""
    from .addressed import block_payload
    chunks = _chunks(value)
    if not chunks:
        return OMIT
    if len(chunks) == 1 and req.own is None:
        chunk = chunks[0]
        req.own = chunk
        req.chunks.append(chunk)
        req.shown.add("", "passage", own_lines(chunk))
        return block_payload(chunk.passage, req.shown)
    return req.letter_blocks(chunks)


def _own_lines(req, value, spec):
    """A chunk as the request's own lines, numbered as in its passage;
    nothing where the input holds several chunks."""
    from .addressed import block_payload
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            return OMIT
        value = value[0]
    if not isinstance(value, Chunk):
        return OMIT
    req.own = value
    if value not in req.chunks:
        req.chunks.append(value)
    req.shown.add("", "passage", own_lines(value))
    return block_payload(value.passage, req.shown)


def _chunks_lettered(req, value, spec):
    """Chunks each under a letter of their own; with "several_only" only
    where there are several."""
    chunks = _chunks(value)
    if not chunks:
        return OMIT
    if spec.get("several_only") and not (isinstance(value, (list, tuple))
                                         and len(chunks) > 1):
        return OMIT
    return req.letter_blocks(chunks)


def _next_chunks(req, value, spec):
    """The next chunks of the hits, as many as a request of the step shows:
    those a reply asked to see first, none shown before; each under a
    letter of its own. Where none is left, the request is not made. They
    are taken before any input is shown (`build`), since whether the
    request is the first over the hits decides what else it shows."""
    if not req.batch:
        return OMIT
    return req.letter_blocks(req.batch)


def take(req: Request, supply, size: int):
    """The chunks a request takes from the scope's *supply* (`engine`'s
    `ListSupply` for a field, `SearchSupply` for a dimension), noted on the
    request; None where the supply has nothing left."""
    if supply is None:
        return None
    coord = req.scope.get("coord")
    if hasattr(supply, "ranked"):           # a dimension's search
        req.ask.engine.locate(coord, req.plan)
        batch, label = supply.take(size, coord.seen)
        if not batch:
            return None
        req.scope.drew()
        coord.seen.update(c.key for c in batch)
        if label == supply.label and supply.ranked is not None:
            coord.ordered.update(c.key for c in batch)
        req.batch, req.label = batch, label
        return batch
    taken = supply.take(size)
    if taken is None:
        return None
    req.scope.drew()
    req.first, req.batch = taken
    return req.batch


def _headings(req, value, spec):
    """The headings above the first chunk (rule `show_headings`)."""
    chunks = _chunks(value)
    if not chunks or not rules.get("show_headings"):
        return OMIT
    heads = req.plan.headings(chunks[0].owner)
    if not heads:
        return OMIT
    req.shown.add(letter_headings(), "headings", heads, renumber=True)
    return req.shown.rendered(letter_headings())


def _title_page(req, value, spec):
    """The first lines of the document's first page: in every request, in
    the first a step makes in the document or in none (rule
    `show_title_page`); with "first_only" in the first request over the
    step's hits only, where the rule says neither "always" nor "never"."""
    from .addressed import title_page_shown
    plan = req.plan
    if plan is None or _placeless(req, value):
        return OMIT
    if spec.get("first_only"):
        mode = rules.get("show_title_page")
        shown = {"always": True, "never": False}.get(mode, req.first)
    else:
        shown = title_page_shown(plan)
    if not shown or not plan.title_page:
        return OMIT
    req.shown.add(letter_title_page(), "title_page", plan.title_page,
                  renumber=True)
    return req.shown.rendered(letter_title_page())


def _settings(req, value, spec):
    """What the document settles for all its values, as lines that can be
    named (rule `show_settled`)."""
    plan = req.plan
    if plan is None or not plan.settings or not rules.get("show_settled") \
            or _placeless(req, value):
        return OMIT
    req.shown.add(letter_settings(), "settings", plan.settings,
                  renumber=True)
    return req.shown.rendered(letter_settings())


def _settings_text(req, value, spec):
    """What the document settles, as plain lines beside a list (rule
    `show_settled`)."""
    from .addressed import settings_of
    shown = settings_of(req.plan) if req.plan is not None else {}
    return shown.get("settings") or OMIT


def _facts(req, value, spec):
    return _settings_text(req, value, spec)


def _value(req, value, spec):
    """The value as its words and its address."""
    place = _place(req, value)
    if place is None:
        req.place = False
        return OMIT
    _passage, first, last = place
    claim = _claim(req, value)
    at = claim.get("at") or {}
    value_at = f"{first}" + (f".{at['cell']}" if at.get("cell") else "") \
        + (f"-{last}" if last != first else "")
    return {"words": claim.get("value_raw") or claim.get("value"),
            "at": value_at}


def _value_lines(req, value, spec):
    """The value's line with its table's title and head, or the sentences
    before and after it (rules `lines_around`, `rows_around`), as the
    request's own lines."""
    from .addressed import block_payload
    place = _place(req, value)
    if place is None:
        req.place = False
        return OMIT
    passage, first, last = place
    req.shown.add("", "passage", passage_lines(passage,
                                               around(passage, first, last)))
    return block_payload(passage, req.shown)


def _value_headings(req, value, spec):
    """The headings up to the value's passage (rule `show_headings`)."""
    place = _place(req, value)
    if place is None or not rules.get("show_headings"):
        return OMIT
    heads = req.plan.headings(place[0].owner)
    if not heads:
        return OMIT
    req.shown.add(letter_headings(), "headings", heads, renumber=True)
    return req.shown.rendered(letter_headings())


def _heading_texts(req, value, spec):
    """The headings up to the value's passage as plain lines (rule
    `show_headings`)."""
    claim = _claim(req, value)
    owner = tuple((claim.get("at") or {}).get("owner") or ())
    if not owner or not rules.get("show_headings"):
        return OMIT
    heads = [line.text for line, _ in req.plan.headings(owner)]
    return heads or OMIT


def _value_passage(req, value, spec):
    """The lines around the value as a block of its passage, shown where
    the value has a passage and None where it has none."""
    from .addressed import block_payload
    claim = _claim(req, value)
    owner = tuple((claim.get("at") or {}).get("owner") or ())
    place = _place(req, value)
    if place is not None:
        passage, first, last = place
        req.shown.add("", "passage", passage_lines(
            passage, around(passage, first, last)))
    if owner not in req.plan.passages:
        return None
    return block_payload(req.plan.passages.get(owner), req.shown)


def _value_plain(req, value, spec):
    """The value as its words and its address, None where it has no
    place."""
    shown = _value(req, value, spec)
    return None if shown is OMIT else shown


def _words_lines(req, value, spec):
    """The value's words and the lines around it, as plain text."""
    claim = _claim(req, value)
    words = str(claim.get("value_raw") or claim.get("value") or "")
    place = _place(req, value)
    lines = []
    if place is not None:
        passage, first, last = place
        lines = [line.text for line, _ in passage_lines(
            passage, around(passage, first, last))]
    return {"words": words, "lines": lines}


def _question(req, value, spec):
    """The question of a dimension, its name where it has none."""
    slot, name = _slot(value)
    if slot is None:
        return OMIT
    return slot.question or name


def _known(req, value, spec):
    """What the value has read so far, in the document's words (rule
    `show_known`)."""
    slot, _name = _slot(value)
    if slot is None or not rules.get("show_known"):
        return OMIT
    known = req.reader.known(_claim(req, value), [slot.name])
    return known or OMIT


def _label(req, value, spec):
    return value.label if hasattr(value, "label") else OMIT


def _description(req, value, spec):
    return getattr(value, "description", None) if hasattr(
        value, "description") else OMIT


def _vocabulary(req, value, spec):
    """The names of a field's list as a document prints them."""
    vocabulary = getattr(value, "vocabulary", None)
    if not vocabulary:
        return OMIT
    return [labels[0] for labels in vocabulary.values() if labels]


def _about_document(req, value, spec):
    """What the document says of itself (its name, its municipality); its
    first line where it says nothing (rule `document_name_fallback`)."""
    plan = req.plan
    context = {key: one for key, one
               in (req.reader.context(plan.document_id) or {}).items()
               if isinstance(one, str) and one.strip()}
    if not context and plan.title_page \
            and rules.get("document_name_fallback"):
        context = {"name": plan.title_page[0][0].text}
    return context or OMIT


def _sentences_before(req, value, spec):
    """The sentences the search of this dimension went with in the rounds
    before, where the step writes a new one knowing them (its "anew" and
    the rule `phrase_new_from_round`)."""
    before = sentences_before(req.ask, value)
    return list(before) if before else OMIT


def sentences_before(ask, coord) -> list:
    """The sentences of the rounds before that a new search sentence is
    written knowing: where the step says "anew", from the round the rule
    `phrase_new_from_round` names."""
    if coord is None or not getattr(coord, "sentences", None):
        return []
    if not ask.setting("anew") \
            or ask.scope.get("round", 1) \
            < rules.get("phrase_new_from_round"):
        return []
    return list(coord.sentences)


def has_place(plan, claim: dict) -> bool:
    """Does the value of *claim* stand in a passage of *plan*?"""
    at = claim.get("at") or {}
    return plan is not None \
        and tuple(at.get("owner") or ()) in plan.passages


def _find_words(req, value, spec):
    return getattr(value, "words", "") if value is not None else OMIT


def _find_lines(req, value, spec):
    """The lines of a find, as plain text; [] where it names none."""
    if value is None:
        return OMIT
    return [line.text for line, _ in getattr(value, "lines", ())]


def _find_lines_if(req, value, spec):
    """The lines of a find, as plain text, where it names any."""
    if value is None or not getattr(value, "lines", None):
        return OMIT
    return [line.text for line, _ in value.lines]


def _find_table(req, value, spec):
    """The title of the table a find stands in, where it names lines of a
    table."""
    if value is None or not getattr(value, "lines", None):
        return OMIT
    passage = getattr(value, "passage", None)
    if passage is None or passage.kind != "table":
        return OMIT
    return passage.title


def _figure_text(req, value, spec):
    """A figure's title and description as its passage gives them: its
    first line, then the rest."""
    if getattr(value, "owner_kind", None) != "figure":
        return OMIT
    lines = (value.text or "").strip().splitlines()
    return {"title": lines[0] if lines else "",
            "description": "\n".join(lines[1:])}


def _picture(req, value, spec):
    """The picture of a figure, sent beside the message and not in it
    (`addressed.PICTURE`), where the run attaches pictures and can read
    this one."""
    if getattr(value, "owner_kind", None) != "figure" or req.reader is None:
        return OMIT
    path = req.reader.image_of(value)
    if not path:
        return OMIT
    from .runner import _image_part
    return path if _image_part(path) is not None else OMIT


def _part_of(made: Callable, part: str) -> Callable:
    """A show of one part of a message whose whole is made by *made(value)*
    (a calculation's, a second reading's, an example's)."""
    def show(req, value, spec):
        if value is None:
            return OMIT
        return made(value)[part]
    return show


def _calculation(value) -> dict:
    from .compute import payload
    return payload(value.question, value.shown, value.fetched)


def _second_reading(value) -> dict:
    from .runner import _review_payload
    return _review_payload(value.row, value.shown, value.parameter,
                           value.slots)


def _draft_field(req, value, spec):
    """A field as the draft of a spec writes it: its name, what it means,
    its type, its units and the entries of its list."""
    from ..compile import examples
    return examples.payload(value or {}, "")["parameter"]


def _always(req, value, spec):
    """The variable as it is, its key always in the message."""
    from .general import view
    return view(value)


# name -> (what the page calls it, what it does, how)
SHOWS: dict = {
    "as_is": ("as it is", "The variable as JSON.", _as_is),
    "always": ("as it is, also where empty", "The variable as JSON; its key "
               "stands in the message also where it is empty.", _always),
    "text": ("as text", "The variable as one text.", _text),
    "field": ("the field and what it means",
              "The name of a field of the Spec and what a value of it is "
              "(rule field_text: in short or whole).", _field),
    "list": ("the field's list",
             "The entries a value of the field is chosen from, numbered, "
             "with what each means where the list is short.", _list),
    "lines": ("numbered lines",
              "A chunk as lines with their numbers, which the answer names; "
              "several chunks each under a letter.", _lines),
    "own_lines": ("a chunk as the request's own lines",
                  "One chunk as lines with their numbers, which the answer "
                  "names; nothing where there are several.", _own_lines),
    "chunks": ("chunks, each under a letter",
               "Chunks each under a letter of their own; with \"several "
               "only\" only where there are several.", _chunks_lettered),
    "next_chunks": ("the next search hits",
                    "The next search hits, as many as a request shows "
                    "(chunks per request): those a reply asked to see "
                    "first, none shown before, each under a letter. Where "
                    "none is left, the request is not made.", _next_chunks),
    "headings": ("the headings above it",
                 "The headings above the chunk's first line (rule "
                 "show_headings).", _headings),
    "title_page": ("the title page",
                   "The first lines of the document's first page (rule "
                   "show_title_page); with \"first request only\" in the "
                   "first request over the search hits.", _title_page),
    "settings": ("what the document settles, as lines",
                 "What holds for every value of the document, as lines an "
                 "answer can name (rule show_settled).", _settings),
    "settings_text": ("what the document settles, as text",
                      "What holds for every value of the document, as plain "
                      "lines (rule show_settled).", _settings_text),
    "facts": ("the facts of the document",
              "What holds for the whole document, as kept so far.", _facts),
    "value": ("the value's words and address",
              "The words of the value and the address of its line.", _value),
    "value_or_none": ("the value's words and address, else empty",
                      "The words of the value and the address of its line; "
                      "empty where it has no place.", _value_plain),
    "value_lines": ("the lines around the value",
                    "The value's line with its table's title and head, or "
                    "the sentences before and after it (rules lines_around, "
                    "rows_around), as lines an answer can name.",
                    _value_lines),
    "value_passage": ("the lines around the value, else empty",
                      "The lines around the value as a block of its "
                      "passage; empty where it has no passage.",
                      _value_passage),
    "value_headings": ("the headings above the value",
                       "The headings up to the value's passage, as lines an "
                       "answer can name (rule show_headings).",
                       _value_headings),
    "heading_texts": ("the headings above the value, as text",
                      "The headings up to the value's passage, as plain "
                      "lines (rule show_headings).", _heading_texts),
    "words_lines": ("the value's words and lines",
                    "The words of the value and the lines around it, as "
                    "plain text.", _words_lines),
    "question": ("the question of the dimension",
                 "What the dimension asks, its name where it asks "
                 "nothing.", _question),
    "known": ("what the value has read",
              "What the value has read so far, in the document's words "
              "(rule show_known).", _known),
    "label": ("the field's name", "The name of the field.", _label),
    "description": ("what the field means", "What a value of the field "
                    "is, as the Spec says.", _description),
    "vocabulary": ("the names of the field's list",
                   "The names a document prints for the entries of the "
                   "field's list.", _vocabulary),
    "about_document": ("what the document says of itself",
                       "Its name and municipality; its first line where it "
                       "says nothing of itself (rule "
                       "document_name_fallback).", _about_document),
    "sentences_before": ("the sentences of the rounds before",
                         "The search sentences this dimension went with "
                         "before, where a new one is written knowing "
                         "them.", _sentences_before),
    "find_words": ("the words of a find", "The words a find names.",
                   _find_words),
    "find_lines": ("the lines of a find",
                   "The lines a find names, as plain text; empty where it "
                   "names none.", _find_lines),
    "find_lines_if": ("the lines of a find, where it names any",
                      "The lines a find names, as plain text, where it "
                      "names any.", _find_lines_if),
    "find_table": ("the title of a find's table",
                   "The title of the table whose lines a find names.",
                   _find_table),
    "figure_text": ("the figure's title and description",
                    "The first line of a figure's passage as its title, the "
                    "rest as its description.", _figure_text),
    "compute_wanted": ("what a calculation wants",
                       "What the question of a calculation wants worked out.",
                       _part_of(_calculation, "wanted")),
    "compute_numbers": ("the numbers of a calculation",
                        "The numbers a calculation starts from, each with "
                        "its id, unit, quote and passage.",
                        _part_of(_calculation, "numbers")),
    "compute_sources": ("the passages of a calculation",
                        "The passages its numbers stand in, each under an "
                        "id.", _part_of(_calculation, "sources")),
    "review_sources": ("the passages of a stored value",
                       "The passage a stored value was read in and the "
                       "section above it, each under an id.",
                       _part_of(_second_reading, "sources")),
    "review_row": ("a stored value",
                   "The value, its quote, its unit and where it stands, as "
                   "the first reading read it.",
                   _part_of(_second_reading, "row")),
    "review_fields": ("the dimensions read again",
                      "The dimensions a second reading asks, each with its "
                      "question and its list.",
                      _part_of(_second_reading, "fields")),
    "draft_field": ("the field as the draft writes it",
                    "A field of a draft spec: its name, what it means, its "
                    "type, its units and the entries of its list.",
                    _draft_field),
    "picture": ("the picture of a figure",
                "The figure's crop, sent beside the message, where the run "
                "attaches pictures; a request whose step needs it is not "
                "made without it.", _picture),
}


def shows_catalogue() -> dict:
    return {name: {"label": label, "says": says}
            for name, (label, says, _how) in SHOWS.items()}


def register(name: str, label: str, says: str, how: Callable) -> None:
    """A show of a profile (`profiles/<name>/blocks.py: SHOWS`)."""
    if name in SHOWS and SHOWS[name][2] is not how:
        raise ValueError(f"the show {name!r} exists already")
    SHOWS[name] = (label, says, how)


def source_of(req: Request, spec: dict):
    """The value an input comes from: the variable it names, or a part of
    it (`general.get`)."""
    from .general import get, raw
    source = str(spec.get("from") or "")
    name, *rest = source.split(".")
    if not name:
        return None
    return raw(req.scope, name) if not rest else get(req.scope, source)


def apart(inputs: list, values: dict) -> dict:
    """The message of a request asked apart from the reading of a
    document, from *values* alone (the sentence a field's chunks are
    ordered by, `runner.document_anchor`): each input as its show says,
    where its condition holds of them."""
    from types import SimpleNamespace
    from . import conditions
    from .engine import Scope
    from .general import PAGE, var_facts
    scope = Scope(None, True, **{PAGE + key: value
                                 for key, value in values.items()})
    req = Request(SimpleNamespace(plan=None, reader=None, scope=scope,
                                  number=lambda key: 0))
    return build(req, inputs,
                 lambda when: conditions.holds(when, var_facts(scope)))


def build(req: Request, inputs: list, holds: Optional[Callable] = None
          ) -> dict:
    """The message of *req*: each input under its key, in their order, as
    its show says; an input whose condition does not hold (*holds(when)*)
    or whose show has nothing is left out. Stops where an input of the
    hits finds nothing left (`Request.used_up`): the hits are taken
    first, before any input is shown."""
    out: dict = {}
    req.payload = out
    if req.batch is None and any(
            isinstance(spec, dict) and spec.get("show") == "next_chunks"
            for spec in inputs or ()):
        if take(req, req.scope.get("supply"),
                req.ask.number("per_request")) is None:
            req.used_up = True
            return out
    for spec in inputs or ():
        if not isinstance(spec, dict):
            continue
        if spec.get("when") is not None and holds is not None \
                and not holds(spec["when"]):
            continue
        how = SHOWS.get(spec.get("show") or "as_is")
        if how is None:
            raise LookupError(f"no show {spec.get('show')!r}")
        part = how[2](req, source_of(req, spec), spec)
        if part is OMIT:
            continue
        out[spec["key"]] = part
    req.payload = out
    return out
