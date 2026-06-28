"""Tests for Stage 2 geometry: IoU, NMS, cross-class suppression, bbox transforms."""
from scripts.preprocessing import stage2_layout as s2

D = s2._Detection


def test_compute_iou():
    assert s2._compute_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert s2._compute_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    assert abs(s2._compute_iou([0, 0, 10, 10], [5, 0, 15, 10]) - (50 / 150)) < 1e-9


def test_apply_nms_per_class_keeps_highest():
    dets = [
        D("table", 21, 0.9, [0, 0, 100, 100]),
        D("table", 21, 0.6, [5, 5, 105, 105]),    # overlaps the 0.9 box → dropped
        D("table", 21, 0.8, [300, 300, 400, 400]),  # separate → kept
    ]
    assert sorted(d.score for d in s2._apply_nms(dets, 0.5)) == [0.8, 0.9]


def test_apply_nms_disabled_at_threshold_one():
    dets = [D("table", 21, 0.9, [0, 0, 10, 10]), D("table", 21, 0.8, [0, 0, 10, 10])]
    assert s2._apply_nms(dets, 1.0) == dets


def test_cross_class_suppresses_lower_confidence_overlap():
    dets = [
        D("table", 21, 0.9, [0, 0, 100, 100]),
        D("image", 14, 0.6, [5, 5, 105, 105]),     # cross-class overlap → dropped
        D("image", 14, 0.8, [300, 300, 400, 400]),
    ]
    # order preserved, only the overlapping lower-confidence image removed
    assert s2._suppress_cross_class_media(dets, 0.5) == [dets[0], dets[2]]


def test_cross_class_keeps_non_overlapping_and_non_media():
    dets = [
        D("table", 21, 0.9, [0, 0, 10, 10]),
        D("image", 14, 0.9, [100, 100, 110, 110]),
        D("text", 22, 0.9, [0, 0, 10, 10]),         # non-media, never touched
    ]
    assert s2._suppress_cross_class_media(dets, 0.5) == dets


def test_bbox_px_to_pt_to_px_roundtrip_dual_dpi():
    pt = s2._bbox_px_to_pt([100, 200, 300, 400], 1000, 2000, 595.0, 842.0)
    px = s2._bbox_pt_to_px(pt, 595.0, 842.0, 2480, 3508)
    assert abs(px[0] / 2480 - 0.1) < 1e-3       # 100/1000 of the width
    assert abs(px[1] / 3508 - 0.1) < 1e-3       # 200/2000 of the height


def test_expand_bbox_clamps_to_page_bounds():
    out = s2._expand_bbox_pt([1, 1, 10, 10], (5, 5, 5, 5), 12.0, 12.0)
    assert out == [0.0, 0.0, 12.0, 12.0]


def test_overlap_fraction_is_asymmetric():
    assert s2._overlap_fraction([2, 2, 4, 4], [0, 0, 10, 10]) == 1.0   # small fully inside
    assert s2._overlap_fraction([0, 0, 10, 10], [100, 100, 110, 110]) == 0.0


def test_vertical_overlap_fraction():
    assert s2._vertical_overlap_fraction([0, 0, 1, 10], [5, 0, 6, 10]) == 1.0
    assert s2._vertical_overlap_fraction([0, 0, 1, 5], [0, 100, 1, 105]) == 0.0
