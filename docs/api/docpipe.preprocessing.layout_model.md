# docpipe.preprocessing.layout_model

`docpipe/preprocessing/layout_model.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

layout_model.py: The PP-DocLayoutV3 model of Stage 2 and the boxes it
detects.

A detection passes a global confidence filter, then a per-class threshold,
then per-class non-maximum suppression and cross-class suppression among
table and image boxes, so one region never yields two crops.

Author: Felix Vossel

## Classes

### Detection

```python
@dataclass
class Detection
```

A single post-processed detection box for one page.

Fields:

- `label: str`
- `label_id: int`
- `score: float`
- `bbox_px: list[float]`

## Functions

### load_model

```python
def load_model()
```

Returns (processor, model, device), downloading the weights on first run.
Call once and pass the tuple to detect_layout_all_pages() — reloading per
PDF re-reads the weights.

### boxes_intersect

```python
def boxes_intersect(box_a: list[float], box_b: list[float]) -> bool
```

True if the two [x0, y0, x1, y1] boxes overlap (touching edges excluded).

### model_inputs

```python
def model_inputs(processor, images: list)
```

The model's input tensors for *images*, resized and normalized on the
CPU. Built ahead of the batch in the prefetch thread, so the main thread
does not wait for it: 0.018 s a page on 8 cores.

### kept_detections

```python
def kept_detections(outputs, target_sizes: torch.Tensor,
                     threshold: float) -> list[tuple[list, list, list]]
```

(scores, labels, boxes) per image, of the queries scoring at least
*threshold*, in the model's reading order, boxes in the pixels of
*target_sizes* (height, width): what the processor's
post_process_object_detection returns for them. It also traces a polygon
around every box from the model's masks, one at a time on one core,
0.037 s a page, and Stage 2 never reads a polygon. Returned as Python
lists, so a page's detections cross from the GPU once.

### infer_batch

```python
def infer_batch(
    images: list,
    processor,
    model,
    device: str,
    inputs=None,
) -> list[list[Detection]]
```

Detections per input image, with the global pre-filter, per-class
thresholds, per-class NMS and cross-class media suppression applied.
Boxes are in the input images' pixel space. *inputs* are the batch's
`model_inputs` when they were built ahead, or the exception that
stopped them.

[Back to the index](../README.md)
