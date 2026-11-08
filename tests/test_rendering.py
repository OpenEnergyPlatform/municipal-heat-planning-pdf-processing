"""Promise (owner decision 2026-11-08, "Hebel 2"): Stage 2 can render its
pages in worker processes, AND a page a worker renders is the same image,
pixel for pixel, as the one Stage 2 renders in its own process, at both
resolutions, AND the batches come back in the order of their pages, AND a page
a worker cannot render comes back as its error, AND while a batch is read
no more than *depth* + 1 after it are rendering."""
import hashlib

import fitz
import pytest
from PIL import Image

from docpipe.preprocessing import rendering
from docpipe.preprocessing.page_text import extract_all_pages
from docpipe.preprocessing.rendering import render_page_to_pil


def plan(tmp_path, pages=5):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72 + 20 * i), f"Seite {i + 1}: 1.234 MWh/a")
        page.draw_rect(fitz.Rect(100, 300, 300, 400 + 10 * i), fill=(0.2, 0.5, 0.8))
    path = tmp_path / "plan.pdf"
    doc.save(path)
    return path


def digest(image):
    return image.size, hashlib.sha256(image.tobytes()).hexdigest()


def as_image(rendered):
    width, height, samples = rendered
    return Image.frombytes("RGB", (width, height), samples)


def test_a_worker_renders_each_page_as_stage_2_does_in_order(tmp_path):
    path = str(plan(tmp_path))
    doc = fitz.open(path)
    got = list(rendering.batches(path, [[0, 1], [2, 3], [4]], (150, 300),
                                   size=2, depth=1))
    assert [len(b) for b in got] == [2, 2, 1]
    for number, rendered in zip(range(5), [p for b in got for p in b]):
        for dpi in (150, 300):
            assert digest(as_image(rendered[dpi])) == digest(
                render_page_to_pil(doc[number], dpi))
    # the failure by construction: a page the document does not have
    [[missing]] = list(rendering.batches(path, [[99]], (150,), 2, 1))
    assert isinstance(missing, str) and missing


def test_no_more_than_depth_batches_render_ahead(monkeypatch):
    submitted = []

    class Done:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

    class Recorder:
        def submit(self, fn, path, number, dpis):
            submitted.append(number)
            return Done(number)

    monkeypatch.setattr(rendering, "pool", lambda size: Recorder())
    batches = rendering.batches("x.pdf", [[0], [1], [2], [3]], (150,), 2, 1)
    assert next(batches) == [0]
    assert submitted == [0, 1, 2]        # the one read, and depth + 1 ahead
    assert next(batches) == [1]
    assert submitted == [0, 1, 2, 3]
    assert list(batches) == [[2], [3]]


@pytest.mark.parametrize("procs", [0, 2])
def test_stage_2_sees_the_same_pages_with_workers_as_without(tmp_path,
                                                             monkeypatch, procs):
    pytest.importorskip("cv2")               # Stage 2 runs where the model does
    pytest.importorskip("torch")
    from docpipe.preprocessing import layout, layout_blocks, layout_model
    path = plan(tmp_path, pages=14)          # two batches of 12
    seen = {}

    def process(pg, fp, width, height, crop_img, dets, images_dir, footnotes):
        seen[pg.page_number] = (width, height, digest(crop_img))
        return pg, []

    monkeypatch.setattr(layout_model, "infer_batch",
                        lambda images, *a, **k: [[] for _ in images])
    monkeypatch.setattr(layout_blocks, "process_page", process)
    monkeypatch.setattr(layout, "LAYOUT_RENDER_PROCS", procs)
    pages, fitz_pages, doc, failed = extract_all_pages(path)
    try:
        out = layout.detect_layout_all_pages(
            pages, fitz_pages, tmp_path / "out", (None, None, "cpu"))
    finally:
        doc.close()
    assert failed == 0 and len(out) == 14 and sorted(seen) == list(range(1, 15))
    expected = {}
    ref = fitz.open(path)
    for i, page in enumerate(ref):
        det = render_page_to_pil(page, layout.LAYOUT_DETECT_DPI)
        crop = render_page_to_pil(page, layout.PAGE_RENDER_DPI)
        expected[i + 1] = (det.width, det.height, digest(crop))
    assert seen == expected
