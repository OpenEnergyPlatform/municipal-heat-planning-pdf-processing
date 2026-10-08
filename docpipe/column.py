"""
column.py: `docpipe column`, a column of one's own for a trial harvest.

    docpipe column NAME DESCRIPTION [--dir FOLDER]

A profile asks what its spec asks, and a spec comes from an ontology. A
question of one's own, put to a few documents, has no place there. This
writes the spec of one such question into a folder of its own: one parameter,
read as text, from a name and a description in plain words ("Renovation
rate", "How many percent of the buildings are renovated each year"). It
writes no example, because the spec loader wants a real one and a person has
to read it. The rest is commands that exist, each given the folder's names:

    docpipe compile examples DRAFT --profile P   propose the example
    docpipe compile apply DRAFT --out SPEC --profile P
                                                 carry the one a person
                                                 accepted into the spec
    docpipe extract DB INDEX HARVEST --spec SPEC --document ID
    docpipe export HARVEST --out TABLE

The harvest checks every value as every harvest does: its quote stands in a
shown passage, and the answer stands in the quote. It is a trial. Nothing
here adopts the column into a profile's spec and nothing here hands the
folder to the serializer. The folder keeps itself out of version control,
because its example and its harvest are passages of the corpus.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional, Sequence

from .compile import draft as drafting
from .compile import examples as proposing
from .extraction import scratch
from .profile import ENV_VAR

# What the folder's own .gitignore says: everything, itself included.
IGNORE = "*\n"


def draft(name: str, description: str) -> dict:
    """The one-parameter draft: the label as the person wrote it, the
    identifier made from it, the description as given and no example."""
    label = " ".join(name.split())
    return {
        "_comment": (
            "A column of one's own, written by `docpipe column`. It is a "
            "draft until it has an example: `docpipe compile examples` "
            "proposes one from the corpus and a person accepts it."),
        "parameters": [{
            "uri": drafting.slug(label),
            "label": label,
            "description": " ".join(description.split()),
            "value_type": "text",
            "axes": {},
        }],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docpipe column",
        description="A column of one's own: the spec of one question for a "
                    "trial harvest, written into a folder of its own from a "
                    "name and a description in plain words. It is no part "
                    "of any profile and not meant for the graph: nothing "
                    "here adopts it into a profile's spec, and nothing here "
                    "hands the folder to the serializer; do not give it to "
                    "`docpipe extract --serialize` either.")
    parser.add_argument("name", help="what the column is called; this is "
                                     "its label, and its identifier is "
                                     "this in lower-case letters, digits "
                                     "and _")
    parser.add_argument("description",
                        help=f"what the column asks for: the model reads "
                             f"this to know what to look for, so say what "
                             f"the value is and what it is not (at least "
                             f"{drafting.MIN_DESCRIPTION_WORDS} words)")
    parser.add_argument("--dir", type=Path, default=None,
                        help=f"the folder of the column (default: "
                             f"{scratch.HOME}/<identifier>)")
    return parser


def _typed(path) -> str:
    """A path as it is typed into a command: in quotes where it holds a
    space, so that the line can be copied as it stands."""
    text = str(path)
    return f'"{text}"' if any(char.isspace() for char in text) else text


def _next_steps(home: Path, profile: Optional[str]) -> str:
    draft_file = _typed(home / scratch.DRAFT)
    spec_file = _typed(home / scratch.SPEC)
    harvest = _typed(home / scratch.HARVEST)
    given = profile or "PROFILE"
    return "\n".join([
        "Next, each as its command runs it:",
        f"  docpipe compile examples {draft_file} --profile {given}",
        f"      read {proposing.review_path(home / scratch.DRAFT)} and set "
        f"\"accept\": true on one proposal",
        f"  docpipe compile apply {draft_file} --out {spec_file} "
        f"--profile {given}",
        f"  docpipe extract DB INDEX {harvest} --spec {spec_file} "
        f"--document ID --profile {given}",
        f"  docpipe export {harvest} --out {_typed(home / scratch.TABLE)} "
        f"--profile {given}",
        "",
        f"The harvest is a trial with stamps of its own; {harvest} is not "
        f"for `docpipe extract --serialize`."])


def main(rest: Sequence[str]) -> int:
    args = _parser().parse_args(list(rest))
    raw = draft(args.name, args.description)
    uri = raw["parameters"][0]["uri"]
    if not uri:
        raise SystemExit(f"{args.name!r} cannot name a column: it has no "
                         f"letter or digit to make an identifier of")
    home = args.dir or Path(scratch.HOME) / uri
    draft_file = home / scratch.DRAFT
    if draft_file.exists():
        raise SystemExit(f"{draft_file} exists already; nothing was "
                         f"written. Give another name or --dir")
    home.mkdir(parents=True, exist_ok=True)
    draft_file.write_text(json.dumps(raw, ensure_ascii=False, indent=1)
                          + "\n", encoding="utf-8")
    written = [draft_file]
    ignore = home / ".gitignore"
    if not ignore.exists():
        ignore.write_text(IGNORE, encoding="utf-8")
        written.append(ignore)
    for path in written:
        print(f"wrote {path}")
    open_points = drafting.todo(raw)
    print(f"{len(open_points)} point(s) open in {draft_file}:")
    for line in open_points:
        print(f"  {line}")
    print()
    print(_next_steps(home, os.environ.get(ENV_VAR)))
    return 0
