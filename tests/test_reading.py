"""A passage is read one value per request (owner decisions 2026-11-04,
2026-11-05 and 2026-11-07): rounds name its values one by one, each round
shown the values read, until the model names none; a value the check refuses
is asked once more with its reason, AND what the fold refuses of a value and
its quote, an answer off its closed list or one its quote does not hold, is
asked once more with the fold's own reason while a value the fold takes is
not, AND one named again is asked once more and, named again, ends the
rounds. A value may stand in any passage a round showed, the passage or the
text around it, AND it is read from the one its quote stands in, which joins
the batch the fold checks it in; a quote in no passage shown is refused.

A round's quote pins its value down: it stands in what was shown exactly
once, AND holds the value exactly once, else the round is asked once more. No
column head is asked. A figure whose image goes with the request may answer
"drawn" and the sentence it read in place of a quote.

Then each coordinate of the spec is asked for each value, one message each in
the order of the spec's groups and of each group's coordinates, AND a
coordinate the spec derives from a unit that was read as an entry of the
parameter's list is not asked; the first message shows what every request of
the parameter shares first and the value last (ticket 26), the pairs and the
plan's years only where it asks a frame coordinate. What the check refuses of
a coordinate's reply is asked once more, and never a third time; a
coordinate left out is asked for by name as missing, AND one given in another
form than asked as given in the wrong form, and both end unanswered; a reply
the check takes whole is asked once. A frame coordinate left open takes the
survey's one tuple, but not against a year the value read of its own.

A table too long for the model's window is read in halves of its rows, AND
a single row that does not fit, or a piece no round answered, is a hole of
its own while the others are read. A table or figure is shown with its
whole section, other tables and figures of it included, AND with the part
around its placeholder where the section is longer than the survey's two
pages (owner decision 2026-11-05); a coordinate quoted from there cites the
section. A passage is shown with the heading it stands under, a table's or
figure's that of its section, a section's its own, AND a quote may stand in
that heading where the passage's text does not carry it. A quote from a
section the request did not show is not read in the reading.

A reading offers no tools (owner decision 2026-11-05, ticket 26): its
requests carry no hit list and its grammars no ask for more. The rounds and
every group but the one that classifies show the parameter's brief, that one
its full definition, AND a parameter without a brief shows its definition
everywhere. Each group is sent the prompt's shared part with its own
section, AND a prompt with a section missing, left over or twice fails, while
a prompt without sections is every group's.

A coordinate reply writes to a coordinate it finds unstated a sentence as the
plan would print it, AND that sentence is kept beside its value for the
combing, never on the claim. The combing's tools show the next section, a
table or figure by its placeholder and a hit by its id, each once; "similar"
lists the passages of the plan nearest to the model's own sentence, the best
of each kind, AND without a ranking it finds nothing and says so; no list
shows what it was searched with, AND the gathering keeps it, so the same
search is not made twice; the gathering ends when a round brings nothing new,
AND a request that no longer fits leaves the reply before it.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from dataclasses import replace
from pathlib import Path

import jsonschema

from docpipe.extraction import fields, lookup, reading, surveyed, thread
from docpipe.extraction.pipeline import Row, Source, merge_field, route_claims
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import verify_tuple
from docpipe.extraction.wording import say
from docpipe.prompts import Prompt

SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = {slot.name: slot for slot in reading.slots_of(SPEC, EMISSION)}
UNSTATED = fields.UNSTATED
FRAME = [slot for slot in reading.slots_of(SPEC, EMISSION)
         if slot.name in ("scenario", "year")]
GROUPS = reading.groups_of(SPEC, list(SLOTS.values()))
# The groups that ask a frame coordinate: they alone are shown the pairs.
FRAMED = {group.name for group, slots in GROUPS
          if {slot.name for slot in slots} & {slot.name for slot in FRAME}}

TEXT = Source("section", 6, "Im Jahr 2022 fielen rund 300 t CO2 bei Erdgas "
              "und 27 t CO2 bei Heizöl an.",
              {"document_id": 7, "section_title": "Bilanz"})
V300 = {"value": 300, "quote": "rund 300 t CO2 bei Erdgas"}
V27 = {"value": 27, "quote": "27 t CO2 bei Heizöl"}
UNIT = {"value": "t CO2", "quote": "rund 300 t CO2"}

TABLE = ("Tabelle 3: Treibhausgasemissionen der Stadt in t CO2\n"
         "| Träger | Haushalte | GHD | gesamt |\n"
         "| --- | --- | --- | --- |\n"
         "| Erdgas | 1.200 | 800 | 2.000 |\n"
         "| Heizöl | 27 | 28 | 27 |")
OIL = "| Heizöl | 27 | 28 | 27 |"


def table(text=TABLE, owner=5, **provenance):
    return Source("table", owner, text, {"document_id": 7, "page": 3,
                                         "section_title": "Bilanz",
                                         **provenance})


# More requests than any reading here needs: a reading that asks on is one
# whose rounds do not end.
ENDLESS = 200


def nth(given, calls, task):
    """The reply to the latest request of *task*: the n-th of *given* for
    its n-th request, the last one again after that."""
    assert len(calls) < ENDLESS, "the reading asks without end"
    n = sum(1 for asked, _ in calls if asked == task)
    return given[min(n, len(given)) - 1]


def answered(thread, reply):
    """What the run keeps of an answer (`runner.ask_in_grammar`): a reply
    the conversation goes on after."""
    if isinstance(reply, dict):
        thread.messages = [*thread.messages,
                           {"role": "user", "content": ""},
                           {"role": "assistant",
                            "content": json.dumps(reply)}]
    return reply


def sent(thread, follow, first):
    """What a request sends as the run builds it (`runner.make_reader`): a
    first message shows *first()*, a follow-up only its fields, marked
    "follows", after the answer of its conversation; the conversation is
    kept under "thread"."""
    if follow is not None:
        assert thread.begun, "a follow-up without an answer to follow"
        return {**follow, "follows": True, "thread": thread}
    payload = first()
    if not thread.begun:
        thread.first = payload
    return {**payload, "thread": thread}


def asking(values=({"value": None},), groups=None, spec=SPEC, **kw):
    """A Reader whose values requests are answered by *values* in turn and
    the request of each coordinate by *groups[coordinate]* in turn (each a
    whole reply, `{coordinate: answer}`), any other coordinate with "not
    printed"; and each request as (task, payload), the task "values" or the
    coordinate asked, the payload built as the run builds it (`sent`)."""
    calls = []

    def ask_values(source, parameter, context, read, thread, follow=None,
                   drawn=False):
        calls.append(("values", sent(thread, follow, lambda:
                                     reading.values_payload(
                                         source, parameter, context, read,
                                         drawn))))
        return answered(thread, nth(values, calls, "values"))

    def ask_text(source, parameter, group, slots, row, context, thread,
                 follow=None):
        # One coordinate in each message (owner decision 2026-11-07).
        assert len(slots) == 1, "a message asks one coordinate"
        name = slots[0].name
        if thread.begun and follow is None:
            first = lambda: reading.group_payload(
                parameter, slots, group.where, context,
                full=group.full_definition)
        else:
            first = lambda: reading.text_payload(
                source, parameter, slots, row, group.where, context,
                full=group.full_definition)
        calls.append((name, sent(thread, follow, first)))
        given = (groups or {}).get(name)
        if given is None:
            reply = {name: {"value": UNSTATED}}
        else:
            reply = nth(given, calls, name)
        return answered(thread, reply)

    return reading.Reader(spec, ask_values, ask_text, **kw), calls


def read_of(source, *, values=({"value": None},), groups=None, pairs=(),
            tuples=(), passages=None, **kw):
    reader, calls = asking(values, groups, **kw)
    passages = passages or {(source.owner_kind, source.owner_id): source}
    read = reader.read(7, EMISSION, source, list(pairs), passages)
    return read, calls


def rounds(calls) -> list:
    return [payload for task, payload in calls if task == "values"]


def corrections_of(calls) -> list:
    return [(task, payload["corrections"]) for task, payload in calls
            if payload.get("corrections")]


def firsts(calls) -> list:
    """(task, payload) of each first message: the ones that show the
    passage."""
    return [(task, payload) for task, payload in calls if "source" in payload]


def unstated_but(**given) -> dict:
    """A reply to the second reading of EMISSION: every coordinate not
    printed but those *given*."""
    return {**{slot.name: {"value": UNSTATED}
               for slot in reading.slots_of(SPEC, EMISSION)}, **given}


def test_a_table_gives_its_rows_cell_by_cell_and_text_gives_none():
    grid = reading.grid_of(TABLE)
    assert grid.columns == 4 and len(grid.body) == 2
    assert grid.body[1][1] == ["Heizöl", "27", "28", "27"]
    assert reading.grid_of("Ein Satz ohne Tabelle.") is None


# -- the values of a passage, one per round ---------------------------------------

def test_each_round_names_the_next_value_and_the_rounds_end_on_none():
    # The rounds are one conversation (owner decisions 2026-11-07): the
    # first message shows the passage, each later one asks for the next
    # value after the answer it follows, and nothing lists what was named.
    read, calls = read_of(TEXT, values=(V300, V27,
                                        {"value": None}))
    asked = rounds(calls)
    assert [p.get("follows", False) for p in asked] == [False, True, True]
    assert all(set(p) == {reading.NEXT, "follows", "thread"}
               for p in asked[1:])
    assert "read" not in asked[0]
    assert len({id(p["thread"]) for p in asked}) == 1
    assert [c["value"] for c in read.claims] == [300, 27]
    none, calls = read_of(TEXT)
    assert none.claims == [] and not none.unread and len(rounds(calls)) == 1


def test_a_value_the_check_refuses_is_asked_once_more_with_its_reason():
    for wrong, why in (
            (dict(V300, quote="rund 300 t CO2 im Jahr"),       # in no passage
             say("quote_not_in_passage")),
            (dict(V300, value=300000), say("value_outside_quote", values=json
                                           .dumps([{"value": 300000,
                                                    "quote": V300["quote"]}],
                                                  ensure_ascii=False)))):
        read, calls = read_of(TEXT, values=(wrong, V300,
                                            {"value": None}))
        assert corrections_of(calls) == [("values", [dict(wrong, what=why)])]
        assert [(c["value"], c["quote"]) for c in read.claims] \
            == [(300, V300["quote"])]
        assert read.corrected == 1 and read.failed == {reading.VALUE: 1}
    _read, calls = read_of(TEXT, values=(V300, {"value": None}))
    assert corrections_of(calls) == []


SCENARIOS = load_spec(json.loads((Path(__file__).resolve().parent.parent
                            / "profiles" / "scenarios" / "extraction_spec.json")
                           .read_text(encoding="utf-8")))
SECTOR = SCENARIOS.by_uri["study_sector"]
COVERS = Source("section", 8, "Scope\nThe model covers the building, "
                "transport and industry sectors.",
                {"document_id": 7, "section_title": "Scope"})
NAMED = "covers the building, transport and industry"


def sector_read(*values):
    reader, calls = asking(values, spec=SCENARIOS)
    read = reader.read(7, SECTOR, COVERS, [],
                       {(COVERS.owner_kind, COVERS.owner_id): COVERS})
    return read, calls


def test_what_the_fold_refuses_of_a_value_is_asked_with_the_fold_s_reason():
    right = {"value": "industry sector", "value_raw": "industry",
             "quote": NAMED}
    for wrong in ({"value": "bioenergy", "quote": NAMED},       # off its list
                  {"value": "industry sector", "quote": NAMED}):  # not quoted
        read, calls = sector_read(wrong, right,
                                  {"value": None})
        why = verify_tuple(wrong, SECTOR, COVERS.text).reason
        assert corrections_of(calls) == [("values", [dict(
            wrong, what=say("value_rejected", reason=why))])]
        assert [(c["value"], c.get("value_raw"))
                for c in read.claims] == [("industry sector", "industry")]
        assert read.corrected == 1 and read.failed == {reading.VALUE: 1}
    # the failure by construction: a value the fold takes is not asked again
    read, calls = sector_read(right, {"value": None})
    assert corrections_of(calls) == [] and len(read.claims) == 1


def test_a_value_named_again_is_asked_once_more_and_then_ends_the_rounds():
    read, calls = read_of(TEXT, values=(V300, V300,
                                        V27, {"value": None}))
    assert corrections_of(calls) == [("values", [dict(V300, what=say(
        "value_already_read", value="300", quote=V300["quote"]))])]
    assert [c["value"] for c in read.claims] == [300, 27]
    stuck, calls = read_of(TEXT, values=(V300,))
    assert [c["value"] for c in stuck.claims] == [300]
    assert len(rounds(calls)) == 3          # the value, again, again: done
    assert stuck.failed == {reading.REPEATED: 1}


# -- a value in any passage shown ------------------------------------------------

SECTION = Source("section", 9,
                 "Bilanz\nDie folgende Tabelle zeigt die Emissionen im Jahr "
                 "2022.\n[p2_tbl5: Tabelle 3]\nInsgesamt fielen 2.027 t CO2 an.",
                 {"document_id": 7, "section_title": "Bilanz"})
AROUND = {"value": 2027, "quote": "Insgesamt fielen 2.027 t CO2 an"}


def placed():
    return table(parent_section=9, block_id="p2_tbl5")


def test_a_value_in_the_text_around_a_table_is_read_from_its_section():
    passages = {("table", 5): placed(), ("section", 9): SECTION}
    read, calls = read_of(placed(), values=(AROUND, {"value": None}),
                          passages=passages)
    claim = read.claims[0]
    assert corrections_of(calls) == [] and claim["value"] == 2027
    assert [(i.source.owner_kind, i.source.owner_id)
            for i in read.batch.items] == [("table", 5), ("section", 9)]
    routed, orphans = route_claims(read.batch, read.claims)
    assert [len(r) for r in routed] == [0, 1] and orphans == []
    # Not shown, the section holds no value of this reading.
    alone, calls = read_of(placed(), values=(AROUND, {"value": None}))
    assert corrections_of(calls)[0][1][0]["what"] == say("quote_not_in_passage")
    assert len(alone.batch.items) == 1


BARE = Source("section", 6, "Bilanz\nEs fielen rund 300 t CO2 an.",
              {"document_id": 7, "section_title": "Bilanz"})


# -- a value's quote pins it down ------------------------------------------------

def test_a_quote_that_holds_its_number_twice_is_asked_once_more():
    # "27" is printed twice in the row (owner decision 2026-11-07: a quote
    # holds its value exactly once), so the row does not pin one down.
    both = {"value": 27, "quote": OIL}
    one = {"value": 27, "quote": "| Heizöl | 27 | 28"}
    read, calls = read_of(table(), values=(both, one, {"value": None}))
    assert corrections_of(calls) == [("values", [dict(both, what=say(
        "value_not_once", value="27", quote=OIL))])]
    assert [(c["value"], c["quote"]) for c in read.claims]         == [(27, one["quote"])]
    assert read.corrected == 1 and read.failed == {reading.UNIQUE: 1}
    # the failure by construction: a quote with the number once is not asked
    # again
    read, calls = read_of(table(), values=(one, {"value": None}))
    assert corrections_of(calls) == [] and read.failed == {}


def test_a_quote_that_stands_twice_in_what_was_shown_is_asked_once_more():
    twice = Source("section", 6, "Im Norden fielen rund 300 t CO2 an. Im "
                   "Süden fielen rund 300 t CO2 an.",
                   {"document_id": 7, "section_title": "Bilanz"})
    vague = {"value": 300, "quote": "fielen rund 300 t CO2 an"}
    south = {"value": 300, "quote": "Süden fielen rund 300 t CO2 an"}
    read, calls = read_of(twice, values=(vague, south, {"value": None}))
    assert corrections_of(calls) == [("values", [dict(vague, what=say(
        "quote_not_unique", quote=vague["quote"]))])]
    assert [c["quote"] for c in read.claims] == [south["quote"]]
    assert read.failed == {reading.UNIQUE: 1}
    # the failure by construction: the same quote standing once is taken
    read, calls = read_of(TEXT, values=(V300, {"value": None}))
    assert corrections_of(calls) == [] and read.failed == {}


def test_a_quote_asked_once_more_is_asked_once_and_then_taken_as_given():
    both = {"value": 27, "quote": OIL}
    read, calls = read_of(table(), values=(both, both, {"value": None}))
    assert len(corrections_of(calls)) == 1
    assert [c["value"] for c in read.claims] == [27]


def test_a_coordinate_may_quote_what_its_value_has_read():
    # The unit its answer gave it, shown in a wording the passage does not
    # print: quoted, the coordinate cites where the unit was read (owner
    # decision 2026-11-05: whatever a request shows of a plan may be
    # quoted).
    def known(claim, asked):
        return ({"unit": "Szenario Bestand 2022"}
                if claim.get("unit_state") == "read" else {})
    subject = {"unit": [{"unit": UNIT}], "subject": [{"subject": {
        "value": "Szenario Bestand", "quote": "Szenario Bestand 2022"}}]}
    read, calls = read_of(TEXT, values=(V300, {"value": None}),
                          groups=subject, known=known)
    claim = read.claims[0]
    assert claim["subject_state"] == "read"
    assert claim["subject_source"] == claim["unit_source"]
    # Not shown, the same quote stands nowhere.
    alone, _ = read_of(TEXT, values=(V300, {"value": None}), groups=subject)
    assert alone.claims[0]["subject_state"] == "unbacked"


# -- one request per value and coordinate -------------------------------------

# The order of a coordinate's first request (ticket 26): the parameter's, the
# plan's, the passage's, the value's.
TEXT_KEYS = ("parameter", "coordinates", "where", "title_page", "settings",
             "sections", "source", "around", "table_before", "value")
# The coordinates a value is asked in the order of the spec's groups and of
# each group's coordinates (owner decision 2026-11-07), written out of the
# spec itself.
ASKED = [name for group in SPEC.groups.values() for name in group.coordinates
         if name in SLOTS]


def test_each_value_is_one_conversation_and_each_coordinate_a_message_of_it():
    # Owner decisions 2026-11-07: the first message shows the passage and
    # the value with the first coordinate; each further coordinate is a
    # message of the same conversation with its own question only; no
    # coordinate is shown pairs of its passage.
    read, calls = read_of(TEXT, values=(V300, V27, {"value": None}))
    asked = [(task, payload) for task, payload in calls if task != "values"]
    n = len(ASKED)
    assert n > len(GROUPS)
    assert [task for task, _ in asked] == ASKED * 2
    assert [p["value"]["value"] for _, p in firsts(asked)] == [300, 27]
    for value in (asked[:n], asked[n:]):
        assert len({id(p["thread"]) for _, p in value}) == 1
    assert asked[0][1]["thread"] is not asked[n][1]["thread"]
    for index, (task, payload) in enumerate(asked):
        assert "known" not in payload, task
        assert [list(payload["coordinates"])] == [[task]]
        keys = [key for key in payload if key != "thread"]
        if index % n:
            # A further coordinate: neither the passage nor the value again.
            assert "source" not in payload and "value" not in payload
        else:
            # What every request of the parameter shares first, the value
            # last.
            assert keys == [key for key in TEXT_KEYS if key in payload]
            assert keys[0] == "parameter" and keys[-1] == "value"
    assert read.asked == 3 + 2 * n


def test_what_the_unit_could_decide_is_asked_and_derived_only_where_open():
    # Owner decision 2026-11-07: the coordinate the spec derives from the
    # unit ("aggregation") is asked like any other, and taken from the unit
    # only where no request read it, once reading and combing are done.
    read, calls = read_of(TEXT, values=ONE, groups={"unit": [{"unit": UNIT}]})
    claim = read.claims[0]
    assert claim["unit_state"] == "read"
    assert "aggregation" in {task for task, _ in calls}
    assert claim["aggregation_state"] == "unstated"
    assert surveyed.derive_left([read]) == 1
    assert claim["aggregation_state"] == "derived"
    assert claim["aggregation_raw"] == "t CO2"
    # the failure by construction: an aggregation the model read stays
    # what it read
    kept, _ = read_of(TEXT, values=ONE, groups={"unit": [{"unit": UNIT}]})
    kept.claims[0].update(aggregation="out:other", aggregation_state="read")
    assert surveyed.derive_left([kept]) == 0
    assert kept.claims[0]["aggregation"] == "out:other"
    # and a unit the plan printed that is no entry of the list decides
    # nothing
    odd = {"value": "Tonnen Kohlenstoff", "quote": "rund 300 t CO2"}
    other, _ = read_of(TEXT, values=ONE, groups={"unit": [{"unit": odd}]})
    assert surveyed.derive_left([other]) == 0
    assert other.claims[0].get("aggregation_state") != "derived"


WRONG_CARRIER = {"value": "Erdgas", "quote": "Erdgas steht hier nicht"}
RIGHT_CARRIER = {"value": "Erdgas", "quote": "300 t CO2 bei Erdgas"}

ONE = (V300, {"value": None})


def test_a_coordinate_the_check_refuses_is_asked_again_by_its_coordinate():
    read, calls = read_of(TEXT, values=ONE, groups={"carrier": [
        {"carrier": WRONG_CARRIER}, {"carrier": RIGHT_CARRIER}]})
    assert corrections_of(calls) == [("carrier", [
        {"coordinate": "carrier", "what": say("quote_not_in_passage")}])]
    claim = read.claims[0]
    assert claim["carrier"] == "Erdgas" and claim["carrier_state"] == "read"


def test_a_reply_wrong_twice_is_not_asked_a_third_time():
    read, calls = read_of(TEXT, values=ONE, groups={"carrier": [
        {"carrier": WRONG_CARRIER}]})
    assert [task for task, _ in calls].count("carrier") == 2
    assert read.claims[0]["carrier_state"] == "unbacked"


def test_a_reply_the_check_takes_whole_is_asked_once():
    read, calls = read_of(TEXT, values=ONE, groups={"carrier": [
        {"carrier": RIGHT_CARRIER}]})
    assert [task for task, _ in calls] == ["values", "values"] + ASKED
    assert read.asked == 2 + len(ASKED)
    assert corrections_of(calls) == []


def test_a_coordinate_left_out_of_the_reply_is_asked_for_by_name_once():
    # The reply names no "sector": asked once more for it, and the answer
    # that follows stands; the coordinate read before it is not asked again.
    read, calls = read_of(TEXT, values=ONE, groups={
        "carrier": [{"carrier": RIGHT_CARRIER}],
        "sector": [{}, {"sector": {"value": UNSTATED}}]})
    assert corrections_of(calls) == [("sector", [
        {"coordinate": "sector", "what": say("key_missing", key="sector")}])]
    claim = read.claims[0]
    assert claim["carrier"] == "Erdgas" and claim["carrier_state"] == "read"
    assert claim["sector_state"] == "unstated"
    assert [task for task, _ in calls].count("carrier") == 1


def test_a_coordinate_left_out_is_asked_for_by_name_and_ends_unanswered():
    read, calls = read_of(TEXT, values=ONE, groups={"year": [
        {"scenario": {"value": UNSTATED}}]})
    assert corrections_of(calls) == [("year", [
        {"coordinate": "year", "what": say("key_missing", key="year")}])]
    assert read.claims[0]["year_state"] == "unanswered"
    assert read.unanswered == 1


def test_a_coordinate_in_another_form_is_asked_again_as_such():
    # A bare word where an object with "value" is asked: the correction names
    # the form, not a missing answer (owner decision 2026-11-06).
    read, calls = read_of(TEXT, values=ONE, groups={"year": [
        {"year": UNSTATED}]})
    assert corrections_of(calls) == [("year", [
        {"coordinate": "year", "what": say("wrong_shape")}])]
    assert read.claims[0]["year_state"] == "unanswered"


# -- several entries, a span of years --------------------------------------------

def test_a_value_stated_for_two_entries_is_one_row_per_entry():
    # Owner decision 2026-11-07: "Fernwärme + Gas-NT" is the value once
    # with each.
    carrier = SLOTS["carrier"]
    if not reading.several(carrier):
        carrier = replace(carrier, several=True)
    both = {"carrier": [{"value": "Erdgas", "quote": "300 t CO2 bei Erdgas"},
                        {"value": "Fernwärme", "quote": "300 t CO2 bei Erdgas"}]}
    assert len(reading.answers_each(both, [carrier])) == 2
    # the failure by construction: a list that may name one entry only is
    # one reply
    single = replace(carrier, several=False)
    assert len(reading.answers_each(both, [single])) == 1


def test_a_span_of_years_is_one_row_per_year_marked_as_the_profile_says():
    year = SLOTS["year"]
    quote = "im Mittel der Jahre 2019 bis 2021"
    row = Row(label="R1", item_index=0, claim={
        "value": 300, "year": 2019, "year_state": "read",
        "year_quote": quote, "year_raw": "2019 bis 2021"})
    made = []

    def clone(one):
        copied = Row(label=f"R{len(made) + 2}", item_index=0,
                     claim=dict(one.claim))
        made.append(copied)
        return copied
    marks = {"qualifier": "out:approximate"}
    got = reading.span_rows(row, year, reading.until_of(
        year, {"year": {"value": 2019, "until": 2021, "quote": quote}}),
        marks, clone)
    assert [r.claim["year"] for r in [row] + got] == [2019, 2020, 2021]
    assert [r.claim["year_state"] for r in [row] + got] \
        == ["read", "derived", "read"]
    assert all(r.claim["qualifier"] == "out:approximate"
               and r.claim["qualifier_state"] == "derived"
               for r in [row] + got)
    # the failure by construction: a last year its quote does not print
    # makes no rows
    alone = Row(label="R9", item_index=0, claim={
        "value": 300, "year": 2019, "year_state": "read",
        "year_quote": "im Jahr 2019 und danach"})
    assert reading.span_rows(alone, year, 2021, marks, clone) == []
    assert "qualifier" not in alone.claim


# -- the grammars ---------------------------------------------------------------

def rejected(instance, schema) -> bool:
    try:
        jsonschema.validate(instance, schema)
    except jsonschema.ValidationError:
        return True
    return False


def values_grammar(drawn=False, parameter=EMISSION):
    return reading.values_response_format(parameter, drawn)["json_schema"][
        "schema"]


def properties_of(schema) -> set:
    """Every key a grammar takes at its top, over its alternatives."""
    keys = set(schema.get("properties") or ())
    for one in schema.get("anyOf") or ():
        keys |= set(one.get("properties") or ())
    return keys


def coordinate_grammar(name):
    return reading.text_response_format([SLOTS[name]])["json_schema"][
        "schema"]


def test_a_round_names_one_value_or_none():
    assert not rejected({"value": None}, values_grammar())
    assert not rejected(V300, values_grammar())
    assert rejected({"value": 300}, values_grammar())     # no quote
    assert rejected([V300], values_grammar())
    # No column head is asked (owner decision 2026-11-07).
    assert rejected(dict(V300, head="gesamt"), values_grammar())
    # No wrapper (owner decision 2026-11-06): the reply as it was before is
    # refused, and a free text value carries no wording beside it, which a
    # number may.
    assert rejected({"next": V300}, values_grammar())
    assert not rejected(dict(V300, value_raw="300"), values_grammar())
    office = SPEC.by_uri["planning_organisation"]
    named = {"value": "Planungsbüro A", "quote": "Planungsbüro A GmbH"}
    assert not rejected(named, values_grammar(parameter=office))
    assert rejected(dict(named, value_raw="Planungsbüro A"),
                    values_grammar(parameter=office))


def test_a_figure_with_its_image_may_answer_drawn_and_read_in_place_of_a_quote():
    # Owner decision 2026-11-07: where the image goes with the request, a
    # number only the image shows is answered "drawn" with what was read.
    off = {"value": 300, "drawn": True, "reading": "Balken bei 300 t CO2"}
    assert not rejected(off, values_grammar(drawn=True))
    assert not rejected(dict(V300, drawn=False), values_grammar(drawn=True))
    assert rejected({"value": 300, "quote": V300["quote"]},
                    values_grammar(drawn=True))          # "drawn" is asked
    # the failures by construction: without the image there is no such
    # answer and a quote is required
    assert rejected(off, values_grammar())
    assert rejected({"value": 300, "drawn": True}, values_grammar())


def test_a_coordinate_reply_answers_the_one_coordinate_asked_and_no_other():
    whole = {"year": {"value": UNSTATED}}
    assert not rejected(whole, coordinate_grammar("year"))
    assert rejected({}, coordinate_grammar("year"))
    assert rejected({"scenario": {"value": UNSTATED}},
                    coordinate_grammar("year"))
    assert rejected(dict(whole, unit={"value": UNSTATED}),
                    coordinate_grammar("year"))


def test_a_year_can_be_answered_as_not_printed_and_only_as_a_year():
    year = reading.answer_schema(SLOTS["year"])
    assert not rejected({"value": 2022}, year)
    assert not rejected({"value": UNSTATED}, year)
    assert rejected({"value": "2022 bis 2030"}, year)


# -- a table too long for the model's window ------------------------------------

LONG = "\n".join(["Tabelle 7: Endenergie je Träger im Jahr 2022 in MWh",
                  "| Träger | 2022 | 2045 |",
                  "| --- | --- | --- |"]
                 + [f"| Träger {n} | {n}.100 | {n}.200 |" for n in range(1, 9)])


def test_a_table_splits_into_halves_of_its_rows_under_its_title_and_head():
    first, second = reading.halves(table(LONG))
    for half in (first, second):
        assert half.text.startswith("Tabelle 7")
        assert "| Träger | 2022 | 2045 |" in half.text
    rows = [len(reading.grid_of(h.text).body) for h in (first, second)]
    assert rows == [4, 4]
    one = table("\n".join(LONG.splitlines()[:4]))
    assert reading.halves(one) == [] and reading.halves(TEXT) == []


def model(cut=lambda rows: False, silent=lambda rows: False):
    """A model reading LONG: CUT where *cut* says the rows shown do not fit,
    no reply where *silent* says so, else the next value of column 2."""
    def answer(source, parameter, context, read, thread, follow=None,
               drawn=False):
        body = [cells for _line, cells in reading.grid_of(source.text).body]
        labels = [cells[0] for cells in body]
        if cut(labels):
            return reading.CUT
        if silent(labels):
            return None
        # What the conversation has named, and what a conversation begun
        # anew shows under "read".
        done = {r["value"] for r in read} | {
            json.loads(m["content"]).get("value")
            for m in thread.messages if m["role"] == "assistant"}
        for line, cells in reading.grid_of(source.text).body:
            value = int(cells[1].replace(".", ""))
            if value not in done:
                return {"value": value, "quote": line}
        return {"value": None}
    return answer


def read_long(answer):
    shown = []

    def ask_values(source, parameter, context, read, thread, follow=None,
                   drawn=False):
        assert len(shown) < ENDLESS, "the reading asks without end"
        shown.append([c[0] for _l, c in reading.grid_of(source.text).body])
        return answered(thread, answer(source, parameter, context, read,
                                       thread, follow, drawn))

    reader = reading.Reader(SPEC, ask_values, lambda *a, **k: {})
    long = table(LONG)
    return reader.read(7, EMISSION, long, [], {("table", 5): long}), shown


ALL = [n * 1000 + 100 for n in range(1, 9)]


def test_a_table_too_long_is_read_in_halves_and_one_row_that_still_is_lost():
    whole, _ = read_long(model())
    assert sorted(c["value"] for c in whole.claims) == ALL
    halved, shown = read_long(model(cut=lambda rows: len(rows) > 4))
    assert sorted(c["value"] for c in halved.claims) == ALL
    assert halved.lost == [] and not halved.unread
    lost, shown = read_long(model(cut=lambda rows: "Träger 4" in rows))
    assert sorted(c["value"] for c in lost.claims) == [v for v in ALL
                                                       if v != 4100]
    assert lost.lost == [reading.CUT] and not lost.unread
    assert ["Träger 4"] in shown


def test_a_piece_no_round_answered_is_a_hole_and_every_piece_cut_is_unread():
    silent, shown = read_long(model(cut=lambda rows: len(rows) > 4,
                                    silent=lambda rows: "Träger 4" in rows))
    assert sorted(c["value"] for c in silent.claims) == ALL[4:]
    assert silent.lost == [reading.NO_ANSWER]
    assert len([rows for rows in shown if "Träger 4" in rows]) == 2  # no half
    every, _ = read_long(model(cut=lambda rows: True))
    assert every.unread and every.why == reading.CUT and every.lost == []


# -- the plan's own years -------------------------------------------------------

BASES = [{"state": "base", "axis": "year", "year": 2022,
          "quote": "im Jahr 2022", "source": ["table", 5], "index": 0},
         {"state": "target", "axis": "year", "year": 2045,
          "quote": "bis zum Jahr 2045", "source": ["table", 5], "index": 1}]


def test_no_coordinate_of_the_reading_is_shown_the_base_and_target_years():
    # Owner decision 2026-11-07: the model looks for a year first; only
    # where nothing found one is it shown the plan's years (`combing`).
    assert reading.years_of(BASES, list(SLOTS.values())) \
        == {"base_years": [2022], "target_years": [2045]}
    assert reading.years_of(BASES, [SLOTS["carrier"]]) == {}
    _read, calls = read_of(TEXT, values=ONE, bases=lambda pairs: BASES)
    shown = {task: (p.get("base_years"), p.get("target_years"))
             for task, p in calls if task != "values"}
    assert shown == {name: (None, None) for name in ASKED}


STATE = Source("section", 6, "Im Bestand fielen rund 300 t CO2 an.",
               {"document_id": 7, "section_title": "Bilanz"})


def read_by_word(year):
    read, _ = read_of(STATE, values=({"value": 300, "quote":
                                               "rund 300 t CO2"},
                                     {"value": None}),
                      groups={"year": [{"year": {
                          "value": year, "value_raw": "Bestand",
                          "quote": "Im Bestand fielen rund 300 t CO2"}}]},
                      bases=lambda pairs: BASES)
    return read.claims[0]


def test_the_reading_takes_no_year_its_quote_does_not_print():
    # Owner decision 2026-11-07: a year named by the plan's word for its
    # state is read only in the request that shows the plan's years, once
    # nothing found a year (`combing.PLAN_YEARS`); the reading takes none.
    assert read_by_word(2022)["year_state"] == "unbacked"
    assert read_by_word(2019)["year_state"] == "unbacked"


# -- the text around a table -----------------------------------------------------

def test_a_table_is_shown_with_its_section_or_the_part_around_its_place():
    passages = {("section", 9): SECTION}
    assert reading.around_of(placed(), passages, 4000).text == SECTION.text
    long = replace(SECTION, text="x" * 5000 + "[p2_tbl5: Tabelle 3]"
                   + "y" * 5000)
    cut = reading.around_of(placed(), {("section", 9): long}, 1000).text
    assert len(cut) == 1000 and "[p2_tbl5" in cut
    assert reading.around_of(table(), passages, 4000) is None    # no section
    assert reading.around_of(SECTION, passages, 4000) is None    # a section
    assert reading.around_of(placed(), {}, 4000) is None         # not shown


def test_the_text_around_a_table_keeps_the_other_tables_of_its_section():
    text = ("Vorher [p2_tbl1: Tabelle 2] Danach kommt die Tabelle. "
            "[p2_tbl5: Tabelle 3] Sie zeigt 2022. [p4_img2] Weiter 999 t CO2.")
    whole = replace(SECTION, text=text)
    assert reading.around_of(placed(), {("section", 9): whole},
                             4000).text == text
    # the failure by construction: past the survey's two pages it is cut
    assert len(reading.around_of(placed(), {("section", 9): whole},
                                 40).text) == 40


GAS = {"value": 1200, "quote": "| Erdgas | 1.200 | 800 | 2.000 |"}
FROM_AROUND = {"year": [{"year": {
    "value": 2022, "quote": "die Emissionen im Jahr 2022"}}]}


def test_a_year_printed_in_the_text_around_a_table_is_read_from_there():
    passages = {("table", 5): placed(), ("section", 9): SECTION}
    read, calls = read_of(placed(), values=(GAS, {"value": None}),
                          groups=FROM_AROUND, passages=passages)
    assert all("Die folgende Tabelle" in payload["around"]
               for _task, payload in firsts(calls))
    claim = read.claims[0]
    assert claim["year"] == 2022 and claim["year_state"] == "read"
    assert claim["year_source"] == ["section", 9]
    alone, _ = read_of(placed(), values=(GAS, {"value": None}),
                       groups=FROM_AROUND)
    assert alone.claims[0]["year_state"] == "unbacked"


# -- the heading a passage stands under ------------------------------------------

HEADED = Source("section", 12, "Es fallen dann noch 80 t CO2 an.",
                {"document_id": 7, "section_title": "Zielszenario 2045"})
V80 = {"value": 80, "quote": "noch 80 t CO2"}
FROM_HEADING = {"year": [{"year": {
    "value": 2045, "quote": "Zielszenario 2045"}}]}


def shown_heading(source):
    return [(s.owner_kind, s.owner_id, s.text)
            for s in reading.heading_of(source)]


def test_a_passage_is_shown_with_its_heading_where_its_text_lacks_it():
    assert shown_heading(HEADED) == [("section", 12, "Zielszenario 2045")]
    assert shown_heading(placed()) == [("section", 9, "Bilanz")]
    assert shown_heading(BARE) == []           # its text carries "Bilanz"
    assert shown_heading(table()) == []        # no section holds the table
    assert shown_heading(replace(HEADED, provenance={"document_id": 7})) == []


def test_a_year_printed_only_in_a_section_s_own_heading_is_read_from_it():
    read, _ = read_of(HEADED, values=(V80, {"value": None}),
                      groups=FROM_HEADING, shown_with=reading.heading_of)
    claim = read.claims[0]
    assert claim["year"] == 2045 and claim["year_state"] == "read"
    assert claim["year_quote"] == "Zielszenario 2045"
    assert claim["year_source"] == ["section", 12]
    # The section's own title stands among the titles every request about
    # a value shows (`reading.sections_of`, owner decision 2026-11-07), so
    # it is read from there without the heading as well.
    alone, _ = read_of(HEADED, values=(V80, {"value": None}),
                       groups=FROM_HEADING)
    assert alone.claims[0]["year_state"] == "read"
    # the failure by construction: a year no shown text prints is not read
    nowhere, _ = read_of(HEADED, values=(V80, {"value": None}), groups={
        "year": [{"year": {"value": 2045, "quote": "Zieljahr ist 2045"}}]})
    assert nowhere.claims[0]["year_state"] == "unbacked"


# -- a quote from a passage never shown --------------------------------------------

FIGURE = Source("figure", 30, "Abbildung 4\nBalken der Emissionen 2030",
                {"document_id": 7, "title": "Abbildung 4",
                 "parent_section": 6, "block_id": "p3_img1"})
AFTER = Source("section", 8, "Ausblick\nDie Werte gelten für das Jahr 2030.",
               {"document_id": 7, "section_title": "Ausblick"})
PLAN = {("section", 6): BARE, ("figure", 30): FIGURE, ("section", 8): AFTER}
BARE_300 = {"value": 300, "quote": "rund 300 t CO2"}
YEAR_AFTER = {"value": 2030, "quote": "gelten für das Jahr 2030"}


def test_a_quote_from_a_section_not_shown_is_not_read_in_the_reading():
    # The reading shows the passage alone (its section and heading, the
    # table before it): a year quoted from the section after it stands in
    # nothing shown and is refused, though the plan holds that section. It
    # is left open for the combing, whose second reading shows the sections
    # around (owner decisions 2026-11-06 and 2026-11-07).
    read, calls = read_of(BARE, values=(BARE_300, {"value": None}),
                          groups={"year": [{"year": YEAR_AFTER}]},
                          passages=PLAN)
    assert read.claims[0]["year_state"] == "unbacked"
    assert not any(key in payload for _task, payload in calls
                   for key in ("before", "after", "more", "hits",
                               "not_found"))
    assert AFTER.text not in json.dumps([p for _t, p in calls],
                                        default=str, ensure_ascii=False)
    # the failure by construction: the year quoted from the passage's own
    # text is read
    dated = Source("section", 6, "Bilanz\nEs fielen im Jahr 2022 rund 300 t "
                   "CO2 an.", {"document_id": 7, "section_title": "Bilanz"})
    own = {"value": 2022, "quote": "Es fielen im Jahr 2022 rund 300 t CO2"}
    read, _ = read_of(dated, values=(BARE_300, {"value": None}),
                      groups={"year": [{"year": own}]},
                      passages={("section", 6): dated, ("section", 8): AFTER})
    assert read.claims[0]["year_state"] == "read"


# -- a reading offers no tools ----------------------------------------------------

def test_a_reading_offers_no_tools_in_its_grammars_or_its_requests():
    for schema in (values_grammar(), values_grammar(drawn=True),
                   *(coordinate_grammar(name) for name in ASKED)):
        assert "more" not in properties_of(schema)
    assert rejected({"value": None, "more": [{"get": "next"}]},
                    values_grammar())
    _read, calls = read_of(TEXT, values=ONE)
    assert calls and not any(key in payload for _task, payload in calls
                             for key in ("more", "hits", "not_found",
                                         "passage"))
    # the failure by construction: the combing's grammar still asks for more
    assert valid([{"get": "next"}], reading.more_schema())


def shown_definitions(parameter):
    """{task: the definition its first request showed of *parameter*}."""
    reader, calls = asking(({"value": 300,
                                      "quote": "Es fielen 300 t an"},
                            {"value": None}))
    source = Source("section", 6, "Es fielen 300 t an.",
                    {"document_id": 7, "section_title": "Bilanz"})
    reader.read(7, parameter, source, [], {("section", 6): source})
    shown = {}
    for task, payload in calls:
        # A further group's message shows the parameter only where it
        # needs the full definition the conversation has not shown.
        if "parameter" in payload:
            shown.setdefault(task, payload["parameter"]["definition"])
    return shown


def test_the_rounds_and_most_groups_show_the_brief_and_one_group_all():
    assert EMISSION.brief and EMISSION.brief != EMISSION.description
    full = {group.name for group in SPEC.groups.values()
            if group.full_definition}
    assert full == {"context"}
    group_of = {name: group.name for group in SPEC.groups.values()
                for name in group.coordinates}
    shown = shown_definitions(EMISSION)
    assert shown["values"] == EMISSION.brief
    assert set(shown) > {"values"}
    for task, definition in shown.items():
        if task != "values":
            assert definition == (EMISSION.description
                                  if group_of[task] in full
                                  else EMISSION.brief), task
    assert any(group_of[task] in full for task in shown if task != "values")
    # the failure by construction: without a brief the definition shows
    plain = replace(EMISSION, brief=None)
    assert set(shown_definitions(plain).values()) == {EMISSION.description}


GROUPED = """Gemeinsam.
<!-- group: frame -->
Rahmen.
<!-- group: number -->
Zahl.
"""


def prompt_of(text):
    return Prompt(id="extraction/read_text", text=text, meta={}, sha256="",
                  path=Path("read_text.md"))


def test_each_group_is_sent_the_shared_part_and_its_own_section():
    # The shared part is the system prompt, each group's words go with the
    # message that asks it (owner decisions 2026-11-07).
    per = thread.cut(prompt_of(GROUPED), ["frame", "number"])
    assert per.system().text == "Gemeinsam.\n"
    assert (per.group("frame"), per.group("number")) == ("Rahmen.", "Zahl.")
    # A prompt without sections is every group's as it stands.
    plain = thread.cut(prompt_of("Alles."), ["frame", "number"])
    assert plain.system().text == "Alles.\n"
    assert plain.group("frame") == plain.group("number") == ""
    # the failures by construction: a group without its section, a section
    # without its group, a section twice
    for text, groups in ((GROUPED, ["frame", "number", "context"]),
                         (GROUPED, ["frame"]),
                         (GROUPED + "<!-- group: frame -->\nNoch einmal.\n",
                          ["frame", "number"])):
        try:
            thread.cut(prompt_of(text), groups)
        except LookupError:
            continue
        raise AssertionError(f"no error for {groups}")


# -- the combing's tools -------------------------------------------------------------

def tools():
    """The tools of a comb task on BARE, as the combing sets them up."""
    return reading.Gathered(seen={("section", 6)},
                            cursor={"next": ("section", 6),
                                    "previous": ("section", 6)})


ORDER = list(PLAN.values())


def test_the_next_section_asked_for_is_shown_once_and_then_the_end():
    gathered = tools()
    assert gathered.fetch([{"get": "next"}], ORDER, PLAN, None)
    assert [m["text"] for m in gathered.context()["more"]] == [AFTER.text]
    # the failure by construction: past the last section there is none
    assert not gathered.fetch([{"get": "next"}], ORDER, PLAN, None)
    assert gathered.missed == [{"get": "next", "why": reading.END}]


def test_a_table_or_figure_named_by_its_placeholder_is_shown_and_none_else():
    gathered = tools()
    assert gathered.fetch([{"get": "item", "id": "[p3_img1: Abbildung 4]"},
                           {"get": "item", "id": "p9_img9"}], ORDER, PLAN,
                          None)
    assert [m["kind"] for m in gathered.context()["more"]] == ["figure"]
    assert gathered.missed == [{"get": "item", "id": "p9_img9",
                                "why": reading.UNKNOWN}]


def test_a_search_lists_its_hits_and_a_hit_asked_for_is_shown():
    gathered = tools()
    assert gathered.fetch([{"get": "search", "pattern": r"Jahr 20\d\d"}],
                          ORDER, PLAN, None)
    (listed,) = gathered.context()["hits"]
    assert listed["total"] == 1 and listed["hits"][0]["id"] == "H1"
    # Its hits, not its pattern (owner decision 2026-11-06).
    assert set(listed) == {"total", "hits"}
    assert gathered.hits[0]["pattern"] == r"Jahr 20\d\d"
    assert "more" not in gathered.context()
    assert gathered.fetch([{"get": "hit", "id": "H1"}], ORDER, PLAN, None)
    assert [m["text"] for m in gathered.context()["more"]] == [AFTER.text]
    # the failure by construction: a hit no list named is unknown
    assert not gathered.fetch([{"get": "hit", "id": "H9"}], ORDER, PLAN, None)
    assert gathered.missed[-1]["why"] == reading.UNKNOWN


def asks(*replies):
    """A request answered by *replies* in turn."""
    left = list(replies)
    return lambda: left.pop(0)


def test_gathering_ends_when_a_round_brings_nothing_new():
    same = {"more": [{"get": "item", "id": "p3_img1"}]}
    reply, n = reading.gather(asks(same, {}), same, tools(), ORDER, PLAN,
                              None)
    assert n == 1 and reply == same          # the figure again: nothing new
    unknown = {"more": [{"get": "item", "id": "p9_img9"}]}
    reply, n = reading.gather(asks({}), unknown, tools(), ORDER, PLAN, None)
    assert n == 0 and reply == unknown       # nothing found: no request
    # the failure by construction: something new asks once more
    reply, n = reading.gather(asks({"more": [{"get": "next"}]}, {"x": 1}),
                              same, tools(), ORDER, PLAN, None)
    assert n == 2 and reply == {"x": 1}


def test_a_request_that_no_longer_fits_leaves_the_reply_before_it():
    first = {"more": [{"get": "next"}], "x": 1}
    reply, n = reading.gather(asks(reading.CUT), first, tools(), ORDER, PLAN,
                              None)
    assert n == 1 and reply == first
    # the failure by construction: a reply that fits stands instead
    reply, n = reading.gather(asks({"x": 2}), first, tools(), ORDER, PLAN,
                              None)
    assert reply == {"x": 2}


def test_a_search_after_a_list_no_search_made_is_searched_once():
    gathered = reading.Gathered()
    gathered.list_hits([(("section", 6), "Bilanz", "Es fielen rund 300 t CO2")],
                       query="Emissionen")
    ask = [{"get": "search", "pattern": r"Jahr 20\d\d"}]
    assert gathered.fetch(ask, list(PLAN.values()), PLAN, None)
    assert not gathered.fetch(ask, list(PLAN.values()), PLAN, None)
    # No list shows what it was searched with, whoever searched.
    assert all(set(listed) <= {"total", "hits"}
               for listed in gathered.context()["hits"])


PROBE = "Die Emissionen gelten für das Bilanzjahr 2022."
NEAREST = [Source("section", 100 + i, f"S{i}\nText {i}", {})
           for i in range(20)]


def ranking(found):
    """A ranking of the plan that returns *found* without what it excludes,
    and the calls it got."""
    calls = []

    def rank(probes, exclude):
        calls.append((list(probes), set(exclude)))
        return [s for s in found if (s.owner_kind, s.owner_id) not in exclude]
    return rank, calls


def test_similar_lists_the_passages_nearest_to_its_sentence_best_of_each_kind():
    rank, calls = ranking(NEAREST)
    gathered = reading.Gathered(seen={("section", 6)}, rank=rank)
    ask = [{"get": "similar", "text": PROBE}]
    assert gathered.fetch(ask, list(PLAN.values()), PLAN, None)
    assert calls == [([PROBE], {("section", 6)})]
    (listed,) = gathered.context()["hits"]
    # Its hits, not its sentence, which the gathering keeps (owner decision
    # 2026-11-06).
    assert set(listed) == {"hits"}
    assert PROBE not in json.dumps(gathered.context(), ensure_ascii=False)
    assert gathered.hits[0]["similar"] == PROBE
    assert [hit["title"] for hit in listed["hits"]] \
        == [f"S{i}" for i in range(reading.SHOWN["section"])]
    # The same sentence again asks nothing and brings nothing new.
    assert not gathered.fetch(ask, list(PLAN.values()), PLAN, None)
    assert len(calls) == 1


def test_similar_without_a_ranking_finds_nothing_and_says_so():
    gathered = reading.Gathered()
    assert not gathered.fetch([{"get": "similar", "text": PROBE}],
                              list(PLAN.values()), PLAN, None)
    assert gathered.missed == [{"get": "similar", "text": PROBE,
                                "why": reading.UNKNOWN}]


def test_a_group_reply_keeps_the_sentence_of_what_it_found_unstated_apart():
    read, _ = read_of(BARE, values=(BARE_300, {"value": None}),
                      groups={"year": [{"year": {"value": UNSTATED,
                                                 "probe": PROBE}}]})
    assert read.probes == [{"year": PROBE}]
    assert not any("probe" in key for key in read.claims[0])
    assert read.claims[0]["year_state"] == "unstated"
    plain, _ = read_of(BARE, values=(BARE_300, {"value": None}))
    assert plain.probes == [{}]


def valid(instance, schema) -> bool:
    return jsonschema.validators.validator_for(schema)(schema).is_valid(
        instance)


def test_a_group_reply_may_write_a_sentence_and_a_tool_a_sentence_to_search():
    text = coordinate_grammar("year")
    assert valid({"year": {"value": UNSTATED, "probe": PROBE}}, text)
    assert not valid({"year": {"value": UNSTATED, "sentence": PROBE}}, text)
    more = reading.more_schema()
    assert valid([{"get": "similar", "text": PROBE}], more)
    assert not valid([{"get": "similar", "sentence": PROBE}], more)


# -- the table it continues, the ends of a range -----------------------------------
# Owner decisions 2026-11-06 and 2026-11-07: a table shows the title and head
# of the table right before it, which it may continue (a heading between them
# does not part them); the two ends of a range are linked. (The second
# reading and the table's frame asked once for all are the combing's, see
# test_combing.py.)

BEFORE = Source("section", 5, "Einleitung\nDie Werte gelten für das Jahr 2022.",
                {"document_id": 7, "section_title": "Einleitung"})
BARE_UNIT = {"value": "t CO2", "quote": "rund 300 t CO2"}


def test_the_two_ends_of_a_range_are_linked_on_both_rows():
    slots = reading.slots_of(SPEC, EMISSION)

    def end(label, value, which, quote="zwischen 60 und 100 t CO2", **more):
        return Row(label=label, item_index=0, claim={
            "value": value, "quote": quote, "qualifier": which,
            "qualifier_state": "read", **more})
    low, high = end("R1", 60, fields.RANGE_LOW), end("R2", 100,
                                                     fields.RANGE_HIGH)
    assert reading.link_ranges([low, high], slots) == 1
    assert low.claim[fields.RANGE] == high.claim[fields.RANGE] == [60, 100]
    # Another answer to a coordinate, or another quote, is another range.
    gas = end("R3", 60, fields.RANGE_LOW, carrier="Erdgas")
    oil = end("R4", 100, fields.RANGE_HIGH, carrier="Heizöl")
    elsewhere = end("R5", 100, fields.RANGE_HIGH, quote="bis 100 t CO2")
    assert reading.link_ranges([gas, oil, elsewhere], slots) == 0
    assert fields.RANGE not in gas.claim


START = Source("table", 1, "Tabelle 5: Liegenschaften\n| Name | Verbrauch |\n"
               "| --- | --- |\n| Schule | 900 |", {"document_id": 7, "page": 114})
REST = Source("table", 2, "| Kita | 61.400 |\n| Halle | 12 |",
              {"document_id": 7, "page": 115})


def test_a_table_shows_the_head_of_the_table_right_before_it():
    marked = lookup.continued([START, REST])
    assert marked[1].provenance["table_before"] == {
        "owner": ["table", 1],
        "text": "Tabelle 5: Liegenschaften\n| Name | Verbrauch |\n| --- | --- |"}
    # A part the layout cut within the page may continue it as well.
    same = replace(REST, provenance={"page": 114})
    assert lookup.continued([START, same])[1].provenance["table_before"] \
        == marked[1].provenance["table_before"]
    # A heading on its page between them does not part them; a page does.
    section = Source("section", 3, "Neuer Abschnitt", {"page": 115})
    assert lookup.continued([START, section, REST])[2].provenance[
        "table_before"] == marked[1].provenance["table_before"]
    assert "table_before" not in lookup.continued(
        [START, replace(REST, provenance={"page": 116})])[1].provenance
    # The reading shows it.
    kita = {"value": 61400, "quote": "| Kita | 61.400 |"}
    read, calls = read_of(marked[1], values=(kita, {"value": None}))
    assert all(p["table_before"] == marked[1].provenance["table_before"][
        "text"] for _task, p in firsts(calls))
    assert corrections_of(calls) == []


def test_a_correction_names_the_ways_that_pass_in_its_request():
    source = [Source("section", 1, "Wärmeverbrauch Erdgas 300 MWh im Jahr", {})]
    quote = "Wärmeverbrauch Erdgas 300 MWh"
    got = merge_field([Row("R1", 0, {})], source, SLOTS["carrier"],
                      {"answers": {"R1": {"value": "Heizöl", "quote": quote}}})
    assert got["failed"][0]["reason"] == say(
        "answer_not_in_quote", answer="Heizöl") + say("or_unstated",
                                                      unstated=UNSTATED)
    got = merge_field([Row("R1", 0, {})], source, SLOTS["subject"],
                      {"answers": {"R1": {"value": "Schule", "quote": quote}}},
                      not_in_quote="or_leave_out")
    assert got["failed"][0]["reason"] == say(
        "answer_not_in_quote_text", answer="Schule") + say("or_leave_out")
