"""A plan's passages as numbered lines in pieces of at most eight (owner
decisions 2026-11-08, plan of 2026-11-09, tests 1 to 3), each promise with a
case that breaks it by construction.

1. Every line of a piece has exactly one address, AND an address shows the
   same text in every request that shows it, AND a piece of a table shows
   its title and head under the same numbers as every other piece of it.
2. No piece has more than eight own lines: a table of twenty rows is three
   pieces.
3. A sentence is cut at line ends and sentence ends, never inside "1.155
   MWh", after "z. B.", "S. 12", "et al." or an ordinal.
4. A line that "|" divides has cells wherever it stands, AND a figure is
   its caption for a field of words and its numbers for a field of
   numbers (plan of 2026-11-09, tests 1 and 2).
"""
from docpipe.extraction.pipeline import Source
from docpipe.extraction.units import (Shown, address_of, chunks_of,
                                      own_lines, passage_of, pieces_for,
                                      sentences_of)


def table(rows: int) -> Source:
    body = "\n".join(f"| Gebäude {i} | {1000 + i} |" for i in range(1, rows + 1))
    return Source("table", 7, "Tabelle 4: Verbrauch der Liegenschaften\n"
                              "| Gebäude | MWh/a |\n| --- | --- |\n" + body)


def shown_numbers(chunk) -> list:
    shown = Shown()
    shown.add("", "passage", own_lines(chunk))
    return [(number, line.text) for number, line, _ in
            shown.blocks[""].entries]


def test_every_line_of_a_piece_has_one_address_and_keeps_it_everywhere():
    passage = passage_of(table(20))
    pieces = chunks_of(passage, 8)
    texts: dict = {}
    for piece in pieces:
        numbers = [number for number, _ in shown_numbers(piece)]
        assert len(numbers) == len(set(numbers))
        for number, text in shown_numbers(piece):
            assert texts.setdefault(number, text) == text
    # Title and head stand in every piece under the same numbers.
    heads = [shown_numbers(piece)[:2] for piece in pieces]
    assert all(head == heads[0] for head in heads)
    assert heads[0] == [(1, "Tabelle 4: Verbrauch der Liegenschaften"),
                        (2, "| Gebäude | MWh/a |")]
    # the failure by construction: two equal rows are two lines, each with
    # an address of its own that names it alone.
    twice = passage_of(Source("table", 8, "| A | B |\n| --- | --- |\n"
                                          "| x | 1 |\n| x | 1 |"))
    piece = chunks_of(twice, 8)[0]
    shown = Shown()
    shown.add("", "passage", own_lines(piece))
    assert [n for n, _, _ in shown.blocks[""].entries] == [1, 2, 3]
    assert shown.find(address_of("2")) != shown.find(address_of("3"))


def test_a_table_without_its_head_rule_has_no_head():
    # the failure by construction of the head: without the rule under it no
    # line is a head, and a piece has no fixed lines to repeat; its lines
    # keep their cells, as every line that "|" divides does (owner decision
    # 2026-11-09).
    passage = passage_of(Source("table", 9, "| A | B |\n| x | 1 |"))
    assert passage.fixed == ()
    assert all(line.role != "head" for line in passage.lines)
    assert [len(line.cells) for line in passage.lines] == [2, 2]


def test_no_piece_has_more_than_eight_own_lines():
    passage = passage_of(table(20))
    pieces = chunks_of(passage, 8)
    assert len(pieces) == 3
    assert [len(piece.numbers) for piece in pieces] == [8, 8, 4]
    text = " ".join(f"Satz {i} endet hier." for i in range(1, 18))
    assert [len(p.numbers) for p in chunks_of(
        passage_of(Source("section", 3, text)), 8)] == [8, 8, 1]


def test_the_sentence_splitter_keeps_numbers_and_abbreviations():
    text = ("Der Verbrauch lag bei 1.155 MWh im Jahr. Siehe z. B. Tab. 3 "
            "auf S. 12 und Müller et al. für den 3. Oktober. Ende.\n"
            "Eine neue Zeile")
    assert sentences_of(text) == [
        "Der Verbrauch lag bei 1.155 MWh im Jahr.",
        "Siehe z. B. Tab. 3 auf S. 12 und Müller et al. für den 3. Oktober.",
        "Ende.", "Eine neue Zeile"]
    # the failure by construction: a sentence end is cut.
    assert sentences_of("Erster Satz. Zweiter Satz.") == [
        "Erster Satz.", "Zweiter Satz."]


def test_an_address_names_a_line_a_cell_or_a_stretch_and_0_none():
    assert address_of("19.5").cell == 5
    assert address_of("A3-A5").last == 5 and address_of("A3-A5").letter == "A"
    assert address_of("12-14").last == 14
    assert address_of(0) is None and address_of("0") is None
    assert address_of("A3-B5") is None and address_of("19.5-20") is None


def test_a_line_that_bars_divide_has_cells_wherever_it_stands():
    """A line of a figure that "|" divides has cells as a table row has
    (owner decision 2026-11-09): its third cell is an address, AND a fourth
    it does not have is none, AND a table row reads as before."""
    from docpipe.extraction import addressed
    figure = Source("figure", 5, "Abbildung 2", {"document_id": 7, "page": 3})
    numbers = [f"{2000 + i} | Erdgas | {100 + i}" for i in range(24)] \
        + ["2026 | Heizöl | 11"]
    passage = passage_of(figure, {"caption": ["Abbildung 2: Verbrauch"],
                                  "numbers": numbers})
    piece = next(c for c in chunks_of(passage, 8) if 26 in c.numbers)
    shown = Shown()
    shown.add("", "passage", own_lines(piece))
    passages = {passage.owner: passage}
    got = addressed.resolve(shown, {"at": "26.3", "words": "11"}, passages)
    assert got.why is None and got.cell == 3 and got.words == "11"
    # the failure by construction: a cell the line does not have
    assert addressed.resolve(shown, {"at": "26.4", "words": "11"},
                             passages).why == addressed.NOT_AN_ADDRESS
    rows = passage_of(table(3))
    shown = Shown()
    shown.add("", "passage", own_lines(chunks_of(rows, 8)[0]))
    got = addressed.resolve(shown, {"at": "4.2", "words": "1002"},
                            {rows.owner: rows})
    assert got.why is None and got.cell == 2


def test_a_figure_is_its_caption_for_words_and_its_numbers_for_numbers():
    """A figure is one piece of its caption for a field of words, AND pieces
    of its numbers, each shown with the caption, for a field of numbers
    (owner decision 2026-11-09)."""
    figure = Source("figure", 5, "Abbildung 3", {"document_id": 7, "page": 4})
    caption = ["Abbildung 3: Wärmebedarf nach Energieträger",
               "x-Achse: Jahr; y-Achse: GWh", "Legende: Erdgas, Heizöl"]
    numbers = [f"{2000 + i} | Erdgas | {100 + i} GWh" for i in range(20)]
    pieces = chunks_of(passage_of(figure, {"caption": caption,
                                           "numbers": numbers}), 8)
    (words,) = pieces_for(pieces, False)
    assert [line.text for line in words.lines()] == caption
    counted = pieces_for(pieces, True)
    assert len(counted) == 3
    assert all([line.text for line in piece.lines()][:3] == caption
               for piece in counted)
    # the failure by construction: a figure without numbers is the same
    # piece for both
    bare = chunks_of(passage_of(figure, {"caption": caption, "numbers": []}),
                     8)
    assert pieces_for(bare, False) == pieces_for(bare, True) == bare
