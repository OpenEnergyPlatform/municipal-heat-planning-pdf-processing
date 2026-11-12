"""
The second ways of the addressed reading (owner decision 2026-11-11):
each is off by standard, which asks today's requests,
and a rule set at a step or overlaid changes what the code does and notes the
request that went through it (`second_way`, the rule's name).

Promises, one sentence each:
1. `outside_list` keep: an answer that is none of a closed list's entries is
   read with its own wording, its entry empty AND the wording noted; ask again
   refuses it as before.
2. `search_with` question or name: a search goes with the field's question or
   the dimension's name AND no request writes a sentence for it.
3. `rerank_when` each round: the reranker orders the chunks left before every
   further request; once orders them once.
4. `show_twice` on: a chunk shown before may be shown a second time AND never
   a third; off: never twice.
5. `fetched_count` on: the chunks the model fetched count against the most a
   search shows; off: they do not.
6. `entry_once_per_wording` off: a wording is asked for every place it
   stands in, on: once; `list_shows_earlier` on: the list question shows the
   wordings settled before, off: it does not.
7. `name_may_be_none` off: the answer 0 of a name is an answer outside the
   list and is asked again; on: it is no entry.
8. `work_without_line` on: a value takes the work its piece names, or this
   publication, with its own line as quote; off: it asks.
9. `unit_searched` on: an open unit is searched; off: it is asked at its
   place only.
Every case is by construction: the standard breaks the second way's promise.
"""
import dataclasses
import types

import pytest

from docpipe import rules
from docpipe.extraction import addressed, conditions, fields, pipeline
from docpipe.extraction.addressed import Counts, Reader, say
from docpipe.extraction.engine import SearchSupply
from docpipe.extraction.pipeline import Row, Source, merge_field

from test_addressed import (ENERGY, SCENARIOS, SLOTS, SPEC, TABLE, TEXT, Model,
                            entry_of, in_order, plan_of, reader_of, searching)
from test_addressed import in_order as _order  # noqa: F401
from test_ruleset_flowing import scope_of
from test_addressed import read_works


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def noted_ways(model, kind):
    return [n.get("second_way") for _, n in model.of(kind)]


# -- 1. outside_list --

def read_scenario_type(entry, **way):
    kind = SCENARIOS.by_uri["scenario_type"]
    text = Source("section", 4, "The Reference scenario continues current "
                                "policies.", {"document_id": 7, "page": 2})
    model = Model(
        find=lambda p, n: {"found": [{"entry": entry, "at": "1",
                                      "words": "Reference scenario"}]}
        if n.get("parameter") == kind.uri else {"found": []})
    with rules.overlaid(**way):
        reads = reader_of(model, spec=SCENARIOS)(plan_of(text), [kind])
    return [c for r in reads for c in r.claims], model, reads


def test_a_find_outside_the_list_is_kept_with_its_wording_or_asked_again():
    kind = SCENARIOS.by_uri["scenario_type"]
    _lines, choices, _grouped = Reader(SCENARIOS, Model().asks(),
                                       in_order).listed(kind)
    outside = len(choices) + 5
    # the standard asks again and keeps nothing
    claims, model, reads = read_scenario_type(outside)
    assert sum(r.failed.get(addressed.NOT_AN_OPTION, 0) for r in reads) == 1
    assert model.of("follow")
    # the second way keeps the wording, leaves the entry empty and notes it
    claims, model, reads = read_scenario_type(outside, outside_list="keep")
    (claim,) = claims
    assert claim["value"] == "" and claim["value_raw"] == "Reference scenario"
    assert claim["value_seen"] == "Reference scenario"
    assert not model.of("follow")
    assert not sum(r.failed.get(addressed.NOT_AN_OPTION, 0) for r in reads)


def test_an_answer_outside_a_list_is_read_with_its_wording_where_kept():
    text = "Der Endenergieverbrauch liegt im Jahr 2030 bei 450 MWh."
    shown = Source("section", 1, text)
    answer = {"value": "Zebra", "value_raw": "Endenergieverbrauch",
              "quote": text}

    def merged():
        row = Row("R1", 0, {})
        got = merge_field([row], [shown], SLOTS["carrier"],
                          {"answers": {"R1": answer}})
        return row, got
    row, got = merged()
    assert got["failed"][0]["why"] == "not_an_option"
    assert row.claim["carrier_state"] != fields.READ
    with rules.overlaid(outside_list="keep"):
        row, got = merged()
    assert not got["failed"] and got["filled"] == 1
    assert row.claim["carrier_state"] == fields.READ
    assert row.claim["carrier"] is None
    assert row.claim["carrier_raw"] == "Endenergieverbrauch"
    assert row.claim["carrier_seen"] == "Endenergieverbrauch"
    # kept does not mean unchecked: a quote that is not shown is refused
    with rules.overlaid(outside_list="keep"):
        row = Row("R1", 0, {})
        got = merge_field([row], [Source("section", 2, "Anderer Text.")],
                          SLOTS["carrier"], {"answers": {"R1": answer}})
    assert got["failed"][0]["why"] == "quote_not_in_source"
    assert row.claim["carrier_state"] != fields.READ


# -- 2. search_with --

def test_a_search_goes_with_the_question_or_the_name_and_asks_no_sentence():
    said = "Die Verbrauchswerte der Liegenschaften gelten für 2021."
    sentences, _counts, model = searching(said)
    assert [said] in sentences and model.of("phrase")
    assert not [w for w in noted_ways(model, "search") if w]
    for how, expected in (("question", SLOTS["year"].question),
                          ("name", "year")):
        with rules.overlaid(search_with=how):
            sentences, _counts, model = searching(said)
        assert [expected] in sentences
        assert [said] not in sentences
        assert not model.of("phrase")
        ways = [n.get("second_way") for _, n in model.of("search")
                if n["coordinate"] == "year"]
        assert ways and set(ways) == {"search_with"}


# -- 3 to 5. the supply of a search --

@dataclasses.dataclass(frozen=True)
class Piece:
    key: tuple


def pieces(n, start=0):
    return [Piece((start + i,)) for i in range(n)]


def test_a_chunk_is_shown_twice_at_most_and_only_where_the_rule_says():
    beside, order = pieces(1), pieces(4, start=1)
    again = [beside[0]]

    def walk(seen):
        supply = SearchSupply(beside, lambda: list(order), "found")
        shown = []
        for _ in range(8):
            batch, _label = supply.take(2, seen)
            if not batch:
                break
            seen.update(c.key for c in batch)
            shown.append([c.key[0] for c in batch])
            supply.fetched = list(again)
        return shown, supply
    shown, supply = walk(set())
    assert shown == [[0], [1, 2], [3, 4]]
    assert not supply.ways
    with rules.overlaid(show_twice=True):
        shown, supply = walk(set())
    # the beside chunk is fetched again and shown a second time, never a
    # third; the order's chunks come once
    assert [k for batch in shown for k in batch].count(0) == 2
    assert all([k for batch in shown for k in batch].count(i) == 1
               for i in (1, 2, 3, 4))
    assert supply.ways == {"show_twice"}


def test_fetched_chunks_count_against_the_search_only_where_the_rule_says():
    order = pieces(6, start=10)
    fetched = pieces(2)

    def walk():
        supply = SearchSupply([], lambda: list(order), "found", 4)
        supply.fetched = list(fetched)
        seen, count = set(), 0
        for _ in range(10):
            batch, _label = supply.take(2, seen)
            if not batch:
                break
            seen.update(c.key for c in batch)
            count += len(batch)
        return count, supply
    count, supply = walk()
    assert count == 8 and not supply.ways
    with rules.overlaid(fetched_count=True):
        count, supply = walk()
    assert count == 4 and supply.ways == {"fetched_count"}


def test_the_reranker_orders_the_chunks_left_each_round_where_asked():
    order = pieces(6)
    seen_by_reranker = []

    def reorder(left):
        seen_by_reranker.append(len(left))
        return list(reversed(left))

    def walk():
        supply = SearchSupply([], lambda: list(order), "found", None,
                              reorder)
        seen, shown = set(), []
        for _ in range(5):
            batch, _label = supply.take(2, seen)
            if not batch:
                break
            seen.update(c.key for c in batch)
            shown += [c.key[0] for c in batch]
        return shown, supply
    shown, supply = walk()
    assert shown == [0, 1, 2, 3, 4, 5] and seen_by_reranker == []
    with rules.overlaid(rerank_when="each_round"):
        shown, supply = walk()
    assert seen_by_reranker == [6, 4, 2]
    assert shown == [5, 4, 3, 2, 1, 0] and supply.ways == {"rerank_when"}


def test_a_search_notes_the_second_ways_its_requests_went_through():
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 4 + i}) for i in range(12)]
    reranked = []

    def rerank(document_id, sentences, chunks):
        reranked.append(len(chunks))
        return list(chunks)
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []})
    reader = Reader(SPEC, model.asks(), in_order, rerank=rerank, budget=10)
    reader(plan_of(many[0], TABLE, *many[1:]), [ENERGY])
    assert not [w for w in noted_ways(model, "search") if w]
    base = len(reranked)
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []})
    reader = Reader(SPEC, model.asks(), in_order, rerank=rerank, budget=10)
    with rules.overlaid(rerank_when="each_round"):
        reader(plan_of(many[0], TABLE, *many[1:]), [ENERGY])
    assert len(reranked) > 2 * base - 1
    assert "rerank_when" in noted_ways(model, "search")


# -- 6. the entry of a list --

def place(number):
    line = types.SimpleNamespace(number=number, text=f"Zeile {number}")
    source = types.SimpleNamespace(owner_kind="section", owner_id=2)
    return types.SimpleNamespace(lines=[(line, source)], source=source,
                                 cell=None, passage=None, quote="")


def test_a_wording_is_asked_once_or_for_every_place_where_the_rule_says():
    def asked(**way):
        model = Model(list=lambda p, n: {"entry": [1]})
        plan = plan_of(TEXT)
        reader = reader_of(model)
        with rules.overlaid(**way):
            for number in (1, 2, 3):
                reader.entry(plan, ENERGY.uri, "carrier", SLOTS["carrier"],
                             "Gas", place(number), Counts(), several=True)
        return model
    model = asked()
    assert len(model.of("list")) == 1
    assert not [w for w in noted_ways(model, "list") if w]
    model = asked(entry_once_per_wording=False)
    assert len(model.of("list")) == 3
    assert set(noted_ways(model, "list")) == {"entry_once_per_wording"}


def test_a_list_question_shows_the_wordings_settled_before_if_asked():
    def asked(**way):
        model = Model(list=lambda p, n: {"entry": [1]})
        plan = plan_of(TEXT)
        with rules.overlaid(**way):
            entry_of(model, SLOTS["carrier"], "Gas", plan=plan, several=True)
            entry_of(model, SLOTS["carrier"], "Erdöl", plan=plan,
                     several=True)
        return [payload for payload, _ in model.of("list")], model
    (first, second), model = asked()
    assert "earlier" not in second and not noted_ways(model, "list")[1]
    (first, second), model = asked(list_shows_earlier=True)
    assert "earlier" not in first
    assert second["earlier"] == [{"words": "gas", "entry": ["Erdgas"]}]
    assert noted_ways(model, "list") == [None, "list_shows_earlier"]


# -- 7. a name that names nothing --

def test_the_answer_0_of_a_name_is_no_entry_unless_the_rule_says_outside():
    def named(**way):
        model = Model(names=lambda p, n: {"entry": 0})
        text = Source("section", 4, "Source: JRC.",
                      {"document_id": 7, "page": 2})
        reader = reader_of(model, spec=SCENARIOS, works=SCENARIOS.works)
        plan = plan_of(text)
        reader.lists_of(plan)
        with rules.overlaid(**way):
            got = reader.name_of(plan, "scenario", "Source: JRC.", None,
                                 Counts())
        return got, model
    got, model = named()
    assert got == [] and not model.of("follow")
    got, model = named(name_may_be_none=False)
    assert got is None
    ((payload, noted),) = model.of("follow")
    assert payload["what"] == [say("name_not_listed", given=0)]
    assert noted["second_way"] == "name_may_be_none"


# -- 8. a work without a line --

def test_a_value_takes_the_work_of_its_piece_without_a_line_where_asked():
    names, model, _reads = read_works({"entry": 0})
    assert names["Delayed"]["work_state"] == fields.SAID_UNSTATED
    assert [p for p, _ in model.of("coord") if "list" in p]
    with rules.overlaid(work_without_line=True):
        names, model, _reads = read_works({"entry": 0})
    delayed = names["Delayed"]
    assert delayed["work_state"] == fields.READ
    assert delayed["work_means"] == ["this publication"]
    assert delayed["work_quote"] == (
        "The Delayed case reaches net zero in 2060.")
    assert not [p for p, _ in model.of("coord") if "list" in p]
    # a piece that names two works leaves the value to ask: no line, no work
    # for a value whose piece names the work of another line


# -- 9. an open unit --

def test_an_open_unit_is_searched_only_where_the_rule_says():
    engine, scope, _doc = scope_of()
    coord = scope.get("coord")
    coord.slot = fields.unit_slot(SPEC, ENERGY)
    coord.group = types.SimpleNamespace(own_passage=("unit",), own_value=())
    row = conditions.one("coordinate", "own_only")

    def own_only():
        return conditions.holds({"all": [row]}, engine.facts(scope))
    assert own_only()
    with rules.overlaid(unit_searched=True):
        assert not own_only()
        # a dimension of the same group stays asked at its place
        coord.slot = SLOTS["carrier"]
        coord.group = types.SimpleNamespace(own_passage=("carrier",),
                                            own_value=())
        assert own_only()


# -- the rules a step sets reach their consumers (item 2) --

def test_the_sign_of_a_find_s_number_stays_outside_where_the_rule_is_off():
    assert addressed.number_of("-1.155") == "-1155"
    assert addressed.number_of("1.155") == "1155"
    with rules.overlaid(sign_belongs="off"):
        assert addressed.number_of("-1.155") == "1155"
        assert addressed.number_of("1.155") == "1155"
    with rules.in_step(rules.stepped({"id": "x", "box": "find"},
                                     {"sign_belongs": "off"})):
        assert addressed.number_of("-1.155") == "1155"
    assert addressed.number_of("-1.155") == "-1155"


def test_the_marks_of_a_span_are_read_where_the_value_is_read():
    reader = Reader(SPEC, Model().asks(), in_order)
    standard = rules.get("span_marks")
    assert standard and reader.span_marks == standard
    marks = {"carrier": "out:approximate"}
    with rules.in_step(rules.stepped({"id": "x", "box": "find"},
                                     {"span_marks": marks})):
        assert reader.span_marks == marks
    with rules.overlaid(span_marks={}):
        assert reader.span_marks == {}
    assert reader.span_marks == standard
    # a reader given its own marks keeps them
    assert Reader(SPEC, Model().asks(), in_order,
                  span_marks={"a": "b"}).span_marks == {"a": "b"}


def test_a_search_may_read_every_chunk_where_a_step_says_so():
    from docpipe.extraction import runner
    reader = Reader(SPEC, Model().asks(), in_order, budget=7)
    assert reader.budget == 7
    with rules.in_step(rules.stepped({"id": "x", "box": "order"},
                                     {"search_to_end": True})):
        assert reader.budget == runner.REST_TO_END
    assert reader.budget == 7


def test_the_model_that_wrote_a_transcription_is_the_step_s_model():
    from docpipe.extraction import runner
    _ask, fingerprint = runner.make_transcribe(None, None)
    standard = fingerprint()
    with rules.in_step(rules.stepped({"id": "x", "box": "transcribe"},
                                     {"model": "another-model"})):
        assert fingerprint() != standard
    assert fingerprint() == standard
    kept = addressed.Transcripts(None, None, fingerprint, lambda s: None)
    assert kept.fingerprint == standard


def test_a_rule_read_in_a_step_names_that_step():
    assert "compute" in rules.BY_NAME["quote_min_chars"].steps
    assert rules.BY_NAME["unreachable_share"].steps[0] == "write"
    assert "read_parameters" in rules.BY_NAME["unreachable_share"].steps
    assert "phrase" in rules.BY_NAME["same_characters"].steps
    assert "each piece" in rules.BY_NAME["figure_part"].steps


# -- item 4: the questions about a value as one conversation --

def asked_about_a_value(**way):
    """The coord requests of the one value of TABLE, in order, with the
    follow-ups: the value's own place answers year and carrier at the row
    of its line, the first answer of the year not holding."""
    def coord(payload, noted):
        if noted["coordinate"] == "year":
            return {"at": "3.1", "words": "2021"} if "conversation" in \
                payload else {"at": "9", "words": "2021"}
        return {"at": 0}
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if n.get("owner") == 3 else {"found": []},
        coord=coord,
        follow=lambda p, n: {"at": 0})
    with rules.overlaid(**way):
        reader_of(model)(plan_of(TABLE), [ENERGY])
    return model


def test_the_questions_about_one_value_are_one_conversation_where_asked():
    model = asked_about_a_value()
    assert not [p for k, p, _ in model.calls if "conversation" in p]
    assert not [n for k, _, n in model.calls if "second_way" in n]
    model = asked_about_a_value(conversation="per_value")
    coords = [(p, n) for p, n in model.of("coord")
              if n["value"] == model.of("coord")[0][1]["value"]]
    first, *later = coords
    # the first question of a value has no history, each later one has the
    # questions before it and how they were answered
    assert "conversation" not in first[0]
    assert later
    held = later[-1][0]["conversation"]
    asked = [entry["asked"] for entry in held if "follow_up" not in entry]
    assert asked == [n["coordinate"] for _, n in coords[:-1]]
    assert all(entry["answer"] is not None for entry in held)
    # the follow-up of an answer that did not hold is an entry of its own
    assert [entry["asked"] for entry in held if "follow_up" in entry] \
        == ["year"]
    assert all(n["second_way"] == "conversation" for _, n in later)
    assert "second_way" not in first[1]
    # a follow-up hangs on the conversation of its value
    for payload, noted in model.of("follow"):
        if noted.get("coordinate"):
            assert payload["conversation"]
            assert noted["second_way"] == "conversation"
    # another value starts a conversation of its own
    assert all(entry["asked"] != "x" for p, _ in later
               for entry in p["conversation"])


# -- item 4: the answer by its quote --

def find_by_quote(quote, **way):
    model = Model(
        find=lambda p, n: {"found": [{"quote": quote, "words": "1.200"}]}
        if n.get("owner") == 3 else {"found": []},
        follow=lambda p, n: None)
    with rules.overlaid(**way):
        reads = reader_of(model)(plan_of(TABLE), [ENERGY])
    claims = [c for r in reads for c in r.claims]
    failed = {}
    for r in reads:
        for why, number in r.failed.items():
            failed[why] = failed.get(why, 0) + number
    return claims, failed, model


def test_an_answer_names_its_line_by_its_quote_where_the_rule_says_so():
    quote = "| Rathaus | 1.200 | 27 |"
    claims, failed, model = find_by_quote(quote)
    # the standard knows no quote: the answer names no line
    assert not claims and failed == {addressed.NOT_AN_ADDRESS: 1}
    claims, failed, model = find_by_quote(quote, answer_with="quote")
    (claim,) = claims
    assert claim["value"] == 1200 and not failed
    assert claim["at"] == {"owner": ["table", 3], "line": 3, "cell": 2}
    assert claim["quote"].endswith(quote)
    # the grammar, the example and the note follow the rule
    ((payload, noted),) = [x for x in model.of("find")
                           if x[1].get("owner") == 3]
    assert noted["second_way"] == "answer_with"
    kind, example = [e for e in model.examples if e[0] == "find"][0]
    assert "quote" in example[0]["found"][0] \
        and "at" not in example[0]["found"][0]
    assert example[0]["found"][0]["quote"] in "\n".join(
        payload["passage"]["lines"])
    def properties(format_):
        return format_["json_schema"]["schema"]["properties"]
    assert "at" in properties(addressed.coord_format(False))
    with rules.overlaid(answer_with="quote"):
        assert "quote" in properties(addressed.coord_format(False))
        assert "at" not in properties(addressed.coord_format(False))
        assert "at" not in properties(addressed.found_format())[
            "found"]["items"]["properties"]


def found_in(owner, reply, **way):
    """(claims with the source of their read, failures) of a reading of
    the table and the text whose find of piece *owner* replies *reply*."""
    model = Model(find=lambda p, n: reply if n.get("owner") == owner
                  else {"found": []}, follow=lambda p, n: None)
    with rules.overlaid(**way):
        reads = reader_of(model)(plan_of(TABLE, TEXT), [ENERGY])
    claims = [(claim, read.batch.items[0].source) for read in reads
              for claim in read.claims]
    failed: dict = {}
    for read in reads:
        for why, number in read.failed.items():
            failed[why] = failed.get(why, 0) + number
    return claims, failed


def test_with_the_check_off_a_quote_is_looked_for_in_the_whole_document():
    """Owner decision 2026-11-12: with the rule `check_quote_shown` off, a
    quote that stands in no shown line is looked for in every passage of
    the document, and the first that holds it is the value's place; one
    that stands nowhere falls; an address that names no shown line is
    asked again either way."""
    elsewhere = {"found": [{"quote": "verbrauchte die Stadt 300 MWh Erdgas",
                            "words": "300"}]}
    # on: the table's request did not show the text
    claims, failed = found_in(3, elsewhere, answer_with="quote")
    assert not claims and failed == {"quote_not_in_source": 1}
    claims, failed = found_in(3, elsewhere, answer_with="quote",
                              check_quote_shown=False)
    ((claim, source),) = claims
    assert not failed and claim["value"] == 300
    assert claim["at"]["owner"] == ["section", 2]
    assert (source.owner_kind, source.owner_id) == ("section", 2)
    assert "300 MWh Erdgas" in claim["quote"]
    # the fold reads it at its place
    report = pipeline.DocumentReport(document_id=7)
    batch = pipeline.Batch(7, ENERGY, [pipeline.WorkItem(7, ENERGY, source)],
                           spec=SPEC)
    pipeline.fold_batch(batch, {"tuples": [claim]}, report, spec=SPEC)
    assert [row["provenance"]["owner_id"] for row in report.tuples] == [2]
    # the failure by construction: standing nowhere it falls, and an address
    # that names no shown line is asked again, the check off or on
    nowhere = {"found": [{"quote": "| Fernwärme | 99 | 5 |", "words": "99"}]}
    claims, failed = found_in(3, nowhere, answer_with="quote",
                              check_quote_shown=False)
    assert not claims and failed == {"quote_not_in_source": 1}
    no_line = {"found": [{"at": "A9", "words": "300"}]}
    claims, failed = found_in(3, no_line, check_quote_shown=False)
    assert not claims and failed == {addressed.NOT_AN_ADDRESS: 1}


def test_a_quote_that_stands_in_no_shown_line_is_not_in_the_source():
    claims, failed, _model = find_by_quote("| Fernwärme | 99 | 5 |",
                                           answer_with="quote")
    assert not claims
    assert failed == {"quote_not_in_source": 1}
    # characters the rule counts as the same compare as the same
    quote = "| Rathaus \u2013 1.200 | 27 |"
    claims, failed, _model = find_by_quote(
        "| Rathaus | 1.200 | 27 |".replace("|", "\u2223"),
        answer_with="quote")
    assert not claims
    with rules.overlaid(answer_with="quote",
                        same_characters={"\u2223": "|"}):
        claims, failed, _model = find_by_quote(
            "\u2223 Rathaus \u2223 1.200 \u2223 27 \u2223")
    assert len(claims) == 1 and not failed
