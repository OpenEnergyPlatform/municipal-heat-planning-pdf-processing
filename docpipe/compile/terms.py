"""
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
"""
from __future__ import annotations

from typing import Optional

OBO = "http://purl.obolibrary.org/obo/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
OBO_IN_OWL = "http://www.geneontology.org/formats/oboInOwl#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
DCT = "http://purl.org/dc/terms/"
SCHEMA = ("http://schema.org/", "https://schema.org/")

# In the order they are trusted, first match first.
LABEL = (RDFS + "label", SKOS + "prefLabel", DCT + "title",
         *(namespace + "name" for namespace in SCHEMA))
OTHER_NAMES = (OBO + "IAO_0000118", SKOS + "altLabel",
               OBO_IN_OWL + "hasExactSynonym")
DEFINITION = (OBO + "IAO_0000115", SKOS + "definition", RDFS + "comment",
              DCT + "description")
# The relation an ontology uses to say which unit family a quantity is
# measured in ("energy value has unit some energy unit"), by the end of its
# IRI as the ontologies the compiler reads write it. Another ontology's is
# passed to `unit_families` by name.
UNIT_PROPERTIES = ("OEO_00040010",)


def says_unit(iri, properties=UNIT_PROPERTIES) -> bool:
    """Is this property the one that names a quantity's unit family?"""
    text = str(iri)
    return text in properties \
        or text.rsplit("/", 1)[-1].rsplit("#", 1)[-1] in properties


class Terms:
    """The annotations of a set of ontology files, by IRI."""

    def __init__(self, graph=None, language: str = "en"):
        self.graph = graph
        self.language = language

    @classmethod
    def read(cls, paths, language: str = "en") -> "Terms":
        from rdflib import Graph
        graph = Graph()
        for path in paths:
            graph.parse(str(path))
        return cls(graph, language)

    def _texts(self, iri: str, predicates) -> list:
        """Every text one of *predicates* gives, the wanted language first,
        then the ones without a language, then nothing else."""
        if self.graph is None:
            return []
        from rdflib import Literal, URIRef
        wanted, untagged = [], []
        for predicate in predicates:
            for value in self.graph.objects(URIRef(iri), URIRef(predicate)):
                if not isinstance(value, Literal):
                    continue
                text = " ".join(str(value).split())
                if not text:
                    continue
                if value.language and value.language.split("-")[0] == \
                        self.language:
                    wanted.append(text)
                elif not value.language:
                    untagged.append(text)
            if wanted or untagged:
                break       # the first predicate that says anything
        return wanted + untagged

    def label(self, iri: str) -> Optional[str]:
        found = self._texts(iri, LABEL)
        return found[0] if found else None

    def other_names(self, iri: str) -> list:
        label = self.label(iri)
        out = []
        for predicate in OTHER_NAMES:
            for text in self._texts(iri, (predicate,)):
                if text != label and text not in out:
                    out.append(text)
        return sorted(out)

    def definition(self, iri: str) -> Optional[str]:
        found = self._texts(iri, DEFINITION)
        return found[0] if found else None

    def _classes_under(self, iri: str) -> set:
        """*iri* and every named class below it."""
        from rdflib import RDFS as R, URIRef
        classes, stack = {URIRef(iri)}, [URIRef(iri)]
        while stack:
            node = stack.pop()
            for child in self.graph.subjects(R.subClassOf, node):
                if isinstance(child, URIRef) and child not in classes:
                    classes.add(child)
                    stack.append(child)
        return classes

    def individuals(self, iri: str) -> list:
        """Every named thing the files type as *iri* or as a class under it:
        what a property whose value is "one of this class" may point at,
        where the ontology names them all."""
        if self.graph is None:
            return []
        from rdflib import RDF, URIRef
        members = set()
        for klass in self._classes_under(iri):
            members |= {node for node in self.graph.subjects(RDF.type, klass)
                        if isinstance(node, URIRef)}
        return sorted(str(member) for member in members)

    def _unit_statements(self, klass, properties) -> list:
        """The unit classes `has unit some X` names in what the files say
        about *klass* itself, also inside an intersection: [X IRI]."""
        from rdflib import BNode, OWL, RDFS as R, URIRef
        from rdflib.collection import Collection
        seen: set = set()
        stack = [node for predicate in (R.subClassOf, OWL.equivalentClass)
                 for node in self.graph.objects(klass, predicate)
                 if isinstance(node, BNode)]
        found = set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            on = self.graph.value(node, OWL.onProperty)
            if on is not None and says_unit(on, properties):
                filler = self.graph.value(node, OWL.someValuesFrom)
                if isinstance(filler, URIRef):
                    found.add(str(filler))
            head = self.graph.value(node, OWL.intersectionOf)
            if head is not None:
                stack.extend(member for member in Collection(self.graph, head)
                             if isinstance(member, BNode))
        return sorted(found)

    def unit_families(self, iri: str, properties=UNIT_PROPERTIES) -> list:
        """The unit families the ontology gives a class: [{"family": IRI of
        the unit class, "stated_on": IRI of the class that says it}].

        What a class itself says about its unit is taken. A class that says
        nothing has what the classes above it say, the nearest ones first;
        nothing above says anything either, then there is no family and the
        list is empty. Nothing is guessed from a name.
        """
        if self.graph is None:
            return []
        from rdflib import RDFS as R, URIRef
        level, seen = [URIRef(iri)], {URIRef(iri)}
        while level:
            found = [{"family": family, "stated_on": str(klass)}
                     for klass in level
                     for family in self._unit_statements(klass, properties)]
            if found:
                return sorted(found, key=lambda one: (one["family"],
                                                      one["stated_on"]))
            above = []
            for klass in level:
                for parent in self.graph.objects(klass, R.subClassOf):
                    if isinstance(parent, URIRef) and parent not in seen:
                        seen.add(parent)
                        above.append(parent)
            level = above
        return []

    def units(self, family: str) -> list:
        """Every unit of a family: the classes below it and the named things
        typed as it or as one of them. The family class itself is not one."""
        if self.graph is None:
            return []
        below = {str(klass) for klass in self._classes_under(family)}
        return sorted((below | set(self.individuals(family)))
                      - {str(family)})
