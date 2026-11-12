"""
What a request shows, how a document is cut into chunks, how an answer is
taken and how a request that did not fit is split are rules, each read where
it is used (owner 2026-11-11: "alles soll anpassbar sein").

The promise: the value of the rule decides, read at the time of use, AND
today's standard gives today's result. Each case sets a rule at a step
(`rules.in_step`) or for the run (`rules.overlaid`) and sees the code do
what the value says, with the standard as the control.
"""
import time

import pytest

from docpipe import rules
from docpipe.extraction import addressed, units
from docpipe.extraction.addressed import (Asking, Counts, Found, Names,
                                          Reader, Shown, budgeted, number_of)
from docpipe.extraction.pipeline import Row, Source
from docpipe.extraction.units import Line, TooManyPlaces

from test_addressed import (ENERGY, SLOTS, TABLE, TEXT, TITLE, Model,
                            plan_of, reader_of)


def at(kind: str, values: dict):
    """What the engine does around a box of *kind* that sets *values*."""
    return rules.in_step(rules.stepped({"id": "x", "box": kind}, values))


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def find_payloads(model: Model, values: dict) -> list:
    plan = plan_of(TITLE, TEXT, TABLE)
    reader = reader_of(model)
    chunk = next(c for c in plan.chunks if c.passage.kind == "table")
    with at("find", values):
        reader.find(plan, ENERGY, chunk, Counts())
    return [payload for payload, _ in model.of("find")]


# -- what a request shows -----------------------------------------------------


def test_the_title_page_is_shown_as_the_step_says_and_by_the_standard():
    (standard,) = find_payloads(Model(), {})
    assert "title_page" in standard                      # the standard
    (never,) = find_payloads(Model(), {"show_title_page": "never"})
    assert "title_page" not in never
    # the control: only the title page differs
    assert {k: v for k, v in standard.items() if k != "title_page"} == never


def test_headings_are_shown_as_the_step_says():
    (shown,) = find_payloads(Model(), {})
    (hidden,) = find_payloads(Model(), {"show_headings": False})
    assert "headings" in shown and "headings" not in hidden


def test_a_title_page_shown_for_the_first_request_only_is_shown_once():
    plan = plan_of(TITLE, TEXT, TABLE)
    model = Model()
    reader = reader_of(model)
    with at("find", {"show_title_page": "first"}):
        for chunk in plan.chunks[:2]:
            reader.find(plan, ENERGY, chunk, Counts())
    first, second = [p for p, _ in model.of("find")]
    assert "title_page" in first and "title_page" not in second


def test_a_table_is_shown_with_the_title_and_head_the_rules_say():
    def lines(values):
        (payload,) = find_payloads(Model(), values)
        return payload["passage"]["lines"]
    assert lines({})[0].startswith("1 Tabelle 4")
    assert lines({"show_table_title": False})[0].startswith("2 | Geb")
    assert not any("Geb" in line for line in
                   lines({"show_table_head": False}))


def test_a_value_in_a_table_is_shown_the_rows_around_it_as_the_rule_says():
    plan = plan_of(TITLE, TEXT, TABLE)
    claim = {"at": {"owner": ["table", 3], "line": 3}, "value": 1}
    _shown, none = addressed.show_value(plan, claim)
    assert len(none["passage"]["lines"]) == 3            # title, head, row
    with rules.overlaid(rows_around=1):
        _shown, more = addressed.show_value(plan, claim)
    assert len(more["passage"]["lines"]) == 4            # and the row after


def test_the_blocks_of_a_place_stand_in_the_order_the_rule_says():
    plan = plan_of(TITLE, TEXT, TABLE)
    plan.settings = [(Line(1, "Alle Werte gelten für 2021."), TEXT)]
    claim = {"at": {"owner": ["section", 2], "line": 2}, "value": 1}
    _shown, usual = addressed.show_value(plan, claim)
    assert list(usual) == ["value", "passage", "headings", "title_page",
                           "settings"]
    with rules.overlaid(shown_block_order=["settings", "passage"]):
        _shown, other = addressed.show_value(plan, claim)
    assert list(other) == ["value", "settings", "passage", "headings",
                           "title_page"]


def test_the_examples_of_a_request_are_shown_as_the_rules_say():
    pair = ({"found": [{"at": "1", "words": "x"}]}, {"found": []})
    assert addressed.shown_example(pair) == pair
    with rules.overlaid(show_empty_example=False):
        assert addressed.shown_example(pair) == (pair[0],)
    with rules.overlaid(show_example=False):
        assert addressed.shown_example(pair) == ()
        assert addressed.shown_example(None) is None


def test_the_field_is_shown_short_or_whole_as_the_rule_says():
    class Parameter:
        label, description, brief = "Energy", "A long description.", "Short."
    assert addressed.field_shown(Parameter())["means"] == "Short."
    with rules.overlaid(field_text="whole"):
        assert addressed.field_shown(Parameter())["means"] \
            == "A long description."


def test_the_page_and_title_of_a_chunk_are_shown_as_the_rules_say():
    plan = plan_of(TITLE, TEXT, TABLE)
    table = plan.passages[("table", 3)]
    shown = Shown()
    shown.add("", "passage", units.own_lines(plan.chunks[-1]))
    both = addressed.block_payload(table, shown)
    assert both["page"] == 3 and both["title"].startswith("Tabelle 4")
    with rules.overlaid(show_passage_page=False, show_passage_title=False):
        none = addressed.block_payload(table, shown)
    assert "page" not in none and "title" not in none


def test_the_sentence_request_shows_the_parts_the_rule_names():
    def payload_with(values):
        model = Model()
        plan = plan_of(TITLE, TEXT, TABLE)
        row = Row("v", 0, {"at": {"owner": ["section", 2], "line": 2},
                        "value": 300, "value_raw": "300 MWh"})
        reader = reader_of(model, context=lambda d: {"name": "Musterstadt"})
        read = type("R", (), {"batch": type("B", (), {"parameter": ENERGY})})
        with at("phrase", values):
            reader.sentence(plan, read, row, SLOTS["year"], Counts())
        (payload, _), = model.of("phrase")
        return payload
    assert {"label", "headings", "document"} <= set(payload_with({}))
    narrow = payload_with({"phrase_shows": ["label", "question", "value"]})
    assert set(narrow) == {"label", "question", "value"}
    assert "headings" not in payload_with({"show_headings": False})


# -- cutting ------------------------------------------------------------------


def test_a_line_is_split_before_a_list_mark_as_the_rules_say():
    text = "Maßnahmen: • Dämmen • Heizen"
    assert units.sentences_of(text) == ["Maßnahmen:", "• Dämmen", "• Heizen"]
    with rules.overlaid(split_bullets=False):
        assert units.sentences_of(text) == [text]
    with rules.overlaid(bullet_marks="▪"):
        assert units.sentences_of(text) == [text]


def test_a_point_after_an_ordinal_ends_no_sentence_up_to_the_digits_ruled():
    text = "Am 3. Oktober war es so. Dann 1234. Neu."
    standard = units.sentences_of(text)
    assert standard[0] == "Am 3. Oktober war es so."
    with rules.overlaid(split_ordinals=True):
        assert units.sentences_of(text)[0] == "Am 3."
    with rules.overlaid(ordinal_max_digits=4):
        assert units.sentences_of(text) != standard      # "1234." too


def test_the_look_ahead_for_an_abbreviation_of_two_parts_is_the_rule_s():
    text = "Das gilt z. B. für alle Häuser."
    assert units.sentences_of(text) == [text]
    with rules.overlaid(abbreviation_lookahead_chars=1):
        assert units.sentences_of(text) != [text]


def test_a_line_with_a_bar_has_cells_only_where_the_rule_says():
    assert units.line_cells("26 JRC | Other | 11") == ("26 JRC", "Other", "11")
    with rules.overlaid(cells_by_bar=False):
        assert units.line_cells("26 JRC | Other | 11") == ()


def test_a_table_is_its_title_head_and_rule_lines_as_the_rules_say():
    def roles(**values):
        with rules.overlaid(**values):
            lines, _ = units.table_lines(TABLE.text)
        return [line.role for line in lines]
    assert roles() == ["title", "head", "body", "body"]
    assert roles(table_title_lines=False) == ["head", "body", "body"]
    assert roles(table_head_lines=False) == ["title", "body", "body"]
    assert roles(table_rule_line=True) == ["title", "head", "rule", "body",
                                           "body"]


def test_a_column_head_comes_from_a_head_line_of_the_width_the_rule_says():
    table = Source("table", 9, "T\n| A | B | C |\n| --- | --- | --- |\n"
                                "| 1 | 2 | 3 |", {"page": 1})
    passage = units.passage_of(table)
    assert passage.head_of(1) == "A"
    wide = Source("table", 9, "| Over | |\n| A | B |\n| --- | --- |\n"
                              "| 1 | 2 |", {"page": 1})
    passage = units.passage_of(wide)
    assert passage.head_of(1) == "Over / A"
    narrow = Source("table", 9, "| Over |\n| A | B |\n| --- | --- |\n"
                                "| 1 | 2 |", {"page": 1})
    passage = units.passage_of(narrow)
    assert passage.head_of(1) == "A"                     # width 1 is out
    with rules.overlaid(head_only_full_width=False):
        assert passage.head_of(1) == "Over / A"


def test_the_title_page_is_the_page_and_the_figures_the_rules_say():
    one = Source("section", 1, "Eins. Zwei.", {"page": 1})
    two = Source("section", 2, "Zwei hier.", {"page": 2})
    figure = Source("figure", 3, "Abbildung eins.", {"page": 1})
    passages = [units.passage_of(s) for s in (figure, one, two)]
    texts = lambda lines: [line.text for line, _ in lines]  # noqa: E731
    assert texts(units.title_page_of(passages, 5)) == ["Eins.", "Zwei."]
    with rules.overlaid(title_page_with_figures=True):
        assert texts(units.title_page_of(passages, 5))[0] == "Abbildung eins."
    with rules.overlaid(title_page_first=2):
        assert texts(units.title_page_of(passages, 5)) == ["Zwei hier."]


def test_a_figure_is_read_in_the_pieces_the_rule_says():
    figure = Source("figure", 5, "x", {"page": 1})
    plan = plan_of(TITLE, figure)
    plan.passages[("figure", 5)] = units.passage_of(
        figure, {"caption": ["Abbildung"], "numbers": ["A: 1", "B: 2"]})
    plan = addressed.Plan(7, [TITLE, figure],
                          {5: {"caption": ["Abbildung"],
                               "numbers": ["A: 1", "B: 2"]}})
    kinds = lambda numbers: [c.of_numbers for c in plan.pieces(numbers)  # noqa
                             if c.passage.kind == "figure"]
    assert kinds(True) == [True] and kinds(False) == [False]
    with rules.overlaid(figure_part="caption"):
        assert kinds(True) == [False]
    with rules.overlaid(figure_part="numbers"):
        assert kinds(False) == [True]


def test_more_places_than_letters_is_refused_with_its_reason():
    shown = Shown()
    with rules.overlaid(letters_others="A"):
        shown.add("A", "A", [(Line(1, "x"), TEXT)])
        with pytest.raises(TooManyPlaces, match="letters_others"):
            shown.letter_for(("table", 3))


# -- a request that did not fit ---------------------------------------------


BIG = Source("table", 8, "Tabelle 9: Verbrauch\n| Gebäude | Erdgas |\n"
                         "| --- | --- |\n| A | 1 |\n| B | 2 |\n| C | 3 |\n"
                         "| D | 4 |", {"document_id": 7, "page": 3})


def test_a_request_that_did_not_fit_is_halved_as_the_rules_say():
    def asked(**values):
        model = Model(find=lambda p, n: "cut_off")
        plan = plan_of(TITLE, BIG)
        chunk = next(c for c in plan.chunks if c.passage.kind == "table")
        reader = reader_of(model)
        with at("find", values):
            got = reader.find(plan, ENERGY, chunk, Counts())
        return len(model.of("find")), len(got["lost"])
    # Four rows: the whole, two halves, four single rows, each a hole.
    assert asked() == (7, 4)
    assert asked(split_by="lines") == (7, 4)
    assert asked(split_cut_off=False) == (1, 1)         # a hole at once
    assert asked(split_most=1) == (3, 2)                # halved once


def test_the_window_of_a_field_of_the_whole_document_is_split_too():
    def window(**values):
        model = Model(docfield=lambda p, n: "cut_off"
                      if len(p["passages"]) > 1 else {"found": []})
        plan = plan_of(TITLE, TEXT, TABLE)
        reader = reader_of(model)
        with at("docfield", values):
            got = reader.ask_window(plan, {"name": "e", "means": "m"},
                                    plan.chunks, Counts(), "energy")
        return len(model.of("docfield")), got[1]
    asks, lost = window()
    assert asks > 1 and lost is None                     # halved, answered
    assert window(split_cut_off=False) == (1, addressed.CUT)


# -- search -------------------------------------------------------------------


def test_a_search_sentence_is_a_question_by_the_words_of_the_rule():
    assert addressed.is_question("Wie viel Gas?")
    assert addressed.is_question("What is it")
    assert not addressed.is_question("Der Plan sagt es.")
    with rules.overlaid(question_words=["der"]):
        assert addressed.is_question("Der Plan sagt es.")
        assert not addressed.is_question("What is it")
        assert addressed.is_question("Und was?")         # the mark


def test_a_search_without_a_sentence_goes_with_what_the_rule_says():
    class Slot:
        question, name = "Wie hoch?", "year"
    reader = reader_of(Model(), probes=lambda p, d: ["Der Plan."])
    plan = plan_of(TITLE)
    answer = lambda: reader.fallback(plan, ENERGY, Slot)  # noqa: E731
    assert answer() == "Der Plan."
    with rules.overlaid(search_fallback="question"):
        assert answer() == "Wie hoch?"
    with rules.overlaid(search_fallback="name"):
        assert answer() == "year"
    with rules.overlaid(search_fallback="none"):
        assert answer() == ""


def test_the_budget_of_three_shares_of_nothing_is_the_best_in_order():
    ranked = [type("C", (), {"key": i,
                             "passage": type("P", (), {"kind": k})})
              for i, k in enumerate(["table", "figure", "section"])]
    got = budgeted(ranked, 2, {"table": 0, "figure": 0, "section": 0})
    assert [c.key for c in got] == [0, 1]                # no zero division


def test_a_pattern_of_the_model_that_does_not_finish_finds_nothing_in_time():
    plan = plan_of(Source("section", 1, "a" * 40 + "b", {"page": 1}))
    reader = reader_of(Model())
    evil = addressed.regex.compile(r"(a+)+$")
    with rules.overlaid(pattern_timeout_s=0.05):
        began = time.monotonic()
        assert reader.matching(evil, plan.chunks, set()) == []
        assert time.monotonic() - began < 5
    fine = addressed.regex.compile("zz")
    assert reader.matching(fine, plan.chunks, set()) == []
    assert reader.matching(addressed.regex.compile("b$"), plan.chunks,
                           set()) == plan.chunks


def test_the_chunks_beside_a_chunk_are_as_many_as_the_rule_says():
    sources = [Source("section", i, f"Satz {i}.", {"page": 1})
               for i in range(1, 6)]
    plan = plan_of(*sources)
    middle = plan.chunks[2]
    assert [c.owner[1] for c in plan.beside(middle)] == [2, 4]
    with rules.overlaid(beside_pieces=2):
        assert [c.owner[1] for c in plan.beside(middle)] == [1, 2, 4, 5]


# -- taking an answer ---------------------------------------------------------


def resolved(words, at_="2.2", **values):
    plan = plan_of(TITLE, TEXT, TABLE)
    shown, _ = addressed.show_value(
        plan, {"at": {"owner": ["table", 3], "line": 3}, "value": 1})
    with rules.overlaid(**values):
        return addressed.resolve(shown, {"at": at_, "words": words},
                                 plan.passages)


def test_the_words_of_a_find_count_with_their_case_as_the_rule_says():
    assert resolved("rathaus", "3").why is None
    assert resolved("rathaus", "3", match_case=True).why \
        == addressed.WORDS_NOT_IN_LINE


def test_a_find_moves_to_the_cell_that_holds_its_words_as_the_rule_says():
    assert resolved("1.200", "3.3").cell == 2
    assert resolved("1.200", "3.3", move_to_cell=False).cell == 3


def test_the_words_of_a_number_print_one_number_as_the_rules_say():
    assert number_of("800 / 750") is None
    assert number_of("ca. 8,8 GWh") is not None
    with rules.overlaid(first_number_only=False):
        assert number_of("800 / 750") == "800"
    plan = plan_of(TITLE, TEXT, TABLE)
    shown, _ = addressed.show_value(
        plan, {"at": {"owner": ["table", 3], "line": 3}, "value": 1})
    reply = {"found": [{"at": "3.1", "words": "Rathaus"}]}
    held, refused = Reader._finds(plan, shown, reply, None, True)
    assert refused and not held
    with rules.overlaid(words_need_number=False):
        held, refused = Reader._finds(plan, shown, reply, None, True)
        assert held and not refused


def test_two_finds_are_one_by_what_the_rule_names():
    plan = plan_of(TITLE, TEXT, TABLE)
    shown, _ = addressed.show_value(
        plan, {"at": {"owner": ["table", 3], "line": 3}, "value": 1})

    def find(cell, words):
        return addressed.resolve(shown, {"at": f"3.{cell}", "words": words},
                                 plan.passages)
    a, b = find(2, "1.200"), find(3, "27")
    assert len(addressed.joined([a], [b])) == 2
    with rules.overlaid(same_find_by=["line"]):
        assert len(addressed.joined([a], [b])) == 1


def test_a_quote_is_extended_in_the_direction_the_rule_says():
    passage = units.passage_of(TEXT)
    standard = units.short_quote(passage, [2], 60)
    assert standard.startswith("Der Verbrauch sank.")
    with rules.overlaid(quote_extend_order="after_then_before"):
        assert units.short_quote(passage, [2], 60).endswith("Sanierung.")


def test_a_quote_over_several_lines_is_evidence_where_the_rule_says():
    plan = plan_of(TITLE, TEXT, TABLE)
    shown, _ = addressed.show_value(
        plan, {"at": {"owner": ["section", 2], "line": 2}, "value": 1})
    texts = lambda: {s.text for s in shown.evidence()}  # noqa: E731
    together = " ".join(line.text for line, _ in shown.blocks[""].lines)
    assert together in texts()
    with rules.overlaid(quote_may_span_lines=False):
        assert together not in texts()


def test_a_find_that_names_several_years_is_read_as_the_rule_says():
    class Slot:
        kind = addressed.NUMBER
    reader = reader_of(Model())
    got = Found(words="2020 bis 2030")
    run = lambda: reader.answers(  # noqa: E731
        plan_of(TITLE), ENERGY, Row("v", 0, {}), Slot, got, Counts())[0][0]
    assert run().get("until") == 2030
    with rules.overlaid(years_in_words="first"):
        assert "until" not in run()


def test_a_find_from_another_place_is_checked_as_the_rule_says():
    plan = plan_of(TITLE, TEXT, TABLE)
    row = Row("v", 0, {"at": {"owner": ["section", 2], "line": 2}, "value": 1})
    got = Found(lines=[(Line(1, "x"), TEXT)], words="x")

    def about(model_reply, **values):
        model = Model(check=lambda p, n: model_reply)
        reader = reader_of(model)
        with rules.overlaid(**values):
            return reader.about(plan, row, SLOTS["year"], got, Counts(), {})
    assert about({"about": "yes"}) is True
    assert about(None) is False
    assert about(None, about_no_reply="keep") is True


def test_the_step_of_the_box_that_checks_reads_its_own_values():
    plan = plan_of(TITLE, TEXT, TABLE)
    row = Row("v", 0, {"at": {"owner": ["section", 2], "line": 2}, "value": 1})
    got = Found(lines=[(Line(1, "x"), TEXT)], words="x")
    model = Model()
    reader = reader_of(model)
    box = {"id": "about", "box": "about",
           "rules": {"about_shows": ["answer"]}}
    what = Asking("search", "about", about_step=lambda: at(
        "about", {"about_shows": ["answer"]}))
    with at("search", {}), addressed.asking(what):
        reader.about(plan, row, SLOTS["year"], got, Counts(), {})
    assert set(model.of("check")[0][0]) == {"answer"}
    assert box["rules"]                                  # (the node's own)


# -- lists --------------------------------------------------------------------


def test_two_equal_names_are_two_entries_unless_the_rule_says_one():
    names = Names("scenario")
    first, second = names.add("Central", 1), names.add("Central", 2)
    assert (first, second) == (1, 2)
    assert names.entries[1].label == "Central (2)"
    one = Names("scenario")
    with rules.overlaid(same_name_two_entries=False):
        assert one.add("Central", 1) == one.add("Central", 2) == 1


def test_names_are_shown_by_work_or_as_found_by_the_rule():
    works = Names("work", addressed.Entry("this publication", "x", 0, ""))
    works.add("Other", 1)
    names = Names("scenario")
    names.add("B", 2)
    names.add("A", 1)
    assert [t for _, t in names.shown(works)][0].endswith(": A")
    with rules.overlaid(names_list_order="found"):
        assert [t for _, t in names.shown(works)][0].endswith(": B")


def test_a_year_list_shows_its_quotes_as_the_rule_says():
    listed = [{"year": 2021, "state": "base", "quote": "Basisjahr 2021"}]
    assert addressed.years_listed(listed) == ["1 2021 (base: Basisjahr 2021)"]
    with rules.overlaid(year_list_quote=False):
        assert addressed.years_listed(listed) == ["1 2021 (base)"]


def test_a_long_list_with_groups_is_asked_in_two_steps_where_the_rule_says():
    class Option:
        definition = ""

        def __init__(self, i, group):
            self.label, self.group = f"o{i}", group
    options = [Option(i, "a" if i < 3 else "b") for i in range(6)]
    _lines, _choices, grouped = addressed.listing(options, 2)
    assert grouped
    with rules.overlaid(two_step_list=False):
        assert not addressed.listing(options, 2)[2]


def test_a_document_name_is_taken_from_the_title_page_as_the_rule_says():
    def payload_with(**values):
        model = Model()
        plan = plan_of(TITLE, TEXT)
        row = Row("v", 0, {"at": {"owner": ["section", 2], "line": 2},
                        "value": 300})
        read = type("R", (), {"batch": type("B", (), {"parameter": ENERGY})})
        reader = reader_of(model)
        with rules.overlaid(**values):
            reader.sentence(plan, read, row, SLOTS["year"], Counts())
        return model.of("phrase")[0][0]
    assert payload_with()["document"] == {"name": TITLE.text.split("\n")[0]}
    assert "document" not in payload_with(document_name_fallback=False)
