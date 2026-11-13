"""The chat finds harvested values by what they mean: a line of words per
value, a vector per line, the nearest lines as a closed list for the model,
and only where the index holds every value."""
import json
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from docpipe.embedding import config as embedding_config
from docpipe.inference import catalog, llm_client, values_index, values_route
from docpipe.serve.values import Values


class Words:
    """An embedder that needs no model: a line's vector is the words it
    holds, so two lines are near when they share words. Counts what it is
    asked."""

    def __init__(self, fail_after=None):
        self.asked = []
        self.fail_after = fail_after

    def vector(self, text):
        vector = np.zeros(embedding_config.EMBEDDING_DIM, dtype="float32")
        for word in text.lower().replace(":", " ").replace(",", " ").split():
            vector[sum(word.encode()) % len(vector)] += 1
        return vector / np.linalg.norm(vector)

    def embed(self, items):
        if self.fail_after is not None and len(self.asked) >= self.fail_after:
            raise RuntimeError("the card went away")
        self.asked.extend(item["text"] for item in items)
        return [self.vector(item["text"]).tolist() for item in items]


def row(number, *, carrier="OEO_1", year=2030, level_state="read", **more):
    return {"parameter": "energy_consumption", "value": number, "unit": "GWh",
            "quote": f"Zitat {number}", "tier": "text_located",
            "parameter_state": "derived", "unit_state": "read",
            "carrier": carrier, "carrier_state": level_state,
            "carrier_raw": "Erdgas" if carrier == "OEO_1" else "Heizöl",
            "year": year, "year_state": "read",
            "provenance": {"page": 3, "owner_kind": "table", "owner_id": 7,
                           "title": "Tabelle 2: Verbrauch"}, **more}


def store_of(*documents):
    return Values({name: rows for name, rows in documents})


def test_a_line_says_whose_it_is_what_it_is_of_and_the_number():
    value = next(iter(store_of(("plan", [row(12)]))))
    line = values_index.entry_text(value, "Oberhausen")
    assert line.startswith("Oberhausen:")
    assert "12 GWh" in line
    assert "2030" in line
    assert "Tabelle 2" in line


def test_a_coordinate_keeps_the_plans_word_beside_the_list_entry():
    said = values_index._coordinate(
        {"value": "x", "label": "Heizöl", "wording": "Mineralöl"}, "titel")
    assert "Heizöl" in said and "Mineralöl" in said


def test_a_word_the_passage_title_holds_is_not_said_twice():
    said = values_index._coordinate(
        {"value": "x", "label": "Zielszenario", "wording": "Szenario 4"},
        "tabelle zu szenario 4")
    assert "Szenario 4" not in said


def test_a_year_is_said_without_the_passage_it_was_read_from():
    said = values_index._coordinate(
        {"value": 2022, "wording": "BHKW-Anlagen"}, "")
    assert said == "2022"


def test_an_unread_coordinate_says_nothing():
    assert values_index._coordinate({"value": None}, "") is None


def test_the_same_value_makes_the_same_line():
    value = next(iter(store_of(("plan", [row(12)]))))
    assert values_index.entry_text(value, "A") \
        == values_index.entry_text(json.loads(json.dumps(value)), "A")


def built(tmp_path, *documents, embedder=None):
    store = store_of(*documents)
    lines = values_index.lines_of(store, {})
    harvest = tmp_path / "corpus"
    embedder = embedder or Words()
    made = values_index.build(harvest, lines, embedder=embedder, batch=2)
    return store, lines, harvest, embedder, made


def test_a_build_holds_every_line_and_says_how_many(tmp_path):
    store, lines, harvest, _embedder, made = built(
        tmp_path, ("plan", [row(1), row(2), row(3)]))
    assert made["lines"] == len(set(lines)) == 3
    assert made["embedded"] == 3 and made["reused"] == 0
    assert values_index.state(lines, values_index.path_for(harvest)) \
        == "current"


def test_two_values_that_read_alike_share_one_vector(tmp_path):
    same = row(1)
    _store, _lines, _harvest, embedder, made = built(
        tmp_path, ("plan", [same, dict(same, quote="anderes Zitat")]))
    assert made["lines"] == 1 and len(embedder.asked) == 1


def test_a_line_that_stayed_is_not_embedded_again(tmp_path):
    store, lines, harvest, _embedder, _made = built(
        tmp_path, ("plan", [row(1), row(2)]))
    grown = store_of(("plan", [row(1), row(2), row(3)]))
    again = Words()
    made = values_index.build(harvest, values_index.lines_of(grown, {}),
                              embedder=again, batch=2)
    assert made["reused"] == 2 and made["embedded"] == 1
    assert len(again.asked) == 1


def test_a_build_that_stopped_goes_on_where_it_stopped(tmp_path):
    store = store_of(("plan", [row(n) for n in range(1, 7)]))
    lines = values_index.lines_of(store, {})
    harvest = tmp_path / "corpus"
    with pytest.raises(RuntimeError):
        values_index.build(harvest, lines, embedder=Words(fail_after=2),
                           batch=2)
    assert not values_index.path_for(harvest).exists()
    second = Words()
    made = values_index.build(harvest, lines, embedder=second, batch=2)
    assert len(second.asked) == 4
    assert made["reused"] == 2 and made["embedded"] == 4


def test_vectors_of_a_line_no_longer_wanted_leave_the_index(tmp_path):
    store, _lines, harvest, _embedder, _made = built(
        tmp_path, ("plan", [row(1), row(2)]))
    kept = store_of(("plan", [row(1)]))
    values_index.build(harvest, values_index.lines_of(kept, {}),
                       embedder=Words(), batch=2)
    index = sqlite3.connect(values_index.path_for(harvest))
    assert index.execute('SELECT count(*) FROM "vectors"').fetchone() == (1,)
    index.close()


def test_an_index_is_missing_stale_or_current(tmp_path, monkeypatch):
    store, lines, harvest, _embedder, _made = built(
        tmp_path, ("plan", [row(1)]))
    path = values_index.path_for(harvest)
    assert values_index.state(lines, tmp_path / "none.db") == "missing"
    assert values_index.state(lines, path) == "current"
    # A value the index does not hold.
    assert values_index.state(lines + ["ein neuer Wert"], path) == "stale"
    # Vectors of another model say nothing about this one's queries.
    monkeypatch.setattr(embedding_config, "EMBEDDING_MODEL", "anderes/Modell")
    assert values_index.state(lines, path) == "stale"


def test_a_stale_index_is_not_loaded(tmp_path):
    _store, _lines, harvest, _embedder, _made = built(
        tmp_path, ("plan", [row(1)]))
    grown = store_of(("plan", [row(1), row(2)]))
    assert values_index.load(harvest, grown, {}) is None


def loaded(tmp_path, *documents):
    store, _lines, harvest, embedder, _made = built(tmp_path, *documents)
    return values_index.load(harvest, store, {}), embedder


def test_the_search_ranks_by_nearness_and_keeps_to_the_document(tmp_path):
    index, words = loaded(tmp_path, ("erster", [row(1), row(2)]),
                          ("zweiter", [row(3, carrier="OEO_2")]))
    found = index.search(words.vector(index.lines[1]))
    assert found[0][1] == index.lines[1]
    assert {value["document"] for value, _ in found} == {"erster", "zweiter"}
    only = index.search(words.vector(index.lines[1]), document="zweiter")
    assert {value["document"] for value, _ in only} == {"zweiter"}
    assert index.search(words.vector(index.lines[1]),
                        document="keiner") == []


def test_the_search_keeps_to_the_levels_asked_for(tmp_path):
    open_row = row(2, level_state="exhausted", carrier=None)
    index, words = loaded(tmp_path, ("plan", [row(1), open_row]))
    found = index.search(words.vector(index.lines[0]), levels=("A", "B"))
    assert [value["value"] for value, _ in found] == [1]


def test_values_that_read_alike_stand_in_the_list_once(tmp_path):
    same = row(1)
    index, words = loaded(tmp_path,
                          ("plan", [same, dict(same, quote="anderes Zitat")]))
    assert len(index.search(words.vector(index.lines[0]))) == 1


def route(index, words, pick, **kwargs):
    kwargs.setdefault("budget", 10 ** 6)
    return values_route.answer_from_index(
        "Frage", index, embed=lambda task: words.vector(index.lines[0]),
        pick=pick, count=len, **kwargs)


def test_the_answer_is_what_the_model_chose_from_the_list(tmp_path):
    index, words = loaded(tmp_path, ("plan", [row(1), row(2)]))
    got = route(index, words, lambda task, entries: [entries[1]["id"]])
    assert got["route"] == "values" and got["total"] == 1
    assert got["values"][0]["value"] == 2


def test_nothing_chosen_is_no_answer_and_says_why(tmp_path):
    index, words = loaded(tmp_path, ("plan", [row(1)]))
    got = route(index, words, lambda task, entries: [])
    assert got["route"] == "rag" and got["reason"] == "no_values"


def test_the_list_ends_where_the_budget_does(tmp_path):
    index, words = loaded(tmp_path, ("plan", [row(n) for n in range(1, 9)]))
    seen = {}

    def pick(task, entries):
        seen["entries"] = entries
        return [entries[0]["id"]]

    one = len(index.lines[0])
    route(index, words, pick, budget=3 * one)
    assert 1 <= len(seen["entries"]) <= 3


def test_the_nearest_line_is_shown_even_when_it_alone_is_over_budget(tmp_path):
    index, words = loaded(tmp_path, ("plan", [row(1), row(2)]))
    seen = {}

    def pick(task, entries):
        seen["entries"] = entries
        return []

    route(index, words, pick, budget=1)
    assert len(seen["entries"]) == 1


def test_a_document_without_values_asks_the_model_nothing(tmp_path):
    index, words = loaded(tmp_path, ("plan", [row(1)]))

    def pick(task, entries):
        raise AssertionError("nothing to choose among")

    got = route(index, words, pick, document="keiner")
    assert got["reason"] == "no_values"


def test_the_list_of_the_model_holds_the_words_and_no_value(tmp_path):
    index, words = loaded(tmp_path, ("plan", [row(1)]))
    seen = {}

    def pick(task, entries):
        seen["entries"] = entries
        return []

    route(index, words, pick)
    assert set(seen["entries"][0]) == {"id", "text"}


# ---------------------------------------------------------- the closed list


def replying(monkeypatch, *replies):
    """The model's replies, in turn; the messages it was sent."""
    sent = []
    left = list(replies)

    def ask(shape, messages, temperature, splittable=False):
        sent.append(messages)
        return left.pop(0)

    monkeypatch.setattr(llm_client, "_ask", ask)
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    return sent


ENTRIES = [{"id": "E1", "text": "eins"}, {"id": "E2", "text": "zwei"}]


def test_a_choice_is_a_list_of_entries_in_their_order(monkeypatch):
    replying(monkeypatch, {"chosen": ["E2", "E1"]})
    assert llm_client.pick_values("Frage", ENTRIES) == ["E1", "E2"]


def test_an_id_outside_the_list_is_asked_again_with_what_was_wrong(monkeypatch):
    sent = replying(monkeypatch, {"chosen": ["E9"]}, {"chosen": ["E2"]})
    assert llm_client.pick_values("Frage", ENTRIES) == ["E2"]
    assert len(sent) == 2
    assert "E9" in sent[1][-1]["content"]


def test_a_reply_is_not_cut_down_to_the_ids_that_are_right(monkeypatch):
    replies = [{"chosen": ["E1", "E9"]}] * llm_client.LLM_MAX_RETRIES
    replying(monkeypatch, *replies)
    with llm_client.collecting() as faults:
        assert llm_client.pick_values("Frage", ENTRIES) == []
    assert [fault["request"] for fault in faults] == ["picked_reply"]


def test_the_grammar_of_the_reply_is_the_list():
    import jsonschema
    schema = llm_client.replies.picked(["E1", "E2"])[1]
    jsonschema.validate({"chosen": ["E1"]}, schema)
    jsonschema.validate({"chosen": []}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"chosen": ["E3"]}, schema)


# ------------------------------------------------------------ what it is called


def test_a_document_is_called_without_date_and_version():
    row_of = {"filename": "waermeplan_kassel_2024q1.pdf", "external_id": "k",
              "id": 1, "published": "2024q1", "is_current": 1}
    name = catalog.Catalog().name(row_of)
    assert name == "waermeplan_kassel_2024q1"


def test_the_names_of_a_corpus_go_by_the_harvest_name():
    entries = [SimpleNamespace(row={"filename": "a_b.pdf"}, facets={})]
    plain = SimpleNamespace(entries=lambda conn, include_superseded: entries,
                            name=lambda row, facets: "Kassel")
    assert values_index.document_names(plain, None) == {"a_b": "Kassel"}
