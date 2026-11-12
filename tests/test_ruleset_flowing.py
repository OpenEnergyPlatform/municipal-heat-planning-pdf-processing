"""
The rules of the flow's own running (`docpipe/ruleset/flowing.py`, owner
decision 2026-11-11).

The promise: the value of the rule decides, read at the time of use, and
today's standard gives today's result. Each case sets the rule at a step or
for the run and sees the code do the other thing, AND the standard does what
it did.

1. Every rule of this part stands in the default file with its standard,
   AND a number the steps take (`replies`, `follow_ups`, `list_meanings`) is
   a value of its own at each of the fourteen steps that ask the model, AND
   a box that asks nothing takes none.
2. The kinds of chunks a search shows come in the order of `supply_order`
   AND the standard shows requested chunks and neighbours together first,
   then the ranked ones; a round with a supply ends by `round_ends`; a
   request for chunks lapses with a find unless `fetch_after_found`.
3. The own chunk is out of the search unless `search_skips_own_piece` is
   off; a new sentence is written from `phrase_new_from_round`; the hole of
   a field names the passage `hole_passage` says; the years of the words of
   a settled year are all of them or the first (`settled_years_taken`).
4. What the document settles is the list `settled_fields` (a field added
   shows in the settings of every later request, one left out does not, a
   name that is no field is refused); coordinates come in `coordinate_order`;
   values in `names_first`; a frame side by side asks in one pool by
   `together_pooled`.
5. The document step reads the passages `include_kinds` and the pages
   `pages` name AND its own `title_page_lines` decides the title page (it
   did not, 10.4.2); the transcribe box can be off or asked only for the
   figures its condition holds for.
6. Every new property of a condition is true at one case and false at
   another; "open" is the states of `open_states`.
7. The rules that stood as settings of a box (`split_across`, ...) give the
   box its value where it has none of its own, AND a value set at the box
   wins.
8. `link_range_ends`, `hit_line_chars`, `plans_kept` are read where they
   are used.
"""
import copy
import time
import types

import pytest

from docpipe import rules
from docpipe.extraction import conditions, engine as engine_map, fields, flow
from docpipe.extraction import reading
from docpipe.extraction.addressed import Counts, Reader
from docpipe.extraction.engine import (Answer, CoordItem, Doc, Engine,
                                       FieldItem, Scope, SearchSupply, Stop,
                                       ValueItem)
from docpipe.extraction.pipeline import Batch, Row, Source, WorkItem
from docpipe.extraction.reading import Read
from docpipe.ruleset import flowing

from test_addressed import (ENERGY, SPEC, TABLE, TEXT, TITLE, Model,
                            plan_of, in_order)


def default() -> list:
    return copy.deepcopy(flow.load(None).tree)


def node(drawing: list, ident: str) -> dict:
    return next(n for n, _ in flow.walk(drawing) if n.get("id") == ident)


def at_step(kind: str, **values):
    return rules.in_step(rules.stepped({"id": "x", "box": kind}, values))


STANDARD = {
    "check_quote_shown": True, "check_answer_in_quote": True,
    "settled_years_taken": "all",
    "link_range_ends": True, "split_across": False,
    "split_table_head": True, "split_caption": True,
    "split_figure_numbers": True,
    "include_kinds": ["section", "table", "figure"], "pages": None,
    "plans_kept": 8, "search_list_factor_on": False,
    "search_rest_after": False, "docfield_title_page": True,
    "phrase_anew": False, "phrase_new_from_round": 2,
    "search_skips_own_piece": True, "fetch_after_found": False,
    "supply_order": ["fetched", "beside", "ranked"],
    "round_ends": "no_chunk_shown", "hole_passage": "first_passage",
    "coordinate_order": [], "names_first": True, "together_pooled": True,
    "settled_fields": ["settings", "base_year", "target_year"],
    "state_mode": "by_supply",
    "open_states": ["exhausted", "unanswered", "unbacked"],
    "hit_line_chars": 200, "this_publication_first": True,
    "publication_description": "with_title"}

ASKING = ("figures", "sentences", "works", "document_fields", "finds",
          "own_place", "quantity", "work", "search_sentence", "beside",
          "plan_years", "name", "about", "compute", "settled_list")
# The steps a profile brings itself stand in its own flow (owner decision
# 2026-11-12, profiles/<name>/blocks.py).
OWN_FLOW = {"works": "scenarios", "work": "scenarios", "name": "scenarios",
            "quantity": "kwp", "plan_years": "kwp"}


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


class Reading:
    """What `Engine` asks of a reader, answered from what a case gives."""

    def __init__(self, **more):
        self.spec = SPEC
        self.plan_fields = {}
        self.frame_slots = []
        self.numbers = flow.default()
        self.budget, self.per_request = 50, 5
        self.shares = {"table": 20, "figure": 15, "section": 15}
        self.fetched = []
        self.rounds = []
        self.groups = []
        self.__dict__.update(more)

    def listed(self, parameter):
        return None

    def each(self, jobs, run):
        self.groups.append(list(jobs))
        return [run(job) for job in jobs]

    def context(self, document_id):
        return {}


def engine_of(**more) -> tuple:
    reader = Reading(**more)
    return Engine(reader, default()), reader


# -- 1. the rules stand, the numbers belong to every step that asks --

def test_every_rule_stands_in_the_default_file_with_its_standard():
    assert {r.name for r in flowing.RULES} == set(STANDARD)
    for name, value in STANDARD.items():
        assert rules.get(name) == value, name
    # the failure by construction: a rule the default file leaves out is
    # no rule of the run
    assert "no_such_rule_here" not in rules.BY_NAME


def test_a_rule_names_the_steps_that_read_it_and_a_step_may_set_it():
    drawing = default()
    node(drawing, "pieces")["rules"] = {"split_across": True}
    assert flow.problems(drawing) == []
    # a box that does not read it refuses it, with its reason
    node(drawing, "own_place")["rules"] = {"split_across": True}
    said = [p["message"] for p in flow.problems(drawing)]
    assert any("is not read here" in m for m in said), said


@pytest.mark.parametrize("ident", ASKING)
def test_each_step_that_asks_takes_its_own_replies_follow_ups_meanings(
        ident, monkeypatch):
    from docpipe.profile import load_profile
    profile = load_profile(OWN_FLOW[ident]) if ident in OWN_FLOW else None
    if profile is not None:
        # the run of a profile reads its own flow
        monkeypatch.setenv("DOCPIPE_PROFILE", profile.name)

    def default():
        return copy.deepcopy(flow.load(profile).tree)
    drawing = default()
    node(drawing, ident)["rules"] = {"follow_ups": 3, "replies": 5,
                                     "list_meanings": 7}
    assert flow.problems(drawing, profile=profile) == []
    drawing = default()
    box = node(drawing, ident)
    own = {setting.key: 2 for setting in
           flow.blocks.LIBRARY[box["box"]].settings
           if setting.key in ("follow_ups", "replies", "list_meanings")}
    assert set(own) == {"follow_ups", "replies", "list_meanings"}
    box["own"] = own
    assert flow.problems(drawing, profile=profile) == []
    engine = Engine(Reading(), drawing)
    assert engine.follow_ups_of(box) == 2
    assert engine.number(box, "replies") == 2


def test_a_box_that_asks_nothing_takes_no_number_of_its_own():
    drawing = default()
    node(drawing, "write")["rules"] = {"follow_ups": 3}
    assert any("is not read here" in p["message"]
               for p in flow.problems(drawing))


# -- 2. the supply of a search --

class Piece:
    def __init__(self, index: int):
        self.key = ("section", 1, index)


def chunk(index: int):
    return Piece(index)


def supply_of():
    near, got, ranked = chunk(1), chunk(2), [chunk(3), chunk(4), chunk(5)]
    supply = SearchSupply([near], lambda: list(ranked), "near")
    supply.fetched = [got]
    return supply, near, got, ranked


def test_the_standard_shows_what_was_asked_for_and_the_neighbours_first():
    supply, near, got, ranked = supply_of()
    batch, label = supply.take(2, set())
    assert batch == [got, near] and label == "near"
    batch, label = supply.take(2, {c.key for c in batch})
    assert batch == ranked[:2] and label == "near"


def test_the_order_of_the_rule_decides_what_a_search_shows_first():
    supply, near, got, ranked = supply_of()
    with rules.overlaid(supply_order=["ranked", "fetched", "beside"]):
        batch, label = supply.take(2, set())
        assert batch == ranked[:2]
        # what was asked for was not used up and comes later
        assert supply.fetched == [got]
    supply, near, got, ranked = supply_of()
    with rules.overlaid(supply_order=["ranked"]):
        assert supply.take(5, set())[0] == ranked
        assert supply.take(5, {c.key for c in ranked})[0] == []


def test_a_kind_the_order_leaves_out_is_never_shown():
    supply, near, got, ranked = supply_of()
    with rules.overlaid(supply_order=["beside", "ranked"]):
        batch, _ = supply.take(5, set())
        assert batch == [near] and got not in batch


class Turns:
    """The steps of a round: a turn draws chunks, or reaches no question."""

    def __init__(self, plan: str):
        self.plan, self.turns = plan, 0

    def __call__(self, steps, scope):
        self.turns += 1
        if self.plan[self.turns - 1] == "d":
            scope.drew()
        elif self.plan[self.turns - 1] == "u":
            scope.used_up()


def round_turns(plan: str, **spec) -> int:
    engine, _ = engine_of()
    turns = Turns(plan)
    engine.run_steps = turns
    scope = Scope(None, True)
    engine.round({"id": "r", "round": spec, "steps": []}, scope)
    return turns.turns


def test_a_round_ends_after_a_turn_without_a_chunk_by_default():
    assert round_turns("dd-dd", supply=True, most=5) == 3
    # the failure by construction: the other choice goes on
    with rules.overlaid(round_ends="supply_used_up"):
        assert round_turns("dd-dd", supply=True, most=5) == 5


def test_a_round_ends_where_its_supply_is_used_up_in_both_choices():
    with rules.overlaid(round_ends="supply_used_up"):
        assert round_turns("ddu-d", supply=True, most=5) == 3


def test_a_round_without_a_most_cannot_run_for_ever():
    with rules.overlaid(round_ends="supply_used_up"):
        assert round_turns("d-", supply=True) == 2


def test_a_value_of_a_step_decides_where_the_round_ends():
    engine, _ = engine_of()
    turns = Turns("dd-dd")
    engine.run_steps = turns
    frame = {"id": "r", "round": {"supply": True, "most": 5},
             "rules": {"round_ends": "supply_used_up"}, "steps": []}
    assert flow.problems([frame]) != []          # not a drawing of its own
    assert [p for p in flow.problems(default())] == []
    with engine.step(frame):
        engine.round(frame, Scope(None, True))
    assert turns.turns == 5


# -- 3. the places a search and a settling name --

def coord_of(plan, owner=("table", 3), line=4):
    claim = {"value": 1200, "quote": "Rathaus 1.200",
             "at": {"owner": list(owner), "line": line}}
    read = Read(Batch(7, ENERGY, [WorkItem(7, ENERGY, TABLE)], spec=SPEC),
                [claim])
    slot = next(s for s in fields.axis_slots(ENERGY) if s.name == "year")
    return CoordItem(read, Row("1", 0, claim), slot, None, [], lambda r: r)


def test_the_own_chunk_of_a_value_is_left_out_of_every_search():
    plan = plan_of(TEXT, TABLE)
    coord = coord_of(plan)
    Engine.locate(coord, plan)
    assert coord.seen == {coord.chunk.key}
    with rules.overlaid(search_skips_own_piece=False):
        other = coord_of(plan)
        Engine.locate(other, plan)
        assert other.chunk is not None and other.seen == set()


def stubbed_search(**more):
    engine, reader = engine_of(**more)
    plan = plan_of(TEXT, TABLE)
    reader.coord_payload = lambda *a: (None, {}, {})
    reader.search_round = lambda *a: ([], [object()], [{"get": "next"}])
    reader.fetch = lambda plan, more, batch, seen, numbers: ["asked"]
    coord = coord_of(plan)
    doc = Doc(plan, Counts(), [ENERGY])
    supply = SearchSupply([], lambda: list(plan.chunks), "found")
    scope = Scope(None, True, doc=doc, plan=plan).child(
        True, coord=coord, supply=supply)
    return engine, scope, supply


def test_an_answer_that_found_a_value_drops_the_chunks_it_asked_for():
    engine, scope, supply = stubbed_search()
    engine.box_search(node(engine.tree, "search"), scope)
    assert supply.fetched == []


def test_with_the_rule_on_the_chunks_it_asked_for_are_fetched_anyway():
    engine, scope, supply = stubbed_search()
    with rules.overlaid(fetch_after_found=True):
        engine.box_search(node(engine.tree, "search"), scope)
    assert supply.fetched == ["asked"]


def test_a_new_sentence_is_written_from_the_round_the_rule_names():
    seen = []

    def sentence(plan, read, row, slot, counts, before=None):
        seen.append(before)
        return f"s{len(seen)}"
    box = {"id": "p", "box": "phrase", "set": {"anew": True}}
    results = {}
    for start in (2, 3):
        seen.clear()
        engine, reader = engine_of(search_sentence=sentence)
        plan = plan_of(TEXT)
        coord = coord_of(plan)
        coord.sentences = ["first"]
        scope = Scope(None, True, doc=Doc(plan, Counts(), [ENERGY]),
                      plan=plan).child(True, coord=coord, round=2)
        with rules.overlaid(phrase_new_from_round=start):
            engine.box_phrase(box, scope)
        results[start] = seen[0]
    assert results[2] == ["first"] and results[3] is None


def test_the_hole_of_a_field_names_the_passage_the_rule_says():
    plan = plan_of(TITLE, TEXT, TABLE)
    item = FieldItem("k", {}, [], first_source=TABLE)
    names = {}
    for where in ("first_passage", "last_passage", "first_asked"):
        with rules.overlaid(hole_passage=where):
            names[where] = Engine.hole_source(plan, item)
    assert names == {"first_passage": TITLE, "last_passage": TABLE,
                     "first_asked": TABLE}
    with rules.overlaid(hole_passage="first_asked"):
        none_asked = FieldItem("k", {}, [])
        assert Engine.hole_source(plan, none_asked) is TITLE


def year_item(words: str):
    got = types.SimpleNamespace(
        words=words, quote=words,
        source=types.SimpleNamespace(owner_kind="section", owner_id=2))
    slot = next(s for s in fields.axis_slots(ENERGY) if s.name == "year")
    item = FieldItem("base_year", {}, [], settled={"_year": slot,
                                                   "_state": "base"})
    item.found = [got]
    return item


def settled_years(words: str, **values) -> list:
    engine, _ = engine_of()
    plan = plan_of(TEXT)
    scope = Scope(None, True, doc=Doc(plan, Counts(), []), plan=plan) \
        .child(True, field_item=year_item(words))
    with rules.overlaid(**values):
        engine.box_settle({"id": "s", "box": "settle"}, scope)
    return [b["year"] for b in plan.bases]


def test_every_year_of_the_words_is_settled_or_only_the_first():
    assert settled_years("2020 und 2019") == [2020, 2019]
    assert settled_years("2020 und 2019", settled_years_taken="first") \
        == [2020]


# -- 4. what is settled, the order, the pool --

def settled_names(**values) -> list:
    engine, reader = engine_of(plan_fields={
        "settings": {"name": "Festlegungen", "means": "m"},
        "base_year": {"name": "Basisjahr", "means": "m"},
        "target_year": {"name": "Zieljahr", "means": "m"}},
        frame_slots=[next(s for s in fields.axis_slots(ENERGY)
                          if s.name == "year")])
    plan = plan_of(TEXT)
    scope = Scope(None, True, doc=Doc(plan, Counts(), []), plan=plan)
    with rules.overlaid(**values):
        return [one["field_item"].key for one in engine.items(
            {"id": "plan", "each": "settled"}, scope)]


def test_the_document_settles_what_the_rule_lists_in_its_order():
    assert settled_names() == ["settings", "base_year", "target_year"]
    assert settled_names(settled_fields=["target_year", "settings"]) \
        == ["target_year", "settings"]


def test_a_field_added_is_asked_before_the_reading_and_kept_in_the_settings():
    assert settled_names(settled_fields=["settings", "energy"]) \
        == ["settings", "energy"]
    engine, _ = engine_of()
    plan = plan_of(TEXT)
    line = plan.passages[("section", 2)].lines[0]
    item = FieldItem("energy", {}, [], settled={"_field": True})
    item.found = [types.SimpleNamespace(lines=[(line, TEXT)])]
    scope = Scope(None, True, doc=Doc(plan, Counts(), []), plan=plan) \
        .child(True, field_item=item)
    engine.box_settle({"id": "s", "box": "settle"}, scope)
    assert [one for one, _ in plan.settings] == [line]
    # the failure by construction: a field left out shows nothing
    assert plan_of(TEXT).settings == []


def test_a_name_that_is_no_field_is_refused_with_its_reason():
    with pytest.raises(Stop, match="no_such_field"):
        settled_names(settled_fields=["settings", "no_such_field"])


def coordinate_names(order: list) -> list:
    engine, reader = engine_of()
    plan = plan_of(TEXT)
    read = Read(Batch(7, ENERGY, [], spec=SPEC), [])
    row = Row("1", 0, {})
    seen = []
    engine.run_steps = lambda steps, scope: seen.append(
        scope.get("coord").slot.name)
    scope = Scope(None, True, doc=Doc(plan, Counts(), [ENERGY]),
                  plan=plan).child(True, value=ValueItem(read, row, [row],
                                                         lambda r: r))
    with rules.overlaid(coordinate_order=order):
        engine.each_coordinate({"id": "c", "each": "coordinate",
                                "steps": []}, scope)
    return seen


def test_the_dimensions_come_in_the_order_the_rule_lists_first():
    standard = coordinate_names([])
    assert standard[:2] == ["unit", "what"] and "carrier" in standard
    got = coordinate_names(["carrier", "year"])
    assert got[:2] == ["carrier", "year"]
    assert sorted(got) == sorted(standard)
    assert coordinate_names(["nothing_of_this_name"]) == standard


def values_in_order(**rule_values) -> list:
    engine, reader = engine_of()
    plan = plan_of(TEXT)
    names = types.SimpleNamespace(uri="n", merged="scenario",
                                  is_numeric=False)
    plain = types.SimpleNamespace(uri="p", merged=None, is_numeric=False)
    reads = [Read(Batch(7, plain, [], spec=SPEC), [{"id": "plain"}]),
             Read(Batch(7, names, [], spec=SPEC), [{"id": "named"}])]
    doc = Doc(plan, Counts(), [])
    doc.find_reads = reads
    seen = []
    engine.run_steps = lambda steps, scope: seen.append(
        scope.get("value").row.claim["id"])
    saved = (engine_map.slots_of, engine_map.mark_unanswered)
    engine_map.slots_of = lambda spec, parameter: []
    engine_map.mark_unanswered = lambda rows, slots: 0
    try:
        with rules.overlaid(**rule_values):
            engine.each_value({"id": "v", "each": "value", "steps": []},
                              Scope(None, True, doc=doc, plan=plan))
    finally:
        engine_map.slots_of, engine_map.mark_unanswered = saved
    return seen


def test_the_values_that_name_a_scenario_come_first_unless_the_rule_is_off():
    assert values_in_order() == ["named", "plain"]
    assert values_in_order(names_first=False) == ["plain", "named"]


def pools(**rule_values) -> list:
    engine, reader = engine_of()
    plan = plan_of(TEXT, TABLE)
    outer = {"id": "o", "each": "field", "which": "pieces",
             "together": True, "steps": [
                 {"id": "i", "each": "piece", "together": True,
                  "steps": []}]}
    doc = Doc(plan, Counts(), [ENERGY])
    engine.run_steps = lambda steps, scope: None
    with rules.overlaid(**rule_values):
        engine.each(outer, Scope(None, True, doc=doc, plan=plan))
    return reader.groups


def test_a_frame_side_by_side_in_another_asks_in_one_pool_or_two_steps():
    one = pools()
    assert len(one) == 1 and all(isinstance(j, Scope) for j in one[0])
    apart = pools(together_pooled=False)
    # the outer items side by side, the inner ones in a run of their own
    assert len(apart) == 1 and all(isinstance(j, list) for j in apart[0])
    assert sum(len(j) for j in apart[0]) == len(one[0])


# -- 5. the document step and the transcribe box --

FIGURE_A = Source("figure", 5, "Abbildung 3: Bedarf",
                  {"document_id": 7, "page": 4})
FIGURE_B = Source("figure", 6, "Abbildung 4: Anteil",
                  {"document_id": 7, "page": 9}, image_path="x.png")


def planned(drawing=None, sources=None, transcripts=None, **values):
    reader = Reader(SPEC, Model().asks(), in_order, flow=drawing)
    with rules.overlaid(**values):
        plan, _ = reader.engine.plan(7, sources or [TITLE, TEXT, TABLE,
                                                    FIGURE_A], transcripts)
    return plan


def test_the_document_step_reads_the_kinds_of_passages_the_rule_names():
    assert {k for k, _ in planned().passages} == {"section", "table",
                                                  "figure"}
    drawing = default()
    node(drawing, "document")["rules"] = {"include_kinds": ["table"]}
    assert flow.problems(drawing) == []
    assert {k for k, _ in planned(drawing).passages} == {"table"}
    with pytest.raises(Exception):
        rules.checked("test", "include_kinds", [])


def test_the_document_step_reads_the_pages_the_rule_names():
    drawing = default()
    node(drawing, "document")["rules"] = {"pages": [2, 3]}
    got = planned(drawing)
    assert {o for _, o in got.passages} == {2, 3}
    assert {o for _, o in planned().passages} == {1, 2, 3, 5}


def test_a_figure_left_out_is_not_transcribed():
    asked = []

    def transcripts(document_id, figures, each):
        asked.append([f.owner_id for f in figures])
        return {}, 0
    drawing = default()
    node(drawing, "document")["rules"] = {"include_kinds": ["section",
                                                             "table"]}
    planned(drawing, transcripts=transcripts)
    assert asked == []
    planned(transcripts=transcripts)
    assert asked == [[5]]


def test_the_title_page_lines_of_the_document_box_decide_the_title_page():
    standard = planned(sources=[TITLE, TEXT, TABLE])
    assert len(standard.title_page) == 2
    for how in ("own", "rules"):
        drawing = default()
        node(drawing, "document")[how] = {"title_page_lines": 1}
        assert flow.problems(drawing) == []
        assert len(planned(drawing, [TITLE, TEXT, TABLE]).title_page) == 1, \
            how
    # a frame's value reaches the box in it as well
    drawing = default()
    node(drawing, "document")["rules"] = {"title_page_also": 3}
    assert flow.problems(drawing) == []


def transcribed(drawing=None) -> list:
    asked = []

    def transcripts(document_id, figures, each):
        asked.append(sorted(f.owner_id for f in figures))
        return {}, 0
    planned(drawing, [TITLE, TEXT, FIGURE_A, FIGURE_B],
            transcripts=transcripts)
    return asked


def test_the_transcribe_box_can_be_switched_off():
    assert transcribed() == [[5, 6]]
    drawing = default()
    node(drawing, "figures")["off"] = True
    assert flow.problems(drawing) == []
    assert transcribed(drawing) == []


def test_the_transcribe_box_asks_only_the_figures_its_condition_holds_for():
    drawing = default()
    node(drawing, "figures")["when"] = {"all": [
        conditions.one("figure", "page", "at_least", 5)]}
    assert flow.problems(drawing) == []
    assert transcribed(drawing) == [[6]]
    node(drawing, "figures")["when"] = {"all": [
        conditions.one("figure", "has_image")]}
    assert transcribed(drawing) == [[6]]
    node(drawing, "figures")["when"] = {"all": [
        conditions.one("figure", "description", "contains", "Anteil")]}
    assert transcribed(drawing) == [[6]]


def test_the_transcribe_condition_knows_the_figure_and_nothing_else():
    drawing = default()
    node(drawing, "figures")["when"] = {"all": [
        conditions.one("field", "numbers")]}
    assert flow.problems(drawing) != []
    node(drawing, "own_place")["when"] = {"all": [
        conditions.one("figure", "has_image")]}
    node(drawing, "figures")["when"] = {"all": [
        conditions.one("figure", "has_image")]}
    assert [p for p in flow.problems(drawing)
            if p["id"] == "figures"] == []
    assert [p for p in flow.problems(drawing)
            if p["id"] == "own_place"] != []


def test_the_size_of_a_figure_s_image_is_its_own(tmp_path):
    pil = pytest.importorskip("PIL.Image")
    path = tmp_path / "f.png"
    pil.new("RGB", (30, 20)).save(path)
    figure = Source("figure", 7, "d", {"page": 1}, image_path=str(path))
    facts = Engine.figure_facts(figure)
    assert facts.get("figure", "image_width") == 30
    assert facts.get("figure", "image_height") == 20
    assert Engine.figure_facts(FIGURE_A).get("figure", "image_width") == 0


# -- 6. the properties of a condition --

def scope_of(**more) -> tuple:
    german = Source("section", 2, "Der Verbrauch der Stadt ist nicht mit "
                    "dem Plan von 2019 zu vergleichen und wird sinken.",
                    {"page": 2})
    plan = plan_of(TITLE, german, TABLE)
    engine, reader = engine_of(context=lambda document_id: {
        "name": more.pop("title", "Musterstadt")})
    claim = {"value": 1200, "quote": "Rathaus 1.200",
             "value_raw": "1.200",
             "at": {"owner": ["table", 3], "line": 4}}
    read = Read(Batch(7, ENERGY, [WorkItem(7, ENERGY, TABLE)], spec=SPEC),
                [claim])
    doc = Doc(plan, Counts(), [ENERGY])
    doc.find_reads = [read]
    row = Row("1", 0, claim)
    coord = CoordItem(read, row, next(s for s in fields.axis_slots(ENERGY)
                                      if s.name == "year"), None, [],
                      lambda r: r)
    scope = Scope(None, True, doc=doc, plan=plan).child(
        True, parameter=ENERGY, value=ValueItem(read, row, [row],
                                                lambda r: r)).child(
        True, coord=coord, chunk=plan.chunk_of(("table", 3), 1, True),
        **more)
    scope.owner().values["answer"] = Answer(
        True, 1, False, False, "1.200", "Rathaus 1.200", follow_ups=2,
        refusal="not_an_address")
    return engine, scope, doc


def holds(of, is_, op=None, value=None, **more) -> bool:
    engine, scope, doc = scope_of()
    for key, number in more.items():
        setattr(doc, key, number)
    return conditions.holds({"all": [conditions.one(of, is_, op, value)]},
                            engine.facts(scope))


CASES = [
    (("field", "unit", "is", "OEO_00050008"), True),
    (("field", "unit", "is", "MWh"), False),
    (("field", "kind", "one_of", ["float"]), True),
    (("field", "kind", "one_of", ["text", "category"]), False),
    (("field", "rows", "is", 1), True),
    (("field", "rows", "is", 0), False),
    (("value", "in_table"), True),
    (("value", "in_text"), False),
    (("value", "number", "more", 1000), True),
    (("value", "number", "less", 1000), False),
    (("value", "quote", "contains", "Rathaus"), True),
    (("value", "quote", "contains", "Schule"), False),
    (("chunk", "kind", "one_of", ["table"]), True),
    (("chunk", "kind", "one_of", ["section", "figure"]), False),
    (("answer", "follow_ups_used", "at_least", 2), True),
    (("answer", "follow_ups_used", "is", 0), False),
    (("answer", "refusal", "one_of", ["not_an_address"]), True),
    (("answer", "refusal", "one_of", ["none", "unbacked"]), False),
    (("document", "language", "one_of", ["de"]), True),
    (("document", "language", "one_of", ["en"]), False),
    (("document", "pages", "is", 3), True),
    (("document", "pages", "more", 3), False),
    (("document", "title", "contains", "muster"), True),
    (("document", "title", "contains", "Dorf"), False),
    (("document", "requests", "is", 0), True),
    (("document", "requests", "more", 0), False),
    (("document", "seconds", "less", 50), True),
    (("document", "seconds", "more", 50), False),
]


@pytest.mark.parametrize("row,expected", CASES)
def test_every_new_property_is_true_at_one_case_and_false_at_another(
        row, expected):
    assert holds(*row) is expected


def test_the_properties_that_count_follow_what_the_run_did():
    assert holds("document", "requests", "is", 3) is False
    engine, scope, doc = scope_of()
    doc.counts.ask("find", 3)
    assert conditions.holds({"all": [conditions.one(
        "document", "requests", "is", 3)]}, engine.facts(scope))
    doc.started -= 100
    assert conditions.holds({"all": [conditions.one(
        "document", "seconds", "more", 50)]}, engine.facts(scope))
    assert engine_map.language_of(["The plan and the rest of this report "
                                   "is for the city"]) == "en"
    assert engine_map.language_of(["1 2 3"]) == "other"


def test_a_question_s_own_counts_say_what_it_came_to_and_join_the_document_s():
    engine, _ = engine_of()
    doc = Doc(plan_of(TEXT), Counts(), [])
    doc.counts.ask("find", 2)
    with engine.counted(doc) as part:
        part.ask("follow")
        part.fail("not_an_address")
        part.fail("check:short")
        assert doc.counts.asked["follow"] == 0
    assert engine.came_to(part) == {"follow_ups": 1,
                                    "refusal": "not_an_address"}
    assert doc.counts.asked["follow"] == 1 and doc.counts.asked["find"] == 2
    assert doc.counts.failed["not_an_address"] == 1
    assert engine_map.refusal_of({"check:x": 2, "unbacked": 1}) \
        == "own_check"
    assert engine_map.refusal_of({"queer": 1}) == "other"
    assert engine_map.refusal_of({}) == "none"


def facts_of_state(state) -> bool:
    row = conditions.one("coordinate", "state", "one_of", ["open"])
    facts = conditions.Facts(lambda subject, prop: state)
    return conditions.holds({"all": [row]}, facts)


def test_open_is_the_states_the_rule_names():
    assert facts_of_state("unanswered") and facts_of_state("unbacked")
    assert not facts_of_state("read") and not facts_of_state("derived")
    with rules.overlaid(open_states=["exhausted"]):
        assert not facts_of_state("unanswered")
        assert facts_of_state("exhausted")
    with at_step("coord", open_states=["read"]):
        assert facts_of_state("read")


# -- 7. the settings of a box that stand as rules --

SETTINGS = [("split", "across", "split_across", True),
            ("split", "table_head", "split_table_head", False),
            ("split", "caption", "split_caption", False),
            ("split", "figure_numbers", "split_figure_numbers", False),
            ("order", "list_factor", "search_list_factor_on", True),
            ("order", "rest_after", "search_rest_after", True),
            ("phrase", "anew", "phrase_anew", True),
            ("docfield", "title_page", "docfield_title_page", False),
            ("state", "mode", "state_mode", "unstated")]


@pytest.mark.parametrize("kind,key,rule,other", SETTINGS)
def test_a_box_without_a_value_of_its_own_takes_the_rule(kind, key, rule,
                                                         other):
    box = {"id": "b", "box": kind}
    setting = next(s for s in flow.blocks.LIBRARY[kind].settings
                   if s.key == key)
    assert setting.rule == rule
    assert Engine.setting(box, key) == setting.default == STANDARD[rule]
    with at_step(kind, **{rule: other}):
        assert Engine.setting(box, key) == other
        # a value of the box itself wins over the rule
        own = {**box, "set": {key: setting.default}}
        assert Engine.setting(own, key) == setting.default


def test_a_frame_s_value_of_such_a_rule_reaches_the_box_in_it():
    frame = {"id": "f", "each": "coordinate", "rules": {
        "state_mode": "out_of_slice"}}
    with rules.in_step(rules.stepped(frame, Engine.own_values(frame))):
        assert Engine.setting({"id": "b", "box": "state"}, "mode") \
            == "out_of_slice"


# -- 8. the rest --

def range_rows():
    options = [types.SimpleNamespace(uri=fields.RANGE_LOW),
               types.SimpleNamespace(uri=fields.RANGE_HIGH)]
    slot = types.SimpleNamespace(name="span", is_closed=True,
                                 options=options)
    rows = [Row("1", 0, {"span": fields.RANGE_LOW, "span_state": "read",
                         "value": 1, "quote": "von 1 bis 5"}),
            Row("2", 0, {"span": fields.RANGE_HIGH, "span_state": "read",
                         "value": 5, "quote": "von 1 bis 5"})]
    return rows, [slot]


def test_the_two_ends_of_a_range_are_linked_unless_the_rule_is_off():
    rows, slots = range_rows()
    assert reading.link_ranges(rows, slots) == 1
    assert rows[0].claim[fields.RANGE] == [1, 5]
    rows, slots = range_rows()
    with rules.overlaid(link_range_ends=False):
        assert reading.link_ranges(rows, slots) == 0
    assert fields.RANGE not in rows[0].claim
    rows, slots = range_rows()
    with at_step("each value", link_range_ends=False):
        assert reading.link_ranges(rows, slots) == 0


def test_a_hit_list_shows_the_first_line_up_to_the_rule():
    long = Source("section", 9, "Titel\n" + "x" * 500, {"page": 1})
    assert len(reading.first_line(long)) == 200
    with at_step("compute", hit_line_chars=10):
        assert len(reading.first_line(long)) == 10


def test_a_pass_keeps_as_many_plans_as_the_rule_says():
    from docpipe.extraction.surveyed import SurveyedHarvest
    model = Model()

    def kept(most: int) -> int:
        reader = Reader(SPEC, model.asks(), in_order)
        harvest = SurveyedHarvest(SPEC, lambda spec: reader,
                                  lambda document_id: [TEXT, TABLE])
        with rules.overlaid(plans_kept=most):
            for document_id in range(5):
                harvest.plan_of(document_id)
        return len(harvest._plans)
    assert kept(2) == 2 and kept(8) == 5


def test_the_value_of_a_rule_is_checked_against_its_bounds():
    for name, bad in (("plans_kept", 0), ("phrase_new_from_round", 0),
                      ("hit_line_chars", 0), ("round_ends", "never"),
                      ("hole_passage", "any"), ("supply_order", ["x"]),
                      ("pages", [3, 2]), ("open_states", ["lost"])):
        assert rules.problem(name, bad) is not None, name
