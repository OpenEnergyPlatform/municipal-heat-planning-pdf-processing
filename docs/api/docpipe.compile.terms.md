# docpipe.compile.terms

`docpipe/compile/terms.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

terms.py: What an ontology calls a term and says it means.

The lists and the properties of a shapes file are identifiers. What stands
behind one, its label, the other names it goes by and its definition, is in
the ontology. This module reads those for any IRI, from whichever of the
usual annotation properties a given ontology uses, so a spec's closed list
can offer the model the ontology's own words.

It also reads one kind of statement about a class: the unit family an
ontology gives a quantity ("has unit some energy unit"), and the units of that
family. That is a suggestion for whoever writes a number's units; which
spellings a document uses and the factors between them are not in an ontology.

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

#### Terms.unit_families

```python
def unit_families(self, iri: str, properties=UNIT_PROPERTIES) -> list
```

The unit families the ontology gives a class: [{"family": IRI of
the unit class, "stated_on": IRI of the class that says it}].

What a class itself says about its unit is taken. A class that says
nothing has what the classes above it say, the nearest ones first;
nothing above says anything either, then there is no family and the
list is empty. Nothing is guessed from a name.

#### Terms.units

```python
def units(self, family: str) -> list
```

Every unit of a family: the classes below it and the named things
typed as it or as one of them. The family class itself is not one.

## Functions

### says_unit

```python
def says_unit(iri, properties=UNIT_PROPERTIES) -> bool
```

Is this property the one that names a quantity's unit family?

[Back to the index](../README.md)
