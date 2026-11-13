"""A table reply gives the table's lines as a list, which the code joins with
line breaks (owner decision 2026-11-11): the model never writes a line break
inside a JSON string, and a reply that gives the table as one string is asked
again instead of taken. A figure's and a page's reply stay text."""
import json
from types import SimpleNamespace

from docpipe import reading
from docpipe.visuals import process, replies
from docpipe.visuals.vision import reply_type

LINES = ["| Energy carrier | Share (%) |", "| --- | --- |", "| Coal | 45.2 |"]


def choice(obj: dict):
    return SimpleNamespace(message=SimpleNamespace(content=json.dumps(obj),
                                                   reasoning_content=None),
                           finish_reason="stop")


def test_table_lines_are_joined_by_the_code():
    found, cause, _said = reading.read(choice({"rows": LINES, "caption": None}),
                                       key="rows", of=reply_type(replies.TABLE))
    assert cause == ""
    assert process._table_text(found) == "\n".join(LINES)


def test_table_as_one_string_is_asked_again():
    one_line = " ".join(LINES)
    found, cause, said = reading.read(choice({"rows": one_line}), key="rows",
                                      of=reply_type(replies.TABLE))
    assert found is None and cause == "missing_key" and said


def test_continued_table_reads_lines_too_figure_and_page_read_text():
    assert reply_type(replies.TABLE_CONTINUED) is list
    assert reply_type(replies.FIGURE) is str
    assert reply_type(replies.PAGE) is str
