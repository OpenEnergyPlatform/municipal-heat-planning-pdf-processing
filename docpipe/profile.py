"""
profile.py: A profile is everything a project contributes to the generic
pipeline: where its documents come from, what extra tables it needs, which
prompts it overrides and which filters its app offers.

The core never imports a profile; it receives one.

A profile is a directory. It is found by its name on a search path, first
match first: the directories $DOCPIPE_PROFILE_PATH names, `profiles/` of the
project, what installed packages register under the entry-point group
`docpipe.profiles`, `profiles/` beside this package, and last the profile
this package brings itself (`builtin/default`). So a project keeps its
profile in its own repository, and `--profile` also takes the directory
itself.

A profile may extend another one (`extends="default"`). What it does not
provide itself, a module's attribute, a prompt, the schema of its tables,
is then taken from the profile it extends. Nothing is taken from a profile
that was not named: a profile without `extends` stands alone, and a part it
lacks is an absence, as before.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import functools
import importlib
import logging
import os
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from . import settings

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
# The profiles this package brings itself.
BUILTIN = Path(__file__).resolve().parent / "builtin"
PROFILES_PACKAGE = "profiles"
ENV_VAR = "DOCPIPE_PROFILE"
PATH_ENV = "DOCPIPE_PROFILE_PATH"
ENTRY_POINTS = "docpipe.profiles"
MARKER = "profile.py"           # the file that makes a directory a profile
COLUMN_LAYOUTS = ("auto", "single", "double")


@functools.lru_cache(maxsize=None)
def _registered() -> tuple:
    """The directories installed packages register profiles in. Read once:
    which packages are installed does not change under a running process,
    and asking every one of them costs more than a profile lookup may."""
    return tuple(_scan_registered())


def _scan_registered() -> list:
    try:
        from importlib import metadata
        found = metadata.entry_points()
        group = (found.select(group=ENTRY_POINTS) if hasattr(found, "select")
                 else found.get(ENTRY_POINTS, ()))
    except Exception:           # a broken installation elsewhere is not ours
        return []
    out = []
    for entry in group:
        try:
            spec = importlib.util.find_spec(entry.value.split(":")[0])
        except (ImportError, ValueError, AttributeError):
            # registered by a package that is gone: what it left behind
            log.warning("profiles registered as %s = %s cannot be found; "
                        "skipped", entry.name, entry.value)
            continue
        for folder in (spec.submodule_search_locations or ()) if spec else ():
            out.append(Path(folder).parent)
    return out


# What the search path was last bound for; see `_bind_search_path`.
_BOUND: Optional[tuple] = None


def search_path() -> list:
    """The directories whose subdirectories are profiles, in order."""
    named = [Path(text).expanduser()
             for text in (os.environ.get(PATH_ENV) or "").split(os.pathsep)
             if text.strip()]
    candidates = [*named, settings.project_dir() / PROFILES_PACKAGE,
                  *_registered(), ROOT / PROFILES_PACKAGE, BUILTIN]
    out: list = []
    for folder in candidates:
        try:
            folder = folder.resolve()
        except OSError:
            continue
        if folder.is_dir() and folder not in out:
            out.append(folder)
    return out


def profile_locations() -> dict:
    """{name: directory} of every profile the search path holds."""
    out: dict = {}
    for folder in search_path():
        for child in sorted(folder.iterdir()):
            if (child / MARKER).is_file() and child.name not in out:
                out[child.name] = child
    return out


def _bind_search_path() -> None:
    """Make `profiles.<name>` importable for every profile on the path.

    A profile's modules import each other as `profiles.<name>.<module>`, and
    a profile kept outside this repository has to be able to do the same. So
    the package `profiles` is given the whole search path to look in, and is
    made up where no such package can be imported at all.
    """
    global _BOUND
    here = settings.project_dir()
    key = (os.environ.get(PATH_ENV), str(here),
           (here / PROFILES_PACKAGE).is_dir())
    package = sys.modules.get(PROFILES_PACKAGE)
    if package is not None and key == _BOUND:
        return                  # nothing the path is made of has moved
    if package is None:
        try:
            package = importlib.import_module(PROFILES_PACKAGE)
        except ModuleNotFoundError:
            package = types.ModuleType(PROFILES_PACKAGE)
            package.__path__ = []
            sys.modules[PROFILES_PACKAGE] = package
    wanted = [str(folder) for folder in search_path()]
    own = [entry for entry in list(getattr(package, "__path__", ()))
           if entry not in wanted]
    if list(getattr(package, "__path__", ())) != wanted + own:
        package.__path__ = wanted + own
        importlib.invalidate_caches()
    _BOUND = key


def name_profile(text: str) -> str:
    """The name for what --profile was given: a name, or a profile's
    directory, whose parent then leads the search path."""
    folder = Path(text).expanduser()
    if not (folder / MARKER).is_file():
        if os.sep in text or "/" in text:
            raise SystemExit(f"{text} is no profile: it holds no {MARKER}")
        return text
    folder = folder.resolve()
    known = [entry for entry in
             (os.environ.get(PATH_ENV) or "").split(os.pathsep) if entry]
    if str(folder.parent) not in known:
        os.environ[PATH_ENV] = os.pathsep.join([str(folder.parent), *known])
    return folder.name


@dataclass(frozen=True)
class Facet:
    """One filter the inference app offers over the profile's metadata."""
    field: str
    label: str
    widget: str = "multiselect"


@dataclass(frozen=True)
class Profile:
    name: str
    column_layout: str = "auto"     # auto | single | double
    data_root: Optional[Path] = None
    # where the profile's own files live; defaults to where it was found
    home: Optional[Path] = None
    facets: Sequence[Facet] = field(default_factory=tuple)
    # what the app calls the project and one of its documents; a profile
    # words it in its own language
    title: str = ""
    document_noun: str = "document"
    # the profile whose parts stand in for the ones this one does not provide
    extends: Optional[str] = None
    # Whether the text of the documents may be passed on. A recorded run
    # (docpipe/providers/cassette.py) holds what it read, and is refused
    # for a profile that does not say so.
    documents_shareable: bool = False

    def __post_init__(self) -> None:
        if not self.name or "/" in self.name or "\\" in self.name:
            raise ValueError(f"unusable profile name: {self.name!r}")
        if self.column_layout not in COLUMN_LAYOUTS:
            raise ValueError(f"column_layout must be one of {COLUMN_LAYOUTS}")
        if self.extends == self.name:
            raise ValueError(f"profile {self.name!r} extends itself")

    @property
    def display_title(self) -> str:
        return self.title or self.name

    def lineage(self) -> list:
        """This profile and the ones it extends, nearest first."""
        out = [self]
        while out[-1].extends:
            wanted = out[-1].extends
            if wanted in [profile.name for profile in out]:
                raise ValueError(
                    f"profile {self.name!r} extends itself by way of "
                    f"{' -> '.join(p.name for p in out)} -> {wanted}")
            try:
                out.append(load_profile(wanted))
            except LookupError as exc:
                raise LookupError(
                    f"profile {out[-1].name!r} extends {wanted!r}: {exc}") \
                    from exc
        return out

    # -- the Python parts a profile may contribute -------------------------
    def component(self, module: str, attr: str):
        """`profiles/<name>/<module>.py: <attr>`, or None if not provided.

        Its own, else that of the nearest profile it extends.
        """
        for profile in self.lineage():
            value = profile._own(module, attr)
            if value is not None:
                return value
        return None

    def own(self, module: str, attr: str):
        """What this profile declares itself in `<module>.py: <attr>`, or None:
        not what it takes from the profile it extends. For a fact that is
        about the files a profile owns, such as the language they are in."""
        return self._own(module, attr)

    def layers(self, module: str, attr: str) -> list:
        """Every value along the line of profiles, nearest first: for a
        table a profile lays over the one it extends, entry by entry."""
        found = (profile._own(module, attr) for profile in self.lineage())
        return [value for value in found if value is not None]

    def _own(self, module: str, attr: str):
        """This profile's own `<module>.py: <attr>`, or None.

        A module the profile does not have is an absence; a module it has that
        fails to import is an error. Swallowing the second would silently
        degrade to the generic behaviour over a typo.
        """
        dotted = f"{PROFILES_PACKAGE}.{self.name}.{module}"
        _bind_search_path()
        try:
            loaded = importlib.import_module(dotted)
        except ModuleNotFoundError as exc:
            # Missing module or missing package above it → absence. Anything
            # else the module failed to import is the profile's own bug.
            missing = exc.name or ""
            if dotted == missing or dotted.startswith(f"{missing}."):
                return None
            raise
        return getattr(loaded, attr, None)

    def require(self, module: str, attr: str):
        """`component`, for the parts the pipeline cannot run without."""
        value = self.component(module, attr)
        if value is None:
            line = [profile.name for profile in self.lineage()]
            where = (f"({PROFILES_PACKAGE}/{self.name}/{module}.py)"
                     if len(line) == 1
                     else f"(nor does {', '.join(line[1:])}, which it extends)")
            raise LookupError(f"profile {self.name!r} provides no "
                              f"{module}.{attr} {where}")
        return value

    # -- where the profile's own files live -------------------------------
    @property
    def package_dir(self) -> Path:
        if self.home:
            return Path(self.home)
        return (profile_locations().get(self.name)
                or ROOT / PROFILES_PACKAGE / self.name)

    @property
    def prompts_dir(self) -> Path:
        return self.package_dir / "prompts"

    @property
    def schema_sql(self) -> Optional[Path]:
        """The schema of the profile's own tables: its file, else the file
        of the nearest profile it extends. A profile that adds a column
        writes the whole file."""
        for profile in self.lineage():
            path = profile.package_dir / "schema.sql"
            if path.is_file():
                return path
        return None

    def has_prompts(self) -> bool:
        """Whether a stage binds prompts under this profile at import."""
        return any(profile.prompts_dir.is_dir()
                   and any(profile.prompts_dir.rglob("*.md"))
                   for profile in self.lineage())

    # -- where its data lives; every path is derived, so two profiles never
    #    share a file even when both run on the same machine ---------------
    @property
    def root(self) -> Path:
        if self.data_root is not None:
            return Path(self.data_root)
        return data_dir() / self.name

    @property
    def pdf_dir(self) -> Path:
        return self.root / "pdf"

    @property
    def processed_dir(self) -> Path:
        return self.root / "pdf" / "processed"

    @property
    def db_path(self) -> Path:
        return self.root / f"{self.name}.db"

    @property
    def index_path(self) -> Path:
        return self.root / "faiss_index.bin"


def data_dir() -> Path:
    """Where data lives when no profile says otherwise.

    $DOCPIPE_DATA_ROOT; else `data/` beside the project file; else, for a
    checkout run without one, `data/` in the checkout; else `data/` in the
    working directory.
    """
    env = os.environ.get("DOCPIPE_DATA_ROOT")
    if env:
        return Path(env)
    if settings.project_file() is not None:
        return settings.project_dir() / "data"
    if (ROOT / PROFILES_PACKAGE).is_dir():
        return ROOT / "data"
    return Path.cwd() / "data"


def shared_file(name: str, without_project: Path) -> Path:
    """A file no profile owns: in the project's `data/`, else where it was.

    A project that has a `docpipe.toml` keeps everything beside it. Without
    one the caller's own place stands, so a run that never had a project file
    finds its files where it left them.
    """
    if settings.project_file() is not None:
        return settings.project_dir() / "data" / name
    return Path(without_project)


def load_profile(name: Optional[str] = None) -> Profile:
    """Import profiles.<name>.profile and return its PROFILE object."""
    name = name or os.environ.get(ENV_VAR) or ""
    if not name:
        raise LookupError(
            f"no profile given; pass --profile or set {ENV_VAR}")
    _bind_search_path()
    try:
        module = importlib.import_module(f"{PROFILES_PACKAGE}.{name}.profile")
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        dotted = f"{PROFILES_PACKAGE}.{name}.profile"
        if not (dotted == missing or dotted.startswith(f"{missing}.")):
            raise           # the profile is there and one of its imports is not
        raise LookupError(
            f"unknown profile {name!r} (available: "
            f"{', '.join(available_profiles()) or 'none'})") from exc

    profile = getattr(module, "PROFILE", None)
    if not isinstance(profile, Profile):
        raise TypeError(f"profiles.{name}.profile must export PROFILE: Profile")
    if profile.name != name:
        raise ValueError(f"profile {name!r} calls itself {profile.name!r}")
    return profile


def active_profile() -> Optional[Profile]:
    """The ambient profile, or None. Used where no profile is passed in."""
    if not os.environ.get(ENV_VAR):
        return None
    return load_profile()


_values: dict = {}


def profile_value(module: str, attr: str):
    """The ambient profile's *attr*, resolved once per profile.

    For the facts about a corpus the core must not invent: which words open a
    caption, how long a caption gets, how many sections fit one request. A
    core constant looks harmless until a second corpus arrives and the value
    is quietly wrong for it — with no error, only worse output.
    """
    profile = active_profile()
    if profile is None:
        raise LookupError(f"{module}.{attr} needs a profile; set ${ENV_VAR}")
    key = (profile.name, module, attr)
    if key not in _values:
        _values[key] = profile.require(module, attr)
    return _values[key]


def program(module: str) -> str:
    """What a stage's usage line calls it: the command it was started as."""
    started = sys.argv[0] if sys.argv else ""
    return started if started.startswith("docpipe ") else f"python -m {module}"


def add_profile_argument(parser) -> None:
    parser.add_argument("--profile", default=os.environ.get(ENV_VAR) or None,
                        help=f"project profile: a name, or the directory of "
                             f"one (default: ${ENV_VAR})")


def bind_command_line(argv: Optional[Sequence[str]] = None) -> None:
    """Put a --profile given on the command line into the environment.

    For a stage's `__main__`, before it imports the stage. What a stage binds
    when it is imported (how many sections fit one request, the chat's
    prompts) is read from the environment, and the command line is parsed
    only after the import. Read the way the stage's own parser reads it, so
    an abbreviation it accepts (--prof) is one this accepts too.
    """
    parser = _Quiet(add_help=False)
    parser.add_argument("--profile")
    try:
        known, _rest = parser.parse_known_args(
            list(sys.argv[1:] if argv is None else argv))
    except ValueError:
        return      # the stage's own parser says what is wrong with the line
    if known.profile:
        os.environ[ENV_VAR] = name_profile(known.profile)


class _Quiet(argparse.ArgumentParser):
    """A parser that raises where argparse prints a usage and exits."""

    def error(self, message):
        raise ValueError(message)


def available_profiles() -> list:
    return sorted(profile_locations())


def resolve_profile(args=None, name: Optional[str] = None) -> Optional[Profile]:
    """The profile for this run, or None.

    A stage binds some of what a profile says when it is imported, which
    happens before the command line is parsed. `bind_command_line` puts the
    flag into the environment before that. A caller that imported the stage
    under one profile and names another here would run on a mix of both;
    that case is refused rather than run.
    """
    name = name or getattr(args, "profile", None) or os.environ.get(ENV_VAR)
    if not name:
        return None
    name = name_profile(name)
    profile = load_profile(name)
    late = os.environ.get(ENV_VAR) != name
    if late and profile.has_prompts():
        raise SystemExit(
            f"profile {name!r} was named after the stage was imported under "
            f"{os.environ.get(ENV_VAR) or 'none'!r} — what a stage binds on "
            f"import is already bound.\n"
            f"Run it as:  python -m <stage> --profile {name} …  "
            f"or set {ENV_VAR}={name}")
    os.environ[ENV_VAR] = name
    return profile


def require_profile(args=None, name: Optional[str] = None) -> Profile:
    """`resolve_profile` for a stage that has nothing to run without one."""
    profile = resolve_profile(args, name)
    if profile is None:
        raise SystemExit(
            f"no profile: pass --profile <name> or set {ENV_VAR} "
            f"(available: {', '.join(available_profiles()) or 'none'})")
    return profile
