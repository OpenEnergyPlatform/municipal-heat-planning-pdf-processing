# docpipe.editor.stagespage

`docpipe/editor/stagespage.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

stagespage.py: The Stages tab: the stages before the harvest as a picture.

Owner request 2026-11-19, point A1 of the review of that day ("ein sechster
Reiter oder ein Eintrag im Ablauf-Reiter zeigt die Stufen 1 bis 6 als
Bild"): from the documents of the profile's source through stages 1 to 6 to
the harvest, each stage with what it does, the command that runs it, its
rules (the tab "stages", one group a stage), the prompts it asks with and
the request logs it writes (stages 4 and 5, owner request A3). What a
stage's logs say is counted on demand (`measured`), at the number of
attempts its rule allows, in the sentences the Flow tab says of the
harvest's (`editor.measured`).

Author: Felix Vossel

## Functions

### group_of

```python
def group_of(stage: dict) -> str
```

The group of the stage's rules on the tab "stages".

### prompts_of

```python
def prompts_of(stage: dict, listed: set) -> list
```

The prompts the stage asks with that the profile has: those it names,
or for a stage that writes a request log every prompt its requests are
made of (`prompts.stage_requests`).

### view

```python
def view(profile, logs: Callable) -> dict
```

The Stages tab: every stage with its rules (how many, how many the
profile sets itself), its prompts and how many request logs it left;
*logs(stage)* lists the names of a stage's logs.

### says

```python
def says(profile, stage_key: str, facts: list) -> dict
```

What the request logs of one stage say (*facts*, `measured.facts` of
each log): how many requests, and the sentences of the replies read and
lost at the number of attempts the stage's rule allows in *profile*.

[Back to the index](../README.md)
