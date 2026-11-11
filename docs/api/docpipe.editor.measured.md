# docpipe.editor.measured

`docpipe/editor/measured.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

measured.py: What the requests of a harvest's traces say about the numbers of
the flow.

A number of the flow was set at least once without knowing what the runs
before did under it. The traces know (`extraction.trace`): every request of
a document with what it showed and what came back. This module counts from
them what bears on a number, and says it as a sentence that names what it
counts: after how many shown pieces a search ended with an answer that
names a place (so how many of those answers a smaller budget would have
come too late for), at which attempt a reply was read, how many answers
were asked again, how long the lists were that requests showed.

Every sentence is one template of `SAID` with its numbers as {names}, in
the words of the page: the page finds its German by that template
(ui/src/i18n/templates.json), so no sentence is glued from pieces. A kind of
request and the cause of an unreadable reply are named as code, as the
request log names them.

Nothing here reads a file: it takes the requests `requests.Trace` made of a
trace. Nothing here says whether an answer held; a trace does not record
that. So a sentence speaks of "an answer that gives a line number", never
of a value read.

Which pieces of a search count toward its budget is noted with each of its
requests since 2026-11-10 (`shows`: "found" for those of the budget, "near"
for the pieces beside the value, "fetched" for those the model asked for
itself). A trace written before says nothing of it; for such a trace the
pieces of every request of a search are counted, and `notes` says so.

Author: Felix Vossel

## Functions

### step_of

```python
def step_of(request: dict) -> Optional[str]
```

The box of the default drawing a recorded request that names no box
of its own (`box`, written since 2026-11-11) was asked in, by its kind;
None for a request of no box. A follow-up is its question's, which
`facts` gives by the kind it follows.

### names_place

```python
def names_place(answer) -> bool
```

Does an answer name a line of what its request showed: an address
other than 0, or a find with one?

### light

```python
def light(events) -> list
```

The requests among a trace's *events* as far as `facts` reads them,
without putting any request back together (`requests.requests_of` does
that, and holds every prompt and passage of a document for it): the
notes of each, its answer, whether its reply could not be read, and how
long the list is that its message shows. A harvest of many documents is
counted from this.

### after

```python
def after(positions, bound: int) -> int
```

How many of *positions* lie beyond *bound*: the answers that came
only after more than *bound* pieces (or attempts) and so would have
come too late under it.

### facts

```python
def facts(requests: list) -> dict
```

What the requests of one trace say, counted once whatever the
numbers asked about:

- "requests": how many, and "steps": how many per box of the flow
  (the box a request names, else `step_of`);
- "searches": one entry per search of a value's coordinate, in order:
  {"requests", "after" (pieces of its budget shown when it ended),
  "found" (its last request's answer names a place), "noted" (its
  requests say which pieces count)};
- "docfields": the pieces shown when a request for a field the document
  has once found something, {"plain": [...], "listed": [...]} by
  whether the field has a list;
- "read": {attempt: replies read at it}, "unreadable": {cause: replies
  that could not be read};
- "follow": {kind of request: answers asked again};
- "lists": the lengths of the lists that requests for an entry showed.

### joined

```python
def joined(many: list) -> dict
```

The facts of several traces as one.

### says

```python
def says(found: dict, numbers: dict) -> dict
```

{number: [sentences]} of what the traces say about the numbers of the
flow at the values *numbers* gives them, each sentence at the named
number it measures. A number that is no whole number there says
nothing, and a number the traces say nothing about has no entry.

### notes

```python
def notes(found: dict) -> list
```

What has to be said about how the traces were counted.

[Back to the index](../README.md)
