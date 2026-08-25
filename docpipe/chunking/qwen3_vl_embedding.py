"""
qwen3_vl_embedding.py – Qwen3-VL wrapper producing normalized text and
vision-language embeddings.

Author: Felix Vossel
"""
import torch
import torch.nn.functional as F
import unicodedata
import numpy as np
import logging

from PIL import Image
from dataclasses import dataclass
from threading import Thread
from typing import Optional, List, Union, Dict, Any
from transformers.models.qwen3_vl.modeling_qwen3_vl import Qwen3VLPreTrainedModel, Qwen3VLModel, Qwen3VLConfig
from transformers.models.qwen3_vl.processing_qwen3_vl import Qwen3VLProcessor
from transformers.modeling_outputs import ModelOutput
from transformers.processing_utils import Unpack
from transformers.utils import TransformersKwargs
from transformers.cache_utils import Cache
from qwen_vl_utils.vision_process import process_vision_info

logger = logging.getLogger(__name__)

MAX_LENGTH = 8192
IMAGE_BASE_FACTOR = 16
IMAGE_FACTOR = IMAGE_BASE_FACTOR * 2
MIN_PIXELS = 4 * IMAGE_FACTOR * IMAGE_FACTOR
MAX_PIXELS = 1800 * IMAGE_FACTOR * IMAGE_FACTOR
FPS = 1
MAX_FRAMES = 64
FRAME_MAX_PIXELS = 768 * IMAGE_FACTOR * IMAGE_FACTOR
MAX_TOTAL_PIXELS = 10 * FRAME_MAX_PIXELS
PAD_TOKEN = "<|endoftext|>"


@dataclass
class Qwen3VLForEmbeddingOutput(ModelOutput):
    """Output structure for the embedding model forward pass."""
    last_hidden_state: Optional[torch.FloatTensor] = None
    attention_mask: Optional[torch.Tensor] = None


class Qwen3VLForEmbedding(Qwen3VLPreTrainedModel):
    """Qwen3-VL model wrapper that returns hidden states instead of logits."""
    _checkpoint_conversion_mapping = {}
    accepts_loss_kwargs = False
    config: Qwen3VLConfig

    def __init__(self, config):
        super().__init__(config)
        self.model = Qwen3VLModel(config)
        self.post_init()

    def get_input_embeddings(self):
        return self.model.get_input_embeddings()

    def set_input_embeddings(self, value):
        self.model.set_input_embeddings(value)

    def set_decoder(self, decoder):
        self.model.set_decoder(decoder)

    def get_decoder(self):
        return self.model.get_decoder()

    def get_video_features(
        self,
        pixel_values_videos: torch.FloatTensor,
        video_grid_thw: Optional[torch.LongTensor] = None
    ):
        return self.model.get_video_features(pixel_values_videos, video_grid_thw)

    def get_image_features(
        self,
        pixel_values: torch.FloatTensor,
        image_grid_thw: Optional[torch.LongTensor] = None
    ):
        return self.model.get_image_features(pixel_values, image_grid_thw)

    @property
    def language_model(self):
        return self.model.language_model

    @property
    def visual(self):
        return self.model.visual

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
    ) -> Union[tuple, Qwen3VLForEmbeddingOutput]:
        # Newer Qwen3-VL needs mm_token_type_ids for multimodal RoPE; text-only
        # batches and older processors omit it, so only pass it when present.
        extra = {}
        if mm_token_type_ids is not None:
            extra["mm_token_type_ids"] = mm_token_type_ids

        outputs = self.model(
            input_ids=input_ids,
            pixel_values=pixel_values,
            pixel_values_videos=pixel_values_videos,
            image_grid_thw=image_grid_thw,
            video_grid_thw=video_grid_thw,
            position_ids=position_ids,
            attention_mask=attention_mask,
            past_key_values=None,
            inputs_embeds=inputs_embeds,
            cache_position=None,
            use_cache=False,
            **extra,
        )
        return Qwen3VLForEmbeddingOutput(
            last_hidden_state=outputs.last_hidden_state,
            attention_mask=attention_mask,
        )


def sample_frames(frames: List[Union[str, Image.Image]], num_segments: int, max_segments: int) -> List[str]:
    """Sample evenly spaced frames from a frame list."""
    duration = len(frames)
    frame_id_array = np.linspace(0, duration - 1, num_segments, dtype=int)
    frame_id_list = frame_id_array.tolist()
    last_frame_id = frame_id_list[-1]

    sampled_frames = []
    for frame_idx in frame_id_list:
        try:
            sampled_frames.append(frames[frame_idx])
        except Exception:
            break
    while len(sampled_frames) < num_segments:
        sampled_frames.append(frames[last_frame_id])
    return sampled_frames[:max_segments]


class Qwen3VLEmbedder:
    """Embedder for Qwen3-VL model processing text, images, and videos."""

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
    ):
        if device is None:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            device = torch.device(device)
        self.device = device

        self.max_length = max_length
        self.min_pixels = min_pixels
        self.max_pixels = max_pixels
        self.total_pixels = total_pixels
        self.fps = fps
        self.num_frames = num_frames
        self.max_frames = max_frames
        self.default_instruction = default_instruction

        # bf16 on GPU; fp32 on CPU, where bf16 matmuls are slow/unsupported.
        if torch_dtype is None:
            torch_dtype = torch.bfloat16 if device.type == "cuda" else torch.float32

        self.model = Qwen3VLForEmbedding.from_pretrained(
            model_name_or_path, trust_remote_code=True, torch_dtype=torch_dtype, **kwargs
        ).to(device)
        # from_pretrained may coerce the dtype; read it back, since float inputs
        # (pixel_values) must be cast to it or the visual tower hits a matmul
        # type error.
        self.param_dtype = next(self.model.parameters()).dtype
        self.processor = Qwen3VLProcessor.from_pretrained(
            model_name_or_path, padding_side='right'
        )
        self.model.eval()

    @torch.no_grad()
    def forward(self, inputs: Dict[str, Any]) -> Dict[str, torch.Tensor]:
        """Run a forward pass and return hidden states + attention mask."""
        inputs.pop("past_key_values", None)
        inputs.pop("use_cache", None)
        outputs = self.model(**inputs, use_cache=False, past_key_values=None)
        return {
            'last_hidden_state': outputs.last_hidden_state,
            'attention_mask': inputs.get('attention_mask')
        }

    def _truncate_tokens(self, token_ids: List[int], max_length: int) -> List[int]:
        """Truncate token sequence to specified max length, preserving special tokens."""
        if len(token_ids) <= max_length:
            return token_ids

        special_token_ids = set(self.processor.tokenizer.all_special_ids)
        num_special = sum(1 for token_idx in token_ids if token_idx in special_token_ids)
        num_non_special_to_keep = max_length - num_special

        final_token_ids = []
        non_special_kept_count = 0
        for token_idx in token_ids:
            if token_idx in special_token_ids:
                final_token_ids.append(token_idx)
            elif non_special_kept_count < num_non_special_to_keep:
                final_token_ids.append(token_idx)
                non_special_kept_count += 1
        return final_token_ids

    def format_model_input(
        self,
        text: Optional[str] = None,
        image: Optional[Union[str, Image.Image]] = None,
        video: Optional[Union[str, List[Union[str, Image.Image]]]] = None,
        instruction: Optional[str] = None,
        fps: Optional[float] = None,
        max_frames: Optional[int] = None
    ) -> List[Dict]:
        """Format a single input (text/image/video) into a chat conversation structure."""
        if instruction:
            instruction = instruction.strip()
            if instruction and not unicodedata.category(instruction[-1]).startswith('P'):
                instruction = instruction + '.'

        content = []
        conversation = [
            {"role": "system", "content": [{"type": "text", "text": instruction or self.default_instruction}]},
            {"role": "user", "content": content}
        ]

        if not text and not image and not video:
            content.append({'type': 'text', 'text': "NULL"})
            return conversation

        if video:
            video_content = None
            video_kwargs = {'total_pixels': self.total_pixels}
            if isinstance(video, list):
                video_content = video
                if self.num_frames is not None or self.max_frames is not None:
                    video_content = sample_frames(video_content, self.num_frames, self.max_frames)
                video_content = [
                    ('file://' + ele if isinstance(ele, str) else ele)
                    for ele in video_content
                ]
            elif isinstance(video, str):
                video_content = video if video.startswith(('http://', 'https://')) else 'file://' + video
                video_kwargs = {'fps': fps or self.fps, 'max_frames': max_frames or self.max_frames}
            else:
                raise TypeError(f"Unrecognized video type: {type(video)}")

            if video_content:
                content.append({
                    'type': 'video', 'video': video_content,
                    **video_kwargs
                })

        if image:
            image_content = None
            if isinstance(image, Image.Image):
                image_content = image
            elif isinstance(image, str):
                image_content = image if image.startswith(('http', 'oss')) else 'file://' + image
            else:
                raise TypeError(f"Unrecognized image type: {type(image)}")

            if image_content:
                content.append({
                    'type': 'image', 'image': image_content,
                    "min_pixels": self.min_pixels,
                    "max_pixels": self.max_pixels
                })

        if text:
            content.append({'type': 'text', 'text': text})

        return conversation

    def _preprocess_inputs(self, conversations: List[List[Dict]]) -> Dict[str, torch.Tensor]:
        """Tokenize and preprocess conversations for the model."""
        text = self.processor.apply_chat_template(
            conversations, add_generation_prompt=True, tokenize=False
        )

        try:
            images, video_inputs, video_kwargs = process_vision_info(
                conversations, image_patch_size=16,
                return_video_metadata=True, return_video_kwargs=True
            )
        except Exception as e:
            logger.error("Error in processing vision info: %s", e)
            images = None
            video_inputs = None
            video_kwargs = {'do_sample_frames': False}
            text = self.processor.apply_chat_template(
                [{'role': 'user', 'content': [{'type': 'text', 'text': 'NULL'}]}],
                add_generation_prompt=True, tokenize=False
            )

        if video_inputs is not None:
            videos, video_metadata = zip(*video_inputs)
            videos = list(videos)
            video_metadata = list(video_metadata)
        else:
            videos, video_metadata = None, None

        inputs = self.processor(
            text=text, images=images, videos=videos, video_metadata=video_metadata,
            truncation=True, max_length=self.max_length, padding=True,
            do_resize=False, return_tensors='pt',
            **video_kwargs
        )

        if inputs["input_ids"].shape[1] >= self.max_length:
            for i in range(inputs["input_ids"].shape[0]):
                seq_len = int(inputs["attention_mask"][i].sum())
                if seq_len >= self.max_length:
                    logger.warning(
                        "Input %d was truncated: %d tokens >= max_length %d",
                        i, seq_len, self.max_length,
                    )

        return inputs

    @staticmethod
    def _pooling_last(hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        """Pool last hidden state by attention mask."""
        flipped_tensor = attention_mask.flip(dims=[1])
        last_one_positions = flipped_tensor.argmax(dim=1)
        col = attention_mask.shape[1] - last_one_positions - 1
        row = torch.arange(hidden_state.shape[0], device=hidden_state.device)
        return hidden_state[row, col]

    def process(self, inputs: List[Dict[str, Any]], normalize: bool = True) -> torch.Tensor:
        """
        Embed a batch of inputs — dicts with 'text' and optionally
        'image'/'video' — into a (batch_size, hidden_dim) tensor, L2-normalized
        unless `normalize` is False.
        """
        conversations = [self.format_model_input(
            text=ele.get('text'),
            image=ele.get('image'),
            video=ele.get('video'),
            instruction=ele.get('instruction'),
            fps=ele.get('fps'),
            max_frames=ele.get('max_frames')
        ) for ele in inputs]

        processed_inputs = self._preprocess_inputs(conversations)
        processed_inputs = {
            k: (v.to(device=self.model.device, dtype=self.param_dtype)
                if torch.is_floating_point(v) else v.to(self.model.device))
            for k, v in processed_inputs.items()
        }

        outputs = self.forward(processed_inputs)
        embeddings = self._pooling_last(outputs['last_hidden_state'], outputs['attention_mask'])

        if normalize:
            embeddings = F.normalize(embeddings, p=2, dim=-1)

        return embeddings


def _input_size(item: Dict[str, Any]) -> int:
    """Rough token cost of one item, for balancing shards.

    Text length stands in for tokens: the ratio is near enough constant
    within a corpus, and only the ORDER matters here. An image is worth a
    fixed surcharge because a crop costs far more than its caption.
    """
    size = len(item.get("text") or "")
    return size + (4000 if item.get("image") is not None else 0)


class MultiGPUEmbedder:
    """Data-parallel wrapper: one Qwen3VLEmbedder replica per visible GPU.

    Each ``.process()`` call round-robin-splits the inputs across the replicas,
    runs the forwards concurrently in one thread each, and re-interleaves the
    results back into the original input order.

    Exposes the same ``process(inputs, normalize=True) -> Tensor`` interface as
    :class:`Qwen3VLEmbedder`; with a single device it degenerates to one replica.
    """

    def __init__(
        self,
        model_name_or_path: str,
        max_length: int = MAX_LENGTH,
        dtype: torch.dtype = torch.bfloat16,
        devices: Optional[List[str]] = None,
        **kwargs,
    ):
        if devices is None:
            n = torch.cuda.device_count()
            devices = [f"cuda:{i}" for i in range(n)] if n > 0 else ["cpu"]
        if not devices:
            devices = ["cpu"]

        logger.info("Loading %d embedder replica(s) on %s (dtype=%s)",
                    len(devices), devices, dtype)
        self.replicas: List[Qwen3VLEmbedder] = []
        for dev in devices:
            self.replicas.append(
                Qwen3VLEmbedder(
                    model_name_or_path, max_length=max_length,
                    device=dev, torch_dtype=dtype, **kwargs,
                )
            )
        self.devices = devices

    def process(self, inputs: List[Dict[str, Any]], normalize: bool = True) -> torch.Tensor:
        """Embed ``inputs`` across all replicas, returned on the CPU in order."""
        n = len(self.replicas)
        if n == 1 or len(inputs) <= 1:
            return self.replicas[0].process(inputs, normalize).to("cpu")

        # Shards are balanced by length, not by position. The processor pads
        # every shard to its own longest member and the threads join at the
        # end, so one 16k-token item dealt into a shard of 50-token items pads
        # that shard to 16k and every other GPU waits for it. Dealing the
        # longest out first keeps the shard totals close.
        order = sorted(range(len(inputs)), key=lambda i: _input_size(inputs[i]),
                       reverse=True)
        places: List[List[int]] = [[] for _ in range(n)]
        for rank, i in enumerate(order):
            places[rank % n].append(i)
        shards = [[inputs[i] for i in place] for place in places]
        outs: List[Optional[torch.Tensor]] = [None] * n
        errs: List[Optional[BaseException]] = [None] * n

        def _work(r: int) -> None:
            try:
                if shards[r]:
                    outs[r] = self.replicas[r].process(shards[r], normalize).to("cpu")
            except BaseException as exc:  # re-raised on the main thread below
                errs[r] = exc

        threads = [Thread(target=_work, args=(r,)) for r in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for exc in errs:
            if exc is not None:
                raise exc

        # Back into the caller's order: one indexed copy per shard instead of
        # a Python iteration and a separate 4096-element copy per item.
        sample = next(o for o in outs if o is not None)
        result = torch.empty((len(inputs), sample.shape[1]), dtype=sample.dtype)
        for r, place in enumerate(places):
            out = outs[r]
            if out is None:
                continue
            result[torch.tensor(place, dtype=torch.long)] = out
        return result