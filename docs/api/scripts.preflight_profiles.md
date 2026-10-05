# scripts.preflight_profiles

`scripts/preflight_profiles.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

preflight_profiles.py – Both profiles of this repository, everything a
corpus run rests on.

The checks are the package's (`docpipe preflight`, docpipe/extraction/
preflight.py) and hold for any profile. This file runs them for the two
profiles kept here, so the command that stands before a corpus run did not
change:

    python scripts/preflight_profiles.py
    python scripts/preflight_profiles.py kwp

Author: Felix Vossel

## Functions

### main

```python
def main(argv: list) -> int
```

[Back to the index](../README.md)
