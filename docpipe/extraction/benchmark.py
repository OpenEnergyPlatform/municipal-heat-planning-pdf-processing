"""
benchmark.py: One harvest, recorded once and made again without a model.

    docpipe benchmark DIR --record     harvest with the configured model and
                                       keep every answer
    docpipe benchmark DIR              harvest again from those answers and
                                       hold the result against the first one

A benchmark is a directory:

    benchmark.json    which profile, which database and index, which
                      arguments and settings the harvest is run with
    cassette.jsonl    the answers of the recorded run (`providers/cassette`)
    harvest/          what the recorded run harvested, and its query cache
    gold.jsonl        what people decided about it (`gold.py`), once
                      somebody has

Both runs take their command line and their settings from `benchmark.json`,
so the second one asks what the first one asked. Nothing else reaches the
harvest: no setting of the shell the benchmark is started in, no project
file, no .env. The one exception is how the models are reached (provider,
address, key), which a recording takes from where it is run and a replay
does not need. Which model is asked is a setting like any other.

Both runs ask one request at a time. A request shows the model what earlier
requests of the same sweep found, so with several in flight its words
depend on which thread was faster, and a replay would ask other words than
the recording answered.

What a replay shows is what a change to the code does to a harvest whose
answers are held still: how a reply is read, what is accepted, how rows are
settled. A change that makes the run ask something else (a prompt, the
spec, how passages are picked) is not answered from the cassette. The
replay says so and fails, and that change needs a recorded run of its own.

Recording asks a model and writes down the text of the documents it read,
so it is only done on purpose (`--record`) and only for a profile whose
documents may be passed on.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional, Sequence

from .. import dotenv, settings
from ..profile import (ENV_VAR, MARKER, PATH_ENV, load_profile, name_profile,
                       program)
from ..providers import cassette
from . import evaluate, trust
from . import gold as golden

MANIFEST = "benchmark.json"
CASSETTE = "cassette.jsonl"
HARVEST = "harvest"
QUERY_CACHE = "query_cache.db"
KEYS = {"profile", "db", "index", "arguments", "environment",
        "min_precision", "min_recall"}
# What both runs are held to, whatever the description says: one request
# and one document at a time, and sets that iterate the same way twice.
ONE_AT_A_TIME = {"EXTRACT_LLM_PARALLEL": "1", "EXTRACT_FIELD_PARALLEL": "1",
                 "EXTRACT_PLAN_PARALLEL": "1", "EXTRACT_BATCH_DOCS": "1",
                 "EXTRACT_LIMIT_ADAPTIVE": "0", "PYTHONHASHSEED": "0"}
# The settings that say how a model is reached, by their names.
REACHED = re.compile(r"(_PROVIDER|_BASE_URL|_API_KEY)$")


def manifest(directory: Path) -> dict:
    """The benchmark's description, checked."""
    path = Path(directory) / MANIFEST
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"{path}: {exc.strerror or exc}. A benchmark is a "
                         f"directory with a {MANIFEST}.")
    except ValueError as exc:
        raise SystemExit(f"{path}: not JSON ({exc})")
    if not isinstance(found, dict):
        raise SystemExit(f"{path}: must be an object")
    unknown = sorted(set(found) - KEYS)
    if unknown:
        raise SystemExit(f"{path}: unknown key(s) {', '.join(unknown)} "
                         f"(known: {', '.join(sorted(KEYS))})")
    for key in ("profile", "db", "index"):
        if not isinstance(found.get(key), str) or not found[key]:
            raise SystemExit(f"{path}: {key!r} is missing")
    arguments = found.setdefault("arguments", [])
    if not isinstance(arguments, list) or not all(
            isinstance(word, str) for word in arguments):
        raise SystemExit(f"{path}: 'arguments' must be a list of strings")
    environment = found.setdefault("environment", {})
    if not isinstance(environment, dict) or not all(
            isinstance(value, str) for value in environment.values()):
        raise SystemExit(f"{path}: 'environment' must map names to strings")
    for name in (cassette.RECORD_ENV, cassette.REPLAY_ENV, ENV_VAR,
                 *ONE_AT_A_TIME):
        if name in environment:
            raise SystemExit(f"{path}: 'environment' must not set {name}; "
                             f"the benchmark sets it itself")
    for name in environment:
        if REACHED.search(name):
            raise SystemExit(
                f"{path}: 'environment' must not set {name}; how a model "
                f"is reached is taken from where the recording is run")
    for key in ("min_precision", "min_recall"):
        floor = found.get(key)
        if floor is not None and not isinstance(floor, (int, float)):
            raise SystemExit(f"{path}: {key!r} must be a number")
    return found


def command(directory: Path, described: dict, out: Path) -> list:
    """The harvest's command line: the same for both runs."""
    directory = Path(directory)
    return [sys.executable, "-m", "docpipe.extraction",
            str(directory / described["db"]),
            str(directory / described["index"]), str(out),
            *described["arguments"]]


def profile_of(directory: Path, described: dict) -> str:
    """The name of the benchmark's profile. `profile` is a name, or the
    directory of a profile as seen from the benchmark's directory, for a
    profile that is not on the search path where the benchmark is run."""
    folder = Path(directory) / described["profile"]
    if (folder / MARKER).is_file():
        return name_profile(str(folder))
    return described["profile"]


def environment(directory: Path, described: dict, variable: str,
                path: Path, no_env_file: Path) -> dict:
    """The harvest's environment: the benchmark's settings and no others.

    Every setting docpipe reads is taken out of this process's environment
    first, except, for a recording, how the models are reached. *no_env_file*
    is an empty file the harvest is given as its .env, so that it reads
    none of its own.
    """
    recording = variable == cassette.RECORD_ENV
    name = profile_of(directory, described)     # may lead the search path
    env = {key: value for key, value in os.environ.items()
           if key not in settings.BY_ENV or key == PATH_ENV
           or (recording and REACHED.search(key))}
    for key in (cassette.RECORD_ENV, cassette.REPLAY_ENV, *dotenv.NAMED):
        env.pop(key, None)
    env[settings.CONFIG_ENV] = ""               # and no project file
    env[dotenv.NAMED[0]] = str(no_env_file)
    env.update(described["environment"])
    env.update(ONE_AT_A_TIME)
    env[ENV_VAR] = name
    env[variable] = str(path)
    # The package this process runs, wherever the harvest is started.
    package = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(
        [package] + [entry for entry in
                     (env.get("PYTHONPATH") or "").split(os.pathsep)
                     if entry and entry != package])
    return env


def _run(words: list, env: dict) -> int:
    return subprocess.run(words, env=env).returncode


def _harvest(directory: Path, described: dict, out: Path, variable: str,
             tape: Path, run: Callable) -> int:
    """Run the harvest once, with an empty file for its .env."""
    handle, name = tempfile.mkstemp(prefix="benchmark-", suffix=".env")
    os.close(handle)
    try:
        return run(command(directory, described, out),
                   environment(directory, described, variable, tape,
                               Path(name)))
    finally:
        os.unlink(name)


def record(directory: Path, *, run: Callable = _run) -> int:
    """Harvest with the configured model and keep every answer."""
    directory = Path(directory)
    described = manifest(directory)
    tape, out = directory / CASSETTE, directory / HARVEST
    profile = load_profile(profile_of(directory, described))
    if not profile.documents_shareable:
        raise SystemExit(
            f"profile {profile.name!r} does not say its documents may be "
            f"passed on (Profile(documents_shareable=True)), and a recorded "
            f"run holds their text: nothing is recorded.")
    if tape.exists() or (out.exists() and any(out.iterdir())):
        raise SystemExit(
            f"{directory} already holds a recorded run ({CASSETTE} or "
            f"{HARVEST}/). A second run appended to it would be two runs in "
            f"one file: move the old one away first.")
    code = _harvest(directory, described, out, cassette.RECORD_ENV, tape,
                    run)
    if code:
        print(f"the harvest ended with {code}: what {tape.name} holds is "
              f"not a whole run", file=sys.stderr)
        return code
    if not tape.is_file():
        print(f"the harvest wrote no {tape.name}: it asked no model",
              file=sys.stderr)
        return 1
    print(f"{directory}: recorded. {golden.FILE_NAME} is written by the "
          f"review page of the chat app.")
    return 0


def replay(directory: Path, out: Optional[Path] = None, *,
           run: Callable = _run) -> int:
    """Harvest again from the recorded answers and hold the result against
    the recorded harvest and the decisions."""
    directory = Path(directory)
    described = manifest(directory)
    tape, recorded = directory / CASSETTE, directory / HARVEST
    for needed in (tape, recorded):
        if not needed.exists():
            raise SystemExit(f"{needed} is missing: nothing was recorded "
                             f"here yet (`{program('docpipe.extraction.benchmark')}"
                             f" {directory} --record`)")
    kept = out is not None
    out = Path(out) if kept else Path(tempfile.mkdtemp(prefix="benchmark-"))
    try:
        out.mkdir(parents=True, exist_ok=True)
        if any(out.glob("*.jsonl")):
            raise SystemExit(f"{out} already holds a harvest; a replay "
                             f"starts from none")
        # The vectors the recorded run searched with: a run that had its
        # embedding model on its own machine left them nowhere else.
        if (recorded / QUERY_CACHE).is_file():
            shutil.copyfile(recorded / QUERY_CACHE, out / QUERY_CACHE)
        code = _harvest(directory, described, out, cassette.REPLAY_ENV,
                        tape, run)
        if code:
            print(f"the replayed harvest ended with {code}: it is not the "
                  f"recorded run made again (see its log above)",
                  file=sys.stderr)
            return code
        rows = golden.harvest(out)
        gold = golden.Gold.load(directory / golden.FILE_NAME)
        # As `docpipe evaluate` counts it: a document whose pages a model
        # transcribed is level B at best.
        database = directory / described["db"]
        report = evaluate.evaluate(
            rows, gold, transcribed=trust.transcribed_documents(
                database if database.is_file() else None))
        comparison = evaluate.compare(rows, golden.harvest(recorded), gold)
        print(evaluate.render(report, comparison))
        short = evaluate.below(report, described.get("min_precision"),
                               described.get("min_recall"))
        for line in short:
            print(line, file=sys.stderr)
        return 1 if short else 0
    finally:
        if not kept:
            shutil.rmtree(out, ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.extraction.benchmark"),
        description="Record one harvest with a model, or make a recorded "
                    "one again without a model and compare.")
    parser.add_argument("directory", type=Path,
                        help=f"the benchmark: a directory with a {MANIFEST}")
    parser.add_argument("--record", action="store_true",
                        help="ask the configured model and keep its answers "
                             "(default: replay what was recorded)")
    parser.add_argument("--out", type=Path,
                        help="keep the replayed harvest here (default: a "
                             "temporary directory, removed afterwards)")
    args = parser.parse_args(argv)
    if args.record:
        if args.out:
            raise SystemExit(f"--record writes into the benchmark's own "
                             f"{HARVEST}/; --out is for a replay")
        return record(args.directory)
    return replay(args.directory, args.out)


if __name__ == "__main__":
    from docpipe.profile import bind_command_line
    bind_command_line()
    sys.exit(main())
