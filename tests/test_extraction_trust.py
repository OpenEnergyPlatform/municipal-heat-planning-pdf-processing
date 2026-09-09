"""How much of a value the run can stand behind, as a level a reader can act on.

Every accepted tuple is verified, and that is a floor rather than a grade: a
value with every coordinate read off its own table and a value whose year was
read off the caption of a different table three pages away both clear it, and
until now the graph showed a reader two numbers.

What these tests hold is that the cut is where the measurement puts it. Image
origin alone separates nothing on this corpus (527 of Kassel's 559 tuples came
out of a table or figure), so it is not a warning; a passage that belongs to
another row is the failure the whole repair is about, so it is.

No model, no GPU.
"""
import importlib
from pathlib import Path

import pytest

from docpipe.extraction import fields
from docpipe.extraction.trust import (LEVEL_A, LEVEL_B, LEVEL_C, MARKS,
                                      check_prose, document_summary, marks,
                                      render, trust)
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL


def _row(**overrides):
    """A value with everything read, every passage in its own table."""
    row = {
        "parameter": "energy_consumption", "value": 241.0,
        "value_target": 241.0, "tier": TIER_TEXT, "flags": [],
        "provenance": {"document_id": 857, "owner_kind": "table",
                       "owner_id": 87457, "parent_section": 349525,
                       "page": 86},
    }
    for name in ("quantity", "carrier", "sector", "year", "scenario",
                 "spatial_scope"):
        row[f"{name}_state"] = fields.READ
        row[f"{name}_source"] = ["table", 87457]
    row["aggregation_state"] = fields.DERIVED
    row.update(overrides)
    return row


def test_a_value_read_off_its_own_table_in_the_plans_text_is_an_a():
    verdict = trust(_row())
    assert verdict == {"level": LEVEL_A, "reasons": [], "image_origin": False,
                       "corroborated": False}


def test_a_reading_out_of_a_picture_is_a_b_and_not_a_warning():
    """527 of Kassel's 559 tuples came out of a table or figure image. A
    signal that fires on 94 percent of the corpus separates nothing, so it
    lowers the level and adds no reason for anyone to chase."""
    verdict = trust(_row(tier=TIER_VISUAL))
    assert verdict["level"] == LEVEL_B
    assert verdict["reasons"] == []
    assert verdict["image_origin"] is True


def test_the_same_value_from_a_transcribed_plan_never_reaches_a():
    """Eleven plans of the corpus have no PDF text layer: a model read their
    pages and everything downstream ran unchanged, so the section text a
    quote is verified against is itself a reading."""
    assert trust(_row())["level"] == LEVEL_A
    capped = trust(_row(), transcribed=True)
    assert capped["level"] == LEVEL_B
    assert capped["reasons"] == ["page_transcribed"]
    # And it caps rather than condemns: on its own it is not a C.
    assert trust(_row(tier=TIER_VISUAL), transcribed=True)["level"] == LEVEL_B


def test_a_passage_that_belongs_to_another_row_is_a_c():
    """The measured failure: 370 of Kassel's 455 year readings cited a
    passage outside the row's own table and its section, 146 of them the
    annotated placeholder of a DIFFERENT table."""
    verdict = trust(_row(year_source=["table", 87517]))
    assert verdict["level"] == LEVEL_C
    assert verdict["reasons"] == ["nonlocal:year"]

    # The section the table stands in is not "another row": that is where a
    # caption and the sentence announcing a table live.
    assert trust(_row(year_source=["section", 349525]))["level"] == LEVEL_A


@pytest.mark.parametrize("field,expected", [
    ({"year_state": fields.EXHAUSTED}, "exhausted:year"),
    ({"sector_state": fields.UNBACKED}, "unbacked:sector"),
    ({"flags": ["quote_repaired"]}, "repaired"),
    ({"flags": ["computed"]}, "computed"),
    ({"flags": ["not_located"]}, "not_located"),
])
def test_every_doubt_the_harvest_records_lowers_the_level(field, expected):
    verdict = trust(_row(**field))
    assert verdict["level"] == LEVEL_C
    assert expected in verdict["reasons"]


def test_a_contested_identity_is_a_c_even_with_everything_else_right():
    verdict = trust(_row(), conflict=True)
    assert verdict["level"] == LEVEL_C
    assert verdict["reasons"] == ["conflict"]


def test_a_coordinate_the_plan_does_not_state_is_not_a_doubt():
    """"The plan does not say it" is a finding about the plan, and "never
    asked, the row left at the gate" is one about this run's scope. Neither
    is a reason to distrust the number that was read."""
    for state in (fields.SAID_UNSTATED, fields.OUT_OF_SLICE,
                  fields.DERIVED, fields.UNANSWERED):
        # The source key is left pointing at a foreign table on purpose. A
        # coordinate that is not read has no evidence to judge, so whatever
        # a previous window left behind must not be judged as if it had.
        verdict = trust(_row(sector_state=state,
                             sector_source=["table", 87517]))
        assert verdict["level"] == LEVEL_A, state
        assert verdict["reasons"] == [], state


def test_the_line_says_what_to_do_about_it():
    """The core no longer writes the words, so this is asked through a
    profile's table. kwp's, because kwp's German is the published wording."""
    from profiles.kwp.kg import TRUST_JOIN, TRUST_PROSE
    line = render(trust(_row(tier=TIER_VISUAL,
                             year_source=["table", 87517])),
                  TRUST_PROSE, join=TRUST_JOIN, row=_row(tier=TIER_VISUAL))
    assert line.startswith("Vertrauen: C")
    assert "nonlocal:year" in line
    assert "Prüfung empfohlen" in line
    # An A says its level and nothing else: there is nothing to act on.
    assert render(trust(_row()), TRUST_PROSE, join=TRUST_JOIN) == "Vertrauen: A"


# ---------------------------------------------------------------------------
# The seam: the marks are the core's, the words are the profile's
# ---------------------------------------------------------------------------

# Enough verdicts to make the core produce every mark it has, each isolating
# as few as it can. Not a sample of what a run writes: a matrix of what a line
# CAN say, which is what a profile has to be able to word.
_VERDICTS = [
    ({"level": LEVEL_A, "reasons": [], "image_origin": False,
      "corroborated": False}, {}),                            # level alone
    ({"level": LEVEL_B, "reasons": [], "image_origin": True,
      "corroborated": False}, {"provenance": {}}),            # + unnamed image
    ({"level": LEVEL_B, "reasons": [], "image_origin": True,
      "corroborated": False},
     {"provenance": {"image": "kassel_t_12.png"}}),           # + named image
    ({"level": LEVEL_B, "reasons": [], "image_origin": False,
      "corroborated": True}, {}),                             # + second source
    ({"level": LEVEL_B, "reasons": ["repaired"], "image_origin": False,
      "corroborated": False}, {}),                            # + one reason
    ({"level": LEVEL_C, "reasons": [], "image_origin": False,
      "corroborated": False}, {}),                            # + review, alone
    ({"level": LEVEL_C, "reasons": ["nonlocal:carrier", "repaired"],
      "image_origin": False, "corroborated": False}, {}),     # two reasons
]


def _profiles():
    """Every profile that serializes a graph, found rather than listed."""
    root = Path(__file__).resolve().parent.parent / "profiles"
    return sorted(p.parent.name for p in root.glob("*/kg.py"))


def test_the_cases_below_produce_every_mark_the_core_has():
    """A mark no case produces is a mark the profile test never asks about,
    so the matrix is held against the vocabulary instead of eyeballed. This is
    the direction a key-set check cannot see: a mark added to MARKS whose
    branch in `marks()` was forgotten."""
    seen = {mark for verdict, row in _VERDICTS
            for mark, _ in marks(verdict, row)}
    assert seen == set(MARKS), sorted(set(MARKS) ^ seen)


def test_every_mark_is_reached_by_a_case_that_isolates_it():
    """Each mark has a case where it is the only thing said beside the level.
    Without that, deleting one branch of `marks()` can hide behind another
    mark that flipped in the same case."""
    alone = set()
    for verdict, row in _VERDICTS:
        pairs = marks(verdict, row)
        if len(pairs) == 2:
            alone.add(pairs[1][0])
    assert alone == set(MARKS) - {"level"}, sorted(alone)


@pytest.mark.parametrize("name", _profiles())
def test_every_profile_words_every_mark_the_core_can_produce(name):
    """The promise of the split: the marks come from the core. That is only a
    promise if a profile cannot quietly stop saying one of them."""
    kg = importlib.import_module("profiles.%s.kg" % name)
    assert set(kg.TRUST_PROSE) == set(MARKS), (
        "profiles/%s/kg.py TRUST_PROSE against trust.MARKS" % name)
    for verdict, row in _VERDICTS:
        for mark, args in marks(verdict, row):
            # Wording a mark as the empty string is not a way to silence it.
            assert kg.TRUST_PROSE[mark].format(**args).strip(), (
                "profiles/%s/kg.py words %r as nothing" % (name, mark))
        line = render(verdict, kg.TRUST_PROSE, join=kg.TRUST_JOIN, row=row)
        assert line.strip()
        assert all(part.strip() for part in line.split(kg.TRUST_JOIN))


def test_a_table_that_words_a_mark_that_is_not_one_is_refused():
    """And the other direction, at import rather than at the first C of a
    corpus run: one missing piece of one comment line in one document out of a
    thousand is not something anybody reads."""
    complete = {mark: "x" for mark in MARKS}
    assert check_prose(dict(complete), "here") == complete
    for broken in (dict(complete, extra="x"),
                   {k: v for k, v in complete.items() if k != "review"}):
        with pytest.raises(LookupError):
            check_prose(broken, "here")


def _sentence_before_sc3(verdict, row=None):
    """`trust.sentence` as it stood before the marks were split out.

    Frozen on purpose. The kwp graph's German is a published artifact and this
    change was supposed to MOVE it, not rewrite it, so the claim is checked
    against a copy instead of argued in a commit message.
    """
    parts = ["Vertrauen: %s" % verdict["level"]]
    if verdict.get("image_origin"):
        image = ((row or {}).get("provenance") or {}).get("image")
        parts.append("aus einem Bild" + (" (%s)" % image if image else ""))
    if verdict.get("corroborated"):
        parts.append("zweite Quelle bestätigt")
    if verdict["reasons"]:
        parts.append(", ".join(verdict["reasons"]))
    if verdict["level"] == LEVEL_C:
        parts.append("Prüfung empfohlen")
    return " · ".join(parts)


def test_the_german_line_is_the_one_that_stood_there_before():
    """Every combination, not the seven of the matrix: the order of the marks
    and the two joins are as easy to get wrong as the words, and only one of
    the three shows up in a spot check."""
    from profiles.kwp.kg import TRUST_JOIN, TRUST_PROSE
    checked = 0
    for level in (LEVEL_A, LEVEL_B, LEVEL_C):
        for image_origin in (False, True):
            for corroborated in (False, True):
                for why in ([], ["repaired"], ["nonlocal:carrier", "repaired"]):
                    for image in (None, "kassel_t_12.png"):
                        verdict = {"level": level, "reasons": list(why),
                                   "image_origin": image_origin,
                                   "corroborated": corroborated}
                        row = {"provenance":
                               {"image": image} if image else {}}
                        assert render(verdict, TRUST_PROSE, join=TRUST_JOIN,
                                      row=row) == _sentence_before_sc3(
                                          verdict, row), verdict
                        checked += 1
    assert checked == 72


# ---------------------------------------------------------------------------
# One line per document
# ---------------------------------------------------------------------------
def test_the_summary_counts_every_value_once_and_names_why():
    """A corpus of 1.082 plans is not read tuple by tuple. What a reader
    wants -- how much of this plan is usable -- has to be one line."""
    rows = [_row(),                                     # A
            _row(tier=TIER_VISUAL),                     # B
            _row(year_source=["table", 87517]),         # C, foreign year
            _row(flags=["computed"])]                   # C, computed
    got = document_summary(857, rows, [{"reason": "x"}, {"reason": "y"}])
    assert got == {"document_id": 857, "tuples": 4, "refusals": 2,
                   "levels": {LEVEL_A: 1, LEVEL_B: 1, LEVEL_C: 2},
                   "reasons": {"computed": 1, "nonlocal:year": 1},
                   "image_origin": 1}
    assert sum(got["levels"].values()) == got["tuples"], "every value, once"


def test_the_summary_says_nothing_about_a_conflict_it_cannot_see():
    """A contested identity is the serializer's finding, and a second reading
    is a later pass. Both would have to be guessed here, and a guessed C is
    worse than an honest floor: the graph side recomputes the level with
    them, and a value that is a C already never becomes an A."""
    got = document_summary(857, [_row()], [])
    assert got["levels"] == {LEVEL_A: 1, LEVEL_B: 0, LEVEL_C: 0}
    assert got["reasons"] == {}
    # The same value, once the serializer knows the identity is contested.
    assert trust(_row(), conflict=True)["level"] == LEVEL_C


def test_a_document_with_nothing_in_it_still_has_a_summary():
    """A plan the run found no value in is a finding about the plan. An
    absent line reads as a plan that was never harvested."""
    got = document_summary(1082, [], [])
    assert got["tuples"] == 0 and got["refusals"] == 0
    assert got["levels"] == {LEVEL_A: 0, LEVEL_B: 0, LEVEL_C: 0}


# ---------------------------------------------------------------------------
# Which axes may be held to the row's own source
# ---------------------------------------------------------------------------
OWN = frozenset({("energy_consumption", "carrier"),
                 ("energy_consumption", "sector")})


def test_an_axis_the_spec_lets_read_a_page_away_is_not_a_doubt():
    """The rule is per axis. A row label is read off its own table, a
    scenario is often named a page earlier, a class is argued in a methods
    chapter. The harvest enforces each one and writes `unbacked` when it is
    broken, so a foreign passage on a `local` or `any` axis is the rule
    working -- reporting it here would fire on the whole corpus and separate
    nothing, which is why image origin is not a reason either."""
    foreign = _row(year_source=["table", 87517])
    assert trust(foreign)["level"] == LEVEL_C, "no rule known: judge it"
    assert trust(foreign, own=OWN) == {"level": LEVEL_A, "reasons": [],
                                       "image_origin": False,
                                       "corroborated": False}


def test_the_axis_the_spec_does_hold_to_its_own_source_still_counts():
    """Otherwise the fix would silence the finding instead of aiming it: the
    carrier is the one coordinate the row itself really carries."""
    verdict = trust(_row(carrier_source=["table", 87517]), own=OWN)
    assert verdict["level"] == LEVEL_C
    assert verdict["reasons"] == ["nonlocal:carrier"]


def test_the_rule_is_read_per_parameter_not_per_axis_name():
    """Two parameters may name an axis the same way and hold it differently,
    so the pair decides. A set keyed by the bare name would carry one
    parameter's rule onto the other's coordinate."""
    row = _row(parameter="emission", carrier_source=["table", 87517])
    assert trust(row, own=OWN)["reasons"] == [], "OWN names only the other one"
    both = OWN | {("emission", "carrier")}
    assert trust(row, own=both)["reasons"] == ["nonlocal:carrier"]


def test_the_summary_hands_the_rule_down():
    """It is the line a reader of 1.082 plans actually reads; computed
    against the wrong rule it reports a clean run as a broken one."""
    rows = [_row(year_source=["table", 87517]) for _ in range(3)]
    assert document_summary(857, rows, [])["levels"][LEVEL_C] == 3
    with_rule = document_summary(857, rows, [], own=OWN)
    assert with_rule["levels"] == {LEVEL_A: 3, LEVEL_B: 0, LEVEL_C: 0}
    assert with_rule["reasons"] == {}


def test_own_evidence_reads_the_rule_off_the_spec():
    """The set has one source, and it is the spec the run was made with."""
    import json
    from pathlib import Path

    from docpipe.extraction.spec import load as load_spec, own_evidence

    root = Path(__file__).resolve().parent.parent
    spec = load_spec(json.loads(
        (root / "profiles" / "kwp" / "extraction_spec.json")
        .read_text(encoding="utf-8")))
    got = own_evidence(spec)
    assert ("energy_consumption", "carrier") in got
    assert ("energy_consumption", "sector") in got
    # Measured against the spec as it reads: year and scenario are "local",
    # aggregation and spatial_scope have no rule at all.
    for name in ("year", "scenario", "quantity", "aggregation",
                 "spatial_scope"):
        assert ("energy_consumption", name) not in got, name
    assert {axis for _uri, axis in got} == {"carrier", "sector"}


def test_a_scenario_lifted_from_another_section_is_now_a_finding():
    """The promise: setting the rule on the scenarios axes makes a coordinate
    judgeable that no reader could judge before.

    `reasons` skips every coordinate that is not in `own` (trust.py), so with
    the empty set the scenarios profile had, a scenario name taken from a
    different section of the paper graded exactly like one read off the row's
    own caption. Three of the four axes are `own` now, and the fourth is
    `local` and stays out on purpose: `local` is a statement about pages, and
    a harvest row records an owner, not a page distance.
    """
    import json
    from pathlib import Path

    from docpipe.extraction.spec import load as load_spec, own_evidence
    from docpipe.extraction.trust import trust

    root = Path(__file__).resolve().parent.parent
    spec = load_spec(json.loads(
        (root / "profiles" / "scenarios" / "extraction_spec.json")
        .read_text(encoding="utf-8")))
    own = own_evidence(spec)
    assert own, "an empty set is what this test exists to end"

    def row(parameter, source):
        return {"parameter": parameter, "tier": TIER_TEXT,
                "provenance": {"owner_kind": "section", "owner_id": 11},
                "scenario": "SSP2-4.5", "scenario_state": "read",
                "scenario_source": source}

    here = ["section", 11]
    far = ["section", 99]
    assert trust(row("scenario_type", here), own=own)["reasons"] == []
    assert trust(row("scenario_type", far),
                 own=own)["reasons"] == ["nonlocal:scenario"]
    assert trust(row("scenario_type", far), own=own)["level"] == LEVEL_C
    # The one axis that is `local`: a page distance is not reconstructible
    # from a row, so it is judged at harvest and not here.
    assert trust(row("scenario_region", far), own=own)["reasons"] == []
    assert trust(row("scenario_region", far), own=own)["level"] == LEVEL_A
    # And with the old empty set nothing at all was findable.
    assert trust(row("scenario_type", far), own=frozenset())["reasons"] == []
    # The `tier` key is what keeps these rows at A: a row without one is
    # graded as taken off an image, which is B whatever its coordinates say.
    tierless = row("scenario_region", here)
    tierless.pop("tier")
    assert trust(tierless, own=own)["level"] == LEVEL_B

def test_parameter_states_names_every_parameter_of_the_spec():
    """One line per parameter, whatever came of it, keyed on the uri the
    tuples are keyed on. Keyed on the label instead, every count reads zero
    and every parameter reads `unstated` on a run that answered."""
    import json
    from pathlib import Path

    from docpipe.extraction.spec import load as load_spec
    from docpipe.extraction.trust import parameter_states

    root = Path(__file__).resolve().parent.parent
    spec = load_spec(json.loads(
        (root / "profiles" / "kwp" / "extraction_spec.json")
        .read_text(encoding="utf-8")))

    tuples = [{"parameter": "energy_consumption", "value": 1.0},
              {"parameter": "energy_consumption", "value": 2.0}]
    refusals = [{"parameter": "emission", "reason": "no_quote"},
                # A refusal that names a parameter with a tuple does not
                # take it back: the tuple survived verification.
                {"parameter": "energy_consumption", "reason": "no_quote"}]
    got = parameter_states(spec, tuples, refusals)

    assert [g["parameter"] for g in got] == [p.uri for p in spec.parameters]
    assert {g["parameter"]: g["state"] for g in got} == {
        "energy_consumption": fields.READ,
        "emission": fields.UNBACKED,
        "planning_organisation": fields.SAID_UNSTATED,
        "heat_load": fields.SAID_UNSTATED}
    assert [(g["tuples"], g["refusals"]) for g in got] == [
        (2, 1), (0, 1), (0, 0), (0, 0)]
