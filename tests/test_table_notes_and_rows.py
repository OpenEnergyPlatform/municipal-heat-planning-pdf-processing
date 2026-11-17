"""
A table's notes and the rows an indented row stands under go with its values
(owner decision 2026-11-17, from the literature on reading tables: notes and
exclusions are skipped, a cell needs the whole lineage of its heads).

The promises, each with a case that breaks it by construction:

1. Every chunk of a table and the place of each of its values show every
   line under the table (rule `table_foot_lines` on; owner decision
   2026-11-17: nothing is cut, so no count of them), AND off shows a line
   under a table only in its own chunk.
2. A row whose first cell is indented at least two places under a row above
   it is shown with that row and with the rows that row stands under, in each
   of its chunks and at its value's place, AND a row indented one place more
   (the spacing of a transcription) stands under none, AND with the rule
   `table_parent_rows` off no row is shown with another.
3. A table's title stays its title line where notes are carried.
"""
from docpipe import rules
from docpipe.extraction import units
from docpipe.extraction.pipeline import Source

NOTES = Source("table", 7, "\n".join([
    "Tabelle 4: Endenergie nach Energieträger",
    "| Träger | 2020 | 2030 |",
    "| --- | --- | --- |",
    "| Erdgas | 120 | 98 |",
    "| Heizöl | 40 | 12 |",
    "| Strom | 30 | 35 |",
    "* ohne Industrie",
    "Angaben in GWh/a.",
    "Quelle: eigene Berechnung.",
]), {"page": 3})

ROWS = Source("table", 8, "\n".join([
    "| Bereich | 2020 |",
    "| --- | --- |",
    "| Wohngebäude | 300 |",
    "|   └ Erdgas | 120 |",
    "|   └ Heizöl | 40 |",
    "|      └ davon Brennwert | 25 |",
    "| Gewerbe | 80 |",
    "|  Strom | 30 |",
]), {"page": 3})


def shown(passage, size):
    return [chunk.shown for chunk in units.chunks_of(passage, size)]


def place(passage, number):
    return [line.number for line, _ in units.passage_lines(passage,
                                                            [number])]


def test_the_notes_under_a_table_go_with_every_chunk_and_value_place():
    with rules.overlaid(table_foot_lines=True):
        passage = units.passage_of(NOTES)
    roles = [line.role for line in passage.lines]
    assert roles == ["title", "head", "body", "body", "body", "foot", "foot",
                     "foot"]
    # All three notes, the third ("Quelle: ...") too, go with every chunk.
    assert passage.fixed == (1, 2, 6, 7, 8)
    assert shown(passage, 2) == [(1, 2, 3, 4, 6, 7, 8), (1, 2, 5, 6, 7, 8)]
    assert place(passage, 4) == [1, 2, 4, 6, 7, 8]


def test_no_note_is_carried_where_the_rule_says_none():
    with rules.overlaid(table_foot_lines=False):
        passage = units.passage_of(NOTES)
    assert passage.fixed == (1, 2)
    assert shown(passage, 2)[0] == (1, 2, 3, 4)
    assert 6 not in place(passage, 4)


def test_a_title_stays_the_title_where_notes_are_carried():
    with rules.overlaid(table_foot_lines=True, table_title_lines=False):
        passage = units.passage_of(NOTES)
    assert passage.title == "| Träger | 2020 | 2030 |"
    assert passage.line(passage.fixed[-1]).role == "foot"


def test_an_indented_row_is_shown_with_the_rows_it_stands_under():
    passage = units.passage_of(ROWS)
    assert passage.parents == {3: (2,), 4: (2,), 5: (2, 4)}
    # "davon Brennwert" in a chunk without "Wohngebäude" brings it along,
    # and "Heizöl" over it.
    assert shown(passage, 2) == [(1, 2, 3), (1, 2, 4, 5), (1, 6, 7)]
    assert place(passage, 5) == [1, 2, 4, 5]


def test_a_row_one_place_further_in_stands_under_none():
    passage = units.passage_of(ROWS)
    assert 7 not in passage.parents
    assert units.row_parents(passage.lines).get(7) is None


def test_no_row_is_shown_with_another_where_the_rule_is_off():
    with rules.overlaid(table_parent_rows=False):
        passage = units.passage_of(ROWS)
    assert passage.parents == {}
    assert shown(passage, 2)[1] == (1, 4, 5)
    assert place(passage, 5) == [1, 5]


def test_a_row_with_an_empty_first_cell_keeps_the_rows_above_it():
    rows = units.table_lines("\n".join([
        "| Bereich | 2020 |", "| --- | --- |", "| Wohngebäude | 300 |",
        "|   └ Erdgas | 120 |", "|  | 7 |", "|   └ Heizöl | 40 |"]))[0]
    assert units.row_parents(rows) == {3: (2,), 5: (2,)}
