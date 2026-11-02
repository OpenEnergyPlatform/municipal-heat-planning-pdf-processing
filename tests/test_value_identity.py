"""What the graph does with different numbers on one identity."""
import pytest

from profiles.kwp import kg


def row(value, subject=None, quote=None):
    return {"quantity": "OEO_00050016", "year": 2045, "value": value,
            "value_target": float(value), "subject": subject,
            "quote": quote or f"| Zeile | {value} |", "scenario": "target",
            "tier": "text_located", "flags": []}


def settled(rows, keep_open=True):
    iri = kg._value_iri("part", rows[0])
    return kg.settle(iri, rows, "part", keep_open=keep_open)


def test_the_subject_of_a_number_splits_two_rows_into_two_nodes():
    kept, _lost, marks = settled([row(53, "Bis 1918"), row(41, "Unbekannt")])
    assert sorted(r["value"] for r in kept.values()) == [41, 53]
    assert sorted(m["named"] for m in marks.values()) == ["Bis 1918", "Unbekannt"]


def test_one_number_on_two_subjects_is_one_node():
    kept, _lost, _marks = settled([row(53, "Bis 1918"), row(53, "bis 1918")])
    assert len(kept) == 1


def test_what_still_disagrees_stays_marked_in_the_full_graph():
    kept, lost, marks = settled([row(100), row(40)])
    assert sorted(r["value"] for r in kept.values()) == [40, 100]
    assert all(m == {"conflict": True} for m in marks.values())
    assert lost["conflict:open"] == 2
    assert not lost["conflict"]


def test_what_still_disagrees_stays_out_of_the_strict_graph():
    kept, lost, _marks = settled([row(100), row(40)], keep_open=False)
    assert kept == {}
    assert lost["conflict"] == 2


def test_two_numbers_of_one_quote_stay_two_nodes():
    kept, _lost, _marks = settled([row(100, quote="| Zeile | 100 | 40 |"),
                                   row(40, quote="| Zeile | 100 | 40 |")])
    assert len(kept) == 2


@pytest.mark.parametrize("values, resolved", [((1000, 1001), "rounding")])
def test_a_rounded_reading_still_loses_before_anything_stays_open(values,
                                                                  resolved):
    kept, _lost, marks = settled([row(v) for v in values])
    assert len(kept) == 1
    assert next(iter(marks.values())).get("resolved") == resolved
