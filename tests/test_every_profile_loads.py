"""Every profile must survive being loaded, not just the one conftest pins.

conftest sets DOCPIPE_PROFILE=kwp before any import, and the config modules
bind their prompts and constants AT import and then sit in sys.modules. So the
whole suite has only ever seen kwp's values: ar6's system prompt, temperature,
max_tokens, window size and word lists were never once loaded by a test. Every
bug this file is here to catch was found by hand, in a batch job, hours in.

A subprocess per profile is the honest way to do this — the import-time binding
is exactly what must be exercised, and that cannot be undone inside a process.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"

# What has to resolve before a stage can process its first document.
# The subprocess does not get conftest's stubs, so it installs its own for the
# heavy optional deps — the point here is the profile binding, not whether
# faiss is present on a laptop.
PROBE = r"""
import sys, types


class _Permissive(types.ModuleType):
    def __getattr__(self, item):
        return type(item, (), {})


for _name in ("openai", "faiss", "cv2", "fitz", "torch", "ollama",
              "PIL", "PIL.Image", "transformers"):
    try:
        __import__(_name)
    except Exception:
        sys.modules[_name] = _Permissive(_name)

import json
from docpipe.refinement import config as refine
from docpipe.visuals import config as visuals
from docpipe.preprocessing import config as pre
from docpipe.preprocessing import stage3_structure as s3

print("@@" + json.dumps({
    "refine_budget": refine.max_request_tokens(),
    "refine_window": refine.WINDOW_SIZE,
    "refine_max_tokens": refine.LLM_MAX_TOKENS,
    "refine_prompt_words": len(refine.SYSTEM_PROMPT.split()),
    "visuals_budget": visuals.max_request_tokens(),
    "caption_max_words": pre.caption_max_words(),
    "title_prefixes": list(pre.title_exclude_prefixes()),
    "figtab_re": s3._dir_figtab_re().pattern,
    "lit_re": s3._dir_lit_title_re().pattern,
}))
"""


def _profiles():
    return sorted(p.name for p in PROFILES.iterdir()
                  if (p / "profile.py").is_file())


def _load(name: str) -> dict:
    env = {**os.environ, "DOCPIPE_PROFILE": name, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"profile {name!r} cannot be loaded:\n{proc.stderr[-2000:]}")
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("@@"))
    return json.loads(line[2:])


@pytest.mark.parametrize("name", _profiles())
def test_a_profile_loads_every_config_module(name):
    """Import-time binding must work for this profile, not only for kwp."""
    got = _load(name)
    assert got["refine_prompt_words"] > 0, "empty system prompt"
    assert got["refine_window"] >= 1
    assert got["title_prefixes"], "no caption prefixes — every figure title "\
                                  "would open a section"


@pytest.mark.parametrize("name", _profiles())
def test_a_profile_states_a_usable_context_budget(name):
    """The number a job script feeds to --max-model-len. It has to exceed the
    reply we ask for, or the request cannot even carry its own answer."""
    got = _load(name)
    assert got["refine_budget"] > got["refine_max_tokens"]
    assert got["visuals_budget"] > 0


def test_profiles_do_not_silently_share_one_language():
    """kwp is German, ar6 English. If their caption prefixes are identical,
    one of them is running on the other's word list — which is how "Figure 3:"
    became a section heading for a whole corpus."""
    loaded = {name: _load(name) for name in _profiles()}
    if len(loaded) < 2:
        pytest.skip("only one profile")
    prefixes = {name: tuple(v["title_prefixes"]) for name, v in loaded.items()}
    assert len(set(prefixes.values())) == len(prefixes), \
        f"two profiles share one caption prefix list: {prefixes}"
