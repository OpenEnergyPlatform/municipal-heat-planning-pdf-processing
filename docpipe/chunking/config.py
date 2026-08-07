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

# Hard ceiling for one section's embedding text. Refinement splits sections
# above SECTION_MAX_WORDS, so this only catches what slipped through; it sits
# clear of MAX_TOKEN_LENGTH so a capped section is never silently truncated by
# the tokenizer instead.
SECTION_EMBED_MAX_WORDS = 1800
# Aggregate batch: MultiGPUEmbedder splits it round-robin across the replicas.
EMBEDDING_BATCH_SIZE = 32

FAISS_INDEX_FILE = "faiss_index.bin"

EMBEDDING_TYPE_SECTION_TEXT = "section_text"
EMBEDDING_TYPE_SECTION_TITLE = "section_title"
EMBEDDING_TYPE_TABLE_TEXT = "table_text"
EMBEDDING_TYPE_TABLE_VL = "table_vl"
EMBEDDING_TYPE_FIGURE_TEXT = "figure_text"
EMBEDDING_TYPE_FIGURE_VL = "figure_vl"