"""
preflight.py: A profile, everything a corpus run rests on.

Not a smoke test. Every line here failed at least once in a way that cost a
GPU run or a night: a prompt whose max_tokens was sized for a contract two
versions old, a vocabulary entry that means "I do not know" sitting where a
class belongs, an axis with no question so the field request carried no
rule.

Prints a table and exits non-zero on a hard failure, so it can stand before
a GPU run:

    docpipe preflight                   the profile in effect
    docpipe preflight kwp scenarios     these

It holds for any profile, wherever it lives. What it reads of a profile is
what the run reads: the spec the profile names (`extraction.SPEC_PATH`),
its prompts, the writer of its graph (its own `kg.make_serializer`, else
the `graph` block of the spec), its `vocabulary` module where it has one.
The keys of a request and a reply are the stage's and are checked here by
name. A wording the run depends on is the profile's, in the language of its
prompts, so the profile says which passages its prompts have to hold
(`extraction.PROMPT_CHECKS`).

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from docpipe.profile import (ENV_VAR, add_profile_argument,
                             bind_command_line, name_profile, program,
                             resolve_profile)

# A value that means "I do not know" is not a reading and must not sit in a
# vocabulary: a coordinate nobody read is a state, not a class. In the
# languages specs are written in here; a word that is not listed passes.
SHRUGS = {"unknown", "unbekannt", "n/a", "keine angabe", "out:unstated"}

# The shape of one entry of a profile's `extraction.PROMPT_CHECKS`.
PROMPT_CHECK_SHAPE = "(what is checked, prompt id, passage, has to be there)"


def prompt_checks(declared) -> tuple:
    """A profile's `PROMPT_CHECKS` as (entries, what is wrong with them).

    An entry is (what is checked, prompt id, passage, whether the passage
    has to be there or must not be). One that is anything else is named
    and not run: a check that cannot be read holds nothing.
    """
    good, bad = [], []
    for entry in declared or ():
        if (isinstance(entry, (tuple, list)) and len(entry) == 4
                and all(isinstance(part, str) and part for part in entry[:3])
                and isinstance(entry[3], bool)):
            good.append(tuple(entry))
        else:
            bad.append(repr(entry))
    return good, bad


def silent_parameters(raw: dict) -> list:
    """Which parameters of a raw spec say nothing about the graph.

    A function rather than three lines inside `audit`, because a gate that
    cannot be handed a failing input is decoration, and `audit` can only be
    handed a profile's own files, which are, by the time anyone runs it, the
    ones that pass.
    """
    return [p["uri"] for p in raw.get("parameters", ()) if not p.get("kg")]


def audit(name: str) -> list:
    """Every check of one profile: (profile, what, ok | warn | FAIL, detail).

    Makes the profile the one in effect for this process (the environment
    names it), because its prompts and its wording are read through that.
    """
    rows: list = []

    def check(what: str, ok: bool, detail: str = "", fatal: bool = True):
        rows.append((name, what,
                     "ok" if ok else ("FAIL" if fatal else "warn"), detail))
        return ok

    from docpipe import prompts
    from docpipe.profile import load_profile

    from . import fields
    from .spec import load as load_spec

    try:
        profile = load_profile(name)
    except (LookupError, ImportError, TypeError, ValueError) as exc:
        check("profile found", False, f"{type(exc).__name__}: {exc}")
        return rows
    os.environ[ENV_VAR] = name
    # The spec the run reads: the one the profile names, and no other. A
    # file that lies beside a profile which does not name it is not read by
    # the run, so it is not a spec here either.
    declared = profile.component("extraction", "SPEC_PATH")
    if declared is None:
        beside = Path(profile.package_dir) / "extraction_spec.json"
        check("spec present", False,
              "the profile names no extraction.SPEC_PATH, so the run reads "
              "no spec"
              + (f" ({beside} lies beside it and is not named)"
                 if beside.is_file() else
                 f" (none at {beside} either; `docpipe compile spec` "
                 f"drafts one)"))
        return rows
    spec_file = Path(declared)
    if not check("spec present", spec_file.is_file(), str(spec_file)):
        return rows
    raw = json.loads(spec_file.read_text(encoding="utf-8"))
    spec = load_spec(raw)
    check("parameters loaded", bool(spec.parameters),
          f"{len(spec.parameters)} parameter(s)")

    # Every coordinate carries the rule the field request needs.
    blank = [f"{p.uri.split('/')[-1]}.{s.name}"
             for p in spec.parameters for s in fields.asked_slots(p)
             if not (s.question or "").strip()]
    check("every axis has a question", not blank, ", ".join(blank))

    # What the spec decides instead of asking. The derivation reads the unit,
    # so it is only sound while no unit belongs to two numeric parameters:
    # otherwise the first one wins silently, which is a guess written down as
    # a reading. The spec says the rule in prose and nothing held it to it.
    numeric = [p for p in spec.parameters if p.is_numeric]
    shared = sorted({u for i, first in enumerate(numeric)
                     for second in numeric[i + 1:]
                     for u in first.units_accepted
                     if u in second.units_accepted})
    check("units of numeric parameters are disjoint",
          not shared, ", ".join(shared) or f"{len(numeric)} numeric parameter(s)")

    # Which entry of the lists a number is in, is a coordinate of its own and
    # is asked before the parameter. Without its question the field request
    # shows the lists and no rule for reading them.
    check("the unit question is set",
          not numeric or bool((spec.unit_question or "").strip()),
          f"{len(numeric)} numeric parameter(s)")

    # A derived coordinate is claimed for every accepted unit of its
    # parameter, so every one of them has to imply it. `integral` is an
    # extensive amount summed over a span, which every Wh and every tonne is
    # and a watt is not.
    derived = [(p, axis_name, axis) for p in spec.parameters
               for axis_name, axis in p.axes.items() if axis.derive]
    bad = [f"{p.label}.{axis_name}" for p, axis_name, axis in derived
           if axis.derive.get("value") not in (axis.vocabulary or {})]
    check("every derived axis hits its own vocabulary",
          not bad, ", ".join(bad) or f"{len(derived)} derived")

    # Which quantity a value is, is a coordinate now. Without its question the
    # field request carries no rule and the whole document-level plan collapses
    # into rows nobody can assign a parameter to.
    check("the parameter question is in the spec",
          bool((spec.parameter_question or "").strip()),
          (spec.parameter_question or "")[:60])

    # One anchor set per question the field sweep asks, and none for the
    # value: the plan searches with the one sentence written per document.
    # Six sentences about a parameter say nothing about where its reference
    # year is printed, and the sweep searched with the raw question until
    # this was measured.
    from .runner import anchor_targets, fill_dynamic_axes
    targets = anchor_targets(spec)
    keys = [t[0] for t in targets]
    wanted = (1 + (1 if fields.unit_slot(spec) is not None else 0)
              + sum(len(fields.asked_slots(p)) for p in spec.parameters))
    check("one anchor per question",
          len(keys) == len(set(keys)) == wanted, f"{len(keys)} target(s)")
    with_question = [t for t in targets if t[3]]
    check("every axis target carries its question",
          len(with_question) >= wanted - 1,
          f"{len(with_question)} with question")
    check("no anchor for the value itself",
          not {p.uri for p in spec.parameters} & set(keys),
          "the plan searches with one sentence per document")

    # No entry that means "I do not know". Those are states now.
    shrugs = []
    for p in spec.parameters:
        for axis_name, axis in p.axes.items():
            for uri in (axis.vocabulary or {}):
                if uri.strip().casefold() in SHRUGS:
                    shrugs.append(f"{p.uri.split('/')[-1]}.{axis_name}={uri}")
        for uri in (p.vocabulary or {}):
            if uri.strip().casefold() in SHRUGS:
                shrugs.append(f"{p.uri.split('/')[-1]}.value={uri}")
    check("no shrug in the vocabulary", not shrugs, ", ".join(shrugs))

    # And the way to say it is absent exists, as an entry and not as prose.
    # A dynamic axis carries no list until the profile fills it per document,
    # so checking the spec as loaded would report "no closed axes" and pass,
    # which is how a profile whose only axis is dynamic would have gone
    # unchecked entirely. The entry it is filled with here is made up.
    dynamic = {axis_name for p in spec.parameters
               for axis_name, axis in p.axes.items() if axis.dynamic}
    filled = fill_dynamic_axes(
        spec, {axis_name: {"entry_1": ["one entry of the list"]}
               for axis_name in dynamic}) if dynamic else spec
    closed = [s for p in filled.parameters for s in fields.axis_slots(p)
              if s.options]
    check("out:unstated is selectable",
          bool(closed) and all(fields.UNSTATED in s.answerable()
                               for s in closed),
          f"{len(closed)} closed axis/axes"
          + (f", of which dynamic: {sorted(dynamic)}" if dynamic else ""))

    # What the profile says its own prompts have to hold. Run beside the
    # checks of the same prompt, the rest after them.
    worded, malformed = prompt_checks(
        profile.component("extraction", "PROMPT_CHECKS"))
    if malformed:
        check(f"prompt checks are {PROMPT_CHECK_SHAPE}", False,
              "; ".join(malformed[:3]))
    run: set = set()

    def as_the_profile_words_it(prompt_id: str, text: str) -> None:
        for what, where, passage, has_to_be_there in worded:
            if where != prompt_id:
                continue
            run.add((what, where, passage, has_to_be_there))
            there = passage in text
            check(what, there == has_to_be_there,
                  "" if there == has_to_be_there else
                  (f"not in {prompt_id}: {passage!r}" if has_to_be_there
                   else f"still in {prompt_id}: {passage!r}"))

    texts: dict = {}
    for prompt_id in ("extraction/rows", "extraction/field",
                      "extraction/queries", "extraction/anchors"):
        try:
            prompt = prompts.load(prompt_id)
        except Exception as exc:
            check(f"prompt {prompt_id}", False, str(exc))
            continue
        texts[prompt_id] = prompt.text
        ok = bool(prompt.text.strip())
        check(f"prompt {prompt_id}", ok, f"{len(prompt.text)} char(s)")
        if prompt_id in ("extraction/rows", "extraction/field"):
            temp = float(prompt.meta.get("temperature", 1))
            check(f"{prompt_id}: temperature 0", temp == 0,
                  f"temperature={temp}")
            check(f"{prompt_id}: answer room",
                  int(prompt.meta.get("max_tokens", 0)) >= 4096,
                  f"max_tokens={prompt.meta.get('max_tokens')}")
    # A prompt that could not be loaded has failed above. What it would
    # have to hold is checked as if it held nothing: every line still
    # stands in the table, and none of them passes.
    field_text = texts.get("extraction/field", "")
    for key in ("groups", "answers", "value_raw", "quote", "corrections",
                fields.UNSTATED):
        check(f"field prompt names {key!r}", f'"{key}"' in field_text)
    # One field per request, and the reply is keyed by the field's name under
    # "fields". A prompt in the old flat shape answers without that key,
    # nothing folds, and every coordinate comes back empty: an entire run of
    # empty tuples with no error anywhere.
    check("field prompt keys the reply by field name",
          '"fields"' in field_text and '"field":' not in field_text)
    as_the_profile_words_it("extraction/field", field_text)

    # The value request reads a passage once for every quantity at once, so
    # it must be told about all of them and not about one.
    rows_text = texts.get("extraction/rows", "")
    check("rows prompt names 'quantities'", '"quantities"' in rows_text)
    as_the_profile_words_it("extraction/rows", rows_text)

    # A text parameter comes out of the same request as the numbers, so the
    # example the model imitates has to show one. A prompt that asked for
    # every number and nothing else produced 0 tuples of a text parameter
    # over 103 harvested documents, while one that does show a text value
    # produced eleven such fields. Checked on the example rather than on a
    # word in the prose: a word can be added without changing what the model
    # copies.
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
        check("rows prompt shows a text value", shown,
              "%d text parameter(s): %s" % (len(text_parameters),
                                            ", ".join(text_parameters[:3])))
    anchors_text = texts.get("extraction/anchors", "")
    check("anchors prompt knows the question", '"question"' in anchors_text)
    as_the_profile_words_it("extraction/anchors", anchors_text)
    for what, where, passage, has_to_be_there in worded:
        if (what, where, passage, has_to_be_there) in run:
            continue
        try:
            text = prompts.load(where).text
        except Exception as exc:
            check(what, False, f"{where}: {exc}")
            continue
        as_the_profile_words_it(where, text)

    # What writes the graph, found the way the run finds it: the profile's
    # own writer, else the generic one, which needs the spec to say what an
    # answer becomes.
    try:
        factory = profile.component("kg", "make_serializer")
    except Exception as exc:        # a writer that does not import writes nothing
        check("serializer present", False, f"{type(exc).__name__}: {exc}")
    else:
        if factory is not None:
            module = sys.modules.get(getattr(factory, "__module__", ""))
            check("serializer present", True,
                  str(getattr(module, "__file__", "") or factory))
        elif not isinstance(raw.get("graph"), dict):
            check("serializer present", False,
                  "no kg.make_serializer and no graph block in the spec: "
                  "nothing says what the graph is")
        else:
            # Built here as the run builds it: a block the generic writer
            # refuses (a base that is still the draft's placeholder, a
            # parameter on a node nobody declared) is refused there after
            # the harvest, which is what this stands before.
            from . import graph
            try:
                graph.make_serializer(raw)
            except graph.GraphError as exc:
                check("serializer present", False, str(exc))
            else:
                check("serializer present", True,
                      "the generic writer, from the graph block of the spec")

    # The published shape of what this run writes. It is generated, so a spec
    # change that nobody regenerated leaves the schema describing a harvest
    # nobody produces, and the schema is what a reader outside this
    # repository has instead of runner.py.
    try:
        import jsonschema                                        # noqa: F401
        has_jsonschema = True
    except ImportError:
        has_jsonschema = False
    check("jsonschema importable", has_jsonschema,
          "" if has_jsonschema else "pip install jsonschema")
    from . import schema as schema_mod
    written = schema_mod.schema_path(name)
    if check("schema present", written.is_file(), str(written)):
        current = (written.read_text(encoding="utf-8")
                   == schema_mod.serialize(schema_mod.build(spec)))
        check("schema current", current,
              "" if current else
              f"python -m docpipe.extraction.schema {name} --write")

    # Every ontology identifier this spec names, held against the pinned
    # ontology: does the term exist, is it deprecated, is a sector a sector
    # and a carrier a carrier. Hand-typed identifiers next to hand-typed
    # labels were checked by nobody, and the ontology moves. For a profile
    # that keeps such a pin (a `vocabulary` module).
    held = profile.component("vocabulary", "check")
    lacking = [part for part in ("load", "foreign_labels")
               if held is not None
               and profile.component("vocabulary", part) is None]
    if lacking:
        check("vocabulary module is whole", False,
              f"{held.__module__} has check and no {', '.join(lacking)}")
    elif held is not None:
        snapshot_file = profile.component("vocabulary", "VOCABULARY_PATH")
        if check("vocabulary snapshot present",
                 bool(snapshot_file and Path(snapshot_file).is_file()),
                 str(snapshot_file)):
            snapshot = profile.component("vocabulary", "load")()
            problems = held(raw, snapshot)
            check("every ontology id matches the pin", not problems,
                  "; ".join(problems[:3]))
            check("pin named",
                  bool(snapshot.get("pin", {}).get("oeo_version_iri")),
                  snapshot.get("pin", {}).get("oeo_version_iri") or "")
            foreign = {u for _w, u, _l, _o in
                       profile.component("vocabulary",
                                         "foreign_labels")(raw, snapshot)}
            check("labels from the corpus rather than the ontology",
                  not foreign, f"{len(foreign)} entry/entries", fatal=False)
            # Named rather than silent. A term of an ontology no file of this
            # snapshot covers is neither right nor wrong here. Reporting it
            # as an error would teach everyone to ignore the real ones;
            # reporting nothing would let the gap grow.
            from docpipe import ontology as _ontology
            open_families = _ontology.uncovered(raw, snapshot)
            check("every id family has a file that knows it",
                  not open_families,
                  ", ".join(f"{k}_* ({len(v)}x)"
                            for k, v in sorted(open_families.items())),
                  fatal=False)
            # What the last `vocabulary --refresh` pulled. A source whose
            # files moved since the commit the profile was reviewed against
            # is named with the files, because the profile mirrors it by hand.
            if profile.component("vocabulary", "SOURCES"):
                from docpipe import upstream as _upstream
                lock = _upstream.load_lock(name)
                check("sources refreshed", lock is not None,
                      "" if lock else
                      f"python -m {held.__module__} --refresh",
                      fatal=False)
                moved = [_upstream.summary(source, record) for source, record
                         in ((lock or {}).get("sources") or {}).items()
                         if record.get("changed_since_reviewed")]
                check("sources unchanged since reviewed", not moved,
                      "; ".join(moved), fatal=False)

    # A coordinate the graph takes has to say what it becomes there. Not
    # every axis does (some are read for the record and never serialized),
    # but an axis with no kg block at all is one nobody decided about.
    silent = [f"{p.uri}.{axis_name}" for p in spec.parameters
              for axis_name, axis in p.axes.items() if not axis.kg]
    check("every axis says what it becomes in the graph", not silent,
          ", ".join(silent), fatal=False)

    # And the same question one level up, which was asked nowhere: the axes
    # of a parameter can all be answered while the parameter's own value says
    # nothing about the graph it lands in. A parameter without an axis is one
    # the axis check above cannot see. Read from the raw file: `kg` is passed
    # through to the serializer and is not a field of the loaded Parameter.
    mute = silent_parameters(raw)
    check("every parameter says what it becomes in the graph", not mute,
          ", ".join(mute), fatal=False)
    return rows


def report(rows: list) -> int:
    """Print the table; how many checks failed hard."""
    hard = sum(1 for row in rows if row[2] == "FAIL")
    width = max((len(row[1]) for row in rows), default=0)
    current = None
    for profile, what, verdict, detail in rows:
        if profile != current:
            print(f"\n=== {profile} ===")
            current = profile
        mark = {"ok": "  ", "warn": "! ", "FAIL": "X "}[verdict]
        print(f"{mark}{what.ljust(width)}  {detail}")
    print(f"\n{len(rows)} check(s), {hard} failure(s)")
    return hard


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.extraction.preflight"),
        description="Check a profile before a corpus run: its spec, its "
                    "prompts, the shape it publishes, the writer of its "
                    "graph. Exits 1 when a check fails.")
    parser.add_argument("profiles", nargs="*", metavar="PROFILE",
                        help="the profiles to check (default: the one in "
                             "effect)")
    add_profile_argument(parser)
    bind_command_line(argv)
    args = parser.parse_args(argv)
    # A name on the line is read like --profile: a profile's directory
    # names the profile in it.
    names = [name_profile(given) for given in args.profiles]
    if not names:
        profile = resolve_profile(args)
        if profile is None:
            parser.error(f"no profile: name one, pass --profile or set "
                         f"{ENV_VAR}")
        names = [profile.name]
    rows: list = []
    for name in names:
        try:
            rows.extend(audit(name))
        except Exception as exc:
            # A profile the audit cannot get through has not passed, and
            # the tables of the others are still worth printing.
            rows.append((name, "the audit ran to its end", "FAIL",
                         f"{type(exc).__name__}: {exc}"))
    return 1 if report(rows) else 0


if __name__ == "__main__":
    sys.exit(main())
