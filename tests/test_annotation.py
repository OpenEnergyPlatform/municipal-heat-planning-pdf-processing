"""Annotation workspace: label IO, IoU matching, evaluation, COCO export."""
import json

from scripts.annotation import common, evaluate as EV


def _box(cls, cx, cy, w, h):
    return {"cls": cls, "cx": cx, "cy": cy, "w": w, "h": h}


def test_label_roundtrip_and_clamping(tmp_path):
    p = tmp_path / "l.txt"
    common.write_labels(p, [_box(21, 0.5, 0.5, 0.2, 0.1),
                            _box(3, 1.2, 0.5, 0.2, 0.1),     # cx clamped to 1.0
                            _box(14, 0.5, 0.5, 0.0, 0.1)])   # zero width dropped
    boxes = common.read_labels(p)
    assert [b["cls"] for b in boxes] == [21, 3]
    assert boxes[1]["cx"] == 1.0


def test_match_page_tp_fp_fn_and_confusion():
    gt = [_box(21, 0.3, 0.3, 0.2, 0.2),      # matched, same class
          _box(3, 0.7, 0.7, 0.2, 0.2),       # matched but predicted as table
          _box(14, 0.1, 0.9, 0.1, 0.1)]      # missed entirely
    pred = [_box(21, 0.31, 0.30, 0.2, 0.2),
            _box(21, 0.7, 0.7, 0.2, 0.2),
            _box(22, 0.9, 0.1, 0.1, 0.1)]    # spurious
    m = EV.match_page(gt, pred)
    assert m["tp"] == [(21,)]
    # chart detected as table: the classic table<->chart confusion must be
    # reported as such, not silently as one FP plus one FN.
    assert m["confused"] == [(3, 21)]
    assert m["fn"] == [14]
    assert m["fp"] == [22]


def test_match_page_is_one_to_one():
    gt = [_box(22, 0.5, 0.5, 0.4, 0.4)]
    pred = [_box(22, 0.5, 0.5, 0.4, 0.4), _box(22, 0.52, 0.5, 0.4, 0.4)]
    m = EV.match_page(gt, pred)
    # One GT box must absorb only ONE prediction; the duplicate is an FP.
    assert len(m["tp"]) == 1 and m["fp"] == [22]


def _workspace(tmp_path, stem, gt, pred, confirmed=True, size=(1000, 1400)):
    for sub in ("labels", "preann", "meta"):
        (tmp_path / sub).mkdir(exist_ok=True)
    common.write_labels(tmp_path / "labels" / f"{stem}.txt", gt)
    common.write_labels(tmp_path / "preann" / f"{stem}.txt", pred)
    (tmp_path / "meta" / f"{stem}.json").write_text(json.dumps(
        {"document_id": 1, "page_number": 3, "width": size[0], "height": size[1]}))
    if confirmed:
        state = tmp_path / "editor_state.json"
        cur = json.loads(state.read_text())["confirmed"] if state.is_file() else []
        state.write_text(json.dumps({"confirmed": cur + [stem]}))


def test_evaluate_counts_only_confirmed_pages(tmp_path):
    _workspace(tmp_path, "a", [_box(21, 0.5, 0.5, 0.2, 0.2)],
               [_box(21, 0.5, 0.5, 0.2, 0.2)], confirmed=True)
    _workspace(tmp_path, "b", [_box(3, 0.5, 0.5, 0.2, 0.2)], [], confirmed=False)
    stats = EV.evaluate(tmp_path)
    # Unconfirmed pages are still uncorrected — scoring them would mistake
    # "not yet reviewed" for "the model was right".
    assert stats["pages"] == 1
    assert stats["tp"][21] == 1 and not stats["fn"]


def test_export_coco_converts_to_absolute_pixels(tmp_path):
    _workspace(tmp_path, "a", [_box(21, 0.5, 0.5, 0.2, 0.1)], [], size=(1000, 2000))
    out = tmp_path / "gt.json"
    n = EV.export_coco(tmp_path, out)
    coco = json.loads(out.read_text())
    assert n == 1 and len(coco["images"]) == 1
    assert coco["annotations"][0]["bbox"] == [400.0, 900.0, 200.0, 200.0]
    assert coco["categories"][21]["name"] == "table"


def test_class_metadata_is_consistent():
    assert len(common.CLASS_NAMES) == 25
    assert common.CLASS_NAMES[13] == "header_image"     # the port-artifact fix
    assert common.CLASS_NAMES[9] == "footer_image"
    assert all(0 <= i < 25 for i in common.EDITOR_CLASS_IDS)
