"""
terms.py: What an ontology calls a term and says it means.

The lists and the properties of a shapes file are identifiers. What stands
behind one, its label, the other names it goes by and its definition, is in
the ontology. This module reads those for any IRI, from whichever of the
usual annotation properties a given ontology uses, so a spec's closed list
can offer the model the ontology's own words.

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

    def individuals(self, iri: str) -> list:
        """Every named thing the files type as *iri* or as a class under it:
        what a property whose value is "one of this class" may point at,
        where the ontology names them all."""
        if self.graph is None:
            return []
        from rdflib import RDF, RDFS as R, URIRef
        classes, stack = {URIRef(iri)}, [URIRef(iri)]
        while stack:
            node = stack.pop()
            for child in self.graph.subjects(R.subClassOf, node):
                if isinstance(child, URIRef) and child not in classes:
                    classes.add(child)
                    stack.append(child)
        members = set()
        for klass in classes:
            members |= {node for node in self.graph.subjects(RDF.type, klass)
                        if isinstance(node, URIRef)}
        return sorted(str(member) for member in members)
