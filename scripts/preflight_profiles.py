#!/usr/bin/env python3
"""
preflight_profiles.py – Both profiles, everything a corpus run rests on.

Not a smoke test. Every line here failed at least once in a way that cost a
GPU run or a night: a prompt whose max_tokens was sized for a contract two
versions old, a vocabulary entry that means "I do not know" sitting where a
class belongs, a job script pointing at an index file that is not there, an
axis with no question so the field request carried no rule.

Prints a table and exits non-zero on the first hard failure, so it can stand
in front of sbatch. Run it for one profile or both:

    python scripts/preflight_profiles.py
    python scripts/preflight_profiles.py kwp

Author: Felix Vossel
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# A value that means "I do not know" is not a reading and must not sit in a
# vocabulary: a coordinate nobody read is a state, not a class.
SHRUGS = {"unknown", "unbekannt", "n/a", "keine angabe", "out:unstated"}

rows: list = []
hard = 0


def check(profile: str, what: str, ok: bool, detail: str = "", fatal=True):
    global hard
    rows.append((profile, what, "ok" if ok else ("FAIL" if fatal else "warn"),
                 detail))
    if not ok and fatal:
        hard += 1
    return ok


def audit(profile: str) -> None:
    os.environ["DOCPIPE_PROFILE"] = profile
    from docpipe import prompts
    from docpipe.extraction import fields
    from docpipe.extraction.spec import load as load_spec

    base = ROOT / "profiles" / profile
    spec_file = base / "extraction_spec.json"
    if not check(profile, "spec present", spec_file.is_file(), str(spec_file)):
        return
    spec = load_spec(json.loads(spec_file.read_text(encoding="utf-8")))
    check(profile, "parameters loaded", bool(spec.parameters),
          f"{len(spec.parameters)} parameter(s)")

    # Every coordinate carries the rule the field request needs.
    blank = [f"{p.uri.split('/')[-1]}.{s.name}"
             for p in spec.parameters for s in fields.asked_slots(p)
             if not (s.question or "").strip()]
    check(profile, "every axis has a question", not blank, ", ".join(blank))

    # What the spec decides instead of asking. The derivation reads the unit,
    # so it is only sound while no unit belongs to two numeric parameters:
    # otherwise the first one wins silently, which is a guess written down as
    # a reading. The spec says the rule in prose and nothing held it to it.
    numeric = [p for p in spec.parameters if p.is_numeric]
    shared = sorted({u for i, first in enumerate(numeric)
                     for second in numeric[i + 1:]
                     for u in first.units_accepted
                     if second.unit_factor(u) is not None})
    check(profile, "units of numeric parameters are disjoint",
          not shared, ", ".join(shared) or f"{len(numeric)} numeric parameter(s)")

    # A derived coordinate is claimed for every accepted unit of its
    # parameter, so every one of them has to imply it. `integral` is an
    # extensive amount summed over a span, which every Wh and every tonne is
    # and a watt is not.
    derived = [(p, name, axis) for p in spec.parameters
               for name, axis in p.axes.items() if axis.derive]
    bad = [f"{p.label}.{name}" for p, name, axis in derived
           if axis.derive.get("value") not in (axis.vocabulary or {})]
    check(profile, "every derived axis hits its own vocabulary",
          not bad, ", ".join(bad) or f"{len(derived)} derived")

    # Which quantity a value is, is a coordinate now. Without its question the
    # field request carries no rule and the whole document-level plan collapses
    # into rows nobody can assign a parameter to.
    check(profile, "the parameter question is in the spec",
          bool((spec.parameter_question or "").strip()),
          (spec.parameter_question or "")[:60])

    # One anchor set per question the field sweep asks, and none for the
    # value: the plan searches with the one sentence written per document.
    # Six sentences about a parameter say nothing about where its reference
    # year is printed, and the sweep searched with the raw question until
    # this was measured.
    from docpipe.extraction.runner import anchor_key, anchor_targets
    targets = anchor_targets(spec)
    keys = [t[0] for t in targets]
    wanted = 1 + sum(len(fields.asked_slots(p)) for p in spec.parameters)
    check(profile, "one anchor per question",
          len(keys) == len(set(keys)) == wanted, f"{len(keys)} target(s)")
    with_question = [t for t in targets if t[3]]
    check(profile, "every axis target carries its question",
          len(with_question) >= wanted - 1,
          f"{len(with_question)} with question")
    check(profile, "no anchor for the value itself",
          not {p.uri for p in spec.parameters} & set(keys),
          "the plan searches with one sentence per document")

    # No entry that means "I do not know". Those are states now.
    shrugs = []
    for p in spec.parameters:
        for name, axis in p.axes.items():
            for uri in (axis.vocabulary or {}):
                if uri.strip().casefold() in SHRUGS:
                    shrugs.append(f"{p.uri.split('/')[-1]}.{name}={uri}")
        for uri in (p.vocabulary or {}):
            if uri.strip().casefold() in SHRUGS:
                shrugs.append(f"{p.uri.split('/')[-1]}.value={uri}")
    check(profile, "no shrug in the vocabulary", not shrugs,
          ", ".join(shrugs))

    # And the way to say it is absent exists, as an entry and not as prose.
    # A dynamic axis carries no list until the profile fills it per document,
    # so checking the spec as loaded would report "no closed axes" and pass —
    # which is how the scenarios profile, whose only axis is dynamic, would
    # have gone unchecked entirely.
    from docpipe.extraction.runner import fill_dynamic_axes
    dynamic = {name for p in spec.parameters
               for name, axis in p.axes.items() if axis.dynamic}
    filled = fill_dynamic_axes(
        spec, {name: {"EN_NPi2020_400": ["das Referenzszenario"]}
               for name in dynamic}) if dynamic else spec
    closed = [s for p in filled.parameters for s in fields.axis_slots(p)
              if s.options]
    check(profile, "out:unstated is selectable",
          bool(closed) and all(fields.UNSTATED in s.answerable()
                               for s in closed),
          f"{len(closed)} closed axis/axes"
          + (f", of which dynamic: {sorted(dynamic)}" if dynamic else ""))

    for prompt_id in ("extraction/rows", "extraction/field",
                      "extraction/queries", "extraction/anchors"):
        try:
            prompt = prompts.load(prompt_id)
        except Exception as exc:
            check(profile, f"prompt {prompt_id}", False, str(exc))
            continue
        ok = bool(prompt.text.strip())
        check(profile, f"prompt {prompt_id}", ok, f"{len(prompt.text)} char(s)")
        if prompt_id in ("extraction/rows", "extraction/field"):
            temp = float(prompt.meta.get("temperature", 1))
            check(profile, f"{prompt_id}: temperature 0", temp == 0,
                  f"temperature={temp}")
            check(profile, f"{prompt_id}: answer room",
                  int(prompt.meta.get("max_tokens", 0)) >= 4096,
                  f"max_tokens={prompt.meta.get('max_tokens')}")
    field_text = prompts.load("extraction/field").text
    for key in ("groups", "answers", "value_raw", "quote", "corrections",
                fields.UNSTATED):
        check(profile, f"field prompt names {key!r}", f'"{key}"' in field_text)
    # The value request reads a passage once for every quantity at once, so it
    # must be told about all of them and not about one.
    # The field request asks for several fields at once now, and the reply is
    # keyed by field name. A prompt still describing one field per request
    # answers in the old shape, nothing folds, and every coordinate comes back
    # empty — an entire run of empty tuples with no error anywhere.
    check(profile, "field prompt knows several fields",
          '"fields"' in field_text and '"field":' not in field_text)

    rows_text = prompts.load("extraction/rows").text
    check(profile, "rows prompt names 'quantities'", '"quantities"' in rows_text)
    check(profile, "rows prompt no longer fixes one parameter",
          '"parameter": die gesucht' not in rows_text)

    # A text parameter comes out of the same request as the numbers, so the
    # example the model imitates has to show one. The kwp prompt asked for
    # "jede Zahl" and nothing else, and planning_organisation produced 0 tuples
    # over 103 harvested documents while the scenarios prompt, which does show
    # a text value, produced eleven such fields. Checked on the example rather
    # than on a word in the prose: a word can be added without changing what
    # the model copies.
    text_parameters = [p.uri for p in spec.parameters
                       if not p.is_numeric and not p.vocabulary]
    if text_parameters:
        shown = False
        for match in re.finditer(r'\{"tuples":.*', rows_text):
            try:
                parsed = json.JSONDecoder().raw_decode(match.group(0))[0]
            except ValueError:
                continue
            shown = shown or any(isinstance(t.get("value"), str)
                                 for t in parsed.get("tuples") or ())
        check(profile, "rows prompt shows a text value", shown,
              "%d text parameter(s): %s" % (len(text_parameters),
                                            ", ".join(text_parameters[:3])))
    anchors_text = prompts.load("extraction/anchors").text
    check(profile, "anchors prompt knows the question", '"question"' in anchors_text)

    kg = base / "kg.py"
    check(profile, "serializer present", kg.is_file(), str(kg))

    # The published shape of what this run writes. It is generated, so a spec
    # change that nobody regenerated leaves the schema describing a harvest
    # nobody produces -- and the schema is what a reader outside this
    # repository has instead of runner.py.
    try:
        import jsonschema                                        # noqa: F401
        has_jsonschema = True
    except ImportError:
        has_jsonschema = False
    check(profile, "jsonschema importable", has_jsonschema,
          "" if has_jsonschema else "pip install jsonschema")
    from docpipe.extraction import schema as schema_mod
    written = schema_mod.schema_path(profile)
    if check(profile, "schema present", written.is_file(), str(written)):
        current = (written.read_text(encoding="utf-8")
                   == schema_mod.serialize(schema_mod.build(spec)))
        check(profile, "schema current", current,
              "" if current else
              f"python -m docpipe.extraction.schema {profile} --write")

    # Every ontology identifier this spec names, held against the pinned
    # ontology: does the term exist, is it deprecated, is a sector a sector
    # and a carrier a carrier. Hand-typed identifiers next to hand-typed
    # labels were checked by nobody, and the ontology moves.
    vocabulary = base / "vocabulary.py"
    if vocabulary.is_file():
        import importlib
        module = importlib.import_module(f"profiles.{profile}.vocabulary")
        snapshot_file = getattr(module, "VOCABULARY_PATH", None)
        if check(profile, "vocabulary snapshot present",
                 bool(snapshot_file and snapshot_file.is_file()),
                 str(snapshot_file)):
            snapshot = module.load()
            problems = module.check(
                json.loads(spec_file.read_text(encoding="utf-8")), snapshot)
            check(profile, "every ontology id matches the pin", not problems,
                  "; ".join(problems[:3]))
            check(profile, "pin named",
                  bool(snapshot.get("pin", {}).get("oeo_version_iri")),
                  snapshot.get("pin", {}).get("oeo_version_iri") or "")
            foreign = {u for _w, u, _l, _o in
                       module.foreign_labels(
                           json.loads(spec_file.read_text(encoding="utf-8")),
                           snapshot)}
            check(profile, "labels from the corpus rather than the ontology",
                  not foreign, f"{len(foreign)} entry/entries", fatal=False)
            # Named rather than silent. A term of an ontology no file of this
            # snapshot covers -- kwp names six MHPO classes and MHPO ships
            # only as OWL functional syntax, which rdflib does not read -- is
            # neither right nor wrong here. Reporting it as an error would
            # teach everyone to ignore the real ones; reporting nothing would
            # let the gap grow.
            from docpipe import ontology as _ontology
            open_families = _ontology.uncovered(
                json.loads(spec_file.read_text(encoding="utf-8")), snapshot)
            check(profile, "every id family has a file that knows it",
                  not open_families,
                  ", ".join(f"{k}_* ({len(v)}x)"
                            for k, v in sorted(open_families.items())),
                  fatal=False)

    # A coordinate the graph takes has to say what it becomes there. Not
    # every axis does -- some are read for the record and never serialized --
    # but an axis with no kg block at all is one nobody decided about.
    silent = [f"{p.uri}.{name}" for p in spec.parameters
              for name, axis in p.axes.items() if not axis.kg]
    check(profile, "every axis says what it becomes in the graph", not silent,
          ", ".join(silent), fatal=False)

    # And the same question one level up, which was asked nowhere: the axes
    # of a parameter can all be answered while the parameter's own value says
    # nothing about the graph it lands in. Thirteen of the fourteen scenarios
    # parameters have no axis at all, so the axis check above could not see
    # them. Read from the raw file: `kg` is passed through to the serializer
    # and is not a field of the loaded Parameter.
    mute = silent_parameters(json.loads(spec_file.read_text(encoding="utf-8")))
    check(profile, "every parameter says what it becomes in the graph", not mute,
          ", ".join(mute), fatal=False)


def silent_parameters(raw: dict) -> list:
    """Which parameters of a raw spec say nothing about the graph.

    A function rather than three lines inside `audit`, because a gate that
    cannot be handed a failing input is decoration, and `audit` can only be
    handed the repository's own files -- which are, by the time anyone runs
    it, the ones that pass.
    """
    return [p["uri"] for p in raw.get("parameters", ()) if not p.get("kg")]


def main(argv: list) -> int:
    for profile in (argv or ["kwp", "scenarios"]):
        audit(profile)
    width = max(len(r[1]) for r in rows)
    current = None
    for profile, what, verdict, detail in rows:
        if profile != current:
            print(f"\n=== {profile} ===")
            current = profile
        mark = {"ok": "  ", "warn": "! ", "FAIL": "X "}[verdict]
        print(f"{mark}{what.ljust(width)}  {detail}")
    print(f"\n{len(rows)} check(s), {hard} failure(s)")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
