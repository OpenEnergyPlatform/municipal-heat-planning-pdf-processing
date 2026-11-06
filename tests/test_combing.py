"""Only values with a coordinate still open are combed, one request per
value and group of the spec with an open coordinate, which shows that one
row AND reads its answers at the top of the reply, AND shows the group's
words for where a plan prints it and asks only the group's open
coordinates; the search ranks the plan with the sentences the
reading wrote to the coordinates asked, AND it shows the best 15 sections, 20
tables and 20 figures of that ranking as a list of hits, the passage itself
and its section left out; without a sentence no list is shown and the model
searches itself with "similar", AND that search lists the plan's passages
nearest to its own sentence. A coordinate answered
from anything the request showed of the plan (a fetched hit, a hit's line or
title, a wording the value has read) is read and cites the passage it was
shown with in window `retrieval`, AND one quoting what the request never
showed is not read AND is told so in the names of what the request shows; one answered as not stated ends unstated; one left without an answer is asked for
by name once more as missing, AND one given in another form than asked (a
bare word where an object with "value" is asked) as given in the wrong
form, and both end unanswered; a coordinate read before is never
touched; and a request that does not fit leaves every open coordinate
exhausted.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

import pytest

from docpipe.extraction import combing, fields, reading
from docpipe.extraction.pipeline import Batch, Source, WorkItem
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.wording import say

SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = [slot.name for slot in reading.slots_of(SPEC, EMISSION)]
GROUPS = reading.groups_of(SPEC, reading.slots_of(SPEC, EMISSION))
YEAR_GROUP = next(group for group, slots in GROUPS
                  if "year" in {slot.name for slot in slots})
UNSTATED = fields.UNSTATED

OWN = Source("section", 6, "Bilanz\nEs fielen rund 300 t CO2 an.",
             {"document_id": 7, "section_title": "Bilanz"})
HIT = Source("section", 8, "Ausblick\nDie Werte gelten für das Jahr 2030.",
             {"document_id": 7, "section_title": "Ausblick"})
PASSAGES = {("section", 6): OWN, ("section", 8): HIT}


def claim(**states):
    """A value of OWN: its unit and carrier read, the rest as *states*."""
    out = {"source": "Q1", "value": 300, "quote": "rund 300 t CO2",
           "unit": "t CO2", "unit_state": fields.READ,
           "carrier": "Erdgas", "carrier_state": fields.READ}
    for name in SLOTS:
        out.setdefault(f"{name}_state", fields.SAID_UNSTATED)
    out.update({f"{name}_state": state for name, state in states.items()})
    return out


def reads(*claims, probes=()):
    """The reading of OWN with *claims*, each with the sentences its group
    replies wrote to what they found unstated, in *probes* by its order."""
    batch = Batch(7, EMISSION, [WorkItem(7, EMISSION, OWN)])
    return [reading.Read(batch, list(claims), probes=list(probes))]


def comber(*replies, ranked=(HIT,), ranking=True, known=None):
    asked, searched = [], []

    def ask(payload, shape, document_id, source, group=None, example=None):
        asked.append(payload)
        return replies[min(len(asked), len(replies)) - 1]

    def rank(document_id, probes, exclude):
        searched.append((probes, set(exclude)))
        return [s for s in ranked
                if (s.owner_kind, s.owner_id) not in exclude]

    made = combing.Comber(SPEC, ask, rank if ranking else None,
                          known or (lambda claim, names: {}))
    return made, asked, searched


def everything(**given):
    out = {name: {"value": UNSTATED} for name in SLOTS}
    out.update(given)
    return out


YEAR = {"value": 2030, "quote": "gelten für das Jahr 2030"}
# What a reading that found the year unstated wrote to it.
SAID = {"year": "Die Emissionen gelten für das Jahr 2022."}


def test_only_values_with_an_open_coordinate_are_combed_once_per_group():
    made, asked, _ = comber({})
    read = reads(claim(), claim(**{name: fields.READ for name in SLOTS}))
    done = made(7, read, PASSAGES, [])
    assert [d.group for d in done] == [group.name for group, _ in GROUPS]
    assert all(d.rows == 1 for d in done)
    # One row per request, shown without a label (owner decision
    # 2026-11-06).
    assert all("rows" not in payload and "row" not in payload["row"]
               for payload in asked)
    # A value open in one group only is combed in that group alone.
    made, asked, _ = comber({})
    done = made(7, reads(claim(**{name: fields.READ for name in SLOTS
                                  if name != "year"})), PASSAGES, [])
    assert [d.group for d in done] == [YEAR_GROUP.name]
    assert set(asked[0]["coordinates"]) == {"year"}
    assert asked[0]["where"] == YEAR_GROUP.where


def test_a_request_shows_one_row_and_its_answers_stand_at_the_top():
    # Owner decision 2026-11-06: no wrapper and no row label.
    slots = reading.slots_of(SPEC, EMISSION)
    schema = combing.comb_response_format(slots)["json_schema"]["schema"]
    assert schema["required"] == SLOTS
    assert set(schema["properties"]) == {*SLOTS, "more"}
    more = [{"get": "hit", "id": "H1"}]
    assert combing.as_rows(dict(everything(year=YEAR), more=more), "R2") == {
        "rows": [dict(everything(year=YEAR), row="R2")], "more": more}
    assert combing.as_rows(reading.CUT, "R2") is reading.CUT
    # A correction names its row, and a request is told only its own.
    told = [{"row": "R2", "what": {"year": "x"}}]
    assert combing.shown_corrections(told, "R2") == {"what": {"year": "x"}}
    assert combing.shown_corrections(told, "R1") is None
    # Two values are two requests, never one.
    made, _, _ = comber({})
    with pytest.raises(ValueError, match="one row"):
        made.comb(7, EMISSION, OWN, slots, [claim(), claim()], PASSAGES, [])


def test_the_search_shows_the_best_of_each_kind_as_a_list_without_its_own():
    ranked = ([Source("section", 100 + i, f"S{i}\ntext", {}) for i in range(20)]
              + [Source("table", 200 + i, f"T{i}\n| a |", {}) for i in range(25)]
              + [Source("figure", 300 + i, f"F{i}\nbild", {}) for i in range(3)])
    shown = combing.shown_hits(ranked)
    kinds = [s.owner_kind for s in shown]
    assert kinds.count("section") == 15 and kinds.count("table") == 20
    assert kinds.count("figure") == 3
    assert shown == [s for s in ranked if s in shown]
    made, asked, searched = comber({}, ranked=(OWN, HIT))
    made(7, reads(claim(), probes=[SAID]), PASSAGES, [])
    assert searched[0][1] == {("section", 6)}
    listed = asked[0]["hits"][0]["hits"]
    assert [(hit["id"], hit["title"]) for hit in listed] == [("H1", "Ausblick")]
    assert listed[0]["line"] == "Die Werte gelten für das Jahr 2030."


def test_a_coordinate_answered_from_a_fetched_hit_is_read_and_cites_it():
    made, asked, _ = comber(
        dict(everything(), more=[{"get": "hit", "id": "H1"}]),
        everything(year=YEAR))
    read = reads(claim(), probes=[SAID])
    done = made(7, read, PASSAGES, [])[0]
    value = read[0].claims[0]
    assert value["year"] == 2030 and value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 8]
    assert list(value["year_window"]) == ["retrieval", 1]
    assert done.fetched == 1 and done.filled == 1
    assert [m["text"] for m in asked[1]["more"]] == [HIT.text]


def test_a_quote_from_nothing_the_request_showed_is_not_read():
    # Without a sentence no list is shown: the passage that prints the year
    # is in the plan, but the request never showed it.
    made, asked, _ = comber(everything(year=YEAR))
    read = reads(claim())
    made(7, read, PASSAGES, [])
    assert read[0].claims[0]["year_state"] == fields.UNBACKED
    # Told in the names of what a combing request shows (owner decision
    # 2026-11-06), not in those of another request.
    (again,) = [p for p in asked if "year" in p["coordinates"]
                and p.get("corrections")]
    assert again["corrections"] == {"what": {"year": say("quote_not_shown")}}


def test_a_quote_from_a_hit_s_line_is_read_and_cites_the_hit():
    # Not fetched: the line the list shows is enough (owner decision
    # 2026-11-05: whatever a request shows of a plan may be quoted).
    made, _, _ = comber(everything(year=YEAR))
    read = reads(claim(), probes=[SAID])
    done = made(7, read, PASSAGES, [])
    value = read[0].claims[0]
    assert value["year"] == 2030 and value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 8]
    assert list(value["year_window"]) == ["retrieval", 1]
    assert sum(d.fetched for d in done) == 0
    # The rest of the hit's passage was not shown and does not count.
    later = Source("section", 8, "Ausblick\nDie Werte gelten ab sofort.\n"
                   "Sie gelten für das Jahr 2030.", HIT.provenance)
    made, asked, _ = comber(everything(year=YEAR),
                            ranked=(later,))
    read = reads(claim(), probes=[SAID])
    made(7, read, {**PASSAGES, ("section", 8): later}, [])
    assert asked[0]["hits"][0]["hits"][0]["line"] == "Die Werte gelten ab sofort."
    assert read[0].claims[0]["year_state"] == fields.UNBACKED


def test_a_quote_from_a_hit_s_title_is_read_and_cites_the_hit():
    titled = Source("table", 9, "| Erdgas | 300 |",
                    {"document_id": 7, "title": "Tabelle 4: Emissionen 2030"})
    made, _, _ = comber(
        everything(year={
            "value": 2030, "quote": "Tabelle 4: Emissionen 2030"}),
        ranked=(titled,))
    read = reads(claim(), probes=[SAID])
    made(7, read, {**PASSAGES, ("table", 9): titled}, [])
    value = read[0].claims[0]
    assert value["year_state"] == fields.READ
    assert value["year_source"] == ["table", 9]


def read_elsewhere():
    """A value whose scenario was read in a passage the combing does not
    show."""
    out = claim(scenario=fields.READ)
    out.update(scenario_raw="Szenario Trend 2030",
               scenario_source=["section", 8])
    return out


def test_a_quote_from_a_wording_the_value_has_read_cites_where_it_was_read():
    # Its wording is shown under "known" and may be quoted.
    reply = everything(year={
        "value": 2030, "quote": "Szenario Trend 2030"})
    made, asked, _ = comber(reply, known=lambda claim, names: {
        "scenario": claim["scenario_raw"]})
    read = reads(read_elsewhere())
    made(7, read, PASSAGES, [])
    value = read[0].claims[0]
    assert asked[0]["row"]["known"] == {"scenario": "Szenario Trend 2030"}
    assert value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 8]
    # Not shown, it does not count.
    made, _, _ = comber(reply)
    read = reads(read_elsewhere())
    made(7, read, PASSAGES, [])
    assert read[0].claims[0]["year_state"] == fields.UNBACKED


def test_not_stated_stays_and_no_answer_is_asked_by_name_then_unanswered():
    entry = everything()
    del entry["year"]
    made, asked, _ = comber(entry)
    read = reads(claim())
    done = made(7, read, PASSAGES, [])[0]
    value = read[0].claims[0]
    assert value["scenario_state"] == fields.SAID_UNSTATED
    assert value["year_state"] == fields.UNANSWERED
    assert asked[1]["corrections"] == {
        "what": {"year": say("key_missing", key="year")}}
    assert done.asked == 2 and len(asked) == 2 + len(GROUPS) - 1


def test_an_answer_in_another_form_is_asked_again_as_such_then_unanswered():
    # "out:unstated" as a bare word where {"value": "out:unstated"} is asked:
    # the correction names the form, not a missing answer.
    made, asked, _ = comber(everything(year=UNSTATED))
    read = reads(claim())
    done = made(7, read, PASSAGES, [])[0]
    assert asked[1]["corrections"] == {"what": {"year": say("wrong_shape")}}
    assert read[0].claims[0]["year_state"] == fields.UNANSWERED
    assert done.asked == 2


def test_a_coordinate_read_before_is_never_touched():
    made, _, _ = comber(
        everything(carrier={"value": "Heizöl", "quote": "Ausblick"}))
    read = reads(claim())
    made(7, read, PASSAGES, [])
    value = read[0].claims[0]
    assert value["carrier"] == "Erdgas" and value["carrier_state"] == fields.READ


def test_a_request_that_does_not_fit_leaves_every_open_coordinate_exhausted():
    made, _, _ = comber(reading.CUT)
    read = reads(claim())
    done = made(7, read, PASSAGES, [])[0]
    value = read[0].claims[0]
    assert value["year_state"] == fields.EXHAUSTED
    assert value["carrier_state"] == fields.READ
    assert done.exhausted == done.open


def test_the_search_ranks_with_the_sentences_of_the_coordinates_asked():
    made, asked, searched = comber({})
    made(7, reads(claim(), probes=[dict(SAID, unit="In t CO2 je Jahr.")]),
         PASSAGES, [])
    # The year group alone has a sentence; the unit is read, not asked.
    assert [probes for probes, _ in searched] == [[SAID["year"]]]
    framed = next(p for p in asked if "year" in p["coordinates"])
    (listed,) = framed["hits"]
    assert listed["query"] == SAID["year"]
    assert all("hits" not in payload for payload in asked
               if "year" not in payload["coordinates"])


def test_without_a_sentence_the_model_searches_itself_with_its_own():
    made, asked, searched = comber(
        dict(everything(),
             more=[{"get": "similar", "text": "Werte für das Jahr 2030"}]),
        dict(everything(), more=[{"get": "hit", "id": "H1"}]),
        everything(year=YEAR))
    read = reads(claim())
    made(7, read, PASSAGES, [])
    assert "hits" not in asked[0]
    assert searched[0] == (["Werte für das Jahr 2030"], {("section", 6)})
    (listed,) = asked[1]["hits"]
    assert listed["similar"] == "Werte für das Jahr 2030"
    assert [hit["title"] for hit in listed["hits"]] == ["Ausblick"]
    value = read[0].claims[0]
    assert value["year"] == 2030 and value["year_state"] == fields.READ
    # Where the run ranks nothing, the search finds nothing and the reply
    # stands.
    made, asked, _ = comber(
        dict(everything(),
             more=[{"get": "similar", "text": "Werte für das Jahr 2030"}]),
        ranking=False)
    done = made(7, reads(claim()), PASSAGES, [])
    assert all(d.missed == 1 and d.asked == 1 and d.hits == 0 for d in done)
