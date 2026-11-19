"""A sentence a model reads that moved out of a stage's code into a prompt
file (owner request 2026-11-19, point A1 of the review of that day) leaves
the results written before as current as they were (`prompts.FROM_CODE`).

The promises, each with a case that breaks it by construction:

1. A result recorded before the prompt had a file is not stale for it while
   the file is the one first written, for each profile's file, AND it is
   stale for it once the file changes.
2. A prompt the record lacks and the code never worded is stale, as it
   always was; a stored hash that differs is stale whatever FROM_CODE says.
3. Every prompt FROM_CODE names is one of a stage's recorded prompts, with
   one first hash per profile that has its own file.
"""
from __future__ import annotations

from docpipe import prompts
from docpipe.profile import load_profile


def test_a_moved_prompt_keeps_the_results_written_before(monkeypatch):
    monkeypatch.setattr(prompts, "FROM_CODE", {"s/moved": ("a1", "b1")})
    stored = {"s/kept": "k1"}
    assert prompts.stale(stored, {"s/kept": "k1", "s/moved": "a1"}) == []
    assert prompts.stale(stored, {"s/kept": "k1", "s/moved": "b1"}) == []
    # the file changed after it was first written
    assert prompts.stale(stored, {"s/kept": "k1", "s/moved": "a2"}) \
        == ["s/moved"]


def test_a_prompt_the_code_never_worded_is_stale_as_before(monkeypatch):
    monkeypatch.setattr(prompts, "FROM_CODE", {"s/moved": ("a1",)})
    stored = {"s/kept": "k1"}
    assert prompts.stale(stored, {"s/kept": "k1", "s/new": "n1"}) \
        == ["s/new"]
    assert prompts.stale({**stored, "s/moved": "old"},
                         {"s/kept": "k1", "s/moved": "a1"}) == ["s/moved"]
    # a record of no prompt at all vouches for none
    assert prompts.stale({}, {"s/moved": "a1"}) == ["s/moved"]


def test_every_prompt_from_code_is_recorded_with_its_first_hashes():
    from docpipe.refinement import config as refine_config
    from docpipe.refinement import split
    from docpipe.visuals import config as visuals_config
    recorded = set(refine_config.prompt_ids()) | set(split.PROMPT_IDS) \
        | set(visuals_config.PROMPT_IDS)
    for pid, shas in prompts.FROM_CODE.items():
        assert pid in recorded, pid
        now = {prompts.load(pid, load_profile(name)).sha256
               for name in ("default", "kwp", "scenarios")}
        assert now <= set(shas), pid
