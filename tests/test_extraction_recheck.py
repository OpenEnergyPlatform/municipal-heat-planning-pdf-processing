"""The evidence rule applied backwards, over a harvest written without it.

Every claim in a harvest file carries its wording and its passage, which is
what makes a rule that tightens enforceable on what is already written. These
hold the two halves of that: a coordinate whose quote carries it survives, and
one whose quote does not — including one that never had a quote at all — is
removed rather than left standing as if it had been checked.

And the stamps go with it, because a file rewritten by a rule its run never
applied is not that run's output. Leaving the stamp is how 205 plans kept a
whole-tuple harvest through a field-wise corpus run.
"""
import json
from pathlib import Path

import pytest

from docpipe.extraction import fields, recheck
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def _spec(name="kwp"):
    return load_spec(json.loads(
        (PROFILES / name / "extraction_spec.json").read_text(encoding="utf-8")))


def _numeric_parameter(spec):
    return next(p for p in spec.parameters if p.axes)


def _write(tmp_path, rows):
    path = tmp_path / "plan.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")
    return path


def test_a_coordinate_its_quote_carries_survives(tmp_path):
    spec = _spec()
    parameter = _numeric_parameter(spec)
    slot = next(s for s in fields.axis_slots(parameter) if s.name == "year")
    row = {"kind": "tuple", "parameter": parameter.uri, "value": 42,
           "year": 2022,
           "year_quote": "Tabelle 3.1: Endenergieverbrauch im Jahr 2022 [GWh/a]"}
    path = _write(tmp_path, [row])
    stats = recheck.recheck_file(path, spec)
    back = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert back["year"] == 2022
    assert back["year_state"] == fields.READ
    assert stats["quote does not carry the answer"] == 0
    assert slot.kind == fields.NUMBER          # the number path, not the text one


def test_a_year_whose_caption_names_no_year_does_not_stay(tmp_path):
    """The measured case: 27.6% of one run's years, this caption among them."""
    spec = _spec()
    parameter = _numeric_parameter(spec)
    row = {"kind": "tuple", "parameter": parameter.uri, "value": 42,
           "year": 1990,
           "year_quote": "Tabelle 1: Bestehende Wärmenetze und Heiz(kraft)werke"}
    path = _write(tmp_path, [row])
    stats = recheck.recheck_file(path, spec)
    back = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert "year" not in back and "year_quote" not in back
    assert back["year_state"] == fields.UNANSWERED
    assert stats["quote does not carry the answer"] == 1


def test_a_coordinate_with_no_quote_at_all_does_not_stay(tmp_path):
    """What the whole-tuple contract produced: a coordinate and no passage.

    It was never checked and cannot be, so it does not get to look like a
    reading that was.
    """
    spec = _spec()
    parameter = _numeric_parameter(spec)
    row = {"kind": "tuple", "parameter": parameter.uri, "value": 42,
           "year": 2022}
    path = _write(tmp_path, [row])
    stats = recheck.recheck_file(path, spec)
    back = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert "year" not in back
    assert stats["no evidence at all"] == 1


def test_refusals_and_unreadable_lines_are_left_alone(tmp_path):
    spec = _spec()
    rows = [{"kind": "refusal", "reason": "unit None not in units_accepted"}]
    path = _write(tmp_path, rows)
    path.write_text(path.read_text(encoding="utf-8") + "{kaputt\n",
                    encoding="utf-8")
    recheck.recheck_file(path, spec)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["kind"] == "refusal"
    assert lines[1] == "{kaputt"


def test_the_stamps_go_with_the_rewrite(tmp_path):
    """A file rewritten by a rule its run never applied is not that run's
    output, and the next run must not skip it."""
    spec = _spec()
    parameter = _numeric_parameter(spec)
    _write(tmp_path, [{"kind": "tuple", "parameter": parameter.uri,
                       "value": 42, "year": 2022}])
    stamp = tmp_path / "plan.stamp.json"
    stamp.write_text("{}", encoding="utf-8")
    stats = recheck.run(tmp_path, spec)
    assert not stamp.exists()
    assert stats["stamps cleared"] == 1
    assert stats["documents"] == 1


def test_keeping_the_stamps_is_something_you_have_to_ask_for(tmp_path):
    spec = _spec()
    parameter = _numeric_parameter(spec)
    _write(tmp_path, [{"kind": "tuple", "parameter": parameter.uri,
                       "value": 42, "year": 2022}])
    stamp = tmp_path / "plan.stamp.json"
    stamp.write_text("{}", encoding="utf-8")
    recheck.run(tmp_path, spec, drop_stamps=False)
    assert stamp.exists()


def test_a_rewritten_harvest_gets_a_rewritten_summary(tmp_path):
    """This pass changes what the tuples say, and the summary counts them.
    Carried over it would report a run that no longer exists, and it is the
    one line a reader of 1.082 plans actually reads.

    The case: a year read off a DIFFERENT table's caption, in a passage that
    does not carry it. It made the value a C. This pass strips it, and the
    value is then an ordinary reading with one coordinate fewer -- which is
    the whole point of applying the rule backwards. A kept summary would go
    on reporting two unusable values.
    """
    spec = _spec()
    parameter = _numeric_parameter(spec)

    def _row(year, quote, source):
        return {"kind": "tuple", "parameter": parameter.uri, "value": 42,
                "year": year, "year_quote": quote, "year_state": fields.READ,
                "provenance": {"document_id": 857, "owner_kind": "table",
                               "owner_id": 1},
                "year_source": source, "tier": "text_located"}

    path = _write(tmp_path, [
        _row(2040, "Tabelle 5: Endenergieverbrauch im Jahr 2040 [GWh/a]",
             ["table", 87517]),
        _row(1990, "Tabelle 1: Bestehende Waermenetze und Heizwerke",
             ["table", 87517]),
        {"kind": "summary", "document_id": 857, "tuples": 2, "refusals": 0,
         "levels": {"A": 0, "B": 0, "C": 2},
         "reasons": {"nonlocal:year": 2}, "image_origin": 0}])

    stats = recheck.recheck_file(path, spec)
    assert stats["summaries rewritten"] == 1
    rows = [json.loads(line) for line
            in path.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 3 and rows[-1]["kind"] == "summary", "still last"
    assert rows[-1]["document_id"] == 857 and rows[-1]["tuples"] == 2
    # 2040 stands in its own quote and stays, read off a foreign table; 1990
    # does not and goes. So one value keeps its C and one loses it.
    assert rows[-1]["levels"] == {"A": 1, "B": 0, "C": 1}
    assert rows[-1]["reasons"] == {"nonlocal:year": 1}
