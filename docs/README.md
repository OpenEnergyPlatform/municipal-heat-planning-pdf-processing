# Documentation

Every page here except `pipeline.md` is generated from the code it describes by `scripts/build_docs.py`, and `tests/test_docs_build.py` fails when a checked-in page and a fresh render disagree. Edit the source, then run:

```
python scripts/build_docs.py --out docs
```

## Pages

- [How the parts fit together](pipeline.md) — hand-written
- [What each stage leaves behind](artifacts.md)
- [The harvest contract: kwp](contract/kwp.md)
- [The harvest contract: scenarios](contract/scenarios.md)
- [What a coordinate's state means](contract/states.md)
- [How much of a value the run can stand behind](contract/trust.md)
- [Profiles](profiles.md)
- [The chat over the corpus](stages/app.md)
- [6. Chunking, embedding, indexing](stages/chunking.md)
- [The parts every stage uses](stages/core.md)
- [The embedders](stages/embedding.md)
- [7. Reading the values out](stages/extraction.md)
- [1. Getting the documents in](stages/fileprocessing.md)
- [8. The knowledge graph](stages/graph.md)
- [Asking the corpus](stages/inference.md)
- [2-3. Reading the page](stages/preprocessing.md)
- [4. Repairing the text](stages/refinement.md)
- [The database](stages/store.md)
- [5. Reading the pictures](stages/visuals.md)
