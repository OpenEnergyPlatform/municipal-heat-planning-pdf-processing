"""
config.py – Central configuration for the chunkingandembedding module.

Author: Felix Vossel
"""

from docpipe.artifacts import (DOCUMENT_JSON,            # noqa: F401  (re-exported)
                               PAGE_TRANSCRIPTION_REPORT_JSON,
                               SECTIONS_JSON, SECTIONS_REFINED_JSON, VISUALS_JSON)

# One definition, imported — not a second copy. These were declared here as
# literals and again in docpipe/embedding/config.py from the environment, so
# setting EMBEDDING_MODEL in .env moved the query side and left the index
# builder on the old model. Same dimension, different vectors, no error.
from docpipe.embedding.config import (EMBEDDING_DIM,             # noqa: E402,F401
                                      EMBEDDING_MODEL)
from docpipe.embedding.config import EMBEDDING_MAX_TOKEN_LENGTH as MAX_TOKEN_LENGTH

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

# Documents allowed to sit prepared and unconsumed. Preparation is far faster
# than embedding, so an unbounded queue holds the WHOLE corpus in memory:
# roughly a million EmbeddingInputs, each carrying its section text. That is
# what killed the 1078-plan run at 194 GB. With a window, resident memory is a
# property of this constant instead of the corpus size.
EMBED_PREPARE_AHEAD = 32

# Items collected before a chunk goes to the GPUs. Large enough that sorting by
# length still fills batches with comparable sequences, small enough that the
# GPUs start long before the last document is read.
EMBED_FLUSH_ITEMS = 4096

# Vectors added before the FAISS index is written out again. The index is a
# single file rewritten whole — about 16 GB at a million 4096-dim vectors — so
# saving it once per flush chunk was ~244 full rewrites over a build, with the
# GPUs idle for every one. This is crash insurance, not durability: a run that
# dies re-embeds at most this many vectors plus the current chunk.
EMBED_SAVE_VECTORS = 50_000

FAISS_INDEX_FILE = "faiss_index.bin"

EMBEDDING_TYPE_SECTION_TEXT = "section_text"
EMBEDDING_TYPE_SECTION_TITLE = "section_title"
EMBEDDING_TYPE_TABLE_TEXT = "table_text"
EMBEDDING_TYPE_TABLE_VL = "table_vl"
EMBEDDING_TYPE_FIGURE_TEXT = "figure_text"
EMBEDDING_TYPE_FIGURE_VL = "figure_vl"