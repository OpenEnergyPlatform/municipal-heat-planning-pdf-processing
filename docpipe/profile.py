"""
profile.py – A profile is everything a project contributes to the generic
pipeline: where its documents come from, what extra tables it needs, which
prompts it overrides and which filters its app offers.

The core never imports a profile; it receives one.

Author: Felix Vossel
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
PROFILES_PACKAGE = "profiles"
ENV_VAR = "DOCPIPE_PROFILE"
COLUMN_LAYOUTS = ("auto", "single", "double")


@dataclass(frozen=True)
class Facet:
    """One filter the inference app offers over the profile's metadata."""
    field: str
    label: str
    widget: str = "multiselect"


@dataclass(frozen=True)
class Profile:
    name: str
    source_language: str = "de"     # language of the documents
    answer_language: str = "de"     # language the app answers in
    column_layout: str = "auto"     # auto | single | double
    data_root: Optional[Path] = None
    # where the profile's own files live; defaults to profiles/<name>
    home: Optional[Path] = None
    facets: Sequence[Facet] = field(default_factory=tuple)
    # what the app calls the project and one of its documents
    title: str = ""
    document_noun: str = "Dokument"

    def __post_init__(self) -> None:
        if not self.name or "/" in self.name or "\\" in self.name:
            raise ValueError(f"unusable profile name: {self.name!r}")
        if self.column_layout not in COLUMN_LAYOUTS:
            raise ValueError(f"column_layout must be one of {COLUMN_LAYOUTS}")

    @property
    def display_title(self) -> str:
        return self.title or self.name

    # -- the Python parts a profile may contribute -------------------------
    def component(self, module: str, attr: str):
        """`profiles/<name>/<module>.py: <attr>`, or None if not provided.

        A module the profile does not have is an absence; a module it has that
        fails to import is an error. Swallowing the second would silently
        degrade to the generic behaviour over a typo.
        """
        dotted = f"{PROFILES_PACKAGE}.{self.name}.{module}"
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
            raise LookupError(f"profile {self.name!r} provides no {module}.{attr} "
                              f"({PROFILES_PACKAGE}/{self.name}/{module}.py)")
        return value

    # -- where the profile's own files live -------------------------------
    @property
    def package_dir(self) -> Path:
        return Path(self.home) if self.home else ROOT / PROFILES_PACKAGE / self.name

    @property
    def prompts_dir(self) -> Path:
        return self.package_dir / "prompts"

    @property
    def schema_sql(self) -> Optional[Path]:
        path = self.package_dir / "schema.sql"
        return path if path.is_file() else None

    # -- where its data lives; every path is derived, so two profiles never
    #    share a file even when both run on the same machine ---------------
    @property
    def root(self) -> Path:
        if self.data_root is not None:
            return Path(self.data_root)
        env = os.environ.get("DOCPIPE_DATA_ROOT")
        return (Path(env) if env else ROOT / "data") / self.name

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


def load_profile(name: Optional[str] = None) -> Profile:
    """Import profiles.<name>.profile and return its PROFILE object."""
    name = name or os.environ.get(ENV_VAR) or ""
    if not name:
        raise LookupError(
            f"no profile given; pass --profile or set {ENV_VAR}")
    try:
        module = importlib.import_module(f"{PROFILES_PACKAGE}.{name}.profile")
    except ImportError as exc:
        available = ", ".join(sorted(p.name for p in (ROOT / PROFILES_PACKAGE).iterdir()
                                     if p.is_dir() and not p.name.startswith("_"))) or "keine"
        raise LookupError(f"unknown profile {name!r} (available: {available})") from exc

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


def add_profile_argument(parser) -> None:
    parser.add_argument("--profile", default=os.environ.get(ENV_VAR) or None,
                        help=f"project profile under {PROFILES_PACKAGE}/ "
                             f"(default: ${ENV_VAR})")


def resolve_profile(args=None, name: Optional[str] = None) -> Optional[Profile]:
    """The profile for this run, or None.

    A stage binds its prompts when it is imported, which happens before the
    command line is parsed. So a profile that overrides prompts has to be in the
    environment from the start; --profile alone would silently use the core
    prompts. That case is refused rather than run.
    """
    name = name or getattr(args, "profile", None) or os.environ.get(ENV_VAR)
    if not name:
        return None
    profile = load_profile(name)
    late = os.environ.get(ENV_VAR) != name
    if late and profile.prompts_dir.is_dir() and any(profile.prompts_dir.rglob("*.md")):
        raise SystemExit(
            f"profile {name!r} overrides prompts, but {ENV_VAR} was not set when "
            f"the stage was imported — the core prompts are already bound.\n"
            f"Run it as:  {ENV_VAR}={name} python -m <stage> …")
    os.environ[ENV_VAR] = name
    return profile
