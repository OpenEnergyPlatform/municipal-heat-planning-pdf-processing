"""
prompts.py: Loads a profile's prompts, one Markdown file per stage, from
`profiles/<profile>/prompts/<stage>/<name>.md`.

There is no core default for what a prompt says about a corpus. A prompt names
the corpus it is written for and the language it answers in, and the core
knows neither: a fallback here could only be some other project's prompt,
which is worse than a missing file. A profile that extends another one has
asked for that profile's prompts where it wrote none itself, and gets exactly
those.

Optional YAML front matter carries the model parameters that belong to the
prompt (temperature, max_tokens), so the two never drift apart.

One kind of prompt is written in two halves. A prompt of the extraction stage
that names a template in its front matter (`template: rows`) is a parts file:
the profile writes what is about its corpus (the role, the examples, the
sentences about its own tables), and the core's contract text of the profile's
language (docpipe/extraction/contract.py) says the rest, once. `load` puts the
two together, so a request, a stamp and the render tool see one prompt. A file
without a `template` key is read as it always was.

A parts file is a front matter and sections that each start with a line
`<!-- part: name -->`. A template is a text with these marks:

    {{name}}                 where a part goes, or a fact the code fills in
    <!-- block: name -->     a stretch of contract text a profile may word
    <!-- /block -->          itself (a part of the same name replaces it) or,
                             where the template allows it, leave out
                             (`without: [name]`)
    <!-- rule: name -->      a numbered rule; the number is written at load,
    {{rule:name}}            counted over the rules that are left, and a
                             reference gives it, so omitting a rule moves the
                             numbers and what points at them

The mark of a block and the slot of a part take their line with them when they
stand alone on it: an absent optional part and an omitted block leave no blank
line behind. A part put in a block's place keeps the whitespace the block ended
with, so the lines around it stay. A block may stand more than once, and then
it can be left out but not worded, since one part cannot say two places. A part
keeps its own lines as written, apart from the blank lines around it; it may
use a fact and a reference to a rule, and nothing else with double braces. The
template's front matter says what it has: `required` and `optional` parts,
`blocks`, and the `omittable` ones among them.

Whatever does not fit fails at load with `PromptPartsError`, which names the
prompt, the part or block, the profile and the two files: a part that is
missing, a part the template does not know, a part whose place is gone, a block
that cannot be left out, a reference to a rule that is not there, a mark or a
double brace that is left in the text. Nothing is filled in for a part that is
missing.

Every prompt has a sha256 over its file. Stages record those hashes with
their output; when a hash no longer matches, the result was produced by a
different prompt and is stale (see `stale()`). A composed prompt has the
sha256 of the file a person would have written by hand: its front matter
without the two keys of the loader, and the text that is sent.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import functools
import hashlib
import importlib
import json
import os
import re
from collections.abc import Mapping as _MappingABC
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .profile import ENV_VAR, Profile, active_profile

VERSION_FILE = ".prompt_versions.json"
_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# The keys of a parts file that are the loader's own: they are not parameters
# of the model request and are not in `Prompt.meta` or the fingerprint.
LOADER_KEYS = ("template", "without")
# The stages that have templates, and the module of the core that holds them.
TEMPLATE_MODULES = {"extraction": "docpipe.extraction.contract"}
# What a template's front matter may say.
_TEMPLATE_KEYS = ("required", "optional", "blocks", "omittable")

_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
# One mark of a template: a block or its end, a rule, a reference to a rule,
# or a slot.
_MARK = re.compile(
    r"<!--\s*(?:(?P<kind>block|rule)\s*:\s*(?P<name>\w+)|(?P<end>/block))\s*-->"
    r"|\{\{\s*rule\s*:\s*(?P<ref>\w+)\s*\}\}"
    r"|\{\{\s*(?P<slot>\w+)\s*\}\}")
# What a part may carry besides its words: a reference to a rule and a fact.
_PART_MARK = re.compile(
    r"\{\{\s*rule\s*:\s*(?P<ref>\w+)\s*\}\}|\{\{\s*(?P<fact>\w+)\s*\}\}")
_PART_LINE = re.compile(r"^[ \t]*<!--\s*part\s*:\s*(\w+)\s*-->[ \t]*$", re.M)
_BLANK_LINES_BEFORE = re.compile(r"\A(?:[ \t]*\n)+")


class PromptPartsError(ValueError):
    """A prompt that names a template could not be composed.

    It says which prompt, which part or block, which profile and which two
    files, so that whoever reads it in a log knows what to open.
    """

    def __init__(self, message: str, *, prompt_id: Optional[str] = None,
                 part: Optional[str] = None, profile: Optional[str] = None,
                 files: Iterable = ()):
        self.prompt_id, self.part, self.profile = prompt_id, part, profile
        self.files = tuple((label, str(path)) for label, path in files
                           if path is not None)
        head = ", ".join(bit for bit in (
            f"prompt {prompt_id!r}" if prompt_id else "",
            f"profile {profile!r}" if profile else "") if bit)
        text = f"{head}: {message}" if head else message
        if self.files:
            text += " [" + "; ".join(f"{label}: {path}"
                                     for label, path in self.files) + "]"
        super().__init__(text)


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    meta: Mapping
    sha256: str
    path: Path
    # How the text was made when the file is a parts file, else None: a
    # mapping with `template`, `language`, `overrides` (the blocks the profile
    # words itself), `omitted` (the blocks it leaves out) and `what_if` ({an
    # omitted block: the text with that block put back}, made when asked for).
    composition: Optional[Mapping] = None

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


def _find(prompt_id: str, profile: Profile) -> tuple:
    """(the profile that has the prompt, its file). The profile's own place
    when nobody has it, for the message that says so."""
    stage, _, name = prompt_id.partition("/")
    if not stage or not name:
        raise ValueError(f"prompt id must be '<stage>/<name>', got {prompt_id!r}")
    for owner in profile.lineage():
        path = owner.prompts_dir / stage / f"{name}.md"
        if path.is_file():
            return owner, path
    return profile, profile.prompts_dir / stage / f"{name}.md"


def path_for(prompt_id: str, profile: Profile) -> Path:
    """Where the prompt lies: in the profile, else in the nearest profile
    it extends. The profile's own place when nobody has it, for the message
    that says so."""
    return _find(prompt_id, profile)[1]


def owner_of(prompt_id: str, profile: Profile) -> Profile:
    """The profile whose file the prompt is: the profile itself, else the
    nearest one it extends that has it."""
    return _find(prompt_id, profile)[0]


def load(prompt_id: str, profile: Optional[Profile] = None,
         use_ambient: bool = True) -> Prompt:
    """The prompt as the profile writes it, or, for a parts file, as the core
    and the profile make it together."""
    if profile is None and use_ambient:
        profile = active_profile()
    if profile is None:
        raise LookupError(
            f"prompt {prompt_id!r} needs a profile; set ${ENV_VAR} or pass one")

    owner, path = _find(prompt_id, profile)
    if not path.is_file():
        extended = [other.name for other in profile.lineage()[1:]]
        raise FileNotFoundError(
            f"profile {profile.name!r} provides no prompt {prompt_id!r} ({path})"
            + (f", nor does {', '.join(extended)}" if extended else ""))

    raw = path.read_text(encoding="utf-8")
    meta, body = _split(raw)
    if "template" in meta:
        return _composed(prompt_id, profile, owner, path, raw, meta, body)
    return Prompt(id=prompt_id, text=body, meta=meta, path=path,
                  sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest())


def per_profile(read):
    """Make *read()* run once per ambient profile, on first use.

    For what a stage needs from its prompts: read when it is first asked for
    and not when the stage is imported, so a stage can be imported, and print
    its --help, before anybody has named a profile. Read once, so one run
    works with one prompt.
    """
    cache: dict = {}

    @functools.wraps(read)
    def reader():
        key = os.environ.get(ENV_VAR)
        if key not in cache:
            cache[key] = read()
        return cache[key]

    return reader


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


# ---------------------------------------------------------------------------
# Templates and parts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Template:
    """One template of the core, read: what it asks of a profile and what it
    says. `nodes` is the body as a tree: ("text", s), ("slot", name, indent,
    newline) for a part, ("fact", name), ("rule", name), ("ref", name) and
    ("block", name, children)."""
    name: str
    language: str
    path: Path
    required: tuple
    optional: tuple
    blocks: tuple
    omittable: tuple
    nodes: tuple
    rules: tuple            # the rules in the order the template has them
    places: Mapping         # part or block name -> the blocks it lies in
    rule_blocks: Mapping    # rule name -> the blocks it lies in
    block_counts: Mapping   # block name -> how often the template has it

    def shape(self) -> dict:
        """What the template asks of a profile, by name: what two templates
        of one name in two languages have to share."""
        return {"required": frozenset(self.required),
                "optional": frozenset(self.optional),
                "blocks": frozenset(self.blocks),
                "omittable": frozenset(self.omittable),
                "rules": frozenset(self.rules)}


def line_at(body: str, offset: int, index: int) -> int:
    """The line of the file that character *index* of *body* is in, for a body
    that starts *offset* lines into the file."""
    return offset + body.count("\n", 0, index) + 1


def _template_failure(path: Path):
    def make(message: str, part: Optional[str] = None) -> PromptPartsError:
        return PromptPartsError(message, part=part,
                                files=(("template", path),))
    return make


def _names(value, key: str, fail) -> tuple:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
            isinstance(item, str) and _NAME.match(item) for item in value):
        raise fail(f"front matter key {key!r} must be a list of names "
                   f"(letters, digits and underscores), got {value!r}")
    if len(set(value)) != len(value):
        raise fail(f"front matter key {key!r} names "
                   f"{sorted({n for n in value if value.count(n) > 1})} twice")
    return tuple(value)


def read_template(path: Path, *, language: str, name: str,
                  fact_names: Iterable = (), fail=None) -> Template:
    """A template file, read and checked as a template: its front matter, its
    marks and what refers to what. `fail(message, part)` makes the exception
    to raise; by default one that names the file."""
    path = Path(path)
    fail = fail or _template_failure(path)
    raw = path.read_text(encoding="utf-8")
    meta, body = _split(raw)
    offset = raw[:len(raw) - len(body)].count("\n")
    unknown = sorted(set(meta) - set(_TEMPLATE_KEYS))
    if unknown:
        raise fail(f"front matter key(s) {unknown} are not a template's: it "
                   f"has {list(_TEMPLATE_KEYS)}, and the parameters of the "
                   f"model are the profile's")
    required, optional, blocks, omittable = (
        _names(meta.get(key), key, fail) for key in _TEMPLATE_KEYS)
    if set(required) & set(optional):
        raise fail(f"{sorted(set(required) & set(optional))} are both "
                   f"required and optional")
    if set(required + optional) & set(blocks):
        raise fail(f"{sorted(set(required + optional) & set(blocks))} are "
                   f"both a part and a block: a name asks for one thing")
    if set(omittable) - set(blocks):
        raise fail(f"omittable {sorted(set(omittable) - set(blocks))} are not "
                   f"among the blocks")
    fact_names = frozenset(fact_names)
    clash = sorted(set(required + optional + blocks) & fact_names)
    if clash:
        raise fail(f"{clash} are the name of a fact of the core; a part or a "
                   f"block takes another")
    parts = frozenset(required + optional)

    line_of = functools.partial(line_at, body, offset)

    def stray(chunk: str, start: int) -> None:
        for mark in ("<!--", "{{"):
            at = chunk.find(mark)
            if at >= 0:
                raise fail(f"line {line_of(start + at)}: {mark!r} is not a "
                           f"mark of a template (block, rule, a reference "
                           f"{{{{rule:name}}}} or a slot {{{{name}}}})")

    stack: list = [("", [])]
    seen_blocks: list = []
    seen_rules: list = []
    places: dict = {}
    rule_blocks: dict = {}
    refs: list = []
    pos = 0
    for found in _MARK.finditer(body):
        start, end = found.span()
        cut_start, cut_end, indent, newline = start, end, "", False
        whole = (found.group("end") or found.group("kind") == "block"
                 or (found.group("slot") in parts))
        if whole:
            first = body.rfind("\n", 0, start) + 1
            last = body.find("\n", end)
            stop = len(body) if last < 0 else last
            if not body[first:start].strip() and not body[end:stop].strip():
                cut_start, indent = first, body[first:start]
                newline = last >= 0
                cut_end = stop + (1 if newline else 0)
        chunk = body[pos:cut_start]
        stray(chunk, pos)
        if chunk:
            stack[-1][1].append(("text", chunk))
        pos = cut_end
        here = tuple(item[0] for item in stack[1:])
        if found.group("end"):
            if len(stack) == 1:
                raise fail(f"line {line_of(start)}: a block is closed that "
                           f"was never opened")
            label, children = stack.pop()
            stack[-1][1].append(("block", label, tuple(children)))
        elif found.group("kind") == "block":
            label = found.group("name")
            if label not in blocks:
                raise fail(f"line {line_of(start)}: block {label!r} is not "
                           f"among the template's blocks {list(blocks)}",
                           label)
            seen_blocks.append(label)
            places.setdefault(label, here)
            stack.append((label, []))
        elif found.group("kind") == "rule":
            label = found.group("name")
            if label in seen_rules:
                raise fail(f"line {line_of(start)}: rule {label!r} stands "
                           f"twice", label)
            seen_rules.append(label)
            rule_blocks[label] = here
            stack[-1][1].append(("rule", label))
        elif found.group("ref"):
            refs.append((found.group("ref"), line_of(start)))
            stack[-1][1].append(("ref", found.group("ref")))
        else:
            label = found.group("slot")
            if label in parts:
                if label in places:
                    raise fail(f"line {line_of(start)}: the slot of part "
                               f"{label!r} stands twice; a part is put in "
                               f"once", label)
                places[label] = here
                stack[-1][1].append(("slot", label, indent, newline))
            elif label in fact_names:
                stack[-1][1].append(("fact", label))
            else:
                raise fail(
                    f"line {line_of(start)}: {{{{{label}}}}} is neither a "
                    f"part of this template ({list(required + optional)}) nor "
                    f"a fact of the core ({sorted(fact_names)})", label)
    tail = body[pos:]
    stray(tail, pos)
    if tail:
        stack[-1][1].append(("text", tail))
    if len(stack) > 1:
        raise fail(f"block {stack[-1][0]!r} is never closed", stack[-1][0])
    for label in blocks:
        if label not in seen_blocks:
            raise fail(f"block {label!r} is declared and never used", label)
    for label in parts:
        if label not in places:
            raise fail(f"part {label!r} is declared and has no slot", label)
    for label, line in refs:
        if label not in seen_rules:
            raise fail(f"line {line}: a reference to rule {label!r}, which "
                       f"the template does not have ({seen_rules})", label)
    for label in required:
        gone = [b for b in places[label] if b in omittable]
        if gone:
            raise fail(f"required part {label!r} lies in the omittable block "
                       f"{gone[0]!r}: leaving the block out would leave the "
                       f"part nowhere", label)
    return Template(
        name=name, language=language, path=path, required=required,
        optional=optional, blocks=blocks, omittable=omittable,
        nodes=tuple(stack[0][1]), rules=tuple(seen_rules), places=places,
        rule_blocks=rule_blocks,
        block_counts={label: seen_blocks.count(label) for label in blocks})


def read_parts(raw_body: str, fail, offset: int = 0) -> dict:
    """{part name: its text} of a parts file's body, which starts `offset`
    lines into the file. A section starts with a line `<!-- part: name -->`;
    its text is what follows up to the next one, without the blank lines
    around it."""
    marks = list(_PART_LINE.finditer(raw_body))
    first = marks[0].start() if marks else len(raw_body)
    lead = raw_body[:first]
    if lead.strip():
        line = line_at(raw_body, offset, len(lead) - len(lead.lstrip()))
        raise fail(f"text stands before the first part, in line {line}; "
                   f"every line of a parts file belongs to a part")
    found: dict = {}
    for index, mark in enumerate(marks):
        name = mark.group(1)
        stop = marks[index + 1].start() if index + 1 < len(marks) \
            else len(raw_body)
        text = _BLANK_LINES_BEFORE.sub("", raw_body[mark.end():stop]).rstrip()
        if name in found:
            raise fail(f"part {name!r} stands twice", name)
        if not text.strip():
            raise fail(f"part {name!r} is empty", name)
        found[name] = text
    return found


class _Context:
    """Where a composition is happening, for what its errors say."""

    def __init__(self, prompt_id: str, profile: Profile, parts_path: Path):
        self.prompt_id, self.profile = prompt_id, profile
        self.parts_path = parts_path
        self.template_path: Optional[Path] = None

    def fail(self, message: str, part: Optional[str] = None) -> PromptPartsError:
        return PromptPartsError(
            message, prompt_id=self.prompt_id, part=part,
            profile=self.profile.name,
            files=(("parts file", self.parts_path),
                   ("template", self.template_path)))


def _unknown(name: str, known: Iterable) -> str:
    near = difflib.get_close_matches(name, list(known), n=1)
    return f" (did you mean {near[0]!r}?)" if near else ""


def _pieces(text: str, label: str, facts_known: frozenset, ctx: _Context):
    """A part's text as pieces: its words verbatim, and its references to
    rules and its facts. Any other double brace or comment mark is an open
    placeholder."""
    out, pos = [], 0
    for found in _PART_MARK.finditer(text):
        out.append(("text", text[pos:found.start()]))
        if found.group("ref"):
            out.append(("ref", found.group("ref")))
        elif found.group("fact") in facts_known:
            out.append(("fact", found.group("fact")))
        else:
            raise ctx.fail(
                f"{found.group(0)} in {label!r} is not a fact of the core "
                f"({sorted(facts_known)}) and not a reference to a rule; an "
                f"open placeholder is never sent", label)
        pos = found.end()
    out.append(("text", text[pos:]))
    for kind, chunk in out:
        if kind == "text":
            for mark in ("<!--", "{{"):
                if mark in chunk:
                    raise ctx.fail(
                        f"{label!r} holds {mark!r} that is not a fact or a "
                        f"reference to a rule; an open placeholder is never "
                        f"sent", label)
    return [piece for piece in out if piece != ("text", "")]


def _trailing_space(children: tuple) -> str:
    """The whitespace a block ends with, which a replacement keeps so that
    the lines around it stay where they were."""
    if children and children[-1][0] == "text":
        chunk = children[-1][1]
        return chunk[len(chunk.rstrip()):]
    return ""


def _compose(template: Template, parts: Mapping, without: frozenset,
             profile: Profile, contract, ctx: _Context) -> str:
    """The body of a prompt: the template with the profile's parts in, the
    overridden blocks replaced, the omitted ones gone, the rules numbered and
    the facts filled. The checks that tie the profile's file to the template
    are here, so a what-if composes under the same ones."""
    known = frozenset(contract.FACT_NAMES)
    pieces: list = []
    placed: set = set()

    def put(label: str) -> None:
        placed.add(label)
        pieces.extend(_pieces(parts[label], label, known, ctx))

    def walk(nodes) -> None:
        for node in nodes:
            tag = node[0]
            if tag in ("text", "rule", "ref", "fact"):
                pieces.append(node)
            elif tag == "slot":
                _, label, indent, newline = node
                if label in parts:
                    if indent:
                        pieces.append(("text", indent))
                    put(label)
                    if newline:
                        pieces.append(("text", "\n"))
            else:
                _, label, children = node
                if label in without:
                    continue
                if label in parts:
                    put(label)
                    space = _trailing_space(children)
                    if space:
                        pieces.append(("text", space))
                    continue
                walk(children)

    walk(template.nodes)

    for label in sorted(set(parts) - placed):
        inside = [b for b in template.places.get(label, ())
                  if b in without or b in parts]
        why = ""
        if inside:
            how = "left out by `without`" if inside[0] in without \
                else "replaced by a part of the same name"
            why = f": its place lies in the block {inside[0]!r}, {how}"
        raise ctx.fail(f"part {label!r} has no place in the prompt{why}; "
                       f"text of the profile that is never sent is a mistake",
                       label)

    numbers: dict = {}
    for kind, value in pieces:
        if kind == "rule":
            numbers[value] = len(numbers) + 1
    out, used = [], set()
    for kind, value in pieces:
        if kind == "text":
            out.append(value)
        elif kind == "rule":
            out.append(f"{numbers[value]}.")
        elif kind == "ref":
            if value not in numbers:
                if value not in template.rules:
                    raise ctx.fail(f"a reference to rule {value!r}, which "
                                   f"the template does not have "
                                   f"({list(template.rules)})", value)
                gone = [b for b in template.rule_blocks[value]
                        if b in without or b in parts]
                raise ctx.fail(
                    f"a reference to rule {value!r}, which is not in this "
                    f"prompt" + (f": it lies in the block {gone[0]!r}, which "
                                 f"is left out or replaced" if gone else "")
                    + "; leave out the text that points at it as well",
                    value)
            out.append(str(numbers[value]))
        else:
            used.add(value)
            out.append("{{" + value + "}}")
    joined = "".join(out)
    if used:
        try:
            values = contract.facts(profile, sorted(used))
        except LookupError as exc:
            raise ctx.fail(f"a fact of the core cannot be filled for this "
                           f"profile: {exc}") from exc
        joined = Prompt(id=ctx.prompt_id, text=joined, meta={}, sha256="",
                        path=ctx.parts_path).render(**values)
    for mark in ("<!--", "{{"):
        at = joined.find(mark)
        if at >= 0:
            around = joined[max(0, at - 30):at + 40].replace("\n", " ")
            raise ctx.fail(f"{mark!r} is left in the composed text, near "
                           f"{around!r}; an open placeholder or a mark is "
                           f"never sent")
    return joined


def _front_without(front: str, drop: tuple) -> str:
    """The front matter the way a person would have written it without the
    keys of the loader: the lines of those keys, and the lines that belong to
    them (a list under a key), are gone and everything else is as written."""
    kept, dropping = [], False
    for line in front.split("\n"):
        key = re.match(r"([A-Za-z_][\w-]*)\s*:", line)
        if key:
            dropping = key.group(1) in drop
        if not dropping:
            kept.append(line)
    return "\n".join(kept)


def _composed(prompt_id: str, profile: Profile, owner: Profile, path: Path,
              raw: str, meta: dict, body: str) -> Prompt:
    """A parts file made into the prompt it stands for."""
    ctx = _Context(prompt_id, profile, path)
    stage = prompt_id.partition("/")[0]
    module = TEMPLATE_MODULES.get(stage)
    if module is None:
        raise ctx.fail(f"stage {stage!r} has no templates (only "
                       f"{sorted(TEMPLATE_MODULES)} do), so the front matter "
                       f"key 'template' has no meaning here")
    contract = importlib.import_module(module)
    name = meta["template"]
    if not isinstance(name, str) or not contract.is_name(name):
        raise ctx.fail(f"front matter key 'template' must name a template "
                       f"(lower case letters, digits and underscores), got "
                       f"{name!r}")
    language = contract.language_of(owner)
    available = contract.languages()
    if language is None:
        raise ctx.fail(
            f"profile {owner.name!r}, which holds this parts file, declares "
            f"no extraction.CONTRACT_LANGUAGE; it is read from the profile "
            f"that owns the parts file and is not inherited (languages: "
            f"{available or 'none'})")
    if language not in available:
        raise ctx.fail(
            f"CONTRACT_LANGUAGE {language!r} of profile {owner.name!r} is not "
            f"a language the core has templates for; it has "
            f"{available or 'none'}")
    ctx.template_path = contract.template_path(language, name)
    if not ctx.template_path.is_file():
        have = [lang for lang in available
                if contract.template_path(lang, name).is_file()]
        raise ctx.fail(
            f"the core has no template {name!r} in language {language!r}"
            + (f" (it has it in {have})" if have else
               f" (it has {contract.template_names(language)})"))
    template = read_template(ctx.template_path, language=language, name=name,
                             fact_names=contract.FACT_NAMES, fail=ctx.fail)

    parts = read_parts(body, ctx.fail, raw[:len(raw) - len(body)].count("\n"))
    allowed = (*template.required, *template.optional, *template.blocks)
    for label in parts:
        if label not in allowed:
            raise ctx.fail(
                f"part {label!r} is not a part or a block of template "
                f"{name!r}{_unknown(label, allowed)}; it has parts "
                f"{list(template.required + template.optional)} and blocks "
                f"{list(template.blocks)}", label)
    for label in parts:
        if template.block_counts.get(label, 0) > 1:
            raise ctx.fail(f"block {label!r} stands {template.block_counts[label]} "
                           f"times in template {name!r}, so one part cannot "
                           f"word it; it can only be left out", label)
    for label in template.required:
        if label not in parts:
            raise ctx.fail(f"part {label!r} is missing; template {name!r} "
                           f"needs {list(template.required)}", label)

    given = meta.get("without")
    if given is None:
        given = []
    if not isinstance(given, list) or not all(isinstance(g, str) for g in given):
        raise ctx.fail(f"front matter key 'without' must be a list of block "
                       f"names, got {given!r}", "without")
    for label in given:
        if label not in template.blocks:
            raise ctx.fail(f"'without' names {label!r}, which is not a block "
                           f"of template {name!r}{_unknown(label, template.blocks)}"
                           f" (blocks: {list(template.blocks)})", label)
        if label not in template.omittable:
            raise ctx.fail(f"block {label!r} cannot be left out; template "
                           f"{name!r} allows leaving out "
                           f"{list(template.omittable)}", label)
        if label in parts:
            raise ctx.fail(f"block {label!r} is both left out and worded by "
                           f"a part of the same name", label)
    if len(set(given)) != len(given):
        raise ctx.fail(f"'without' names a block twice: {given}", "without")
    without = frozenset(given)

    def compose(omitted: frozenset) -> str:
        return _compose(template, parts, omitted, profile, contract, ctx)

    text = compose(without)

    meta_out = {key: value for key, value in meta.items()
                if key not in LOADER_KEYS}
    front = _FRONT_MATTER.match(raw).group(1)
    kept = _front_without(front, LOADER_KEYS)
    import yaml
    if (yaml.safe_load(kept) or {}) != meta_out:
        raise ctx.fail(f"the front matter cannot be written without "
                       f"{list(LOADER_KEYS)} line by line, so the "
                       f"fingerprint of the prompt would not be that of a "
                       f"file written by hand; put each key on lines of its "
                       f"own")
    written = f"---\n{kept}\n---\n" if kept.strip() else ""
    sha = hashlib.sha256((written + text).encode("utf-8")).hexdigest()
    composition = {
        "template": name, "language": language,
        "overrides": sorted(label for label in template.blocks
                            if label in parts),
        "omitted": sorted(without),
        "what_if": _PutBack(sorted(without),
                            lambda label: compose(without - {label}))}
    return Prompt(id=prompt_id, text=text, meta=meta_out, sha256=sha,
                  path=path, composition=composition)


class _PutBack(_MappingABC):
    """{omitted block: the text with that block put back}. Each text is made
    the first time it is asked for, so a prompt that is only loaded costs
    nothing for what only the render tool shows."""

    def __init__(self, labels: list, make):
        self._labels, self._make, self._made = tuple(labels), make, {}

    def __getitem__(self, label: str) -> str:
        if label not in self._labels:
            raise KeyError(label)
        if label not in self._made:
            self._made[label] = self._make(label)
        return self._made[label]

    def __iter__(self):
        return iter(self._labels)

    def __len__(self) -> int:
        return len(self._labels)
