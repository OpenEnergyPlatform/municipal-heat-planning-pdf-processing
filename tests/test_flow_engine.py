"""
The run does what the drawing of its flow says (owner decisions 2026-11-10
evening, "Freie Ablaufgrafik"; engine.py).

The promises, each with a case that breaks it by construction:

2. The run does the drawing: the search before the pieces beside shows its
   supply first, AND a box switched off asks nothing of its kind, AND a
   second search of 20 pieces shows at most 20 more after the first 50.
   A box that is off is not there for the check of the drawing, AND a
   condition about the answer reads the answer of its own item (nothing
   came back where no box of it asked), AND a round until the supply is
   used up ends after a turn that showed nothing of it.
3. Cutting: a new piece at every heading leaves no piece over two sections,
   AND every piece of a table shows its head, AND a piece over several
   passages goes out with a letter for each.
5. An own check refuses a quote of 15 characters, asks again with its
   sentence, leaves it unbacked and counts it under check:<name>, AND one
   of 25 characters holds, AND a quote outside the shown lines is refused
   still, with every box that can be off off.
6. Rounds: at most 2 asks no third, AND a round with neither a most nor a
   supply is refused, AND a new sentence from round 2 is asked with the
   sentences before.
7. A whole pass asks again only what is open, never what was read, and
   stops after its most.
"""
import copy

from docpipe.extraction import addressed, conditions, flow, units
from docpipe.extraction.addressed import Plan, Reader
from docpipe.extraction.pipeline import Source

from test_addressed import (ENERGY, SPEC, TABLE, TEXT, Model, in_order,
                            plan_of)
from docpipe.rules import step_kind


def default() -> list:
    return copy.deepcopy(flow.load(None).tree)


def node(drawing: list, ident: str) -> dict:
    return next(n for n, _ in flow.walk(drawing) if n.get("id") == ident)


def row(of, is_, op=None, value=None, no=False) -> dict:
    return conditions.one(of, is_, op, value, no)


class Boxed(Model):
    """A Model that keeps the box each request was asked by."""

    def asks(self, check: bool = True):
        made = super().asks(check)

        def wrap(ask):
            if ask is None:
                return None

            def asked(*args, **kw):
                kw = dict(kw)
                out = ask(*args, **kw)
                kind, payload, noted = self.calls[-1]
                self.calls[-1] = (kind, payload,
                                  {**noted, "box": addressed.asking_box()})
                return out
            return asked
        for name in ("find", "docfield", "coord", "list", "search", "follow",
                     "names", "check", "work", "phrase"):
            setattr(made, name, wrap(getattr(made, name)))
        return made


def read(drawing: list, model: Model, *sources, **kw) -> list:
    assert flow.problems(drawing) == [], flow.problems(drawing)
    reader = Reader(SPEC, model.asks(), in_order, flow=drawing, **kw)
    return reader(plan_of(*sources), [ENERGY])


MANY = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
               {"document_id": 7, "page": 4 + i}) for i in range(90)]
TABLE_FINDS = Model.DEFAULT["find"]


def finding_table(p, n):
    if p.get("passage", {}).get("kind") == "table":
        return {"found": [{"at": "3.2", "words": "1.200"}]}
    return {"found": []}


# -- 2. the run does the drawing ---------------------------------------------------

def carrier_requests(model: Model) -> list:
    return [(kind, noted.get("shows"), noted.get("box"))
            for kind, payload, noted in model.calls
            if noted.get("coordinate") == "carrier"
            and kind in ("coord", "phrase", "search")]


def test_the_default_drawing_asks_beside_before_the_search():
    model = Boxed(find=finding_table)
    read(default(), model, TEXT, TABLE, *MANY[:12])
    kinds = carrier_requests(model)
    assert kinds[0][0] == "coord"
    shows = [s for k, s, _ in kinds if k == "search"]
    assert shows[0] == "near" and "found" in shows


def test_the_search_before_the_pieces_beside_shows_its_supply_first():
    drawing = default()
    way = node(drawing, "search_way")
    steps = way["else"]
    by = {one["id"]: one for one in steps}
    near_state = {"id": "near_state", "box": "state",
                  "when": {"all": [row("coordinate", "state", "one_of",
                                       ["read", "unbacked"], True)]},
                  "set": {"mode": "by_supply"}}
    way["else"] = [by["search_sentence"], by["search_on"], by["near"],
                   by["beside_round"], near_state]
    model = Boxed(find=finding_table)
    read(drawing, model, TEXT, TABLE, *MANY[:12])
    shows = [s for k, s, _ in carrier_requests(model) if k == "search"]
    assert shows and shows[0] == "found"
    # the failure by construction: the default shows the pieces beside first
    model = Boxed(find=finding_table)
    read(default(), model, TEXT, TABLE, *MANY[:12])
    assert [s for k, s, _ in carrier_requests(model)
            if k == "search"][0] == "near"


def test_a_box_switched_off_asks_nothing_of_its_kind():
    drawing = default()
    node(drawing, "search_sentence")["off"] = True
    node(drawing, "search_anew")["off"] = True       # the new sentence of round 2 on
    node(drawing, "beside_round")["off"] = True
    model = Boxed(find=finding_table)
    read(drawing, model, TEXT, TABLE, *MANY[:12])
    asked = carrier_requests(model)
    assert not [one for one in asked if one[0] == "phrase"]
    assert not [one for one in asked if one[1] == "near"]
    assert [one for one in asked if one[1] == "found"]
    # the failure by construction: on, they ask
    model = Boxed(find=finding_table)
    read(default(), model, TEXT, TABLE, *MANY[:12])
    assert [one for one in carrier_requests(model) if one[0] == "phrase"]


def test_a_box_that_is_off_is_not_there_for_the_check_of_the_drawing():
    drawing = default()
    node(drawing, "beside")["off"] = True
    assert [p["id"] for p in flow.problems(drawing)] == ["beside_round"]
    drawing = default()
    node(drawing, "search")["off"] = True
    assert [p["id"] for p in flow.problems(drawing)] == ["search_round"]
    # the failure by construction: on, the run can do the drawing
    assert flow.problems(default()) == []


def passed(drawing: list, ident: str) -> list:
    """*drawing* with the box *ident* passed by a condition that does not
    hold where it stands."""
    node(drawing, ident)["when"] = {"all": [row(
        "coordinate", "state", "one_of", ["derived"])]}
    return drawing


def answer_stops(drawing: list) -> list:
    """*drawing* whose step after the own place stops where the request
    before it got no answer: the shipped flows search on since 2026-11-13,
    so the condition is put back here to read the answer it asks about."""
    node(drawing, "after_own_place")["if"][0]["when"]["any"].insert(
        0, {"of": "answer", "is": "answered", "not": True})
    return drawing


def test_a_condition_about_the_answer_reads_the_answer_of_its_own_item():
    model = Boxed(find=finding_table)
    claims = [c for r in read(passed(answer_stops(default()), "own_place"),
                              model, TEXT, TABLE) for c in r.claims]
    assert claims and not [n for _, _, n in model.calls
                           if n.get("box") == "own_place"]
    # nothing came back for the coordinate: it is left unanswered, never
    # searched by the answer of a box around it
    assert {c["carrier_state"] for c in claims} == {"unanswered"}
    assert not carrier_requests(model)
    # the failure by construction: asked, its answer leads into the search
    model = Boxed(find=finding_table)
    claims = [c for r in read(answer_stops(default()), model, TEXT, TABLE)
              for c in r.claims]
    assert "unanswered" not in {c["carrier_state"] for c in claims}
    assert [one for one in carrier_requests(model) if one[0] == "search"]


def test_a_round_until_the_supply_is_used_up_ends_when_a_turn_shows_none():
    model = Boxed(find=finding_table)
    claims = [c for r in read(passed(default(), "search"), model, TEXT,
                              TABLE, *MANY[:12]) for c in r.claims]
    assert not [one for one in carrier_requests(model) if one[2] == "search"]
    assert {c["carrier_state"] for c in claims} <= {"exhausted", "unstated",
                                                    "read", "unbacked"}
    # the failure by construction: asked, the search shows its supply
    model = Boxed(find=finding_table)
    read(default(), model, TEXT, TABLE, *MANY[:12])
    assert [one for one in carrier_requests(model) if one[2] == "search"]


def shown_by(model: Model, box: str, coordinate: str = "carrier") -> int:
    return sum(noted.get("chunks", 0) for kind, payload, noted in model.calls
               if kind == "search" and noted.get("box") == box
               and noted.get("coordinate") == coordinate
               and noted.get("value") == "R1")


def test_a_second_search_of_20_shows_at_most_20_more_after_the_first_50():
    drawing = default()
    on = node(drawing, "search_on")["if"][0]["steps"]
    state = on.pop()
    on += [{"id": "more_order", "box": "order", "own": {"pieces": 20}},
           {"id": "more_round", "round": {"supply": True},
            "stop": {"any": [row("coordinate", "state", "one_of", ["read"]),
                             row("coordinate", "state", "one_of",
                                 ["unbacked"])]},
            "steps": [{"id": "more_search", "box": "ask",
                       "preset": "search"}]},
           state]
    model = Boxed(find=finding_table)
    read(drawing, model, TEXT, TABLE, *MANY)
    first, more = shown_by(model, "search"), shown_by(model, "more_search")
    assert 40 <= first <= 50
    assert 0 < more <= 20
    # the failure by construction: without the second box, none more
    model = Boxed(find=finding_table)
    read(default(), model, TEXT, TABLE, *MANY)
    assert shown_by(model, "more_search") == 0


# -- 3. cutting ---------------------------------------------------------------------

SECTIONS = [Source("section", 20 + i, f"Satz eins {i}. Satz zwei {i}.",
                   {"document_id": 7, "page": 1 + i // 2,
                    "section_title": f"Kapitel {i}"}) for i in range(4)]
LONG = Source("table", 30, "Tabelle 9: Viele Zeilen\n| A | B |\n| --- | --- |\n"
              + "\n".join(f"| Zeile {i} | {i} |" for i in range(20)),
              {"document_id": 7, "page": 9})


def cut(sources, **settings) -> Plan:
    return Plan(7, list(sources), {}, cut=units.Cut(**settings))


def test_a_new_piece_at_every_heading_leaves_none_over_two_sections():
    heading = {"all": [row("line", "heading")]}
    plan = cut(SECTIONS, lines=100, across=True, new_piece=heading)
    assert plan.groups == []
    assert [c.owner for c in plan.chunks] == [s and (s.owner_kind,
                                                     s.owner_id)
                                              for s in SECTIONS]
    # the failure by construction: across without the condition
    plan = cut(SECTIONS, lines=100, across=True)
    assert len(plan.groups) == 1 and len(plan.groups[0]) == 4


def test_every_piece_of_a_table_shows_its_head():
    plan = cut([LONG], lines=8, new_piece={"all": [row("line", "role",
                                                       "one_of",
                                                       ["title"])]})
    pieces = [c for c in plan.chunks if c.owner == ("table", 30)]
    assert len(pieces) == 3
    head = set(plan.passages[("table", 30)].fixed)
    assert head and all(head <= set(c.shown) for c in pieces)
    # the failure by construction: the head not carried
    plan = cut([LONG], lines=8, table_head=False)
    pieces = [c for c in plan.chunks if c.owner == ("table", 30)]
    assert not all(head <= set(c.shown) for c in pieces)


def test_a_piece_over_several_passages_goes_out_with_a_letter_each():
    page = {"all": [row("line", "new_page")]}
    plan = cut(SECTIONS, lines=100, across=True, new_piece=page)
    assert [len(g) for g in plan.groups] == [2, 2]
    model = Boxed()
    reader = Reader(SPEC, model.asks(), in_order)
    reader(plan, [ENERGY])
    finds = model.of("find")
    assert len(finds) == 2
    for payload, _ in finds:
        assert "passage" not in payload
        assert sorted(payload["passages"]) == ["A", "B"]
        assert payload["passages"]["A"]["lines"][0].startswith("A1 ")
    # the failure by construction: a piece over two pages is cut there
    assert all(len({c.passage.page for c in g}) == 1 for g in plan.groups)


def test_the_plain_cut_is_the_cut_of_every_flow_before():
    for size in (1, 3, 8):
        plain = Plan(7, [TEXT, TABLE, LONG, *SECTIONS], {}, size)
        general = Plan(7, [TEXT, TABLE, LONG, *SECTIONS], {},
                       cut=units.Cut(lines=size, new_piece={"all": [
                           row("line", "lines_in_piece", "at_least",
                               10_000)]}))
        assert [(c.key, c.shown) for c in plain.chunks] \
            == [(c.key, c.shown) for c in general.chunks]


# -- 5. an own check -------------------------------------------------------------------

SHORT = Source("section", 40, "Erdgas: 300 MWh.", {"document_id": 7,
                                                   "page": 2})
LONGER = Source("section", 41, "Der Verbrauch an Erdgas betrug 300 MWh.",
                {"document_id": 7, "page": 2})
CHECK = {"id": "short_quote", "box": "check", "set": {
    "name": "kurzes Zitat",
    "refuse": {"all": [row("quote", "length", "less", 20)]},
    "sentence": "The quote is shorter than 20 characters; quote the whole "
                "line."}}


def checked(drawing: list) -> list:
    steps = node(drawing, "coordinate_way")["else"]
    at = steps.index(node(drawing, "own_place"))
    steps.insert(at + 1, copy.deepcopy(CHECK))
    assert flow.problems(drawing) == []
    return drawing


def what_at_line_1(p, n):
    if n.get("coordinate") == "what":
        return {"at": "1", "words": "Erdgas"}
    return {"at": 0}


def own_check_run(source) -> tuple:
    model = Boxed(find=lambda p, n: {"found": [{"at": "1", "words": "300"}]},
                  coord=what_at_line_1,
                  follow=lambda p, n: {"at": "1", "words": "Erdgas"}
                  if n.get("coordinate") == "what" else None)
    counts = addressed.Counts()
    reader = Reader(SPEC, model.asks(), in_order, flow=checked(default()))
    (claim,) = [c for r in reader(plan_of(source), [ENERGY], counts=counts)
                for c in r.claims]
    return claim, model, counts


def test_an_own_check_refuses_a_short_quote_and_counts_its_reason():
    claim, model, counts = own_check_run(SHORT)
    follows = [p for k, p, n in model.calls
               if k == "follow" and n.get("coordinate") == "what"]
    assert follows and "shorter than 20 characters" in str(
        follows[0]["what"])
    assert claim["what_state"] == "unbacked"
    assert counts.failed["check:kurzes Zitat"] == 2


def test_an_own_check_lets_a_long_enough_quote_hold():
    claim, model, counts = own_check_run(LONGER)
    assert claim["what_state"] == "read"
    assert "check:kurzes Zitat" not in counts.failed
    # the failure by construction: the same short line without the check
    model = Boxed(find=lambda p, n: {"found": [{"at": "1", "words": "300"}]},
                  coord=what_at_line_1)
    (claim,) = [c for r in Reader(SPEC, model.asks(), in_order)(
        plan_of(SHORT), [ENERGY]) for c in r.claims]
    assert claim["what_state"] == "read"


def test_a_quote_outside_the_shown_lines_is_refused_with_every_box_off():
    drawing = checked(default())
    for one, _ in flow.walk(drawing):
        if flow.kind_of(one) == "box" and step_kind(one) in (
                "phrase", "about", "check", "names", "works", "sentences",
                "compute"):
            one["off"] = True
    assert flow.problems(drawing) == []
    model = Boxed(find=lambda p, n: {"found": [{"at": "Z9", "words": "300"}]})
    counts = addressed.Counts()
    Reader(SPEC, model.asks(), in_order, flow=drawing)(
        plan_of(SHORT), [ENERGY], counts=counts)
    assert counts.failed[addressed.NOT_AN_ADDRESS] >= 1


# -- 6. rounds -------------------------------------------------------------------------

def test_a_round_of_at_most_2_asks_no_third():
    drawing = default()
    node(drawing, "search_round")["round"] = {"most": 2}
    model = Boxed(find=finding_table)
    read(drawing, model, TEXT, TABLE, *MANY)
    per_value = {}
    for kind, payload, noted in model.calls:
        if kind == "search" and noted.get("box") == "search":
            key = (noted.get("value"), noted.get("coordinate"))
            per_value[key] = per_value.get(key, 0) + 1
    assert per_value and max(per_value.values()) == 2
    # the failure by construction: until the supply is used up, more
    model = Boxed(find=finding_table)
    read(default(), model, TEXT, TABLE, *MANY)
    assert max(sum(1 for k, p, n in model.calls
                   if k == "search" and n.get("box") == "search"
                   and (n.get("value"), n.get("coordinate")) == key)
               for key in per_value) > 2


def test_a_round_without_a_most_and_without_a_supply_is_refused():
    drawing = default()
    node(drawing, "search_round")["round"] = {"supply": None}
    assert flow.problems(drawing)
    drawing = default()
    round_ = node(drawing, "search_round")
    round_["round"] = {"supply": True}
    round_["steps"] = [{"id": "lone", "box": "last_year"}]
    assert any("show the supply" in p["message"]
               for p in flow.problems(drawing))


def test_a_new_sentence_from_round_2_is_asked_with_the_sentences_before():
    drawing = default()
    on = node(drawing, "search_on")["if"][0]["steps"]
    order, round_, state = on
    on[:] = [{"id": "again", "round": {"most": 2},
              "stop": {"any": [row("coordinate", "state", "one_of",
                                   ["read", "unbacked"])]},
              "steps": [{"id": "again_sentence", "box": "ask",
                         "preset": "phrase", "set": {"anew": True}},
                        order, round_]},
             state]
    model = Boxed(find=finding_table,
                  phrase=lambda p, n: {"phrase": f"Satz {len(p.get('before') or [])}."})
    read(drawing, model, TEXT, TABLE, *MANY)
    again = [p for k, p, n in model.calls
             if k == "phrase" and n.get("box") == "again_sentence"]
    assert again and any(p.get("before") for p in again)
    assert all("before" not in p for k, p, n in model.calls
               if k == "phrase" and n.get("box") == "search_sentence")


# -- 7. a whole pass -------------------------------------------------------------------

def with_second_pass(most: int) -> list:
    drawing = default()
    values = node(drawing, "values")
    second = {"id": "again_pass", "round": {"most": most}, "steps": [{
        "id": "values_again", "each": "value", "order": "names_first",
        "steps": [{"id": "coordinates_again", "each": "coordinate",
                   "order": "groups",
                   "when": {"all": [row("coordinate", "state", "one_of",
                                        ["open"])]},
                   "steps": [
                       {"id": "again_order", "box": "order",
                        "own": {"pieces": 10}},
                       {"id": "again_round", "round": {"supply": True},
                        "stop": {"any": [row("coordinate", "state",
                                             "one_of",
                                             ["read", "unbacked"])]},
                        "steps": [{"id": "again_search", "box": "ask",
                                   "preset": "search"}]},
                       {"id": "again_state", "box": "state",
                        "when": {"all": [row("coordinate", "state",
                                             "one_of", ["read", "unbacked"],
                                             True)]}}]}]}]}
    drawing.insert(drawing.index(values) + 1, second)
    return drawing


def pass_run(most: int) -> tuple:
    model = Boxed(find=finding_table,
                  coord=lambda p, n: {"at": "2.2", "words": "MWh/a"}
                  if n.get("coordinate") == "unit" else {"at": 0})
    reads = read(with_second_pass(most), model, TEXT, TABLE, *MANY,
                 budget=5)
    claims = [c for r in reads for c in r.claims]
    again = [n for k, p, n in model.calls
             if k == "search" and n.get("box") == "again_search"]
    return claims, again


def test_a_whole_pass_asks_only_what_is_open_and_stops_after_its_most():
    claims, again = pass_run(1)
    assert again
    read_states = {(c["at"]["line"], name) for c in claims
                   for name in ("unit", "what", "year", "carrier")
                   if c.get(f"{name}_state") == "read"}
    assert read_states, "the first pass reads something"
    asked = {n.get("coordinate") for n in again}
    assert "unit" not in asked and asked <= {"year", "carrier"}
    shown = {}
    for n in again:
        key = (n.get("value"), n.get("coordinate"))
        shown[key] = shown.get(key, 0) + n.get("chunks", 0)
    assert max(shown.values()) <= 10
    # the failure by construction: a most of 2 shows more
    _claims, again = pass_run(2)
    shown2 = {}
    for n in again:
        key = (n.get("value"), n.get("coordinate"))
        shown2[key] = shown2.get(key, 0) + n.get("chunks", 0)
    assert max(shown2.values()) > 10
