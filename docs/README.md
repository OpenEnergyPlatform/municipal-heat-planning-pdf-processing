# Documentation

Every page here except `pipeline.md` is generated from the code it describes by `scripts/build_docs.py`, and `tests/test_docs_build.py` fails when a checked-in page and a fresh render disagree. Edit the source, then run:

```
python scripts/build_docs.py --out docs
```

## Pages

- [How the parts fit together](pipeline.md) — hand-written
- [What each stage leaves behind](artifacts.md): artifacts.py – The per-document files under ``<doc>/results/``, in the order the pipeline writes them.
- [The harvest contract: kwp](contract/kwp.md)
- [The harvest contract: scenarios](contract/scenarios.md)
- [What a coordinate's state means](contract/states.md): fields.py – The deterministic skeleton of a tuple.
- [How much of a value the run can stand behind](contract/trust.md): trust.py – How much of a value the run can actually stand behind.
- [Profiles](profiles.md): profile.py – A profile is everything a project contributes to the generic pipeline: where its documents come from, what extra tables it needs, which prompts it overrides and which filters its app offers.
- [The chat over the corpus](stages/app.md): inference_app – Streamlit RAG chat over the KWP knowledge base.
- [6. Chunking, embedding, indexing](stages/chunking.md): chunking – Merge the preprocessing and visuals outputs, embed them, index them.
- [The parts every stage uses](stages/core.md): artifacts.py – The per-document files under ``<doc>/results/``, in the order the pipeline writes them.
- [The embedders](stages/embedding.md): embedding – One interface, several ways to get a vector.
- [7. Reading the values out](stages/extraction.md): Ontology-guided value extraction — the OBIE stage.
- [1. Getting the documents in](stages/fileprocessing.md): Getting a profile's documents into its database.
- [8. The knowledge graph](stages/graph.md): serialize.py – From harvested tuples to the profile's target graph.
- [Asking the corpus](stages/inference.md): Retrieval and grounded answering — usable from a UI or from a batch job.
- [2-3. Reading the page](stages/preprocessing.md): pipeline.py – Orchestration of the PDF preprocessing pipeline (Stages 1-3).
- [4. Repairing the text](stages/refinement.md): pipeline.py – Orchestration of the text-refinement module.
- [The database](stages/store.md): Database layer: core schema, profile schema, and the queries over them.
- [5. Reading the pictures](stages/visuals.md): visuals – Vision-LLM enrichment of tables and figures.
