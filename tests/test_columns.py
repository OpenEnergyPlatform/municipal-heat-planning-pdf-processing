"""Reading order on one- and two-column pages."""
from pathlib import Path

import pytest

from docpipe.preprocessing import columns
from docpipe.preprocessing.models import Block, PageData
from docpipe.preprocessing.stage3_structure import build_sections

WIDTH, HEIGHT = 595.0, 842.0          # A4 in points
LEFT, RIGHT = (50.0, 290.0), (305.0, 545.0)


def _block(name, y, x_range=(50.0, 545.0), kind="text"):
    x0, x1 = x_range
    return Block(id=name, type=kind, bbox=[x0, y, x1, y + 40.0],
                 content=name if kind == "text" else None)


def _page(blocks, number=1):
    return PageData(page_number=number, width_pt=WIDTH, height_pt=HEIGHT,
                    blocks=list(blocks))


def _two_column_blocks(rows=5):
    """Alternating left/right blocks, as the (y, x) sort would hand them over."""
    out = []
    for i in range(rows):
        y = 100.0 + i * 60.0
        out.append(_block(f"L{i}", y, LEFT))
        out.append(_block(f"R{i}", y, RIGHT))
    return out


def _ids(blocks):
    return [b.id for b in blocks]


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------
def test_full_width_text_is_a_single_column():
    blocks = [_block(f"T{i}", 100.0 + i * 60) for i in range(8)]
    assert columns.find_gutters(blocks, WIDTH) == []


def test_two_columns_are_found_at_their_gutter():
    (gutter,) = columns.find_gutters(_two_column_blocks(), WIDTH)
    assert LEFT[1] < gutter < RIGHT[0]


def test_an_off_centre_gutter_is_found_too():
    """A narrow left column and a wide right one is still two columns."""
    blocks = []
    for i in range(5):
        y = 100.0 + i * 60
        blocks.append(_block(f"L{i}", y, (50.0, 200.0)))
        blocks.append(_block(f"R{i}", y, (220.0, 545.0)))
    (gutter,) = columns.find_gutters(blocks, WIDTH)
    assert 200.0 < gutter < 220.0


def test_too_few_blocks_is_not_enough_evidence():
    assert columns.find_gutters(_two_column_blocks(rows=2), WIDTH) == []


def test_one_lonely_block_beside_a_column_is_not_a_second_column():
    """Otherwise a figure caption sitting to the right would flip a whole page."""
    blocks = [_block(f"L{i}", 100.0 + i * 60, LEFT) for i in range(5)]
    blocks.append(_block("R0", 100.0, RIGHT))
    assert columns.find_gutters(blocks, WIDTH) == []


def test_tables_and_figures_do_not_vote():
    """A full-width figure on a two-column page must not fill in the gutter."""
    blocks = _two_column_blocks()
    blocks.append(_block("fig", 400.0, kind="image"))
    assert columns.find_gutters(blocks, WIDTH)


# ---------------------------------------------------------------------------
# ordering
# ---------------------------------------------------------------------------
def test_a_column_is_read_to_its_end_before_the_next_one():
    blocks = _two_column_blocks(rows=3)
    assert _ids(blocks) == ["L0", "R0", "L1", "R1", "L2", "R2"]   # the (y, x) order
    ordered = columns.order_blocks(blocks, gutters=[297.5])
    assert _ids(ordered) == ["L0", "L1", "L2", "R0", "R1", "R2"]


def test_a_spanning_block_closes_the_columns_above_it():
    """A full-width heading mid-page starts a new pair of columns below it."""
    blocks = [
        _block("L0", 100.0, LEFT), _block("R0", 100.0, RIGHT),
        _block("head", 220.0),                      # full width
        _block("L1", 300.0, LEFT), _block("R1", 300.0, RIGHT),
    ]
    ordered = columns.order_blocks(blocks, gutters=[297.5])
    assert _ids(ordered) == ["L0", "R0", "head", "L1", "R1"]


def test_without_a_gutter_the_order_is_top_down():
    blocks = _two_column_blocks(rows=2)
    assert _ids(columns.order_blocks(blocks, gutters=[])) == ["L0", "R0", "L1", "R1"]


# ---------------------------------------------------------------------------
# the profile setting
# ---------------------------------------------------------------------------
def test_single_never_looks_for_columns():
    page = _page(_two_column_blocks(rows=3))
    assert columns.sort_page(page, "single") == []
    assert _ids(page.blocks) == ["L0", "R0", "L1", "R1", "L2", "R2"]


def test_auto_detects_per_page():
    page = _page(_two_column_blocks(rows=3))
    assert columns.sort_page(page, "auto")
    assert _ids(page.blocks) == ["L0", "L1", "L2", "R0", "R1", "R2"]


def test_double_falls_back_to_the_page_centre_when_nothing_is_detected():
    """The profile says two columns; a page too sparse to prove it still is one."""
    page = _page(_two_column_blocks(rows=2))
    assert columns.sort_page(page, "double") == [pytest.approx(WIDTH / 2)]
    assert _ids(page.blocks) == ["L0", "L1", "R0", "R1"]


def test_a_mixed_document_is_decided_page_by_page():
    two_col = _page(_two_column_blocks(rows=3), number=1)
    one_col = _page([_block(f"T{i}", 100.0 + i * 60) for i in range(8)], number=2)
    assert columns.sort_pages([two_col, one_col], "auto") == 1
    assert columns.count_multi_column_pages([two_col, one_col]) == (1, 2)


# ---------------------------------------------------------------------------
# stage 3 uses it
# ---------------------------------------------------------------------------
def test_section_content_follows_the_columns():
    page = _page(_two_column_blocks(rows=3))
    (section,) = build_sections([page], column_layout="auto")
    assert section.content == "L0 L1 L2 R0 R1 R2"


def test_stage3_keeps_the_plain_order_for_a_profile_that_says_single():
    page = _page(_two_column_blocks(rows=3))
    (section,) = build_sections([page], column_layout="single")
    assert section.content == "L0 R0 L1 R1 L2 R2"


def test_stage3_leaves_a_single_column_document_alone():
    page = _page([_block(f"T{i}", 100.0 + i * 60) for i in range(8)])
    (section,) = build_sections([page], column_layout="auto")
    assert section.content == "T0 T1 T2 T3 T4 T5 T6 T7"


# ---------------------------------------------------------------------------
# the report reads a processed root, wherever it was typed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("argv,expected", [
    (["--report-columns", "data/pdf/processed"], "data/pdf/processed"),
    (["--report-columns", "in", "out"], "out"),
    (["--report-columns"], None),                     # falls back to the profile
])
def test_report_columns_takes_the_path_from_either_positional(monkeypatch, argv, expected):
    import sys as _sys

    from docpipe.preprocessing import pipeline

    seen = {}
    monkeypatch.setattr(pipeline, "report_columns", lambda root, **kw: seen.setdefault("root", root))
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    monkeypatch.setattr(_sys, "argv", ["prog", *argv])
    with pytest.raises(SystemExit):
        pipeline.main()
    if expected is None:
        assert seen["root"].name == "processed"       # the profile's own
    else:
        assert seen["root"] == Path(expected)


# ---------------------------------------------------------------------------
# a column that carries a list
# ---------------------------------------------------------------------------

def test_a_bulleted_column_is_still_a_column():
    """A list is typeset on two left edges — the bullet line and the indent its
    continuation takes. Demanding a single edge rejected the page, which was
    then read across the gutter and interleaved the two columns line by line."""
    blocks = []
    for i in range(10):
        y = 100.0 + i * 30.0
        blocks.append(_block(f"L{i}", y, LEFT))
        # every third right-hand block opens a bullet, the rest are indented
        x0 = RIGHT[0] if i % 3 == 0 else RIGHT[0] + 11.0
        blocks.append(_block(f"R{i}", y, (x0, RIGHT[1])))
    assert columns.find_gutters(blocks, WIDTH), "the gutter is plainly there"


def test_labels_scattered_around_a_chart_are_not_a_column():
    """The check still has to reject what it was written for: text that leaves
    clean vertical gaps without being typeset in a column."""
    blocks = [_block(f"L{i}", 100.0 + i * 30.0, LEFT) for i in range(10)]
    for i in range(10):
        x0 = RIGHT[0] + i * 9.0            # every label at its own indent
        blocks.append(_block(f"R{i}", 100.0 + i * 30.0, (x0, x0 + 60.0)))
    assert columns.find_gutters(blocks, WIDTH) == []


def test_two_edges_a_hair_apart_are_one_edge():
    """round(x / 4) put 306.0 and 306.4 into different buckets and counted the
    same indent twice."""
    column = [_block("a", 0.0, (306.0, 400.0)), _block("b", 0.0, (306.4, 400.0)),
              _block("c", 0.0, (305.8, 400.0))]
    assert columns._edge_clusters(column) == [3]
