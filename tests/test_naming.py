"""A scenario is read as the publication prints it, and which of a
publication's names mean the same scenario is asked once it is read (owner
decisions 2026-11-06).

The scenario of a value is asked as free text with no list, AND a name its
quote does not print is not read. A value stated for several scenarios is
one row per name, each checked on its own, AND a correction for one of them
names its name, AND the combing's rows join their value's reading; a pass
over a stored harvest takes the first name. Only a free-text coordinate or
value is merged, AND never one the survey reads.

Once the document is folded, one request shows every name read for a kind
under a number with its places, each quote with 500 characters before and
after it, AND a stretch of a passage once however many quotes stand in it.
Names of one thing mean the name it is called by, AND a name of several
things means each of theirs, AND an answer with no name shown means the name
itself. The reply answers every name in numbers only: under each number
shown, at least one of the numbers shown, AND nothing beside them, in the
form a server holds it to and in the form a hosted API does. An entry under
or with a number not shown, AND a name the reply left out, is asked once
more with its reason, AND the second reply counts only for the names asked
again, AND a name answered in neither means itself. Each row read gets the
names of what it means, AND a row that read no name gets none. One name asks nothing. A
request that does not fit is asked in two halves, AND what the halves found
once more together. The graph writes a row to each scenario its name means,
AND names of one scenario are one factsheet.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

import jsonschema
import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from docpipe.extraction import combing, fields, naming, reading
from docpipe.providers import schema as strict_schema
from docpipe.extraction.pipeline import READ, Batch, Source, WorkItem
from docpipe.extraction.spec import SpecError, load as load_spec
from docpipe.extraction.wording import say
from profiles.scenarios import kg
from test_graph_from_shapes import OEO, oekg

SPEC_FILE = (Path(__file__).resolve().parent.parent / "profiles"
             / "scenarios" / "extraction_spec.json")
SPEC = load_spec(json.loads(SPEC_FILE.read_text(encoding="utf-8")))
LABEL = SPEC.by_uri["scenario_label"]
YEAR = SPEC.by_uri["scenario_year"]

TEXT = Source("section", 6, "We analyse two pathways: the Current Policies "
              "scenario (CurPol) and the NDC scenario. Results for the "
              "CurPol scenario are reported for 2030.",
              {"document_id": 7, "section_title": "Scenarios"})
Y2030 = {"value": "2030", "quote": "Results for the CurPol scenario are "
                                   "reported for 2030"}
NAMED = {"scenario": {"value": "CurPol",
                      "quote": "Results for the CurPol scenario"}}
TWO = {"scenario": [{"value": "CurPol",
                     "quote": "Results for the CurPol scenario"},
                    {"value": "NDC", "quote": "the NDC scenario"}]}


def read_of(parameter, values, groups=None, spec=None):
    """A Reader over TEXT: *values* the replies of the rounds in turn,
    *groups* {group: a reply, or [replies in turn]}."""
    calls = []
    given = {name: (list(reply) if isinstance(reply, list) else [reply])
             for name, reply in (groups or {}).items()}

    def ask_values(source, parameter, context, read, corrections=None):
        calls.append(("values", reading.values_payload(
            source, parameter, context, read, corrections),
            reading.values_response_format(parameter)))
        return values[min(sum(1 for c in calls if c[0] == "values"),
                          len(values)) - 1]

    def ask_text(source, parameter, group, slots, row, context,
                 corrections=None):
        calls.append((group.name, reading.text_payload(
            source, parameter, slots, row, group.where, context,
            corrections), reading.text_response_format(slots)))
        replies = given.get(group.name)
        if not replies:
            return {slot.name: {"value": fields.UNSTATED} for slot in slots}
        return replies.pop(0) if len(replies) > 1 else replies[0]

    reader = reading.Reader(spec or SPEC, ask_values, ask_text, [])
    read = reader.read(7, parameter, TEXT, [], [],
                       {(TEXT.owner_kind, TEXT.owner_id): TEXT})
    return read, calls


def scenario_slot(spec):
    year = spec.by_uri["scenario_year"]
    return next(s for s in fields.axis_slots(year) if s.name == "scenario")


def unmerged_spec():
    """The spec with the scenario of scenario_year not merged."""
    raw = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    year = next(p for p in raw["parameters"] if p["uri"] == "scenario_year")
    year["axes"]["scenario"].pop("merged")
    return load_spec(raw)


# -- the reading ---------------------------------------------------------------

def test_a_scenario_is_read_as_printed_and_a_name_its_quote_lacks_is_not():
    read, calls = read_of(YEAR, (Y2030, {"value": None}),
                          groups={"scenario": NAMED})
    (_task, payload, shape), = [c for c in calls if c[0] == "scenario"]
    assert payload["coordinates"]["scenario"].get("options") is None
    assert payload["coordinates"]["scenario"]["kind"] == fields.TEXT
    claim = read.claims[0]
    assert (claim["scenario_state"], claim["scenario"]) == (READ, "CurPol")
    assert claim["scenario_quote"] == NAMED["scenario"]["quote"]
    elsewhere = {"scenario": {"value": "CurPol",
                              "quote": "We analyse two pathways"}}
    alone, _ = read_of(YEAR, (Y2030, {"value": None}),
                       groups={"scenario": elsewhere})
    assert alone.claims[0]["scenario_state"] == fields.UNBACKED


def test_a_list_splits_only_where_the_coordinate_is_merged():
    slot = scenario_slot(SPEC)
    a, b = TWO["scenario"]
    assert reading.answers_each(TWO, [slot]) == [{"scenario": a},
                                                 {"scenario": b}]
    assert reading.answers_each({"scenario": a}, [slot]) == [{"scenario": a}]
    assert reading.answers_each({"scenario": []}, [slot]) \
        == [{"scenario": None}]
    plain = scenario_slot(unmerged_spec())
    assert reading.answers_each(TWO, [plain]) == [TWO]
    assert "anyOf" in reading.answer_schema(slot)
    assert reading.answer_schema(plain)["type"] == "object"


def test_a_value_stated_for_several_scenarios_is_one_row_each():
    read, _ = read_of(YEAR, (Y2030, {"value": None}),
                      groups={"scenario": TWO})
    assert [(c["value"], c["scenario"], c["scenario_state"])
            for c in read.claims] == [("2030", "CurPol", READ),
                                      ("2030", "NDC", READ)]
    assert read.claims[1]["scenario_quote"] == "the NDC scenario"
    assert len(read.probes) == len(read.claims)
    # A list for a coordinate that is not merged is not split: it is no
    # answer, and the value stays one row.
    plain = unmerged_spec()
    alone, _ = read_of(plain.by_uri["scenario_year"],
                       (Y2030, {"value": None}),
                       groups={"scenario": TWO}, spec=plain)
    assert len(alone.claims) == 1
    assert alone.claims[0]["scenario_state"] != READ


def test_a_correction_for_one_of_several_scenarios_names_its_name():
    stray = {"scenario": [TWO["scenario"][0],
                          {"value": "NDC",
                           "quote": "the NDC pathway of another study"}]}
    fixed = {"scenario": {"value": "NDC", "quote": "the NDC scenario"}}
    read, calls = read_of(YEAR, (Y2030, {"value": None}),
                          groups={"scenario": [stray, fixed]})
    (_task, corrected, _shape), = [c for c in calls if c[0] == "scenario"
                                   and c[1].get("corrections")]
    named = corrected["corrections"][0]
    assert (named["coordinate"], named["value"], named["quote"]) \
        == ("scenario", "NDC", "the NDC pathway of another study")
    assert [(c["scenario"], c["scenario_state"]) for c in read.claims] \
        == [("CurPol", READ), ("NDC", READ)]


def test_the_combing_makes_one_row_per_scenario_for_the_reading():
    claim = {"source": "Q1", "value": "2030", "quote": Y2030["quote"],
             "scenario_state": fields.SAID_UNSTATED}
    batch = Batch(7, YEAR, [WorkItem(7, YEAR, TEXT)], spec=SPEC)
    read = reading.Read(batch, [claim], probes=[{"scenario": "a sentence"}])
    reply = TWO
    passages = {(TEXT.owner_kind, TEXT.owner_id): TEXT}
    combing.Comber(SPEC, lambda *a, **k: reply, lambda *a: [],
                   lambda claim, names: {})(7, [read], passages, [])
    assert [(c["scenario"], c["scenario_state"]) for c in read.claims] \
        == [("CurPol", READ), ("NDC", READ)]
    assert read.probes == [{"scenario": "a sentence"}] * 2
    # A pass over a stored harvest re-reads its row in place: the first.
    stored = {"source": "Q1", "value": "2030", "quote": Y2030["quote"],
              "scenario_state": fields.SAID_UNSTATED}
    claims = [stored]
    combed = combing.Comber(SPEC, lambda *a, **k: reply, None,
                            lambda claim, names: {}).comb_groups(
        7, YEAR, TEXT, reading.slots_of(SPEC, YEAR), claims, passages, [],
        coordinates=["scenario"])
    assert claims == [stored] and not combed[0].made
    assert (stored["scenario"], stored["scenario_state"]) == ("CurPol", READ)


def test_only_a_free_text_coordinate_or_value_is_merged():
    raw = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    spec = load_spec(raw)
    assert naming.merged_slots(spec)["scenario_label"] == {
        naming.VALUE: "scenario"}
    assert naming.merged_slots(spec)["scenario_year"] == {
        "scenario": "scenario"}
    sector = next(p for p in raw["parameters"] if p["uri"] == "study_sector")
    sector["merged"] = "sector"
    with pytest.raises(SpecError):
        load_spec(raw)
    raw = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    region = next(p for p in raw["parameters"]
                  if p["uri"] == "scenario_region")
    region["axes"]["scenario"]["merged"] = ""
    with pytest.raises(SpecError):
        load_spec(raw)


def test_a_merged_coordinate_is_not_read_in_the_survey():
    raw = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    raw["groups"]["scenario"]["read_in"] = "survey"
    with pytest.raises(SpecError):
        load_spec(raw)


# -- which names mean the same scenario ----------------------------------------

LCEO, ZERO = "LCEO Zero Carbon", "the Zero Carbon scenario"
TECH, LIFE, BOTH = "EC LTS 1.5Tech", "EC LTS 1.5Life", "the EC LTS scenarios"


def test_names_of_one_scenario_mean_the_name_it_is_called_by():
    order = [LCEO, ZERO, TECH, LIFE, BOTH]
    meant = naming.meanings(order, {
        LCEO: [LCEO], ZERO: [LCEO], TECH: [TECH], LIFE: [LIFE],
        BOTH: [TECH, LIFE]})
    assert meant == {LCEO: [LCEO], ZERO: [LCEO], TECH: [TECH],
                     LIFE: [LIFE], BOTH: [TECH, LIFE]}
    # A chain ends at the name that answered itself, a name pointing at a
    # name of several means each of theirs, and an answer with no name of
    # the order means the name itself.
    meant = naming.meanings(["a", "b", "c", "d", "e"], {
        "a": ["a"], "b": ["c"], "c": ["a"], "d": ["e"],
        "e": ["a", "missing"]})
    assert meant["b"] == ["a"] and meant["c"] == ["a"]
    assert meant["e"] == ["a"] and meant["d"] == ["a"]
    assert naming.meanings(["a"], {"a": ["missing"]}) == {"a": ["a"]}
    # Two names pointing at each other are one thing, called by the first.
    assert naming.meanings(["x", "y"], {"x": ["y"], "y": ["x"]}) \
        == {"x": ["x"], "y": ["x"]}
    # Several names of one thing are that one thing.
    assert naming.meanings(["p", "q", "r"], {
        "p": ["p"], "q": ["p"], "r": ["p", "q"]})["r"] == ["p"]


def test_the_places_show_each_quote_with_500_characters_around_it():
    text = ("x" * 1000 + " QUOTE ONE " + "y" * 300 + " QUOTE TWO "
            + "z" * 2000 + " QUOTE THREE " + "w" * 600)
    owner = ("section", 1)
    source = Source("section", 1, text, {"section_title": "Results"})
    shown, at = naming.places_of(
        {"a": [(owner, "QUOTE ONE")], "b": [(owner, "QUOTE TWO")],
         "c": [(owner, "QUOTE THREE")], "d": [(owner, "Results")],
         "e": [(owner, "nowhere at all")]}, {owner: source})
    one, two = text.index("QUOTE ONE"), text.index("QUOTE TWO")
    assert at["a"] == at["b"] == ["P1"]
    assert shown["P1"] == text[one - 500:two + len("QUOTE TWO") + 500]
    three = text.index("QUOTE THREE")
    assert shown[at["c"][0]] == text[three - 500:
                                     three + len("QUOTE THREE") + 500]
    assert shown[at["d"][0]] == "Results"
    assert shown[at["e"][0]] == "nowhere at all"
    assert len(shown) == 4


def rows_of(*names, unread=()):
    """A label row per name, and a year row per name that read it, each
    with a quote the passage prints."""
    rows = []
    for index, name in enumerate(names):
        rows.append({"parameter": "scenario_label", "value": name,
                     "quote": f"We call it {name} here",
                     "provenance": {"owner_kind": "section",
                                    "owner_id": index}})
        rows.append({"parameter": "scenario_year", "value": "2050",
                     "scenario": name, "scenario_state": READ,
                     "scenario_quote": f"We call it {name} here",
                     "scenario_source": ["section", index]})
    # A row that read no name: its scenario was not taken, whatever stands
    # beside it.
    rows += [{"parameter": "scenario_year", "value": "2030",
              "scenario": "Ghost", "scenario_state": state} for state in unread]
    return rows


def passages_of(names):
    return {("section", index): Source("section", index,
                                       f"Text. We call it {name} here. More.",
                                       {"section_title": "S"})
            for index, name in enumerate(names)}


def by_number(answers):
    """A reply as the model gives it: *answers* ({name: [names]}) under the
    numbers the request showed the names under; a name it did not show
    stays as it is."""
    def reply(payload):
        number = {entry["name"]: key for key, entry in payload["names"].items()}
        return {number.get(name, name): [number.get(one, one) for one in given]
                for name, given in answers.items()}
    return reply


def every(answers):
    """A reply that answers every name the request showed, under its number:
    with *answers* ({name: [names]}) where given, with its own number
    otherwise."""
    def reply(payload):
        out = {key: [key] for key in payload["names"]}
        out.update(by_number(answers)(payload))
        return out
    return reply


def names_shown(payload) -> dict:
    """{number: name} of a request."""
    return {key: entry["name"] for key, entry in payload["names"].items()}


def namer(replies, fits=None):
    """A Namer whose requests answer *replies* in turn, and what it was
    asked; with *fits*, a request of more names than that does not fit."""
    asked = []

    def ask(payload, shape, document_id, kind):
        asked.append(payload)
        if fits is not None and len(payload["names"]) > fits:
            return naming.CUT
        reply = replies.pop(0)
        return reply(payload) if callable(reply) else reply
    return naming.Namer(SPEC, ask), asked


def test_each_row_read_is_marked_with_what_its_name_means():
    names = [LCEO, ZERO]
    rows = rows_of(*names, unread=[fields.UNBACKED])
    # Every name is answered (owner decision 2026-11-06): the one that
    # means itself with its own number.
    made, asked = namer([by_number({LCEO: [LCEO], ZERO: [LCEO]})])
    meant = made(7, rows, passages_of(names))
    assert meant == {"scenario": {LCEO: [LCEO], ZERO: [LCEO]}}
    (payload,), = [asked]
    assert payload["kind"] == "scenario"
    assert names_shown(payload) == {"N1": LCEO, "N2": ZERO}
    assert all(f"We call it {name} here" in " ".join(payload["places"].values())
               for name in names)
    assert [row.get("value_means") for row in rows
            if row["parameter"] == "scenario_label"] == [[LCEO], [LCEO]]
    assert [row.get("scenario_means") for row in rows
            if row["parameter"] == "scenario_year"] == [[LCEO], [LCEO], None]


def test_one_name_asks_nothing():
    rows = rows_of(LCEO)
    made, asked = namer([])
    assert made(7, rows, passages_of([LCEO])) == {"scenario": {LCEO: [LCEO]}}
    assert asked == [] and rows[0]["value_means"] == [LCEO]


def test_the_reply_answers_every_name_in_numbers_shown():
    schema = naming.response_format(["N1", "N2"])["json_schema"]["schema"]
    strict, decode = strict_schema.strict(schema)
    whole = {"N1": ["N1"], "N2": ["N1", "N2"]}
    for form in (schema, strict):
        jsonschema.validate(whole, form)
    assert decode(whole) == whole
    # Every name is answered (owner decision 2026-11-06): a name left out,
    # or a null in its place, is no reply in either form, and neither is a
    # name where numbers belong, or a key beside them.
    for wrong in ({"N2": ["N1"]}, {}, {"N1": None, "N2": ["N1"]},
                  {"N1": ["N1"], "N2": [LCEO]}, {"N1": ["N1"], ZERO: ["N1"]},
                  {**whole, "note": ["N1"]}):
        for form in (schema, strict):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(wrong, form)
    # An empty list: the server's grammar refuses it, a hosted API's has no
    # minimum, so the reading asks it again.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"N1": ["N1"], "N2": []}, schema)
    _, wrong = naming.answers_of({"N1": ["N1"], "N2": []},
                                 {LCEO: "N1", ZERO: "N2"})
    assert [one["name"] for one in wrong] == ["N2"]


def test_a_name_answered_with_names_not_shown_is_asked_again_then_itself():
    names = [LCEO, ZERO]
    made, asked = namer([every({ZERO: ["Zero"]}), every({ZERO: [LCEO]})])
    assert made(7, rows_of(*names), passages_of(names))["scenario"][ZERO] \
        == [LCEO]
    assert "corrections" not in asked[0]
    assert asked[1]["corrections"] == [{
        "name": "N2", "value": ["Zero"],
        "what": say("name_not_listed", name="N2", given='["Zero"]')}]
    # A name written where its number belongs is not a number shown, and
    # its number is left out.
    made, asked = namer([{"N1": ["N1"], ZERO: ["N1"]}, every({ZERO: [LCEO]})])
    assert made(7, rows_of(*names), passages_of(names))["scenario"][ZERO] \
        == [LCEO]
    assert [one["name"] for one in asked[1]["corrections"]] == [ZERO, "N2"]
    made, asked = namer([every({ZERO: ["Zero"]}), every({ZERO: ["Zero"]})])
    assert made(7, rows_of(*names), passages_of(names))["scenario"][ZERO] \
        == [ZERO]
    assert len(asked) == 2


def test_every_name_is_answered_and_one_left_out_is_asked_again_then_itself():
    names = [LCEO, ZERO, TECH]
    # Left out: asked again under its number, with the reason.
    made, asked = namer([by_number({LCEO: [LCEO], ZERO: [LCEO]}),
                         every({TECH: [TECH]})])
    meant = made(7, rows_of(*names), passages_of(names))["scenario"]
    assert asked[1]["corrections"] == [
        {"name": "N3", "what": say("key_missing", key="N3")}]
    assert meant[TECH] == [TECH]
    # The second reply counts only for the names asked again: what the first
    # answered stands, whatever the second says of it.
    made, asked = namer([by_number({LCEO: [LCEO], ZERO: [LCEO]}),
                         every({TECH: [LCEO]})])
    meant = made(7, rows_of(*names), passages_of(names))["scenario"]
    assert meant[ZERO] == [LCEO] and meant[TECH] == [LCEO]
    # Answered in neither: it means itself.
    made, asked = namer([by_number({LCEO: [LCEO]}),
                         by_number({LCEO: [LCEO]})])
    meant = made(7, rows_of(*names), passages_of(names))["scenario"]
    assert meant == {LCEO: [LCEO], ZERO: [ZERO], TECH: [TECH]}
    assert [one["name"] for one in asked[1]["corrections"]] == ["N2", "N3"]
    assert len(asked) == 2


def test_a_request_that_does_not_fit_is_asked_in_halves_then_together():
    names = ["A", "B", "C", "D"]
    made, asked = namer([every({"B": ["A"]}), every({}),
                         every({"C": ["A"]})], fits=3)
    meant = made(7, rows_of(*names), passages_of(names))["scenario"]
    assert meant == {"A": ["A"], "B": ["A"], "C": ["A"], "D": ["D"]}
    assert [sorted(names_shown(one).values()) for one in asked] == [
        names, ["A", "B"], ["C", "D"], ["A", "C", "D"]]
    # Halves that join nothing ask nothing more: it would be the request
    # that did not fit.
    made, asked = namer([every({}), every({})], fits=3)
    meant = made(7, rows_of(*names), passages_of(names))["scenario"]
    assert meant == {name: [name] for name in names}
    assert len(asked) == 3


# -- the graph -------------------------------------------------------------------

def factsheets(rows):
    serializer = kg.make_serializer(Path("no-such.db"), model=oekg(),
                                    groups={})
    graph = Graph().parse(data=serializer("doc", rows), format="turtle")
    sheets = set(graph.subjects(RDF.type, URIRef(OEO + "OEO_00000365")))
    labels = {str(graph.value(sheet, RDFS.label)): sheet for sheet in sheets}
    years = {label: {str(o)[:4] for o in graph.objects(
        sheet, URIRef(OEO + "OEO_00020440"))}
        for label, sheet in labels.items()}
    return years


def test_the_graph_puts_a_row_on_each_scenario_its_name_means():
    title = {"parameter": "publication_title", "value": "A Study",
             "quote": "A Study"}

    def label(name, means=None):
        return {"parameter": "scenario_label", "value": name,
                "quote": f"the {name} scenario",
                **({"value_means": means} if means else {})}
    year = {"parameter": "scenario_year", "value": "2050",
            "quote": "reach net zero by 2050", "scenario": BOTH,
            "scenario_state": READ,
            "scenario_quote": f"{BOTH} reach net zero by 2050",
            "scenario_means": [TECH, LIFE]}
    rows = [title, label(LCEO, [LCEO]), label(ZERO, [LCEO]),
            label(TECH, [TECH]), label(LIFE, [LIFE]), year]
    assert factsheets(rows) == {LCEO: set(), TECH: {"2050"},
                                LIFE: {"2050"}}
    # Without what the names mean, each name is a scenario of its own.
    bare = [{key: value for key, value in row.items()
             if not key.endswith("means")} for row in rows]
    assert factsheets(bare) == {LCEO: set(), ZERO: set(), TECH: set(),
                                LIFE: set(), BOTH: {"2050"}}
    assert kg.scenario_names(dict(year, scenario_quote="nothing like it")) \
        == []
