"""
doctor.py: Can this installation run? One line per thing looked at.

    docpipe doctor [--stage S] [--offline] [--json]

Nothing here needs a GPU or reads a document: a server is asked which models
it serves and answers one request of one token, a database says how many
documents it holds and which embedding model built its index. What fails
makes the command exit 1, with what to do about it on the line, so a first
start and a CI job can both stop on it.

What the stages ask of the setup is looked at where the stages say it: the
context a stage needs is the budget the stage computes, the request fields
are probed by the preflight the stages run, the completeness of a stage's
prompts and wording is the loader's and the wording tables' own. Nothing here
counts any of it again.

A stage whose packages are not installed is a warning, not a failure: an
installation that only chats needs no layout model. Named with --stage, the
same finding is a failure. With --offline no server is asked, and each
group of lines that needs one says it was skipped.

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
from pathlib import Path
from typing import Optional, Sequence

from . import dotenv, settings
from .store.schema import readonly_uri
from .profile import ENV_VAR, PROFILES_PACKAGE, available_profiles, \
    load_profile, profile_locations

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


class Unconfigured(Exception):
    """A part the profile does not provide: its line is skipped, not failed."""


@dataclass
class Asked:
    """One role's server as its endpoint line found it. Kept for the lines
    that need the same answer: asking again is a second request, and it could
    answer something else."""
    role: str
    base_url: str
    api_key: str
    model: str
    check: Check
    window: Optional[int] = None
    served: bool = False        # it answered, and it serves the model


def _guarded(area: str, name: str, work, *args, hint: str = "") -> list:
    """The checks `work(*args)` returns. A doctor that raises says nothing
    about what it was looking at, so what a stage or a profile raises is a
    line: a part the profile does not provide is skipped, a package that is
    not installed is a warning (the packages section says what installs it),
    anything else is a failure in its own words."""
    try:
        return work(*args)
    except Unconfigured as exc:
        return [Check(area, name, SKIP, str(exc))]
    except ModuleNotFoundError as exc:
        # A module of docpipe's own or of a profile that is not there is a
        # broken installation, not a package to install.
        if (exc.name or "").partition(".")[0] not in (
                (__package__ or "docpipe").partition(".")[0],
                PROFILES_PACKAGE):
            return [Check(area, name, WARN,
                          f"needs the package {exc.name or exc}")]
        return [Check(area, name, FAIL, f"{type(exc).__name__}: {exc}", hint)]
    except Exception as exc:        # whatever a stage or a profile raises
        return [Check(area, name, FAIL, f"{type(exc).__name__}: {exc}",
                      hint)]


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


def check_profile(stage: Optional[str] = None) -> tuple:
    """(checks, the profile or None)."""
    name = os.environ.get(ENV_VAR)
    found = profile_locations()
    if not name and stage == "chat":
        # The chat answers on the built-in profile when none is named, so
        # that is the one its lines are checked against. Every other stage
        # stops without a profile, and so does this check.
        from .inference.wording import BUILT_IN
        return [Check("profile", "name", OK,
                      f"no profile named: the chat runs on the built-in "
                      f"profile {BUILT_IN}",
                      f"pass --profile, or set `profile` in "
                      f"{settings.PROJECT_FILE}, to name another (found: "
                      f"{', '.join(found) or 'none'})")], load_profile(BUILT_IN)
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


def _asked(label: str, base_url: str, api_key: str, model: str) -> Asked:
    """One role's endpoint: whichever API it is set to, asked for its models."""
    from . import llm_preflight, providers

    def found(check: Check, window: Optional[int] = None,
              served: bool = False) -> Asked:
        return Asked(label, base_url, api_key, model, check, window, served)

    try:
        name = providers.provider(label)
    except ValueError as exc:
        return found(Check("endpoint", label, FAIL, str(exc)))
    hosted = name in providers.HOSTED
    where = f"the {name} API" if hosted else base_url
    try:
        served, window = llm_preflight.serving_limits(
            base_url, api_key, timeout=10.0, role=label)
    except ImportError as exc:
        return found(Check("endpoint", label, FAIL, str(exc).splitlines()[0],
                           f'pip install "docpipe[{name}]"'))
    except llm_preflight.PreflightError as exc:
        return found(Check(
            "endpoint", label, FAIL, str(exc).splitlines()[0],
            # by the name a .env is read under: the project
            # file takes no secret
            f"set {settings.BY_KEY[label + '.api_key'].env} in "
            f".env" if hosted else
            f"start the server, or set {label}.base_url"))
    except Exception as exc:        # a client that cannot even be built
        return found(Check("endpoint", label, FAIL,
                           f"{type(exc).__name__}: {exc}",
                           f"check {label}.provider, {label}.base_url and "
                           f"{label}.api_key"))
    if model not in served:
        import difflib
        near = (difflib.get_close_matches(model, served, n=8, cutoff=0.3)
                if hosted else served[:8])
        return found(Check("endpoint", label, FAIL,
                           f"{where} does not serve {model!r}",
                           f"it serves: {', '.join(near)}; set {label}.model"),
                     window)
    return found(Check("endpoint", label, OK,
                       f"{where} serves {model}"
                       + (f", context {window}" if window else "")),
                 window, served=True)


def _endpoint(label: str, base_url: str, api_key: str, model: str) -> Check:
    """The endpoint line alone."""
    return _asked(label, base_url, api_key, model).check


def _skipped(offline: bool) -> str:
    """Why no server is asked at all, or ''."""
    if offline:
        return "--offline"
    if importlib.util.find_spec("openai") is None:
        return "the openai package is missing"
    return ""


def servers(stage: Optional[str], offline: bool) -> list:
    """The servers the stage's command talks to, each asked once."""
    if _skipped(offline):
        return []
    env = os.environ.get
    out = []
    if stage in (None, "refine", "extract", "chat"):
        out.append(_asked(
            "llm", env("LLM_BASE_URL", "http://localhost:8000/v1"),
            env("LLM_API_KEY", "EMPTY"),
            env("LLM_MODEL", settings.BY_ENV["LLM_MODEL"].default or "")))
    if stage in (None, "visuals") and (env("VLM_BASE_URL") or stage
                                       or env("VLM_PROVIDER")):
        out.append(_asked(
            "vlm", env("VLM_BASE_URL",
                       settings.BY_ENV["VLM_BASE_URL"].default or ""),
            env("VLM_API_KEY", "EMPTY"),
            env("VLM_MODEL", settings.BY_ENV["VLM_MODEL"].default or "")))
    return out


def check_endpoints(stage: Optional[str], offline: bool,
                    asked: Optional[list] = None) -> list:
    why = _skipped(offline)
    if why:
        return [Check("endpoint", "all", SKIP, why)]
    return [server.check for server in
            (servers(stage, offline) if asked is None else asked)]


# ---------------------------------------------------------------------------
# What each stage needs of the servers
# ---------------------------------------------------------------------------

def _harvest_budget(profile, prompt_id: str) -> int:
    from . import prompts
    from .extraction import runner
    path = profile.component("extraction", "SPEC_PATH")
    if path is None:
        raise Unconfigured("the profile configures no extraction stage")
    return runner.context_budget(prompts.load(prompt_id, profile),
                                 runner.load_spec(Path(path)))


def _extract_budget(profile) -> int:
    from .extraction import runner
    return _harvest_budget(profile, runner.HARVEST_PROMPT_ID)


def _review_budget(profile) -> int:
    from .extraction import runner
    return _harvest_budget(profile, runner.REVIEW_PROMPT_ID)


def _refine_budget(profile) -> int:
    from .refinement import config
    return config.max_request_tokens()


def _visuals_budget(profile) -> int:
    from .visuals import config
    return config.max_request_tokens()


# (line, the command it belongs to, the role whose server it asks, the
# budget). The stage computes the budget: it is the number its own preflight
# is called with, and the doctor counts nothing again.
BUDGETS = (
    ("refine", "refine", "llm", _refine_budget),
    ("extract", "extract", "llm", _extract_budget),
    ("extract --review", "extract", "llm", _review_budget),
    ("visuals", "visuals", "vlm", _visuals_budget),
)


def _fit(name: str, server: Asked, need: int) -> list:
    """One stage's budget against the window its server reports."""
    from . import llm_preflight, providers
    wants = f"needs {need} tokens per request"
    if not server.served:
        return [Check("context", name, SKIP,
                      f"{wants}; not compared, the {server.role} endpoint "
                      f"line above did not pass")]
    hosted = providers.hosted(server.role)
    if server.window is None:
        # A hosted API has no server of one's own to start.
        fix = (f"check that {server.model} takes at least {need} tokens, or "
               f"set {server.role}.model to a model that does" if hosted else
               f"start it with a context of at least {need} tokens")
        return [Check("context", name, WARN,
                      f"{wants}; the server does not report its context size",
                      f"{fix}, or lower the stage's window/max-tokens "
                      f"settings")]
    if server.window < need:
        fix = (f"set {server.role}.model to a model with a larger context"
               if hosted else
               f"raise the server's {llm_preflight.CONTEXT_FLAG} to at "
               f"least {need}")
        return [Check("context", name, FAIL,
                      f"{wants}, the server offers {server.window}",
                      f"{fix}, or lower the stage's window/max-tokens "
                      f"settings")]
    return [Check("context", name, OK,
                  f"{wants}, the server offers {server.window}")]


def _context_of(name: str, server: Asked, budget, profile) -> list:
    return _fit(name, server, budget(profile))


def check_context(stage: Optional[str], profile, asked: list,
                  skipped: str = "") -> list:
    """The context each stage needs against the context its server reports.
    Only the servers that were asked count: a role nobody asked about has no
    line here either."""
    if skipped:
        return [Check("context", "all", SKIP, skipped)]
    if profile is None:
        return [Check("context", "all", SKIP, "no profile, so no stage to "
                      "compute a budget for")]
    by_role = {server.role: server for server in asked}
    out = []
    for name, owner, role, budget in BUDGETS:
        if (stage and stage != owner) or role not in by_role:
            continue
        out += _guarded("context", name, _context_of, name, by_role[role],
                        budget, profile)
    return out


def _accepts(server: Asked) -> list:
    from . import llm_preflight, providers
    if not server.served:
        return [Check("request", server.role, SKIP,
                      "not asked, the endpoint line above did not pass")]
    try:
        unanswered = llm_preflight.assert_request_accepted(
            server.base_url, server.api_key, server.model,
            what="a stage", role=server.role)
    except llm_preflight.PreflightError as exc:
        lines = str(exc).splitlines()
        return [Check("request", server.role, FAIL, lines[0],
                      " ".join(line.strip() for line in lines[1:]))]
    if unanswered:
        return [Check("request", server.role, WARN,
                      f"no verdict: {unanswered}",
                      "ask again when the server is idle; a run sends these "
                      "fields all the same")]
    fields = ", ".join(llm_preflight.request_extras())
    return [Check("request", server.role, OK,
                  f"{server.model} accepts the request fields {fields}"
                  + (" and a reply schema"
                     if providers.hosted(server.role) else ""))]


# The commands whose requests carry `request_extras`. The chat's do not, so a
# server a chat-only setup talks to is not asked about fields it never gets.
SENDS_FIELDS = ("refine", "extract", "visuals")


def check_request(stage: Optional[str], asked: list,
                  skipped: str = "") -> list:
    """Whether each server takes the request fields the stages send. The one
    request of one token that `assert_serving` sends, sent on its own."""
    if stage and stage not in SENDS_FIELDS:
        return []
    if skipped:
        return [Check("request", "all", SKIP, skipped)]
    out = []
    for server in asked:
        out += _guarded("request", server.role, _accepts, server)
    return out


# ---------------------------------------------------------------------------
# What the profile has to hold for each stage
# ---------------------------------------------------------------------------

def _prompt_ids(stage: str) -> tuple:
    """The prompts a stage's own module says it loads."""
    if stage == "preprocess":
        from .preprocessing import page_text_fallback
        return (page_text_fallback.PAGE_TRANSCRIBE_PROMPT_ID,)
    if stage == "refine":
        from .refinement import config
        return tuple(config.PROMPT_IDS)
    if stage == "visuals":
        from .visuals import config
        return tuple(config.PROMPT_IDS)
    if stage == "extract":
        from .extraction import runner
        return (*runner.PROMPT_IDS, runner.REVIEW_PROMPT_ID)
    if stage == "chat":
        from .inference import llm_client
        return tuple(llm_client.PROMPT_IDS)
    if stage == "compile":
        from .compile import examples
        return (examples.EXAMPLE_PROMPT_ID,)
    raise ValueError(f"no prompts are known for the stage {stage!r}")


# The commands that load prompts of their own.
PROMPTED = ("preprocess", "refine", "visuals", "extract", "chat", "compile")


def _has_extraction(profile) -> None:
    if profile.component("extraction", "SPEC_PATH") is None:
        raise Unconfigured("the profile configures no extraction stage")


def _prompts_of(stage: str, profile) -> list:
    from . import prompts
    ids = _prompt_ids(stage)
    # The prompts of the extraction folder belong to a profile that has an
    # extraction stage, the way the stages ask for them.
    if any(prompt_id.startswith("extraction/") for prompt_id in ids):
        _has_extraction(profile)
    # Read the way the stage reads them: one that is there and cannot be
    # read (front matter that is no mapping) stops the stage as one that is
    # not there.
    missing, unreadable = [], []
    for prompt_id in ids:
        try:
            prompts.load(prompt_id, profile)
        except FileNotFoundError:
            missing.append(prompt_id)
        except Exception as exc:    # what the loader raises for a bad file
            unreadable.append(f"{prompt_id} ({type(exc).__name__}: {exc})")
    if missing or unreadable:
        said, hints = [], []
        if missing:
            said.append(f"{len(missing)} of {len(ids)} prompt(s) missing: "
                        f"{', '.join(missing)}")
            hints.append(f"write them under {profile.prompts_dir}, or "
                         f"extend a profile that has them")
        if unreadable:
            said.append(f"{len(unreadable)} of {len(ids)} prompt(s) cannot "
                        f"be read: {'; '.join(unreadable)}")
            hints.append("the front matter between the two --- lines of a "
                         "prompt is a mapping of settings")
        return [Check("prompts", stage, FAIL, "; ".join(said),
                      "; ".join(hints))]
    return [Check("prompts", stage, OK, f"{len(ids)} prompt(s) found")]


def _extraction_phrases(profile) -> list:
    from .extraction import wording
    _has_extraction(profile)
    return [Check("wording", "extraction.PHRASES", OK,
                  f"{len(wording.phrases(profile))} phrase(s), none missing")]


def _inference_phrases(profile) -> list:
    from .inference import wording
    return [Check("wording", "inference.PHRASES", OK,
                  f"{len(wording.phrases(profile))} phrase(s), none missing")]


def _inference_ui(profile) -> list:
    from .inference import wording
    return [Check("wording", "inference.UI", OK,
                  f"{len(wording.ui(profile))} label(s), none missing")]


def _graph_route(profile) -> list:
    from .inference import kg_route
    hooks = kg_route.hooks(profile)
    if hooks is None:
        raise Unconfigured("the profile has no graph route to answer from "
                           "(no kg.VALUE_QUERY)")
    return [Check("wording", "graph route", OK,
                  f"{len(hooks.notes)} reason(s) worded, and its coordinate "
                  f"prompt found")]


# (stage, line, check). The tables are the stages' own, and so is the check
# that one is complete: it raises and names what is missing.
WORDING = (
    ("extract", "extraction.PHRASES", _extraction_phrases),
    ("chat", "inference.PHRASES", _inference_phrases),
    ("chat", "inference.UI", _inference_ui),
    ("chat", "graph route", _graph_route),
)


def check_stages(stage: Optional[str], profile) -> list:
    """Whether the profile in effect holds each stage's prompts and wording.
    What a stage asks of a profile is read from the stage."""
    if profile is None:
        return [Check("prompts", "all", SKIP, "no profile"),
                Check("wording", "all", SKIP, "no profile")]
    out = []
    for name in PROMPTED:
        if stage and stage != name:
            continue
        out += _guarded("prompts", name, _prompts_of, name, profile)
    for owner, name, work in WORDING:
        if stage and stage != owner:
            continue
        out += _guarded("wording", name, work, profile,
                        hint="complete the table in the profile, or in a "
                             "profile it extends")
    return out


# ---------------------------------------------------------------------------
# The embedding model of the index against the one queries use
# ---------------------------------------------------------------------------

def _recorded(profile) -> list:
    from .embedding import config
    from .store import schema
    path = profile.db_path
    try:
        with sqlite3.connect(readonly_uri(path), uri=True) as conn:
            said = schema.meta(conn)
            model = schema.embedding_mismatch(conn, config.EMBEDDING_MODEL)
            dim = schema.dimension_mismatch(conn, config.EMBEDDING_DIM)
    except sqlite3.Error as exc:
        return [Check("embedding", name, FAIL, f"{path}: {exc}")
                for name in ("model", "dimension")]
    built_model, built_dim = (said.get("embedding/model"),
                              said.get("embedding/dim"))
    out = []
    if not built_model:
        out.append(Check("embedding", "model", WARN,
                         "the database records no embedding model",
                         "`docpipe chunk --step embed` records it"))
    elif model:
        out.append(Check("embedding", "model", FAIL, model,
                         f"set embedding.model to {built_model}, or embed "
                         f"the corpus again with {config.EMBEDDING_MODEL}"))
    else:
        out.append(Check("embedding", "model", OK,
                         f"{built_model}, as queries are embedded"))
    if built_dim is None:
        out.append(Check("embedding", "dimension", WARN,
                         "the database records no embedding dimension",
                         "`docpipe chunk --step embed` records it"))
    elif dim:
        out.append(Check("embedding", "dimension", FAIL, dim,
                         f"set embedding.dim to {built_dim}"))
    else:
        out.append(Check("embedding", "dimension", OK,
                         f"{built_dim} dimensions, as queries are "
                         f"embedded"))
    return out


def check_embedding(stage: Optional[str], profile) -> list:
    """The embedding model and dimension the database records for its index,
    against the ones configured for queries. Offline: it reads the file."""
    if stage not in (None, "chunk", "extract", "chat"):
        return []
    if profile is None:
        return [Check("embedding", name, SKIP, "no profile")
                for name in ("model", "dimension")]
    if not profile.db_path.is_file():
        return [Check("embedding", name, SKIP,
                      f"{profile.db_path} does not exist")
                for name in ("model", "dimension")]
    return _guarded("embedding", "index", _recorded, profile)


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
    found, profile = check_profile(stage)
    checks += found
    checks += check_packages(stage)
    # Each server is asked once; the lines that need its answer share it.
    skipped = _skipped(offline)
    asked = servers(stage, offline)
    checks += check_endpoints(stage, offline, asked)
    checks += check_context(stage, profile, asked, skipped)
    checks += check_request(stage, asked, skipped)
    checks += check_stages(stage, profile)
    checks += check_data(profile)
    checks += check_embedding(stage, profile)
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
