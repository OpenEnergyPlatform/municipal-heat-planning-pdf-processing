"""Every library the package imports is one pyproject.toml declares, and what
`docpipe edit` loads when it starts is in the package's own list or in its
extra `editor`.

1. Each name a module of docpipe/ or profiles/ imports from outside the
   standard library and the repository is a requirement of the package or of
   one of its extras, by the distribution it is installed as
   (`DISTRIBUTION`).
2. `docpipe doctor` and `docpipe edit` read the same lists: doctor's CORE is
   the package's own requirements, and each library NEEDS names for a
   command is in the extra it names (or the package's own).
3. Importing every module of docpipe.editor imports nothing but the
   package's own requirements and the extra `editor`, in a process of its
   own in which every other library is refused.

Each promise has a case that breaks it by construction: a module importing
a library no list names, a doctor list with one name too many, the start of
the editor with `regex` refused.
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from docpipe import doctor
from docpipe.editor import start

ROOT = Path(__file__).resolve().parent.parent
LOCAL = {"docpipe", "profiles", "__future__"}
# An import name installed under another name; any other is its own.
DISTRIBUTION = {"yaml": "pyyaml", "PIL": "pillow", "fitz": "pymupdf",
                "cv2": "opencv-python-headless", "faiss": "faiss-cpu",
                "llm_sandbox": "llm-sandbox", "qwen_vl_utils": "qwen-vl-utils"}

needs_stdlib_list = pytest.mark.skipif(
    not hasattr(sys, "stdlib_module_names"),
    reason="the standard library's list of modules is Python 3.10's")


def normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def distribution(module: str) -> str:
    return normal(DISTRIBUTION.get(module, module))


def requirement(text: str) -> tuple:
    """(distribution, whether a marker limits it) of one requirement."""
    name = re.match(r"\s*([A-Za-z0-9_.-]+)", text).group(1)
    return normal(name), ";" in text


def declared() -> tuple:
    """({distribution: whether a marker limits it} of the package's own
    requirements, {extra: {distribution}})."""
    try:
        import tomllib
    except ImportError:                 # Python before 3.11
        import tomli as tomllib
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]
    core = dict(requirement(one) for one in project["dependencies"])
    extras = {name: {requirement(one)[0] for one in listed}
              for name, listed in project["optional-dependencies"].items()}
    return core, extras


def imports_of(text: str) -> set:
    """The top-level names *text* imports absolutely."""
    out = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            out.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 \
                and node.module:
            out.add(node.module.partition(".")[0])
    return out


def sources() -> dict:
    """{path: text} of every module of docpipe/ and profiles/."""
    out = {}
    for folder in ("docpipe", "profiles"):
        for path in (ROOT / folder).rglob("*.py"):
            if "node_modules" in path.parts:
                continue
            out[path.relative_to(ROOT).as_posix()] = path.read_text(
                encoding="utf-8")
    return out


def outside(texts: dict) -> dict:
    """{import name: [paths]} of the names *texts* import from outside the
    standard library and the repository."""
    std = set(sys.stdlib_module_names)
    found: dict = {}
    for path, text in texts.items():
        for name in imports_of(text):
            if name not in std and name not in LOCAL:
                found.setdefault(name, []).append(path)
    return found


def undeclared(found: dict, core: dict, extras: dict) -> dict:
    """{import name: [paths]} of the names no list of pyproject.toml has."""
    every = set(core).union(*extras.values())
    return {name: paths for name, paths in found.items()
            if distribution(name) not in every}


def doctor_disagreements(core_names, needs: dict, core: dict,
                         extras: dict) -> list:
    """Where doctor's lists say otherwise than pyproject.toml."""
    out = []
    ours = {distribution(name) for name in core_names}
    theirs = {name for name, marked in core.items() if not marked}
    out += [f"CORE has {name}, which is no requirement"
            for name in sorted(ours - theirs)]
    out += [f"CORE lacks {name}" for name in sorted(theirs - ours)]
    for command, (modules, extra) in needs.items():
        if extra is None:
            continue
        if extra not in extras:
            out.append(f"{command}: no extra {extra!r}")
            continue
        for module in modules:
            if distribution(module) not in extras[extra] | set(core):
                out.append(f"{command}: {module} is not in [{extra}]")
    return out


@needs_stdlib_list
def test_every_library_the_package_imports_is_declared():
    core, extras = declared()
    assert undeclared(outside(sources()), core, extras) == {}


@needs_stdlib_list
def test_a_library_no_list_names_is_found():
    core, extras = declared()
    found = outside({"docpipe/x.py": "import os\nimport notalibrary\n"
                                     "from docpipe import rules\n"})
    assert undeclared(found, core, extras) == {
        "notalibrary": ["docpipe/x.py"]}


def test_doctor_reads_the_lists_of_the_package():
    core, extras = declared()
    assert doctor_disagreements(doctor.CORE, doctor.NEEDS, core,
                                extras) == []


def test_a_doctor_list_that_says_otherwise_is_found():
    core, extras = declared()
    said = doctor_disagreements(doctor.CORE + ("notalibrary",),
                                {"edit": (("pandas",), "editor")}, core,
                                extras)
    assert said == ["CORE has notalibrary, which is no requirement",
                    "edit: pandas is not in [editor]"]


GUARD = r'''
import builtins, importlib, pkgutil, sys
allowed = set(sys.argv[1].split(","))
std = set(sys.stdlib_module_names)
real = builtins.__import__

def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    importer = (globals or {}).get("__name__") or ""
    top = name.partition(".")[0]
    if (level == 0 and importer.partition(".")[0] == "docpipe"
            and top not in std and top not in ("docpipe", "profiles")
            and top not in allowed):
        raise ModuleNotFoundError("refused: " + top, name=top)
    return real(name, globals, locals, fromlist, level)

builtins.__import__ = guarded
import docpipe.editor
for module in pkgutil.iter_modules(docpipe.editor.__path__):
    importlib.import_module("docpipe.editor." + module.name)
print("started")
'''


def start_with(allowed: set) -> subprocess.CompletedProcess:
    """Every module of docpipe.editor imported in a process of its own in
    which docpipe may import only *allowed* from outside."""
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-c", GUARD,
                           ",".join(sorted(allowed))], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=300)


def editor_allowed() -> set:
    """The import names of the package's own requirements and of the extra
    `editor`."""
    core, extras = declared()
    lists = set(core) | extras["editor"]
    return {name for name in outside(sources())
            if distribution(name) in lists}


@needs_stdlib_list
def test_the_editor_starts_with_its_own_lists_alone():
    done = start_with(editor_allowed())
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().endswith("started")


@needs_stdlib_list
def test_the_editor_without_regex_does_not_start():
    done = start_with(editor_allowed() - {"regex"})
    assert done.returncode != 0
    assert "refused: regex" in done.stderr


def test_the_command_names_what_the_installation_lacks():
    absent = {"regex", "rdflib"}
    core, tabs = start.missing_libraries(
        find=lambda name: None if name in absent else object())
    assert core == ["regex"]
    assert tabs == ["rdflib"]
    assert start.missing_libraries(find=lambda name: object()) == ([], [])
