"""
inference_app – Streamlit RAG chat over the KWP knowledge base.

A user-facing retrieval + question-answering front-end for the corpus produced
by the batch pipeline (SQLite `KWP.db` + a global FAISS index). Runs on a
separate, resource-constrained server: the multimodal embedding model is loaded
NF4-quantized on demand (freed again after every request) so it never sits
resident in VRAM, while the answer-generating LLM (Qwen-122B) is called over a
remote OpenAI-compatible API.

Author: Felix Vossel
"""
