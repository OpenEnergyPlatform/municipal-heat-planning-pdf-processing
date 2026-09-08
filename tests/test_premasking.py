"""Tests for semantic pre-masking of figures embedded in table crops (Stage 2)."""
import conftest

conftest.needs_real("torch")

import pytest

from docpipe.preprocessing import stage2_layout as s2
from docpipe.preprocessing.models import PageData

# These tests need the real Pillow (the conftest stub has no Image.new()).
from PIL import Image
_HAS_PIL = hasattr(Image, "new")
pil_only = pytest.mark.skipif(not _HAS_PIL, reason="needs real Pillow")

D = s2._Detection


def test_boxes_intersect():
    assert s2._boxes_intersect([0, 0, 10, 10], [5, 5, 15, 15])      # overlap
    assert s2._boxes_intersect([0, 0, 100, 100], [10, 10, 20, 20])  # contained
    assert not s2._boxes_intersect([0, 0, 10, 10], [20, 20, 30, 30])  # disjoint
    assert not s2._boxes_intersect([0, 0, 10, 10], [10, 0, 20, 10])    # edge-touch only


@pil_only
def test_extract_crop_rgb_masks_regions():
    img = Image.new("RGB", (50, 50), (10, 20, 30))
    arr = s2._extract_crop_rgb(img, [0, 0, 50, 50], mask_bboxes_px=[[10, 10, 20, 20]])
    assert list(arr[15, 15]) == [255, 255, 255]     # inside masked region
    assert list(arr[5, 5]) == [10, 20, 30]          # outside (top-left)
    assert list(arr[30, 30]) == [10, 20, 30]        # outside (bottom-right)


@pil_only
def test_extract_crop_rgb_without_mask_is_untouched():
    img = Image.new("RGB", (50, 50), (10, 20, 30))
    arr = s2._extract_crop_rgb(img, [0, 0, 50, 50])
    assert list(arr[15, 15]) == [10, 20, 30]


@pil_only
def test_process_page_premasks_figure_inside_table(tmp_path):
    # 100x100 page, 1pt == 1px (det and crop image both 100), figure inside table.
    page = Image.new("RGB", (100, 100), (128, 128, 128))
    pg = PageData(page_number=1, width_pt=100.0, height_pt=100.0)
    dets = [
        D("table", 21, 0.9, [10, 10, 90, 90]),
        D("image", 14, 0.8, [20, 20, 40, 40]),   # embedded chart → must be masked
    ]
    _, crop_jobs = s2._process_page(pg, None, 100, 100, page, dets, tmp_path)

    table_job = next(j for j in crop_jobs if j.block_id.endswith("_tbl0"))
    arr = table_job.crop_rgb
    # Table crop origin is the expanded box (5,5); figure [20,40] → crop-local [15,35].
    assert list(arr[25, 25]) == [255, 255, 255]     # inside the masked figure
    assert list(arr[60, 60]) == [128, 128, 128]     # table content, untouched


@pil_only
def test_process_page_premasks_with_dual_dpi(tmp_path):
    # Detection image 100x100, crop image 200x200 (higher DPI), page 100pt:
    # masking must stay aligned because both boxes go det-px → pt → crop-px.
    crop_page = Image.new("RGB", (200, 200), (128, 128, 128))
    pg = PageData(page_number=1, width_pt=100.0, height_pt=100.0)
    dets = [
        D("table", 21, 0.9, [10, 10, 90, 90]),
        D("image", 14, 0.8, [20, 20, 40, 40]),
    ]
    _, crop_jobs = s2._process_page(pg, None, 100, 100, crop_page, dets, tmp_path)
    arr = next(j for j in crop_jobs if j.block_id.endswith("_tbl0")).crop_rgb
    assert list(arr[50, 50]) == [255, 255, 255]      # figure region (crop-local ~30..70)
    assert list(arr[150, 150]) == [128, 128, 128]    # table content, untouched


@pil_only
def test_process_page_masking_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(s2, "MASK_FIGURES_IN_TABLE_CROPS", False)
    page = Image.new("RGB", (100, 100), (128, 128, 128))
    pg = PageData(page_number=1, width_pt=100.0, height_pt=100.0)
    dets = [
        D("table", 21, 0.9, [10, 10, 90, 90]),
        D("image", 14, 0.8, [20, 20, 40, 40]),
    ]
    _, crop_jobs = s2._process_page(pg, None, 100, 100, page, dets, tmp_path)
    table_job = next(j for j in crop_jobs if j.block_id.endswith("_tbl0"))
    assert list(table_job.crop_rgb[25, 25]) == [128, 128, 128]   # not masked
