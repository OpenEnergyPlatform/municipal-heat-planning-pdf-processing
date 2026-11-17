"""
Nothing the addressed reading shows is cut (owner decision 2026-11-17: "Nichts
kürzen, einfach ggf. clever aufteilen und darauf achten, dass die Zuordnung
zu Sektion und Seite etc. nicht verlieren gehen"), each promise with a case
that breaks it by construction.

1. A table cell that prints several numbers gives one item to ask for each
   number, all with the address of the cell.
2. The title page is every line of the first page, however many it has, AND
   a first page that has no lines gives the page the rule names.
3. The headings of a request are every heading up to its place in reading
   order, AND the nearest is the last, however many there are.
4. A list is shown with every entry and what each means, however long it is
   and whatever its groups, in one request where it fits the window.
5. A list that does not fit the window is asked in parts, AND every entry
   stands in a part with its meaning and its number in the whole list, AND no
   part is longer than the window leaves room for.
6. The answers of the parts are put together: none named is none, one named
   is that one, several named are asked once more over those entries with
   what they mean and their numbers in the whole list.
7. An entry whose meaning alone does not fit is split at its sentences, AND
   every sentence of it is shown in a part.
8. The numbers of the flow that cut these are gone: the lines of the title
   page, the headings shown and the entries shown with a meaning.
"""
import dataclasses
import json
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import addressed, fields, flow, runner
from docpipe.extraction.addressed import Source

from test_addressed import TABLE, TEXT, Model, plan_of, reader_of


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


# -- 1. the numbers of a cell ---------------------------------------------------

def test_every_number_a_cell_prints_is_an_item_to_ask():
    plan = plan_of(TABLE, TEXT)
    items = addressed.untaken_items(plan, [])
    schule = [item for item in items if "Schule" in item.text]
    # "800 / 750" is cell 2 of the row: two items of one address, then 12.
    assert [(item.cell, item.words) for item in schule] \
        == [(2, "800"), (2, "750"), (3, "12")]
    assert len({item.line for item in schule}) == 1
    # the failure by construction: a value that took the cell takes both
    line = schule[0].line
    taken = addressed.untaken_items(plan, [
        {"at": {"owner": ["table", 3], "line": line, "cell": 2}}])
    assert [item.words for item in taken if item.line == line] == ["12"]


# -- 2. the title page --------------------------------------------------------------

def test_the_title_page_is_every_line_of_the_first_page():
    lines = "\n".join(f"Zeile {i} der Titelseite." for i in range(1, 41))
    first = Source("section", 1, lines, {"document_id": 7, "page": 1})
    later = Source("section", 2, "Spaeter.", {"document_id": 7, "page": 2})
    plan = plan_of(first, later)
    # forty lines: more than the twelve the page was cut to before
    assert len(plan.title_page) == 40
    assert [line.text for line, _ in plan.title_page] \
        == [f"Zeile {i} der Titelseite." for i in range(1, 41)]
    # the failure by construction: a page the rule names is no first page
    # while the first has lines
    with rules.overlaid(title_page_first=2):
        assert len(plan_of(first, later).title_page) == 1


# -- 3. the headings ----------------------------------------------------------------

def test_the_headings_are_all_of_them_up_to_the_place_the_nearest_last():
    sources = [Source("section", 10 + i, f"Text {i}.",
                      {"document_id": 7, "page": 1 + i,
                       "section_title": f"Titel {i}"}) for i in range(30)]
    plan = plan_of(*sources)
    heads = plan.headings(("section", 10 + 29))
    assert [line.text for line, _ in heads] \
        == [f"Titel {i}" for i in range(30)]
    # the failure by construction: a place in the middle has the headings
    # before it only, not those after
    middle = plan.headings(("section", 10 + 14))
    assert [line.text for line, _ in middle][-1] == "Titel 14"
    assert len(middle) == 15


# -- lists ----------------------------------------------------------------------------

def sector_list(count: int, sentences: int = 1):
    return SimpleNamespace(
        name="sector", question="Welcher Sektor?", options=tuple(
            fields.Option(
                label=f"Sektor {i}", uri=f"S{i}",
                definition=" ".join(
                    f"Der Sektor {i} umfasst Anlage {k} und mehr."
                    for k in range(sentences)),
                group="A" if i % 2 else "B") for i in range(1, count + 1)))


def values_of(slot, words):
    return {"words": words, "find": None,
            "dimension": SimpleNamespace(slot=slot, name="sector")}


def window_of(monkeypatch, reader, plan, slot, lines: float):
    """The window a request over *lines* entries of *slot* fills: the
    model window is set to the frame of a list request and the room of that
    many entries."""
    monkeypatch.setattr(runner, "model_window", lambda: 10 ** 6)
    wide = reader.list_window(plan, values_of(slot, "x"), None, [])
    shown = reader.list_of(slot.options)[0]
    # What a counted text costs beside its lines (its message), once, and
    # what each line adds: the room is that of *lines* lines.
    empty = wide.count(json.dumps([], ensure_ascii=False, indent=1))
    most = max(wide.count(json.dumps([line], ensure_ascii=False, indent=1))
               - empty for line in shown)
    limit = wide.frame + empty + int(lines * most)
    monkeypatch.setattr(runner, "model_window", lambda: limit)
    return reader.list_window(plan, values_of(slot, "x"), None, [])


def asked_lists(model) -> list:
    return [payload["list"] for payload, _ in model.of("list")]


def number_of(line: str) -> int:
    return int(line.split(" ", 1)[0])


def test_a_list_is_shown_whole_with_every_meaning_in_one_request():
    slot = sector_list(100)
    model = Model(list=lambda p, n: {"entry": 77})
    got = reader_of(model).entry(plan_of(TEXT), "u", "sector", slot,
                                 "Sektor 77", None, addressed.Counts())
    (shown,) = asked_lists(model)
    assert got == "Sektor 77" and len(shown) == 100
    assert all("(means: Der Sektor " in line for line in shown)
    assert [number_of(line) for line in shown] == list(range(1, 101))
    # the lines of a list with groups are the entries, never the groups
    lines, _choices, grouped = addressed.listing(slot.options)
    assert lines == shown and not grouped


def test_a_list_over_the_window_is_asked_in_parts_with_their_numbers(
        monkeypatch):
    slot = sector_list(60)
    plan = plan_of(TEXT)
    model = Model(list=lambda p, n: {
        "entry": 47 if any(number_of(line) == 47 for line in p["list"])
        else 0})
    reader = reader_of(model)
    room = window_of(monkeypatch, reader, plan, slot, 9)
    got = reader.entry(plan, "u", "sector", slot, "Sektor 47", None,
                       addressed.Counts())
    parts = asked_lists(model)
    # one entry named by one part: that one, with no request more
    assert got == "Sektor 47" and len(parts) >= 5
    # every entry of the list is in exactly one part, with its meaning and
    # the number it has in the whole list
    shown = [line for part in parts for line in part]
    assert sorted(number_of(line) for line in shown) == list(range(1, 61))
    assert all(f"(means: Der Sektor {number_of(line)} umfasst" in line
               for line in shown)
    # no part is longer than the room the window leaves
    for part in parts:
        assert room.fits(json.dumps(part, ensure_ascii=False, indent=1))
    # the failure by construction: the whole list does not fit that window
    assert not room.fits(json.dumps(
        reader.list_of(slot.options)[0], ensure_ascii=False, indent=1))


def test_no_part_names_an_entry_is_none_and_several_are_asked_once_more(
        monkeypatch):
    slot = sector_list(60)
    plan = plan_of(TEXT)
    model = Model(list=lambda p, n: {"entry": 0})
    reader = reader_of(model)
    window_of(monkeypatch, reader, plan, slot, 9)
    none = reader.entry(plan, "u", "sector", slot, "Nichts", None,
                        addressed.Counts())
    asked = asked_lists(model)
    assert none == "" and len(asked) >= 5
    # several parts name an entry: the first of its lines each, then one
    # more request over those, their numbers kept, with what they mean
    model = Model(list=lambda p, n: {"entry": number_of(p["list"][0])})
    reader = reader_of(model)
    plan = plan_of(TEXT)
    window_of(monkeypatch, reader, plan, slot, 9)
    got = reader.entry(plan, "u", "sector", slot, "Mehrere", None,
                       addressed.Counts())
    parts = asked_lists(model)
    final = parts[-1]
    firsts = [number_of(part[0]) for part in parts[:-1]]
    assert [number_of(line) for line in final] == firsts
    assert 2 <= len(final) < 60 and len(parts) == len(firsts) + 1
    assert all(f"(means: Der Sektor {number_of(line)} umfasst" in line
               for line in final)
    assert got == f"Sektor {firsts[0]}"


def test_an_entry_whose_meaning_does_not_fit_is_split_at_its_sentences(
        monkeypatch):
    slot = sector_list(6, sentences=40)
    plan = plan_of(TEXT)
    model = Model(list=lambda p, n: {"entry": 0})
    reader = reader_of(model)
    window_of(monkeypatch, reader, plan, slot, 0.3)
    reader.entry(plan, "u", "sector", slot, "Sektor 3", None,
                 addressed.Counts())
    shown = " ".join(line for part in asked_lists(model) for line in part)
    # every sentence of every meaning is in some part
    for i in range(1, 7):
        for k in range(40):
            assert f"Der Sektor {i} umfasst Anlage {k} und mehr." in shown
    # and every part names its entry by its number in the list
    assert all(number_of(line) in range(1, 7)
               for part in asked_lists(model) for line in part)


# -- 8. the numbers that cut are gone ----------------------------------------------

def test_the_numbers_that_cut_are_no_numbers_of_the_flow():
    for name in ("title_page_lines", "headings", "list_meanings"):
        assert name not in flow.BY_NAME
        assert name not in {f.name for f in
                            dataclasses.fields(flow.Numbers)}
        assert name not in flow.default().as_dict()


# -- 9. a fragment of a split entry says which entry it is ---------------------------

def unnamed_list(count: int, sentences: int):
    """A list whose definitions never repeat the name of their entry: a
    fragment names it only where it is given its label."""
    return SimpleNamespace(
        name="sector", question="Welcher Sektor?", options=tuple(
            fields.Option(
                label=f"Sektor {i}", uri=f"S{i}",
                definition=" ".join(f"Er umfasst Anlage {k} und mehr."
                                    for k in range(sentences)),
                group="A" if i % 2 else "B") for i in range(1, count + 1)))


def test_every_fragment_of_a_split_entry_names_its_entry(monkeypatch):
    slot = unnamed_list(3, sentences=40)
    plan = plan_of(TEXT)
    model = Model(list=lambda p, n: {"entry": 0})
    reader = reader_of(model)
    room = window_of(monkeypatch, reader, plan, slot, 0.3)
    reader.entry(plan, "u", "sector", slot, "Sektor 3", None,
                 addressed.Counts())
    lines = [line for part in asked_lists(model) for line in part]
    fragments = [line for line in lines if number_of(line) == 3]
    assert len(fragments) >= 3
    # each fragment names the entry, not only the first one: the first by
    # its own words, every later one by the label in front of it
    assert all(line.startswith("3 Sektor 3") for line in fragments)
    assert sum("(continued)" in line for line in fragments) \
        == len(fragments) - 1
    # the label counts in the room: every part fits what was measured
    assert all(room.fits(json.dumps(part, ensure_ascii=False, indent=1))
               for part in asked_lists(model))


def test_a_list_whose_line_cannot_be_split_to_fit_ends_that_question(
        monkeypatch):
    slot = sector_list(2)
    plan = plan_of(TEXT)
    model = Model(list=lambda p, n: {"entry": 1})
    reader = reader_of(model)
    monkeypatch.setattr(reader, "list_window", lambda *a, **k:
                        SimpleNamespace(fits=lambda text: False))
    counts = addressed.Counts()
    got = reader.entry(plan, "u", "sector", slot, "Sektor 1", None, counts)
    # no request went out, the question ended with the existing reason,
    # and nothing escaped
    assert got == "" and asked_lists(model) == []
    assert counts.failed["too_long"] == 1


# -- 10. measuring records nothing, and takes nothing back ---------------------------

def test_measuring_keeps_the_marks_other_threads_set():
    import threading
    plan = plan_of(TEXT)
    step = SimpleNamespace(ident="step-b")
    inside, done = threading.Event(), threading.Event()
    seen = {}

    def other():
        token = rules.STEP.set(step)
        try:
            inside.wait(5)
            seen["first"] = plan.first_request()
            done.set()
        finally:
            rules.STEP.reset(token)

    thread = threading.Thread(target=other)
    thread.start()
    with plan.measuring():
        assert plan.first_request() is True       # measuring records nothing
        assert plan.first_request() is True
        inside.set()
        done.wait(5)
    thread.join()
    assert seen["first"] is True
    # the other thread's mark survives the end of the measuring
    token = rules.STEP.set(step)
    try:
        assert plan.first_request() is False
    finally:
        rules.STEP.reset(token)
    # and what was only measured was never recorded
    assert plan.first_request() is True
