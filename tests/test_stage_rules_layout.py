"""
The decisions of stage 2 (layout) are rules, and the stage decides by them
(owner request 2026-11-19, A1: "Die festen Werte werden Regeln mit dem
heutigen Wert als Standard").

The promises, each with a case that breaks it by construction:

1. Every rule of the stage has a default in the default profile's file that
   `rules.problem` takes, a title and a help; AND the kinds of region a rule
   may name are the labels of the model; AND the defaults are the values the
   code held, with the profiles' own caption length and opening words.
2. A region of the layout model counts by the confidence of its kind
   (`layout_class_min_scores`, `layout_default_min_score`,
   `layout_min_score`), AND regions overlapping by more than
   `layout_overlap_limit` are reduced to the more certain one, AND the kinds
   that make a crop are `table_classes` and `figure_classes`.
3. A page is processed by the kinds of its rules: what is removed
   (`furniture_classes`), what is a footnote (`footnote_classes`), how much of
   a text block must lie in a region (`text_suppress_overlap`), the margins of
   a crop, the kinds that are headings (`heading_classes`) and the row of a
   removed region (`heading_same_row_gap`), a figure blanked in a table
   (`mask_figures_in_tables`).
4. The resolutions the pages are rendered at are `layout_detect_dpi` and
   `crop_render_dpi`, AND a document is refused by the failed groups of pages
   `layout_failed_batches_allowed` allows.
5. A heading is found by its font by `font_headings` and the rules of its
   size, length, capitals, end marks and boldness; a caption by
   `caption_max_distance_pt`, `caption_not_across_heading`,
   `caption_max_words` and `heading_excluded_prefixes`.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from docpipe import rules
from docpipe.preprocessing import config, layout_captions
from docpipe.preprocessing.models import Block, PageData
from docpipe.profile import load_profile
from docpipe.ruleset import stage_layout

# Stage 2 cuts its crops with OpenCV and runs its model with torch, where
# the layout model runs. Neither is needed to decide by a rule: where one is
# missing a stand-in serves the import and is taken away again.
_STAND_INS = {}
if importlib.util.find_spec("cv2") is None:
    _STAND_INS["cv2"] = types.ModuleType("cv2")
if importlib.util.find_spec("torch") is None:
    import contextlib
    _torch = types.ModuleType("torch")
    _torch.bfloat16 = _torch.float16 = object()
    _torch.no_grad = contextlib.nullcontext
    _torch.tensor = lambda value, **more: value
    _STAND_INS["torch"] = _torch
sys.modules.update(_STAND_INS)
try:
    from docpipe.preprocessing import (headings, layout, layout_blocks,
                                       layout_model)
    from docpipe.preprocessing.layout_model import Detection
finally:
    for name in _STAND_INS:
        sys.modules.pop(name, None)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = json.loads((ROOT / "docpipe/builtin/default/rules.json")
                     .read_text(encoding="utf-8"))["rules"]


# -- 1: the rules, their defaults and the values the code held ----------------

@pytest.mark.parametrize("one", stage_layout.RULES, ids=lambda one: one.name)
def test_every_rule_has_a_default_a_title_and_a_help(one):
    assert one.tab == "stages" and one.group == stage_layout.GROUP
    assert one.title.strip() and len(one.help.split()) > 10
    assert one.name in DEFAULT
    assert rules.problem(one.name, DEFAULT[one.name]) is None


def test_the_kinds_a_rule_may_name_are_the_labels_of_the_model():
    assert set(stage_layout.LABELS) == set(config.PP_ID2LABEL.values())
    # the failure by construction: a kind the model does not have
    assert rules.problem("furniture_classes", ["header", "nonsense"]) \
        is not None
    assert rules.problem("table_classes", []) is not None   # tables: no empty


def test_the_defaults_are_the_values_the_code_held():
    scores = DEFAULT["layout_class_min_scores"]
    # the thresholds the code held, by the model's class number
    held = {0: 0.5, 1: 0.5, 2: 0.5, 3: 0.45, 4: 0.55, 5: 0.4, 6: 0.4,
            7: 0.5, 8: 0.5, 9: 0.5, 10: 0.5, 11: 0.5, 12: 0.5, 13: 0.5,
            14: 0.85, 15: 0.4, 16: 0.5, 17: 0.55, 18: 0.5, 19: 0.5, 20: 0.45,
            21: 0.85, 22: 0.65, 23: 0.65, 24: 0.5}
    assert set(scores) == set(config.PP_ID2LABEL.values())
    assert {lid: scores[config.PP_ID2LABEL[lid]] for lid in held} == held
    assert (DEFAULT["layout_min_score"], DEFAULT["layout_default_min_score"],
            DEFAULT["layout_overlap_limit"]) == (0.4, 0.4, 0.5)
    assert (DEFAULT["crop_render_dpi"], DEFAULT["layout_detect_dpi"],
            DEFAULT["layout_failed_batches_allowed"]) == (300, 150, 0)
    assert DEFAULT["furniture_classes"] == [
        "footer", "footer_image", "header", "header_image", "number"]
    assert DEFAULT["footnote_classes"] == ["footnote"]
    assert DEFAULT["table_classes"] == ["table"]
    assert DEFAULT["figure_classes"] == ["chart", "image"]
    assert DEFAULT["caption_classes"] == ["figure_title", "vision_footnote"]
    assert DEFAULT["heading_classes"] == ["doc_title", "paragraph_title"]
    assert DEFAULT["table_crop_margins_pt"] == {
        "left": 5.0, "top": 5.0, "right": 5.0, "bottom": 8.0}
    assert DEFAULT["figure_crop_margins_pt"]["bottom"] == 10.0
    assert (DEFAULT["font_heading_size_ratio"],
            DEFAULT["font_heading_min_chars"],
            DEFAULT["font_heading_max_chars"],
            DEFAULT["font_heading_caps_min_chars"]) == (1.2, 3, 90, 6)
    assert (DEFAULT["text_suppress_overlap"], DEFAULT["heading_same_row_gap"],
            DEFAULT["caption_max_distance_pt"]) == (0.9, 0.2, 60.0)


def test_each_profile_has_its_own_caption_length_and_opening_words():
    got = {name: rules.load(load_profile(name)) for name in
           ("default", "kwp", "scenarios")}
    assert [got[n]["caption_max_words"] for n in got] == [60, 45, 160]
    assert got["default"]["heading_excluded_prefixes"] == [
        "figure", "fig.", "table", "tab."]
    assert got["kwp"]["heading_excluded_prefixes"] == [
        "abbildung", "abb.", "tabelle", "tab."]
    assert got["scenarios"]["heading_excluded_prefixes"][-2:] == [
        "box", "plate"]


# -- 2: the layout model's regions --------------------------------------------

def _model_run(monkeypatch, found, **overlaid):
    """`infer_batch` on one image, the model's own post-processing standing
    in with *found* = [(score, class id, box)]."""
    monkeypatch.setattr(layout_model, "model_inputs",
                        lambda processor, images: {})
    monkeypatch.setattr(layout_model, "kept_detections",
                        lambda out, sizes, floor: [(
                            [s for s, _, _ in found], [i for _, i, _ in found],
                            [b for _, _, b in found])])
    image = types.SimpleNamespace(size=(100, 100))
    with rules.overlaid(**overlaid):
        return layout_model.infer_batch(
            [image], None, lambda **inputs: None, "cpu")[0]


def test_a_region_counts_by_the_confidence_of_its_kind(monkeypatch):
    found = [(0.5, 3, [0, 0, 10, 10]),        # a chart: needs 0.45
             (0.6, 14, [20, 0, 30, 10]),      # an image: needs 0.85
             (0.9, 14, [40, 0, 50, 10])]
    kept = _model_run(monkeypatch, found)
    assert [(d.label, d.score) for d in kept] == [("chart", 0.5),
                                                  ("image", 0.9)]
    scores = {**DEFAULT["layout_class_min_scores"], "image": 0.55}
    kept = _model_run(monkeypatch, found, layout_class_min_scores=scores)
    assert len(kept) == 3
    scores = {**DEFAULT["layout_class_min_scores"], "chart": 0.55}
    assert [d.label for d in _model_run(
        monkeypatch, found, layout_class_min_scores=scores)] == ["image"]


def test_a_kind_that_is_not_listed_has_the_default_confidence(monkeypatch):
    found = [(0.45, 3, [0, 0, 10, 10])]
    scores = {key: value for key, value
              in DEFAULT["layout_class_min_scores"].items()
              if key != "chart"}
    assert len(_model_run(monkeypatch, found,
                          layout_class_min_scores=scores)) == 1   # 0.45 >= 0.4
    assert _model_run(monkeypatch, found, layout_class_min_scores=scores,
                      layout_default_min_score=0.5) == []


def test_the_model_floor_is_asked_of_the_post_processing(monkeypatch):
    seen = []
    monkeypatch.setattr(layout_model, "model_inputs",
                        lambda processor, images: {})
    monkeypatch.setattr(layout_model, "kept_detections",
                        lambda out, sizes, floor: seen.append(floor) or [
                            ([], [], [])])
    image = types.SimpleNamespace(size=(100, 100))
    layout_model.infer_batch([image], None, lambda **inputs: None, "cpu")
    with rules.overlaid(layout_min_score=0.7):
        layout_model.infer_batch([image], None, lambda **inputs: None, "cpu")
    assert seen == [0.4, 0.7]


def test_regions_overlapping_by_more_than_the_limit_are_one(monkeypatch):
    found = [(0.95, 21, [0, 0, 10, 10]), (0.9, 21, [0, 0, 10, 9]),   # tables
             (0.88, 14, [0, 0, 10, 10])]                             # image
    kept = _model_run(monkeypatch, found)
    assert [d.score for d in kept] == [0.95]
    kept = _model_run(monkeypatch, found, layout_overlap_limit=1.0)
    assert [d.score for d in kept] == [0.95, 0.9, 0.88]


def test_the_kinds_that_make_a_crop_are_the_tables_and_the_figures():
    assert layout_model.media_labels() == {"table", "image", "chart"}
    with rules.overlaid(table_classes=["table", "seal"],
                        figure_classes=["image"]):
        assert layout_model.media_labels() == {"table", "seal", "image"}


# -- 3: a page ----------------------------------------------------------------

def _text(block_id, y, content, x0=50, x1=550, label=None):
    return Block(id=block_id, type="text", bbox=[x0, y, x1, y + 10],
                 content=content, layout_label=label)


def _page(*blocks):
    return PageData(page_number=3, width_pt=600, height_pt=800,
                    blocks=list(blocks))


def _process(page, detections, tmp_path):
    tally = layout_blocks.FootnoteTally()
    out, jobs = layout_blocks.process_page(page, None, 600, 800, None,
                                           detections, tmp_path, tally)
    return {block.id: block for block in out.blocks}, tally


def test_the_kinds_of_furniture_are_removed_and_the_others_stay(tmp_path):
    detections = [Detection("footer", 8, 0.9, [40, 760, 560, 795])]
    kept, _ = _process(_page(_text("f", 770, "Seite 12")), detections, tmp_path)
    assert "f" not in kept
    with rules.overlaid(furniture_classes=["header"]):
        kept, _ = _process(_page(_text("f", 770, "Seite 12")), detections,
                           tmp_path)
    assert "f" in kept


def test_the_kinds_of_footnote_keep_their_text_labelled(tmp_path):
    detections = [Detection("footnote", 10, 0.9, [40, 690, 560, 730])]
    kept, tally = _process(_page(_text("n", 700, "¹ ohne Industrie")),
                           detections, tmp_path)
    assert kept["n"].layout_label == "footnote" and tally.blocks == 1
    with rules.overlaid(footnote_classes=[]):
        kept, tally = _process(_page(_text("n", 700, "¹ ohne Industrie")),
                               detections, tmp_path)
    assert kept["n"].layout_label is None and tally.blocks == 0


def test_a_text_block_belongs_to_a_region_by_the_share_of_the_rule(tmp_path):
    # the block is 500 wide; the region covers its left 60 per cent
    detections = [Detection("footer", 8, 0.9, [0, 760, 350, 795])]
    kept, _ = _process(_page(_text("f", 770, "Seite 12", 50, 550)),
                       detections, tmp_path)
    assert "f" in kept                         # 300 of 500 pt: 0.6 < 0.9
    with rules.overlaid(text_suppress_overlap=0.5):
        kept, _ = _process(_page(_text("f", 770, "Seite 12", 50, 550)),
                           detections, tmp_path)
    assert "f" not in kept


def test_the_margins_of_a_crop_are_the_rules_four_numbers():
    assert layout_blocks._margins("table_crop_margins_pt") == (5.0, 5.0, 5.0,
                                                               8.0)
    assert layout_blocks._margins("figure_crop_margins_pt")[3] == 10.0
    with rules.overlaid(table_crop_margins_pt={
            "left": 1.0, "top": 2.0, "right": 3.0, "bottom": 4.0}):
        assert layout_blocks._margins("table_crop_margins_pt") == (
            1.0, 2.0, 3.0, 4.0)
    with rules.overlaid(table_crop_margins_pt={"left": 1.0}):
        with pytest.raises(ValueError, match="top"):
            layout_blocks._margins("table_crop_margins_pt")


def test_a_title_that_opens_like_a_caption_is_no_heading(tmp_path):
    from docpipe.preprocessing.layout_blocks import _text_from_bbox  # noqa: F401

    class Page:
        def get_text(self, mode, clip=None):
            return "Abbildung 3: Bedarf"

    detections = [Detection("paragraph_title", 17, 0.9, [40, 90, 560, 110])]
    out, _ = layout_blocks.process_page(
        _page(), Page(), 600, 800, None, detections, tmp_path)
    assert out.blocks == []                    # kwp: "abbildung" is excluded
    with rules.overlaid(heading_excluded_prefixes=["zzz"]):
        out, _ = layout_blocks.process_page(
            _page(), Page(), 600, 800, None, detections, tmp_path)
    assert [b.content for b in out.blocks] == ["Abbildung 3: Bedarf"]


class _Words:
    """A page whose text is *words* wherever a region is read."""

    def __init__(self, words=""):
        self.words = words

    def get_text(self, mode, clip=None):
        return self.words


def test_the_kinds_of_heading_are_those_of_the_rule(tmp_path):
    detections = [Detection("paragraph_title", 17, 0.9, [40, 90, 560, 110])]
    out, _ = layout_blocks.process_page(
        _page(), _Words("Wärmebedarf 2030"), 600, 800, None, detections,
        tmp_path)
    assert [b.content for b in out.blocks] == ["Wärmebedarf 2030"]
    # broken by construction: a kind the rule does not name is no heading
    with rules.overlaid(heading_classes=["doc_title"]):
        out, _ = layout_blocks.process_page(
            _page(), _Words("Wärmebedarf 2030"), 600, 800, None, detections,
            tmp_path)
    assert out.blocks == []


def test_a_heading_on_the_row_of_a_removed_region_is_no_heading(tmp_path):
    # a page head and a title side by side, on the very same row
    detections = [Detection("header", 12, 0.9, [40, 90, 290, 110]),
                  Detection("paragraph_title", 17, 0.9, [310, 90, 560, 110])]
    out, _ = layout_blocks.process_page(
        _page(), _Words("Kapitel 3"), 600, 800, None, detections, tmp_path)
    assert out.blocks == []
    # a gap of 0 asks more than a full overlap of the rows: it is a heading
    with rules.overlaid(heading_same_row_gap=0.0):
        out, _ = layout_blocks.process_page(
            _page(), _Words("Kapitel 3"), 600, 800, None, detections,
            tmp_path)
    assert [b.content for b in out.blocks] == ["Kapitel 3"]


def _table_and_figure(tmp_path):
    """A black page with a table and a figure inside it: the table's crop
    and the figure's block."""
    from PIL import Image
    image = Image.new("RGB", (600, 800), (0, 0, 0))
    detections = [Detection("table", 21, 0.9, [100, 100, 500, 500]),
                  Detection("image", 14, 0.9, [200, 200, 300, 300])]
    out, jobs = layout_blocks.process_page(
        _page(), _Words(), 600, 800, image, detections, tmp_path)
    table = next(job.crop_rgb for job in jobs if "_tbl" in job.block_id)
    figure = next(b for b in out.blocks if b.type == "image")
    return table, figure


def test_a_figure_inside_a_table_is_blanked_by_the_switch(tmp_path):
    # the figure's middle, (250, 250) on the page, is (155, 155) in the
    # table's crop, which starts at the table's margins, (95, 95)
    table, _ = _table_and_figure(tmp_path)
    assert list(table[155, 155]) == [255, 255, 255]
    assert list(table[55, 55]) == [0, 0, 0]          # the table itself
    with rules.overlaid(mask_figures_in_tables=False):
        table, _ = _table_and_figure(tmp_path)
    assert list(table[155, 155]) == [0, 0, 0]


def test_a_figure_is_cut_with_the_margins_of_its_rule(tmp_path):
    _, figure = _table_and_figure(tmp_path)
    assert figure.bbox == [195.0, 195.0, 305.0, 310.0]
    with rules.overlaid(figure_crop_margins_pt={
            "left": 0, "top": 0, "right": 0, "bottom": 0}):
        _, figure = _table_and_figure(tmp_path)
    assert figure.bbox == [200.0, 200.0, 300.0, 300.0]


# -- 4: resolutions and refusal -----------------------------------------------

class _Tensor:
    def to(self, device):
        return self


def _run_document(tmp_path, monkeypatch, fail=(), pages=14):
    import fitz
    from docpipe.preprocessing.page_text import extract_all_pages
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Seite {i + 1}")
    path = tmp_path / "plan.pdf"
    doc.save(path)
    seen = []
    calls = []

    def infer(images, processor, model, device, inputs=None):
        calls.append(len(images))
        if len(calls) in fail:
            raise RuntimeError("the model failed")
        return [[] for _ in images]

    def process(pg, fp, width, height, crop_img, dets, images_dir, footnotes):
        seen.append((width, crop_img.width))
        return pg, []

    monkeypatch.setattr(layout_model, "infer_batch", infer)
    monkeypatch.setattr(layout_blocks, "process_page", process)
    monkeypatch.setattr(layout, "LAYOUT_RENDER_PROCS", 0)
    pages_, fitz_pages, doc_, _ = extract_all_pages(path)
    try:
        layout.detect_layout_all_pages(
            pages_, fitz_pages, tmp_path / "out",
            (lambda images, return_tensors: {"pixel_values": _Tensor()},
             None, "cpu"))
    finally:
        doc_.close()
    return seen


def test_the_pages_are_rendered_at_the_resolutions_of_the_rules(tmp_path,
                                                                monkeypatch):
    (tmp_path / "a").mkdir()
    seen = _run_document(tmp_path / "a", monkeypatch, pages=1)
    assert seen == [(1240, 2480)]              # A4 at 150 and at 300 dpi
    (tmp_path / "b").mkdir()
    with rules.overlaid(layout_detect_dpi=72, crop_render_dpi=144):
        seen = _run_document(tmp_path / "b", monkeypatch, pages=1)
    assert seen == [(595, 1190)]
    (tmp_path / "c").mkdir()
    with rules.overlaid(layout_detect_dpi=100, crop_render_dpi=100):
        seen = _run_document(tmp_path / "c", monkeypatch, pages=1)
    assert seen == [(827, 827)]                # one rendering for both


def test_a_failed_group_of_pages_refuses_the_document_by_default(tmp_path,
                                                                 monkeypatch):
    with pytest.raises(layout.LayoutDetectionFailed):
        _run_document(tmp_path, monkeypatch, fail=(2,))


def test_a_document_may_have_as_many_failed_groups_as_the_rule_allows(
        tmp_path, monkeypatch):
    with rules.overlaid(layout_failed_batches_allowed=1):
        _run_document(tmp_path, monkeypatch, fail=(2,))      # one: allowed
    (tmp_path / "two").mkdir()
    with rules.overlaid(layout_failed_batches_allowed=1):
        with pytest.raises(layout.LayoutDetectionFailed):
            _run_document(tmp_path / "two", monkeypatch, fail=(1, 2))


# -- 5: headings and captions -------------------------------------------------

def test_a_heading_is_found_by_the_size_of_its_font():
    looks = headings._looks_like_heading
    assert looks("Wärmebedarf", 12.0, False, 10.0)          # 1.2 times
    assert not looks("Wärmebedarf", 11.0, False, 10.0)
    with rules.overlaid(font_heading_size_ratio=1.5):
        assert not looks("Wärmebedarf", 12.0, False, 10.0)
    with rules.overlaid(font_heading_size_ratio=1.05):
        assert looks("Wärmebedarf", 11.0, False, 10.0)


def test_a_bold_text_that_is_larger_is_a_heading_by_the_switch():
    looks = headings._looks_like_heading
    assert looks("Wärmebedarf", 10.5, True, 10.0)
    with rules.overlaid(bold_larger_is_heading=False):
        assert not looks("Wärmebedarf", 10.5, True, 10.0)


def test_a_heading_has_the_lengths_of_the_rules():
    looks = headings._looks_like_heading
    assert looks("Abc", 13.0, False, 10.0) and not looks("Ab", 13.0, False, 10.0)
    long = "Wärme " * 20
    assert not looks(long.strip(), 13.0, False, 10.0)
    with rules.overlaid(font_heading_max_chars=200):
        assert looks(long.strip(), 13.0, False, 10.0)
    with rules.overlaid(font_heading_min_chars=4):
        assert not looks("Abc", 13.0, False, 10.0)


def test_a_text_in_capitals_is_a_heading_from_the_rules_letters():
    looks = headings._looks_like_heading
    assert looks("ABCDEF", 10.0, False, 10.0)
    assert not looks("ABCDE", 10.0, False, 10.0)
    with rules.overlaid(font_heading_caps_min_chars=5):
        assert looks("ABCDE", 10.0, False, 10.0)


def test_running_text_is_no_heading_by_the_rules_end_marks():
    looks = headings._looks_like_heading
    assert not looks("Das ist ein Satz.", 13.0, False, 10.0)
    assert not looks("Ein Satz. Der nächste", 13.0, False, 10.0)
    with rules.overlaid(heading_prose_end_marks="!?"):
        assert looks("Das ist ein Satz.", 13.0, False, 10.0)
        assert looks("Ein Satz. Der nächste", 13.0, False, 10.0)
        assert not looks("Wirklich!", 13.0, False, 10.0)


def test_a_heading_by_font_is_promoted_by_the_switch():
    def pages():
        body = [_text(f"b{i}", 100 + 20 * i, "Fließtext " * 30) for i in range(3)]
        for block in body:
            block.font_size = 10.0
        title = _text("t", 50, "Wärmebedarf")
        title.font_size = 14.0
        return [_page(title, *body)]
    out = headings.promote_headings_by_font(pages())
    assert out[0].blocks[0].layout_label == "paragraph_title"
    with rules.overlaid(font_headings=False):
        out = headings.promote_headings_by_font(pages())
    assert out[0].blocks[0].layout_label is None


def _media_page(gap, between=False):
    table = Block(id="t", type="table", bbox=[50, 100, 550, 200])
    caption = _text("c", 200 + gap, "Tabelle 1: Bedarf", label="figure_title")
    blocks = [table, caption]
    if between:
        blocks.append(_text("h", 200 + gap / 2, "Kapitel",
                            label="paragraph_title"))
    return _page(*blocks)


def test_a_caption_is_taken_by_the_kinds_of_the_rules():
    [page] = layout_captions.resolve_captions([_media_page(10)])
    assert page.blocks[0].caption == "Tabelle 1: Bedarf"
    with rules.overlaid(caption_classes=["vision_footnote"],
                        caption_max_distance_pt=0):
        [page] = layout_captions.resolve_captions([_media_page(10)])
    assert page.blocks[0].caption is None


def test_a_plain_text_is_a_caption_within_the_rules_distance():
    def media():
        table = Block(id="t", type="table", bbox=[50, 100, 550, 200])
        return _page(table, _text("c", 270, "Tabelle 1: Bedarf"))   # 120 away
    [page] = layout_captions.resolve_captions([media()])
    assert page.blocks[0].caption is None
    with rules.overlaid(caption_max_distance_pt=200):
        [page] = layout_captions.resolve_captions([media()])
    assert page.blocks[0].caption == "Tabelle 1: Bedarf"


def test_a_caption_is_not_taken_across_a_heading_by_the_switch():
    [page] = layout_captions.resolve_captions([_media_page(100, between=True)])
    assert page.blocks[0].caption is None
    with rules.overlaid(caption_not_across_heading=False):
        [page] = layout_captions.resolve_captions(
            [_media_page(100, between=True)])
    assert page.blocks[0].caption == "Tabelle 1: Bedarf"


def test_a_text_is_a_caption_when_it_has_no_more_words_than_the_rule():
    assert config.caption_like("eins zwei drei")
    assert not config.caption_like("wort " * 46)            # kwp: 45
    assert config.caption_like("wort " * 45)
    with rules.overlaid(caption_max_words=2):
        assert not config.caption_like("eins zwei drei")
    with rules.overlaid(caption_max_words=100):
        assert config.caption_like("wort " * 46)


def test_the_kinds_of_heading_and_the_excluded_words_are_the_rules():
    assert config.title_exclude_prefixes() == ("abbildung", "abb.", "tabelle",
                                               "tab.")
    with rules.overlaid(heading_excluded_prefixes=["zzz"]):
        assert config.title_exclude_prefixes() == ("zzz",)
        assert headings._looks_like_heading("Abbildung 3", 13.0, False, 10.0)
    assert not headings._looks_like_heading("Abbildung 3", 13.0, False, 10.0)
