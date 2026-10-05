# docpipe.compile.terms

`docpipe/compile/terms.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

terms.py: What an ontology calls a term and says it means.

The lists and the properties of a shapes file are identifiers. What stands
behind one, its label, the other names it goes by and its definition, is in
the ontology. This module reads those for any IRI, from whichever of the
usual annotation properties a given ontology uses, so a spec's closed list
can offer the model the ontology's own words.

Nothing is made up here: a term the files say nothing about has no label,
and the draft says so.

Author: Felix Vossel

## Classes

### Terms

```python
class Terms
```

The annotations of a set of ontology files, by IRI.

#### Terms.\_\_init\_\_

```python
def __init__(self, graph=None, language: str = "en")
```

#### Terms.read

```python
@classmethod
def read(cls, paths, language: str = "en") -> "Terms"
```

#### Terms.label

```python
def label(self, iri: str) -> Optional[str]
```

#### Terms.other_names

```python
def other_names(self, iri: str) -> list
```

#### Terms.definition

```python
def definition(self, iri: str) -> Optional[str]
```

#### Terms.individuals

```python
def individuals(self, iri: str) -> list
```

Every named thing the files type as *iri* or as a class under it:
what a property whose value is "one of this class" may point at,
where the ontology names them all.

[Back to the index](../README.md)
