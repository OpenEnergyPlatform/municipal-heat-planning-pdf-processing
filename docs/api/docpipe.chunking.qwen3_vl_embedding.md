# docpipe.chunking.qwen3_vl_embedding

`docpipe/chunking/qwen3_vl_embedding.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

qwen3_vl_embedding.py – Qwen3-VL wrapper producing normalized text and
vision-language embeddings.

Author: Felix Vossel

## Classes

### Qwen3VLForEmbeddingOutput

```python
@dataclass
class Qwen3VLForEmbeddingOutput(ModelOutput)
```

Output structure for the embedding model forward pass.

Fields:

- `last_hidden_state: Optional[torch.FloatTensor] = None`
- `attention_mask: Optional[torch.Tensor] = None`

### Qwen3VLForEmbedding

```python
class Qwen3VLForEmbedding(Qwen3VLPreTrainedModel)
```

Qwen3-VL model wrapper that returns hidden states instead of logits.

Fields:

- `config: Qwen3VLConfig`

#### Qwen3VLForEmbedding.\_\_init\_\_

```python
def __init__(self, config)
```

#### Qwen3VLForEmbedding.get_input_embeddings

```python
def get_input_embeddings(self)
```

#### Qwen3VLForEmbedding.set_input_embeddings

```python
def set_input_embeddings(self, value)
```

#### Qwen3VLForEmbedding.set_decoder

```python
def set_decoder(self, decoder)
```

#### Qwen3VLForEmbedding.get_decoder

```python
def get_decoder(self)
```

#### Qwen3VLForEmbedding.get_video_features

```python
def get_video_features(
    self,
    pixel_values_videos: torch.FloatTensor,
    video_grid_thw: Optional[torch.LongTensor] = None
)
```

#### Qwen3VLForEmbedding.get_image_features

```python
def get_image_features(
    self,
    pixel_values: torch.FloatTensor,
    image_grid_thw: Optional[torch.LongTensor] = None
)
```

#### Qwen3VLForEmbedding.language_model

```python
@property
def language_model(self)
```

#### Qwen3VLForEmbedding.visual

```python
@property
def visual(self)
```

#### Qwen3VLForEmbedding.forward

```python
def forward(
    self,
    input_ids: torch.LongTensor = None,
    attention_mask: Optional[torch.Tensor] = None,
    position_ids: Optional[torch.LongTensor] = None,
    past_key_values: Optional[Cache] = None,
    inputs_embeds: Optional[torch.FloatTensor] = None,
    pixel_values: Optional[torch.Tensor] = None,
    pixel_values_videos: Optional[torch.FloatTensor] = None,
    image_grid_thw: Optional[torch.LongTensor] = None,
    video_grid_thw: Optional[torch.LongTensor] = None,
    mm_token_type_ids: Optional[torch.Tensor] = None,
    cache_position: Optional[torch.LongTensor] = None,
    logits_to_keep: Union[int, torch.Tensor] = 0,
    **kwargs: Unpack[TransformersKwargs],
) -> Union[tuple, Qwen3VLForEmbeddingOutput]
```

### Qwen3VLEmbedder

```python
class Qwen3VLEmbedder
```

Embedder for Qwen3-VL model processing text, images, and videos.

#### Qwen3VLEmbedder.\_\_init\_\_

```python
def __init__(
    self,
    model_name_or_path: str,
    max_length: int = MAX_LENGTH,
    min_pixels: int = MIN_PIXELS,
    max_pixels: int = MAX_PIXELS,
    total_pixels: int = MAX_TOTAL_PIXELS,
    fps: float = FPS,
    num_frames: int = MAX_FRAMES,
    max_frames: int = MAX_FRAMES,
    default_instruction: str = "Represent the user's input.",
    device: Optional[Union[str, torch.device]] = None,
    torch_dtype: Optional[torch.dtype] = None,
    **kwargs
)
```

#### Qwen3VLEmbedder.forward

```python
@torch.no_grad()
def forward(self, inputs: Dict[str, Any]) -> Dict[str, torch.Tensor]
```

Run a forward pass and return hidden states + attention mask.

#### Qwen3VLEmbedder.format_model_input

```python
def format_model_input(
    self,
    text: Optional[str] = None,
    image: Optional[Union[str, Image.Image]] = None,
    video: Optional[Union[str, List[Union[str, Image.Image]]]] = None,
    instruction: Optional[str] = None,
    fps: Optional[float] = None,
    max_frames: Optional[int] = None
) -> List[Dict]
```

Format a single input (text/image/video) into a chat conversation structure.

#### Qwen3VLEmbedder.process

```python
def process(self, inputs: List[Dict[str, Any]], normalize: bool = True) -> torch.Tensor
```

Embed a batch of inputs — dicts with 'text' and optionally
'image'/'video' — into a (batch_size, hidden_dim) tensor, L2-normalized
unless `normalize` is False.

### MultiGPUEmbedder

```python
class MultiGPUEmbedder
```

Data-parallel wrapper: one Qwen3VLEmbedder replica per visible GPU.

Each ``.process()`` call round-robin-splits the inputs across the replicas,
runs the forwards concurrently in one thread each, and re-interleaves the
results back into the original input order.

Exposes the same ``process(inputs, normalize=True) -> Tensor`` interface as
:class:`Qwen3VLEmbedder`; with a single device it degenerates to one replica.

#### MultiGPUEmbedder.\_\_init\_\_

```python
def __init__(
    self,
    model_name_or_path: str,
    max_length: int = MAX_LENGTH,
    dtype: torch.dtype = torch.bfloat16,
    devices: Optional[List[str]] = None,
    **kwargs,
)
```

#### MultiGPUEmbedder.process

```python
def process(self, inputs: List[Dict[str, Any]], normalize: bool = True) -> torch.Tensor
```

Embed ``inputs`` across all replicas, returned on the CPU in order.

## Functions

### sample_frames

```python
def sample_frames(frames: List[Union[str, Image.Image]], num_segments: int, max_segments: int) -> List[str]
```

Sample evenly spaced frames from a frame list.

[Back to the index](../README.md)
