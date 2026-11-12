"""The rules the area agents could not wire, wired (integration 2).

Each promise below is one sentence, each AND is its own test, and each has
a case that breaks it by construction.

about: the box that checks a find has its own step AND the asking box hands
it on, so the rule `about_no_reply` reads there.

field_text: a field of the whole document is built inside the box that asks
it, so the rule `field_text` is that box's own.

docfield: the finds of the parts of a window that were read count even where
another part was a hole.

flow.problems: three shares of 0 in a drawing are refused AND more chunks to
a request than letters are refused AND the standard drawing has neither.

resolve: empty words are refused whatever the rule says AND words not in the
line are refused only where `check_answer_in_quote` is on.

publication: the first work of a document is the publication itself where
`this_publication_first` is on, described as `publication_description`
says, AND a value read onto the first work is the publication's own only
there.

fetch: an ask for the next section brings in `fetch_next` sections AND the
cursor ends on the last of them AND past the end it is the end.

states: the states a dimension ends in after the gate, the combing and the
search come from `state_rules`.

takes_group: a field the spec says nothing of takes a group as the step
reads `default_takes_group`; a field the spec says it does not take, never.

surveyed: a pass that was not read completely writes nothing only where
`parameter_pass_all_or_nothing` is on AND a document read to its end is
skipped only where `rest_once_per_document` is on AND a document nothing
says was read is skipped only where `rest_without_trace` is skip.
"""
import copy
import types

import pytest

from docpipe import rules
from docpipe.extraction import (addressed, fields, flow, general, reading,
                                spec, surveyed, targets, topup_rest, units)
from docpipe.extraction.addressed import Names
from docpipe.extraction.engine import Doc, FieldItem, Scope
from docpipe.extraction.pipeline import Source

from test_addressed import ENERGY, TABLE, TEXT, TITLE, plan_of
from test_ruleset_flowing import coord_of, engine_of, node
import test_surveyed_passes as sp
from conftest import step_node


def default():
    return copy.deepcopy(flow.load(None).tree)


def at(kind, **values):
    return rules.in_step(rules.stepped(step_node(kind), values))


# -- about -------------------------------------------------------------------

def test_the_asking_box_hands_the_about_box_on_as_a_step_of_its_own():
    engine, _ = engine_of()
    drawing = engine.tree
    node(drawing, "about")["rules"] = {"about_no_reply": "keep"}
    keeper = engine.attached_of(node(drawing, "search"), "keep_find")
    assert keeper is node(drawing, "about")
    with at("search"), engine.step(keeper):
        assert rules.get("about_no_reply") == "keep"
    # by construction: the search step alone has the standard
    with at("search"):
        assert rules.get("about_no_reply") != "keep"


def test_a_question_with_no_about_box_after_it_has_no_about_step():
    engine, _ = engine_of()
    assert engine.attached_of(node(engine.tree, "finds"),
                              "keep_find") is None


# -- field_text --------------------------------------------------------------

def test_a_field_of_the_whole_document_is_built_in_the_box_that_asks():
    item = FieldItem("k", None, None, False, None, ENERGY)
    assert item.shown is None
    with at("docfield", field_text="whole"):
        whole = addressed.field_shown(item.parameter)
    with at("docfield", field_text="brief"):
        brief = addressed.field_shown(item.parameter)
    assert whole["means"] == ENERGY.description
    assert brief["means"] == (ENERGY.brief or ENERGY.description)


# -- docfield: the finds of a window with a hole ------------------------------

def window_scope(plan, item):
    chunks = list(plan.chunks[:2])
    supply = types.SimpleNamespace(take=lambda n: (False, list(chunks)),
                                   seen=set(), fetched=[])
    doc = Doc(plan, addressed.Counts(), [ENERGY])
    return Scope(None, True, doc=doc, plan=plan, field_item=item,
                 supply=supply)


def test_the_finds_of_a_window_count_where_another_part_was_a_hole(
        monkeypatch):
    plan = plan_of(TITLE, TEXT, TABLE)
    engine, reader = engine_of()
    found = addressed.Found(lines=[(addressed.Line(1, "x"), TEXT)],
                            words="x")
    item = FieldItem("k", {"name": "n", "means": "m"}, [], False, None,
                     ENERGY)
    box = node(engine.tree, "document_fields")
    reader.halves = lambda piece, depth: [piece[:1], piece[1:]] \
        if len(piece) > 1 else None

    def window(*parts):
        replies = iter(parts)
        monkeypatch.setattr(targets, "_gathered_once",
                            lambda *a: next(replies))
        item.found, item.lost = [], None
        scope = window_scope(plan, item)
        general.ask_step(engine, box, scope)
        return scope.get("answer")
    # the whole window did not fit: its first half is read, its second is
    # a hole
    answer = window(([], addressed.CUT, []), ([found], None, []),
                    ([], addressed.NO_ANSWER, []))
    assert item.found == [found] and item.lost == addressed.NO_ANSWER
    assert answer.answered is True
    # by construction: nothing read and a hole is no answer
    answer = window(([], addressed.CUT, []), ([], None, []),
                    ([], addressed.NO_ANSWER, []))
    assert item.found == [] and answer.answered is False


# -- flow.problems ------------------------------------------------------------

def test_three_shares_of_zero_and_too_many_chunks_are_refused_in_a_drawing():
    assert flow.problems(default()) == []
    drawing = default()
    node(drawing, "document_search_order")["rules"] = {
        "search_tables": 0, "search_figures": 0, "search_text": 0}
    said = [p["message"] for p in flow.problems(drawing)]
    assert any("shares of a search are 0" in m for m in said)
    # by construction: one share keeps the drawing sound
    node(drawing, "document_search_order")["rules"]["search_text"] = 1
    assert not [p for p in flow.problems(drawing) if "shares" in p["message"]]
    drawing = default()
    node(drawing, "search")["own"] = {
        "per_request": len(units.letters_others()) + 1}
    said = [p["message"] for p in flow.problems(drawing)]
    assert any("letters" in m for m in said)
    node(drawing, "search")["own"] = {"per_request": 5}
    assert not [p for p in flow.problems(drawing) if "letters" in p["message"]]


def test_the_steps_that_read_the_headings_are_those_the_flow_names():
    for kind in ("find", "coord", "phrase", "search", "work_coordinate",
                 "works", "last_year", "about"):
        assert kind in flow.BY_NAME["headings"].steps
    assert "work_coordinate" in flow.BY_NAME["list_meanings"].steps


# -- resolve ------------------------------------------------------------------

def resolved(words, at_="3", **values):
    plan = plan_of(TITLE, TEXT, TABLE)
    shown, _ = addressed.show_value(
        plan, {"at": {"owner": ["table", 3], "line": 3}, "value": 1})
    with rules.overlaid(**values):
        return addressed.resolve(shown, {"at": at_, "words": words},
                                 plan.passages)


def test_words_not_in_the_line_are_refused_only_where_the_rule_is_on():
    assert resolved("Zeppelin").why == addressed.WORDS_NOT_IN_LINE
    got = resolved("Zeppelin", check_answer_in_quote=False)
    assert got.why is None and got.words == "Zeppelin"


def test_empty_words_are_refused_whatever_the_rule_says():
    for on in (True, False):
        assert resolved("", check_answer_in_quote=on).why \
            == addressed.WORDS_NOT_IN_LINE


# -- publication --------------------------------------------------------------

def works_of(**values):
    reader = types.SimpleNamespace(works_field={"name": "work"},
                                   spec=types.SimpleNamespace(parameters=[]))
    plan = plan_of(TITLE, TEXT)
    plan.names.pop("work", None)
    with rules.overlaid(**values):
        addressed.Reader.lists_of(reader, plan)
    return plan.names["work"].entries


def test_the_first_work_is_the_publication_described_as_the_rule_says():
    first = works_of()[0]
    assert first.label == "this publication"
    assert first.name.startswith("this publication: ")
    assert works_of(publication_description="plain")[0].name \
        == "this publication"


def test_the_list_of_works_starts_empty_where_the_rule_is_off():
    assert works_of(this_publication_first=False) == []


def test_only_the_first_work_is_the_publications_own_where_the_rule_is_on():
    seen = []

    class Slot:
        options = [types.SimpleNamespace(uri=addressed.THIS_PUBLICATION,
                                         label="own"),
                   types.SimpleNamespace(uri=addressed.ANOTHER_WORK,
                                         label="other")]
        name = "work"

    def merged(rows, evidence, slot, answer, window=None, document=()):
        seen.append(answer["answers"]["r"]["value"])
        return {"failed": []}

    row = types.SimpleNamespace(label="r", claim={})
    works = Names("work", addressed.Entry("this publication", "x", 0, ""))
    got = types.SimpleNamespace(words="w", quote="q")
    old = addressed.merge_field
    addressed.merge_field = merged
    try:
        for first in (True, False):
            with rules.overlaid(this_publication_first=first):
                addressed.Reader.take_work(row, Slot, 1, got, [], ("own", 1),
                                           works)
    finally:
        addressed.merge_field = old
    assert seen == ["own", "other"]


# -- fetch --------------------------------------------------------------------

SECTIONS = [Source("section", i, f"S{i}\nText {i}", {}) for i in range(1, 6)]


def tools():
    return reading.Gathered(seen={("section", 1)},
                            cursor={"next": ("section", 1),
                                    "previous": ("section", 1)})


def test_an_ask_for_the_next_section_brings_in_as_many_as_the_rule_says():
    one = tools()
    assert one.fetch([{"get": "next"}], SECTIONS, {}, None)
    assert [m["text"] for m in one.context()["more"]] == [SECTIONS[1].text]
    with rules.overlaid(fetch_next=3):
        three = tools()
        assert three.fetch([{"get": "next"}], SECTIONS, {}, None)
        assert [m["text"] for m in three.context()["more"]] == [
            s.text for s in SECTIONS[1:4]]
        assert three.cursor["next"] == ("section", 4)


def test_the_next_ask_goes_on_from_the_last_section_and_ends_past_the_end():
    with rules.overlaid(fetch_next=3):
        three = tools()
        three.fetch([{"get": "next"}], SECTIONS, {}, None)
        assert three.fetch([{"get": "next"}], SECTIONS, {}, None)
        assert three.cursor["next"] == ("section", 5)
        assert not three.fetch([{"get": "next"}], SECTIONS, {}, None)
        assert three.missed == [{"get": "next", "why": reading.END}]


# -- states -------------------------------------------------------------------

def state_of(mode, rest=False):
    engine, _ = engine_of()
    # Another piece left, or the value's own piece the only one.
    plan = plan_of(TEXT, TABLE) if rest else plan_of(TABLE)
    coord = coord_of(plan)
    scope = Scope(None, True, doc=Doc(plan, addressed.Counts(), []),
                  plan=plan, coord=coord)
    engine.box_state({"id": "s", "box": "state", "set": {"mode": mode}},
                     scope)
    return coord.row.claim[f"{coord.slot.name}_state"]


def test_the_states_after_the_gate_the_combing_and_the_search_are_the_rules():
    assert state_of("out_of_slice") == fields.OUT_OF_SLICE
    assert state_of("unstated") == fields.SAID_UNSTATED
    assert state_of("by_supply", rest=True) == fields.EXHAUSTED
    assert state_of("by_supply", rest=False) == fields.SAID_UNSTATED
    table = {**rules.default()["state_rules"], "out_of_slice": "unanswered",
             "unstated_after_combing": "unbacked", "exhausted": "derived"}
    with rules.overlaid(state_rules=table):
        assert state_of("out_of_slice") == "unanswered"
        assert state_of("unstated") == "unbacked"
        assert state_of("by_supply", rest=True) == "derived"
        assert state_of("by_supply", rest=False) == "unbacked"


def test_a_state_the_rule_names_that_is_none_is_refused():
    table = {**rules.default()["state_rules"], "exhausted": "later"}
    with rules.overlaid(state_rules=table):
        with pytest.raises(rules.RuleError, match="later"):
            state_of("by_supply", rest=True)


# -- takes_group --------------------------------------------------------------

def test_a_field_takes_a_group_as_the_step_reads_the_rule_unless_spec_says():
    silent = types.SimpleNamespace(takes_group=None)
    no = types.SimpleNamespace(takes_group=False)
    yes = types.SimpleNamespace(takes_group=True)
    assert spec.group_taken(silent) is True
    with at("coord", default_takes_group=False):
        assert spec.group_taken(silent) is False
        assert spec.group_taken(yes) is True
    # by construction: the spec's own value never moves with the rule
    assert spec.group_taken(no) is False
    with at("coord", default_takes_group=True):
        assert spec.group_taken(no) is False


# -- surveyed -----------------------------------------------------------------

def test_a_pass_not_read_completely_writes_nothing_only_where_the_rule_is_on(
        tmp_path):
    for on in (True, False):
        folder = tmp_path / str(on)
        folder.mkdir()
        path = sp.started(folder, sp.stored_tuple())
        sp.write_survey(folder, answered=[(sp.ONE, {})])
        before = path.read_bytes()
        with rules.overlaid(parameter_pass_all_or_nothing=on):
            written, failed, _ = surveyed.append_unread(
                sp.DOC, f"{sp.NAME}.pdf", folder,
                sp.unread_deps([], note_429=True))
        if on:
            assert (written, failed) == (False, 1)
            assert path.read_bytes() == before
        else:
            assert failed == 0 and path.read_bytes() != before


def test_a_document_read_to_its_end_is_skipped_only_where_the_rule_is_on(
        tmp_path):
    sp.started(tmp_path, sp.stored_tuple(),
               producers=[{"pass": "harvest"}, {"pass": topup_rest.PASS}])
    sp.write_survey(tmp_path, answered=[(sp.ONE, {})])
    calls = []
    surveyed.append_unread(sp.DOC, f"{sp.NAME}.pdf", tmp_path,
                           sp.unread_deps(calls))
    assert calls == []
    with rules.overlaid(rest_once_per_document=False):
        surveyed.append_unread(sp.DOC, f"{sp.NAME}.pdf", tmp_path,
                               sp.unread_deps(calls))
    assert len(calls) == 1


def test_a_document_nothing_says_was_read_is_skipped_only_where_rule_says(
        tmp_path):
    sp.started(tmp_path, sp.stored_tuple())
    calls = []
    surveyed.append_unread(sp.DOC, f"{sp.NAME}.pdf", tmp_path,
                           sp.unread_deps(calls))
    assert calls == []
    with rules.overlaid(rest_without_trace="read_all"):
        surveyed.append_unread(sp.DOC, f"{sp.NAME}.pdf", tmp_path,
                               sp.unread_deps(calls))
    # by construction: every passage of the document is read
    assert [owners for _d, owners, _a in calls] == [
        [sp.ONE, sp.TWO, sp.THREE]]
