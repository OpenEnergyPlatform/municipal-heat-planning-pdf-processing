# docpipe.extraction.contract

`docpipe/extraction/contract.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

contract.py: The core's half of the extraction prompts: where its templates
are, which languages they come in and the facts the code fills into them.

A prompt of the extraction stage says what the answer has to look like (the
keys, the quote that stands in a source, the answer that stands in the quote,
"not stated", what to do with a closed list) and it says what the corpus is
(the role, the examples, how its tables are written). The first is the same
for every corpus and was copied into every profile's prompts, with the
sentences drifting apart. It is written in `contract/<language>/<name>.md`,
and a profile's prompt that names it (`template: rows`) holds its own half:
its parts, and its own words for a sentence of the template that fits it
less well. docpipe/prompts.py puts them together.

The language of a prompt is a fact about the profile that owns the parts
file, declared there as `extraction.CONTRACT_LANGUAGE` and not inherited: a
profile that extends another and keeps its parts files gets the language
those are in. A profile with no declaration, or one the core has no templates
for, is refused at load and told which languages there are.

A fact is a value the code decides and a prompt only repeats, so the prompt
and the request agree by construction: the least length of a quote
(`verify.MIN_QUOTE_CHARS`), the word for "not stated" (`fields.UNSTATED`),
and the words the closed list is shown in and the key of the frame's list from
the profile's PHRASES. No template carries any of them as a typed number or
word.

Author: Felix Vossel

## Functions

### is_name

```python
def is_name(text: str) -> bool
```

Whether *text* can name a template or a language: lower case letters,
digits and underscores, so that it never leaves the template folder.

### languages

```python
def languages() -> list
```

The languages the core has templates in: the folders of TEMPLATE_ROOT
that hold one.

### template_names

```python
def template_names(language: str) -> list
```

The templates one language has.

### template_path

```python
def template_path(language: str, name: str) -> Path
```

Where a template of the language lies, whether or not it is there. Both
names are checked so that no name reaches outside the folder.

### language_of

```python
def language_of(owner) -> Optional[str]
```

The language the parts files of a profile are in, as that profile
declares it itself, or None.

### read

```python
def read(language: str, name: str) -> "prompts.Template"
```

One template of the core, read and checked as a template.

### available

```python
def available() -> list
```

[(language, name)] of every template there is.

### facts

```python
def facts(profile, names: Iterable) -> dict
```

{name: value} of the facts a prompt names, for this profile. Only the
ones asked for are read: a profile whose PHRASES are incomplete is told so
by a prompt that needs them and not by one that does not.

[Back to the index](../README.md)
