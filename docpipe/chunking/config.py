"""
config.py – Central configuration for the chunkingandembedding module.

Author: Felix Vossel
"""

from docpipe.artifacts import (DOCUMENT_JSON,            # noqa: F401  (re-exported)
                               SECTIONS_JSON, SECTIONS_REFINED_JSON, VISUALS_JSON)

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

# Documents prepared in parallel while the GPUs embed. Reading a merged JSON and
# asking the DB what the document already has took 6.6 s each in the last full
# run — 91 of 184 minutes with every GPU idle, because the whole corpus was
# prepared before the first batch went out.
EMBED_PREPARE_WORKERS = 8

# Items collected before a chunk goes to the GPUs. Large enough that sorting by
# length still fills batches with comparable sequences, small enough that the
# GPUs start long before the last document is read.
EMBED_FLUSH_ITEMS = 4096

FAISS_INDEX_FILE = "faiss_index.bin"

EMBEDDING_TYPE_SECTION_TEXT = "section_text"
EMBEDDING_TYPE_SECTION_TITLE = "section_title"
EMBEDDING_TYPE_TABLE_TEXT = "table_text"
EMBEDDING_TYPE_TABLE_VL = "table_vl"
EMBEDDING_TYPE_FIGURE_TEXT = "figure_text"
EMBEDDING_TYPE_FIGURE_VL = "figure_vl"