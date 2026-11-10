# Editing a profile's spec in the browser

## What it is for

A profile's `extraction_spec.json` holds the questions a harvest asks, the
closed lists the answers are chosen from, the texts a model is shown about a
document and the examples. It is a long file, and one line of it can make a
stored harvest stale. `docpipe edit` shows that file as a page in the browser,
one form per question, and says what an edit costs the next run before it is
written. The page works on the spec only. The prompts and the flow of the
reading are not in it yet.

```
docpipe edit --profile kwp
docpipe edit --profile scenarios --harvest DIR --port 8766 --no-browser
```

`--profile` is needed (or the profile the environment names); without one the
command stops and says so. `--harvest DIR` names a folder with a harvest and
its stamps, a local copy; the command stops where the folder does not exist.
`--port N` is 8765 by default, and a free port is taken where that one is in
use. `--no-browser` only prints the address and does not open it. The server
runs until Ctrl+C.

## The page

The server binds `127.0.0.1` only, answers a request only if its `Host` is
`127.0.0.1` or `localhost` with its own port, and takes a POST only with
`Content-Type: application/json` and the header `X-Docpipe-Edit: 1`, which the
page sends and a form on another site cannot. A request it refuses is read to
its end before the connection closes, so the refusal arrives instead of a
reset connection. The page is one HTML file with plain JavaScript and one
style sheet, with no build step, and loads nothing from outside.

On the left is a tree, on the right the form of the selected node:

- the top-level questions (`_comment`, `parameter_question`, `unit_question`);
- what a document settles for all its values (`plan_fields`) and its other
  works (`works`), where the spec has them, with a button to add one it does
  not have;
- the groups, and the fields. A field opens into its own list (`vocabulary`),
  the entries a list closed per document always has beside the document's
  own (`beside`) and its coordinates, each with its own list.

The keys of a form are the ones `docpipe/extraction/spec.py` reads, each with
the comment the code writes at its field (`specs.form`); a few keys the code
leaves without a comment have a sentence of the form's own. A key the form
does not know stays in the file as it is. An edit is made in the page's copy
of the spec; nothing is written until Save.

## Check and Save

Check writes nothing. It does three things:

- runs the run's own loader (`spec.load`) over the edited spec. If the loader
  refuses it, the page shows the loader's words and the place it names, and a
  button goes to that place;
- says which questions the edit moves, by the run's own fingerprints
  (`spec.fingerprints`): one entry per key whose fingerprint differs, with a
  sentence on the pass that settles it (below);
- shows the diff against the file, and the entries whose definition differs
  from the profile's ontology snapshot.

With `--harvest` it also lists, per moved key, the documents whose stamp the
edit makes stale, asked of the run's own comparison (`runner.stale`). Without
it the page says that no documents are counted and why: no harvest folder was
given, or the folder holds no `*.stamp.json`.

Save writes the spec only if the loader takes it. An edit that takes
something away is written only after the page has listed it and it is
confirmed: a field, a coordinate, an entry of a list, a name or a spelling of
an entry, a unit, a choice of a coordinate, a group, a key of `plan_fields`,
the `works` block, one of the two questions at the top. A changed text is no
removal. A file that changed on disk since the page loaded it is not
overwritten: the page says so and offers to reload. The file is written whole
or not at all (a temporary file beside it, then put in its place).

The file is written in one fixed form: two spaces of indentation, every
character as typed, one line break at the end, in the line endings the file
already has. Both profile specs were brought into that form once, with every
fingerprint unchanged (64 keys in `kwp`, 44 in `scenarios`), so a save changes
the lines an edit changed and no others. A browser does not tell `1.0` from
`1`, so a number the page sends back unchanged is written as the file has it.
A spec with an object key that is a whole number cannot go through the page,
since a browser moves such a key to the front of its object; Check says so.

## What an edit costs the next run

The stamp of a harvested document holds one fingerprint per question, and a
run compares them one by one (see [the extraction stage](extraction.md)). So
an edit that moves no question, such as a changed `_comment`, a `kg` block, or
a text in `plan_fields`, `works` or `beside`, leaves every document current.
Where a key moved, the page names the pass that settles it:

| the key | the pass |
|---|---|
| a list that only grew: every entry still there with its name, its spellings and its meaning, and nothing else of the question changed | `--remap` maps the stored wordings onto the list without a model |
| a coordinate that is new, or whose question or an entry changed | `--top-up` asks the coordinate again (a coordinate of the frame needs `--force-stale`); `--remap` where only stored wordings need mapping |
| a new field, and the keys that belong to it alone | `--top-up-parameters` searches each stored document for it and appends its rows |
| what a field asks, the question that assigns a value to a field, or a key the spec no longer has | `--force-stale`: the documents are harvested again |
| the unit question or the units it offers | `--top-up` asks the unit of the stored values again |

The sentence on the page is the authority for a key; the table is the rule
behind it (`specs.changes`).

## Copies and removals

A field or a coordinate is created as a copy under a new key. The key has no
blank and no slash, since a stamp names a question by `<field>/<coordinate>`,
and it may not be taken. A copied field stands right after its original with
all its coordinates and lists and has no example, so the loader refuses the
spec until the copy has one of its own. A copied coordinate stands right after
its original and joins the group of the original, in every list of the group
that names the original.

A removal is made in the page's copy and written with the next confirmed
Save. What follows from it goes with it, so the spec still loads: a
coordinate that no field has any more leaves its group, a group left without
coordinates goes, and a question the `works` block asks of a removed field
leaves the block.

A new entry of a list is chosen from the profile's ontology snapshot
(`vocabulary.json`) by a search over identifier, label and alternative labels,
or typed as an entry of its own (`out:`). A spelling is typed and put right
after the entry's name, so the file gains exactly one line. Beside an entry's
own definition the page shows the snapshot's and marks the entry where they
differ, with the line the profile check prints for it (`specs.notes`).

## What the editor does not touch

The spec is the only file the editor writes through its own code, and the
write guard (`server.Files`) lets that code write only inside the profile's
folder. It reads only inside the folders of the profiles in effect, the
harvest it was given, its own page and the generated documentation. A path is
resolved first, so `..` and links cannot lead out. It commits nothing, pushes
nothing, starts no job and sends nothing over a network. It runs `git` for
the branch and for the files of the profile folder that differ from the last
commit, to show both in the header, and changes nothing with it.

After a save a button regenerates the schema and the documentation pages
(`python -m docpipe.extraction.schema <profile> --write`, then
`python scripts/build_docs.py --out docs`) and lists the files that changed.
Those two commands write the profile's `extraction_schema.json` and the pages
under `docs/`, and only on that button.

## What it does not contain yet

The prompts and the flow of the reading (which step asks what, in which
order) cannot be edited in it: the prompts stay files of the profile, the
flow stays code. The page has one tab, the spec.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/editor/__init__.py</code></summary>

docpipe.editor: `docpipe edit`, a profile's extraction spec in the browser.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/specs.py</code></summary>

specs.py: What the editor does with a profile's extraction spec.

No page and no file in here: text in, text out, so each promise the page makes
can be held to in a test without a server. The page keeps the parsed spec,
changes it and sends it back; what happens to it then is decided here.

The file is written in one fixed form (`dump`), the one `json.dumps` gives
with two spaces, in the line endings the file has. Both profile specs were
brought into that form once, so a save changes the lines an edit changed and
no others; a number the page sends back unchanged is written as the file has
it (`as_written`), because a browser does not tell `1.0` from `1`.

A spec is written only if the run's own loader takes it (`problem`,
`spec.load`). What an edit costs the next run is said with the run's own
functions and nothing else: the fingerprint of every question
(`spec.fingerprints`, in `changes`) and, where a harvest lies beside, the
documents whose stamps the edit makes stale (`runner.stale`, in `affected`).
An edit that takes something away (a field, a coordinate, an entry of a list,
a spelling) is written only after it is confirmed (`save`).

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/server.py</code></summary>

server.py: The local server of `docpipe edit` and the one file guard.

`App` answers a request as plain data (method, path, query and body in, a
status and an object out), so every promise of the endpoints can be held to
without a socket. What an endpoint says comes from `specs.py`; this module
only reads the file, asks the logic and, where the logic says so, writes.

`Files` is the one place the editor touches a file: it may write only inside
the profile's own folder and read only inside the folders of the profiles in
effect, the harvest it was given, the page itself and the generated
documentation. A path is resolved first, so `..` and links cannot lead out.

The HTTP layer binds 127.0.0.1 only, answers only a `Host` it knows (a page
of another site cannot reach the server by a name of its own) and takes a
POST only with the header the page sends (a form on another site cannot send
it). A request it answers without having read it to the end, a refusal, is
read off before the connection closes, so that the answer arrives. The
standard library is all this needs.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
