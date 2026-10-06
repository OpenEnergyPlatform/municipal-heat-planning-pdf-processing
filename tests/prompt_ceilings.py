"""A prompt that may answer more or less than the profile's file says.

A run takes two numbers off the prompts it sends: how many tokens the largest
request needs, and how many sources the rows request may read. Both rest on
the `max_tokens` of a prompt's front matter, so the tests that hold those two
numbers to the prompts give one prompt a ceiling of its own and look at what
moves.
"""
import dataclasses

from docpipe import prompts

# The loader as shipped, taken once: each call below replaces the one before
# it and never stacks on it.
_LOADER = prompts.load


def with_max_tokens(monkeypatch, ceilings) -> None:
    """The loader, but a prompt named in *ceilings* answers up to that many
    tokens."""
    def load(prompt_id, profile=None, **kw):
        prompt = _LOADER(prompt_id, profile, **kw)
        if prompt_id in ceilings:
            prompt = dataclasses.replace(
                prompt, meta={**prompt.meta, "max_tokens": ceilings[prompt_id]})
        return prompt

    monkeypatch.setattr(prompts, "load", load)
