"""A scenario document some of whose pages a model read, because the PDF had
no text there, has every value graded as a reading of a reading (reason
page_transcribed, at best level B), as kwp grades its plans; a document whose
pages the PDF printed, or nobody looked at, has its values graded on their
own; and a database that cannot be opened stops the graph instead of reading
as one without such documents."""
import sqlite3

import pytest

from profiles.scenarios import kg
from test_graph_from_shapes import make_serializer, oekg


def database(tmp_path, transcribed: dict):
    path = tmp_path / "scenarios.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE Documents (id INTEGER PRIMARY KEY, "
                 "filename TEXT, page_text_transcribed INTEGER)")
    conn.executemany("INSERT INTO Documents (filename, page_text_transcribed) "
                     "VALUES (?, ?)",
                     [(f"{name}.pdf", pages) for name, pages in transcribed.items()])
    conn.commit()
    conn.close()
    return path


def rows(title):
    return [{"parameter": "publication_title", "value": title,
             "quote": title, "tier": "text_located"},
            {"parameter": "publication_author", "value": "Ada Lovelace",
             "quote": "Ada Lovelace", "tier": "text_located"}]


def levels(text):
    return {line.split("confidence:")[1].split()[0].strip(";,")
            for line in text.splitlines() if "confidence:" in line}


def test_a_document_with_pages_a_model_read_is_graded_at_best_b(tmp_path):
    db = database(tmp_path, {"read": 3, "printed": 0, "unlooked": None})
    serializer = make_serializer(db, model=oekg())
    read = serializer("read", rows("A Read Study"))
    printed = serializer("printed", rows("A Printed Study"))
    unlooked = serializer("unlooked", rows("An Unlooked Study"))
    assert levels(read) == {"B"} and "page_transcribed" in read
    assert levels(printed) == {"A"} and "page_transcribed" not in printed
    assert levels(unlooked) == {"A"} and "page_transcribed" not in unlooked


def test_a_database_that_cannot_be_opened_stops_the_graph(tmp_path):
    with pytest.raises(sqlite3.Error):
        kg.make_serializer(tmp_path / "missing" / "scenarios.db", model=oekg())
