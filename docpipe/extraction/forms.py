"""
forms.py: The forms an answer of "Ask the model" can have (owner decision
2026-11-12 evening, plan "modell_fragen", point 4).

Each form is a JSON schema the request sends as its grammar and an example
answer its prompt shows (`FORMS`): the values a request finds, each with
its line and words; one place or several; the entry of a list; a name of
the document's list or a new one; a search sentence; yes or no; the works
a chunk names; a work, a year of the plan's; or a schema of the step's own.
A form takes what the request showed (`shows.Request`) and what its target
says of the question: whether a dimension takes several entries, whether a
field has a list, whether the answer may ask to see more, whether a figure's
picture may be asked for.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Callable, Optional

from . import addressed, fields
from .units import letter_headings, letter_title_page


def _example_at(req, at: str) -> str:
    """The letter of the lines an example answer names: the request's own
    chunk, else (with "title_page") the title page where it is shown, else
    the first other chunk."""
    if req.own is not None:
        return ""
    if at == "title_page" and letter_title_page() in req.shown.blocks:
        return letter_title_page()
    return req.letters[0] if req.letters else ""


def finds(req, closed: bool = False, more: bool = False,
          at: str = "own") -> tuple:
    """The values a request finds, each an address and its words, and the
    number of its entry where the field has a list (*closed*); an empty list
    where nothing shown holds one; and two example answers, one with a find
    and the empty one."""
    return (addressed.found_format(closed, more=more),
            addressed.find_example(req.shown, closed,
                                   _example_at(req, at)))


def place(req, several: bool = False, more: bool = False,
          image: bool = False) -> tuple:
    """One place and its words, or several, or 0 where no shown line says
    it."""
    return (addressed.coord_format(several, more=more, image=image),
            addressed.Reader.coord_example(req.shown, several))


def entry(req, several: bool = False) -> tuple:
    """The number of a list's entry, 0 for none; several where several may
    be meant."""
    return (addressed.entry_format(several),
            {"entry": [1]} if several else {"entry": 1})


def name(req, several: bool = False, more: bool = False) -> tuple:
    """The number of an entry of the document's list of names, "new" for a
    name not on it yet, 0 for none; several where the words may name
    several."""
    return (addressed.entry_format(several=several, new=True, more=more),
            {"entry": [1]} if several else {"entry": 1})


def phrase(req) -> tuple:
    """A sentence as the document would print what a search looks for."""
    return addressed.phrase_format(), None


def yes_no(req) -> tuple:
    """Whether a place speaks about the value: yes or no."""
    return addressed.about_format(), {"about": "yes"}


def works(req) -> tuple:
    """The lines of a chunk that name other works and the line that shows
    the rest are this publication's own."""
    other, _empty = addressed.find_example(req.shown)
    heads = req.shown.blocks.get(letter_headings())
    own_at = f"{letter_headings()}{len(heads.entries)}" if heads \
        else addressed.first_address(req.shown, False)
    return (addressed.work_format(),
            ({**other, "own": {addressed.address_key(): 0, "words": ""}},
             {"found": [], "own": {**addressed.point(req.shown, False,
                                                     at=own_at),
                                   "words": fields.said()}}))


def work_choice(req) -> tuple:
    """The work of a value as an entry of the document's list of works,
    and the line that shows it."""
    return (addressed.work_choice_format(),
            {"entry": 1, **addressed.point(req.shown, False),
             "words": fields.said()})


def year_choice(req) -> tuple:
    """The line that names the plan's word for a state and the entry of the
    plan's years it means."""
    return (addressed.year_format(),
            {**addressed.point(req.shown, False), "words": fields.said(),
             "entry": 1})


def lines(req) -> tuple:
    """A figure written out: its caption (title, axes, legend) and its
    numbers, each a line (owner decision 2026-11-09); the example begins
    with the figure's title where the request shows one."""
    figure = req.payload.get("figure")
    title = figure.get("title") if isinstance(figure, dict) else ""
    return (addressed.lines_format(),
            {"caption": [title or fields.said(), fields.said()],
             "numbers": [fields.said()]})


def compute(req, labels: tuple = (), more=None, take=None,
            quote: bool = False) -> tuple:
    """A calculation's answer: an action of the sandbox, or the number with
    the numbers it came from (`replies.compute`)."""
    from . import replies
    return addressed._format("compute_reply", replies.compute(
        list(labels), more=more, take=take, quote=quote)), None


def review(req, slots: tuple = ()) -> tuple:
    """A second reading's answer: each dimension asked with its words and
    its quote (`replies.review`)."""
    from . import replies
    return addressed._format("review_reply", replies.review(slots)), None


def example(req, numeric: bool = False) -> tuple:
    """The values a passage holds of a field, proposed as its example
    (`compile.examples.reply_shape`)."""
    from ..compile import examples
    return addressed._format(*examples.reply_shape(numeric)), None


# name -> (what the page calls it, what it is, the shape and example)
FORMS: dict = {
    "finds": ("values with their lines", "Every value the shown lines hold: "
              "the address of its line and its words, and the number of its "
              "entry where the field has a list; an empty list where none.",
              finds),
    "place": ("a place", "The address of the line that says it and its "
              "words, or 0; a list of them where the dimension takes "
              "several.", place),
    "entry": ("an entry of the list", "The number of the entry the words "
              "mean, 0 for none; several where several may be meant.",
              entry),
    "name": ("an entry of the document's list of names",
             "The number of the entry a name means, \"new\" for a name not "
             "on the list yet, 0 for none.", name),
    "phrase": ("a search sentence", "A sentence as the document would print "
               "what the search looks for.", phrase),
    "yes_no": ("yes or no", "\"yes\" where the place speaks about the "
               "value, else \"no\".", yes_no),
    "works": ("the works of a chunk", "The lines that name another work, "
              "each with the name as printed, and the line that shows the "
              "rest are this publication's own, 0 where none does.", works),
    "work_choice": ("a work of the list", "The number of the work in the "
                    "document's list, 0 for none, and the line that shows "
                    "it.", work_choice),
    "year_choice": ("a year of the plan's", "The line that names the plan's "
                    "word for a state, its words, and the number of the year "
                    "of the plan's it means, 0 for none.", year_choice),
    "lines": ("the lines of a figure", "Its caption (title, axes, legend) "
              "and its numbers, each a line.", lines),
    "compute": ("a calculation", "An action of the sandbox (code to run, a "
                "passage to fetch, a number to take), or the number with the "
                "numbers it came from.", compute),
    "review": ("a second reading", "Each dimension asked, with its words and "
               "its quote.", review),
    "example": ("a proposed example", "The values the passage holds of the "
                "field, each with its words and its quote.", example),
}


def register(name_: str, label: str, says: str, how: Callable) -> None:
    """A form of a profile (`profiles/<name>/blocks.py: FORMS`)."""
    if name_ in FORMS and FORMS[name_][2] is not how:
        raise ValueError(f"the form {name_!r} exists already")
    FORMS[name_] = (label, says, how)


def forms_catalogue() -> dict:
    return {key: {"label": label, "says": says}
            for key, (label, says, _how) in FORMS.items()}


def of(reply, req, **options) -> tuple:
    """(shape, example) of the answer form *reply* (a name of `FORMS`, or a
    JSON schema of the step's own) for *req*, with the options its target
    gives (several, closed, more, image)."""
    if isinstance(reply, dict):
        from .general import example_of, schema_with_more
        schema = schema_with_more(reply) if options.get("more") else reply
        return addressed.reply_format(schema), example_of(reply)
    how = FORMS.get(reply)
    if how is None:
        raise LookupError(f"no answer form {reply!r}")
    fn = how[2]
    import inspect
    names = set(inspect.signature(fn).parameters) - {"req"}
    return fn(req, **{key: value for key, value in options.items()
                      if key in names})


def problem(reply) -> Optional[str]:
    """Why *reply* is no answer form, None where it is one."""
    if isinstance(reply, str):
        return None if reply in FORMS else f"no answer form {reply!r}"
    from .general import schema_problem
    return schema_problem(reply)
