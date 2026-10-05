"""
run.py: `docpipe run`, the stages that turn a folder into a corpus.

    docpipe run [--from STAGE] [--to STAGE] [--skip STAGE ...]

ingest, preprocess, refine, visuals, chunk and lexical, in that order, for
the profile in effect. Each is started the way `docpipe <stage>` starts it,
in a process of its own: a stage that holds a model, or dies, leaves nothing
behind for the next one. The harvest (`extract`) is not among them: it needs
a spec, and what it costs is for its own command to say.

A stage is given the arguments its command line needs and the profile
knows, and no others: ingest takes its paths from the profile and needs
`--source` only where the profile's source has a document list to name,
preprocess takes the profile's PDF folder as its input, refine and visuals
take `--batch` (their input is the profile's processed folder). A stage that
cannot start without an argument the profile cannot give is named before any
stage starts. The run stops at the first stage that ends non-zero, with that
stage's exit code.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from typing import Callable, Optional, Sequence

from .profile import require_profile

# The order the stages build on each other; `docpipe status` has the same columns.
STAGES = ("ingest", "preprocess", "refine", "visuals", "chunk", "lexical")

# What a signal killed is told as a shell tells it: 128 plus the signal.
SIGNAL_BASE = 128
INTERRUPTED = 130
USAGE_ERROR = 2


def _ingest(profile) -> tuple:
    """`docpipe ingest` names its document list by `--source`, unless the
    profile's source has a place where the list stands without being told."""
    try:
        source = profile.component("source", "SOURCE")
    except ImportError as exc:
        return [], [f"its document source, which cannot be loaded: {exc}"]
    if source is None:
        return [], ["a document source (source.py: SOURCE), which this "
                    "profile does not provide"]
    default = getattr(source, "default_location", None)
    if default is None or default(profile.pdf_dir) is None:
        return [], ["--source: the profile's document list, which this "
                    "profile has no place for by default"]
    return [], []


def _preprocess(profile) -> tuple:
    """The stage's input is a PDF or a folder of them and it has no default;
    the profile's PDF folder is where ingest puts them."""
    return [str(profile.pdf_dir)], []


def _batch(profile) -> tuple:
    """Refine and visuals default to the profile's processed folder, which
    holds one directory per document; without `--batch` they would take it
    for one document."""
    return ["--batch"], []


def _alone(profile) -> tuple:
    """Every path comes from the profile."""
    return [], []


# stage -> (arguments it is given, what the profile cannot give it), for a profile
_GIVEN: dict = {
    "ingest": _ingest,
    "preprocess": _preprocess,
    "refine": _batch,
    "visuals": _batch,
    "chunk": _alone,
    "lexical": _alone,
}


def select(first: Optional[str] = None, last: Optional[str] = None,
           skip: Sequence[str] = ()) -> list:
    """The stages from *first* to *last* without those in *skip*, in order.
    A range that holds no stage is an error, not an empty run."""
    for name in (first, last, *skip):
        if name is not None and name not in STAGES:
            raise ValueError(f"{name!r} is not a stage of this command "
                             f"({', '.join(STAGES)})")
    start = STAGES.index(first) if first else 0
    end = STAGES.index(last) if last else len(STAGES) - 1
    if start > end:
        raise ValueError(f"--from {first} comes after --to {last} "
                         f"({', '.join(STAGES)})")
    chosen = [stage for stage in STAGES[start:end + 1] if stage not in skip]
    if not chosen:
        raise ValueError("no stage is left to run: --skip names every stage "
                         "from --from to --to")
    return chosen


def stage_command(stage: str, arguments: Sequence[str]) -> list:
    """The process that is `docpipe <stage> <arguments>`. The profile and the
    project file reach it through the environment."""
    return [sys.executable, "-m", "docpipe", stage, *arguments]


def launch(command: Sequence[str]) -> int:
    """Run *command* to its end and return its exit code."""
    code = subprocess.call(list(command))
    return SIGNAL_BASE - code if code < 0 else code


def run_stages(profile, stages: Sequence[str],
               launcher: Optional[Callable] = None) -> int:
    """Start *stages* one after the other, for *profile*. Returns 0 when all
    ended 0, else the exit code of the first that did not. Nothing is started
    while a stage lacks an argument the profile cannot give."""
    launcher = launcher or launch
    plan: list = []
    lacking: list = []
    for stage in stages:
        arguments, missing = _GIVEN[stage](profile)
        plan.append((stage, arguments))
        lacking += [(stage, what) for what in missing]
    if lacking:
        blocked = len({stage for stage, _ in lacking})
        print(f"docpipe run: nothing was started; {blocked} stage(s) cannot "
              f"start under the profile {profile.name!r}:", file=sys.stderr)
        for stage, what in lacking:
            print(f"  {stage} needs {what}", file=sys.stderr)
        print("Run such a stage by itself, given what it needs, and leave it "
              "out here with --skip, or start after it with --from.",
              file=sys.stderr, flush=True)
        return USAGE_ERROR
    total = len(plan)
    print(f"docpipe run: {total} stage(s) under the profile "
          f"{profile.name!r}: {', '.join(stage for stage, _ in plan)}",
          flush=True)
    for number, (stage, arguments) in enumerate(plan, 1):
        shown = shlex.join(["docpipe", stage, *arguments])
        print(f"docpipe run: stage {number} of {total}: {shown}", flush=True)
        try:
            code = launcher(stage_command(stage, arguments))
        except KeyboardInterrupt:
            code = INTERRUPTED
            reason = "was interrupted"
        else:
            reason = f"ended with exit code {code}"
        if code:
            left = [name for name, _ in plan[number:]]
            tail = (f"; not run: {', '.join(left)}" if left else "")
            print(f"docpipe run: {stage} {reason}{tail}", file=sys.stderr,
                  flush=True)
            return code
    print(f"docpipe run: {total} stage(s) ended 0; `docpipe status` says what "
          f"each document has", flush=True)
    return 0


def main(rest: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="docpipe run",
        description="Run the stages ingest, preprocess, refine, visuals, "
                    "chunk and lexical one after the other, each as its own "
                    "command would run it, for the profile in effect. It "
                    "stops at the first stage that ends non-zero, with that "
                    "stage's exit code. The harvest (extract) is not part "
                    "of it.")
    parser.add_argument("--from", dest="first", choices=STAGES,
                        metavar="STAGE", help="start with this stage "
                        "(default: ingest)")
    parser.add_argument("--to", dest="last", choices=STAGES, metavar="STAGE",
                        help="end with this stage (default: lexical)")
    parser.add_argument("--skip", action="extend", nargs="+", default=[],
                        choices=STAGES, metavar="STAGE",
                        help="leave these stages out")
    args = parser.parse_args(list(rest))
    try:
        stages = select(args.first, args.last, args.skip)
    except ValueError as exc:
        parser.error(str(exc))
    return run_stages(require_profile(), stages)
