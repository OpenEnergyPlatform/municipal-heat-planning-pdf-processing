"""
A field that found little in a document is read a second time over the same
pieces, and the finds of both passes are united (owner decision 2026-11-17,
from the literature on reading a place several times: LangExtract, Google
2025; each find is backed by its own quote, and the graph merges duplicates
anyway).

The promises, each with a case that breaks it by construction:

1. A field with at least one find and fewer than `find_again_below` is
   asked a second time over the same pieces, one request for each request
   of the first pass, AND what the second pass finds joins the first's.
2. A value found at the same place in both passes is one value, AND a
   value of the same line at another cell, or another place, is a value of
   its own.
3. A field with no find is not asked again, AND a field with as many finds
   as the rule says, or more, is not asked again.
4. The rule at 0 asks no second pass, AND the second pass is the first
   one's requests asked again (the rule `same_request_once` is off in it),
   noted on each request (`second_way`) AND on the trace.
5. The rule `find_again_way` words only the second pass: the first pass
   reads the find prompt in its standard way, the second in the way the rule
   says, AND the three find prompts hold both ways.
"""
from pathlib import Path

import pytest

from docpipe import rules
from docpipe.extraction import thread
from docpipe.extraction.engine import Engine

from test_addressed import (ENERGY, TABLE, TEXT, Model, plan_of, reader_of)

ROOT = Path(__file__).resolve().parent.parent
FIRST = {"at": "3.2", "words": "1.200"}
SECOND = {"at": "3.3", "words": "27"}
THIRD = {"at": "4.3", "words": "12"}


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def finds_of(first, second=None):
    """A find reply: what the first pass answers over the table's piece and,
    where *second* is given, what a request of the second pass answers;
    nothing over any other piece."""
    def reply(payload, noted):
        if payload["passage"]["kind"] != "table":
            return {"found": []}
        if noted.get("second_way") and second is not None:
            return {"found": second}
        return {"found": first}
    return reply


def read(model, *sources, **overlay):
    with rules.overlaid(**overlay):
        reads = reader_of(model)(plan_of(*sources), [ENERGY])
    claims = [c for r in reads for c in r.claims]
    return claims, model


def requests(model):
    """([chunks of the first pass], [chunks of the second]) of the find
    requests, by what each notes."""
    first = [n["chunk"] for _, n in model.of("find")
             if not n.get("second_way")]
    again = [n["chunk"] for _, n in model.of("find")
             if n.get("second_way")]
    return first, again


def values_of(claims):
    return sorted(c["value"] for c in claims)


def test_a_field_with_few_finds_is_asked_again_over_the_same_pieces():
    model = Model(find=finds_of([FIRST], [SECOND, THIRD, FIRST]))
    claims, model = read(model, TABLE, TEXT)
    first, again = requests(model)
    assert first and sorted(first) == sorted(again)
    # What the second pass found joins what the first found.
    assert values_of(claims) == [12, 27, 1200]
    # The break by construction: a second pass that found nothing new adds
    # nothing, and the first pass's value stays.
    model = Model(find=finds_of([FIRST], [FIRST]))
    claims, model = read(model, TABLE, TEXT)
    assert values_of(claims) == [1200]
    assert requests(model)[1]


def test_a_value_found_in_both_passes_is_one_value_at_its_place():
    model = Model(find=finds_of([FIRST], [FIRST, SECOND]))
    claims, _ = read(model, TABLE, TEXT)
    assert values_of(claims) == [27, 1200]
    assert len([c for c in claims if c["at"].get("cell") == 2]) == 1
    # The break by construction: the same words at another cell, line or
    # passage, and other words at the same cell, are values of their own.
    base = {"value_raw": "27", "at": {"owner": ["table", 3], "line": 3,
                                      "cell": 3}}
    key = Engine.find_key
    assert key(base) == key({**base, "value": 27})
    for at in ({"cell": 2}, {"line": 4}, {"owner": ["table", 4]},
               {"last": 5}):
        assert key({**base, "at": {**base["at"], **at}}) != key(base)
    assert key({**base, "value_raw": "28"}) != key(base)


def test_a_field_without_a_find_or_with_enough_finds_is_not_asked_again():
    model = Model(find=finds_of([], [FIRST]))
    claims, model = read(model, TABLE, TEXT)
    assert not claims and not requests(model)[1]
    # Three finds are the rule's standard number: not asked again.
    three = [FIRST, SECOND, THIRD]
    claims, model = read(Model(find=finds_of(three, [])), TABLE, TEXT)
    assert len(claims) == 3 and not requests(model)[1]
    # The break by construction: one find fewer than the rule says is.
    claims, model = read(Model(find=finds_of(three[:2], [])), TABLE, TEXT)
    assert requests(model)[1]
    # And the number is the rule's: at 2 the same two finds are enough.
    claims, model = read(Model(find=finds_of(three[:2], [])), TABLE, TEXT,
                         find_again_below=2)
    assert not requests(model)[1]


def test_the_rule_at_0_asks_no_second_pass_and_the_second_is_noted():
    one = finds_of([FIRST], [SECOND])
    claims, model = read(Model(find=one), TABLE, TEXT, find_again_below=0)
    assert values_of(claims) == [1200] and not requests(model)[1]
    # The break by construction: at its standard the same model is asked.
    traced = []
    reader = reader_of(Model(find=one), trace=lambda event, doc, **values:
                       traced.append((event, values)))
    reads = reader(plan_of(TABLE, TEXT), [ENERGY])
    assert values_of([c for r in reads for c in r.claims]) == [27, 1200]
    again = [v for e, v in traced if e == "second_way"
             and v.get("rule") == "find_again_below"]
    assert again and again[0]["added"] == 1 and again[0]["finds"] == 1
    assert again[0]["parameter"] == ENERGY.uri


def test_the_way_words_the_second_pass_only_and_every_find_prompt_has_both():
    seen = []

    def reply(payload, noted):
        seen.append((bool(noted.get("second_way")),
                     rules.get("find_again_way")))
        return finds_of([FIRST], [SECOND])(payload, noted)
    read(Model(find=reply), TABLE, TEXT, find_again_way="generous")
    assert {(second, way) for second, way in seen
            if second} == {(True, "generous")}
    assert {(second, way) for second, way in seen
            if not second} == {(False, "same")}
    # The break by construction: with the way "same" the second pass reads
    # the standard way too.
    seen.clear()
    read(Model(find=reply), TABLE, TEXT, find_again_way="same")
    assert {way for _, way in seen} == {"same"}
    for path in ("docpipe/builtin/default", "profiles/kwp",
                 "profiles/scenarios"):
        text = (ROOT / path / "prompts" / "extraction" / "find.md") \
            .read_text(encoding="utf-8")
        thread.check_ways(text, path)
        with rules.overlaid(find_again_way="generous"):
            generous = thread.chosen(text, path)
        with rules.overlaid(find_again_way="same"):
            plain = thread.chosen(text, path)
        assert generous != plain and len(generous) > len(plain)
