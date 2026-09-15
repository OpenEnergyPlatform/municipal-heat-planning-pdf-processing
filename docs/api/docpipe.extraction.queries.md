# docpipe.extraction.queries

`docpipe/extraction/queries.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

queries.py: Expands a profile's query templates into retrieval probes drawn
from the spec.

One broad question per parameter under-harvests. Retrieval ranks, a rank has a
cap, and the tenth-most-similar table wins over the eleventh for no reason a
corpus cares about. So the profile supplies query templates and the spec
supplies the material, a parameter's label and its axis vocabularies, and every
combination becomes its own retrieval probe. The templates live with the
profile because their wording is corpus language (German for kwp's plans); this
module only expands placeholders.

Placeholders:
    {label}        the parameter's label
    {axis:NAME}    one query per vocabulary entry of that axis, using the
                   entry's first (primary) corpus label

Author: Felix Vossel

## Functions

### expand

```python
def expand(templates: list, parameter: Parameter) -> list
```

Every template × every referenced vocabulary entry, order-stable.

[Back to the index](../README.md)
