"""
The rules of the reading by address (`addressed.py`) that decide how a
search, a list, a find, a number's words and the order of the pieces are
made, each read where it is used and set at a step of its kind
(`rules.in_step`) or laid over the run (`rules.overlaid`).

The promise of each: the value decides what the code does, AND the standard
gives today's result. Every case holds the break by construction: the same
reading with the rule set the other way.

Author: Felix Vossel
"""
import json
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import addressed, fields
from docpipe.extraction.addressed import (Counts, Found, Names, Orders,
                                          Reader)
from docpipe.extraction.pipeline import Row, Source
from docpipe.extraction.units import Line

from test_addressed import (ENERGY, SLOTS, SPEC, TABLE, TEXT, TITLE, Model,
                            coordinate_answers, entry_of, in_order, plan_of,
                            reader_of, searching)
from conftest import step_node


def at(kind: str, values: dict):
    """What the engine does around a box of *kind* that sets *values*."""
    return rules.in_step(rules.stepped(step_node(kind), values))


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


# -- the years and spans a find names ---------------------------------------

def test_a_year_is_a_number_of_four_digits_inside_the_range_of_the_rule():
    text = "1799 1800 2199 2200 und 2020"
    assert addressed.years_in(text) == ["1800", "2199", "2020"]
    with at("find", {"year_words": [2000, 2100]}):
        assert addressed.years_in(text) == ["2020"]
    # the failure by construction: a range that holds no year of the text
    with at("find", {"year_words": [1000, 1100]}):
        assert addressed.years_in(text) == []


def test_the_words_that_make_a_span_of_years_are_the_rule_s():
    def spans(text, **values):
        with at("find", values):
            return bool(addressed.span().search(text))
    assert spans("2020 bis 2030") and spans("2030-2045")
    assert not spans("2020 bis 2030", span_words=[])
    assert spans("2020 until 2030")
    assert spans("2020 dann 2030", span_words=["dann"])
    assert not spans("2020 dann 2030")
    assert not spans("2020 until 2030", span_words=["dann"])
    # the failure by construction: with both empty nothing is a span
    assert not spans("2020 bis 2030", span_words=[], span_dashes="")
    assert not spans("2030-2045", span_words=[], span_dashes="")


def test_the_dashes_that_make_a_span_of_years_are_the_rule_s():
    def spans(text, **values):
        with at("find", values):
            return bool(addressed.span().search(text))
    assert spans("2030-2045") and spans("2030–2045")
    assert not spans("2030–2045", span_dashes="-")
    assert spans("2030/2045", span_dashes="/")
    # the failure by construction: the dashes gone, the words still make one
    assert not spans("2030-2045", span_dashes="")
    assert spans("2030 bis 2045", span_dashes="")


# -- what a reply may fetch ---------------------------------------------------

def test_a_reply_may_fetch_what_the_rule_allows_and_the_schema_says_so():
    every = ["next", "previous", "item", "search", "similar"]
    assert addressed.fetches() == every
    assert addressed.more_schema()["items"]["properties"]["get"][
        "enum"] == every
    with at("search", {"fetches": ["next", "similar"]}):
        assert addressed.fetches() == ["next", "similar"]
        assert addressed.more_schema()["items"]["properties"]["get"][
            "enum"] == ["next", "similar"]
    # the failure by construction: nothing allowed, nothing to fetch
    with at("search", {"fetches": []}):
        assert addressed.fetches() == []


# -- the cell an example names ------------------------------------------------

def test_the_example_names_the_cell_the_rule_says_and_the_last_one_at_most():
    plan = plan_of(TITLE, TEXT, TABLE)
    shown, _ = addressed.show_value(
        plan, {"at": {"owner": ["table", 3], "line": 3}, "value": 1})
    assert addressed.first_address(shown, True) == "3.2"
    with at("find", {"example_cell": 3}):
        assert addressed.first_address(shown, True) == "3.3"
    # the failure by construction: a row with fewer cells gets its last one,
    # and no cell where the example is no cell's
    with at("find", {"example_cell": 9}):
        assert addressed.first_address(shown, True) == "3.3"
        assert addressed.first_address(shown, False) == "3"


# -- an answer that does not hold after its follow-ups -----------------------

def year_state(**values):
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []},
        coord=coordinate_answers(year={"at": "1", "words": "1999"}),
        follow=lambda p, n: {"at": "1", "words": "1998"}
        if n.get("coordinate") == "year" else None)
    with at("coord", values):
        reads = reader_of(model)(plan_of(TABLE), [ENERGY])
    (claim,) = [c for r in reads for c in r.claims]
    return claim["year_state"]


def test_an_answer_that_does_not_hold_ends_unbacked_or_as_it_was():
    assert year_state() == fields.UNBACKED
    assert year_state(after_follow_ups="unbacked") == fields.UNBACKED
    assert year_state(after_follow_ups="discard") == fields.SAID_UNSTATED


# -- a search: the finds that are checked and the finds that are taken ------

LONG = Source("section", 2, "Der Verbrauch sank. Die Stadt verbrauchte 300 "
                            "MWh Erdgas. Danach kam die Sanierung 2020. Im "
                            "Jahr 2021 war es anders. Ende.",
              {"document_id": 7, "page": 2})


def long_value(payload, noted):
    """The find of the value in the piece of LONG that names it."""
    if noted.get("owner") == 2 and "Die Stadt" in json.dumps(payload):
        return {"found": [{"at": "2", "words": "300"}]}
    return {"found": []}


def years_found(payload, noted, which=("2020", "2021")):
    """What a search for the year finds: every line of the pieces shown
    that names one of *which*."""
    if noted["coordinate"] != "year":
        return {"at": 0}
    found = [{"at": line.split(" ")[0], "words": year}
             for block in payload["passages"].values()
             for line in block["lines"] for year in which if year in line]
    return {"found": found} if found else {"at": 0}


def test_a_find_in_the_values_own_passage_is_checked_where_the_rule_says():
    def checks(**values):
        model = Model(find=long_value, search=lambda p, n: years_found(
            p, n, ("2021",)))
        with at("search", values):
            reader_of(model)(plan_of(LONG, chunk_units=2), [ENERGY])
        return len(model.of("check"))
    assert checks() == 0                      # the value's own passage
    assert checks(about_other="passage") == 0
    assert checks(about_other="any") == 1


def test_the_finds_a_search_takes_for_one_value_are_the_rule_s():
    def years(**values):
        model = Model(find=long_value, search=years_found)
        with at("search", values):
            reads = reader_of(model)(plan_of(LONG, chunk_units=2), [ENERGY])
        return sorted(c["year"] for r in reads for c in r.claims
                      if c.get("year_state") == fields.READ)
    assert years() == [2020]                  # the first find alone
    assert years(search_finds_taken="first") == [2020]
    assert years(search_finds_taken="all") == [2020, 2021]


# -- the lists ----------------------------------------------------------------

def big_list(groups=("A", "B"), size=30):
    return SimpleNamespace(
        name="sector", question="Welcher Sektor?", options=tuple(
            fields.Option(label=f"Sektor {i}", uri=f"S{i}",
                          definition=f"Der Sektor {i}.",
                          group=groups[0] if i < size * 2 // 3
                          else groups[1]) for i in range(size)))


def test_the_groups_a_two_step_list_takes_are_the_first_or_every_one_named():
    slot = big_list()

    def asked(**values):
        model = Model(list=lambda p, n: {"entry": [1, 2]}
                      if n.get("step") == "group" else {"entry": 25})
        with at("docfield", values):
            got = entry_of(model, slot, "Sektor 22")
        return got, [len(p["list"]) for p, _ in model.of("list")]
    # the first group named: its twenty entries, and 25 is none of them
    assert asked() == ("", [2, 20])
    assert asked(group_picks_taken="first") == ("", [2, 20])
    # every group named: the entries of both, and what is chosen among them
    # is an entry of the list, never the name of a group
    assert asked(group_picks_taken="all") == ("Sektor 24", [2, 30])


def test_a_group_without_entries_shows_the_whole_list_or_none():
    slot = big_list(size=6)

    def asked(**values):
        model = Model(list=lambda p, n: {"entry": 5})
        with at("find", values):
            got = entry_of(model, slot, "Sektor 4", group="Z")
        return got, [len(p["list"]) for p, _ in model.of("list")]
    assert asked() == ("Sektor 4", [6])
    assert asked(group_without_entries="all_entries") == ("Sektor 4", [6])
    # the failure by construction: none, and no request is sent
    assert asked(group_without_entries="none") == ("", [])


def test_a_long_list_shown_whole_is_never_shown_by_its_groups():
    # the group a find named has no entry and the list is long: what the
    # model chooses among are the entries, and the label is an entry's
    slot = big_list()
    model = Model(list=lambda p, n: {"entry": 25})
    assert entry_of(model, slot, "Sektor 24", group="Z") == "Sektor 24"
    assert [len(p["list"]) for p, _ in model.of("list")] == [30]


def test_the_names_request_shows_what_a_fixed_entry_means_as_the_rule_says():
    def listed(**values):
        model = Model(names=lambda p, n: {"entry": 0})
        plan = plan_of(TEXT)
        plan.names["scenario"] = Names("scenario")
        with at("names", values):
            reader_of(model).name_of(plan, "scenario", "Zentral", None,
                                     Counts(), besides=(("Fest", "bleibt"),))
        return [p["list"] for p, _ in model.of("names")]
    assert listed() == [["1 Fest (means: bleibt)"]]
    assert listed(names_meanings=True) == [["1 Fest (means: bleibt)"]]
    assert listed(names_meanings=False) == [["1 Fest"]]


# -- what a number is ---------------------------------------------------------

def quantity_words(**values):
    model = Model(list=lambda p, n: {"entry": 0})
    claim = {"what": "Gas", "what_raw": "Gas", "what_state": fields.READ,
             "head": "Erdgas MWh/a", "unit": "MWh/a",
             "at": {"owner": ["table", 3], "line": 3, "cell": 2},
             "value": 1200, "quote": "| Rathaus | 1.200 | 27 |"}
    with at("quantity", values):
        reader_of(model).quantity(plan_of(TEXT, TABLE), ENERGY,
                                  Row("v", 0, claim), SLOTS["carrier"],
                                  Counts())
    return [p["words"] for p, _ in model.of("list")]


def test_the_words_of_a_question_about_a_number_are_joined_as_the_rule_says():
    assert quantity_words() == ["Gas / Erdgas MWh/a / MWh/a"]
    assert quantity_words(quantity_joiner=" | ") == [
        "Gas | Erdgas MWh/a | MWh/a"]
    # the failure by construction: a joiner no word of the plan has
    assert quantity_words(quantity_joiner="") == ["GasErdgas MWh/aMWh/a"]


def test_the_words_of_a_question_about_a_number_are_those_the_rule_names():
    assert quantity_words(quantity_words=["unit", "head"]) == [
        "MWh/a / Erdgas MWh/a"]
    assert quantity_words(quantity_words=["head"]) == ["Erdgas MWh/a"]
    # the failure by construction: no part left, the value's words stand
    assert quantity_words(quantity_words=[]) == ["1200"]


# -- a search sentence that is a question -------------------------------------

def test_a_search_sentence_that_is_a_question_is_used_where_the_rule_says():
    question = "Für welches Jahr gelten die Verbrauchswerte?"

    def sentences(**values):
        with at("phrase", values):
            said, counts, _model = searching(
                question, probes=lambda p, d: ["Der Satz des Felds."])
        return said[0], counts.questions
    assert sentences() == ([question], 2)
    assert sentences(question_as_sentence=True) == ([question], 2)
    assert sentences(question_as_sentence=False) == (["Der Satz des Felds."],
                                                     0)


# -- the order of the pieces --------------------------------------------------

def test_the_reranker_orders_only_as_many_pieces_as_the_rule_says():
    def ordered(**values):
        calls = []

        def rerank(document_id, sentences, chunks):
            calls.append(len(chunks))
            return list(reversed(chunks))
        reader = Reader(SPEC, Model().asks(), in_order, rerank=rerank,
                        search_order=lambda d, s, p: list(p))
        plan = plan_of(TITLE, TEXT, TABLE)
        pieces = list(plan.chunks)
        with at("search", values):
            shown = reader.shown_order(plan, ["Satz"], pieces)
            again = reader.rerank_left(plan, ["Satz"], pieces)
        return calls, shown == pieces, again == pieces, len(pieces)
    assert ordered() == ([3, 3], False, False, 3)
    # the failure by construction: more pieces asked for than there are,
    # so the pieces keep their order
    assert ordered(rerank_least_pieces=4) == ([], True, True, 3)
    assert ordered(rerank_least_pieces=3)[0] == [3, 3]


def test_the_order_of_a_document_is_kept_and_used_again_where_the_rule_says(
        tmp_path):
    plan = plan_of(TEXT, TABLE)

    def asked(**values):
        count = []

        def order(document_id, sentences, chunks):
            count.append(1)
            return list(chunks)
        with at("order", values):
            Orders(order, lambda parameter, document: ["Satz."],
                   tmp_path)(plan, [ENERGY], 8)
        return len(count)
    assert asked() == 1                        # made and kept
    assert asked() == 0                        # kept, not made again
    assert asked(reuse_stored_order=True) == 0
    # the failure by construction: off, it is made again every time
    assert asked(reuse_stored_order=False) == 1
    assert asked(reuse_stored_order=False) == 1


# -- what a request shows of the value and the plan ---------------------------

def requests_of_a_value(known=None, settings=False, **values):
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if n.get("owner") == 3 else {"found": []})
    plan = plan_of(TABLE)
    if settings:
        plan.settings = [(Line(1, "Basisjahr 2021"), TEXT)]
    reader = reader_of(model, known=known) if known else reader_of(model)
    with at("coord", values):
        reader(plan, [ENERGY])
    return [payload for payload, _ in model.of("coord")]


def test_a_request_shows_what_the_value_has_read_where_the_rule_says():
    def known(claim, asked):
        return {"unit": "MWh/a"}
    shown = requests_of_a_value(known=known)
    assert shown and all(p["known"] == {"unit": "MWh/a"} for p in shown)
    # the failure by construction: off, the same requests show nothing of it
    hidden = requests_of_a_value(known=known, show_known=False)
    assert len(hidden) == len(shown)
    assert all("known" not in p for p in hidden)
    assert [{k: v for k, v in p.items() if k != "known"} for p in shown] \
        == hidden


def test_a_request_shows_what_the_plan_settles_where_the_rule_says():
    shown = requests_of_a_value(settings=True)
    assert shown and all(p["settings"] == ["F1 Basisjahr 2021"]
                         for p in shown)
    hidden = requests_of_a_value(settings=True, show_settled=False)
    assert len(hidden) == len(shown)
    assert all("settings" not in p for p in hidden)
    assert addressed.settings_of(plan_with_settings()) != {}
    with at("coord", {"show_settled": False}):
        assert addressed.settings_of(plan_with_settings()) == {}


def plan_with_settings():
    plan = plan_of(TABLE)
    plan.settings = [(Line(1, "Basisjahr 2021"), TEXT)]
    return plan


# -- a line of another work ---------------------------------------------------

def test_a_line_of_another_work_covers_its_piece_where_the_rule_says():
    plan = plan_of(TITLE, TEXT, TABLE)
    chunk = next(c for c in plan.chunks if c.passage.kind == "table")
    title = chunk.passage.fixed[0]
    head = Found(letter=addressed.letter_headings(),
                 lines=[(Line(1, "Bilanz"), TEXT)], words="x")
    fixed = Found(letter="", lines=[(Line(title, "t"), TABLE)], words="x")
    body = Found(letter="", lines=[(Line(3, "t"), TABLE)], words="x")
    assert Reader.covered(chunk, head) is None
    assert Reader.covered(chunk, fixed) is None
    assert Reader.covered(chunk, body) == {(("table", 3), 3)}
    with at("works", {"work_find_covers_piece": False}):
        assert Reader.covered(chunk, head) == {(("section", 2), 1)}
        assert Reader.covered(chunk, fixed) == {(("table", 3), title)}
        # the failure by construction: a line of the piece's own body
        # covers its own line either way
        assert Reader.covered(chunk, body) == {(("table", 3), 3)}
