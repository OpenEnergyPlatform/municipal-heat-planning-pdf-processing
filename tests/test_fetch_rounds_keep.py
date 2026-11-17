"""The rule `fetch_rounds_keep` (owner decision 2026-11-17, from the
literature on VISOR).

Promises:
- with "all", two rounds of fetching show the chunks of both rounds in the
  last request;
- with "last", the last request shows only the chunks of the last round (and
  the request's own), and none of the first round;
- with one round, "all" and "last" make the same requests;
- nothing is fetched twice in either mode (the `seen` sets stay);
- the loop of the coord and search steps (`targets.fetched_again`) follows
  the rule the same way: "all" shows both rounds in the second re-ask, "last"
  only the round before, one round is the same either way;
- with "last", a line that only a chunk of the first round showed is not
  found in the request's `Shown` after the second round (it cannot be
  cited); with "all" it is; a line of the request's own chunk and one of the
  last round are found in both modes.
"""
from docpipe import rules
from docpipe.extraction import addressed
from docpipe.extraction.addressed import Found, Names

from test_addressed import SCENARIOS, plan_of, reader_of
from test_fetching_places import (EXPLAINED, FILLERS, NAMED, Shaped,
                                 address_of)


def texts(payload) -> str:
    return " ".join(" ".join(block["lines"])
                    for block in (payload.get("passages") or {}).values())


def run(**over):
    def names(payload, noted):
        passages = texts(payload)
        if "stands for" not in passages:
            return {"entry": "new",
                    "more": [{"get": "search", "pattern": "stands for"}]}
        if "Abschnitt 5" not in passages:
            return {"entry": "new",
                    "more": [{"get": "search", "pattern": "Abschnitt 5"}]}
        return {"entry": 1}
    model = Shaped(names=names)
    reader = reader_of(model, spec=SCENARIOS)
    plan = plan_of(NAMED, *FILLERS, EXPLAINED)
    plan.names["scenario"] = Names("scenario")
    plan.names["scenario"].add("Klimaneutral 2045")
    passage = plan.passages[("table", 12)]
    line = next(one for one in passage.lines if "KN2045" in one.text)
    got = Found(lines=[(line, passage.source)], passage=passage,
                words="KN2045")
    with rules.overlaid(**over):
        reader.name_of(plan, "scenario", "KN2045", got, addressed.Counts())
    return [texts(p) for kind, p, _s, _n in model.shapes if kind == "names"]


def test_all_shows_the_chunks_of_both_rounds():
    asked = run(fetch_rounds=2, fetch_rounds_keep="all")
    assert len(asked) == 3
    assert "stands for" in asked[2] and "Abschnitt 5" in asked[2]


def test_last_shows_only_the_chunks_of_the_last_round():
    asked = run(fetch_rounds=2, fetch_rounds_keep="last")
    assert len(asked) == 3
    assert "Abschnitt 5" in asked[2] and "stands for" not in asked[2]
    # a request of the first round is the same in both modes
    assert asked[1] == run(fetch_rounds=2, fetch_rounds_keep="all")[1]


def test_one_round_is_the_same_either_way():
    assert run(fetch_rounds=1, fetch_rounds_keep="last") \
        == run(fetch_rounds=1, fetch_rounds_keep="all")


def test_nothing_is_fetched_twice_in_either_mode():
    # by construction: the model asks for the same place again in round two;
    # nothing is fetched (seen), so the loop stops with two requests.
    def names(payload, noted):
        return {"entry": "new",
                "more": [{"get": "search", "pattern": "stands for"}]}
    for keep in ("all", "last"):
        model = Shaped(names=names)
        reader = reader_of(model, spec=SCENARIOS)
        plan = plan_of(NAMED, *FILLERS, EXPLAINED)
        plan.names["scenario"] = Names("scenario")
        passage = plan.passages[("table", 12)]
        line = next(one for one in passage.lines if "KN2045" in one.text)
        got = Found(lines=[(line, passage.source)], passage=passage,
                    words="KN2045")
        with rules.overlaid(fetch_rounds=3, fetch_rounds_keep=keep):
            reader.name_of(plan, "scenario", "KN2045", got,
                           addressed.Counts())
        assert len([1 for kind, *_ in model.shapes if kind == "names"]) == 2


# -- the loop of the coord and search steps (`targets.fetched_again`) ---------

def driven(**over):
    """(requests, req) of `fetched_again` over a real Reader.fetch and
    show_fetched: the reply asks for "stands for", then for "Abschnitt 5",
    then for nothing. A request is (the text of its passages, the shown
    address of a line of each round, the own line's address)."""
    from types import SimpleNamespace
    from docpipe.extraction import targets
    from docpipe.extraction.units import Shown, address_of as parse
    model = Shaped()
    reader = reader_of(model, spec=SCENARIOS)
    plan = plan_of(NAMED, *FILLERS, EXPLAINED)
    passage = plan.passages[("table", 12)]
    line = next(one for one in passage.lines if "KN2045" in one.text)
    anchor = addressed.Reader.anchor_of(plan, Found(
        lines=[(line, passage.source)], passage=passage, words="KN2045"))
    req = SimpleNamespace(chunks=anchor, shown=Shown(), payload={})
    req.shown.add("", "", addressed.own_lines(anchor[0]))
    asked = []

    def again(request, shape, example, counts, fetched=0):
        passages = texts(request.payload)
        asked.append((passages, {
            "first": request.shown.find(parse(address_of(
                request.payload, "stands for"))) if "stands for"
            in passages else None,
            "second": request.shown.find(parse(address_of(
                request.payload, "Abschnitt 5"))) if "Abschnitt 5"
            in passages else None,
            "own": request.shown.find(parse(str(line.number)))}))
        if "stands for" in passages and "Abschnitt 5" not in passages:
            return {"more": [{"get": "search", "pattern": "Abschnitt 5"}]}
        return {}
    ask = SimpleNamespace(reader=reader, plan=plan, ask=again)
    first = {"more": [{"get": "search", "pattern": "stands for"}]}
    with rules.overlaid(**over):
        targets.fetched_again(ask, req, {}, {}, first, addressed.Counts())
    return asked


def test_the_loop_of_coord_and_search_follows_the_rule():
    both = driven(fetch_rounds=2, fetch_rounds_keep="all")
    assert len(both) == 2
    assert "stands for" in both[1][0] and "Abschnitt 5" in both[1][0]
    last = driven(fetch_rounds=2, fetch_rounds_keep="last")
    assert len(last) == 2
    assert "Abschnitt 5" in last[1][0] and "stands for" not in last[1][0]
    # the first re-ask is the same in both modes, and so is one round
    assert both[0] == last[0]
    assert driven(fetch_rounds=1, fetch_rounds_keep="last") \
        == driven(fetch_rounds=1, fetch_rounds_keep="all")


def test_a_line_of_a_dropped_chunk_cannot_be_cited():
    # the line only the first round showed, in the request of the second
    kept = driven(fetch_rounds=2, fetch_rounds_keep="all")[1][1]
    dropped = driven(fetch_rounds=2, fetch_rounds_keep="last")[1][1]
    assert dropped["first"] is None and kept["first"] is not None
    # the failure by construction: the line of the last round and the
    # request's own line are found in both modes
    assert dropped["second"] is not None and kept["second"] is not None
    assert dropped["own"] is not None and kept["own"] is not None
