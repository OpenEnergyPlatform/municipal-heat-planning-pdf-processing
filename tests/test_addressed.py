"""One document read in pieces of numbered lines, one question per request,
every answer an address (addressed.py, owner decisions 2026-11-08 and
2026-11-09), each promise with a case that breaks it by construction.

3. A figure is transcribed once into its caption and its numbers, AND one
   kept in the form of one list is transcribed again.
4. A find whose address names no shown line is `not_an_address`, AND one
   whose words do not stand in its line `words_not_in_line`, AND a cell with
   two numbers is asked again; a table value's quote is its row, AND its
   `head` the head of its column. A field with a list is asked with it, AND
   its find names the number of its entry, AND a number off the list is
   `not_an_option` and asked again, AND no list request follows a find with
   its number, AND the find of a group asks its member.
5. A coordinate's request is its instruction and exactly one message, AND
   it shows of the plan only the value's line with its table's title and
   head, or the sentences beside it, the headings, the title page, the
   settings and what the value has read. Every request that finds values
   shows two replies: a find at an address it shows, and none.
6. The search after a coordinate nothing shown says goes with a sentence a
   request of its own writes (`phrase`) from the value's words and lines and
   the question, once per field, coordinate and wording, AND a coordinate's
   0 carries no sentence and is not asked again for one, AND a sentence
   that is a question is searched and counted, AND without a sentence the
   search goes with the field's.
7. A number off the list is `not_an_option` and asked once more, AND 0 is no
   entry, AND one wording of one field is asked once per document, AND a
   list longer than a request shows with meanings shows names only, AND one
   whose entries name groups is asked group first, AND the list is shown as
   it is, never with an earlier wording.
8. A field a document has once is never asked per piece, AND is asked over
   at most the run's budget of pieces, five a request, a field with a list
   over twice that.
9. Two equal names of two works are two entries, AND the list is shown by
   work. Words that name no such thing (0) are no entry, AND the value keeps
   an empty note the graph makes no scenario of, AND a name of an entry
   takes the work its entry was read with, AND a new name without a work is
   no entry of this publication.
10. A search shows at most its budget of pieces, the best of each kind up to
    its share, then the best of any kind, ordered once by the reranker, five
    a request, AND a piece a reply fetches comes first and outside the
    budget, AND no piece twice; it ends `unstated` where no piece is left,
    `exhausted` where the budget left some, `unbacked` where a find does not
    hold after its follow-up. The run's settings set the budget, the shares,
    the pieces a request and the attempts, by default 50, 20/15/15, 5 and 3.
11. An answer that does not hold is asked once more, once, AND then the
    coordinate is `unbacked`.
13. Each piece is asked once whose results its lines state (`work`), AND a
    value in the line of a work takes it, read, quoted with that line, AND a
    heading's work covers the piece, AND a value of no work's line is this
    publication's only with the line that says so, AND else it asks its
    work as a choice of the document's works, 0 `unstated` and never
    searched, AND no value takes a work without a line. The details of the
    new works are asked side by side, all before any value is read, and
    their values do not reach the graph.
14. Words of a group of scenarios take the members the document names, one
    row each, where the field takes groups, AND stay with the group's words
    for a description, AND such a description reaches no scenario.
A coordinate that reads a value as another entry than the one it must have
closes those after it (`out_of_slice`), and the reasons a find or a
coordinate can fail stand in the trace schema.
"""
import collections
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

from docpipe.extraction import (addressed, fields, flow, graph, runner,
                                schema, trust, units, verify, wording)
from docpipe.extraction.addressed import Asks, Names, Plan, Reader
from docpipe.extraction.bricks import Call
from docpipe.extraction.pipeline import Source
from docpipe.profile import load_profile
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.wording import say
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
                                                       "Stadt 300 MWh Erdgas"}]}}]})
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
               "coord": lambda p, n: {"at": 0},
               "search": lambda p, n: {"at": 0},
               "list": lambda p, n: {"entry": 0},
               "names": lambda p, n: {"entry": "new"},
               "check": lambda p, n: {"about": "yes"},
               "work": lambda p, n: {"found": [], "own": {"at": 0}},
               "phrase": lambda p, n: {"phrase": "Der Plan sagt es."},
               "follow": lambda p, n: None}

    def __init__(self, **replies):
        self.replies = {**self.DEFAULT, **replies}
        self.calls: list = []
        self.examples: list = []

    def asks(self, check: bool = True) -> Asks:
        def asker(kind):
            def ask(payload, document_id, /, *, shape, example, **noted):
                self.calls.append((kind, payload, noted))
                self.examples.append((kind, example))
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
                    check=asker("check") if check else None,
                    work=asker("work"), phrase=asker("phrase"))

    def of(self, kind: str) -> list:
        return [(payload, noted) for k, payload, noted in self.calls
                if k == kind]


def plan_of(*sources, chunk_units=8) -> Plan:
    return Plan(7, list(sources), {}, chunk_units)


def in_order(document_id, sentences, chunks):
    return list(chunks)


def flow_of(spec):
    """The drawing a reading of *spec* reads by: a scenario paper's is the
    flow of its profile, which draws the steps only scenario papers take
    (owner decision 2026-11-12), any other the default's."""
    if spec is SCENARIOS:
        from docpipe.extraction import flow as flow_map
        from docpipe.profile import load_profile
        return flow_map.tree_of(load_profile("scenarios"))
    return None


def reader_of(model: Model, spec=SPEC, **kw) -> Reader:
    kw.setdefault("flow", flow_of(spec))
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


def test_the_questions_before_about_a_value_are_messages_of_their_own(
        monkeypatch):
    """Where the rule `conversation` keeps the questions about a value
    (owner decision 2026-11-07), each earlier question and its answer go
    before the request as messages of their own, a follow-up with its
    words after it, AND the request's own message is its question alone;
    a request without them is one message."""
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
    first = {"value": {"words": "1.200", "at": "3.2"},
             "passage": {"lines": ["3 | Rathaus | 1.200 |"]},
             "question": "Für welches Jahr gilt diese Zahl?"}
    again = {**first, "answer": {"at": "9"}, "what": ["nichts"]}
    later = {**first, "question": "Welcher Energieträger?",
             "conversation": [
                 {"asked": "year", "sent": first, "answer": {"at": "9"}},
                 {"asked": "year", "follow_up": ["nichts"], "sent": again,
                  "answer": {"at": "3", "words": "2021"}}]}
    form, example = addressed.coord_format(False), {"at": "3", "words": "."}
    asks.coord(later, 7, shape=form, example=example)
    assert [m["role"] for m in sent[0]] == [
        "system", "user", "assistant", "user", "assistant", "user"]
    assert json.loads(sent[0][1]["content"]) == first
    assert json.loads(sent[0][2]["content"]) == {"at": "9"}
    shown = json.dumps(again, ensure_ascii=False, indent=1)
    assert sent[0][3]["content"].startswith(shown + "\n\n")
    assert json.loads(sent[0][4]["content"]) == {"at": "3", "words": "2021"}
    own = json.loads(sent[0][5]["content"])
    assert own == {key: value for key, value in later.items()
                   if key != "conversation"}
    asks.coord(first, 7, shape=form, example=example)
    assert [m["role"] for m in sent[1]] == ["system", "user"]
    assert json.loads(sent[1][1]["content"]) == first


# -- 6. the search -------------------------------------------------------------

def searching(phrase: str, probes=None, second: str = ""):
    """(the sentences a search was ordered with, the counts, the model) of a
    plan whose table value's year and carrier nothing shown says, the
    sentence written by a request of its own (*phrase*); with *second* a
    second table with a value of these words."""
    sentences = []

    def order(document_id, said, chunks):
        sentences.append(list(said))
        return list(chunks)
    other = Source("table", 4, "Tabelle 5: Verbrauch der Bäder\n"
                               "| Gebäude | Erdgas MWh/a |\n| --- | --- |\n"
                               f"| Bad | {second} |",
                   {"document_id": 7, "page": 5, "section_title": "Bilanz"})

    def find(payload, noted):
        if noted.get("owner") == 3:
            return {"found": [{"at": "3.2", "words": "1.200"}]}
        if second and noted.get("owner") == 4:
            return {"found": [{"at": "3.2", "words": second}]}
        return {"found": []}
    model = Model(find=find, phrase=lambda p, n: {"phrase": phrase})
    reader = Reader(SPEC, model.asks(), in_order, search_order=order,
                    probes=probes)
    counts = addressed.Counts()
    sources = [TEXT, TABLE] + ([other] if second else [])
    reader(plan_of(*sources), [ENERGY], counts=counts)
    return sentences, counts, model


def test_a_search_goes_with_the_sentence_a_request_of_its_own_writes():
    said = "Die Verbrauchswerte der Liegenschaften gelten für 2021."
    sentences, counts, model = searching(said)
    assert [said] in sentences and counts.questions == 0
    # The sentence is asked with the value's words, its lines and the
    # question of the coordinate.
    (payload,) = [p for p, n in model.of("phrase")
                  if n["coordinate"] == "year"]
    assert payload["value"]["words"] == "1.200"
    assert payload["value"]["lines"][-1] == "| Rathaus | 1.200 | 27 |"
    assert payload["question"] == SLOTS["year"].question
    # A coordinate's 0 carries no sentence and is not asked again for one.
    assert "hyde" not in json.dumps(addressed.coord_format(False))
    assert not [n for _, n in model.of("follow")
                if n.get("coordinate") == "year"]
    question = "Für welches Jahr gelten die Verbrauchswerte?"
    sentences, counts, _model = searching(question)
    assert [question] in sentences
    assert counts.questions >= 1
    # the failure by construction: without a sentence of its own the search
    # goes with the field's.
    sentences, counts, _model = searching(
        " ", probes=lambda parameter, document: ["Der Satz des Felds."])
    assert ["Der Satz des Felds."] in sentences


def test_one_wording_asks_its_sentence_once_per_coordinate_and_document():
    def asked(second):
        _sentences, _counts, model = searching("Ein Satz.", second=second)
        return collections.Counter(n["coordinate"]
                                   for _, n in model.of("phrase"))
    # Two values of the same words: one sentence per coordinate.
    assert asked("1.200") == {"year": 1, "carrier": 1}
    # the failure by construction: other words are a sentence of their own
    assert asked("950") == {"year": 2, "carrier": 2}


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
    # How long a list may be to show what its entries mean is the flow's
    # number: a reading told thirty shows it for these thirty, in one step.
    def told(meanings):
        return dataclasses.replace(flow.default(), list_meanings=meanings)
    model = Model(list=lambda p, n: {"entry": 1})
    reader_of(model, numbers=told(30)).entry(
        plan_of(TEXT), ENERGY.uri, slot.name, slot, "Sektor 0", None,
        addressed.Counts())
    ((ask, _noted),) = model.of("list")
    assert len(ask["list"]) == 30 and "(means: " in ask["list"][0]
    # And the list a field's finds name their entry in is shown by it too.
    kind = SCENARIOS.by_uri["scenario_type"]
    entries = len(fields.value_choice(kind).options)

    def lines(meanings):
        return reader_of(Model(), spec=SCENARIOS,
                         numbers=told(meanings)).listed(kind)[0]
    assert "(means: " in lines(entries)[0]
    assert "(means: " not in lines(entries - 1)[0]


# -- 8. a field asked once, the end of a search ---------------------------------

def test_a_field_asked_once_is_never_asked_per_piece_and_runs_its_budget():
    title = SCENARIOS.by_uri["publication_title"]
    sector = SCENARIOS.by_uri["study_sector"]
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 2 + i}) for i in range(12)]
    model = Model()
    reader = reader_of(model, spec=SCENARIOS)
    reads = reader(plan_of(TITLE, *many), [title])
    assert not model.of("find")
    shown = [payload for payload, _ in model.of("docfield")]
    # The title page first, then five pieces at a time to the last one:
    # thirteen pieces are three requests.
    assert "title_page" in shown[0] and "title_page" not in shown[1]
    assert [len(p.get("passages", {})) for p in shown] == [5, 5, 3]
    assert all(not read.claims for read in reads)

    # At most the run's budget of pieces, a field with a list twice that.
    def pieces(field_):
        model = Model()
        reader_of(model, spec=SCENARIOS, budget=4)(plan_of(TITLE, *many),
                                                   [field_])
        return [len(p.get("passages", {})) for p, _ in model.of("docfield")]
    assert pieces(title) == [4]
    assert pieces(sector) == [5, 3]


def test_a_search_ends_unstated_where_its_ranking_runs_out_or_at_its_budget():
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 4 + i}) for i in range(30)]

    def read(budget, **replies):
        model = Model(
            find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
            if p["passage"]["kind"] == "table" else {"found": []},
            **replies)
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
    # A find that does not hold after its follow-up ends the search
    # `unbacked`, and nothing more is shown.
    claim, model = read(
        budget=100,
        search=lambda p, n: {"at": "A1", "words": "1999"}
        if n["coordinate"] == "year" else {"at": 0},
        follow=lambda p, n: {"at": "A1", "words": "1998"}
        if n.get("coordinate") == "year" else None)
    assert claim["year_state"] == fields.UNBACKED
    assert len([n for _, n in model.of("search")
                if n["coordinate"] == "year"]) == 1


def test_a_reading_given_no_numbers_takes_the_default_flow_s():
    numbers = flow.default()
    reader = reader_of(Model())
    assert (reader.budget, reader.shares, reader.per_request) == (
        numbers.search_pieces, numbers.shares(), numbers.search_per_request)
    # the failure by construction: the numbers it is given are the ones it
    # reads with, and what a search is given itself wins over them
    mine = dataclasses.replace(numbers, search_pieces=7, search_tables=1,
                               search_figures=2, search_text=3,
                               search_per_request=2)
    reader = reader_of(Model(), numbers=mine)
    assert (reader.budget, reader.shares, reader.per_request) == (
        7, {"table": 1, "figure": 2, "section": 3}, 2)
    assert reader_of(Model(), numbers=mine, budget=9).budget == 9


def test_a_field_with_a_list_reads_the_budget_times_the_flow_s_factor():
    sector = SCENARIOS.by_uri["study_sector"]
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 2 + i}) for i in range(12)]

    def pieces(factor):
        model = Model()
        numbers = dataclasses.replace(flow.default(),
                                      listed_field_factor=factor)
        reader_of(model, spec=SCENARIOS, budget=4, numbers=numbers)(
            plan_of(TITLE, *many), [sector])
        return [len(p.get("passages", {})) for p, _ in model.of("docfield")]
    assert pieces(3) == [5, 5, 2]
    # the failure by construction: a factor of one reads the budget itself
    assert pieces(1) == [4]


def test_an_answer_that_does_not_hold_is_asked_again_as_often_as_the_flow_says():
    # A find at a line the request did not show, and follow-ups that name
    # other such lines until the last one names the value's.
    bad = [{"found": [{"at": f"{line}.2", "words": "1.200"}]}
           for line in (9, 8, 7)]
    good = {"found": [{"at": "3.2", "words": "1.200"}]}

    def read(follow_ups, answers):
        left = iter(answers)
        model = Model(find=lambda p, n: bad[0], follow=lambda p, n: next(left))
        numbers = dataclasses.replace(flow.default(), follow_ups=follow_ups)
        reads = reader_of(model, numbers=numbers)(plan_of(TABLE), [ENERGY])
        return model, [claim for read in reads for claim in read.claims]
    model, claims = read(2, [bad[1], good])
    first, second = [payload for payload, noted in model.of("follow")
                     if noted["asked"] == "find"]
    assert [claim["value"] for claim in claims] == [1200]
    # each is asked with the answer before it and why that did not hold
    assert first["answer"] == bad[0] and second["answer"] == bad[1]
    assert "8.2" in json.dumps(second["what"])
    # the failures by construction: with one follow-up the second is never
    # asked and nothing is read, with none no follow-up is asked at all
    model, claims = read(1, [bad[1], good])
    assert len(model.of("follow")) == 1 and not claims
    model, claims = read(0, [])
    assert not model.of("follow") and not claims


def test_a_coordinate_is_asked_again_as_often_as_the_flow_says():
    def read(follow_ups, answers):
        left = iter(answers)
        model = Model(
            find=lambda p, n: {"found": [{"at": "2", "words": "300"}]},
            coord=coordinate_answers(year={"at": "2", "words": "2021"}),
            follow=lambda p, n: next(left) if n.get("coordinate") == "year"
            else None)
        numbers = dataclasses.replace(flow.default(), follow_ups=follow_ups)
        reads = reader_of(model, numbers=numbers)(plan_of(TEXT), [ENERGY])
        (claim,) = [claim for read in reads for claim in read.claims]
        asked = [payload for payload, noted in model.of("follow")
                 if noted.get("coordinate") == "year"]
        return claim, asked
    wrong, right = {"at": "2", "words": "2020"}, {"at": "2", "words": "2022"}
    claim, asked = read(2, [wrong, right])
    assert (claim["year"], claim["year_state"]) == (2022, fields.READ)
    assert [payload["answer"]["words"] for payload in asked] == ["2021",
                                                                 "2020"]
    # the failures by construction: one follow-up leaves it unbacked, and
    # so does none, which asks nothing again
    claim, asked = read(1, [wrong, right])
    assert claim["year_state"] == fields.UNBACKED and len(asked) == 1
    claim, asked = read(0, [])
    assert claim["year_state"] == fields.UNBACKED and not asked


def test_every_place_that_asks_again_does_so_as_often_as_the_flow_says():
    # An answer that does not hold at each of the seven places, and
    # follow-ups that never hold either.
    again = {"find": {"found": [{"at": "9.2", "words": "1.200"}]},
             "docfield": {"found": [{"at": "99", "words": "Titel"}]},
             "work": {"found": [{"at": "9.9", "words": "IRENA 2018"}],
                      "own": {"at": 0}},
             "list": {"entry": 9}, "names": {"entry": 99}}

    def follow(payload, noted):
        if noted["asked"] == "coord":
            return {"entry": 99} if noted["coordinate"] == "work" \
                else {"at": "1", "words": "1999"}
        return again[noted["asked"]]

    def asked(follow_ups) -> dict:
        numbers = dataclasses.replace(flow.default(), follow_ups=follow_ups)
        models = []

        def model(**replies):
            models.append(Model(follow=follow, **replies))
            return models[-1]
        # a value and one of its coordinates
        reader_of(model(
            find=lambda p, n: {"found": [{"at": "9.2", "words": "1.200"},
                                         {"at": "3.2", "words": "1.200"}]}
            if p["passage"]["kind"] == "table" else {"found": []},
            coord=coordinate_answers(year={"at": "1", "words": "1999"})),
            numbers=numbers)(plan_of(TABLE), [ENERGY])
        # an entry of a list
        reader_of(model(list=lambda p, n: {"entry": 9}),
                  numbers=numbers).entry(
            plan_of(TEXT), ENERGY.uri, "carrier", SLOTS["carrier"], "Kohle",
            None, addressed.Counts(), several=True)
        # a field the document has once
        reader_of(model(docfield=lambda p, n: again["docfield"]),
                  spec=SCENARIOS, numbers=numbers)(
            plan_of(TITLE), [SCENARIOS.by_uri["publication_title"]])
        # the work of a piece, a name of the document's list, the work of
        # a value
        label = SCENARIOS.by_uri["scenario_label"]
        reader_of(model(
            work=lambda p, n: again["work"],
            find=lambda p, n: {"found": [{"at": at, "words": words}
                                         for at, words in NAMES_IN.get(
                                             n.get("owner"), ())]}
            if n.get("parameter") == label.uri else {"found": []},
            names=lambda p, n: {"entry": 99},
            coord=lambda p, n: {"entry": 99} if "list" in p else {"at": 0}),
            spec=SCENARIOS, works=SCENARIOS.works, numbers=numbers)(
            plan_of(*WORK_PLAN), [label])
        return dict(collections.Counter(
            "a value's work" if noted["asked"] == "coord"
            and noted["coordinate"] == "work" else noted["asked"]
            for one in models for _, noted in one.of("follow")))
    once = asked(1)
    assert set(once) == {"find", "docfield", "list", "names", "coord",
                         "work", "a value's work"}
    assert asked(2) == {place: 2 * n for place, n in once.items()}
    # the failure by construction: where the flow says none, no place asks
    assert asked(0) == {}


def test_a_search_notes_which_pieces_each_request_shows():
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 4 + i}) for i in range(12)]
    fetch = iter([{"at": 0, "more": [{"get": "search",
                                      "pattern": "Abschnitt 11[.]"}]}])
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []},
        search=lambda p, n: next(fetch, {"at": 0})
        if n["coordinate"] == "year" else {"at": 0})
    reader_of(model)(plan_of(many[0], TABLE, *many[1:]), [ENERGY])
    shows = [noted["shows"] for _, noted in model.of("search")
             if noted["coordinate"] == "year"]
    # the pieces beside the value, then what its reply fetched, then the
    # pieces of the search's budget
    assert shows[:2] == ["near", "fetched"]
    assert set(shows[2:]) == {"found"} and len(shows) > 2


def test_a_search_shows_its_budget_by_kind_first_then_the_best_of_any():
    def ranked(kinds):
        return [SimpleNamespace(passage=SimpleNamespace(kind=kind), key=(i,))
                for i, kind in enumerate(kinds)]
    shares = {"table": 20, "figure": 15, "section": 15}
    order = ranked(["section"] * 40 + ["table"] * 30 + ["figure"] * 30)
    got = addressed.budgeted(order, 50, shares)
    assert collections.Counter(c.passage.kind for c in got) == {
        "table": 20, "figure": 15, "section": 15}
    assert got == [c for c in order if c in got]
    # A document of three table pieces still shows fifty, the best of the
    # rest of any kind.
    few = ranked(["section"] * 80 + ["table"] * 3)
    got = addressed.budgeted(few, 50, shares)
    assert len(got) == 50
    assert sum(c.passage.kind == "table" for c in got) == 3
    # the failure by construction: fewer pieces than the budget are all
    # shown, each once
    small = ranked(["section"] * 7)
    assert addressed.budgeted(small, 50, shares) == small


def test_a_search_reranks_its_budget_once_and_shows_no_piece_twice():
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 10 + i}) for i in range(30)]
    reranked = []

    def rerank(document_id, sentences, chunks):
        reranked.append(len(chunks))
        return list(reversed(chunks))
    fetch = iter([{"at": 0, "more": [{"get": "search",
                                      "pattern": "Abschnitt 29[.]"}]}])
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if n.get("owner") == 3 else {"found": []},
        search=lambda p, n: next(fetch, {"at": 0})
        if n["coordinate"] == "year" else {"at": 0})
    reader = Reader(SPEC, model.asks(), in_order, rerank=rerank, budget=10)
    (claim,) = [c for r in reader(plan_of(TABLE, *many), [ENERGY])
                for c in r.claims]
    pages = [[block["page"] for block in p["passages"].values()]
             for p, n in model.of("search") if n["coordinate"] == "year"]
    # The piece after the value's, the piece its answer fetched, then the
    # budget of ten in the reranker's order, five a request; the value's
    # own piece and the pieces shown before are not shown again.
    assert pages == [[10], [39], [18, 17, 16, 15, 14], [13, 12, 11]]
    # One order of the reranker per search, of the budget's pieces.
    assert reranked == [10, 10]
    # the failure by construction: pieces of the plan stay unshown, so the
    # budget, not the plan, ended it.
    assert claim["year_state"] == fields.EXHAUSTED


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


# -- 13. the work of a value --------------------------------------------------------

WORK_PLAN = (
    Source("section", 1, "Net zero pathways for Europe",
           {"document_id": 7, "page": 1}),
    Source("table", 12, "Table 7: Studies compared\n"
                        "| Study | Scenario | 2050 |\n| --- | --- | --- |\n"
                        "| IRENA 2018 | REmap | 80 |\n"
                        "| IEA 2020 | NZE | 90 |",
           {"document_id": 7, "page": 5}),
    Source("section", 20, "Our scenarios are Central and High.",
           {"document_id": 7, "page": 6, "section_title": "4 Results"}),
    Source("section", 30, "The Delayed case reaches net zero in 2060.",
           {"document_id": 7, "page": 7, "section_title": "5 Outlook"}),
    Source("section", 40, "Its scenario Tech15 is the most ambitious.",
           {"document_id": 7, "page": 8,
            "section_title": "EC 2018 - A Clean Planet for all"}))
# The scenario names each passage of WORK_PLAN prints, by its owner.
NAMES_IN = {12: [("3.2", "REmap"), ("4.2", "NZE")], 20: [("1", "Central")],
            30: [("1", "Delayed")], 40: [("1", "Tech15")]}


def work_of_piece(payload, noted):
    """What a piece's work request answers in WORK_PLAN: the studies of the
    table row by row, the work a heading names, the line that says the
    publication's own scenarios, nothing elsewhere."""
    owner = noted.get("owner")
    if owner == 12:
        return {"found": [{"at": "3.1", "words": "IRENA 2018"},
                          {"at": "4.1", "words": "IEA 2020"}],
                "own": {"at": 0}}
    if owner == 40:
        heading = next(line for line in payload["headings"]
                       if "EC 2018" in line)
        return {"found": [{"at": heading.split(" ", 1)[0],
                           "words": "EC 2018"}], "own": {"at": 0}}
    if owner == 20:
        return {"found": [], "own": {"at": "1", "words": "Our scenarios"}}
    return {"found": [], "own": {"at": 0}}


def read_works(choice, each=None, detail=None):
    """(the scenario names read in WORK_PLAN by their words, the model, the
    reads): a value no line attributes answers *choice* when asked its
    work, a detail of a new work *detail(payload, noted)*."""
    label = SCENARIOS.by_uri["scenario_label"]

    def coord(payload, noted):
        if "list" in payload:
            return choice
        if "work" in payload and detail is not None:
            return detail(payload, noted)
        return {"at": 0}
    model = Model(
        work=work_of_piece,
        find=lambda p, n: {"found": [{"at": at, "words": words}
                                     for at, words in NAMES_IN.get(
                                         n.get("owner"), ())]}
        if n.get("parameter") == label.uri else {"found": []},
        coord=coord)
    reader = reader_of(model, spec=SCENARIOS,
                       works=SCENARIOS.works,
                       **({"each": each} if each is not None else {}))
    reads = reader(plan_of(*WORK_PLAN), [label])
    names = {c["value"]: c for r in reads if r.batch.parameter is label
             for c in r.claims}
    return names, model, reads


def work_label(uri: str) -> str:
    return next(o.label for s in fields.axis_slots(
        SCENARIOS.by_uri["publication_title"]) if s.name == "work"
        for o in s.options if o.uri == uri)


def test_a_value_takes_the_work_of_its_line_and_asks_only_where_none_shows():
    names, model, _reads = read_works({"entry": 0})
    another = work_label(addressed.ANOTHER_WORK)
    this = work_label(addressed.THIS_PUBLICATION)
    # Each piece is asked once.
    pieces = plan_of(*WORK_PLAN).pieces(False)
    assert sorted(n["owner"] for _, n in model.of("work")) \
        == sorted(c.owner[1] for c in pieces)
    # A value in the row of a work takes it, read, quoted with the row.
    remap = names["REmap"]
    assert (remap["work"], remap["work_state"], remap["work_means"]) \
        == (another, fields.READ, ["IRENA 2018"])
    assert remap["work_quote"] == "| IRENA 2018 | REmap | 80 |"
    assert names["NZE"]["work_means"] == ["IEA 2020"]
    # A heading that names a work speaks for its whole piece.
    assert names["Tech15"]["work_means"] == ["EC 2018"]
    assert names["Tech15"]["work_quote"].startswith("EC 2018")
    # A value of no work's line is this publication's only with the line
    # that says so as its quote.
    central = names["Central"]
    assert (central["work"], central["work_means"]) \
        == (this, ["this publication"])
    assert central["work_quote"] == "Our scenarios are Central and High."
    # Only the value no line attributes asks its work, as a choice of the
    # document's works; 0 leaves it unstated, and it is never searched.
    asked = [p for p, _ in model.of("coord") if "list" in p]
    assert [p["value"]["words"] for p in asked] == ["Delayed"]
    assert asked[0]["list"][0] == "1 this publication"
    assert names["Delayed"]["work_state"] == fields.SAID_UNSTATED
    assert not [n for _, n in model.of("search")
                if n.get("coordinate") == "work"]
    # the failure by construction: no value takes a work without a line,
    names, _model, _reads = read_works({"entry": 2})
    assert names["Delayed"]["work_state"] == fields.SAID_UNSTATED
    # and one with the line that shows it reads it.
    names, _model, _reads = read_works({"entry": 3, "at": "1",
                                        "words": "Delayed"})
    assert names["Delayed"]["work_means"] == ["IEA 2020"]


def test_the_details_of_new_works_run_side_by_side_before_any_value_is_read():
    batches = []

    def each(jobs, run):
        jobs = list(jobs)
        batches.append(jobs)
        return [run(job) for job in jobs]

    def detail(payload, noted):
        if payload["work"] == "IRENA 2018" \
                and noted["parameter"] == "study_organisation":
            return {"at": "3.1", "words": "IRENA"}
        return {"at": 0}
    _names, model, reads = read_works({"entry": 0}, each=each, detail=detail)
    # A detail's job: (number of the work, find, field, question, the
    # piece that names the work).
    asked_of_a_work = set(SCENARIOS.works["fields"])
    (details,) = [jobs for jobs in batches if jobs
                  and isinstance(jobs[0], tuple) and len(jobs[0]) == 5
                  and jobs[0][2] in asked_of_a_work]
    # Every detail of the three new works in one turn of side by side.
    assert len(details) == 3 * len(SCENARIOS.works["fields"])
    first_find = next(i for i, (kind, _p, _n) in enumerate(model.calls)
                      if kind == "find")
    assert all(i < first_find for i, (kind, p, _n) in enumerate(model.calls)
               if kind == "work" or (kind == "coord" and "work" in p))
    # A value of another work does not reach the graph.
    (organisation,) = [c for r in reads
                       if r.batch.parameter.uri == "study_organisation"
                       for c in r.claims]
    assert organisation["value"] == "IRENA"
    assert organisation["work_means"] == ["IRENA 2018"]
    # The scenarios drawing admits a row only where its kept dimensions
    # hold (`kept_coordinates`), which refuses this one for its work.
    profile = load_profile("scenarios")
    assert {"brick": "kept_coordinates"} \
        in graph.load_drawing(profile).document["admit"]
    kept = graph.registry(profile)["kept_coordinates"]
    row = {"parameter": "study_organisation", **organisation}
    assert kept.run(Call(doc=SimpleNamespace(spec=SCENARIOS), row=row)) \
        == f"work:{work_label(addressed.ANOTHER_WORK)}"


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
CAPTION = ["Abbildung 3: Wärmebedarf nach Energieträger 2021"]
NUMBERS = ["Erdgas: 1.200 MWh", "Heizöl: 27 MWh"]


def transcripts(store, asked: list, prompt="p1", image="img1"):
    def ask(source, document_id):
        asked.append(source.owner_id)
        return {"caption": CAPTION, "numbers": NUMBERS}
    return addressed.Transcripts(ask, store, prompt, lambda source: image)


def test_a_figure_is_transcribed_once_in_two_lists_and_its_value_is_drawn(
        tmp_path):
    asked: list = []
    lines = {"caption": CAPTION, "numbers": NUMBERS}
    got, n = transcripts(tmp_path, asked)(7, [FIGURE])
    assert got == {5: lines} and n == 1 and asked == [5]
    # A second run with the same image and prompt asks nothing.
    again, n = transcripts(tmp_path, asked)(7, [FIGURE])
    assert again == {5: lines} and n == 0 and asked == [5]
    # the failure by construction: another prompt or another image is asked
    assert transcripts(tmp_path, asked, prompt="p2")(7, [FIGURE])[1] == 1
    assert transcripts(tmp_path, asked, image="img2")(7, [FIGURE])[1] == 1
    # One kept in the form of one list is asked again.
    old = tmp_path / "old"
    old.mkdir()
    (old / "7.json").write_text(json.dumps({"5": {
        "image": "img1", "prompt": "p1", "lines": CAPTION + NUMBERS}}),
        encoding="utf-8")
    assert transcripts(old, asked)(7, [FIGURE])[1] == 1
    # A value read off it stands in a line of its numbers, drawn, and is a
    # C.
    model = Model(find=lambda p, n: {"found": [{"at": "2",
                                                 "words": "1.200"}]})
    plan = Plan(7, [FIGURE], got, 8)
    (claim,) = [c for r in reader_of(model)(plan, [ENERGY])
                for c in r.claims]
    assert claim["drawn"] is True and claim["quote"] == "Erdgas: 1.200 MWh"
    checked = verify.verify_tuple(claim, ENERGY, "\n".join(CAPTION + NUMBERS),
                                  owner_kind="figure")
    row = {**checked.tuple, "flags": checked.flags, "tier": checked.tier}
    assert trust.trust(row)["level"] == trust.LEVEL_C


def test_a_figure_written_out_with_a_step_s_own_parts_is_kept_apart(
        tmp_path):
    # A step that writes out the figures with a prompt, inputs or answer
    # form of its own asks with its own request AND keeps what it wrote
    # under its own mark, so that neither step takes the other's
    # transcription (owner decision 2026-11-12 evening, every question is
    # "Ask the model"; `engine.Engine.writes_figures`).
    asked: list = []
    told = {"inputs": [{"key": "figure", "from": "figure",
                        "show": "figure_text"}]}
    kept = transcripts(tmp_path, asked)
    kept(7, [FIGURE])
    assert asked == [5]
    own: list = []

    def own_ask(source, document_id):
        own.append(source.owner_id)
        return {"caption": CAPTION, "numbers": NUMBERS}
    assert kept(7, [FIGURE], ask=own_ask, told=told)[1] == 1
    assert own == [5] and asked == [5]
    assert kept(7, [FIGURE], ask=own_ask, told=told)[1] == 0
    # the failure by construction: the preset's step does not take it
    assert kept(7, [FIGURE])[1] == 1 and asked == [5, 5]


# -- 12. the reasons ------------------------------------------------------------

def test_the_reasons_of_an_address_stand_and_those_of_a_quote_are_gone():
    assert {addressed.NOT_AN_ADDRESS, addressed.WORDS_NOT_IN_LINE} \
        <= set(schema.DROP_REASONS)
    assert {"quote_not_unique", "value_not_once"}.isdisjoint(
        wording.REQUIRED)
    assert {"not_an_address", "words_not_in_line"} <= wording.REQUIRED


# -- 4. a field with a list ---------------------------------------------------------

def test_a_closed_field_s_find_names_its_entry_of_the_list_it_is_shown():
    kind = SCENARIOS.by_uri["scenario_type"]
    text = Source("section", 4, "The Reference scenario continues current "
                                "policies.", {"document_id": 7, "page": 2})
    lines, choices, _grouped = Reader(SCENARIOS, Model().asks(),
                                      in_order).listed(kind)
    reference = choices.index("reference scenario") + 1

    def read(entry):
        model = Model(
            find=lambda p, n: {"found": [{"entry": entry, "at": "1",
                                          "words": "Reference scenario"}]}
            if n.get("parameter") == kind.uri else {"found": []},
            follow=lambda p, n: {"found": [{"entry": reference, "at": "1",
                                            "words": "Reference scenario"}]}
            if n.get("asked") == "find" else None)
        reads = reader_of(model, spec=SCENARIOS)(plan_of(text), [kind])
        return reads, model
    reads, model = read(reference)
    (payload,) = [p for p, n in model.of("find")
                  if n.get("parameter") == kind.uri]
    assert payload["list"] == lines
    (claim,) = [c for r in reads for c in r.claims]
    assert claim["value"] == "reference scenario"
    assert claim["value_raw"] == "Reference scenario"
    # A find with its number asks no list request for its value.
    assert not [n for _, n in model.of("list")
                if n.get("parameter") == kind.uri
                and n.get("coordinate") == "value"]
    # the failure by construction: a number off the list is refused and
    # asked again with its reason
    reads, model = read(len(choices) + 5)
    assert sum(r.failed.get(addressed.NOT_AN_OPTION, 0) for r in reads) == 1
    (claim,) = [c for r in reads for c in r.claims]
    assert claim["value"] == "reference scenario"


def test_the_find_of_a_group_asks_its_member_among_the_group_s_entries():
    sector = SCENARIOS.by_uri["study_sector"]
    text = Source("section", 4, "The study covers the energy industries.",
                  {"document_id": 7, "page": 2})
    _lines, groups, grouped = Reader(SCENARIOS, Model().asks(),
                                     in_order).listed(sector)
    crf = next(i for i, g in enumerate(groups, start=1)
               if g.startswith("CRF"))
    members = [o.label for o in fields.value_choice(sector).options
               if o.group == groups[crf - 1]]

    def docfield(payload, noted):
        for block in (payload.get("passages") or {}).values():
            for line in block["lines"]:
                if "energy industries" in line:
                    return {"found": [{"entry": crf,
                                       "at": line.split(" ", 1)[0],
                                       "words": "energy industries"}]}
        return {"found": []}
    model = Model(docfield=docfield, list=lambda p, n: {"entry": 2})
    reads = reader_of(model, spec=SCENARIOS)(plan_of(TITLE, text), [sector])
    (claim,) = [c for r in reads for c in r.claims]
    (asked,) = [p for p, n in model.of("list")
                if n.get("parameter") == sector.uri]
    # The find names the group, the list request shows its members only.
    assert grouped and len(members) > 1
    assert len(asked["list"]) == len(members)
    assert claim["value"] == members[1]


# -- 5. two replies shown -------------------------------------------------------------

def shown_addresses(payload) -> set:
    """The addresses of the lines a request shows."""
    blocks = [payload.get("passage") or {}] \
        + list((payload.get("passages") or {}).values())
    lines = [line for block in blocks for line in block.get("lines", [])] \
        + list(payload.get("title_page") or []) \
        + list(payload.get("headings") or [])
    return {line.split(" ", 1)[0] for line in lines}


def shows_two(example, payload) -> bool:
    """Does a request show two replies: a find at an address it shows, and
    one without finds?"""
    if not isinstance(example, tuple) or len(example) != 2:
        return False
    one, nothing = example
    if not one.get("found") or nothing.get("found") != []:
        return False
    at = str(one["found"][0]["at"]).split(".")[0]
    return at in shown_addresses(payload)


def test_every_request_that_finds_values_shows_a_find_of_its_own_and_none():
    label = SCENARIOS.by_uri["scenario_label"]
    title = SCENARIOS.by_uri["publication_title"]
    model = Model()
    reader_of(model, spec=SCENARIOS, works=SCENARIOS.works)(
        plan_of(*WORK_PLAN), [label, title])
    kinds = ("find", "docfield", "work")
    examples = [(kind, example) for kind, example in model.examples
                if kind in kinds]
    payloads = [p for kind, p, _n in model.calls if kind in kinds]
    assert {kind for kind, _ in examples} == set(kinds)
    for (kind, example), payload in zip(examples, payloads):
        assert shows_two(example, payload), kind
    # the failure by construction: one reply, or a find at a line the
    # request does not show, is not two
    example, payload = examples[0][1], payloads[0]
    assert not shows_two(example[0], payload)
    assert not shows_two(({"found": [{"at": "99", "words": "x"}]},
                          {"found": []}), payload)


# -- 7. the list as it is --------------------------------------------------------------

def test_a_list_request_shows_the_list_as_it_is_and_no_earlier_wording():
    model = Model(list=lambda p, n: {"entry": [1]})
    plan = plan_of(TEXT)
    entry_of(model, SLOTS["carrier"], "Gas", plan=plan, several=True)
    entry_of(model, SLOTS["carrier"], "Erdöl", plan=plan, several=True)
    first, second = [payload for payload, _ in model.of("list")]
    assert second["list"] == first["list"]
    assert "in this document" not in json.dumps(second, ensure_ascii=False)


# -- 9. a name that names nothing, a name of an entry ------------------------------------

def test_a_name_that_names_no_scenario_is_no_entry_and_the_graph_takes_none():
    label = SCENARIOS.by_uri["scenario_label"]
    text = Source("section", 4, "Source: JRC.\nThe Central scenario reaches "
                                "net zero.", {"document_id": 7, "page": 2})

    def names_reply(payload, noted):
        if noted.get("kind") == "scenario" \
                and payload["name"] == "Source: JRC.":
            return {"entry": 0}
        return {"entry": "new"}
    model = Model(
        work=lambda p, n: {"found": [], "own": {
            "at": "2", "words": "The Central scenario"}},
        find=lambda p, n: {"found": [{"at": "1", "words": "Source: JRC."},
                                     {"at": "2", "words": "Central"}]}
        if n.get("parameter") == label.uri else {"found": []},
        names=names_reply)
    plan = plan_of(text)
    reads = reader_of(model, spec=SCENARIOS,
                      works=SCENARIOS.works)(plan, [label])
    named = {c["value"]: c for r in reads for c in r.claims}
    # 0 is taken: no entry, the value stays read with an empty note.
    assert named["Source: JRC."]["value_means"] == []
    assert [e.name for e in plan.names["scenario"].entries] == ["Central"]
    assert named["Central"]["value_means"] == ["Central"]
    # The graph makes no scenario of it, and one of a name it was never
    # asked about, as before.
    assert kg.scenario_names({"parameter": label.uri,
                              **named["Source: JRC."]}) == []
    assert kg.scenario_names({"parameter": label.uri,
                              **named["Central"]}) == ["Central"]
    # the failure by construction: without the note the name is a scenario
    unasked = {k: v for k, v in named["Source: JRC."].items()
               if k != "value_means"}
    assert kg.scenario_names({"parameter": label.uri, **unasked}) \
        == ["Source: JRC."]


def test_a_name_of_an_entry_takes_its_work_and_one_without_work_stays_apart():
    label = SCENARIOS.by_uri["scenario_label"]
    text = Source("section", 4, "The Delayed case and the Rapid case end in "
                                "2060.", {"document_id": 7, "page": 2})

    def names_reply(payload, noted):
        if payload["name"] == "Delayed":
            return {"entry": next(i for i, line in enumerate(
                payload["list"], start=1) if line.endswith(": Delayed"))}
        return {"entry": "new"}
    model = Model(
        find=lambda p, n: {"found": [{"at": "1", "words": "Delayed"},
                                     {"at": "1", "words": "Rapid"}]}
        if n.get("parameter") == label.uri else {"found": []},
        coord=lambda p, n: {"entry": 0} if "list" in p else {"at": 0},
        names=names_reply)
    reader = reader_of(model, spec=SCENARIOS,
                       works=SCENARIOS.works)
    plan = plan_of(text)
    reader.lists_of(plan)
    iea = plan.names["work"].add("IEA 2020")
    read_as = {"work": work_label(addressed.ANOTHER_WORK),
               "work_state": fields.READ, "work_raw": "IEA 2020",
               "work_quote": "| IEA 2020 | Delayed | 90 |",
               "work_means": ["IEA 2020"]}
    plan.names["scenario"].add("Delayed", work=iea,
                               quote="| IEA 2020 | Delayed | 90 |",
                               work_read=read_as)
    reads = reader(plan, [label])
    named = {c["value"]: c for r in reads for c in r.claims}
    # The entry decides last: the name takes the work its entry was read
    # with, its own work left open.
    assert {k: named["Delayed"][k] for k in read_as} == read_as
    assert named["Delayed"]["work_window"] == ["entry", 1]
    # the failure by construction: a new name whose work stayed open is an
    # entry of no work, not of this publication
    rapid = plan.names["scenario"].entries[-1]
    assert (rapid.name, rapid.work) == ("Rapid", 0)
    assert named["Rapid"]["work_state"] == fields.SAID_UNSTATED


# -- what the spec says a plan settles (owner decision 2026-11-10) -------------

KWP_RAW = json.loads((ROOT / "profiles" / "kwp" / "extraction_spec.json")
                     .read_text(encoding="utf-8"))


def requests_of_a_reading(raw: dict, monkeypatch) -> list:
    """[(kind, what it shows, what is noted of it)] of one plan read by the
    reader the run builds from a spec (`runner.make_reader`)."""
    spec = load_spec(raw)
    model = Model()
    monkeypatch.setattr(runner, "make_asks", lambda profile: model.asks())
    reader = runner.make_reader(spec, None, in_order, in_order)
    plan = plan_of(TITLE, TEXT, TABLE)
    # As the harvest of a document does (`surveyed.SurveyedHarvest`).
    reader.settled(plan, addressed.Counts())
    reader(plan, [spec.by_uri["energy_consumption"]])
    return model.calls


def test_what_a_plan_settles_is_asked_with_the_words_of_the_spec(
        monkeypatch):
    calls = requests_of_a_reading(KWP_RAW, monkeypatch)
    shown = {noted["parameter"]: payload["field"]
             for kind, payload, noted in calls if kind == "docfield"
             and noted["parameter"] in KWP_RAW["plan_fields"]}
    assert shown == {key: {"name": said["name"], "means": said["means"]}
                     for key, said in KWP_RAW["plan_fields"].items()}
    # the failure by construction: a spec that settles nothing asks none of
    # the three
    bare = {k: v for k, v in KWP_RAW.items() if k != "plan_fields"}
    assert not [noted for kind, _payload, noted
                in requests_of_a_reading(bare, monkeypatch)
                if noted.get("parameter") in KWP_RAW["plan_fields"]]


def test_a_reworded_target_year_changes_the_requests_that_show_it_only(
        monkeypatch):
    reworded = json.loads(json.dumps(KWP_RAW))
    reworded["plan_fields"]["target_year"]["means"] += " Auch ein Etappenziel."
    before = requests_of_a_reading(KWP_RAW, monkeypatch)
    after = requests_of_a_reading(reworded, monkeypatch)
    assert len(before) == len(after)
    moved = [noted_a.get("parameter")
             for (kind, shown, _noted), (kind_a, shown_a, noted_a)
             in zip(before, after) if (kind, shown) != (kind_a, shown_a)]
    assert moved and set(moved) == {"target_year"}
