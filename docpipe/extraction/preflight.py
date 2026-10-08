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
(`extraction.PROMPT_CHECKS`). The shapes of its graph are the profile's as
well: it says where they are (`extraction.shapes_files`) and which of their
properties it leaves out on purpose (`extraction.NOT_EXTRACTED`).

Two lines only say what they find and never fail: the properties of the
shapes that nobody asks and the definitions of the spec that are not the
pin's. A third fails when it must: the example reply of the field prompt has
to read back through the reader of the run, and the same reply with an
invented quote has to be refused.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
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


def not_extracted(declared) -> tuple:
    """A profile's `extraction.NOT_EXTRACTED` as ({(shape, property): why},
    what is wrong with it).

    The shape properties the profile leaves out on purpose, each with a
    sentence of reason. An entry that is anything else is named and not
    counted: a record that cannot be read records nothing, so what it was
    meant to cover warns as if it were not there. The same holds for a value
    that is no mapping at all, which is named once.
    """
    if not declared:
        return {}, []
    if not isinstance(declared, Mapping):
        return {}, [f"the record itself is of type "
                    f"{type(declared).__name__}, not a mapping"]
    good, bad = {}, []
    for key, why in declared.items():
        if (isinstance(key, (tuple, list)) and len(key) == 2
                and all(isinstance(part, str) and part for part in key)
                and isinstance(why, str) and why.strip()):
            good[tuple(key)] = why
        else:
            bad.append(repr(key))
    return good, bad


def shape_properties(files, raw: dict) -> tuple:
    """(properties no parameter asks, all properties) of the shapes.

    Both as sorted (shape, property) pairs, the property by the end of its
    IRI. A property is asked when a parameter's `kg` block names it or the
    graph block links it: `docpipe compile diff` decides that and this reads
    what it lists as "not_asked". The shapes file is read as the compiler
    reads it, which needs rdflib.
    """
    from docpipe.compile import draft, shapes
    found, _prefixes = shapes.read(files)
    every = sorted({(shape.name, draft.local(prop.path))
                    for shape in found for prop in shape.properties})
    unasked = sorted({(row["shape"], row["path"])
                      for row in draft.differences(found, raw)
                      if row["kind"] == "not_asked"})
    return unasked, every


def shapes_verdict(profile, raw: dict) -> tuple:
    """(ok, detail) for the shape properties nobody asks, never a failure.

    The profile says where its shapes are (`extraction.shapes_files`, the
    files of its last refresh) and which of their properties it leaves out on
    purpose (`extraction.NOT_EXTRACTED`). Where it names no shapes, or the
    file is not there, or rdflib is not, the line says it is skipped: a
    check that was not run is not a gap found.
    """
    left_out, unreadable = not_extracted(
        profile.component("extraction", "NOT_EXTRACTED"))
    hook = profile.component("extraction", "shapes_files")
    if hook is None:
        return True, "skipped: the profile names no shapes file"
    try:
        files = [Path(one) for one in hook()]
    except Exception as exc:              # a hook that does not run names none
        return False, f"shapes_files: {type(exc).__name__}: {exc}"
    files = [one for one in files if one.is_file()]
    if not files:
        return True, "skipped: no shapes file of the last refresh"
    try:
        import rdflib                                          # noqa: F401
    except ImportError:
        return True, "skipped: rdflib is not installed"
    try:
        unasked, every = shape_properties(files, raw)
    except Exception as exc:              # a file that does not parse
        return False, (f"the shapes could not be read: "
                       f"{type(exc).__name__}: {exc}")
    open_ = [pair for pair in unasked if pair not in left_out]
    shown = [f"{shape}.{path}" for shape, path in open_]
    return not open_ and not unreadable, (
        f"{len(open_)} of {len(every)} shape propert(y/ies) nobody asks "
        f"and the profile does not record"
        + (": " + ", ".join(shown[:8]) + (", ..." if len(shown) > 8 else "")
           if shown else "")
        + (f"; unreadable NOT_EXTRACTED entries: "
           f"{', '.join(unreadable[:3])}" if unreadable else ""))


# The passage the example reply is held to when its quote is made up. It has
# to be long enough to name a place and has to stand in no passage that is
# shown, which `reads_back` checks before it uses it.
INVENTED_QUOTE = "A passage that no source of this request contains."


def example_lines(text: str) -> list:
    """The lines of a field prompt that are an example reply.

    The prompt asks for the reply on ONE line, so its example is one: the
    lines that open the object the reply is. A wrapped example is not found
    here, which `audit` says and does not pass over.
    """
    return [line.strip() for line in (text or "").splitlines()
            if line.strip().startswith('{"fields"')]


def reads_back(line: str, spec) -> tuple:
    """(ok, detail) for one example reply, read the way a run reads a reply.

    The line goes through `runner._loads_object` and the field it answers
    through `merge_field`, against passages that are the example's own
    quotes: every row of it has to come out read, apart from a row the
    example itself answers "not stated". Then the same reply with every
    quote replaced by one that stands in none of those passages has to come
    out unbacked on every row, or the first half would hold of any reply.

    The field is the spec's coordinate of that name. A list that the profile
    only fills per document is no list here, and a name the spec has no
    coordinate for is read as free text, which the detail says.
    """
    import json

    from . import fields
    from .pipeline import Row, Source, merge_field
    from .runner import _loads_object
    from .verify import quote_in

    data = _loads_object(line)
    if data is None:
        return False, "the example is not exactly one JSON object"
    named = data.get("fields")
    if not isinstance(named, dict) or len(named) != 1:
        return False, ('the example does not name exactly one field under '
                       '"fields"')
    (field_name, answer), = named.items()
    if not isinstance(answer, dict):
        return False, f"the example's answer for {field_name!r} is no object"

    # The rows the way merge_field takes them: "answers" first, the rows of a
    # group after, and the first mention of a row is the one that counts.
    said: dict = {}
    singles = answer.get("answers")
    for label, one in (singles.items() if isinstance(singles, dict) else ()):
        said.setdefault(str(label).strip(), one)
    groups = [one for one in answer.get("groups") or ()
              if isinstance(one, dict)]
    for group in groups:
        for label in group.get("rows") or ():
            said.setdefault(str(label).strip(), group)
    if not said:
        return False, "the example answers no row"
    unstated = {label for label, one in said.items()
                if isinstance(one, dict)
                and str(one.get("value")).strip() == fields.UNSTATED}
    quotes = []
    for one in said.values():
        text = one.get("quote") if isinstance(one, dict) else None
        if isinstance(text, str) and text not in quotes:
            quotes.append(text)
    sources = [Source("section", index, text)
               for index, text in enumerate(quotes)]
    if any(quote_in(source.text, INVENTED_QUOTE) for source in sources):
        return False, "the invented quote stands in a passage of the example"

    if field_name == "parameter":
        slot = fields.parameter_slot(spec)
    elif field_name == fields.UNIT:
        slot = fields.unit_slot(spec)
    else:
        slot = next((one for parameter in spec.parameters
                     for one in fields.axis_slots(parameter)
                     if one.name == field_name), None)
    free = slot is None
    if free:
        slot = fields.Slot(name=field_name, kind=fields.TEXT)
    state = f"{slot.name}_state"

    def read(reply):
        rows = [Row(label, 0) for label in said]
        return rows, merge_field(rows, sources, slot, reply)

    rows, result = read(answer)
    wrong = [f"{row['row']}: {row['why']}" for row in result["failed"]]
    missed = [f"{row.label}: not read" for row in rows
              if row.label not in unstated
              and row.claim.get(state) != fields.READ]
    if wrong or missed:
        return False, ("row(s) of the example do not come out backed: "
                       + "; ".join((wrong + missed)[:3]))
    kept = len(rows) - len(unstated)
    if kept < 1:
        return False, "no row of the example carries a quote to be backed"

    # The same reply with every quote made up, in a group and in an answer.
    made_up = json.loads(json.dumps(answer))
    entries = list(made_up["answers"].values()) \
        if isinstance(made_up.get("answers"), dict) else []
    entries += [one for one in made_up.get("groups") or ()
                if isinstance(one, dict)]
    for one in entries:
        if isinstance(one, dict) and "quote" in one:
            one["quote"] = INVENTED_QUOTE
    rows, result = read(made_up)
    read_anyway = [row.label for row in rows
                   if row.label not in unstated
                   and row.claim.get(state) == fields.READ]
    if read_anyway:
        return False, ("a quote that stands in no passage is still read on "
                       f"{len(read_anyway)} row(s): "
                       + ", ".join(read_anyway[:3]))
    return True, (f"{kept} row(s) read from their quotes, and "
                  f"{kept} row(s) unbacked with an invented one"
                  + (f"; {field_name!r} is no coordinate of this spec, read "
                     f"as free text" if free else ""))


def example_verdict(line: str, spec) -> tuple:
    """`reads_back` for the audit, which a broken example must not abort.

    An example whose "groups" is no list or whose "rows" is none cannot be
    walked at all, and the reader says so by raising. For the audit that is
    a failed line that names the example's fault, as it is for any other
    example the reader does not read, and not a traceback in place of the
    other checks of the profile.
    """
    try:
        return reads_back(line, spec)
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        return False, ("the reader could not walk the example: "
                       f"{type(exc).__name__}: {exc}")


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

    # The reply the prompt prints is the one the model imitates, so it has to
    # be a reply the reader reads and backs. The words above only say the
    # prompt names its keys; a prompt can name them all and show an example
    # whose quote is in no passage or whose answer is not in its quote.
    # Checked on the one-line example of the prompt itself, with the reader
    # the run uses, and a copy of it with an invented quote has to be refused,
    # which is what lets this fail.
    if not field_text.strip():
        check("field prompt's own example reads back", False,
              "no field prompt to take an example from")
    else:
        examples = example_lines(field_text)
        if not examples:
            check("field prompt's own example reads back", False,
                  'no line of the field prompt starts with {"fields"; its '
                  "example is not on one line, or it has none",
                  fatal=False)
        else:
            verdicts = [example_verdict(one, spec) for one in examples]
            failed = [detail for ok, detail in verdicts if not ok]
            check("field prompt's own example reads back", not failed,
                  "; ".join(failed[:2]) if failed else
                  (verdicts[0][1] if len(verdicts) == 1 else
                   f"{len(verdicts)} example line(s): "
                   + "; ".join(detail for _ok, detail in verdicts)))

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
            # The words the model reads of a class stand in the spec and the
            # pin is the yardstick: a refresh that rewrites a definition
            # moves nothing the model is asked, and the spec is edited by
            # hand. Said and never refused, like the labels above, which are
            # the note on a label that differs.
            from docpipe import ontology as _ontology
            if "terms" not in snapshot:
                # A pin of a project's own making, which lists no terms to
                # hold a definition against: not run, and said so.
                check("definitions agree with the pin", True,
                      "skipped: the pin lists no terms")
            else:
                defined = _ontology.definition_differences(raw, snapshot)
                rewritten = [one[1] for one in defined
                             if one[2] == _ontology.REWRITTEN]
                only_pin = [one[1] for one in defined
                            if one[2] == _ontology.PIN_ONLY]

                def some(classes: list) -> str:
                    return ", ".join(classes[:3]) + (
                        ", ..." if len(classes) > 3 else "")
                check("definitions agree with the pin", not defined,
                      f"{len(rewritten)} class(es) with a rewritten "
                      f"definition"
                      + (f" ({some(rewritten)})" if rewritten else "")
                      + f", {len(only_pin)} class(es) only the pin defines"
                      + (f" ({some(only_pin)})" if only_pin else ""),
                      fatal=False)
            # Named rather than silent. A term of an ontology no file of this
            # snapshot covers is neither right nor wrong here. Reporting it
            # as an error would teach everyone to ignore the real ones;
            # reporting nothing would let the gap grow.
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

    # What the shapes of the graph hold that nobody asks for. A property a
    # parameter does not read is either left out on purpose, and the profile
    # says so with a reason (`extraction.NOT_EXTRACTED`), or nobody decided.
    # The second is a warning: it stops no run, it makes the gap readable
    # where it was only a hand command (`docpipe compile diff`).
    ok, detail = shapes_verdict(profile, raw)
    check("every shape property is asked or left out on purpose", ok, detail,
          fatal=False)
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
