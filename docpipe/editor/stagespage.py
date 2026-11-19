"""
stagespage.py: The Stages tab: the stages before the harvest as a picture.

Owner request 2026-11-19, point A1 of the review of that day ("ein sechster
Reiter oder ein Eintrag im Ablauf-Reiter zeigt die Stufen 1 bis 6 als
Bild"): from the documents of the profile's source through stages 1 to 6 to
the harvest, each stage with what it does, the command that runs it, its
rules (the tab "stages", one group a stage), the prompts it asks with and
the request logs it writes (stages 4 and 5, owner request A3). What a
stage's logs say is counted on demand (`measured`), at the number of
attempts its rule allows, in the sentences the Flow tab says of the
harvest's (`editor.measured`).

Author: Felix Vossel
"""
from __future__ import annotations

import importlib
from typing import Callable

from .. import rules as rule_files
from . import measured
from . import prompts as prompt_view

# The stages in their order: the number the documentation gives them, what
# each does, the command that runs it, the module that holds its rules, the
# prompts it asks with, the request log it writes (`trace.open_stage`) and
# the rule that says how often it asks a request (its measured sentences).
STAGES = (
    {"n": 1, "key": "text", "name": "Page text", "command": "preprocess",
     "rules": "stage_text",
     "says": "Reads the text of each page from the PDF's own text layer; "
             "a page without one is transcribed by the vision model where "
             "the run asks for it.",
     "prompts": ("preprocessing/page_transcribe",
                 "preprocessing/page_request"),
     "log": None, "attempts": None},
    {"n": 2, "key": "layout", "name": "Layout", "command": "preprocess",
     "rules": "stage_layout",
     "says": "Finds the blocks of each page with the layout model: text, "
             "headings, tables, figures, captions and what stands on every "
             "page; cuts out each table and figure as a picture.",
     "prompts": (), "log": None, "attempts": None},
    {"n": 3, "key": "sections", "name": "Sections", "command": "preprocess",
     "rules": "stage_sections",
     "says": "Puts the blocks in reading order across the columns, drops "
             "running heads and lists of contents, and cuts the document "
             "into sections under its headings.",
     "prompts": (), "log": None, "attempts": None},
    {"n": 4, "key": "refine", "name": "Refinement", "command": "refine",
     "rules": "stage_refine",
     "says": "The text model repairs the text of the sections window by "
             "window, cuts long sections at their topics and cleans the "
             "titles.",
     "prompts": "refinement", "log": "refinement",
     "attempts": "refine_max_attempts"},
    {"n": 5, "key": "visuals", "name": "Tables and figures",
     "command": "visuals", "rules": "stage_visuals",
     "says": "The vision model transcribes each table and describes each "
             "figure; a table that does not fit is read in strips.",
     "prompts": "visuals", "log": "visuals",
     "attempts": "vision_max_attempts"},
    {"n": 6, "key": "chunks", "name": "Pieces and vectors",
     "command": "chunk", "rules": "stage_chunks",
     "says": "Joins text, tables and figures into one document, writes the "
             "database, cuts the pieces the search shows and embeds them.",
     "prompts": ("visuals/context_sentence",
                 "visuals/context_sentence_empty"),
     "log": None, "attempts": None},
)
# What comes before stage 1 and after stage 6.
BEFORE = {"name": "Documents", "command": "ingest",
          "says": "The documents the profile's source names, registered and "
                  "fetched; the exceptions of a register stand in the data "
                  "files of the Sources tab."}
AFTER = {"name": "Harvest", "command": "extract",
         "says": "Reads the values the spec asks for; its steps are drawn "
                 "in the Flow tab."}


def group_of(stage: dict) -> str:
    """The group of the stage's rules on the tab "stages"."""
    return importlib.import_module(
        f"docpipe.ruleset.{stage['rules']}").GROUP


def prompts_of(stage: dict, listed: set) -> list:
    """The prompts the stage asks with that the profile has: those it names,
    or for a stage that writes a request log every prompt its requests are
    made of (`prompts.stage_requests`)."""
    named = stage["prompts"]
    if isinstance(named, str):
        named = [one for ids in prompt_view.stage_requests(named).values()
                 for one in ids]
    return [one for one in dict.fromkeys(named) if one in listed]


def view(profile, logs: Callable) -> dict:
    """The Stages tab: every stage with its rules (how many, how many the
    profile sets itself), its prompts and how many request logs it left;
    *logs(stage)* lists the names of a stage's logs."""
    listed = {one["id"] for one in prompt_view.listing(profile)}
    current = rule_files.load(profile)
    own = {name for name, owner in current.owners.items()
           if profile.name in str(owner)}
    out = []
    for stage in STAGES:
        group = group_of(stage)
        of_stage = [one.name for one in rule_files.of_tab("stages", profile)
                    if one.group == group]
        out.append({
            "n": stage["n"], "key": stage["key"], "name": stage["name"],
            "says": stage["says"], "command": stage["command"],
            "group": group, "rules": len(of_stage),
            "own_rules": sum(name in own for name in of_stage),
            "first_rule": of_stage[0] if of_stage else None,
            "prompts": prompts_of(stage, listed),
            "log": stage["log"],
            "logs": len(logs(stage["log"])) if stage["log"] else 0})
    return {"stages": out, "before": BEFORE, "after": AFTER}


def says(profile, stage_key: str, facts: list) -> dict:
    """What the request logs of one stage say (*facts*, `measured.facts` of
    each log): how many requests, and the sentences of the replies read and
    lost at the number of attempts the stage's rule allows in *profile*."""
    stage = next(one for one in STAGES if one["key"] == stage_key)
    found = measured.joined(facts)
    attempts = stage["attempts"]
    allowed = rule_files.load(profile).get(attempts) if attempts else None
    said = measured.says(found, {"replies": allowed}) \
        if isinstance(allowed, int) else {}
    return {"stage": stage_key, "logs": len(facts),
            "requests": found["requests"], "attempts": attempts,
            "allowed": allowed, "says": said.get("replies", [])}
