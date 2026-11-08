"""Promise (owner decision 2026-11-08): Stage 2's main process only runs the
model and reads its pages. Its detections are those of the processor's
post-processing, the same scores, labels and boxes in the same order, AND
only of queries scoring at least the threshold. The model's inputs are built
ahead of the batch, AND a batch whose inputs could not be built fails like a
batch the model could not run. Every crop of every page is written, by a
thread, AND a crop that cannot be written is not counted as written."""
import threading
from types import SimpleNamespace

import fitz
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")             # Stage 2 runs where the model does
torch = pytest.importorskip("torch")

from docpipe.preprocessing import crops, layout, layout_blocks, layout_model  # noqa: E402
from docpipe.preprocessing.page_text import extract_all_pages                # noqa: E402


def outputs(batch=2, queries=30, classes=5, seed=0):
    g = torch.Generator().manual_seed(seed)
    return SimpleNamespace(
        logits=torch.randn(batch, queries, classes, generator=g) * 3,
        pred_boxes=torch.rand(batch, queries, 4, generator=g) * 0.5 + 0.1,
        order_logits=torch.randn(batch, queries, queries, generator=g),
        out_masks=torch.randn(batch, queries, 40, 40, generator=g))


def test_the_detections_are_the_processors_without_polygons():
    module = pytest.importorskip(
        "transformers.models.pp_doclayout_v3.image_processing_pp_doclayout_v3")
    processor = module.PPDocLayoutV3ImageProcessor()
    sizes = torch.tensor([[1754, 1240], [1240, 1754]])
    for seed in range(3):
        out = outputs(seed=seed)
        library = processor.post_process_object_detection(out, threshold=0.3,
                                                          target_sizes=sizes)
        ours = layout_model.kept_detections(out, sizes, 0.3)
        for lib, (scores, labels, boxes) in zip(library, ours):
            assert scores == lib["scores"].tolist()
            assert labels == lib["labels"].tolist()
            assert boxes == lib["boxes"].tolist()
            assert scores and all(s >= 0.3 for s in scores)


def test_a_threshold_above_every_score_keeps_nothing():
    out = outputs()
    kept = layout_model.kept_detections(out, torch.tensor([[100, 100]] * 2), 1.01)
    assert kept == [([], [], []), ([], [], [])]


def plan(tmp_path, pages=14):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Seite {i + 1}")
    path = tmp_path / "plan.pdf"
    doc.save(path)
    return path


def run(tmp_path, monkeypatch, processor, process):
    monkeypatch.setattr(layout_blocks, "process_page", process)
    pages, fitz_pages, doc, _ = extract_all_pages(plan(tmp_path))
    try:
        return layout.detect_layout_all_pages(
            pages, fitz_pages, tmp_path / "out", (processor, None, "cpu"))
    finally:
        doc.close()


def test_every_crop_is_written_and_an_unwritable_one_is_not(tmp_path, monkeypatch):
    built = []

    def processor(images, return_tensors):
        built.append(len(images))
        return {"pixel_values": torch.zeros(len(images), 1)}

    def infer(images, processor, model, device, inputs=None):
        assert inputs is not None and len(inputs["pixel_values"]) == len(images)
        return [[] for _ in images]

    jobs = {}

    def process(pg, fp, width, height, crop_img, dets, images_dir, footnotes):
        images_dir.mkdir(parents=True, exist_ok=True)
        rgb = np.full((8 + pg.page_number, 9, 3), pg.page_number, dtype=np.uint8)
        # the failure by construction: page 7's crop goes to a missing folder
        where = images_dir / ("missing" if pg.page_number == 7 else "")
        job = crops.CropJob(f"p{pg.page_number}", where / f"p{pg.page_number}.png", rgb)
        jobs[pg.page_number] = job
        return pg, [job]

    monkeypatch.setattr(layout_model, "infer_batch", infer)
    written, threads = {}, set()
    real_write = crops.write_crop

    def write(job):
        threads.add(threading.current_thread().name.split("_")[0])
        written[job.block_id] = real_write(job)
        return written[job.block_id]

    monkeypatch.setattr(crops, "write_crop", write)
    run(tmp_path, monkeypatch, processor, process)
    assert built == [12, 2]
    assert written == {f"p{n}": n != 7 for n in range(1, 15)}
    assert threads == {"stage2-crops"}
    for n, job in jobs.items():
        if n == 7:
            assert not job.out_path.exists()
        else:
            assert job.out_path.read_bytes() == crops.encode_crop(job)[2]


def test_a_batch_whose_inputs_could_not_be_built_fails(tmp_path, monkeypatch):
    def processor(images, return_tensors):
        raise RuntimeError("no inputs")

    def model(**inputs):
        raise AssertionError("the model must not run without its inputs")

    monkeypatch.setattr(layout_blocks, "process_page",
                        lambda pg, *a: (pg, []))
    pages, fitz_pages, doc, _ = extract_all_pages(plan(tmp_path))
    try:
        with pytest.raises(layout.LayoutDetectionFailed):
            layout.detect_layout_all_pages(
                pages, fitz_pages, tmp_path / "out", (processor, model, "cpu"))
    finally:
        doc.close()
