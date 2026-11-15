"""
newprofile.py: A new profile, as `docpipe init` and the editor make it
(owner request 2026-11-14, wish 5: "Es wäre cool, wenn es auch die Option
gäbe über den Editor ein Profil anzulegen").

A new profile lies in the profile folder of the project (`profiles/<name>`)
beside a folder for its PDFs (`data/<name>/pdf`). It starts empty, extending
the profile docpipe brings itself, or as a copy of a profile the installation
finds: then it extends that one and has a copy of each of its files a page
edits (the spec, the flow, the graph, the chat, the rules, the sources), so
editing them leaves the other profile as it was. Where it is given the
addresses of an ontology, shapes or a graph, they are its sources; a draft of
its spec is made from shapes with the same code `docpipe init --shapes` uses.
Everything is read before anything is written: a name taken, a file that
cannot be used or a source that cannot be fetched leaves nothing behind.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Optional

from . import settings
from .profile import available_profiles, load_profile, profile_locations

# The files of a profile its copy gets its own of, where the profile has one.
COPIED = ("extraction_spec.json", "extraction_schema.json", "flow.json",
          "graph.json", "chat.json", "rules.json", "sources.json")
# What a source given by its address is called in the new profile's
# sources.json, in the order a page asks them.
ADDRESSED = ("ontology", "shapes", "graph")
NAME = re.compile(r"[a-z][a-z0-9_]*")
DRAFT_FILE = "extraction_spec.draft.json"

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

# A copy of another profile: it extends that one, so every part it does not
# have itself is that profile's, and says what that one says of itself.
COPY_PY = """\
\"\"\"{title}: a copy of the profile {source}.

It extends {source}: every part it does not have itself is that profile's.
Its own spec, flow, graph, chat, rules and sources are copies of those of
{source}, so editing them leaves {source} as it was.
\"\"\"
from docpipe.profile import Facet, Profile

PROFILE = Profile(
    name="{name}",
    extends="{source}",
    title="{title}",
    document_noun="{noun}",
    column_layout="{layout}",
    documents_shareable={shareable},
    facets=({facets}),
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


class ProfileError(ValueError):
    """A profile that cannot be made. It says why; nothing was written."""


def check_name(name: str) -> None:
    """Refuses a name that cannot name a profile or names one there is."""
    if not NAME.fullmatch(name or ""):
        raise ProfileError(f"{name!r} cannot name a project: lower-case "
                           f"letters, digits and _, starting with a letter")
    if name in available_profiles():
        raise ProfileError(f"a profile named {name!r} exists already "
                           f"({profile_locations()[name]}); pick another "
                           f"name")


def draft_from_shapes(given):
    """(the draft of a spec, the shapes file it is from). *given* is a file
    of the user's, or True for the one the package brings."""
    if given == "":
        # An unset variable in `--shapes "$FILE"`: not the bundled shape.
        raise ProfileError("--shapes was given an empty file name")
    try:
        from .compile import cli as compiling
        from .compile import shapes
        path = shapes.BUNDLED if given is True else Path(given).expanduser()
        return compiling.draft_of(path), path
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] != "rdflib":
            raise
        raise ProfileError("--shapes reads shapes with rdflib, which is not "
                           "installed: pip install \"docpipe[kg]\"") from None
    except SystemExit as exc:
        raise ProfileError(str(exc.code)) from None


def addressed_sources(addresses: Optional[dict]) -> dict:
    """{name: source} of the addresses given (`ADDRESSED`), each the file at
    its address (the kind `url` of `sources.KEYS`)."""
    out = {}
    for name in ADDRESSED:
        url = (addresses or {}).get(name)
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        if not re.match(r"https?://", url):
            raise ProfileError(f"the address of the {name} is no http(s) "
                               f"address: {url!r}")
        file = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        out[name] = {"kind": "url", "url": url, "file": file or name}
    return out


def _copy_py(name: str, source) -> str:
    """profile.py of a copy of *source*: its words, extending it."""
    facets = "".join(
        f"\n        Facet({f.field!r}, {f.label!r}"
        + (f", {f.widget!r}" if f.widget != "multiselect" else "") + "),"
        for f in source.facets)
    return COPY_PY.format(
        name=name, source=source.name,
        title=f"{source.display_title} ({name})",
        noun=source.document_noun, layout=source.column_layout,
        shareable=bool(source.documents_shareable),
        facets=facets + ("\n    " if facets else ""))


def write_profile(home: Path, name: str, *, copy_of: Optional[str] = None,
                  draft: Optional[dict] = None,
                  sources: Optional[dict] = None) -> list:
    """Makes profile *name* in the project at *home* and the folder of its
    PDFs; returns the files written. *copy_of*: the profile it is a copy
    of, else it extends the one docpipe brings; *draft*: the draft of its
    spec; *sources*: sources laid over those it has."""
    check_name(name)
    home = Path(home)
    folder = home / "profiles" / name
    if folder.exists():
        raise ProfileError(f"{folder} exists already; nothing was written")
    source = load_profile(copy_of) if copy_of else None
    own = Path(source.package_dir) if source is not None else None
    copied = [own / one for one in COPIED
              if own is not None and (own / one).is_file()]
    held = json.loads((own / "sources.json").read_text(encoding="utf-8")) \
        if own is not None and (own / "sources.json").is_file() else {}
    (home / "data" / name / "pdf").mkdir(parents=True, exist_ok=True)
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("", encoding="utf-8")
    title = name.replace("_", " ").capitalize()
    (folder / "profile.py").write_text(
        _copy_py(name, source) if source is not None
        else PROFILE_PY.format(name=name, title=title), encoding="utf-8")
    (folder / "extraction.py").write_text(EXTRACTION_PY, encoding="utf-8")
    written = [folder / "profile.py", folder / "extraction.py"]
    for path in copied:
        shutil.copyfile(path, folder / path.name)
        written.append(folder / path.name)
    if draft is not None:
        (folder / DRAFT_FILE).write_text(
            json.dumps(draft, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        written.append(folder / DRAFT_FILE)
    if sources:
        held = dict(held)
        held["sources"] = {**(held.get("sources") or {}), **sources}
        (folder / "sources.json").write_text(
            json.dumps(held, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        if folder / "sources.json" not in written:
            written.append(folder / "sources.json")
    return written


def write_project(home: Path, name: str) -> list:
    """The project's file, and an example of its .env and a .gitignore
    where there are none yet; returns the files written."""
    home = Path(home)
    project = home / settings.PROJECT_FILE
    project.write_text(PROJECT_TOML.format(name=name), encoding="utf-8")
    written = [project]
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
    return written


def missing(draft: Optional[dict]) -> list:
    """What still stands between a draft and a spec, one line each (a real
    example per field before the strict check takes it, and whatever else
    `compile.draft.todo` names); [] without a draft."""
    if draft is None:
        return []
    from .compile import draft as drafting
    return list(drafting.todo(draft))
