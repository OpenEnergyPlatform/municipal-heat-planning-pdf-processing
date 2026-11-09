"""One document read in pieces of numbered lines, one question per request,
every answer an address (addressed.py, owner decisions 2026-11-08, plan of
2026-11-09), each promise with a case that breaks it by construction.

4. A find whose address names no shown line is `not_an_address`, AND one
   whose words do not stand in its line `words_not_in_line`, AND a cell with
   two numbers is asked again; a table value's quote is its row, AND its
   `head` the head of its column.
5. A coordinate's request is its instruction and exactly one message, AND
   it shows of the plan only the value's line with its table's title and
   head, or the sentences beside it, the headings, the title page, the
   settings and what the value has read.
6. A search sentence that is a question is searched and counted, AND the
   search after a coordinate nothing shown says goes with the answer's
   sentence and only without one with the field's.
7. A number off the list is `not_an_option` and asked once more, AND 0 is no
   entry, AND one wording of one field is asked once per document, AND a
   list longer than a request shows with meanings shows names only, AND one
   whose entries name groups is asked group first.
8. A field a document has once is never asked per piece, AND its ranking
   runs out before it is left without a value; a coordinate's search ends
   `unstated` where its ranking runs out AND `exhausted` at its budget.
9. Two equal names of two works are two entries, AND the list is shown by
   work.
11. An answer that does not hold is asked once more, once, AND then the
    coordinate is `unbacked`.
13. A work beside the publication is asked its title, organisation and year
    at its own line, AND never by a field's request per piece, AND its
    values do not reach the graph.
14. Words of a group of scenarios take the members the document names, one
    row each, where the field takes groups, AND stay with the group's words
    for a description, AND such a description reaches no scenario.
A coordinate that reads a value as another entry than the one it must have
closes those after it (`out_of_slice`), and the reasons a find or a
coordinate can fail stand in the trace schema.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from docpipe.extraction import (addressed, fields, runner, schema, trust,
                                units, verify, wording)
from docpipe.extraction.addressed import Asks, Names, Plan, Reader
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.wording import say
from profiles.scenarios import extraction as scenarios_extraction
from profiles.scenarios import kg

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = load_spec(json.loads((ROOT / "profiles" / "scenarios"
                                  / "extraction_spec.json")
                                 .read_text(encoding="utf-8")))

# A spec of one number with a unit, a wording, a year and a list.
SPEC = load_spec({
    "unit_question": "Welche Einheit druckt der Plan für diese Zahl?",
    "groups": {
        "number": {"coordinates": ["unit", "what"], "read_in": "reading",
                   "own_passage": ["unit", "what"],
                   "where": "Die Zeile der Zahl."},
        "frame": {"coordinates": ["year"], "read_in": "reading",
                  "where": "Der Titel der Tabelle."},
        "context": {"coordinates": ["carrier"], "read_in": "reading",
                    "where": "Die Zeilenbeschriftung."}},
    "parameters": [{
        "uri": "energy", "label": "Energieverbrauch",
        "description": "Eine Energiemenge, die der Plan für seine Gemeinde "
                       "bilanziert, je Energieträger und Jahr.",
        "value_type": "float", "unit_target": "OEO_00050008",
        "units_accepted": {"MWh": {"factor": 1.0, "names_period": False},
                           "MWh/a": {"factor": 1.0, "names_period": True}},
        "axes": {
            "what": {"type": "text", "required": False,
                     "question": "Welche Bezeichnung gibt der Plan dieser "
                                 "Zahl?"},
            "year": {"type": "int",
                     "question": "Für welches Jahr gilt diese Zahl?"},
            "carrier": {"required": False, "several": True,
                        "question": "Für welchen Energieträger gilt diese "
                                    "Zahl?",
                        "vocabulary": {
                            "OEO_1": {"label": "Erdgas", "spellings": ["Gas"],
                                      "definition": "Erdgas aus Lagerstätten."},
                            "OEO_2": {"label": "Heizöl", "spellings": [],
                                      "definition": "Heizöl für Heizungen."},
                            "out:total": {"label": "Summe", "spellings": [],
                                          "definition": "Alle zusammen."}}}},
        "example": {"source": "Im Jahr 2022 verbrauchte die Stadt 300 MWh "
                              "Erdgas für Wärme.",
                    "tuples": [{"value": 300, "quote": "verbrauchte die "
                                                       "Stadt 300 MWh Erdgas"}]},
        "kg": {}}]})
ENERGY = SPEC.by_uri["energy"]
SLOTS = {slot.name: slot for slot in fields.axis_slots(ENERGY)}

TITLE = Source("section", 1, "Kommunale Wärmeplanung Musterstadt\n"
                             "Erstellt von Planungsbüro Nord",
               {"document_id": 7, "page": 1})
TEXT = Source("section", 2, "Der Verbrauch sank. Im Jahr 2022 verbrauchte die "
                            "Stadt 300 MWh Erdgas. Danach kam die Sanierung.",
              {"document_id": 7, "page": 2, "section_title": "Bilanz"})
TABLE = Source("table", 3, "Tabelle 4: Verbrauch der Liegenschaften 2021\n"
                           "| Gebäude | Erdgas MWh/a | Heizöl MWh/a |\n"
                           "| --- | --- | --- |\n"
                           "| Rathaus | 1.200 | 27 |\n"
                           "| Schule | 800 / 750 | 12 |",
               {"document_id": 7, "page": 3, "section_title": "Bilanz"})


class Model:
    """The requests of a harvest answered per kind by *replies[kind]
    (payload, noted)*, a default where none is given; every request kept
    as (kind, payload, noted)."""

    DEFAULT = {"find": lambda p, n: {"found": []},
               "docfield": lambda p, n: {"found": []},
               "coord": lambda p, n: {"at": 0, "hyde": "Der Plan sagt es."},
               "search": lambda p, n: {"at": 0},
               "list": lambda p, n: {"entry": 0},
               "names": lambda p, n: {"entry": "new"},
               "check": lambda p, n: {"about": "yes"},
               "follow": lambda p, n: None}

    def __init__(self, **replies):
        self.replies = {**self.DEFAULT, **replies}
        self.calls: list = []

    def asks(self, check: bool = True) -> Asks:
        def asker(kind):
            def ask(payload, document_id, /, *, shape, example, **noted):
                self.calls.append((kind, payload, noted))
                return self.replies[kind](payload, noted)
            return ask

        def follow(kind, payload, document_id, /, *, shape, example,
                   **noted):
            noted = {**noted, "asked": kind}
            self.calls.append(("follow", payload, noted))
            return self.replies["follow"](payload, noted)
        return Asks(find=asker("find"), docfield=asker("docfield"),
                    coord=asker("coord"), list=asker("list"),
                    search=asker("search"), follow=follow,
                    names=asker("names"),
                    check=asker("check") if check else None)

    def of(self, kind: str) -> list:
        return [(payload, noted) for k, payload, noted in self.calls
                if k == kind]


def plan_of(*sources, chunk_units=8) -> Plan:
    return Plan(7, list(sources), {}, chunk_units)


def in_order(document_id, sentences, chunks):
    return list(chunks)


def reader_of(model: Model, spec=SPEC, **kw) -> Reader:
    return Reader(spec, model.asks(kw.pop("check", True)), in_order, **kw)


def coordinate_answers(**by_name):
    """A coord reply per coordinate asked, the default for any other."""
    def reply(payload, noted):
        got = by_name.get(noted.get("coordinate"))
        if got is None:
            return Model.DEFAULT["coord"](payload, noted)
        return got(payload, noted) if callable(got) else got
    return reply


# -- 4. finding ----------------------------------------------------------------

def test_a_find_is_checked_at_its_address_and_quotes_its_row():
    finds = iter([{"found": [{"at": "9.2", "words": "1.200"},
                             {"at": "3.2", "words": "999"},
                             {"at": "4.2", "words": ""},
                             {"at": "3.2", "words": "1.200"}]},
                  {"found": []}])
    model = Model(find=lambda p, n: next(finds))
    plan = plan_of(TABLE)
    reads = reader_of(model)(plan, [ENERGY])
    (claim,) = [claim for read in reads for claim in read.claims]
    assert claim["value"] == 1200 and claim["value_raw"] == "1.200"
    assert claim["quote"].endswith("| Rathaus | 1.200 | 27 |")
    assert claim["head"] == "Erdgas MWh/a"
    assert claim["at"] == {"owner": ["table", 3], "line": 3, "cell": 2}
    # What did not hold went back once, each with its reason.
    ((payload, noted),) = model.of("follow")
    assert noted["asked"] == "find"
    assert [entry["why"] for entry in payload["what"]] == [
        addressed.told(addressed.NOT_AN_ADDRESS,
                       {"at": "9.2", "words": "1.200"}),
        addressed.told(addressed.WORDS_NOT_IN_LINE,
                       {"at": "3.2", "words": "999"}),
        addressed.told(addressed.WORDS_NOT_IN_LINE,
                       {"at": "4.2", "words": ""})]
    assert reads[0].failed == {addressed.NOT_AN_ADDRESS: 1,
                               addressed.WORDS_NOT_IN_LINE: 2}


def test_a_number_keeps_its_sign_and_a_cell_of_two_numbers_holds_none():
    assert addressed.number_of("-1.155") == "-1155"
    assert addressed.number_of("750.940 kWh") == "750940"
    # the failure by construction: two numbers, or a span, are no number
    assert addressed.number_of("800 / 750") is None
    assert addressed.number_of("2019 bis 2021") is None


def test_a_quote_is_its_lines_and_a_short_one_takes_the_lines_around_it():
    """A quote names a place: the lines its address names, AND where they
    are shorter than the minimum, the shown lines of the same passage
    before them, else after them; a quote of several shown lines stands in
    what was shown."""
    title = Source("section", 1, "2018\nKommunale Wärmeplanung",
                   {"document_id": 7, "page": 1, "section_title": "Titel"})
    text = Source("section", 9, "Kurz. Im Jahr 2022 verbrauchte die Stadt "
                                "300 MWh Erdgas. Ende.",
                  {"document_id": 7, "page": 2, "section_title": "Bilanz"})

    def what_of(answer):
        model = Model(
            find=lambda p, n: {"found": [{"at": "2", "words": "300"}]}
            if n.get("owner") == 9 else {"found": []},
            coord=coordinate_answers(what=answer))
        (claim,) = [c for r in reader_of(model)(plan_of(title, text),
                                                [ENERGY]) for c in r.claims]
        return claim.get("what_state"), claim.get("what_quote")
    assert what_of({"at": "1-2", "words": ""}) == (
        fields.READ, "Kurz. Im Jahr 2022 verbrauchte die Stadt 300 MWh "
                     "Erdgas.")
    assert what_of({"at": "1", "words": "Kurz"}) == (
        fields.READ, "Kurz. Im Jahr 2022 verbrauchte die Stadt 300 MWh "
                     "Erdgas.")
    assert what_of({"at": "T1", "words": "2018"}) == (
        fields.READ, "2018 Kommunale Wärmeplanung")
    # the failure by construction: a short line whose passage shows no
    # other line names no place
    assert what_of({"at": "H1", "words": "Titel"})[0] == fields.UNBACKED


# -- 5. what a coordinate's request shows -------------------------------------

def test_a_coordinate_is_shown_its_line_and_what_lies_around_it_only():
    model = Model(find=lambda p, n: {"found": [{"at": "3.2",
                                                 "words": "1.200"}]}
                  if p["passage"]["kind"] == "table" else {"found": []})
    plan = plan_of(TITLE, TEXT, TABLE)
    plan.settings = [(units.Line(1, "Alle Werte gelten für 2021."),
                      TEXT)]
    reader_of(model)(plan, [ENERGY])
    asked = model.of("coord")
    assert asked
    for payload, _noted in asked:
        assert set(payload) <= {"value", "passage", "headings", "title_page",
                                "settings", "field", "question", "known"}
        # The table's title, its head and the value's row, nothing else.
        assert payload["passage"]["lines"] == [
            "1 Tabelle 4: Verbrauch der Liegenschaften 2021",
            "2 | Gebäude | Erdgas MWh/a | Heizöl MWh/a |",
            "3 | Rathaus | 1.200 | 27 |"]
        assert payload["settings"] == ["F1 Alle Werte gelten für 2021."]
        assert payload["title_page"][0] == "T1 Kommunale Wärmeplanung " \
                                           "Musterstadt"
    # A sentence is shown with the sentences before and after it.
    shown, payload = addressed.show_value(plan, {
        "at": {"owner": ["section", 2], "line": 2}, "value": 300})
    assert payload["passage"]["lines"] == [
        "1 Der Verbrauch sank.", "2 Im Jahr 2022 verbrauchte die Stadt 300 "
        "MWh Erdgas.", "3 Danach kam die Sanierung."]


def test_a_request_is_its_prompt_and_one_message(monkeypatch):
    from docpipe.profile import load_profile
    sent = []

    def create(**request):
        sent.append(request["messages"])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(
                content='{"at": "3", "words": "2021"}'))])
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(runner, "_client", lambda: client)
    monkeypatch.setattr(runner.trace, "event", lambda *a, **k: None)
    asks = runner.make_asks(load_profile("kwp"))
    payload = {"value": {"words": "1.200", "at": "3.2"},
               "passage": {"lines": ["3 | Rathaus | 1.200 |"]},
               "question": "Für welches Jahr gilt diese Zahl?"}
    asks.coord(payload, 7, shape=addressed.coord_format(False),
               example={"at": "3", "words": "..."})
    asks.coord({**payload, "settings": ["F1 Alles gilt für 2021."]}, 7,
               shape=addressed.coord_format(False),
               example={"at": "3", "words": "..."})
    assert [[m["role"] for m in messages] for messages in sent] == [
        ["system", "user"], ["system", "user"]]
    # Only a request that carries the settings is told what they are.
    assert '"settings"' not in sent[0][0]["content"]
    assert '"settings"' in sent[1][0]["content"]


# -- 6. the search -------------------------------------------------------------

def searching(hyde: str, probes=None):
    sentences = []

    def order(document_id, said, chunks):
        sentences.append(list(said))
        return list(chunks)
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []},
        coord=coordinate_answers(year={"at": 0, "hyde": hyde}))
    reader = Reader(SPEC, model.asks(), in_order, search_order=order,
                    probes=probes)
    counts = addressed.Counts()
    reader(plan_of(TEXT, TABLE), [ENERGY], counts=counts)
    return sentences, counts, model


def test_a_search_goes_with_the_answer_s_sentence_and_counts_a_question():
    said = "Die Verbrauchswerte der Liegenschaften gelten für 2021."
    sentences, counts, _model = searching(said)
    assert [said] in sentences and counts.questions == 0
    question = "Für welches Jahr gelten die Verbrauchswerte?"
    sentences, counts, _model = searching(question)
    assert [question] in sentences
    assert counts.questions >= 1
    # the failure by construction: without a sentence of its own the search
    # goes with the field's.
    sentences, counts, _model = searching(
        " ", probes=lambda parameter, document: ["Der Satz des Felds."])
    assert ["Der Satz des Felds."] in sentences


# -- 7. the list -----------------------------------------------------------------

def entry_of(model, slot, words, plan=None, **kw):
    reader = reader_of(model)
    return reader.entry(plan or plan_of(TEXT), ENERGY.uri, slot.name, slot,
                        words, None, addressed.Counts(), **kw)


def test_a_number_off_the_list_is_asked_once_more_and_0_is_no_entry():
    model = Model(list=lambda p, n: {"entry": 9},
                  follow=lambda p, n: {"entry": 2})
    assert entry_of(model, SLOTS["carrier"], "Heizöl", several=True) \
        == ["Heizöl"]
    ((payload, _noted),) = model.of("follow")
    assert payload["what"] == [say("not_an_option", given=9)]
    # 0 names no entry.
    assert entry_of(Model(list=lambda p, n: {"entry": 0}), SLOTS["carrier"],
                    "Fernwärme") == ""


def test_a_wording_no_entry_fits_is_kept_as_today_s_empty_answer():
    # Plan 3.5: 0 is what the empty answer was, the wording kept for the
    # vocabulary: a unit read as printed and flagged `unmapped:unit`, any
    # other coordinate's wording beside an open entry (`<axis>_seen`).
    def read(entry):
        model = Model(
            find=lambda p, n: {"found": [{"at": "2", "words": "300"}]},
            coord=coordinate_answers(
                unit={"at": "2", "words": "MWh"},
                carrier={"found": [{"at": "2", "words": "Erdgas"}]}),
            list=lambda p, n: {"entry": entry})
        reads = reader_of(model)(plan_of(TEXT), [ENERGY])
        (claim,) = [c for r in reads for c in r.claims]
        return claim, verify.verify_tuple(claim, ENERGY, TEXT.text), model
    claim, checked, model = read(0)
    assert claim["carrier_seen"] == "Erdgas" and not claim.get("carrier")
    assert "unmapped:unit:MWh" in checked.flags
    # A place that answered is searched no further.
    assert not model.of("search")
    # the failure by construction: an entry of the list is read as it
    claim, checked, _model = read(1)
    assert claim["carrier"] == "Erdgas"
    assert not claim.get("carrier_seen")
    assert not [f for f in checked.flags if f.startswith("unmapped:")]


def test_one_wording_of_one_field_is_asked_once_per_document():
    model = Model(list=lambda p, n: {"entry": [1]})
    plan = plan_of(TEXT)
    for _ in range(3):
        assert entry_of(model, SLOTS["carrier"], "Gas", plan=plan,
                        several=True) == ["Erdgas"]
    assert len(model.of("list")) == 1
    # the failure by construction: another wording is asked anew
    entry_of(model, SLOTS["carrier"], "Erdgas", plan=plan, several=True)
    assert len(model.of("list")) == 2


def test_a_long_list_shows_names_and_one_with_groups_is_asked_group_first():
    options = tuple(fields.Option(label=f"Sektor {i}", uri=f"S{i}",
                                  definition=f"Der Sektor {i}.",
                                  group="A" if i < 20 else "B")
                    for i in range(30))
    slot = SimpleNamespace(name="sector", question="Welcher Sektor?",
                           options=options)
    model = Model(list=lambda p, n: {"entry": 2} if n.get("step") == "group"
                  else {"entry": 3})
    assert entry_of(model, slot, "Sektor 22") == "Sektor 22"
    (group, ask) = [payload for payload, _ in model.of("list")]
    assert group["list"] == ["1 A", "2 B"]
    # The entries of the group chosen, ten, with what each means.
    assert len(ask["list"]) == 10 and "(means: " in ask["list"][0]
    # the failure by construction: without groups the thirty show names only
    plain = SimpleNamespace(name="sector", question="Welcher Sektor?",
                            options=tuple(fields.Option(
                                label=o.label, uri=o.uri,
                                definition=o.definition) for o in options))
    model = Model(list=lambda p, n: {"entry": 1})
    entry_of(model, plain, "Sektor 0")
    ((ask, _noted),) = model.of("list")
    assert len(ask["list"]) == 30 and "(means: " not in ask["list"][0]


# -- 8. a field asked once, the end of a search ---------------------------------

def test_a_field_asked_once_is_never_asked_per_piece_and_runs_its_ranking():
    title = SCENARIOS.by_uri["publication_title"]
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 2 + i}) for i in range(12)]
    model = Model()
    reader = reader_of(model, spec=SCENARIOS)
    reads = reader(plan_of(TITLE, *many), [title])
    assert not model.of("find")
    shown = [payload for payload, _ in model.of("docfield")]
    # The title page first, then five pieces at a time to the last one.
    assert "title_page" in shown[0] and "title_page" not in shown[1]
    assert [len(p.get("passages", {})) for p in shown] == [5, 5, 3]
    assert all(not read.claims for read in reads)


def test_a_search_ends_unstated_where_its_ranking_runs_out_or_at_its_budget():
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 4 + i}) for i in range(30)]

    def read(budget):
        model = Model(
            find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
            if p["passage"]["kind"] == "table" else {"found": []})
        reader = Reader(SPEC, model.asks(), in_order, budget=budget)
        reads = reader(plan_of(TABLE, *many), [ENERGY])
        (claim,) = [c for r in reads for c in r.claims]
        return claim, model
    claim, model = read(budget=100)
    assert claim["year_state"] == fields.SAID_UNSTATED
    # Own-passage coordinates are not searched at all.
    assert claim["unit_state"] == fields.SAID_UNSTATED
    assert not [n for _, n in model.of("search") if n["coordinate"] == "unit"]
    claim, model = read(budget=2)
    assert claim["year_state"] == fields.EXHAUSTED


def test_the_search_has_at_least_100_rounds_whatever_a_run_sets(monkeypatch):
    monkeypatch.setattr(runner, "REST_MAX_WINDOWS", 12)
    assert runner.search_rounds() == 100
    # the failure by construction: a run that sets more keeps more
    monkeypatch.setattr(runner, "REST_MAX_WINDOWS", 400)
    assert runner.search_rounds() == 400


def test_a_coordinate_request_without_an_answer_leaves_it_unanswered():
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []},
        coord=coordinate_answers(year=lambda p, n: None))
    (claim,) = [c for r in reader_of(model)(plan_of(TABLE), [ENERGY])
                for c in r.claims]
    assert claim["year_state"] == fields.UNANSWERED
    # Nothing searched for it: it was not answered, not found nowhere.
    assert not [n for _, n in model.of("search")
                if n["coordinate"] == "year"]


def test_a_piece_whose_answer_did_not_fit_is_asked_in_halves_of_its_lines():
    """A piece whose answer did not fit its room is asked in halves of its
    own lines, each with its table's title and head, AND a single line that
    does not fit is a hole of its own (`cut_off`)."""
    table = Source("table", 3, "Tabelle 4: Verbrauch 2021\n"
                               "| Gebäude | Erdgas MWh/a |\n| --- | --- |\n"
                               "| Rathaus | 1.200 |\n| Schule | 800 |\n"
                               "| Bad | 450 |",
                   {"document_id": 7, "page": 3})

    def find(payload, noted):
        rows = [line for line in payload["passage"]["lines"]
                if line.split(" ", 1)[1].startswith("| ")
                and "Gebäude" not in line]
        if len(rows) > 1:
            return "cut_off"
        number, text = rows[0].split(" ", 1)
        if "Bad" in text:
            return "cut_off"
        return {"found": [{"at": f"{number}.2",
                           "words": text.split("|")[2].strip()}]}
    model = Model(find=find)
    reads = reader_of(model)(plan_of(table), [ENERGY])
    values = sorted(c["value"] for r in reads for c in r.claims)
    assert values == [800, 1200]
    # Three rows: cut, then halves of one and two rows, the two cut again.
    assert len(model.of("find")) == 5
    shown = [p["passage"]["lines"][:2] for p, _ in model.of("find")]
    assert all(head == ["1 Tabelle 4: Verbrauch 2021",
                        "2 | Gebäude | Erdgas MWh/a |"] for head in shown)
    # the failure by construction: the row that never fits is a hole
    assert [why for r in reads for why in r.lost] == [addressed.CUT]


# -- 9. names of two works -------------------------------------------------------

def test_two_equal_names_of_two_works_are_two_entries_shown_by_work():
    works = Names("work", addressed.Entry("this publication",
                                          "this publication", 0))
    works.add("IRENA 2018")
    works.add("IEA 2020")
    names = Names("scenario")
    assert names.add("Reference", work=3) == 1
    assert names.add("Reference", work=2) == 2
    assert names.add("Reference", work=3) == 1
    assert [e.label for e in names.entries] == ["Reference", "Reference (2)"]
    assert names.shown(works) == [(2, "IRENA 2018: Reference"),
                                  (1, "IEA 2020: Reference")]


# -- 11. an answer asked once more ------------------------------------------------

def test_an_answer_that_does_not_hold_is_asked_once_more_then_unbacked():
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []},
        coord=coordinate_answers(year={"at": "1", "words": "1999"}),
        follow=lambda p, n: {"at": "1", "words": "1998"}
        if n.get("coordinate") == "year" else None)
    reads = reader_of(model)(plan_of(TABLE), [ENERGY])
    (claim,) = [c for r in reads for c in r.claims]
    assert claim["year_state"] == fields.UNBACKED
    asked_again = [n for _, n in model.of("follow")
                   if n.get("coordinate") == "year"]
    assert len(asked_again) == 1
    # the failure by construction: an answer that holds is asked nothing more
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []},
        coord=coordinate_answers(year={"at": "1", "words": "2021"}))
    reads = reader_of(model)(plan_of(TABLE), [ENERGY])
    (claim,) = [c for r in reads for c in r.claims]
    assert claim["year"] == 2021 and claim["year_state"] == fields.READ
    assert not [n for _, n in model.of("follow")
                if n.get("coordinate") == "year"]


# -- a coordinate that closes those after it --------------------------------------

def test_a_year_read_as_another_year_is_not_asked_its_scenario():
    year = SCENARIOS.by_uri["scenario_year"]
    text = Source("section", 4, "Published in the year 2018 by BNEF.",
                  {"document_id": 7, "page": 2})

    def read(kind_entry):
        model = Model(
            find=lambda p, n: {"found": [{"at": "1", "words": "2018"}]},
            coord=coordinate_answers(year_kind={"at": "1",
                                                "words": "Published"}),
            list=lambda p, n: {"entry": kind_entry})
        reads = reader_of(model, spec=SCENARIOS)(plan_of(text), [year])
        (claim,) = [c for r in reads for c in r.claims]
        return claim, model
    other = next(i for i, o in enumerate(
        next(s for s in fields.axis_slots(year)
             if s.name == "year_kind").options, start=1)
        if o.uri == "out:other_year")
    claim, model = read(other)
    assert claim["scenario_state"] == fields.OUT_OF_SLICE
    assert not [n for _, n in model.of("coord")
                if n["coordinate"] == "scenario"]
    claim, model = read(3 - other)
    assert [n for _, n in model.of("coord") if n["coordinate"] == "scenario"]


# -- 13. the works beside the publication -----------------------------------------

def test_a_work_is_asked_its_details_at_its_line_and_stays_out_of_the_graph():
    line = Source("table", 12, "Table 4: Studies compared\n"
                               "| Study | Published by |\n| --- | --- |\n"
                               "| TYNDP 2018 Scenario Report | ENTSO-E, 2018 |",
                  {"document_id": 7, "page": 5})
    detail = {"publication_title": {"at": "3.1",
                                    "words": "TYNDP 2018 Scenario Report"},
              "study_organisation": {"at": "3.2", "words": "ENTSO-E"},
              "publication_date": {"at": "3.2", "words": "2018"}}
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.1", "words": "TYNDP 2018 "
                                                           "Scenario Report"}]}
        if n.get("parameter") == "work" else {"found": []},
        coord=lambda p, n: detail.get(n["parameter"], {"at": 0, "hyde": "x"})
        if n.get("coordinate") == "work" else {"at": 0, "hyde": "x"})
    reader = reader_of(model, spec=SCENARIOS,
                       works=scenarios_extraction.WORKS)
    reads = reader(plan_of(TITLE, line), [])
    rows = {claim["parameter"] if "parameter" in claim
            else read.batch.parameter.uri: claim
            for read in reads for claim in read.claims}
    assert set(rows) == {"publication_title", "study_organisation",
                         "publication_date"}
    assert rows["study_organisation"]["value"] == "ENTSO-E"
    assert rows["publication_title"]["work_means"] == [
        "TYNDP 2018 Scenario Report"]
    # Never asked per piece as a field of this publication.
    assert {n["parameter"] for _, n in model.of("find")} == {"work"}
    assert not model.of("docfield")
    # A value of another work does not reach the graph.
    another = next(o.label for s in fields.axis_slots(
        SCENARIOS.by_uri["publication_title"]) if s.name == "work"
        for o in s.options if o.uri == addressed.ANOTHER_WORK)
    for parameter, claim in rows.items():
        assert claim["work"] == another
        assert kg.held_back({"parameter": parameter, **claim}) \
            == f"work:{another}"


# -- 14. words of a group of scenarios --------------------------------------------

def test_group_words_take_their_members_except_for_a_description():
    year = SCENARIOS.by_uri["scenario_year"]
    abstract = SCENARIOS.by_uri["scenario_abstract"]
    scenario_year = next(o.label for s in fields.axis_slots(year)
                         if s.name == "year_kind" for o in s.options
                         if o.uri == s.keep)
    text = Source("section", 4, "All scenarios run to the year 2050 and "
                                "assume rising carbon prices.",
                  {"document_id": 7, "page": 2})
    plan = plan_of(text)
    reader = None

    def names_reply(payload, noted):
        if noted.get("kind") == "work":
            return {"entry": 1}
        if isinstance(payload.get("list"), list) and len(payload["list"]) > 2 \
                and isinstance(payload["name"], str) \
                and "All scenarios" in payload["name"]:
            # the two scenarios after the two entries beside the names
            return {"entry": [3, 4]} if noted.get("parameter") \
                == year.uri else {"entry": 2}
        return {"entry": "new"}
    model = Model(
        find=lambda p, n: {"found": [{"at": "1", "words": "2050"}]}
        if n.get("parameter") == year.uri else
        {"found": [{"at": "1", "words": "assume rising carbon prices"}]}
        if n.get("parameter") == abstract.uri else {"found": []},
        coord=coordinate_answers(
            year_kind={"at": "1", "words": "run to the year"},
            scenario={"at": "1", "words": "All scenarios"}),
        list=lambda p, n: {"entry": next(
            i for i, line in enumerate(p["list"], start=1)
            if "scenario year" in line)},
        names=names_reply)
    reader = reader_of(model, spec=SCENARIOS)
    # The document's list holds two scenarios already.
    reader.lists_of(plan)
    plan.names["scenario"].add("Low demand")
    plan.names["scenario"].add("High demand")
    reads = reader(plan, [year, abstract])
    years = [c for r in reads if r.batch.parameter is year for c in r.claims]
    assert sorted(c["scenario_means"][0] for c in years) == [
        "High demand", "Low demand"]
    assert {c["scenario"] for c in years} == {addressed.SEVERAL}
    assert all(c["year_kind"] == scenario_year for c in years)
    (described,) = [c for r in reads if r.batch.parameter is abstract
                    for c in r.claims]
    assert described["scenario"] == addressed.SEVERAL
    assert not described.get("scenario_means")
    assert kg.scenario_names({"parameter": abstract.uri, **described}) == []
    assert sorted(kg.scenario_names({"parameter": year.uri, **c})[0]
                  for c in years) == ["High demand", "Low demand"]


# -- 10. a figure transcribed once --------------------------------------------

FIGURE = Source("figure", 5, "Abbildung 3: Wärmebedarf nach Energieträger\n"
                             "Das Balkendiagramm zeigt den Bedarf.",
                {"document_id": 7, "page": 4})
LINES = ["Abbildung 3: Wärmebedarf nach Energieträger 2021",
         "Erdgas: 1.200 MWh", "Heizöl: 27 MWh"]


def transcripts(store, asked: list, prompt="p1", image="img1"):
    def ask(source, document_id):
        asked.append(source.owner_id)
        return {"lines": LINES}
    return addressed.Transcripts(ask, store, prompt, lambda source: image)


def test_a_figure_is_transcribed_once_and_its_value_is_drawn(tmp_path):
    asked: list = []
    got, n = transcripts(tmp_path, asked)(7, [FIGURE])
    assert got == {5: LINES} and n == 1 and asked == [5]
    # A second run with the same image and prompt asks nothing.
    again, n = transcripts(tmp_path, asked)(7, [FIGURE])
    assert again == {5: LINES} and n == 0 and asked == [5]
    # the failure by construction: another prompt or another image is asked
    assert transcripts(tmp_path, asked, prompt="p2")(7, [FIGURE])[1] == 1
    assert transcripts(tmp_path, asked, image="img2")(7, [FIGURE])[1] == 1
    # A value read off it stands in a line of the transcription, drawn,
    # and is a C.
    model = Model(find=lambda p, n: {"found": [{"at": "2",
                                                 "words": "1.200"}]})
    plan = Plan(7, [FIGURE], got, 8)
    (claim,) = [c for r in reader_of(model)(plan, [ENERGY])
                for c in r.claims]
    assert claim["drawn"] is True and claim["quote"] == "Erdgas: 1.200 MWh"
    checked = verify.verify_tuple(claim, ENERGY, "\n".join(LINES),
                                  owner_kind="figure")
    row = {**checked.tuple, "flags": checked.flags, "tier": checked.tier}
    assert trust.trust(row)["level"] == trust.LEVEL_C


# -- 12. the reasons ------------------------------------------------------------

def test_the_reasons_of_an_address_stand_and_those_of_a_quote_are_gone():
    assert {addressed.NOT_AN_ADDRESS, addressed.WORDS_NOT_IN_LINE} \
        <= set(schema.DROP_REASONS)
    assert {"quote_not_unique", "value_not_once"}.isdisjoint(
        wording.REQUIRED)
    assert {"not_an_address", "words_not_in_line"} <= wording.REQUIRED
