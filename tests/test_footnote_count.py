"""What stage 2 removes as a footnote, and says that it did.

Promised: stage 2 removes every text block that lies in a box the layout model
classes as a footnote, and still does, AND it logs for each document one line
with the number of text blocks that were and the number of their characters,
AND a block that something else removed, or that no footnote box holds, is
not in that count, AND no page of the output has a field it did not have.

The stage is driven as it runs, with the model's boxes made up and the pages'
text blocks as the PDF's text layer would have given them. A page is 100 by
100 points and the detection image is the same size, so a box's pixels are
its points.
"""
import logging
import sys

import pytest

from docpipe.preprocessing import config
from docpipe.preprocessing.models import Block, PageData

LOGGER = "docpipe.preprocessing.stage2_layout"

# Two notes under one footnote box, a running header, a sentence of the body,
# and a table's own note: the last two are not footnotes.
NOTE_1 = "1 Source: the statistics office of the state, 2021."
NOTE_2 = "2 Own calculation after the guideline of 2020."
HEADER = "Municipal heat plan, draft"
BODY = "The district is heated mostly by gas boilers."


class _Image:
    width = 100
    height = 100


@pytest.fixture
def s2(monkeypatch):
    """The stage module. Without the real torch its two dtypes are the only
    thing the import reads from it, and a stand-in gets them for the test."""
    torch = sys.modules["torch"]
    for dtype in ("bfloat16", "float16"):
        if not hasattr(torch, dtype):
            monkeypatch.setattr(torch, dtype, dtype, raising=False)
    from docpipe.preprocessing import stage2_layout
    monkeypatch.setattr(stage2_layout, "_render_page_to_pil",
                        lambda fp, dpi: _Image())
    monkeypatch.setattr(stage2_layout, "LAYOUT_BATCH_SIZE", 12)
    monkeypatch.setattr(stage2_layout, "_text_from_bbox",
                        lambda fp, bbox: "Note: the table's own note")
    return stage2_layout


def _text(block_id, bbox, content):
    return Block(id=block_id, type="text", bbox=bbox, content=content)


def _page(number, blocks):
    return PageData(page_number=number, width_pt=100.0, height_pt=100.0,
                    blocks=blocks)


def _run(s2, monkeypatch, tmp_path, pages, boxes, caplog):
    """Stage 2 over *pages*; *boxes* is one list of detections per page."""
    monkeypatch.setattr(s2, "_infer_batch", lambda images, *a: list(boxes))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        out = s2.detect_layout_all_pages(
            pages, [object()] * len(pages), tmp_path, (None, None, "cpu"))
    lines = [r.getMessage() for r in caplog.records
             if r.name == LOGGER and "footnote class" in r.getMessage()]
    return out, lines


def _page_with_two_notes():
    return _page(1, [
        _text("a", [10, 2, 90, 6], HEADER),
        _text("b", [10, 10, 90, 20], BODY),
        _text("c", [10, 40, 90, 45], "Source line of the table"),
        _text("d", [10, 80, 90, 85], NOTE_1),
        _text("e", [10, 87, 90, 92], NOTE_2),
    ])


def _boxes_of_page_one(s2):
    D = s2._Detection
    return [
        D("header", 12, 0.9, [0, 0, 100, 8]),
        D("vision_footnote", 24, 0.9, [5, 38, 95, 47]),
        D("footnote", 10, 0.9, [5, 78, 95, 95]),
    ]


def test_two_notes_on_one_page_are_removed_and_counted(
        s2, monkeypatch, tmp_path, caplog):
    page_one, page_two = _page_with_two_notes(), _page(2, [
        _text("f", [10, 10, 90, 20], BODY)])
    out, lines = _run(s2, monkeypatch, tmp_path, [page_one, page_two],
                      [_boxes_of_page_one(s2), []], caplog)

    kept = [b.content for b in out[0].blocks if b.type == "text"]
    assert NOTE_1 not in kept and NOTE_2 not in kept        # still removed
    assert BODY in kept
    assert lines == [
        f"Stage 2: the footnote class removed 2 text block(s) with "
        f"{len(NOTE_1) + len(NOTE_2)} character(s)"]


def test_a_document_without_a_footnote_says_so(
        s2, monkeypatch, tmp_path, caplog):
    out, lines = _run(s2, monkeypatch, tmp_path,
                      [_page(1, [_text("a", [10, 10, 90, 20], BODY)])],
                      [[]], caplog)
    assert [b.content for b in out[0].blocks] == [BODY]
    assert lines == ["Stage 2: the footnote class removed 0 text block(s) "
                     "with 0 character(s)"]


def test_the_line_is_one_for_the_document_and_not_one_for_a_page(
        s2, monkeypatch, tmp_path, caplog):
    """Three pages, two of them with a note: one line, with the sum."""
    D = s2._Detection
    note = [D("footnote", 10, 0.9, [5, 78, 95, 95])]
    pages = [_page(n, [_text(f"n{n}", [10, 80, 90, 85], NOTE_1)])
             for n in (1, 2)] + [_page(3, [])]
    _out, lines = _run(s2, monkeypatch, tmp_path, pages,
                       [note, note, []], caplog)
    assert lines == [
        f"Stage 2: the footnote class removed 2 text block(s) with "
        f"{2 * len(NOTE_1)} character(s)"]


def test_what_something_else_removes_is_not_counted(
        s2, monkeypatch, tmp_path, caplog):
    """Four of the five text blocks leave the page: the header, the line the
    table's note box replaces, and the two footnotes. Only the last two are
    footnotes."""
    out, lines = _run(s2, monkeypatch, tmp_path, [_page_with_two_notes()],
                      [_boxes_of_page_one(s2)], caplog)
    ids = {b.id for b in out[0].blocks if b.type == "text"}
    assert ids == {"b", "p0_cap0"}          # a, c, d and e are gone
    assert "removed 2 text block(s)" in lines[0]


# The other classes stage 2 takes text off a page for. Written out and not
# derived from the config: a class added to the footnote set would otherwise
# drop out of the cases that say it is not one.
OTHER_REMOVED_CLASSES = ["header", "header_image", "footer", "footer_image",
                         "number"]


def test_the_other_removed_classes_are_all_of_them():
    assert set(OTHER_REMOVED_CLASSES) | {"footnote"} == config.SUPPRESS_CLASSES


@pytest.mark.parametrize("label", OTHER_REMOVED_CLASSES)
def test_text_in_the_box_of_another_removed_class_is_removed_and_not_counted(
        label, s2, monkeypatch, tmp_path, caplog):
    """A page number or a running footer goes off the page like a footnote
    does, and is not a footnote: widening the class set would count it."""
    label_id = next(i for i, name in config.PP_ID2LABEL.items()
                    if name == label)
    note = _text("n", [10, 80, 90, 85], NOTE_1)
    out, lines = _run(s2, monkeypatch, tmp_path, [_page(1, [note])],
                      [[s2._Detection(label, label_id, 0.9,
                                      [5, 78, 95, 95])]], caplog)
    assert out[0].blocks == []                          # removed all the same
    assert lines == ["Stage 2: the footnote class removed 0 text block(s) "
                     "with 0 character(s)"]


def test_a_block_the_box_does_not_hold_is_neither_removed_nor_counted(
        s2, monkeypatch, tmp_path, caplog):
    """Half of it lies in the box: under the bar for a removal, so it stays,
    and it is not a removed footnote either."""
    D = s2._Detection
    half = _text("h", [10, 70, 90, 80], "A line half in the box")
    held = _text("k", [10, 82, 90, 87], NOTE_1)
    out, lines = _run(s2, monkeypatch, tmp_path, [_page(1, [half, held])],
                      [[D("footnote", 10, 0.9, [5, 75, 95, 95])]], caplog)
    assert [b.content for b in out[0].blocks] == ["A line half in the box"]
    assert f"removed 1 text block(s) with {len(NOTE_1)} character(s)" \
        in lines[0]


def test_a_box_over_no_text_is_not_a_removed_block(
        s2, monkeypatch, tmp_path, caplog):
    """A page without a text layer has a footnote box and no text block in
    it. Counting the boxes would say one."""
    D = s2._Detection
    _out, lines = _run(s2, monkeypatch, tmp_path, [_page(1, [])],
                       [[D("footnote", 10, 0.9, [5, 78, 95, 95])]], caplog)
    assert lines == ["Stage 2: the footnote class removed 0 text block(s) "
                     "with 0 character(s)"]


def test_a_document_stage_2_refuses_has_no_count(
        s2, monkeypatch, tmp_path, caplog):
    """A batch that never reached the model drops the whole document: what
    the other batches counted is not a number worth reading."""
    monkeypatch.setattr(s2, "LAYOUT_BATCH_SIZE", 1)
    calls = []

    def flaky(images, *a):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("out of memory")
        return [[s2._Detection("footnote", 10, 0.9, [5, 78, 95, 95])]]

    monkeypatch.setattr(s2, "_infer_batch", flaky)
    pages = [_page(n, [_text(f"n{n}", [10, 80, 90, 85], NOTE_1)])
             for n in (1, 2)]
    with caplog.at_level(logging.INFO, logger=LOGGER):
        with pytest.raises(s2.LayoutDetectionFailed):
            s2.detect_layout_all_pages(pages, [object()] * 2, tmp_path,
                                       (None, None, "cpu"))
    assert not [r for r in caplog.records
                if "footnote class" in r.getMessage()]


def test_the_output_has_no_field_it_did_not_have(
        s2, monkeypatch, tmp_path, caplog):
    """What goes to pages.json is the page as it was: this and nothing more,
    no count on the page and none on a block."""
    out, _lines = _run(s2, monkeypatch, tmp_path, [_page_with_two_notes()],
                       [_boxes_of_page_one(s2)], caplog)
    assert out[0].to_dict() == {
        "page_number": 1, "width_pt": 100.0, "height_pt": 100.0,
        "blocks": [
            {"id": "b", "type": "text", "bbox": [10, 10, 90, 20],
             "content": BODY},
            {"id": "p0_cap0", "type": "text", "bbox": [5.0, 38.0, 95.0, 47.0],
             "content": "Note: the table's own note", "confidence": 0.9,
             "layout_label": "vision_footnote"},
        ]}


def test_the_footnote_class_is_still_one_that_is_removed():
    """The count is of the removal. If the class stopped being a removed one,
    nothing would be counted and nothing removed, and the line would read as
    a document without footnotes."""
    assert config.FOOTNOTE_CLASSES
    assert config.FOOTNOTE_CLASSES <= config.SUPPRESS_CLASSES
    assert "vision_footnote" not in config.SUPPRESS_CLASSES
