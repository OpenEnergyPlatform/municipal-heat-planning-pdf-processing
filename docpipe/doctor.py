"""
doctor.py: Can this installation run? One line per thing looked at.

    docpipe doctor [--stage S] [--offline] [--json]

Nothing here needs a GPU, reads a document or asks a model a question: a
server is asked which models it serves, a database how many documents it
holds. What fails makes the command exit 1, with what to do about it on the
line, so a first start and a CI job can both stop on it.

A stage whose packages are not installed is a warning, not a failure: an
installation that only chats needs no layout model. Named with --stage, the
same finding is a failure.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

from . import dotenv, settings
from .store.schema import readonly_uri
from .profile import ENV_VAR, available_profiles, load_profile, \
    profile_locations

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

# What each command imports beyond the package's own requirements, and the
# extra that installs it.
NEEDS = {
    "ingest": ((), None),
    "preprocess": (("cv2", "torch", "transformers"), "layout"),
    "refine": ((), None),
    "visuals": ((), None),
    "chunk": (("torch", "transformers", "qwen_vl_utils"), "embed"),
    "extract": ((), None),
    "chat": (("streamlit",), "app"),
    "graph": (("rdflib", "pyshacl"), "kg"),
    "compile": (("rdflib",), "kg"),
}
CORE = ("yaml", "openai", "numpy", "PIL", "fitz", "requests", "tqdm",
        "jsonschema", "rapidfuzz", "faiss")


@dataclass
class Check:
    area: str
    name: str
    status: str
    detail: str
    hint: str = ""


def _missing(modules: Sequence[str]) -> list:
    return [name for name in modules if importlib.util.find_spec(name) is None]


def check_python() -> list:
    version = "%d.%d.%d" % sys.version_info[:3]
    if sys.version_info < (3, 9):
        return [Check("python", "version", FAIL, version,
                      "docpipe needs Python 3.9 or newer")]
    return [Check("python", "version", OK, version)]


def check_project() -> list:
    out = []
    path = settings.project_file()
    out.append(Check("project", "file", OK,
                     str(path) if path else
                     f"no {settings.PROJECT_FILE}: defaults and the "
                     f"environment"))
    for path in dotenv.FILES:
        out.append(Check("project", ".env", OK, str(path)))
    changed = [row for row in settings.rows() if row[2] != "default"]
    out.append(Check("project", "settings", OK,
                     f"{len(changed)} of {len(settings.SETTINGS)} set "
                     f"(`docpipe config --set` lists them)"))
    return out


def check_profile() -> tuple:
    """(checks, the profile or None)."""
    name = os.environ.get(ENV_VAR)
    found = profile_locations()
    if not name:
        return [Check("profile", "name", FAIL, "no profile named",
                      f"pass --profile, or set `profile` in "
                      f"{settings.PROJECT_FILE} (found: "
                      f"{', '.join(found) or 'none'})")], None
    try:
        profile = load_profile(name)
    except Exception as exc:        # whatever a profile's own code raises
        return [Check("profile", name, FAIL, f"{type(exc).__name__}: {exc}",
                      f"found: {', '.join(found) or 'none'}")], None
    try:
        line = profile.lineage()
    except Exception as exc:        # a profile it extends is not there
        return [Check("profile", name, FAIL,
                      f"{type(exc).__name__}: {exc}")], None
    extended = ", ".join(owner.name for owner in line[1:])
    out = [Check("profile", name, OK, str(profile.package_dir)
                 + (f" (extends {extended})" if extended else ""))]
    # A prompt counts once, for the nearest profile that has it.
    owners: dict = {}
    for owner in line:
        if owner.prompts_dir.is_dir():
            for path in sorted(owner.prompts_dir.rglob("*.md")):
                owners.setdefault(f"{path.parent.name}/{path.stem}",
                                  owner.name)
    own = sum(1 for owner in owners.values() if owner == name)
    out.append(Check("profile", "prompts", OK if owners else WARN,
                     f"{len(owners)} prompt file(s)"
                     + (f", {own} of its own" if extended else ""),
                     "" if owners else "the stages that ask a model need "
                     "the profile's prompts"))
    for label, module, attr in (("source", "source", "SOURCE"),
                                ("extraction spec", "extraction", "SPEC_PATH")):
        try:
            part = profile.component(module, attr)
        except ModuleNotFoundError as exc:
            # A package the profile's own code imports, and not a fault of
            # the profile: the packages section says what installs it.
            out.append(Check("profile", label, WARN,
                             f"needs the package {exc.name}"))
            continue
        except Exception as exc:
            out.append(Check("profile", label, FAIL,
                             f"{type(exc).__name__}: {exc}"))
            continue
        out.append(Check("profile", label, OK if part is not None else SKIP,
                         "provided" if part is not None else "not provided"))
    return out, profile


def check_packages(stage: Optional[str]) -> list:
    out = []
    missing = _missing(CORE)
    out.append(Check("packages", "core", FAIL if missing else OK,
                     f"missing: {', '.join(missing)}" if missing else
                     "installed", "pip install docpipe" if missing else ""))
    for command, (modules, extra) in NEEDS.items():
        if stage and command != stage:
            continue
        if command == "chunk" and os.environ.get(
                "EMBEDDING_INDEX_BACKEND", "local").strip() == "api":
            modules = ()            # the vectors come from an endpoint
        missing = _missing(modules)
        if not missing:
            out.append(Check("packages", command, OK, "installed"))
            continue
        out.append(Check(
            "packages", command, FAIL if stage else WARN,
            f"missing: {', '.join(missing)}",
            f'pip install "docpipe[{extra}]"'))
    return out


def _endpoint(label: str, base_url: str, api_key: str, model: str) -> Check:
    """One role's endpoint: whichever API it is set to, asked for its models."""
    from . import llm_preflight, providers
    try:
        name = providers.provider(label)
    except ValueError as exc:
        return Check("endpoint", label, FAIL, str(exc))
    hosted = name in providers.HOSTED
    where = f"the {name} API" if hosted else base_url
    try:
        served, window = llm_preflight.serving_limits(
            base_url, api_key, timeout=10.0, role=label)
    except ImportError as exc:
        return Check("endpoint", label, FAIL, str(exc).splitlines()[0],
                     f'pip install "docpipe[{name}]"')
    except llm_preflight.PreflightError as exc:
        return Check("endpoint", label, FAIL,
                     str(exc).splitlines()[0],
                     # by the name a .env is read under: the project
                     # file takes no secret
                     f"set {settings.BY_KEY[label + '.api_key'].env} in "
                     f".env" if hosted else
                     f"start the server, or set {label}.base_url")
    if model not in served:
        import difflib
        near = (difflib.get_close_matches(model, served, n=8, cutoff=0.3)
                if hosted else served[:8])
        return Check("endpoint", label, FAIL,
                     f"{where} does not serve {model!r}",
                     f"it serves: {', '.join(near)}; set {label}.model")
    return Check("endpoint", label, OK,
                 f"{where} serves {model}"
                 + (f", context {window}" if window else ""))


def check_endpoints(stage: Optional[str], offline: bool) -> list:
    if offline:
        return [Check("endpoint", "all", SKIP, "--offline")]
    if importlib.util.find_spec("openai") is None:
        return [Check("endpoint", "all", SKIP, "the openai package is missing")]
    env = os.environ.get
    out = []
    if stage in (None, "refine", "extract", "chat"):
        out.append(_endpoint(
            "llm", env("LLM_BASE_URL", "http://localhost:8000/v1"),
            env("LLM_API_KEY", "EMPTY"),
            env("LLM_MODEL", settings.BY_ENV["LLM_MODEL"].default or "")))
    if stage in (None, "visuals") and (env("VLM_BASE_URL") or stage
                                       or env("VLM_PROVIDER")):
        out.append(_endpoint(
            "vlm", env("VLM_BASE_URL",
                       settings.BY_ENV["VLM_BASE_URL"].default or ""),
            env("VLM_API_KEY", "EMPTY"),
            env("VLM_MODEL", settings.BY_ENV["VLM_MODEL"].default or "")))
    return out


def check_data(profile) -> list:
    if profile is None:
        return []
    out = []
    root = profile.root
    out.append(Check("data", "root", OK if root.is_dir() else WARN, str(root),
                     "" if root.is_dir() else "nothing ingested yet"))
    pdfs = len(list(profile.pdf_dir.glob("*.pdf"))) \
        if profile.pdf_dir.is_dir() else 0
    out.append(Check("data", "documents", OK if pdfs else WARN,
                     f"{pdfs} PDF file(s) in {profile.pdf_dir}"))
    if profile.db_path.is_file():
        try:
            with sqlite3.connect(readonly_uri(profile.db_path),
                                 uri=True) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM Documents").fetchone()[0]
            out.append(Check("data", "database", OK,
                             f"{count} document(s) in {profile.db_path}"))
        except sqlite3.Error as exc:
            out.append(Check("data", "database", FAIL,
                             f"{profile.db_path}: {exc}"))
    else:
        out.append(Check("data", "database", WARN,
                         f"{profile.db_path} does not exist",
                         "`docpipe chunk` writes it"))
    index = profile.index_path
    out.append(Check("data", "index", OK if index.is_file() else WARN,
                     f"{index} ({index.stat().st_size // 1_000_000} MB)"
                     if index.is_file() else f"{index} does not exist",
                     "" if index.is_file() else "`docpipe chunk` writes it"))
    return out


def run(stage: Optional[str] = None, offline: bool = False) -> list:
    checks = check_python() + check_project()
    found, profile = check_profile()
    checks += found
    checks += check_packages(stage)
    checks += check_endpoints(stage, offline)
    checks += check_data(profile)
    return checks


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="docpipe doctor",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("--stage", choices=sorted(NEEDS),
                        help="check for this command only, and count its "
                             "missing packages as a failure")
    parser.add_argument("--offline", action="store_true",
                        help="ask no server")
    parser.add_argument("--json", action="store_true",
                        help="print the checks as JSON")
    args = parser.parse_args(argv)
    checks = run(args.stage, args.offline)
    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=1))
    else:
        for check in checks:
            line = f"{check.area:<9} {check.status:<4} {check.name}: " \
                   f"{check.detail}"
            print(line + (f"\n{'':<14} -> {check.hint}" if check.hint else ""))
        failed = sum(check.status == FAIL for check in checks)
        warned = sum(check.status == WARN for check in checks)
        print(f"{len(checks)} check(s), {failed} failure(s), "
              f"{warned} warning(s)")
    return 1 if any(check.status == FAIL for check in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
