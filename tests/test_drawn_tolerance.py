"""
A number read off the picture of a figure is an estimate: where it and a
printed number of the same place disagree, the graph compares them with a
share of its own (owner decision 2026-11-17, rule `drawn_tolerance` of the
graph file; from the literature on reading charts, where models read
diverse charts far worse than printed numbers).

The promises, each with a case that breaks it by construction:

1. Two numbers of one place, one of them drawn, settle as one rounded
   statement within `drawn_tolerance`, the more precise one kept, AND two
   printed numbers keep the share of `rounding_tolerance`, AND without the
   rule every number keeps that share.
2. The kwp graph file has the rule, and the writer hands it to the settling.
"""
from docpipe import graphfile
from docpipe.extraction import readings
from docpipe.profile import load_profile


def number(value, drawn=False):
    row = {"value": value, "value_target": float(value), "subject": "",
           "quote": f"{value}", "tier": "text_located", "flags": []}
    if drawn:
        row["drawn"] = True
    return row


def settled(rows, drawn_tolerance):
    return readings.settle(
        "iri", rows, lambda row, label="": f"iri/{label or row['value']}",
        fold=lambda text: str(text).lower(), wording=("subject",),
        tolerance=0.02, order=["rounding", "contested"], corroborate=False,
        keep_open=True, drawn_tolerance=drawn_tolerance)


def test_a_drawn_number_settles_within_a_share_of_its_own():
    printed, drawn = number("1234"), number("1150", drawn=True)
    kept, lost, marks = settled([printed, drawn], 0.1)
    assert list(kept.values()) == [printed]
    assert marks["iri"] == {"resolved": "rounding"}
    assert lost["conflict:rounding"] == 1
    # Within the printed share alone the two stay contested.
    kept, lost, _ = settled([printed, drawn], 0.02)
    assert len(kept) == 2 and lost["conflict:open"] == 2
    # Two printed numbers 7 % apart keep the printed share.
    kept, _, _ = settled([printed, number("1150")], 0.1)
    assert len(kept) == 2
    # Without the rule the drawn one keeps it too.
    kept, _, _ = settled([printed, drawn], None)
    assert len(kept) == 2


def test_the_kwp_graph_file_has_the_rule():
    assert "drawn_tolerance" in graphfile.declared(load_profile("kwp"))
    graphfile.reset()
    try:
        assert graphfile.get("drawn_tolerance", "kwp") == 0.1
    finally:
        graphfile.reset()
