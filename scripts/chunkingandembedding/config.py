"""
config.py – Central configuration for the chunkingandembedding module.

Author: Felix Vossel
"""

FINAL_JSON = "results/structured_output_final.json"
IMAGES_JSON = "results/structured_output_images.json"
MERGED_JSON = "results/output.json"

EMBEDDING_MODEL = "Qwen/Qwen3-VL-Embedding-8B"
EMBEDDING_DIM = 4096
MAX_TOKEN_LENGTH = 16384
# Batch is split round-robin across the GPU replicas (see MultiGPUEmbedder), so
# this is the *aggregate* batch; with 4 H100s in bf16 that is ~8 items/GPU.
# Tune down if VL (image) batches ever approach VRAM limits.
EMBEDDING_BATCH_SIZE = 32

FAISS_INDEX_FILE = "faiss_index.bin"

EMBEDDING_TYPE_SECTION_TEXT = "section_text"
EMBEDDING_TYPE_SECTION_TITLE = "section_title"
EMBEDDING_TYPE_TABLE_TEXT = "table_text"
EMBEDDING_TYPE_TABLE_VL = "table_vl"
EMBEDDING_TYPE_FIGURE_TEXT = "figure_text"
EMBEDDING_TYPE_FIGURE_VL = "figure_vl"