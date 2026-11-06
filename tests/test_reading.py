"""A passage is read one value per request (owner decisions 2026-11-04 and
2026-11-05): rounds name its values one by one, each round shown the values
read, until the model names none; a value the check refuses is asked once
more with its reason, AND what the fold refuses of a value and its quote, an
answer off its closed list or one its quote does not hold, is asked once
more with the fold's own reason while a value the fold takes is not, AND one
named again is asked once more and, named again, ends the rounds. A value
may stand in any passage a round showed, the passage or the text around it,
AND it is read from the one its quote stands in, which joins the batch the
fold checks it in; a quote in no passage shown is refused.

A number in a table takes its column from the head the model wrote, so two
equal numbers of one row are two values, AND a head no head line prints is
asked once more and then dropped; a head that prints one year of the
document's pairs is the number's year, read off the head line, AND where
exactly one pair has that year, its scenario too.

Then each group of the spec is asked for each value, its coordinates still
open only, AND a group with none open is not asked; the request shows what
every request of the parameter shares first and the value last (ticket 26),
the pairs and the plan's years only where it asks a frame coordinate. What
the check refuses of a group's reply is asked once more
by its coordinate, and never a third time; a coordinate left out is asked
for by name and ends unanswered; a reply the check takes whole is asked
once. A frame coordinate left open takes the survey's one tuple, but not
against a year the value read under its own head.

A table too long for the model's window is read in halves of its rows, AND
a single row that does not fit, or a piece no round answered, is a hole of
its own while the others are read. A table or figure is shown with its
whole section, other tables and figures of it included, AND with the part
around its placeholder where the section is longer than the survey's two
pages (owner decision 2026-11-05); a coordinate quoted from there cites the
section. A passage is
shown with the heading it stands under, a table's or figure's that of its
section, a section's its own, AND a quote may stand in that heading where the
passage's text does not carry it.

A reading offers no tools (owner decision 2026-11-05, ticket 26): its
requests carry no hit list and its grammars no ask for more. The rounds and
every group but the one that classifies show the parameter's brief, that one
its full definition, AND a parameter without a brief shows its definition
everywhere. Each group is sent the prompt's shared part with its own
section, AND a prompt with a section missing, left over or twice fails, while
a prompt without sections is every group's.

A group reply writes to a coordinate it finds unstated a sentence as the plan
would print it, AND that sentence is kept beside its value for the combing,
never on the claim. The combing's tools show the next section, a table or
figure by its placeholder and a hit by its id, each once; "similar" lists the
passages of the plan nearest to the model's own sentence, the best of each
kind, AND without a ranking it finds nothing and says so; the gathering ends
when a round brings nothing new, AND a request that no longer fits leaves the
reply before it.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from dataclasses import replace
from pathlib import Path

import jsonschema

from docpipe.extraction import fields, reading
from docpipe.extraction.pipeline import Row, Source, route_claims
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


def asking(values=({"next": None},), groups=None, spec=SPEC, frame=FRAME,
           **kw):
    """A Reader whose values requests are answered by *values* in turn and
    the requests of each group by *groups[name]* in turn, any other group
    with every coordinate not printed; and each request as (task, payload),
    the payload built as the run builds it."""
    calls = []

    def ask_values(source, parameter, context, read, corrections=None):
        calls.append(("values", reading.values_payload(
            source, parameter, context, read, corrections)))
        return nth(values, calls, "values")

    def ask_text(source, parameter, group, slots, row, context,
                 corrections=None):
        calls.append((group.name, reading.text_payload(
            source, parameter, slots, row, group.where, context,
            corrections, full=group.full_definition)))
        given = (groups or {}).get(group.name)
        if given is None:
            return {slot.name: {"value": UNSTATED} for slot in slots}
        return nth(given, calls, group.name)

    return reading.Reader(spec, ask_values, ask_text, frame, **kw), calls


def read_of(source, *, values=({"next": None},), groups=None, pairs=(),
            tuples=(), passages=None, **kw):
    reader, calls = asking(values, groups, **kw)
    passages = passages or {(source.owner_kind, source.owner_id): source}
    read = reader.read(7, EMISSION, source, list(tuples), list(pairs),
                       passages)
    return read, calls


def rounds(calls) -> list:
    return [payload for task, payload in calls if task == "values"]


def corrections_of(calls) -> list:
    return [(task, payload["corrections"]) for task, payload in calls
            if payload.get("corrections")]


def test_a_table_gives_its_rows_cell_by_cell_and_text_gives_none():
    grid = reading.grid_of(TABLE)
    assert grid.columns == 4 and len(grid.body) == 2
    assert grid.body[1][1] == ["Heizöl", "27", "28", "27"]
    assert reading.grid_of("Ein Satz ohne Tabelle.") is None


# -- the values of a passage, one per round ---------------------------------------

def test_each_round_names_the_next_value_and_the_rounds_end_on_none():
    read, calls = read_of(TEXT, values=({"next": V300}, {"next": V27},
                                        {"next": None}))
    assert [p["read"] for p in rounds(calls)] == [[], [V300], [V300, V27]]
    assert [c["value"] for c in read.claims] == [300, 27]
    none, calls = read_of(TEXT)
    assert none.claims == [] and not none.unread and len(rounds(calls)) == 1


def test_a_value_the_check_refuses_is_asked_once_more_with_its_reason():
    for wrong, why in (
            (dict(V300, quote="rund 300 t CO2 im Jahr"),       # in no passage
             say("quote_not_in_source")),
            (dict(V300, value=300000), say("value_outside_quote", values=json
                                           .dumps([{"value": 300000,
                                                    "quote": V300["quote"]}],
                                                  ensure_ascii=False)))):
        read, calls = read_of(TEXT, values=({"next": wrong}, {"next": V300},
                                            {"next": None}))
        assert corrections_of(calls) == [("values", [dict(wrong, what=why)])]
        assert [(c["value"], c["quote"]) for c in read.claims] \
            == [(300, V300["quote"])]
        assert read.corrected == 1 and read.failed == {reading.VALUE: 1}
    _read, calls = read_of(TEXT, values=({"next": V300}, {"next": None}))
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
    reader, calls = asking(values, spec=SCENARIOS, frame=[])
    read = reader.read(7, SECTOR, COVERS, [], [],
                       {(COVERS.owner_kind, COVERS.owner_id): COVERS})
    return read, calls


def test_what_the_fold_refuses_of_a_value_is_asked_with_the_fold_s_reason():
    right = {"value": "industry sector", "value_raw": "industry",
             "quote": NAMED}
    for wrong in ({"value": "bioenergy", "quote": NAMED},       # off its list
                  {"value": "industry sector", "quote": NAMED}):  # not quoted
        read, calls = sector_read({"next": wrong}, {"next": right},
                                  {"next": None})
        why = verify_tuple(wrong, SECTOR, COVERS.text).reason
        assert corrections_of(calls) == [("values", [dict(
            wrong, what=say("value_rejected", reason=why))])]
        assert [(c["value"], c.get("value_raw"))
                for c in read.claims] == [("industry sector", "industry")]
        assert read.corrected == 1 and read.failed == {reading.VALUE: 1}
    # the failure by construction: a value the fold takes is not asked again
    read, calls = sector_read({"next": right}, {"next": None})
    assert corrections_of(calls) == [] and len(read.claims) == 1


def test_a_value_named_again_is_asked_once_more_and_then_ends_the_rounds():
    read, calls = read_of(TEXT, values=({"next": V300}, {"next": V300},
                                        {"next": V27}, {"next": None}))
    assert corrections_of(calls) == [("values", [dict(V300, what=say(
        "value_already_read", value="300", quote=V300["quote"]))])]
    assert [c["value"] for c in read.claims] == [300, 27]
    stuck, calls = read_of(TEXT, values=({"next": V300},))
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
    read, calls = read_of(placed(), values=({"next": dict(AROUND,
                                                         head="gesamt")},
                                           {"next": None}),
                          passages=passages)
    claim = read.claims[0]
    assert corrections_of(calls) == [] and claim["value"] == 2027
    assert [(i.source.owner_kind, i.source.owner_id)
            for i in read.batch.items] == [("table", 5), ("section", 9)]
    routed, orphans = route_claims(read.batch, read.claims)
    assert [len(r) for r in routed] == [0, 1] and orphans == []
    assert "head" not in claim             # a section has no column
    # Not shown, the section holds no value of this reading.
    alone, calls = read_of(placed(), values=({"next": AROUND}, {"next": None}))
    assert corrections_of(calls)[0][1][0]["what"] == say("quote_not_in_source")
    assert len(alone.batch.items) == 1


BARE = Source("section", 6, "Bilanz\nEs fielen rund 300 t CO2 an.",
              {"document_id": 7, "section_title": "Bilanz"})


# -- a number in a table ---------------------------------------------------------

def test_two_equal_numbers_of_a_row_are_two_values_by_their_heads():
    read, calls = read_of(table(), values=(
        {"next": {"value": 27, "quote": OIL, "head": "Haushalte"}},
        {"next": {"value": 27, "quote": OIL, "head": "gesamt"}},
        {"next": None}))
    assert corrections_of(calls) == []
    assert [c["head"] for c in read.claims] == ["Haushalte", "gesamt"]
    # Named without its head, the second is the first named again.
    same, calls = read_of(table(), values=(
        {"next": {"value": 27, "quote": OIL}},
        {"next": {"value": 27, "quote": OIL}}, {"next": None}))
    assert corrections_of(calls) == [("values", [{
        "value": 27, "quote": OIL,
        "what": say("value_already_read", value="27", quote=OIL)}])]
    assert [c["value"] for c in same.claims] == [27]
    assert "head" not in same.claims[0]   # two cells print it: no column


def test_a_head_no_head_line_prints_is_asked_once_more_and_then_dropped():
    wrong = {"value": 800, "quote": "| Erdgas | 1.200 | 800 | 2.000 |",
             "head": "Wohnen"}
    read, calls = read_of(table(), values=({"next": wrong}, {"next": wrong},
                                           {"next": None}))
    assert corrections_of(calls) == [("values", [dict(wrong, what=say(
        "head_not_in_table", head="Wohnen"))])]
    # The number's own cell still names its column.
    assert read.claims[0]["head"] == "GHD"
    right, calls = read_of(table(), values=({"next": dict(wrong, head="GHD")},
                                            {"next": None}))
    assert corrections_of(calls) == [] and right.claims[0]["head"] == "GHD"


YEARS = ("Tabelle 4: Emissionen nach Szenario in t CO2\n"
         "| Träger | Bestand 2022 | Ziel 2045 |\n"
         "| --- | --- | --- |\n"
         "| Erdgas | 1.200 | 300 |")
YEARS_HEAD = "| Träger | Bestand 2022 | Ziel 2045 |"
PAIRS = [{"scenario": "Bestand", "scenario_quote": YEARS_HEAD,
          "scenario_source": ["table", 4], "year": 2022,
          "year_quote": YEARS_HEAD, "year_source": ["table", 4]},
         {"scenario": "Zielszenario", "scenario_raw": "Ziel",
          "scenario_quote": YEARS_HEAD, "scenario_source": ["table", 4],
          "year": 2045, "year_quote": YEARS_HEAD, "year_source": ["table", 4]}]
UNDER_2022 = {"value": 1200, "quote": "| Erdgas | 1.200 | 300 |",
              "head": "Bestand 2022"}


def years():
    return table(YEARS, owner=4)


def test_a_head_with_a_year_of_the_pairs_dates_the_number_and_its_pair():
    read, calls = read_of(years(), values=({"next": UNDER_2022},
                                           {"next": None}), pairs=PAIRS)
    claim = read.claims[0]
    assert (claim["year"], claim["year_state"]) == (2022, "read")
    assert list(claim["year_window"]) == ["head", 2]
    assert (claim["scenario"], claim["scenario_state"]) == ("Bestand", "read")
    # Both frame coordinates read: the frame group is not asked.
    assert "frame" not in {task for task, _ in calls}
    # Two pairs of that year: the year is read, the scenario asked.
    twice, calls = read_of(years(), values=({"next": UNDER_2022},
                                            {"next": None}),
                           pairs=[PAIRS[0], dict(PAIRS[1], year=2022)])
    assert twice.claims[0]["year_state"] == "read"
    assert [set(p["coordinates"]) for task, p in calls if task == "frame"] \
        == [{"scenario"}]
    # A year no pair has dates nothing.
    none, calls = read_of(years(), values=({"next": UNDER_2022},
                                           {"next": None}), pairs=PAIRS[1:])
    assert none.claims[0].get("year_state") != "read"
    assert [set(p["coordinates"]) for task, p in calls if task == "frame"] \
        == [{"scenario", "year"}]


def test_a_coordinate_may_quote_what_its_value_has_read():
    # The scenario its pair gave it, shown under "read" in a wording the
    # table does not print: quoted, the coordinate cites where the scenario
    # was read (owner decision 2026-11-05: whatever a request shows of a
    # plan may be quoted).
    def known(claim, asked):
        return ({"scenario": "Szenario Bestand 2022"}
                if claim.get("scenario_state") == "read" else {})
    subject = {"number": [{"unit": {"value": UNSTATED}, "subject": {
        "value": "Szenario Bestand", "quote": "Szenario Bestand 2022"}}]}
    read, calls = read_of(years(), values=({"next": UNDER_2022},
                                           {"next": None}),
                          groups=subject, pairs=PAIRS, known=known)
    assert [p["value"]["read"] for task, p in calls if task == "number"] \
        == [{"scenario": "Szenario Bestand 2022"}]
    claim = read.claims[0]
    assert claim["subject_state"] == "read"
    assert claim["subject_source"] == ["table", 4]
    # Not shown, the same quote stands nowhere.
    alone, _ = read_of(years(), values=({"next": UNDER_2022}, {"next": None}),
                       groups=subject, pairs=PAIRS)
    assert alone.claims[0]["subject_state"] == "unbacked"


# -- one request per value and group -------------------------------------------

# The order of a group's request (ticket 26): the parameter's, the plan's,
# the passage's, the value's.
TEXT_KEYS = ("parameter", "coordinates", "where", "base_years",
             "target_years", "source", "around", "known", "value",
             "corrections")


def test_each_group_is_asked_alone_and_only_a_frame_group_sees_the_pairs():
    read, calls = read_of(TEXT, values=({"next": V300}, {"next": V27},
                                        {"next": None}),
                          tuples=[PAIRS[0]], pairs=PAIRS)
    asked = [(task, payload) for task, payload in calls if task != "values"]
    assert [task for task, _ in asked] == [g.name for g, _ in GROUPS] * 2
    assert [p["value"]["value"] for _, p in asked] \
        == [300] * len(GROUPS) + [27] * len(GROUPS)
    for task, payload in asked:
        assert ("known" in payload) == (task in FRAMED), task
        # What every request of the parameter shares first, the value last.
        assert list(payload) == [key for key in TEXT_KEYS if key in payload]
        assert list(payload)[0] == "parameter"
        assert list(payload)[-1] == "value"
    assert read.asked == 3 + 2 * len(GROUPS)


WRONG_CARRIER = {"value": "Erdgas", "quote": "Erdgas steht hier nicht"}
RIGHT_CARRIER = {"value": "Erdgas", "quote": "300 t CO2 bei Erdgas"}


CONTEXT = next(slots for group, slots in GROUPS if group.name == "context")


def context(**given):
    """A reply of the context group: every coordinate not printed but for
    *given*."""
    return {**{slot.name: {"value": UNSTATED} for slot in CONTEXT}, **given}


ONE = ({"next": V300}, {"next": None})


def test_a_coordinate_the_check_refuses_is_asked_again_by_its_coordinate():
    read, calls = read_of(TEXT, values=ONE, groups={"context": [
        context(carrier=WRONG_CARRIER), context(carrier=RIGHT_CARRIER)]})
    assert corrections_of(calls) == [("context", [
        {"coordinate": "carrier", "what": say("quote_not_in_source")}])]
    claim = read.claims[0]
    assert claim["carrier"] == "Erdgas" and claim["carrier_state"] == "read"


def test_a_reply_wrong_twice_is_not_asked_a_third_time():
    read, calls = read_of(TEXT, values=ONE, groups={"context": [
        context(carrier=WRONG_CARRIER)]})
    assert [task for task, _ in calls].count("context") == 2
    assert read.claims[0]["carrier_state"] == "unbacked"


def test_a_reply_the_check_takes_whole_is_asked_once():
    read, calls = read_of(TEXT, values=ONE, groups={"context": [
        context(carrier=RIGHT_CARRIER)]})
    assert [task for task, _ in calls] == ["values", "values"] + [
        group.name for group, _ in GROUPS]
    assert read.asked == 2 + len(GROUPS)


def test_a_coordinate_read_the_first_time_stays_as_read():
    first = context(carrier=RIGHT_CARRIER)
    del first["sector"]
    read, calls = read_of(TEXT, values=ONE, groups={"context": [
        first, context(carrier={"value": UNSTATED})]})
    assert corrections_of(calls) == [("context", [
        {"coordinate": "sector", "what": say("key_missing", key="sector")}])]
    claim = read.claims[0]
    assert claim["carrier"] == "Erdgas" and claim["carrier_state"] == "read"
    assert claim["sector_state"] == "unstated"


def test_a_coordinate_left_out_is_asked_for_by_name_and_ends_unanswered():
    read, calls = read_of(TEXT, values=ONE, groups={"frame": [
        {"scenario": {"value": UNSTATED}}]})
    assert corrections_of(calls) == [("frame", [
        {"coordinate": "year", "what": say("key_missing", key="year")}])]
    assert read.claims[0]["year_state"] == "unanswered"
    assert read.unanswered == 1


# -- the survey's tuple of the passage ------------------------------------------

TUPLE = {"scenario": "Bestand", "scenario_raw": "im Jahr 2022",
         "scenario_quote": "im Jahr 2022", "scenario_source": ["table", 5],
         "year": 2022, "year_quote": "im Jahr 2022",
         "year_source": ["table", 5]}
TITLED = table("Tabelle 3: Emissionen im Jahr 2022\n" + TABLE.split("\n", 1)[1])


def erdgas():
    return [Row(label="R1", item_index=0, claim={
        "source": "Q1", "value": 1200,
        "quote": "| Erdgas | 1.200 | 800 | 2.000 |"})]


def test_an_open_frame_takes_the_surveys_one_tuple_with_its_quote():
    rows = erdgas()
    assert reading.inherit(rows, FRAME, [TUPLE], [TUPLE], [TITLED]) == 2
    assert rows[0].claim["year"] == 2022
    assert rows[0].claim["year_quote"] == "im Jahr 2022"
    assert list(rows[0].claim["year_window"])[0] == "frame"


def test_two_tuples_or_a_year_of_its_own_take_nothing_from_the_survey():
    rows = erdgas()
    assert reading.inherit(rows, FRAME, [TUPLE, dict(TUPLE, year=2040)],
                           [], [TITLED]) == 0
    rows[0].claim.update(year=2040, year_state="read")
    assert reading.inherit(rows, FRAME, [TUPLE], [TUPLE], [TITLED]) == 0
    assert rows[0].claim["year"] == 2040
    assert rows[0].claim.get("scenario_state") != "read"


# -- the grammars ---------------------------------------------------------------

def rejected(instance, schema) -> bool:
    try:
        jsonschema.validate(instance, schema)
    except jsonschema.ValidationError:
        return True
    return False


def values_grammar(head=False):
    return reading.values_response_format(EMISSION, head)["json_schema"][
        "schema"]


def group_grammar(name):
    slots = next(s for g, s in GROUPS if g.name == name)
    return reading.text_response_format(slots)["json_schema"]["schema"]


def test_a_round_names_one_value_or_none_and_a_head_only_where_asked():
    assert not rejected({"next": None}, values_grammar())
    assert not rejected({"next": V300}, values_grammar())
    assert rejected({"next": {"value": 300}}, values_grammar())     # no quote
    assert rejected({"next": [V300]}, values_grammar())
    with_head = dict(V300, head="gesamt")
    assert not rejected({"next": with_head}, values_grammar(head=True))
    assert rejected({"next": with_head}, values_grammar())
    assert reading.with_head_asked(EMISSION, table())
    assert not reading.with_head_asked(EMISSION, TEXT)
    assert not reading.with_head_asked(SPEC.by_uri["planning_organisation"],
                                       table())


def test_a_group_reply_answers_every_coordinate_of_its_group_and_no_other():
    whole = {name: {"value": UNSTATED} for name in ("year", "scenario")}
    assert not rejected(whole, group_grammar("frame"))
    assert rejected({"year": {"value": UNSTATED}}, group_grammar("frame"))
    assert rejected(dict(whole, unit={"value": UNSTATED}),
                    group_grammar("frame"))


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
    def answer(source, parameter, context, read, corrections=None):
        body = [cells for _line, cells in reading.grid_of(source.text).body]
        labels = [cells[0] for cells in body]
        if cut(labels):
            return reading.CUT
        if silent(labels):
            return None
        done = {r["value"] for r in read}
        for line, cells in reading.grid_of(source.text).body:
            value = int(cells[1].replace(".", ""))
            if value not in done:
                return {"next": {"value": value, "quote": line,
                                 "head": "2022"}}
        return {"next": None}
    return answer


def read_long(answer):
    shown = []

    def ask_values(source, parameter, context, read, corrections=None):
        assert len(shown) < ENDLESS, "the reading asks without end"
        shown.append([c[0] for _l, c in reading.grid_of(source.text).body])
        return answer(source, parameter, context, read, corrections)

    reader = reading.Reader(SPEC, ask_values, lambda *a, **k: {}, FRAME)
    long = table(LONG)
    return reader.read(7, EMISSION, long, [], [], {("table", 5): long}), shown


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


def test_only_a_group_asking_the_year_is_shown_the_base_and_target_years():
    assert reading.years_of(BASES, list(SLOTS.values())) \
        == {"base_years": [2022], "target_years": [2045]}
    assert reading.years_of(BASES, [SLOTS["carrier"]]) == {}
    _read, calls = read_of(TEXT, values=ONE, bases=lambda pairs: BASES)
    shown = {task: (p.get("base_years"), p.get("target_years"))
             for task, p in calls if task != "values"}
    assert shown == {group.name: (([2022], [2045]) if group.name in FRAMED
                                  else (None, None)) for group, _ in GROUPS}


STATE = Source("section", 6, "Im Bestand fielen rund 300 t CO2 an.",
               {"document_id": 7, "section_title": "Bilanz"})


def read_by_word(year):
    read, _ = read_of(STATE, values=({"next": {"value": 300, "quote":
                                               "rund 300 t CO2"}},
                                     {"next": None}),
                      groups={"frame": [{"scenario": {"value": UNSTATED},
                                         "year": {
                                             "value": year,
                                             "value_raw": "Bestand",
                                             "quote": "Im Bestand fielen "
                                                      "rund 300 t CO2"}}]},
                      bases=lambda pairs: BASES)
    return read.claims[0]


def test_a_value_named_by_the_plans_word_for_its_state_takes_that_year():
    claim = read_by_word(2022)
    assert claim["year"] == 2022 and claim["year_state"] == "read"
    assert claim["year_quote"] == "im Jahr 2022"
    assert claim["year_link_quote"] == "Im Bestand fielen rund 300 t CO2"


def test_a_year_named_by_the_word_but_not_of_the_plan_is_not_read():
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


GAS = {"value": 1200, "quote": "| Erdgas | 1.200 | 800 | 2.000 |",
       "head": "Haushalte"}
FROM_AROUND = {"frame": [{"scenario": {"value": UNSTATED}, "year": {
    "value": 2022, "quote": "die Emissionen im Jahr 2022"}}]}


def test_a_year_printed_in_the_text_around_a_table_is_read_from_there():
    passages = {("table", 5): placed(), ("section", 9): SECTION}
    read, calls = read_of(placed(), values=({"next": GAS}, {"next": None}),
                          groups=FROM_AROUND, passages=passages)
    assert all("Die folgende Tabelle" in payload["around"]
               for _task, payload in calls)
    claim = read.claims[0]
    assert claim["year"] == 2022 and claim["year_state"] == "read"
    assert claim["year_source"] == ["section", 9]
    alone, _ = read_of(placed(), values=({"next": GAS}, {"next": None}),
                       groups=FROM_AROUND)
    assert alone.claims[0]["year_state"] == "unbacked"


# -- the heading a passage stands under ------------------------------------------

HEADED = Source("section", 12, "Es fallen dann noch 80 t CO2 an.",
                {"document_id": 7, "section_title": "Zielszenario 2045"})
V80 = {"value": 80, "quote": "noch 80 t CO2"}
FROM_HEADING = {"frame": [{"scenario": {"value": UNSTATED}, "year": {
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
    read, _ = read_of(HEADED, values=({"next": V80}, {"next": None}),
                      groups=FROM_HEADING, shown_with=reading.heading_of)
    claim = read.claims[0]
    assert claim["year"] == 2045 and claim["year_state"] == "read"
    assert claim["year_quote"] == "Zielszenario 2045"
    assert claim["year_source"] == ["section", 12]
    alone, _ = read_of(HEADED, values=({"next": V80}, {"next": None}),
                       groups=FROM_HEADING)
    assert alone.claims[0]["year_state"] == "unbacked"


# -- a quote from a passage never shown --------------------------------------------

FIGURE = Source("figure", 30, "Abbildung 4\nBalken der Emissionen 2030",
                {"document_id": 7, "title": "Abbildung 4",
                 "parent_section": 6, "block_id": "p3_img1"})
AFTER = Source("section", 8, "Ausblick\nDie Werte gelten für das Jahr 2030.",
               {"document_id": 7, "section_title": "Ausblick"})
PLAN = {("section", 6): BARE, ("figure", 30): FIGURE, ("section", 8): AFTER}
BARE_300 = {"value": 300, "quote": "rund 300 t CO2"}
YEAR_AFTER = {"value": 2030, "quote": "gelten für das Jahr 2030"}


def frame(**given):
    return {"scenario": {"value": UNSTATED}, "year": {"value": UNSTATED},
            **given}


def test_a_quote_from_a_section_never_shown_is_not_read():
    # The section is in the plan, but no request showed it.
    read, calls = read_of(BARE, values=({"next": BARE_300}, {"next": None}),
                          groups={"frame": [frame(year=YEAR_AFTER)]},
                          passages=PLAN)
    assert read.claims[0]["year_state"] == "unbacked"
    assert not any(key in payload for _task, payload in calls
                   for key in ("more", "hits", "not_found"))


# -- a reading offers no tools ----------------------------------------------------

def test_a_reading_offers_no_tools_in_its_grammars_or_its_requests():
    for schema in (values_grammar(), values_grammar(head=True),
                   *(group_grammar(group.name) for group, _ in GROUPS)):
        assert "more" not in schema["properties"]
    assert rejected({"next": None, "more": [{"get": "next"}]},
                    values_grammar())
    _read, calls = read_of(TEXT, values=ONE, tuples=[PAIRS[0]], pairs=PAIRS)
    assert calls and not any(key in payload for _task, payload in calls
                             for key in ("more", "hits", "not_found",
                                         "passage"))
    # the failure by construction: the combing's grammar still asks for more
    assert valid([{"get": "next"}], reading.more_schema())


def shown_definitions(parameter):
    """{task: the definition its first request showed of *parameter*}."""
    reader, calls = asking(({"next": {"value": 300,
                                      "quote": "Es fielen 300 t an"}},
                            {"next": None}))
    source = Source("section", 6, "Es fielen 300 t an.",
                    {"document_id": 7, "section_title": "Bilanz"})
    reader.read(7, parameter, source, [], [], {("section", 6): source})
    shown = {}
    for task, payload in calls:
        shown.setdefault(task, payload["parameter"]["definition"])
    return shown


def test_the_rounds_and_most_groups_show_the_brief_and_one_group_all():
    assert EMISSION.brief and EMISSION.brief != EMISSION.description
    full = {group.name for group in SPEC.groups.values()
            if group.full_definition}
    assert full == {"context"}
    shown = shown_definitions(EMISSION)
    assert shown["values"] == EMISSION.brief
    assert set(shown) > {"values"}
    for task, definition in shown.items():
        if task != "values":
            assert definition == (EMISSION.description if task in full
                                  else EMISSION.brief), task
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
    per = reading.group_prompts(prompt_of(GROUPED), ["frame", "number"])
    assert per["frame"].text == "Gemeinsam.\n\nRahmen.\n"
    assert per["number"].text == "Gemeinsam.\n\nZahl.\n"
    # A prompt without sections is every group's as it stands.
    plain = reading.group_prompts(prompt_of("Alles."), ["frame", "number"])
    assert {name: one.text for name, one in plain.items()} \
        == {"frame": "Alles.", "number": "Alles."}
    # the failures by construction: a group without its section, a section
    # without its group, a section twice
    for text, groups in ((GROUPED, ["frame", "number", "context"]),
                         (GROUPED, ["frame"]),
                         (GROUPED + "<!-- group: frame -->\nNoch einmal.\n",
                          ["frame", "number"])):
        try:
            reading.group_prompts(prompt_of(text), groups)
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
    assert listed["similar"] == PROBE
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
    read, _ = read_of(BARE, values=({"next": BARE_300}, {"next": None}),
                      groups={"frame": [frame(year={"value": UNSTATED,
                                                    "probe": PROBE})]})
    assert read.probes == [{"year": PROBE}]
    assert not any("probe" in key for key in read.claims[0])
    assert read.claims[0]["year_state"] == "unstated"
    plain, _ = read_of(BARE, values=({"next": BARE_300}, {"next": None}),
                       groups={"frame": [frame()]})
    assert plain.probes == [{}]


def valid(instance, schema) -> bool:
    return jsonschema.validators.validator_for(schema)(schema).is_valid(
        instance)


def test_a_group_reply_may_write_a_sentence_and_a_tool_a_sentence_to_search():
    text = reading.text_response_format(FRAME)["json_schema"]["schema"]
    assert valid({"scenario": {"value": UNSTATED},
                  "year": {"value": UNSTATED, "probe": PROBE}}, text)
    assert not valid({"scenario": {"value": UNSTATED},
                      "year": {"value": UNSTATED, "sentence": PROBE}}, text)
    more = reading.more_schema()
    assert valid([{"get": "similar", "text": PROBE}], more)
    assert not valid([{"get": "similar", "sentence": PROBE}], more)
