"""
__init__.py: Marks the extraction package as the OBIE stage.

OBIE (ontology-based information extraction) turns passages a document's index
already found into typed value tuples for a knowledge graph, using a profile's
ontology as the contract. This file carries no code besides the docstring;
`pipeline.py` holds the helpers of the fold, `runner.py` wires the harvest to
a live corpus and model, and `spec.py` loads the contract.

Author: Felix Vossel
"""
