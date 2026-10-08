"""
cli.py: The one command.

    docpipe [--profile P] [--config FILE] <command> [arguments]

A stage binds part of what a profile and a project say when it is imported.
So this module imports no stage. It settles the profile and the project file
first, and then runs the stage the way `python -m docpipe.<stage>` runs it,
which keeps working and takes the same arguments.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__, settings
from .profile import ENV_VAR, ROOT, available_profiles, \
    bind_command_line, name_profile, profile_locations

# command -> (module run as __main__, one line of help)
STAGES = {
    "ingest": ("docpipe.ingest", "stage 1: register and fetch the documents "
                                 "the profile's source names"),
    "preprocess": ("docpipe.preprocessing", "stages 2-3: layout, reading "
                                            "order, sections"),
    "refine": ("docpipe.refinement", "stage 4: repair the text of each "
                                     "section"),
    "visuals": ("docpipe.visuals", "stage 5: transcribe tables, describe "
                                   "figures"),
    "chunk": ("docpipe.chunking", "stage 6: merge, database, embeddings"),
    "reanchor": ("docpipe.extraction.identity", "after a rebuilt database: "
                 "find each harvested row's passage again"),
    "compile": ("docpipe.compile", "draft an extraction spec from the "
                "shapes and the ontology of a graph"),
    "preflight": ("docpipe.extraction.preflight", "before a corpus run: "
                  "the profile's spec, prompts, schema and graph writer"),
    "estimate": ("docpipe.estimate", "before a run: the requests, tokens and "
                 "price each stage still has ahead of it, no model called"),
    "extract": ("docpipe.extraction", "stage 7: harvest values, top up, "
                                      "review, serialize"),
    "evaluate": ("docpipe.extraction.evaluate", "precision and recall of a "
                 "harvest against what people decided; --diff: two "
                 "harvests compared"),
    "benchmark": ("docpipe.extraction.benchmark", "record one harvest with "
                  "a model, or make it again without one"),
    "export": ("docpipe.serve.export", "values, states or refusals of a "
               "harvest as a table (CSV, JSON lines)"),
    "serve": ("docpipe.serve", "answer questions about a harvest, its "
              "states and the corpus passages: HTTP API or MCP server"),
    "lexical": ("docpipe.inference.lexical", "build the word index the chat "
                "searches beside the vectors"),
    "sandbox": ("docpipe.app.sandbox_service", "the service that runs code "
                "a model wrote, in a container without a network"),
}
OWN = {
    "init": "start a project here: a project file and a profile of its own",
    "run": "ingest to lexical in one go, each as its own command runs it",
    "status": "which stage has left output for which document",
    "chat": "the chat over a processed corpus",
    "doctor": "check this installation: packages, profile, servers, "
              "prompts, data",
    "config": "every setting, its value and where the value comes from",
    "profiles": "the profiles this installation finds, and where",
    "column": "a column of one's own: the spec of one question for a "
              "trial harvest, in a folder of its own",
}
USAGE = "docpipe [--profile P] [--config FILE] <command> [arguments]"


def _help() -> str:
    lines = [f"usage: {USAGE}", "", "commands:"]
    for name, (_module, text) in STAGES.items():
        lines.append(f"  {name:<11} {text}")
    for name, text in OWN.items():
        lines.append(f"  {name:<11} {text}")
    lines += ["", "options:",
              "  --profile P    the project profile: a name, or the "
              f"directory of one (default: ${ENV_VAR})",
              f"  --config FILE  the project file (default: the nearest "
              f"{settings.PROJECT_FILE}, or ${settings.CONFIG_ENV})",
              "  --version",
              "", "Both options are also taken after the command. "
              "`docpipe <command> --help`",
              "shows a command's own arguments."]
    return "\n".join(lines)


def _split(argv: Sequence[str]):
    """(options given before the command, the command, the rest)."""
    options: dict = {}
    rest = list(argv)
    while rest and rest[0].startswith("-"):
        word = rest.pop(0)
        name, _, value = word.partition("=")
        if name in ("--profile", "--config"):
            if not _:
                if not rest:
                    raise SystemExit(f"{name} needs a value\n{USAGE}")
                value = rest.pop(0)
            options[name[2:]] = value
        elif word in ("-h", "--help"):
            options["help"] = True
        elif word == "--version":
            options["version"] = True
        else:
            raise SystemExit(f"unknown option {word}\n{USAGE}")
    command = rest.pop(0) if rest else None
    return options, command, rest


def _pull(rest: Sequence[str], names: Sequence[str]):
    """(the options of *names* found among a command's arguments, the
    arguments without them). What follows a bare `--` is left alone."""
    options: dict = {}
    kept: list = []
    words = list(rest)
    while words:
        word = words.pop(0)
        if word == "--":
            kept += [word, *words]
            break
        name, given, value = word.partition("=")
        if name in names:
            if not given:
                if not words:
                    raise SystemExit(f"{name} needs a value\n{USAGE}")
                value = words.pop(0)
            options[name[2:]] = value
        else:
            kept.append(word)
    return options, kept


def _settle(options: dict) -> None:
    """The project file and the profile, before anything is imported that
    binds either."""
    if "config" in options:
        try:
            path = settings.apply(options["config"])
        except settings.ConfigError as exc:
            raise SystemExit(str(exc))
        # for a process this one starts, and for whatever looks again
        os.environ[settings.CONFIG_ENV] = str(path)
    if options.get("profile"):
        os.environ[ENV_VAR] = name_profile(options["profile"])


def _run_stage(command: str, rest: Sequence[str]) -> int:
    module = STAGES[command][0]
    saved = sys.argv
    sys.argv = [f"docpipe {command}", *rest]
    # A --profile after the command, before anything of the stage is
    # imported: a stage whose module is its own entry point (`export`,
    # `evaluate`, `lexical`) has no `__main__` that could do it in time.
    bind_command_line(rest)
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    finally:
        sys.argv = saved
    return 0


def _chat(rest: Sequence[str]) -> int:
    app = Path(__file__).resolve().parent / "app" / "app.py"
    import importlib.util
    if importlib.util.find_spec("streamlit") is None:
        raise SystemExit("the chat needs streamlit: "
                         "pip install 'docpipe[app]'")
    return subprocess.call([sys.executable, "-m", "streamlit", "run",
                            str(app), *rest])


PROJECT_TOML = """\
# The project file. A value here stands unless the environment sets the same
# name; a key or a token belongs in .env, not here. Every setting, its value
# and where the value comes from: `docpipe config`.
profile = "{name}"

[llm]
# A server of one's own that speaks the OpenAI API, or a hosted model:
# base_url = "http://localhost:8000/v1"
# model = ""
# provider = "openai-compatible"      # or: openai, anthropic, gemini

[vlm]
# The vision model: reads pages without text, tables and figures.
# base_url = "http://localhost:8001/v1"
# model = ""
# provider = "openai-compatible"

[refine]
# Ask for corrections (find and replace) instead of every section retyped.
return_corrections = true
"""

PROFILE_PY = """\
\"\"\"{title}: this project's profile.

It extends the profile docpipe brings itself. What is written here, and in
the files beside this one, replaces that profile's part of the same name: a
prompt under prompts/<stage>/<name>.md, a word list in preprocessing.py, the
labels in inference.py, the tables in schema.sql. `docpipe doctor` shows what
is in effect.
\"\"\"
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="{name}",
    extends="default",
    title="{title}",
    document_noun="document",
    facets=(
        Facet("folder", "Folder"),
    ),
)
"""


EXTRACTION_PY = """\
\"\"\"Extraction: this project's spec, once there is one.

`docpipe compile spec --shapes ... --out extraction_spec.draft.json` drafts
it from the shapes of a graph, and `docpipe compile apply ... --out
extraction_spec.json` (beside this file) writes it when nothing is open.
\"\"\"
from pathlib import Path

_SPEC = Path(__file__).with_name("extraction_spec.json")
SPEC_PATH = _SPEC if _SPEC.is_file() else None
"""


DRAFT_FILE = "extraction_spec.draft.json"


def _draft_from_shapes(given):
    """(the draft of a spec, the shapes file it is from). `given` is a file
    of the user's, or True for the one the package brings. Raises SystemExit
    before anything is written, naming the file that could not be used."""
    if given == "":
        # An unset variable in `--shapes "$FILE"`: not the bundled shape.
        raise SystemExit("--shapes was given an empty file name; nothing "
                         "was written")
    try:
        from .compile import cli as compiling
        from .compile import shapes
        path = shapes.BUNDLED if given is True else Path(given).expanduser()
        return compiling.draft_of(path), path
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] != "rdflib":
            raise
        raise SystemExit("--shapes reads shapes with rdflib, which is not "
                         "installed: pip install \"docpipe[kg]\"; nothing "
                         "was written")
    except SystemExit as exc:
        raise SystemExit(f"{exc.code}; nothing was written") from None


def _init(rest: Sequence[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="docpipe init", description=OWN["init"].capitalize() + ".")
    parser.add_argument("name", nargs="?",
                        help="what the project is called: lower-case "
                             "letters, digits and _ (default: the folder's "
                             "name)")
    parser.add_argument("--dir", default=".", help="the project's folder "
                                                   "(default: this one)")
    parser.add_argument("--shapes", nargs="?", const=True, default=None,
                        metavar="FILE",
                        help="also write the draft of an extraction spec "
                             "into the new profile, from the SHACL shapes in "
                             "FILE or, without one, from the small metadata "
                             "shape docpipe brings (title, author, date, "
                             "...). A draft is no spec: nothing is harvested "
                             "until `docpipe compile` has finished it. Needs "
                             "docpipe[kg]. Give the project's name before "
                             "this option")
    args = parser.parse_args(list(rest))
    home = Path(args.dir).expanduser().resolve()
    name = args.name or re.sub(r"[^a-z0-9]+", "_",
                               home.name.lower()).strip("_")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name or ""):
        raise SystemExit(f"{name!r} cannot name a project: lower-case "
                         f"letters, digits and _, starting with a letter")
    if name in available_profiles():
        raise SystemExit(f"a profile named {name!r} exists already "
                         f"({profile_locations()[name]}); pick another name")
    project = home / settings.PROJECT_FILE
    profile = home / "profiles" / name
    for path in (project, profile):
        if path.exists():
            raise SystemExit(f"{path} exists already; nothing was written")
    # Read before anything is made: a file that cannot be used leaves no
    # half of a project behind.
    shaped = None if args.shapes is None else _draft_from_shapes(args.shapes)
    pdfs = home / "data" / name / "pdf"
    pdfs.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True)
    title = name.replace("_", " ").capitalize()
    (profile / "__init__.py").write_text("", encoding="utf-8")
    (profile / "profile.py").write_text(
        PROFILE_PY.format(name=name, title=title), encoding="utf-8")
    (profile / "extraction.py").write_text(EXTRACTION_PY, encoding="utf-8")
    project.write_text(PROJECT_TOML.format(name=name), encoding="utf-8")
    written = [project, profile / "profile.py", profile / "extraction.py"]
    if shaped is not None:
        draft, source = shaped
        (profile / DRAFT_FILE).write_text(
            json.dumps(draft, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        written.append(profile / DRAFT_FILE)
    example = home / ".env.example"
    if not example.exists():
        lines = ["# Keys and tokens. Copy to .env, which is not checked in."]
        lines += [f"# {s.help}\n# {s.env}=" for s in settings.SETTINGS
                  if s.secret]
        example.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(example)
    ignore = home / ".gitignore"
    if not ignore.exists():
        ignore.write_text(".env\ndata/\n", encoding="utf-8")
        written.append(ignore)
    for path in written:
        print(f"wrote {path}")
    print(f"\nPut the PDFs into {pdfs}, say in {settings.PROJECT_FILE} where "
          f"the models are,\nand run:\n\n"
          f"  docpipe doctor\n  docpipe run\n  docpipe chat\n\n"
          f"`docpipe run` is ingest, preprocess, refine, visuals, chunk and "
          f"lexical one after the other,\n`docpipe status` says what each "
          f"document has so far. PDFs lying in another folder: `docpipe "
          f"ingest --source FOLDER`,\nthen `docpipe run --skip ingest`. "
          f"`docpipe <command> --help` shows what each command takes.")
    if shaped is not None:
        from .compile import draft as drafting
        draft_path = profile / DRAFT_FILE
        spec_path = profile / "extraction_spec.json"
        print(f"\n{draft_path.name} is the draft of a spec from {source.name}: "
              f"{len(draft['parameters'])} parameter(s), "
              f"{len(drafting.todo(draft))} point(s) still open. It is not a "
              f"spec, so `docpipe extract` stops until {spec_path.name} "
              f"exists beside it. What the draft lacks:\n\n"
              f"  docpipe compile check {draft_path}\n\n"
              f"`docpipe compile examples` proposes the missing examples from "
              f"a corpus that `docpipe run` has processed, and\n"
              f"`docpipe compile apply {draft_path} --out {spec_path}` "
              f"writes the spec once nothing is open. A draft made with "
              f"`docpipe compile spec --ontology ...` carries the "
              f"ontology's labels and unit suggestions; this one has none.")
    return 0


def _config(rest: Sequence[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="docpipe config", description=OWN["config"])
    # The commands that have settings of their own. One that has none
    # (compile, evaluate, export) reads those of the stage it works for.
    parser.add_argument("--stage",
                        choices=sorted({stage for setting in settings.SETTINGS
                                        for stage in setting.stages}),
                        help="only the settings this command reads")
    parser.add_argument("--set", action="store_true",
                        help="only the settings that are not at their default")
    args = parser.parse_args(list(rest))
    print(f"project file: {settings.project_file() or 'none'}")
    print(f"profile:      {os.environ.get(ENV_VAR) or 'none'}")
    for setting, value, origin, shadowed in settings.rows(args.stage):
        if args.set and origin == "default":
            continue
        shown = "(unset)" if value is None else (
            "****" if setting.secret and value else value)
        line = f"{setting.key:<34} {shown}  [{origin}; {setting.env}]"
        if shadowed is not None:
            line += f"  ({settings.PROJECT_FILE} says {shadowed})"
        print(line)
    return 0


def _profiles(rest: Sequence[str]) -> int:
    if rest:
        print(f"usage: docpipe profiles\n\n{OWN['profiles']}")
        return 0 if set(rest) <= {"-h", "--help"} else 2
    found = profile_locations()
    if not found:
        print("no profile found")
        return 1
    active = os.environ.get(ENV_VAR)
    for name, folder in found.items():
        print(f"{'*' if name == active else ' '} {name:<14} {folder}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    options, command, rest = _split(sys.argv[1:] if argv is None else argv)
    if options.get("version"):
        print(f"docpipe {__version__}")
        return 0
    if command is None or (options.get("help") and command is None):
        print(_help())
        return 0 if options.get("help") else 2
    if command not in STAGES and command not in OWN:
        raise SystemExit(f"unknown command {command!r}\n\n{_help()}")
    # After the command as well: a stage takes --profile itself, and none
    # of them knows --config.
    after, rest = _pull(rest, ("--config",) if command in STAGES
                        else ("--profile", "--config"))
    options.update(after)
    _settle(options)
    if options.get("help"):
        rest = ["--help", *rest]
    if command in STAGES:
        return _run_stage(command, rest)
    if command == "init":
        return _init(rest)
    if command == "run":
        from . import run as running
        return running.main(rest)
    if command == "status":
        from . import status
        return status.main(rest)
    if command == "chat":
        return _chat(rest)
    if command == "config":
        return _config(rest)
    if command == "profiles":
        return _profiles(rest)
    if command == "column":
        from . import column
        return column.main(rest)
    from . import doctor
    return doctor.main(rest)


if __name__ == "__main__":
    sys.exit(main())
