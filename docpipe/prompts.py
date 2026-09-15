"""
prompts.py: Loads a profile's prompts, one Markdown file per stage, from
`profiles/<profile>/prompts/<stage>/<name>.md`.

There is no core default. A prompt names the corpus it is written for and
the language it answers in, and the core knows neither: a fallback here
could only be some other project's prompt, which is worse than a missing
file.

Optional YAML front matter carries the model parameters that belong to the
prompt (temperature, max_tokens), so the two never drift apart.

Every prompt has a sha256 over its file. Stages record those hashes with
their output; when a hash no longer matches, the result was produced by a
different prompt and is stale (see `stale()`).

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .profile import ENV_VAR, Profile, active_profile

VERSION_FILE = ".prompt_versions.json"
_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    meta: Mapping
    sha256: str
    path: Path

    @property
    def placeholders(self) -> frozenset:
        return frozenset(_PLACEHOLDER.findall(self.text))

    def render(self, **values) -> str:
        """Substitute {{name}}. Unknown or missing names are an error, so a
        renamed placeholder fails loudly instead of shipping '{{foo}}' to the
        model."""
        needed = self.placeholders
        missing = needed - set(values)
        if missing:
            raise KeyError(f"{self.id}: missing placeholder(s) {sorted(missing)}")
        extra = set(values) - needed
        if extra:
            raise KeyError(f"{self.id}: unknown placeholder(s) {sorted(extra)}")
        return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), self.text)


def path_for(prompt_id: str, profile: Profile) -> Path:
    stage, _, name = prompt_id.partition("/")
    if not stage or not name:
        raise ValueError(f"prompt id must be '<stage>/<name>', got {prompt_id!r}")
    return profile.prompts_dir / stage / f"{name}.md"


def load(prompt_id: str, profile: Optional[Profile] = None,
         use_ambient: bool = True) -> Prompt:
    """The prompt as the profile writes it."""
    if profile is None and use_ambient:
        profile = active_profile()
    if profile is None:
        raise LookupError(
            f"prompt {prompt_id!r} needs a profile; set ${ENV_VAR} or pass one")

    path = path_for(prompt_id, profile)
    if not path.is_file():
        raise FileNotFoundError(
            f"profile {profile.name!r} provides no prompt {prompt_id!r} ({path})")

    raw = path.read_text(encoding="utf-8")
    meta, body = _split(raw)
    return Prompt(id=prompt_id, text=body, meta=meta, path=path,
                  sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest())


def text(prompt_id: str, **values) -> str:
    """Shorthand for module-level constants: text('refinement/refine')."""
    prompt = load(prompt_id)
    return prompt.render(**values) if values else prompt.text


def versions(prompt_ids: Iterable[str],
             profile: Optional[Profile] = None) -> dict:
    """{id: sha256} — write this next to a stage's output."""
    return {pid: load(pid, profile).sha256 for pid in prompt_ids}


def record(directory: Path, prompt_ids: Iterable[str],
           profile: Optional[Profile] = None) -> None:
    """Write the prompt hashes next to a stage's output."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / VERSION_FILE).write_text(
        json.dumps(versions(prompt_ids, profile), indent=1, sort_keys=True),
        encoding="utf-8")


def check(directory: Path, prompt_ids: Iterable[str],
          profile: Optional[Profile] = None) -> list:
    """Prompt ids that changed since the result in *directory* was produced."""
    path = directory / VERSION_FILE
    stored = None
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = None
    return stale(stored, versions(prompt_ids, profile))


def stale(stored: Optional[Mapping], current: Mapping) -> list:
    """Prompt ids whose hash changed since the stored result was produced.

    An absent entry counts as changed: results from before prompts were
    versioned cannot be vouched for either.
    """
    if not stored:
        return sorted(current)
    return sorted(pid for pid, sha in current.items() if stored.get(pid) != sha)


def _split(raw: str) -> tuple:
    """Front matter plus body. The body is passed through byte for byte —
    leading and trailing whitespace of a prompt is part of the prompt."""
    match = _FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    import yaml  # only prompts that carry front matter need it
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("prompt front matter must be a mapping")
    return meta, raw[match.end():]
