"""A scenario is read as the publication prints it, and which of a
publication's names mean the same scenario is asked once it is read (owner
decisions 2026-11-06).

The scenario of a value is asked as free text with no list, AND a name its
quote does not print is not read. A value stated for several scenarios is
one row per name, each checked on its own, AND a correction for one of them
names its name, AND the combing's rows join their value's reading; a pass
over a stored harvest takes the first name. Only a free-text coordinate or
value is merged, AND never one the survey reads.

Once the document is folded, the names read for a kind get candidates
from two sources (owner decisions 2026-11-06): one request over all names,
each under a number with the quote it was read with, AND as its example a
group of its own first two names, whose groups name numbers shown, two or
more each, AND a reply without "groups" or with a number not shown is asked
once more with its reason, AND one wrong twice gives no groups, AND a
request that does not fit is asked for each half of the names; and each
name embedded with the text around it where it was first read, 100
characters before and after it, AND its 15 nearest names by angle, never
itself, AND every name that has it among its nearest. Each name with a
candidate is asked on its own against its candidates alone: its places,
each quote with 500 characters before and after it, AND a stretch of a
passage once however many quotes stand in it, AND only its own places, AND
its candidates under numbers with the quotes they were read with, AND as
its example the name alone; a name without candidates asks nothing. An
answer that holds the name gives the other names of its thing, AND so does
one other name alone; two names are one thing only where each gives the
other, called by its first name, AND a wrong name given one way joins
nothing; an answer of several names without the name stands for each of
their things, AND an answer with no name shown means the name itself. The
reply names numbers shown under "means", at least one, AND nothing beside
them, in the form a server holds it to and in the form a hosted API does. A
reply without "means", AND one with a number not shown, is asked once more
with its reason, AND a name answered in neither means itself. Each row read
gets the names of what it means, AND a row that read no name gets none. One
name asks nothing. A request about a name that does not fit is asked
against each half of its candidates, AND a half that gives the name alone
adds nothing. The graph writes a row to each scenario its name means, AND
names of one scenario are one factsheet.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path
from types import SimpleNamespace

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
from test_graph_from_shapes import OEO, make_serializer, oekg


def answered(thread, reply):
    """What the run keeps of an answer (`runner.ask_in_grammar`): a reply
    the conversation goes on after (owner decisions 2026-11-07)."""
    if thread is not None and isinstance(reply, dict):
        thread.messages = [*thread.messages, {"role": "user", "content": ""},
                           {"role": "assistant",
                            "content": json.dumps(reply)}]
    return reply


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


def listed(reply):
    """A values reply as the run asks it (owner decisions 2026-11-08: every
    value of a passage in one answer): a fixture's one value as an answer
    that lists it, {"value": null} as one that lists none; a whole answer,
    or no answer, as given."""
    if not isinstance(reply, dict) or "values" in reply:
        return reply
    if reply.get("value") is None:
        return {"values": [], "incomplete": False}
    return {"values": [reply], "incomplete": False}


def read_of(parameter, values, groups=None, spec=None):
    """A Reader over TEXT: *values* the replies of the rounds in turn,
    *groups* {group: a reply, or [replies in turn]}."""
    calls = []
    given = {name: (list(reply) if isinstance(reply, list) else [reply])
             for name, reply in (groups or {}).items()}

    def ask_values(source, parameter, context, read, thread, follow=None,
                   drawn=False):
        payload = ({**follow, "follows": True} if follow is not None
                   else reading.values_payload(source, parameter, context,
                                               read, drawn))
        calls.append(("values", payload,
                      reading.values_response_format(parameter)))
        return answered(thread, listed(values[min(
            sum(1 for c in calls if c[0] == "values"), len(values)) - 1]))

    def ask_text(source, parameter, group, slots, row, context, thread,
                 follow=None):
        name = group.name if group is not None else "near"
        if follow is not None:
            payload = {**follow, "follows": True}
        elif thread.begun:
            payload = reading.group_payload(parameter, slots, group.where,
                                            context)
        else:
            payload = reading.text_payload(source, parameter, slots, row,
                                           group.where, context)
        calls.append((name, payload, reading.text_response_format(slots)))
        replies = given.get(name)
        if not replies:
            reply = {slot.name: {"value": fields.UNSTATED} for slot in slots}
        else:
            reply = replies.pop(0) if len(replies) > 1 else replies[0]
        return answered(thread, reply)

    reader = reading.Reader(spec or SPEC, ask_values, ask_text)
    read = reader.read(7, parameter, TEXT, [],
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
    # Entries beside the names are for an axis of names only.
    year["axes"]["scenario"].pop("beside", None)
    return load_spec(raw)


# -- the reading ---------------------------------------------------------------

def test_a_scenario_is_read_as_printed_and_a_name_its_quote_lacks_is_not():
    read, calls = read_of(YEAR, (Y2030, {"value": None}),
                          groups={"scenario": NAMED})
    (_task, payload, shape), = [c for c in calls if c[0] == "scenario"]
    # A wording, with no list but the entries it takes beside the names
    # (owner decision 2026-11-07).
    assert payload["coordinates"]["scenario"]["kind"] == fields.TEXT
    assert set(payload["coordinates"]["scenario"]["options"]) == {
        "status quo", "several scenarios"}
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
    # The conversation shows no passage, only the value's quote and what it
    # read: the quote of the value holds the names here.
    claim = {"source": "Q1", "value": "2030", "quote": TEXT.text,
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
    stored = {"source": "Q1", "value": "2030", "quote": TEXT.text,
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


def test_names_are_one_scenario_only_where_each_gives_the_other():
    order = [LCEO, ZERO, TECH, LIFE, BOTH]
    meant = naming.meanings(order, {
        LCEO: [LCEO, ZERO], ZERO: [ZERO, LCEO], TECH: [TECH], LIFE: [LIFE],
        BOTH: [TECH, LIFE]})
    assert meant == {LCEO: [LCEO], ZERO: [LCEO], TECH: [TECH],
                     LIFE: [LIFE], BOTH: [TECH, LIFE]}
    # The failure by construction: a name that gives another which does not
    # give it back is no join (owner decision 2026-11-06).
    meant = naming.meanings(order, {LCEO: [LCEO, ZERO], ZERO: [ZERO]})
    assert meant[LCEO] == [LCEO] and meant[ZERO] == [ZERO]
    # One other name alone is a name of its thing too, where it gives it
    # back.
    assert naming.meanings(["x", "y"], {"x": ["y"], "y": ["y", "x"]}) \
        == {"x": ["x"], "y": ["x"]}
    assert naming.meanings(["x", "y"], {"x": ["y"], "y": ["y"]}) \
        == {"x": ["x"], "y": ["y"]}
    # A wrong name in a list joins nothing that does not give it back: 2DS
    # gives RTS, RTS does not give 2DS.
    meant = naming.meanings(["2DS", "2C", "RTS"], {
        "2DS": ["2DS", "2C", "RTS"], "2C": ["2C", "2DS"], "RTS": ["RTS"]})
    assert meant == {"2DS": ["2DS"], "2C": ["2DS"], "RTS": ["RTS"]}
    # Joins chain: p and q, q and r make one thing, called by its first.
    meant = naming.meanings(["p", "q", "r"], {
        "p": ["p", "q"], "q": ["q", "p", "r"], "r": ["r", "q"]})
    assert meant == {"p": ["p"], "q": ["p"], "r": ["p"]}
    # A name of several things stands for each, by the names they are
    # called by, and is joined to none of them.
    meant = naming.meanings(["a", "b", "c", "g"], {
        "a": ["a", "b"], "b": ["b", "a"], "c": ["c", "g"], "g": ["b", "c"]})
    assert meant == {"a": ["a"], "b": ["a"], "c": ["c"], "g": ["a", "c"]}
    # An answer with no name of the order means the name itself.
    assert naming.meanings(["a"], {"a": ["missing"]}) == {"a": ["a"]}


def test_the_candidates_are_the_groups_and_the_nearest_names_both_ways():
    order = ["a", "b", "c", "d", "e"]
    assert naming.candidates(order, [["c", "a"]], {"d": ["b"]}) == {
        "a": ["c"], "b": ["d"], "c": ["a"], "d": ["b"], "e": []}
    # The failure by construction: a name no group holds and no name has
    # among its nearest has none (e above), and a name not read is none.
    assert naming.candidates(["a"], [["a", "x"]], {"a": ["x"]}) == {"a": []}


def test_the_nearest_names_are_by_angle_and_never_the_name_itself():
    vectors = [(1, 0), (0.9, 0.1), (0, 1), (5, 5)]
    near = naming.neighbours(vectors, 2)
    # By angle: the long vector at 45 degrees is farther than the short one
    # beside it, though their product is larger.
    assert near[0] == [1, 3]
    assert all(at not in nearest for at, nearest in enumerate(near))
    assert [len(nearest) for nearest in naming.neighbours(vectors, 15)] \
        == [3] * 4
    assert naming.NEIGHBOURS == 15
    many = [(1, i / 100) for i in range(20)]
    assert {len(nearest) for nearest
            in naming.neighbours(many, naming.NEIGHBOURS)} == {15}


def test_a_name_is_embedded_with_100_characters_around_it_where_first_read():
    quote = "the LCEO Zero Carbon scenario reaches"
    text = "x" * 300 + " " + quote + " " + "y" * 300
    passages = {
        ("section", 1): Source("section", 1, text, {"section_title": "S"}),
        ("section", 2): Source("section", 2, "z" * 50 + " LCEO Zero Carbon "
                               "again " + "w" * 50, {})}
    places = [(("section", 1), quote), (("section", 2), "LCEO Zero Carbon")]
    at = text.index(LCEO)
    assert naming.EMBED_CONTEXT_CHARS == 100
    assert naming.context_of(LCEO, places, passages) == (
        LCEO + "\n" + text[at - 100:at + len(LCEO) + 100])
    # The failure by construction: a quote that does not print the name
    # gives the text around the quote.
    start = text.index(quote)
    assert naming.context_of("LCEO ZC", places, passages) == (
        "LCEO ZC\n" + text[start - 100:start + len(quote) + 100])


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


def turns(per_name=None, shorts=()):
    """What the model answers about each name in turn: a reply as it is
    (a dict), or the names it gives in the numbers the request showed, a
    name the request did not show as it is, and whether it is one of the
    short names *shorts*; a name with nothing left gives itself."""
    left = {name: list(replies) for name, replies in (per_name or {}).items()}

    def answer(name, payload):
        number = {entry["name"]: key for key, entry in payload["names"].items()}
        replies = left.get(name)
        given = replies.pop(0) if replies else [name]
        if isinstance(given, dict):
            return given
        return {"means": [number.get(one, one) for one in given],
                "short": name in shorts}
    return answer


def names_shown(payload) -> dict:
    """{number: name} of a request."""
    return {key: entry["name"] for key, entry in payload["names"].items()}


def namer(answer, fits=None, grouped=None, vectors=None, groups_fit=None):
    """A Namer whose request about a name answers *answer(name, payload)*,
    one of more names than *fits* not fitting; whose request over all names
    answers *grouped(payload)*, by default one group of every name it
    shows, one of more names than *groups_fit* not fitting; and whose
    embedding gives each name its vector in *vectors*, no embedding where
    there are none. Returns it, the requests about a name and those over all
    names, each with the example its prompt shows, the texts embedded, and
    the trace."""
    asked, group_asks, embedded, traced = [], [], [], []

    def ask(payload, shape, document_id, kind, example=None, thread=None,
            follow=None):
        # A follow-up carries what was wrong after the answer it follows
        # (owner decisions 2026-11-07); the request it follows is kept.
        payload = {**payload, **(follow or {})}
        asked.append((payload, example))
        if fits is not None and len(payload["names"]) > fits:
            return naming.CUT
        return answer(payload["name"]["name"], payload)

    def ask_groups(payload, shape, document_id, kind, example=None,
                   thread=None, follow=None):
        payload = {**payload, **(follow or {})}
        group_asks.append((payload, example))
        if groups_fit is not None and len(payload["names"]) > groups_fit:
            return naming.CUT
        if grouped is None:
            return {"groups": [list(payload["names"])]}
        return grouped(payload)

    def embed(texts):
        embedded.extend(texts)
        return [vectors[text.split("\n")[0]] for text in texts]
    made = naming.Namer(SPEC, ask,
                        trace=lambda *args, **kw: traced.append((args, kw)),
                        ask_groups=ask_groups,
                        embed=embed if vectors is not None else None)
    return made, asked, group_asks, embedded, traced


def test_every_name_is_asked_on_its_own_with_its_places_and_its_candidates():
    names = [LCEO, ZERO, TECH]
    rows = rows_of(*names, unread=[fields.UNBACKED])
    # The request over all names puts LCEO and ZERO together; TECH has no
    # candidate and asks nothing (owner decision 2026-11-06).
    made, asked, group_asks, _, traced = namer(
        turns({LCEO: [[LCEO, ZERO]], ZERO: [[ZERO, LCEO]]}),
        grouped=lambda payload: {"groups": [["N1", "N2"]]})
    meant = made(7, rows, passages_of(names))
    assert meant == {"scenario": {LCEO: [LCEO], ZERO: [LCEO], TECH: [TECH]}}
    # The request over all names shows every name with the quote it was
    # read with, and as its example a group of its first two names.
    ((shown, example),) = group_asks
    assert shown["kind"] == "scenario"
    assert names_shown(shown) == {"N1": LCEO, "N2": ZERO, "N3": TECH}
    assert [entry["quote"] for entry in shown["names"].values()] == [
        f"We call it {name} here" for name in names]
    assert example == {"groups": [["N1", "N2"]]}
    # One request per name that has a candidate, showing the name and its
    # candidates alone, and its own places alone.
    assert [payload["name"]["name"] for payload, _ in asked] == [LCEO, ZERO]
    for payload, example in asked:
        own = payload["name"]["name"]
        assert payload["kind"] == "scenario"
        assert names_shown(payload) == {"N1": LCEO, "N2": ZERO}
        places = " ".join(payload["name"]["places"])
        assert f"We call it {own} here" in places
        assert all(f"We call it {other} here" not in places
                   for other in names if other != own)
        # Its example is its own reply: the name alone.
        assert example == {"means": [payload["name"]["number"]],
                           "short": False}
    assert [row.get("value_means") for row in rows
            if row["parameter"] == "scenario_label"] == [[LCEO], [LCEO],
                                                          [TECH]]
    assert [row.get("scenario_means") for row in rows
            if row["parameter"] == "scenario_year"] == [[LCEO], [LCEO],
                                                         [TECH], None]
    ((_, summary),) = [one for one in traced if one[0][0] == "naming"]
    assert (summary["names"], summary["things"], summary["groups"],
            summary["asked"]) == (3, 2, 1, 2)


def test_the_nearest_names_by_their_embedding_are_candidates_too(monkeypatch):
    names = ["A", "B", "C", "D"]
    monkeypatch.setattr(naming, "NEIGHBOURS", 1)
    vectors = {"A": (1, 0), "B": (0.9, 0.1), "C": (0, 1), "D": (0.1, 0.9)}
    made, asked, _, embedded, _ = namer(
        turns(), grouped=lambda payload: {"groups": []}, vectors=vectors)
    made(7, rows_of(*names), passages_of(names))
    # Each name embedded once, with the text around it where it was read.
    assert [text.split("\n")[0] for text in embedded] == names
    assert all(f"We call it {name} here" in text
               for name, text in zip(names, embedded))
    against = {payload["name"]["name"]: sorted(names_shown(payload).values())
               for payload, _ in asked}
    assert against == {"A": ["A", "B"], "B": ["A", "B"], "C": ["C", "D"],
                       "D": ["C", "D"]}
    # The failure by construction: with no group and no embedding, nothing
    # is asked and every name means itself.
    made, asked, _, _, _ = namer(turns(),
                                 grouped=lambda payload: {"groups": []})
    assert made(7, rows_of(*names), passages_of(names))["scenario"] == {
        name: [name] for name in names}
    assert asked == []


def test_one_name_asks_nothing():
    rows = rows_of(LCEO)
    made, asked, group_asks, embedded, _ = namer(turns(),
                                                 vectors={LCEO: (1, 0)})
    assert made(7, rows, passages_of([LCEO])) == {"scenario": {LCEO: [LCEO]}}
    assert asked == group_asks == embedded == []
    assert rows[0]["value_means"] == [LCEO]


def test_the_reply_names_numbers_shown_under_means():
    schema = naming.response_format(["N1", "N2"])["json_schema"]["schema"]
    strict, decode = strict_schema.strict(schema)
    for whole in ({"means": ["N1"], "short": False},
                  {"means": ["N2", "N1"], "short": True}):
        for form in (schema, strict):
            jsonschema.validate(whole, form)
        assert decode(whole) == whole
    # A reply without "means", with a name where numbers belong, or with a
    # key beside it, is no reply in either form.
    for wrong in ({}, {"means": None, "short": False},
                  {"means": [LCEO], "short": False}, {"means": ["N1"]},
                  {"means": ["N1"], "short": False, "note": ["N1"]},
                  {"N1": ["N1"]}):
        for form in (schema, strict):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(wrong, form)
    # An empty list: the server's grammar refuses it, a hosted API's has no
    # minimum, so the naming asks it again.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"means": [], "short": False}, schema)
    numbers = {LCEO: "N1", ZERO: "N2"}
    assert naming.means_of({"means": ["N2", "N1"], "short": True},
                           numbers) == (([ZERO, LCEO], True), None)
    # the failure by construction: no "short", asked again by its key
    assert naming.means_of({"means": ["N2"]}, numbers) == (
        None, {"what": say("key_missing", key="short")})
    assert naming.means_of({"means": [], "short": False}, numbers) == (None, {
        "value": [], "what": say("name_not_listed", name="means",
                                 given="[]")})


def test_the_groups_reply_names_lists_of_numbers_shown():
    schema = naming.groups_format(["N1", "N2", "N3"])["json_schema"]["schema"]
    strict, decode = strict_schema.strict(schema)
    for whole in ({"groups": [["N1", "N2"]]}, {"groups": []},
                  {"groups": [["N3", "N1", "N2"]]}):
        for form in (schema, strict):
            jsonschema.validate(whole, form)
        assert decode(whole) == whole
    # A reply without "groups", with numbers outside a list, a name where
    # numbers belong, or a key beside it, is no reply in either form.
    for wrong in ({}, {"groups": ["N1", "N2"]}, {"groups": [[LCEO, "N1"]]},
                  {"groups": [["N1", "N2"]], "note": []}):
        for form in (schema, strict):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(wrong, form)
    # A group of one name: the server's grammar refuses it, and read it is
    # no group.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"groups": [["N1"]]}, schema)
    numbers = {LCEO: "N1", ZERO: "N2", TECH: "N3"}
    assert naming.groups_of({"groups": [["N2", "N1", "N2"], ["N3"],
                                        ["N3", "N3"]]}, numbers) == (
        [[ZERO, LCEO]], None)
    assert naming.groups_of({"groups": [["N1", "N9"]]}, numbers) == (None, {
        "value": [["N1", "N9"]], "what": say(
            "groups_not_listed", name="groups", given='[["N1", "N9"]]')})


def test_a_wrong_groups_reply_is_asked_again_with_its_reason_then_none():
    names = [LCEO, ZERO]
    both = turns({LCEO: [[LCEO, ZERO]], ZERO: [[ZERO, LCEO]]})
    replies = [{"groups": [["N1", "Zero"]]}, {"groups": [["N1", "N2"]]}]
    made, _, group_asks, _, _ = namer(both,
                                      grouped=lambda payload: replies.pop(0))
    assert made(7, rows_of(*names), passages_of(names))["scenario"][ZERO] \
        == [LCEO]
    assert group_asks[1][0]["corrections"] == {
        "value": [["N1", "Zero"]],
        "what": say("groups_not_listed", name="groups",
                    given='[["N1", "Zero"]]')}
    # Without "groups" at all: missing, by its key.
    replies = [{"N1": ["N2"]}, {"groups": [["N1", "N2"]]}]
    made, _, group_asks, _, _ = namer(
        turns({LCEO: [[LCEO, ZERO]], ZERO: [[ZERO, LCEO]]}),
        grouped=lambda payload: replies.pop(0))
    made(7, rows_of(*names), passages_of(names))
    assert group_asks[1][0]["corrections"] == {
        "what": say("key_missing", key="groups")}
    # Wrong twice: asked twice only, no groups, and with no other source
    # nothing is asked about a name.
    replies = [{"groups": "N1"}, {"groups": [["N1", "x"]]}]
    made, asked, group_asks, _, _ = namer(
        turns(), grouped=lambda payload: replies.pop(0))
    assert made(7, rows_of(*names), passages_of(names))["scenario"] == {
        LCEO: [LCEO], ZERO: [ZERO]}
    assert len(group_asks) == 2 and asked == []


def test_a_request_over_all_names_that_does_not_fit_is_asked_for_each_half():
    names = ["A", "B", "C", "D", "E"]
    made, asked, group_asks, _, _ = namer(turns(), groups_fit=3)
    made(7, rows_of(*names), passages_of(names))
    assert [sorted(names_shown(payload).values())
            for payload, _ in group_asks] == [names, ["A", "B"],
                                              ["C", "D", "E"]]
    # Each half's group gives candidates; one across the halves does not.
    against = {payload["name"]["name"]: sorted(names_shown(payload).values())
               for payload, _ in asked}
    assert against == {"A": ["A", "B"], "B": ["A", "B"],
                       "C": ["C", "D", "E"], "D": ["C", "D", "E"],
                       "E": ["C", "D", "E"]}
    # Nothing left to halve: no groups, and the trace says why.
    made, asked, group_asks, _, traced = namer(turns(), groups_fit=1)
    meant = made(7, rows_of("A", "B", "C"), passages_of(["A", "B", "C"]))
    assert meant["scenario"] == {"A": ["A"], "B": ["B"], "C": ["C"]}
    assert len(group_asks) == 1 and asked == []
    assert [kw.get("why") for args, kw in traced if args[0] == "naming"] \
        == [naming.CUT, None]


def test_a_wrong_reply_is_asked_again_with_its_reason_then_means_itself():
    names = [LCEO, ZERO]
    made, asked, _, _, _ = namer(turns({LCEO: [[LCEO, ZERO]],
                                        ZERO: [{"means": ["Zero"],
                                                "short": False}, [LCEO]]}))
    assert made(7, rows_of(*names), passages_of(names))["scenario"][ZERO] \
        == [LCEO]
    again = [payload for payload, _ in asked if payload.get("corrections")]
    assert [payload["name"]["name"] for payload in again] == [ZERO]
    assert again[0]["corrections"] == {
        "value": ["Zero"],
        "what": say("name_not_listed", name="means", given='["Zero"]')}
    # Without "means" at all: missing, by its key.
    made, asked, _, _, _ = namer(turns({LCEO: [[LCEO, ZERO]],
                                        ZERO: [{"N2": ["N1"]}, [LCEO]]}))
    assert made(7, rows_of(*names), passages_of(names))["scenario"][ZERO] \
        == [LCEO]
    (again,) = [payload for payload, _ in asked if payload.get("corrections")]
    assert again["corrections"] == {"what": say("key_missing", key="means")}
    # Wrong twice: asked twice only, and the name means itself.
    made, asked, _, _, _ = namer(turns({
        LCEO: [[LCEO, ZERO]], ZERO: [{"means": ["Zero"], "short": False},
                                     {"means": [LCEO], "short": False}]}))
    assert made(7, rows_of(*names), passages_of(names))["scenario"][ZERO] \
        == [ZERO]
    assert [payload["name"]["name"] for payload, _ in asked].count(ZERO) == 2


def test_a_request_about_a_name_that_does_not_fit_is_asked_against_halves():
    names = ["A", "B", "C", "D", "E"]
    # C gives A in the half that shows A and itself alone in the other, and
    # A gives C: one thing.
    made, asked, _, _, _ = namer(turns({"A": [["A", "C"]],
                                        "C": [["C", "A"], ["C"]]}), fits=3)
    meant = made(7, rows_of(*names), passages_of(names))["scenario"]
    assert meant == {"A": ["A"], "B": ["B"], "C": ["A"], "D": ["D"],
                     "E": ["E"]}
    about_c = [sorted(names_shown(payload).values())
               for payload, _ in asked if payload["name"]["name"] == "C"]
    assert about_c == [names, ["A", "B", "C"], ["C", "D", "E"]]
    # A name of several scenarios, one in each half, stands for both.
    made, _, _, _, _ = namer(turns({"C": [["A"], ["E"]]}), fits=3)
    assert made(7, rows_of(*names), passages_of(names))["scenario"]["C"] \
        == ["A", "E"]
    # A half that gives the name alone adds nothing: C stands for A and B.
    made, _, _, _, _ = namer(turns({"C": [["A", "B"], ["C"]]}), fits=3)
    assert made(7, rows_of(*names), passages_of(names))["scenario"]["C"] \
        == ["A", "B"]
    # Nothing left to halve: the name means itself.
    made, asked, _, _, _ = namer(turns(), fits=1)
    meant = made(7, rows_of("A", "B"), passages_of(["A", "B"]))["scenario"]
    assert meant == {"A": ["A"], "B": ["B"]} and len(asked) == 2


# -- the graph -------------------------------------------------------------------

def factsheets(rows):
    serializer = make_serializer(Path("no-such.db"), model=oekg(),
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


# -- one quote for several names, one follow-up per reply, the names read so
# far (owner decisions 2026-11-07) -------------------------------------------

SHARED = {"value": ["CurPol", "NDC"],
          "quote": "the Current Policies scenario (CurPol) and the NDC "
                   "scenario"}


# Promise: an answer may name several scenarios with one quote, AND it stands
# for one answer per name, each with that quote, AND the grammar takes it
# for a coordinate that may name several things only, AND only with its
# quote; by construction, a list of such an answer and a single one, a
# shared answer without a quote, and a coordinate that is not merged.
def test_names_that_share_one_quote_are_one_answer_each_with_that_quote():
    slot = scenario_slot(SPEC)
    schema = reading.answer_schema(slot)
    jsonschema.validate(SHARED, schema)
    jsonschema.validate([SHARED, NAMED["scenario"]], schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"value": ["CurPol", "NDC"]}, schema)
    plain = scenario_slot(unmerged_spec())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(SHARED, reading.answer_schema(plain))
    each = [{"scenario": {"value": name, "quote": SHARED["quote"]}}
            for name in SHARED["value"]]
    assert reading.answers_each({"scenario": SHARED}, [slot]) == each
    assert reading.answers_each({"scenario": [SHARED, NAMED["scenario"]]},
                                [slot]) == each + [NAMED]
    assert reading.answers_each({"scenario": SHARED}, [plain]) \
        == [{"scenario": SHARED}]


# Promise: a value read with one quote for several names is one row per
# name, each read with that quote, AND a name the shared quote lacks is
# refused on its row alone and asked once more by its name; by construction,
# a quote that holds both names and one that holds one.
def test_a_shared_quote_reads_each_name_it_holds_and_refuses_the_others():
    read, _ = read_of(YEAR, (Y2030, {"value": None}),
                      groups={"scenario": {"scenario": SHARED}})
    assert [(c["scenario"], c["scenario_state"], c["scenario_quote"])
            for c in read.claims] == [("CurPol", READ, SHARED["quote"]),
                                      ("NDC", READ, SHARED["quote"])]
    half = {"value": ["CurPol", "Current Policies"],
            "quote": "Results for the CurPol scenario"}
    read, calls = read_of(YEAR, (Y2030, {"value": None}),
                          groups={"scenario": {"scenario": half}})
    assert [(c.get("scenario"), c["scenario_state"]) for c in read.claims] \
        == [("CurPol", READ), (None, fields.UNBACKED)]
    told = [one for payload in follow_ups(calls)
            for one in payload["corrections"]]
    assert [(one["value"], one["quote"]) for one in told] == [
        ("Current Policies", "Results for the CurPol scenario")]


FIRST = {"scenario": [
    {"value": "CurPol", "quote": "Results for the CurPol scenario"},
    # A quote in no passage, and a name its quote lacks: both refused.
    {"value": "NDC", "quote": "the NDC pathway of another study"},
    {"value": "Current Policies", "quote": "the CurPol scenario"}]}
CHANGED = {"value": "Current Policies scenario",
           "quote": "the Current Policies scenario (CurPol)"}
NDC_FIXED = {"value": "NDC", "quote": "the NDC scenario"}
CP_FIXED = {"value": "Current Policies",
            "quote": "the Current Policies scenario"}
CURPOL_AGAIN = FIRST["scenario"][0]


def follow_ups(calls, task: str = "scenario") -> list:
    """The messages of *task* that carry corrections."""
    return [payload for name, payload, _shape in calls
            if name == task and payload.get("corrections")]


# Promise: what the check refuses on the rows one answer made is asked in ONE
# message after that answer, naming each refused name with its quote, AND
# each answer goes to the row of its name whatever its place in the reply,
# AND a name for none of them is a row of its own, AND an answer that
# repeats an accepted one unchanged makes no row; by construction, the names
# answered out of order, a further name and a repeat.
def test_one_follow_up_names_every_refused_name_and_each_finds_its_row():
    again = {"scenario": [CHANGED, NDC_FIXED, CURPOL_AGAIN, CP_FIXED]}
    read, calls = read_of(YEAR, (Y2030, {"value": None}),
                          groups={"scenario": [FIRST, again]})
    (asked,) = follow_ups(calls)
    assert [(one["coordinate"], one["value"], one["quote"])
            for one in asked["corrections"]] == [
        ("scenario", "NDC", "the NDC pathway of another study"),
        ("scenario", "Current Policies", "the CurPol scenario")]
    assert [(c["scenario"], c["scenario_state"]) for c in read.claims] == [
        ("CurPol", READ), ("NDC", READ), ("Current Policies", READ),
        ("Current Policies scenario", READ)]
    assert read.claims[1]["scenario_quote"] == "the NDC scenario"


# Promise: a changed name goes to the next row of a refused name still open;
# by construction, the reply names one refused name as before and the other
# under another name, before it.
def test_a_changed_name_goes_to_the_next_refused_row_still_open():
    again = {"scenario": [CHANGED, NDC_FIXED]}
    read, calls = read_of(YEAR, (Y2030, {"value": None}),
                          groups={"scenario": [FIRST, again]})
    assert len(follow_ups(calls)) == 1
    assert [(c["scenario"], c["scenario_state"]) for c in read.claims] == [
        ("CurPol", READ), ("NDC", READ), ("Current Policies scenario", READ)]


# Promise: a row corrected on another coordinate takes it from a follow-up's
# first answer, AND so does a refused row whose name came back from no
# answer, AND an unchanged repeat corrects no name; by construction, a
# coordinate beside the names.
def test_a_follow_up_s_answers_go_to_the_coordinates_each_row_was_told():
    names = SimpleNamespace(name="scenario", merged="scenario")
    other = SimpleNamespace(name="region", merged=None)
    rows = [reading.Row(label=f"R{i}", item_index=0, claim={})
            for i in range(3)]
    given = {"R0": {"scenario": {"value": "A", "quote": "qa"}},
             "R1": {"scenario": {"value": "B", "quote": "qb"}},
             "R2": {"scenario": {"value": "C", "quote": "qc"}}}
    corrections = {"R0": [{"coordinate": "region"}],
                   "R1": [{"coordinate": "scenario"},
                          {"coordinate": "region"}]}
    repeat = {"scenario": {"value": "A", "quote": "qa"}, "region": "EU"}
    fixed = {"scenario": {"value": "B", "quote": "qb2"}, "region": "EU"}
    out = reading.routed([repeat, fixed], rows, corrections, given,
                         [names, other])
    assert [(row.label, answer, coordinates)
            for row, answer, coordinates in out] == [
        ("R0", repeat, {"region"}), ("R1", fixed, {"scenario", "region"})]
    out = reading.routed([repeat], rows, corrections, given, [names, other])
    assert [(row.label, coordinates) for row, _answer, coordinates in out] \
        == [("R0", {"region"}), ("R1", {"region"})]


def combing_asks(*replies):
    """An ask that answers *replies* in turn, and what it was sent."""
    asked = []

    def ask(payload, shape, document_id, source, group=None, example=None,
            thread=None, follow=None):
        asked.append(payload if follow is None else follow)
        return answered(thread, replies[min(len(asked), len(replies)) - 1])
    return ask, asked


def year_open(**given):
    # The conversation shows the value's quote and not its passage, so the
    # quote holds the names the answers quote.
    return {"source": "Q1", "value": "2030", "quote": TEXT.text,
            "scenario_state": fields.SAID_UNSTATED, **given}


# Promise: the combing asks what it refuses on the rows its reply made in ONE
# message after that reply, naming each refused name with its quote, AND
# each answer goes to the row of its name, AND a further name is a row of
# its own that joins the reading; by construction, two names refused and
# three given back.
def test_the_combing_asks_once_for_every_refused_name():
    batch = Batch(7, YEAR, [WorkItem(7, YEAR, TEXT)], spec=SPEC)
    read = reading.Read(batch, [year_open()], probes=[{}])
    ask, asked = combing_asks(FIRST, {"scenario": [CHANGED, NDC_FIXED,
                                                   CP_FIXED]})
    passages = {(TEXT.owner_kind, TEXT.owner_id): TEXT}
    combing.Comber(SPEC, ask, None, lambda claim, names: {})(
        7, [read], passages, [])
    told = [payload for payload in asked if payload.get("corrections")]
    assert len(told) == 1
    assert [(one["value"], one["quote"]) for one in told[0]["corrections"]] \
        == [("NDC", "the NDC pathway of another study"),
            ("Current Policies", "the CurPol scenario")]
    assert [(c["scenario"], c["scenario_state"]) for c in read.claims] == [
        ("CurPol", READ), ("NDC", READ), ("Current Policies", READ),
        ("Current Policies scenario", READ)]
    assert len(read.probes) == len(read.claims)


# Promise: a combing request for a coordinate that may name several things
# shows every name read in the plan so far, each once, in the order read, as
# a value and as a coordinate (owner decision 2026-11-07), AND one for a
# coordinate that names no such thing shows none; by construction, a name
# read twice, and the scenario not merged.
def test_the_combing_shows_every_name_read_so_far_once():
    read_too = [year_open(scenario=name, scenario_state=READ,
                          scenario_quote=quote)
                for name, quote in (("CurPol", "the CurPol scenario"),
                                    ("Current Policies",
                                     "the Current Policies scenario"))]
    passages = {(TEXT.owner_kind, TEXT.owner_id): TEXT}
    for spec, shown in ((SPEC, ["CurPol", "NDC", "Current Policies"]),
                        (unmerged_spec(), None)):
        label, year = (spec.by_uri[uri] for uri in ("scenario_label",
                                                     "scenario_year"))
        labels = reading.Read(Batch(7, label, [WorkItem(7, label, TEXT)],
                                    spec=spec), [
            {"source": "Q1", "value": "CurPol",
             "quote": "the CurPol scenario"},
            {"source": "Q1", "value": "NDC", "quote": "the NDC scenario"}])
        years = reading.Read(Batch(7, year, [WorkItem(7, year, TEXT)],
                                   spec=spec),
                             [year_open(), *read_too], probes=[{}, {}, {}])
        ask, asked = combing_asks({"more": []})
        combing.Comber(spec, ask, None, lambda claim, names: {})(
            7, [labels, years], passages, [])
        first = [payload for payload in asked if "passage" in payload]
        assert len(first) == 1
        assert first[0].get("names") == shown
        if shown:
            assert combing.names_read(spec, [labels, years]) == {
                "scenario": shown}


# Promise: a name the naming answers as a short name marks its rows
# `value_short`, AND one it does not answer so stays unmarked (owner decision
# 2026-11-07; the graph's side is in test_graph_from_shapes.py).
def test_a_name_answered_as_short_marks_its_rows():
    long, short = "Distributed Generation", "ENTSO-E DG"

    def marked(shorts):
        rows = rows_of(long, short)
        made, _, _, _, _ = namer(turns({long: [[long, short]],
                                        short: [[short, long]]},
                                       shorts=shorts))
        made(7, rows, passages_of([long, short]))
        return [row["value"] for row in rows if row.get("value_short")]
    assert marked({short}) == [short]
    # the failure by construction: no short name answered, none marked
    assert marked(set()) == []


# Promise: the words of several scenarios are asked once per wording and
# document, against every scenario of the document, AND the rows with those
# words get the scenarios the answer names; an answer naming none leaves
# them with no scenario. The graph writes such a row to each of them, AND to
# none without them (owner decision 2026-11-07).
def several_rows(*names):
    rows = rows_of(*names)
    for index, words in enumerate(("all scenarios", "All Scenarios")):
        rows.append({"parameter": "scenario_year", "value": f"20{40 + index}",
                     "quote": f"by 20{40 + index} in {words}",
                     "scenario": naming.SEVERAL, "scenario_raw": words,
                     "scenario_state": READ,
                     "scenario_quote": f"by 20{40 + index} in {words}",
                     "scenario_source": ["section", 0]})
    return rows


def resolve(answer):
    asked = []

    def ask_several(payload, shape, document_id, kind, example=None,
                    thread=None, follow=None):
        asked.append(payload)
        number = {entry["name"]: key for key, entry in payload["names"].items()}
        return {"means": [number[one] for one in answer]}
    made = naming.Namer(SPEC, turns(), ask_groups=lambda *a, **k: {"groups": []},
                        ask_several=ask_several)
    rows = several_rows(LCEO, TECH)
    made(7, rows, passages_of([LCEO, TECH]))
    return rows, asked


def test_the_words_of_several_scenarios_get_the_scenarios_they_stand_for():
    rows, asked = resolve([LCEO, TECH])
    assert len(asked) == 1
    assert set(names_shown(asked[0]).values()) == {LCEO, TECH}
    several = [row for row in rows if row.get("scenario") == naming.SEVERAL]
    assert [row.get("scenario_means") for row in several] == [[LCEO, TECH]] * 2
    from profiles.scenarios import kg
    assert kg.scenario_names(several[0]) == [LCEO, TECH]
    # the failure by construction: the answer names none
    rows, _ = resolve([])
    several = [row for row in rows if row.get("scenario") == naming.SEVERAL]
    assert all("scenario_means" not in row for row in several)
    assert kg.scenario_names(several[0]) == []
