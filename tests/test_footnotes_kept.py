"""
The footnotes at the foot of a page stay text of the plan (owner decision
2026-11-17: "wir sollten die Fußnoten behalten"). Until then Stage 2 removed
them like a page number, and no request of the harvest could read what a
footnote says of a number ("¹ witterungsbereinigt", "* ohne Industrie").

The promises, each with a case that breaks it by construction:

1. Stage 2 keeps a text block that lies in a footnote box, labelled
   `footnote`, AND still removes a block in a footer or page number box, AND
   counts the footnote blocks it kept.
2. Stage 3 sets a footnote on a line of its own after the text of its page,
   a text segment marked as a footnote, AND where that text breaks off in a
   sentence that runs on to the next page, the footnote waits for the end of
   that sentence, AND a table, a figure or a new section ends the wait: the
   footnote stays in the section of its page, before the placeholder.
"""
import importlib.util
import sys
import types

from docpipe.preprocessing.models import Block, PageData
from docpipe.preprocessing.sections import build_sections

# Stage 2 cuts its crops with OpenCV, which runs where the layout model does
# and is not needed to sort text blocks: where it is missing, a stand-in
# serves the import and is taken away again, so that the tests that need the
# real one still skip.
_STAND_IN = importlib.util.find_spec("cv2") is None
if _STAND_IN:
    sys.modules["cv2"] = types.ModuleType("cv2")
try:
    from docpipe.preprocessing import layout_blocks
    from docpipe.preprocessing.layout_model import Detection
finally:
    if _STAND_IN:
        sys.modules.pop("cv2", None)


def text(block_id, y, content, label=None):
    return Block(id=block_id, type="text", bbox=[50, y, 550, y + 10],
                 content=content, layout_label=label)


def page(number, *blocks):
    return PageData(page_number=number, width_pt=600, height_pt=800,
                    blocks=list(blocks))


def title(block_id, y, content):
    return text(block_id, y, content, "paragraph_title")


def test_stage_2_keeps_a_footnote_and_removes_the_page_furniture(tmp_path):
    pg = page(3, text("b0", 100, "Der Bedarf liegt bei 1.234 GWh¹."),
              text("b1", 700, "¹ Witterungsbereinigt, ohne Industrie."),
              text("b2", 770, "Seite 12"))
    detections = [Detection("footnote", 10, 0.9, [40, 690, 560, 730]),
                  Detection("footer", 8, 0.9, [40, 760, 560, 795])]
    tally = layout_blocks.FootnoteTally()
    out, jobs = layout_blocks.process_page(pg, None, 600, 800, None,
                                           detections, tmp_path,
                                           footnotes=tally)
    by_id = {block.id: block for block in out.blocks}
    assert "b2" not in by_id                       # the footer is gone
    assert by_id["b1"].layout_label == "footnote"  # the footnote stays
    assert by_id["b0"].layout_label is None
    assert (tally.blocks, jobs) == (1, [])
    assert "kept 1 text block(s)" in tally.line()


def test_a_footnote_stands_on_a_line_of_its_own_after_its_page():
    sections = build_sections([
        page(1, title("t", 50, "Wärmebedarf"),
             text("a", 100, "Der Bedarf liegt bei 1.234 GWh¹."),
             text("f", 700, "¹ Witterungsbereinigt", "footnote")),
        page(2, text("b", 100, "Weiter geht es."))], "single")
    section = sections[-1]
    assert section.content == ("Der Bedarf liegt bei 1.234 GWh¹.\n"
                               "¹ Witterungsbereinigt\nWeiter geht es.")
    marked = [seg for seg in section.segments if seg.get("footnote")]
    assert marked == [{"page": 1, "kind": "text",
                       "text": "¹ Witterungsbereinigt",
                       "footnote": True, "bbox": [[50, 700, 550, 710]]}]


def test_a_footnote_waits_for_the_end_of_a_sentence_that_runs_on():
    sections = build_sections([
        page(1, title("t", 50, "Wärmebedarf"),
             text("a", 100, "Der Bedarf liegt bei"),
             text("f", 700, "¹ Witterungsbereinigt", "footnote")),
        page(2, text("b", 100, "rund 1.234 GWh im Jahr 2020."),
             text("c", 200, "Danach sinkt er."))], "single")
    assert sections[-1].content == (
        "Der Bedarf liegt bei rund 1.234 GWh im Jahr 2020.\n"
        "¹ Witterungsbereinigt\nDanach sinkt er.")


def test_a_table_or_a_new_section_ends_the_wait():
    table = Block(id="p1_tbl0", type="table", bbox=[50, 100, 550, 300],
                  path="images/p1_tbl0.png")
    sections = build_sections([
        page(1, title("t", 50, "Wärmebedarf"),
             text("a", 80, "Der Bedarf liegt bei"),
             text("f", 700, "¹ Witterungsbereinigt", "footnote")),
        page(2, table,
             text("g", 650, "² Stand 2022", "footnote")),
        page(3, title("u", 50, "Potenziale"),
             text("b", 100, "Neu."))], "single")
    first, second = sections[-2], sections[-1]
    assert first.content == ("Der Bedarf liegt bei\n¹ Witterungsbereinigt\n"
                             "[p1_tbl0]\n² Stand 2022")
    assert second.content == "Neu."
