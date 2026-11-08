# docpipe.preprocessing.crops

`docpipe/preprocessing/crops.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

crops.py: Cuts a table or image out of its page and writes it as PNG.

Author: Felix Vossel

## Classes

### CropJob

```python
@dataclass
class CropJob
```

Everything needed to encode and write one detected region as PNG.

Fields:

- `block_id: str`
- `out_path: Path`
- `crop_rgb: np.ndarray`

## Functions

### extract_crop_rgb

```python
def extract_crop_rgb(
    image: Image.Image,
    bbox_px: list[float],
    mask_bboxes_px: Optional[list[list[float]]] = None,
) -> Optional[np.ndarray]
```

RGB crop of *bbox_px* from *image*, or None if the crop would be
degenerate. Boxes in *mask_bboxes_px* — which must be in the same
image-pixel space as *bbox_px*, not crop-local — are whited out.

### encode_crop

```python
def encode_crop(job: CropJob) -> tuple[str, Path, bytes]
```

Encodes a crop RGB array as PNG bytes.

### write_crop

```python
def write_crop(job: CropJob) -> bool
```

Encodes one crop as PNG and writes it to disk; True on success.

[Back to the index](../README.md)
