# scripts.build_docs

`scripts/build_docs.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Generate the documentation pages from the sources they describe.

A hand-written page is a second copy of something, and the copy is the one
that goes stale: it says what a module did when somebody last looked. Every
page under `docs/` except one is therefore rendered from what it documents --
module docstrings, the checked-in extraction schemas, the artifact constants,
the signatures and docstrings of every public name for the API reference --
and `--check` fails the test suite the moment the checked-in page and a fresh
render disagree.

What that buys, concretely: renaming a package, emptying a docstring, adding a
state to `fields.py` without regenerating a schema, or adding a profile with no
contract page all turn into a red test instead of a paragraph nobody re-reads.

Two rules hold the thing together.

**One door.** `read_source` is the only function that opens a file, and it
refuses anything outside `docpipe/`, `profiles/`, `scripts/` and `docs/`, and
anything under `data/`. The corpus is not in this repository, but the plans it
is built from are not public either, and a generator that can read a path can
publish it. A test parses THIS file and asserts no other read exists.

**Build, then write.** `build()` renders every page into memory and writes
nothing; `write()` is the only writer and refuses a key that escapes its output
directory. So `--check` cannot mutate the tree it is checking, and a source
that has moved fails the whole build instead of leaving half a site.

Usage:
    python scripts/build_docs.py --out docs      # rewrite the pages
    python scripts/build_docs.py --check         # fail on drift
Exit codes:
    0  the checked-in pages are a fresh render
    1  a page has drifted, a page is orphaned, or a source has moved

Author: Felix Vossel

## Classes

### SourceMoved

```python
class SourceMoved(Exception)
```

A page's source is gone, empty, or no longer carries what it renders.

#### SourceMoved.\_\_init\_\_

```python
def __init__(self, page: str, rel: str, why: str)
```

## Functions

### read_source

```python
def read_source(rel: str) -> str
```

The text of one documented file. The only read in this module.

Returns text and not a path on purpose: a caller holding a path would have
to open it, and the second door is how the first one stops meaning
anything.

### docstring_of

```python
def docstring_of(rel: str) -> str
```

One module's docstring, or `SourceMoved` if it has none.

### json_at

```python
def json_at(rel: str, pointer: str)
```

The value at a `/`-separated pointer, or `SourceMoved`.

### constants_of

```python
def constants_of(rel: str) -> tuple
```

((name, value, trailing comment), ...) for one module's string names.

Two passes over one string, because neither tool alone can do it: `ast`
keeps no comments, and `ast.literal_eval` raises on an f-string -- and
seven of the nine artifact names ARE f-strings built from the two before
them. The comment is what says which stage writes the file, which is the
only reason the page is worth generating.

### states_table

```python
def states_table() -> tuple
```

((constant name, value, gloss), ...) in the schema's own enum order.

The rule is an intersection and it has to be: `fields.py` carries twelve
module-level strings and only seven of them are states. Published by
"every string constant" the page would offer `out:unstated`, which is an
ANSWER a model may give and not a state a coordinate can be in.

### trust_table

```python
def trust_table() -> tuple
```

((level, gloss), ...), the reason patterns, the flag reasons, the
marks of a trust line in their order, and the reason separator.

The levels and the reason vocabulary are read from the published schema
rather than from `trust.py` alone, because the schema is the copy an
existing test keeps equal to the code -- so the page inherits that check
instead of adding a second one.

### toctree_groups

```python
def toctree_groups(pages) -> list
```

[(caption, [page, ...])] for the site's contents, wildcards expanded.

A page that no group names still reaches the contents, in a last group,
so a new page is a broken build (the Read the Docs build treats a page
outside every toctree as a warning) rather than an unreachable document.

### resolve

```python
def resolve(sources) -> dict
```

{page: [(rel, value)]} — every source of every page, or `SourceMoved`.

Run over the WHOLE manifest before anything is rendered, so a source that
has moved fails the build instead of leaving a site whose other half is
fresh.

### intro_of

```python
def intro_of(page: str) -> str
```

The page's own introduction, or "" when it has none.

### render_stage_page

```python
def render_stage_page(page: str, parts: list) -> str
```

The page's introduction, then one section per module.

The introduction is prose somebody wrote; everything under it is the
module's own docstring, verbatim. Two layers rather than one, because they
go stale differently: a docstring is wrong the moment its module changes
and is checked by being generated, while "this runs before that" is not in
any module and cannot be.

### render_profile_page

```python
def render_profile_page(name: str, harvest: dict, intro: str) -> str
```

The profile's own page: prose, then the parameters and their axes
read off the published contract, never off the spec (the spec carries
real corpus tables as examples).

### render_contract_page

```python
def render_contract_page(profile: str, schema: dict, stamp=None,
                         trace=None, intro: str = "") -> str
```

One section per record kind, straight out of the published schema,
then the stamp beside the harvest file and the trace beside both.

### render_states_page

```python
def render_states_page(rows, intro: str = "") -> str
```

### render_trust_page

```python
def render_trust_page(levels, reasons, flag_reasons, marks, join,
                      doc: str, intro: str = "") -> str
```

### render_artifacts_page

```python
def render_artifacts_page(constants, doc: str, intro: str = "") -> str
```

### render_profiles_page

```python
def render_profiles_page(doc: str, profiles, intro: str = "") -> str
```

How to write a profile, then what `profile.py` itself says.

The introduction is the part that matters to somebody adding a third
profile, and it is prose in `docs/_intros/profiles.md` rather than a
docstring: the contract is spread over `profile.py`, the two existing
profiles and the architecture tests, and no single module can state it.

### dotted

```python
def dotted(rel: str) -> str
```

`docpipe/extraction/pipeline.py` is `docpipe.extraction.pipeline`,
and a package's `__init__.py` is the package.

### api_page

```python
def api_page(rel: str) -> str
```

### is_api_module

```python
def is_api_module(page: str) -> bool
```

A module's page, as opposed to the reference's own index.

### parse_api

```python
def parse_api(text: str, rel: str) -> dict
```

What one module publishes, from its text.

Its docstring, every public function and class with their docstrings,
and what its `__all__` exports. Public is what `__all__` names when
there is one, and otherwise every name without a leading underscore.

### module_api

```python
def module_api(rel: str) -> dict
```

### markdown_safe

```python
def markdown_safe(doc: str) -> str
```

A docstring as the Markdown it is written in.

Escaped, and only outside code spans, fenced blocks and indented code:
a `<` that opens what Markdown takes for a tag, so `<name>.jsonl` reads
as written instead of as ".jsonl" with the tag swallowed; the underscores
at a word's edge, so `__init__` does not come out as "init" in bold; and
a `#` opening a line, which would be a heading of the page rather than a
line of the docstring. Inside a list item, four spaces are the item's
continuation and not code, so there the code rule needs four more.

### render_api_page

```python
def render_api_page(module: dict, known=None) -> str
```

One module: its docstring, then every public class and function with
its signature as written and its docstring, verbatim.

### render_api_index

```python
def render_api_index(modules: dict, intro: str = "") -> str
```

The reference's own index: one list per package with each module's
first sentence, then the toctrees that put the pages in the sidebar.

The toctrees are hidden because the lists above them already name every
page, with a sentence each, and Sphinx would otherwise print the same
names a second time without one.

### render_toctree

```python
def render_toctree(pages, intro: str = "") -> str
```

`index.md`: the site's front page, its introduction and its contents.

Sphinx needs one document that names every other, in the order a reader
should meet them. That order is the pipeline's, which is in no file: the
packages are named after what they do, not after when they run. One
toctree per group of GROUPS, so the sidebar carries the group names.

### render_index

```python
def render_index(pages, ledes=None) -> str
```

### build

```python
def build() -> dict
```

{page relpath: text}. Renders everything, writes nothing.

### write

```python
def write(out_dir, pages: dict) -> list
```

Write the rendered pages. The only writer in this module.

### check

```python
def check() -> int
```

Compare the checked-in pages with a fresh render. 0 when they agree.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
