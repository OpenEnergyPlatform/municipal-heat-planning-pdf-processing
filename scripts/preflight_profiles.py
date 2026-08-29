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
             for p in spec.parameters for s in fields.axis_slots(p)
             if not (s.question or "").strip()]
    check(profile, "jede Achse hat eine Frage", not blank, ", ".join(blank))

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
    wanted = 1 + sum(1 + len(fields.axis_slots(p)) for p in spec.parameters)
    check(profile, "ein Anker je Frage",
          len(keys) == len(set(keys)) == wanted, f"{len(keys)} Ziel(e)")
    with_question = [t for t in targets if t[3]]
    check(profile, "jedes Achsenziel traegt seine Frage",
          len(with_question) >= wanted - len(spec.parameters) - 1,
          f"{len(with_question)} mit Frage")

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
    rows_text = prompts.load("extraction/rows").text
    check(profile, "Zeilen-Prompt nennt 'quantities'", '"quantities"' in rows_text)
    check(profile, "Zeilen-Prompt fixiert keinen Parameter mehr",
          '"parameter": die gesucht' not in rows_text)
    anchors_text = prompts.load("extraction/anchors").text
    check(profile, "Anker-Prompt kennt die Frage", '"question"' in anchors_text)

    kg = base / "kg.py"
    check(profile, "Serializer vorhanden", kg.is_file(), str(kg))


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
