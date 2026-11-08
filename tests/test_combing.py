"""The coordinates the reading left open are asked in a NEW conversation per
value (owner decisions 2026-11-04 to 2026-11-07), and only values with a
coordinate still open are combed. The conversation's first message shows the
value, its answers so far with their quotes and the place's title, AND NOT the
passage itself, which the whole-table conversation alone shows; each later
message carries only what is new.

First the second reading: the sections before and after the value's place are
shown once, AND each open coordinate but the one printed with the number
itself is asked on its own, one message after another, in the order of the
spec's groups, AND its answer may be "not stated", AND a find from those
sections cites them in window `near`.

Then the search, for each coordinate still open that another passage can
state: the first message of a search shows the hits of a ranking with the
sentence written to it, as a list of the best 15 sections, 20 tables and 20
figures, the passage itself and its section left out, AND none of the
sentences, AND lets the model only fetch those hits; later messages may also
search; without a sentence no list is shown and the model searches itself
with "similar", AND that search lists the plan's passages nearest to its own
sentence. A coordinate answered from anything the conversation showed of the
plan (a fetched hit, a hit's line or title, the quote of an answer read) is
read and cites the passage it was shown with in window `retrieval`, AND one
quoting what was never shown is not read AND is told so in the names of what
the conversation shows, AND one whose quote lacks its answer is told to fix it
or leave the coordinate out, never offered "not stated", which the second
reading offers. The search offers no "not stated": its grammar requires no
coordinate and takes no UNSTATED, AND its options leave it out. A coordinate
the reply leaves out, or gives as UNSTATED all the same, is not asked for
again, AND a round that asks for nothing new while one is unfound gets the
next passages of the ranking, of the plan in its order where there is none,
until every passage was listed, AND only then does it end unstated; a find
ends the listing; one whose request no longer fits before that ends
exhausted. One given in another form than asked is asked for again as given
in the wrong form and ends unanswered; a coordinate read before is never
touched; and a request that does not fit leaves the searched coordinates
exhausted.

Every value of a table is asked for itself, AND none takes an answer another
value of its table read. A year nothing found is asked once more with the
plan's base and target years, AND only that request reads a year by the
plan's word for its state; no earlier request is shown those years. Every
conversation shows the titles of the sections up to the value's place.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

import pytest

from docpipe.extraction import combing, fields, reading
from docpipe.extraction.pipeline import Batch, Row, Source, WorkItem, merge_field
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.wording import say


def answered(thread, reply):
    """What the run keeps of an answer (`runner.ask_in_grammar`): a reply
    the conversation goes on after (owner decisions 2026-11-07)."""
    if thread is not None and isinstance(reply, dict):
        thread.messages = [*thread.messages, {"role": "user", "content": ""},
                           {"role": "assistant",
                            "content": json.dumps(reply)}]
    return reply


SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = [slot.name for slot in reading.slots_of(SPEC, EMISSION)]
UNSTATED = fields.UNSTATED
# What the spec says of each coordinate, read from the spec itself.
ORDER = [name for group in SPEC.groups.values() for name in group.coordinates
         if name in SLOTS]
PRINTED = {name for group in SPEC.groups.values()
           for name in group.own_value if name in SLOTS}
SEARCHED = [name for group in SPEC.groups.values()
            for name in group.coordinates if name in SLOTS
            and name not in group.own_value
            and name not in group.own_passage]

OWN = Source("section", 6, "Bilanz\nEs fielen rund 300 t CO2 an.",
             {"document_id": 7, "section_title": "Bilanz"})
NEXT = Source("section", 7, "Weiter\nDazu steht hier nichts.",
              {"document_id": 7, "section_title": "Weiter"})
HIT = Source("section", 8, "Ausblick\nDie Werte gelten für das Jahr 2030.",
             {"document_id": 7, "section_title": "Ausblick"})
# The section after OWN is NEXT, which the second reading shows; HIT is the
# one the search finds.
PASSAGES = {("section", 6): OWN, ("section", 7): NEXT, ("section", 8): HIT}


def claim(**states):
    """A value of OWN: its unit and carrier read, the rest as *states*."""
    out = {"source": "Q1", "value": 300, "quote": "rund 300 t CO2",
           "unit": "t CO2", "unit_state": fields.READ,
           "unit_quote": "rund 300 t CO2", "unit_source": ["section", 6],
           "carrier": "Erdgas", "carrier_state": fields.READ}
    for name in SLOTS:
        out.setdefault(f"{name}_state", fields.SAID_UNSTATED)
    out.update({f"{name}_state": state for name, state in states.items()})
    return out


def only(*names, **more):
    """A value of OWN whose coordinates *names* alone are open."""
    out = claim(**{name: fields.READ for name in SLOTS
                   if name not in names})
    out.update({f"{name}_state": fields.SAID_UNSTATED for name in names})
    out.update(more)
    return out


def reads(*claims, probes=(), source=OWN):
    """The reading of *source* with *claims*, each with the sentences its
    replies wrote to what they found unstated, in *probes* by its order."""
    batch = Batch(7, EMISSION, [WorkItem(7, EMISSION, source)])
    return [reading.Read(batch, list(claims), probes=list(probes))]


def comber(replies=None, ranked=(HIT,), ranking=True, known=None):
    """A Comber whose requests are answered by *replies*, {(kind,
    coordinate): [reply, ...]}, the n-th request of that kind about that
    coordinate by the n-th reply, the last one again after that; kind is
    "near" (the second reading) or "comb" (the search). A request without a
    reply says "not stated" in the second reading and finds nothing in the
    search. Returns it with the messages it was asked (a follow-up as its
    message shows it), the grammar each was asked in, and the searches
    made."""
    asked, shapes, searched, counts = [], [], [], {}

    def ask(payload, shape, document_id, source, group=None, example=None,
            thread=None, follow=None):
        asked.append(payload if follow is None
                     else {**follow, "follows": True})
        schema = shape["json_schema"]
        kind = "near" if schema["name"] == "near_reply" else "comb"
        name = next(key for key in schema["schema"]["properties"]
                    if key != "more")
        shapes.append((kind, name, shape))
        key = (kind, name)
        counts[key] = counts.get(key, 0) + 1
        given = (replies or {}).get(key)
        if given is None:
            reply = {name: {"value": UNSTATED}} if kind == "near" else {}
        else:
            reply = given[min(counts[key], len(given)) - 1]
        return answered(thread, reply)

    def rank(document_id, probes, exclude):
        searched.append((probes, set(exclude)))
        return [s for s in ranked
                if (s.owner_kind, s.owner_id) not in exclude]

    made = combing.Comber(SPEC, ask, rank if ranking else None,
                          known or (lambda claim, names: {}))
    made.shapes = shapes
    return made, asked, searched


def conversations(asked) -> list:
    """The messages of *asked* by conversation, each list beginning with the
    message that shows the value (the comber asks in order without a pool):
    the rounds of a value are one conversation (owner decisions
    2026-11-07)."""
    out = []
    for payload in asked:
        if not payload.get("follows"):
            out.append([])
        out[-1].append(payload)
    return out


def lists_of(asked) -> list:
    """Every list of hits the messages of *asked* brought, in order."""
    return [one for payload in asked for one in payload.get("hits") or ()]


def asked_of(asked) -> list:
    """The coordinate each message of *asked* that asks one names."""
    return [name for payload in asked
            for name in (payload.get("coordinates") or ())]


YEAR = {"value": 2030, "quote": "gelten für das Jahr 2030"}
# What a reading that found the year unstated wrote to it.
SAID = {"year": "Die Emissionen gelten für das Jahr 2022."}


def test_only_values_with_an_open_coordinate_are_combed_in_one_conversation():
    made, asked, _ = comber()
    read = reads(claim(), only())
    done = made(7, read, PASSAGES, [])
    # The value with nothing open is not combed; the other is one
    # conversation, however many coordinates are open.
    assert len(done) == 1 and done[0].rows == 1
    assert len(conversations(asked)) == 1
    # The coordinate the number's own print holds is not asked.
    open_ = [name for name in ORDER if name not in ("unit", "carrier")
             and name not in PRINTED]
    assert done[0].open == len(open_)
    # None is asked of a value that has none open.
    made, asked, _ = comber()
    assert made(7, reads(only()), PASSAGES, []) == [] and asked == []
    # The failure by construction: a coordinate open makes a conversation.
    made, asked, _ = comber()
    assert len(made(7, reads(only("year")), PASSAGES, [])) == 1 and asked


def test_each_message_asks_one_coordinate_in_the_order_of_the_spec():
    made, asked, _ = comber()
    made(7, reads(claim()), PASSAGES, [])
    near = list(dict.fromkeys(name for kind, name, _shape in made.shapes
                              if kind == "near"))
    comb = list(dict.fromkeys(name for kind, name, _shape in made.shapes
                              if kind == "comb"))
    open_ = [name for name in ORDER if name not in ("unit", "carrier")]
    # The second reading asks all but the coordinate the number's own print
    # holds, in the order of the groups; the search then those another
    # passage can state, in the same order.
    assert near == [name for name in open_ if name not in PRINTED]
    assert comb == [name for name in open_ if name in SEARCHED]
    assert PRINTED and not set(PRINTED) & set(near + comb)
    assert all(len(payload["coordinates"]) == 1 for payload in asked
               if "coordinates" in payload)


def test_the_first_message_shows_the_value_and_its_answers_and_not_the_passage():
    made, asked, _ = comber()
    made(7, reads(only("year", "scenario")), PASSAGES, [])
    (conversation,) = conversations(asked)
    first, later = conversation[0], conversation[1:]
    assert first["value"]["value"] == 300
    assert first["value"]["quote"] == "rund 300 t CO2"
    assert first["read"]["unit"] == {"value": "t CO2",
                                     "quote": "rund 300 t CO2"}
    assert first["passage"]["title"] == "Bilanz"
    # The passage itself is not shown: its quote and answers pin it down.
    assert "source" not in first and OWN.text not in json.dumps(
        first, ensure_ascii=False)
    # Each message after brings only what is new, neither the value nor the
    # parameter again.
    assert later and not any({"value", "read", "parameter", "passage",
                              "source"} & set(payload) for payload in later)
    # The titles of the sections up to the value's place, its own last
    # (owner decision 2026-11-07); a value further on is shown more of them.
    assert first["sections"] == ["Bilanz"]
    made, asked, _ = comber()
    made(7, reads(only("year"), source=NEXT), PASSAGES, [])
    assert conversations(asked)[0][0]["sections"] == ["Bilanz", "Weiter"]


def test_the_second_reading_shows_the_sections_around_and_cites_them():
    before = Source("section", 5, "Einleitung\nDie Werte gelten ab 1999.",
                    {"document_id": 7, "section_title": "Einleitung"})
    plan = {("section", 5): before, **PASSAGES}
    ask = {("near", "year"): [{"year": {
        "value": 2030, "quote": "Die Werte gelten ab 1999."}}]}
    made, asked, _ = comber()
    read = reads(only("year"))
    made(7, read, plan, [])
    first = asked[0]
    assert (first["before"], first["after"]) == (before.text, NEXT.text)
    assert list(first["coordinates"]) == ["year"]
    # "not stated" is an answer of the second reading.
    (kind, _name, shape), = made.shapes[:1]
    assert kind == "near" and UNSTATED in json.dumps(shape)
    # A find from the section before is read and cites it in window near.
    year = {"year": {"value": 1999, "quote": "Die Werte gelten ab 1999."}}
    made, asked, _ = comber({("near", "year"): [year]})
    read = reads(only("year"))
    (done,) = made(7, read, plan, [])
    value = read[0].claims[0]
    assert value["year"] == 1999 and value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 5]
    assert list(value["year_window"]) == ["near", 1]
    assert (done.near, done.near_read) == (1, 1)
    # Read in the second reading, the search is not asked for it.
    assert not any(kind == "comb" for kind, _n, _s in made.shapes)
    # The failure by construction: a plan without a section around the place
    # has no second reading, and shows no section.
    made, asked, _ = comber()
    (done,) = made(7, reads(only("year")), {("section", 6): OWN}, [])
    assert done.near == 0
    assert not any(key in payload for payload in asked
                   for key in ("before", "after"))


def test_the_second_reading_may_write_the_sentence_the_search_ranks_with():
    sentence = "Die Werte gelten für das Jahr 2030."
    said = {"year": {"value": UNSTATED, "probe": sentence}}
    made, asked, searched = comber({("near", "year"): [said]})
    made(7, reads(only("year")), PASSAGES, [])
    assert [probes for probes, _ in searched] == [[sentence]]
    # The failure by construction: no sentence, nothing ranked.
    made, asked, searched = comber()
    made(7, reads(only("year")), PASSAGES, [])
    assert searched == []


def test_a_request_shows_one_row_and_its_answers_stand_at_the_top():
    # Owner decision 2026-11-06: no wrapper and no row label.
    slots = reading.slots_of(SPEC, EMISSION)
    schema = combing.comb_response_format(slots)["json_schema"]["schema"]
    assert set(schema["properties"]) == {*SLOTS, "more"}
    more = [{"get": "hit", "id": "H1"}]
    assert combing.as_rows(dict({"year": YEAR}, more=more), "R2") == {
        "rows": [{"year": YEAR, "row": "R2"}], "more": more}
    assert combing.as_rows(reading.CUT, "R2") is reading.CUT
    # Two values are two requests, never one.
    made, _, _ = comber()
    with pytest.raises(ValueError, match="one row"):
        made.comb(7, EMISSION, OWN, slots, [claim(), claim()], PASSAGES, [])


def gets_of(shape) -> list:
    return shape["json_schema"]["schema"]["properties"]["more"]["items"][
        "properties"]["get"]["enum"]


def test_the_first_search_message_only_lists_hits_and_later_ones_may_search():
    made, asked, _ = comber(
        {("comb", "year"): [{"more": [{"get": "hit", "id": "H1"}]},
                            {"more": [{"get": "hit", "id": "H1"}]}]})
    made(7, reads(only("year"), probes=[SAID]), PASSAGES, [])
    comb = [shape for kind, _name, shape in made.shapes if kind == "comb"]
    # The first message lets the model fetch the hits it was shown, nothing
    # else; the message after it may search itself.
    assert gets_of(comb[0]) == list(combing.FIRST_GETS) == ["hit"]
    assert set(gets_of(comb[1])) == set(reading.GETS)
    # The failure by construction: without a list nothing is there to
    # fetch, and the model searches itself at once.
    made, asked, _ = comber(ranked=())
    made(7, reads(only("year")), PASSAGES, [])
    first = [shape for kind, _name, shape in made.shapes if kind == "comb"][0]
    assert set(gets_of(first)) == set(reading.GETS)


def test_the_search_shows_the_best_of_each_kind_as_a_list_without_its_own():
    ranked = ([Source("section", 100 + i, f"S{i}\ntext", {}) for i in range(20)]
              + [Source("table", 200 + i, f"T{i}\n| a |", {}) for i in range(25)]
              + [Source("figure", 300 + i, f"F{i}\nbild", {}) for i in range(3)])
    shown = combing.shown_hits(ranked)
    kinds = [s.owner_kind for s in shown]
    assert kinds.count("section") == 15 and kinds.count("table") == 20
    assert kinds.count("figure") == 3
    assert shown == [s for s in ranked if s in shown]
    made, asked, searched = comber(ranked=(OWN, NEXT, HIT))
    made(7, reads(only("year"), probes=[SAID]), PASSAGES, [])
    # What the conversation shows (the value's place, the section next to
    # it) is not listed as a hit.
    assert searched[0][1] >= {("section", 6), ("section", 7)}
    listed = lists_of(asked)[0]["hits"]
    assert [(hit["id"], hit["title"]) for hit in listed] == [("H1", "Ausblick")]
    assert listed[0]["line"] == "Die Werte gelten für das Jahr 2030."


def test_a_coordinate_answered_from_a_fetched_hit_is_read_and_cites_it():
    made, asked, _ = comber({("comb", "year"): [
        {"more": [{"get": "hit", "id": "H1"}]}, {"year": YEAR}]})
    read = reads(only("year"), probes=[SAID])
    done = made(7, read, PASSAGES, [])[0]
    value = read[0].claims[0]
    assert value["year"] == 2030 and value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 8]
    assert list(value["year_window"]) == ["retrieval", 1]
    assert done.fetched == 1 and done.filled == 1
    (fetched,) = [p for p in asked if p.get("more")]
    assert [m["text"] for m in fetched["more"]] == [HIT.text]


def test_the_search_offers_no_not_stated_and_the_second_reading_does():
    # Owner decision 2026-11-06: the run, not the model, says the plan does
    # not state a coordinate. Neither the search's grammar nor its options
    # offer it.
    slots = reading.slots_of(SPEC, EMISSION)
    schema = combing.comb_response_format(slots)["json_schema"]["schema"]
    assert "required" not in schema
    assert UNSTATED not in json.dumps(schema)
    year = schema["properties"]["year"]["properties"]["value"]
    assert year == {"type": "integer"}
    made, asked, _ = comber()
    made(7, reads(claim()), PASSAGES, [])
    kinds = [kind for kind, _name, _shape in made.shapes]
    shown = [(kind, entry) for kind, payload in zip(kinds, asked)
             for entry in (payload.get("coordinates") or {}).values()]
    searched = [entry for kind, entry in shown if kind == "comb"]
    assert any("options" in entry for entry in searched)
    assert all(UNSTATED not in entry.get("options", {}) for entry in searched)
    # The failure by construction: the second reading offers it, in what it
    # shows and in its grammar.
    assert any(UNSTATED in entry.get("options", {})
               for kind, entry in shown if kind == "near")
    near = combing.near_response_format(slots[:1])["json_schema"]["schema"]
    assert UNSTATED in json.dumps(near)
    assert UNSTATED in reading.coordinate_shown(
        next(slot for slot in slots if slot.is_closed))["options"]


def test_a_quote_from_nothing_the_conversation_showed_is_not_read():
    # Without a sentence no list is shown: the passage that prints the year
    # is in the plan, but the conversation never showed it.
    made, asked, _ = comber({("comb", "year"): [{"year": YEAR}]})
    read = reads(only("year"))
    made(7, read, PASSAGES, [])
    assert read[0].claims[0]["year_state"] == fields.UNBACKED
    # Told in the names of what the conversation shows (owner decision
    # 2026-11-06), not in those of another request.
    (again,) = [p for p in asked if p.get("corrections")]
    assert again["corrections"] == [{"coordinate": "year",
                                     "what": say("quote_not_shown")}]
    # A message after the answer it corrects (owner decisions 2026-11-07).
    assert again["follows"] and "coordinates" not in again


def test_a_quote_from_a_hit_s_line_is_read_and_cites_the_hit():
    # Not fetched: the line the list shows is enough (owner decision
    # 2026-11-05: whatever a request shows of a plan may be quoted).
    made, _, _ = comber({("comb", "year"): [{"year": YEAR}]})
    read = reads(only("year"), probes=[SAID])
    done = made(7, read, PASSAGES, [])
    value = read[0].claims[0]
    assert value["year"] == 2030 and value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 8]
    assert list(value["year_window"]) == ["retrieval", 1]
    assert sum(d.fetched for d in done) == 0
    # The rest of the hit's passage was not shown and does not count.
    later = Source("section", 8, "Ausblick\nDie Werte gelten ab sofort.\n"
                   "Sie gelten für das Jahr 2030.", HIT.provenance)
    made, asked, _ = comber({("comb", "year"): [{"year": YEAR}]},
                            ranked=(later,))
    read = reads(only("year"), probes=[SAID])
    made(7, read, {**PASSAGES, ("section", 8): later}, [])
    assert lists_of(asked)[0]["hits"][0]["line"] == "Die Werte gelten ab sofort."
    assert read[0].claims[0]["year_state"] == fields.UNBACKED


def test_a_quote_from_a_hit_s_title_is_read_and_cites_the_hit():
    titled = Source("table", 9, "| Erdgas | 300 |",
                    {"document_id": 7, "title": "Tabelle 4: Emissionen 2030"})
    made, _, _ = comber({("comb", "year"): [{"year": {
        "value": 2030, "quote": "Tabelle 4: Emissionen 2030"}}]},
        ranked=(titled,))
    read = reads(only("year"), probes=[SAID])
    made(7, read, {**PASSAGES, ("table", 9): titled}, [])
    value = read[0].claims[0]
    assert value["year_state"] == fields.READ
    assert value["year_source"] == ["table", 9]


def test_a_quote_from_an_answer_the_value_has_read_cites_where_it_was_read():
    # The quote of an answer is shown with the answers so far and may be
    # quoted, citing the passage it was read in.
    def read_elsewhere(quote):
        out = only("year")
        out.update(scenario_raw="Szenario Trend", scenario="Trend",
                   scenario_quote=quote, scenario_source=["section", 8])
        return out
    reply = {("comb", "year"): [{"year": {
        "value": 2030, "quote": "Szenario Trend 2030"}}]}
    made, asked, _ = comber(reply)
    read = reads(read_elsewhere("Szenario Trend 2030"))
    made(7, read, PASSAGES, [])
    value = read[0].claims[0]
    assert asked[0]["read"]["scenario"] == {"value": "Szenario Trend",
                                            "quote": "Szenario Trend 2030"}
    assert value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 8]
    # The failure by construction: an answer whose quote lacks the year
    # shows no such passage, and the same quote stands nowhere.
    made, _, _ = comber(reply)
    read = reads(read_elsewhere("Szenario Trend"))
    made(7, read, PASSAGES, [])
    assert read[0].claims[0]["year_state"] == fields.UNBACKED


SECTIONS = [Source("section", 100 + i,
                   f"S{i}\nDie Werte gelten für das Jahr {2000 + i}.", {})
            for i in range(20)]
PLAN = {**PASSAGES, **{(s.owner_kind, s.owner_id): s for s in SECTIONS}}


def test_an_unfound_coordinate_lists_the_plan_to_its_end_then_is_unstated():
    # A reply that finds nothing and asks for nothing: never asked for it
    # again, the next passages of the ranking instead, until every passage
    # was listed (owner decision 2026-11-06: the search runs empty).
    made, asked, _ = comber(ranked=SECTIONS)
    read = reads(only("year"), probes=[SAID])
    (done,) = made(7, read, PLAN, [])
    assert read[0].claims[0]["year_state"] == fields.SAID_UNSTATED
    lists = lists_of(asked)
    listed = [hit["title"] for one in lists for hit in one["hits"]]
    assert sorted(listed) == sorted(s.text.split("\n")[0] for s in SECTIONS)
    assert len(listed) == len(set(listed))       # each passage listed once
    assert [len(one["hits"]) for one in lists] == [15, 5]
    # Each message brings only the list that is new since the answer it
    # follows (owner decisions 2026-11-07): the second reading's, then the
    # search's two lists.
    assert [p.get("follows", False) for p in asked] == [False, True, True]
    assert [len(p["hits"]) for p in asked if "hits" in p] == [1, 1]
    # The sentences ranked with are not shown (owner decision 2026-11-06).
    assert all(set(one) == {"hits"} for one in lists)
    assert done.asked == 3 and done.listed == 1
    assert all("corrections" not in payload for payload in asked)
    # The failure by construction: a find on the second list ends it, read.
    found = {"year": {"value": 2017, "quote": "gelten für das Jahr 2017"}}
    made, asked, _ = comber({("comb", "year"): [{}, found]}, ranked=SECTIONS)
    read = reads(only("year"), probes=[SAID])
    (done,) = made(7, read, PLAN, [])
    value = read[0].claims[0]
    assert value["year_state"] == fields.READ
    assert value["year_source"] == ["section", 117]
    assert done.asked == 3 and done.listed == 1


def test_without_a_ranking_the_plan_is_listed_in_its_order():
    made, asked, _ = comber()
    read = reads(only("year"))
    (done,) = made(7, read, PLAN, [])
    search = [p for p in asked if "coordinates" in p][1:]
    assert search and "hits" not in search[0]
    # The section the second reading showed is not listed again.
    order = [s.text.split("\n")[0] for s in PLAN.values()
             if s not in (OWN, NEXT)]
    listed = [hit["title"] for one in lists_of(asked) for hit in one["hits"]]
    assert listed == ["Ausblick"] + [f"S{i}" for i in range(15)] \
        + [f"S{i}" for i in range(15, 20)]
    assert listed == order
    assert all("query" not in one for one in lists_of(asked))
    assert read[0].claims[0]["year_state"] == fields.SAID_UNSTATED


def test_unstated_from_the_model_is_no_answer_and_the_listing_goes_on():
    # The model writes "not stated" all the same, as an object or a bare
    # word: no answer, not asked for again, and the plan is listed on.
    for said in ({"value": UNSTATED}, UNSTATED, [{"value": UNSTATED}]):
        made, asked, _ = comber({("comb", "year"): [{"year": said}]},
                                ranked=SECTIONS)
        read = reads(only("year"), probes=[SAID])
        (done,) = made(7, read, PLAN, [])
        assert read[0].claims[0]["year_state"] == fields.SAID_UNSTATED
        assert done.listed == 1
        assert all("corrections" not in payload for payload in asked)


def test_a_request_that_no_longer_fits_while_listing_leaves_it_exhausted():
    made, _, _ = comber({("comb", "year"): [{}, reading.CUT]},
                        ranked=SECTIONS)
    read = reads(only("year"), probes=[SAID])
    (done,) = made(7, read, PLAN, [])
    assert read[0].claims[0]["year_state"] == fields.EXHAUSTED
    assert done.exhausted == 1
    # The failure by construction: the same listing that fits ends unstated.
    made, _, _ = comber({("comb", "year"): [{}, {}]}, ranked=SECTIONS)
    read = reads(only("year"), probes=[SAID])
    made(7, read, PLAN, [])
    assert read[0].claims[0]["year_state"] == fields.SAID_UNSTATED


def test_an_answer_in_another_form_is_asked_again_as_such_then_unanswered():
    # A bare year where {"value": 2030, "quote": ...} is asked: a find, so
    # the listing ends, and the correction names the form.
    made, asked, _ = comber({("comb", "year"): [{"year": 2030}]})
    read = reads(only("year"), probes=[SAID])
    (done,) = made(7, read, PASSAGES, [])
    (again,) = [p for p in asked if p.get("corrections")]
    assert again["corrections"] == [{"coordinate": "year",
                                     "what": say("wrong_shape")}]
    assert read[0].claims[0]["year_state"] == fields.UNANSWERED
    assert done.corrected == 1 and done.listed == 0
    # The failure by construction: given in the form asked, it is read.
    made, asked, _ = comber({("comb", "year"): [{"year": 2030},
                                                {"year": YEAR}]})
    read = reads(only("year"), probes=[SAID])
    made(7, read, PASSAGES, [])
    assert read[0].claims[0]["year_state"] == fields.READ


def test_a_quote_without_its_answer_is_told_to_be_fixed_or_left_out():
    # The quote stands in the hit's line but lacks the year: asked again,
    # with no "not stated" offered (owner decision 2026-11-06).
    lacking = {"year": {"value": 2030, "quote": "Die Werte gelten für das"}}
    made, asked, _ = comber({("comb", "year"): [lacking, {}]})
    read = reads(only("year"), probes=[SAID])
    made(7, read, PASSAGES, [])
    (again,) = [p for p in asked if p.get("corrections")]
    (told,) = [one["what"] for one in again["corrections"]
               if one["coordinate"] == "year"]
    # A year may be named by the plan's word ("Basisjahr"): that way first.
    assert told.startswith(say("answer_not_in_quote", answer=2030))
    assert told.endswith(say(combing.NOT_IN_QUOTE, unstated=UNSTATED))
    assert UNSTATED not in told
    assert read[0].claims[0]["year_state"] == fields.UNBACKED
    # The failure by construction: where a request offers "not stated", as
    # the second reading does, the same check offers it.
    slot = next(s for s in reading.slots_of(SPEC, EMISSION)
                if s.name == "year")
    got = merge_field([Row(label="R1", item_index=0, claim={})], [HIT], slot,
                      {"answers": {"R1": lacking["year"]}})
    assert UNSTATED in got["failed"][0]["reason"]


def test_a_coordinate_read_before_is_never_touched():
    made, _, _ = comber({("comb", "carrier"): [{"carrier": {
        "value": "Heizöl", "quote": "Ausblick"}}]})
    read = reads(claim())
    made(7, read, PASSAGES, [])
    value = read[0].claims[0]
    assert value["carrier"] == "Erdgas" and value["carrier_state"] == fields.READ


def test_a_request_that_does_not_fit_leaves_the_searched_coordinates_exhausted():
    made, _, _ = comber({("comb", "year"): [reading.CUT],
                         ("comb", "carrier"): [reading.CUT]})
    read = reads(only("year", "carrier"))
    done = made(7, read, PASSAGES, [])[0]
    value = read[0].claims[0]
    assert value["year_state"] == fields.EXHAUSTED
    assert value["carrier_state"] == fields.EXHAUSTED
    assert done.exhausted == done.open == 2
    # The failure by construction: a coordinate read before is left alone.
    made, _, _ = comber({("comb", "year"): [reading.CUT]})
    read = reads(only("year"))
    done = made(7, read, PASSAGES, [])[0]
    assert read[0].claims[0]["carrier_state"] == fields.READ
    assert done.exhausted == done.open == 1


def test_the_search_ranks_with_the_sentences_of_the_coordinates_asked():
    made, asked, searched = comber(ranked=SECTIONS)
    made(7, reads(only("year", "sector"),
                  probes=[dict(SAID, unit="In t CO2 je Jahr.")]), PLAN, [])
    # The year alone has a sentence; the unit is read, not asked.
    assert [probes for probes, _ in searched] == [[SAID["year"]]]
    search = [(name, payload) for (kind, name, _), payload
              in zip(made.shapes, asked) if kind == "comb"]
    year = [payload for name, payload in search if name == "year"][0]
    (listed,) = year["hits"]
    # Ranked with it, the list does not show it: the run wrote it, the plan
    # does not print it (owner decision 2026-11-06); no message does.
    assert set(listed) == {"hits"} and listed["hits"]
    assert SAID["year"] not in json.dumps(asked, ensure_ascii=False)
    # A coordinate without a sentence starts without a list, and what it
    # lists later is the plan in its order.
    sector = [payload for name, payload in search if name == "sector"][0]
    assert "hits" not in sector
    later = [one for payload in asked[asked.index(sector) + 1:]
             for one in payload.get("hits") or ()]
    assert later and all(set(one) == {"hits"} for one in later)


def test_without_a_sentence_the_model_searches_itself_with_its_own():
    made, asked, searched = comber({("comb", "year"): [
        {"more": [{"get": "similar", "text": "Werte für das Jahr 2030"}]},
        {"more": [{"get": "hit", "id": "H1"}]},
        {"year": YEAR}]})
    read = reads(only("year"))
    made(7, read, PASSAGES, [])
    search = [p for (kind, _n, _s), p in zip(made.shapes, asked)
              if kind == "comb"]
    assert "hits" not in search[0]
    assert searched[0] == (["Werte für das Jahr 2030"],
                           {("section", 6), ("section", 7)})
    (listed,) = search[1]["hits"]
    # Its hits, not its sentence (owner decision 2026-11-06).
    assert set(listed) == {"hits"}
    assert "Werte für das Jahr 2030" not in json.dumps(search[1],
                                                       ensure_ascii=False)
    assert [hit["title"] for hit in listed["hits"]] == ["Ausblick"]
    value = read[0].claims[0]
    assert value["year"] == 2030 and value["year_state"] == fields.READ
    # Where the run ranks nothing, the search finds nothing, and the plan is
    # listed in its order: here its one other passage.
    made, asked, _ = comber({("comb", "year"): [
        {"more": [{"get": "similar", "text": "Werte für das Jahr 2030"}]}]},
        ranking=False)
    (done,) = made(7, reads(only("year")), PASSAGES, [])
    assert done.missed == 1 and done.hits == 1 and done.listed == 1


TABLE = Source("table", 11, "Tabelle 3: Emissionen\n| Träger | t CO2 |\n"
               "| --- | --- |\n| Erdgas | 300 |\n| Heizöl | 27 |",
               {"document_id": 7, "page": 3})
FRAME = ("scenario", "year")


def frame_open(**more):
    """A value of TABLE whose frame alone is open."""
    return only(*FRAME, **more)


def test_every_value_of_a_table_is_combed_for_itself():
    # Owner decision 2026-11-07: each value is asked its own coordinates;
    # none takes what another value of its table read.
    batch = Batch(7, EMISSION, [WorkItem(7, EMISSION, TABLE)])
    gas = frame_open()
    oil = dict(frame_open(), value=27, quote="| Heizöl | 27 |")
    read = [reading.Read(batch, [gas, oil], probes=[SAID, SAID])]
    # The first value's search finds the year, the second's nothing.
    made, asked, _ = comber({("comb", "year"): [{"year": YEAR}, {}]})
    done = made(7, read, {("table", 11): TABLE, **PASSAGES}, [])
    conversation = conversations(asked)
    assert len(done) == 2 and len(conversation) == 2
    assert not any({"whole_table", "source"} & set(c[0]) for c in conversation)
    assert (gas["year"], gas["year_state"]) == (2030, fields.READ)
    # the failure by construction: the other value of the table did not
    # read it, and is not given it
    assert oil["year_state"] != fields.READ and "year_quote" not in oil


# -- a year nothing found ----------------------------------------------------------

STATED = Source("section", 7, "Bestand\nDie Werte zeigen den Bestand.",
                {"document_id": 7, "section_title": "Bestand"})
BASES = [{"state": "base", "axis": "year", "year": 2022,
          "quote": "Das Basisjahr ist 2022.", "source": ["section", 8],
          "index": 0}]
BY_WORD = {"year": {"value": 2022, "value_raw": "Bestand",
                    "quote": "Die Werte zeigen den Bestand."}}


def year_by_word(bases):
    value = only("year")
    made, asked, _ = comber({("near", "year"): [
        {"year": {"value": UNSTATED}}, BY_WORD]})
    (done,) = made(7, reads(value), {("section", 6): OWN,
                                     ("section", 7): STATED,
                                     ("section", 8): HIT}, [], bases=bases)
    return value, done, asked


def test_a_year_nothing_found_is_asked_once_more_with_the_plans_years():
    # Owner decision 2026-11-07: first the model looks for a year; only
    # where nothing found one may it choose the plan's base or target year.
    value, done, asked = year_by_word(BASES)
    (shown,) = [p for p in asked if "plan_years" in p]
    assert shown["plan_years"] == {"base_years": [2022]}
    assert asked.index(shown) == len(asked) - 1
    assert not any("base_years" in json.dumps(p) for p in asked[:-1])
    assert done.plan_years == 1
    assert (value["year"], value["year_state"]) == (2022, fields.READ)
    assert list(value["year_window"]) == ["base_year", 0]
    assert value["year_link_quote"] == "Die Werte zeigen den Bestand."
    # the failure by construction: a plan without base years asks nothing
    # more, and the word reads no year
    value, done, asked = year_by_word(None)
    assert not any("plan_years" in p for p in asked)
    assert done.plan_years == 0 and value["year_state"] != fields.READ


def test_a_year_found_is_never_asked_with_the_plans_years():
    value = only("year")
    made, asked, _ = comber({("near", "year"): [
        {"year": {"value": 2030, "quote": "gelten für das Jahr 2030"}}]})
    made(7, reads(value), {("section", 6): OWN, ("section", 7): HIT},
         [], bases=BASES)
    assert value["year_state"] == fields.READ
    assert not any("plan_years" in p for p in asked)
