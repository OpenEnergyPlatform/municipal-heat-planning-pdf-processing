"""Tests for the imageprocessing dataclasses."""
from docpipe.visuals.models import EnrichedFigure, EnrichedTable, ProcessingStats


def test_enriched_table_roundtrip():
    t = EnrichedTable(id="p1_tbl0", path="images/p1_tbl0.png", page_number=1,
                      caption="c", markdown="| a |")
    d = t.to_dict()
    assert d["markdown"] == "| a |"
    assert EnrichedTable.from_dict(d).caption == "c"


def test_enriched_figure_omits_none_fields():
    f = EnrichedFigure(id="p1_img0", path="images/p1_img0.png")
    d = f.to_dict()
    assert "description" not in d and "caption" not in d


def test_processing_stats_summary():
    s = ProcessingStats(total_tables=2, processed_tables=1, failed_tables=1)
    out = s.summary()
    assert "1/2" in out and "1 failed" in out
