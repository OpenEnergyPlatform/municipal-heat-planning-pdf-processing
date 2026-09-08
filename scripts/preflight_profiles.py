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
    rows.append((profile, what, "ok" if ok else ("FEHLER" if fatal else "warn"),
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
    if not check(profile, "spec vorhanden", spec_file.is_file(), str(spec_file)):
        return
    spec = load_spec(json.loads(spec_file.read_text(encoding="utf-8")))
    check(profile, "Parameter geladen", bool(spec.parameters),
          f"{len(spec.parameters)} Parameter")

    # Every coordinate carries the rule the field request needs.
    blank = [f"{p.uri.split('/')[-1]}.{s.name}"
             for p in spec.parameters for s in fields.asked_slots(p)
             if not (s.question or "").strip()]
    check(profile, "jede Achse hat eine Frage", not blank, ", ".join(blank))

    # What the spec decides instead of asking. The derivation reads the unit,
    # so it is only sound while no unit belongs to two numeric parameters:
    # otherwise the first one wins silently, which is a guess written down as
    # a reading. The spec says the rule in prose and nothing held it to it.
    numeric = [p for p in spec.parameters if p.is_numeric]
    shared = sorted({u for i, first in enumerate(numeric)
                     for second in numeric[i + 1:]
                     for u in first.units_accepted
                     if second.unit_factor(u) is not None})
    check(profile, "die Einheiten der Zahlparameter sind disjunkt",
          not shared, ", ".join(shared) or f"{len(numeric)} Zahlparameter")

    # A derived coordinate is claimed for every accepted unit of its
    # parameter, so every one of them has to imply it. `integral` is an
    # extensive amount summed over a span, which every Wh and every tonne is
    # and a watt is not.
    derived = [(p, name, axis) for p in spec.parameters
               for name, axis in p.axes.items() if axis.derive]
    bad = [f"{p.label}.{name}" for p, name, axis in derived
           if axis.derive.get("value") not in (axis.vocabulary or {})]
    check(profile, "jede abgeleitete Achse trifft ihr eigenes Vokabular",
          not bad, ", ".join(bad) or f"{len(derived)} abgeleitet")

    # Which quantity a value is, is a coordinate now. Without its question the
    # field request carries no rule and the whole document-level plan collapses
    # into rows nobody can assign a parameter to.
    check(profile, "die Parameterfrage steht in der Spec",
          bool((spec.parameter_question or "").strip()),
          (spec.parameter_question or "")[:60])

    # One anchor set per QUESTION. Six sentences about a parameter say nothing
    # about where its reference year is printed, and the field sweep searched
    # with the raw question until this was measured.
    from docpipe.extraction.runner import anchor_key, anchor_targets
    targets = anchor_targets(spec)
    keys = [t[0] for t in targets]
    wanted = 1 + sum(1 + len(fields.asked_slots(p)) for p in spec.parameters)
    check(profile, "ein Anker je Frage",
          len(keys) == len(set(keys)) == wanted, f"{len(keys)} Ziel(e)")
    with_question = [t for t in targets if t[3]]
    check(profile, "jedes Achsenziel traegt seine Frage",
          len(with_question) >= wanted - len(spec.parameters) - 1,
          f"{len(with_question)} mit Frage")

    # What the profile freezes, and what it leaves to the model. A frozen
    # anchor is a section that really produced a value, so the file outlives
    # the spec it was measured against: a key that is no question of this spec
    # would be dropped by every reader without a word, and the run would search
    # with a set nobody checked. It fails here rather than on five GPUs.
    from docpipe.extraction.runner import frozen_anchors
    from docpipe.profile import load_profile
    try:
        fixed, fixed_sha = frozen_anchors(load_profile(profile), spec)
    except Exception as exc:
        check(profile, "eingefrorene Anker lesbar", False, str(exc)[:140])
    else:
        check(profile, "eingefrorene Anker lesbar", True,
              (f"{sum(len(v) for v in fixed.values())} Anker fuer {len(fixed)} "
               f"von {len(keys)} Frage(n), sha {fixed_sha}, den Rest schreibt "
               f"das Modell" if fixed else "keine, das Modell schreibt alle"),
              fatal=False)

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
    check(profile, "kein Achselzucker im Vokabular", not shrugs,
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
    check(profile, "out:unstated ist waehlbar",
          bool(closed) and all(fields.UNSTATED in s.answerable()
                               for s in closed),
          f"{len(closed)} geschlossene Achse(n)"
          + (f", davon dynamisch: {sorted(dynamic)}" if dynamic else ""))

    for prompt_id in ("extraction/rows", "extraction/field",
                      "extraction/queries", "extraction/anchors"):
        try:
            prompt = prompts.load(prompt_id)
        except Exception as exc:
            check(profile, f"Prompt {prompt_id}", False, str(exc))
            continue
        ok = bool(prompt.text.strip())
        check(profile, f"Prompt {prompt_id}", ok, f"{len(prompt.text)} Zeichen")
        if prompt_id in ("extraction/rows", "extraction/field"):
            temp = float(prompt.meta.get("temperature", 1))
            check(profile, f"{prompt_id}: temperature 0", temp == 0,
                  f"temperature={temp}")
            check(profile, f"{prompt_id}: Antwortraum",
                  int(prompt.meta.get("max_tokens", 0)) >= 4096,
                  f"max_tokens={prompt.meta.get('max_tokens')}")
    field_text = prompts.load("extraction/field").text
    for key in ("groups", "answers", "value_raw", "quote", "corrections",
                fields.UNSTATED):
        check(profile, f"Feld-Prompt nennt {key!r}", f'"{key}"' in field_text)
    # The value request reads a passage once for every quantity at once, so it
    # must be told about all of them and not about one.
    # The field request asks for several fields at once now, and the reply is
    # keyed by field name. A prompt still describing one field per request
    # answers in the old shape, nothing folds, and every coordinate comes back
    # empty — an entire run of empty tuples with no error anywhere.
    check(profile, "Feld-Prompt kennt mehrere Felder",
          '"fields"' in field_text and '"field":' not in field_text)

    rows_text = prompts.load("extraction/rows").text
    check(profile, "Zeilen-Prompt nennt 'quantities'", '"quantities"' in rows_text)
    check(profile, "Zeilen-Prompt fixiert keinen Parameter mehr",
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
        check(profile, "Zeilen-Prompt zeigt einen Textwert", shown,
              "%d Textparameter: %s" % (len(text_parameters),
                                        ", ".join(text_parameters[:3])))
    anchors_text = prompts.load("extraction/anchors").text
    check(profile, "Anker-Prompt kennt die Frage", '"question"' in anchors_text)

    kg = base / "kg.py"
    check(profile, "Serializer vorhanden", kg.is_file(), str(kg))

    # The published shape of what this run writes. It is generated, so a spec
    # change that nobody regenerated leaves the schema describing a harvest
    # nobody produces -- and the schema is what a reader outside this
    # repository has instead of runner.py.
    try:
        import jsonschema                                        # noqa: F401
        has_jsonschema = True
    except ImportError:
        has_jsonschema = False
    check(profile, "jsonschema importierbar", has_jsonschema,
          "" if has_jsonschema else "pip install jsonschema")
    from docpipe.extraction import schema as schema_mod
    written = schema_mod.schema_path(profile)
    if check(profile, "Schema vorhanden", written.is_file(), str(written)):
        current = (written.read_text(encoding="utf-8")
                   == schema_mod.serialize(schema_mod.build(spec)))
        check(profile, "Schema aktuell", current,
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
        if check(profile, "Vokabular-Schnappschuss vorhanden",
                 bool(snapshot_file and snapshot_file.is_file()),
                 str(snapshot_file)):
            snapshot = module.load()
            problems = module.check(
                json.loads(spec_file.read_text(encoding="utf-8")), snapshot)
            check(profile, "jede Ontologie-Id passt zum Pin", not problems,
                  "; ".join(problems[:3]))
            check(profile, "Pin benannt",
                  bool(snapshot.get("pin", {}).get("oeo_version_iri")),
                  snapshot.get("pin", {}).get("oeo_version_iri") or "")
            foreign = {u for _w, u, _l, _o in
                       module.foreign_labels(
                           json.loads(spec_file.read_text(encoding="utf-8")),
                           snapshot)}
            check(profile, "Beschriftungen aus dem Korpus statt der Ontologie",
                  not foreign, f"{len(foreign)} Eintrag/Eintraege", fatal=False)
            # Named rather than silent. A term of an ontology no file of this
            # snapshot covers -- kwp names six MHPO classes and MHPO ships
            # only as OWL functional syntax, which rdflib does not read -- is
            # neither right nor wrong here. Reporting it as an error would
            # teach everyone to ignore the real ones; reporting nothing would
            # let the gap grow.
            from docpipe import ontology as _ontology
            open_families = _ontology.uncovered(
                json.loads(spec_file.read_text(encoding="utf-8")), snapshot)
            check(profile, "jede Id-Familie hat eine Datei, die sie kennt",
                  not open_families,
                  ", ".join(f"{k}_* ({len(v)}x)"
                            for k, v in sorted(open_families.items())),
                  fatal=False)

    # A coordinate the graph takes has to say what it becomes there. Not
    # every axis does -- some are read for the record and never serialized --
    # but an axis with no kg block at all is one nobody decided about.
    silent = [f"{p.uri}.{name}" for p in spec.parameters
              for name, axis in p.axes.items() if not axis.kg]
    check(profile, "jede Achse sagt, was sie im Graphen wird", not silent,
          ", ".join(silent), fatal=False)

    # And the same question one level up, which was asked nowhere: the axes
    # of a parameter can all be answered while the parameter's own value says
    # nothing about the graph it lands in. Thirteen of the fourteen scenarios
    # parameters have no axis at all, so the axis check above could not see
    # them. Read from the raw file: `kg` is passed through to the serializer
    # and is not a field of the loaded Parameter.
    mute = silent_parameters(json.loads(spec_file.read_text(encoding="utf-8")))
    check(profile, "jeder Parameter sagt, was er im Graphen wird", not mute,
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
        mark = {"ok": "  ", "warn": "! ", "FEHLER": "X "}[verdict]
        print(f"{mark}{what.ljust(width)}  {detail}")
    print(f"\n{len(rows)} Pruefung(en), {hard} Fehler")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
