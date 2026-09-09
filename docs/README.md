# Documentation

Every page here except the hand-written ones is generated from the code it describes by `scripts/build_docs.py`, and `tests/test_docs_build.py` fails when a checked-in page and a fresh render disagree. Edit the source, then run:

```
python scripts/build_docs.py --out docs
```

## Pages

- [How the parts fit together](pipeline.md): hand-written
- [Running the pipeline](running.md): hand-written
- [Glossary](glossary.md): hand-written
- [What each stage leaves behind](artifacts.md): Names the per-document result files under `<doc>/results/`, in the order the pipeline writes them.
- [The harvest contract: kwp](contract/kwp.md)
- [The harvest contract: scenarios](contract/scenarios.md)
- [What a coordinate's state means](contract/states.md): Computes the deterministic skeleton of a tuple from the spec.
- [How much of a value the run can stand behind](contract/trust.md): Grades every harvested value by how far the run can stand behind it.
- [Profiles](profiles.md): A profile is everything a project contributes to the generic pipeline: where its documents come from, what extra tables it needs, which prompts it overrides and which filters its app offers.
- [The kwp profile](profiles/kwp.md)
- [The scenarios profile](profiles/scenarios.md)
- [The chat over the corpus](stages/app.md): Marks inference_app as a package, a Streamlit retrieval and question answering chat front end over a docpipe corpus.
- [6. Chunking, embedding, indexing](stages/chunking.md): Merges the preprocessing and visuals outputs, embeds them, and indexes them.
- [The parts every stage uses](stages/core.md): Names the per-document result files under `<doc>/results/`, in the order the pipeline writes them.
- [The embedders](stages/embedding.md): Exposes one Embedder interface behind several backends.
- [7. Reading the values out](stages/extraction.md): Marks the extraction package as the OBIE stage.
- [1. Getting the documents in](stages/fileprocessing.md): Exposes the Source contract and the ingest and register functions that get a profile's documents into its database.
- [8. The knowledge graph](stages/graph.md): Turns a document harvest into the profile's target graph.
- [Asking the corpus](stages/inference.md): Retrieval and grounded answering, usable from a UI or from a batch job.
- [2-3. Reading the page](stages/preprocessing.md): Orchestrates the PDF preprocessing pipeline, Stages 1 to 3.
- [4. Repairing the text](stages/refinement.md): Orchestrates the textrefinement stage.
- [The database](stages/store.md): Exposes the database layer, its core schema, its profile schema, and the queries run over them.
- [5. Reading the pictures](stages/visuals.md): Vision-LLM enrichment of tables and figures.
