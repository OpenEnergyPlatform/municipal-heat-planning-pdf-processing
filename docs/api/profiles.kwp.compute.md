# profiles.kwp.compute

`profiles/kwp/compute.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

compute.py: What a heat plan leaves to be worked out from its printed numbers.

Two kinds of open question (`docpipe/extraction/compute.py` asks them):

- A share whose absolute number stands nowhere in its frame: "Heizöl 21 %"
  and "Wärmeverbrauch 185.200 MWh". Which total is the whole of the share is
  the model's reading, by what it means and not by its word, so all of them
  are offered, and where none is, the request may take one from the plan
  (`take_whole`).
- Parts of an amount without their sum: a sum closes exactly one axis, so the
  parts agree on everything but that axis and none of them says it is the
  total. Parts may stand in several passages.

On eight plans 71 percent of the shares had their absolute number printed, and
170 of 289 sets of parts in one passage printed their sum.

A sum over passages must not count one statement twice. `one_statement` holds
what can be told by machine: the same part, the same number within the graph's
rounding, in two passages or under one quote. Two rows of one passage with one
number are two rows. A set whose largest number is the sum of the others has
printed its sum under another word. The rest is reading and stays with the
model: a part contained in another, alternatives of one plant, a list of only
the largest parts.

What a question's numbers make is its own arithmetic, a share times its total
or the sum of the parts, and an answer has to be it (`makes`). Two questions
that come to the same number with the same coordinates are one statement, and
one row of it stays (`same`, owner decision 2026-11-03).

## Functions

### parts_of

```python
def parts_of() -> dict
```

### qualified

```python
def qualified(row: dict, used: list) -> dict
```

*row*, a number worked out from the rows *used*, with the qualifier
they leave it (owner decision 2026-11-06: the compute step inherits it):
theirs, with its evidence, where they all print the same word; none
where none prints one; "ungefähr" where they differ, since a sum of
approximate parts is approximate. A worked-out number is the end of no
range.

### entry

```python
def entry(row: dict, axis: str) -> Optional[str]
```

What this row says on this axis, None if it says nothing. A sub-area
is told from another by its name.

### whole_on

```python
def whole_on(row: dict, axis: str) -> Optional[str]
```

As `entry`, and a row that says nothing on an axis is not split on it:
the technology of most numbers is simply not asked for.

### framed

```python
def framed(row: dict) -> bool
```

### additive

```python
def additive(row: dict, spec) -> bool
```

An amount over a span in the slice, with its year and scenario. A power
is no amount: two peaks do not add up, and neither do two emission
factors, converted onto a unit of their own (g CO2/kWh) and not onto
their parameter's. An `out:` quantity has no class the graph takes: a
specific value, a saving, a useful energy. Zero is a part of nothing and
the whole of nothing, and rows of it fill plans' tables.

### same_number

```python
def same_number(a: dict, b: dict) -> bool
```

### one_statement

```python
def one_statement(a: dict, b: dict, part) -> bool
```

The same part with the same number, said twice: in two passages, or
under one quote. In one passage under two quotes it is two rows.

### distinct

```python
def distinct(rows: list, part) -> list
```

One row per statement, the most precisely printed of each.

### holds_its_sum

```python
def holds_its_sum(parts: list) -> bool
```

Is the largest of three or more numbers the sum of the others?

### known

```python
def known(row: dict, spec) -> dict
```

What was read about this number, in the plan's words where it has
them and in the list's where it does not.

### number

```python
def number(row: dict, spec, unit: Optional[str] = None) -> Number
```

The row as a question shows it, in *unit* if it names one.

### label_of

```python
def label_of(row: dict, axis: str, spec) -> Optional[str]
```

### amounts

```python
def amounts(spec) -> list
```

The parameters a whole can be one of: an amount over a span.

### quantity_slot

```python
def quantity_slot(parameter)
```

### choices

```python
def choices(spec) -> dict
```

What a whole the request takes may be, as the request shows it.

### taking

```python
def taking(spec) -> dict
```

The schema of a whole the request takes.

### take_whole

```python
def take_whole(share: dict, claim: dict, source, spec)
```

A whole the request found in a passage no row of it holds, as a
Number, or why it is not one. *source* is the passage its quote stands
in, of all the request showed. Read like any number (`verify_tuple`: its
quote in the passage, its value in the quote), its unit an entry the
parameter converts (owner decision 2026-11-07: a number whose unit is no
entry is read and not converted, and no input of a computation until
the list grows), its quantity like any coordinate (`answer_in_quote`), and its
year, scenario and area the share's, since a whole has to have them. It
stands only in the request, as an input, and is no row of its own (owner
decision 2026-11-05).

### share_question

```python
def share_question(share: dict, bases: list, spec) -> Question
```

### split_of

```python
def split_of(row: dict) -> tuple
```

### open_shares

```python
def open_shares(rows: list, spec) -> list
```

### sum_question

```python
def sum_question(parts: list, axis: str, spec) -> Question
```

### open_sums

```python
def open_sums(rows: list, spec) -> list
```

### questions

```python
def questions(rows: list, spec) -> list
```

Every number this document's verified rows leave open.

### same

```python
def same(a: dict, b: dict, spec) -> bool
```

Two worked-out rows that are one statement: the same number with the
same coordinates, whichever questions came to it. The subject is the
plan's wording and tells only different numbers apart, as in the graph;
the number is compared in its target unit, within the graph's rounding.

[Back to the index](../README.md)
