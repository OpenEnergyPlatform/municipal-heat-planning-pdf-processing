"""
graphprobe.py: The graph of a local harvest as a profile's graph file has
it written, into a folder of the temp directory, for the Graph tab of
`docpipe edit` ("Test write"). A process of its own, because a writer reads
its rules when it is imported:

    python -m docpipe.editor.graphprobe PROFILE HARVEST DB OUT

with `DOCPIPE_GRAPH_FILE` naming the graph file to write with (the page's,
unsaved) or unset for the profile's own. Writes OUT/graph.ttl and
OUT/probe.json: per document the nodes it has in the graph and what left it
with which constraint, the nodes of each class, the violations of each
constraint and how many nodes were named anew. Nothing is written but into
OUT; no model is asked.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path


def probe(profile_name: str, harvest: Path, db: Path, out: Path) -> dict:
    os.environ["DOCPIPE_PROFILE"] = profile_name
    os.environ.setdefault("EXTRACT_PROVENANCE", "0")
    from docpipe import graphfile
    from docpipe.extraction.gate import _serializer
    from docpipe.extraction.serialize import (apply_graph_file,
                                              profile_context, run)
    from docpipe.profile import load_profile
    from rdflib import RDF, Graph

    profile = load_profile(profile_name)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "graph.ttl"
    index: dict = {}
    counts = run(Path(harvest), path, _serializer(profile, Path(db)), None,
                 index=index)
    shapes = profile.component("vocabulary", "shapes")
    paths = [one for one in (shapes() if shapes else [])
             if Path(one).is_file()]
    context = profile_context(profile) if paths else ()
    written = {name: len(subjects) for name, subjects in index.items()}
    done = apply_graph_file(path, profile, paths, context, index) or {
        "classes_left_out": {}, "readdressed": 0, "left_out": [], "stop": []}
    text = path.read_text(encoding="utf-8")
    graph = Graph().parse(data=text, format="turtle")
    present = {str(node) for node in graph.subjects()}
    by_class = Counter(graphfile.local(klass)
                       for _node, klass in graph.subject_objects(RDF.type))
    found = graphfile.violations(text, paths, context) if paths else []
    per_key = Counter(key for key, _node in found)
    nodes_per_key: dict = {}
    for key, node in found:
        nodes_per_key.setdefault(key, set()).add(node)
    documents = {}
    for name, subjects in index.items():
        mine = set(subjects)
        documents[name] = {
            "written": written.get(name, 0),
            "kept": sum(1 for one in subjects if one in present),
            "violations": sum(1 for _key, node in found if node in mine),
            "left_out": [entry for entry in done["left_out"]
                         if entry.get("document") == name
                         or entry.get("node") in mine]}
    report = {"documents": documents, "tuples": sum(counts.values()),
              "triples": len(graph), "classes": dict(by_class),
              "violations": dict(per_key),
              "violating_nodes": {key: len(nodes)
                                  for key, nodes in nodes_per_key.items()},
              "done": done, "shapes": [str(one) for one in paths],
              "graph_file": os.environ.get(graphfile.ENV)}
    (out / "probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return report


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 4:
        print("usage: python -m docpipe.editor.graphprobe PROFILE HARVEST DB "
              "OUT", file=sys.stderr)
        return 2
    report = probe(argv[0], Path(argv[1]), Path(argv[2]), Path(argv[3]))
    print(f"RESULT|probe|documents={len(report['documents'])}|"
          f"triples={report['triples']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
