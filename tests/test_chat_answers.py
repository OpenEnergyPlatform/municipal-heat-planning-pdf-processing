"""The chat shows a statement only where its evidence stands, and an answer
from the harvest names the values it stands on."""
from docpipe.inference import statements
from docpipe.inference.llm_client import grounded_quote
from docpipe.inference.values_route import used_values

HITS = [{"owner_kind": "section", "owner_id": 11},
        {"owner_kind": "table", "owner_id": 12}]
ITEMS = {0: {"text": "Der Endenergieverbrauch betrug 2022 rund 450 GWh."},
         1: {"text": "| Erdgas | 120 GWh |"}}


def back(said, runs=()):
    return statements.back(said, items=ITEMS, hits=HITS, attached=set(),
                           delivered={}, runs=list(runs))


def test_every_statement_is_shown_or_dropped_with_its_cause():
    said = [
        {"statement": "Verbrauch 450 GWh", "basis": "text", "index": 0,
         "quote": "Endenergieverbrauch betrug 2022 rund 450 GWh"},
        {"statement": "erfunden", "basis": "text", "index": 0,
         "quote": "Der Verbrauch lag bei 900 GWh"},
        {"statement": "falsche Quelle", "basis": "text", "index": 5,
         "quote": "Endenergieverbrauch betrug 2022"},
        {"statement": "", "basis": "text", "index": 0, "quote": "x"},
        {"statement": "unbekannte Basis", "basis": "gefühl", "index": 0},
        "kein Objekt",
    ]
    shown, dropped = back(said)
    assert [s["owner_id"] for s in shown] == [11]
    assert [d["why"] for d in dropped] == [
        "quote", "no_source", "blank", "blank", "blank"]
    assert len(shown) + len(dropped) == len(said)


def test_an_index_is_an_integer_and_nothing_else():
    shown, dropped = back([{"statement": "s", "basis": "text", "index": "0",
                            "quote": "Endenergieverbrauch betrug 2022"},
                           {"statement": "s", "basis": "text", "index": True,
                            "quote": "Endenergieverbrauch betrug 2022"}])
    assert shown == [] and [d["why"] for d in dropped] == [
        "no_source", "no_source"]


def test_a_computed_statement_needs_a_run_of_this_call_that_succeeded():
    said = {"statement": "Summe 570 GWh", "basis": "computed", "index": 0,
            "quote": "Endenergieverbrauch betrug 2022 rund 450 GWh", "run": 1}
    ok = [{"code": "print(450+120)", "output": {"ok": True}}]
    failed = [{"code": "x", "output": {"ok": False}}]
    assert back([said], ok)[0][0]["computed"] is True
    assert back([said], failed)[1][0]["why"] == "run"
    assert back([dict(said, run=2)], ok)[1][0]["why"] == "run"


def test_a_quote_is_grounded_only_whole_and_long_enough():
    item = {"text": "Die Fernwärme deckt  37 %  des Bedarfs."}
    assert grounded_quote('"die fernwärme deckt 37 %"', item)
    assert grounded_quote("Fernwärme", item) is None
    assert grounded_quote("Die Fernwärme deckt 40 %", item) is None


def test_a_harvest_answer_uses_the_values_its_statements_quote():
    values = [{"id": 1, "value_raw": "120", "quote": "| Erdgas | 120 GWh |"},
              {"id": 2, "value_raw": "80", "quote": "| Heizöl | 80 GWh |"},
              {"id": 3, "value_raw": "450",
               "quote": "Der Endenergieverbrauch betrug 2022 rund 450 GWh."}]
    said = [{"quote": "| Erdgas | 120 GWh |", "citation": 1},
            {"quote": "rund 450 GWh", "citation": 2}]
    assert [(v["id"], v["n"]) for v in used_values(values, said)] == [
        (1, 1), (3, 2)]
    shared = [{"quote": "Der Endenergieverbrauch betrug", "citation": 1}]
    assert used_values(values, shared) == [], (
        "a piece of the passage that does not name the value uses nothing")
