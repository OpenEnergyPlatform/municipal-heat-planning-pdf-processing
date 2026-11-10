# Editing a profile in the browser

## What it is for

A profile's `extraction_spec.json` holds the questions a harvest asks, the
closed lists the answers are chosen from, the texts a model is shown about a
document and the examples. It is a long file, and one line of it can make a
stored harvest stale. A profile also holds its prompts, the files a model is
told its task in, and the sentences its stages say to the model outside them.
`docpipe edit` shows these as a page in the browser with three tabs. The Spec tab
shows the spec, one form per question, and says what an edit costs the next run
before it is written. The Prompts tab edits the prompt files and the sentence
files of the profile; with a harvest folder it also shows what an edit does to
the requests recorded there, and it can send a few of them once more. The Flow
tab draws the steps a document is read in and edits the numbers that bound them,
which stand in the profile's `flow.json`. The order of the steps and what a step
does is code and is not in the page.

```
docpipe edit --profile kwp
docpipe edit --profile scenarios --harvest DIR --port 8766 --no-browser
```

`--profile` is needed (or the profile the environment names); without one the
command stops and says so. `--harvest DIR` names a folder with a harvest, its
stamps and its traces, a local copy; the command stops where the folder does not
exist.
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

The header has three tabs, **Spec**, **Prompts** and **Flow**, marks a tab that
holds edits not yet saved and says whether there are any. The rest of this section is the
Spec tab. On the left is a tree, on the right the form of the selected node:

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
an edit that moves no question, such as a changed `_comment`, a `kg` block, a
text in `plan_fields`, `works` or `beside`, or the key `of` of a plan field that
is a year (it is in no fingerprint), leaves every document current.
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

## Prompts

The second tab edits the prompts and the sentences of the profile. It has three
columns: a list on the left, the editor of the selected file in the middle and
the recorded requests on the right.

The list names every prompt the profile runs with, by stage and name
(`prompts.listing`): the files of its own under `prompts/<stage>/<name>.md` and
those it takes from the profile it extends, each marked with the profile it
belongs to. Below the prompts stand the sentence files, one entry per module
(see Sentences). A box filters the list.

A file is shown cut into three kinds of piece (`prompts.segments`):

- the settings on top, between the two `---` lines (`temperature`,
  `max_tokens`), as two inputs;
- what every request of its kind is told;
- each part only some requests are told, opened by a marker line:
  `<!-- with: headings -->` for a part sent with a request whose message
  carries the field `headings`, `<!-- follow-up: x -->` for the words of a
  follow-up message that carries `x`. The marker line itself is not editable.

The cut loses nothing. `prompts.joined` puts the pieces back character for
character, and the page builds the text it sends back by the same
concatenation, with no trimming and no reordering. It adds one thing: where a
box ends in the middle of a line and a marker follows, it ends that line, since
the run reads a marker only on a line of its own. A file that names a template
of the core is edited as one text, and the text that is sent, made from the file
and the template, stands beneath it and cannot be edited.

**Check** writes nothing. It refuses a text on which a run would fail, or with
which it would send what was not meant (`prompts.problem`), measured against
the file a run loads today, in these cases and no others:

- the settings on top cannot be read, or are not a mapping of settings;
- the loader (`prompts.made`) refuses the text for another reason, for a parts
  file that names a template, for instance one the template does not take; the
  page shows the loader's words;
- `temperature` is not a number, or `max_tokens` is not a whole number or is
  below 1 (a yes or no is no number);
- a part is marked twice for the same field (`thread.cut`);
- the file on disk has a follow-up part for a field and the text has none: the
  code sends a follow-up with it and would have no words for it;
- the text has a `{{name}}` the file on disk does not have, or the file has one
  that the text lost: the code fills exactly the names that are there;
- the text adds something written as a marker that the run would not read as
  one (`thread.MARK`): inside a line, with words after it, or spelled another
  way. The run would take it for text and send it, with the part it was meant
  to open, in every request that is told the words before it. What the file on
  disk has already is not held against the text.

Where the text is taken, Check shows the diff of the file, the diff by sentence
of the text that is sent (`sentences.unified`), the size of that text in
characters before and after, and the settings where they changed. It also says
that a changed prompt makes no harvest stale: a stamp rests on the questions of
the spec alone (`prompts.NO_STALE`).

**Save** writes the text as typed, in the line endings the file on disk has,
whole or not at all, and only where Check takes the text and it differs from the
file. A prompt the profile takes from the profile it extends is saved as a file
of the profile's own; the page names the new file before the save, and the other
profile's file is never touched. A file that changed on disk since the page
loaded it, the file a run loads today, is not overwritten: the page says so and
offers to reload.

After a save the page runs two commands (`/api/review`) in the repository root
and shows the output of each: `python -m docpipe preflight --profile NAME`, the
profile check, and `python scripts/render_prompts.py --profile NAME --before
HEAD`, the before and after of every prompt against the last commit, with the
text of the `summary.md` the script writes. Each has ten minutes. The same two
run after a save of the sentences. The script writes one folder per run under
`docpipe-prompt-review` in the system's folder for temporary files and names it
in its output; the editor leaves these folders where they are.

## Recorded requests

With `--harvest`, the traces in the folder are read: one file
`<name>.trace.jsonl.gz` per document (a plain `<name>.trace.jsonl` too; where a
name has both, the compressed one). `requests.Traces` reads each trace once per
state of its file, which takes some seconds for a large trace, and
`requests.requests_of` turns it into one request per `*_ask` event with what was
sent, what came back and what became of it (taken, asked again, no answer,
unreadable). Without `--harvest`, or where the folder holds no trace, the column
says so and has nothing to show.

For the prompt that is selected, the list holds the requests it has a say in
(`prompts.concerns`): the requests of its own kind, and for the follow-up prompt
the requests asked again. A request asked again goes under the prompt of
the request it follows, so it is listed under that prompt too. The list is
filtered by field, by the fields a message carries (which is how the requests a
part is told to are found) and by a text anywhere in the instruction, the
message or the answer, and is paged by 100.

A chosen request is shown as a chat: the instruction, the message with its
numbered lines, the addresses the answer names, the answer and what became of
it. The instruction is not the recorded one but is made again from the text being
edited, unsaved text included, and the sentences the edit changes are marked,
with those it removed listed beneath. A switch shows the instruction as it was
sent. It is made by the two functions every request of the harvest passes
(`runner.request_prompt`, which gives what every request is told and the part of
each field the message carries, and `runner.system_text`, which writes the
example reply in). The editor has no rule of its own for this.

Above the chat stand the other requests of the same value
(`requests.chain_of`): the find of its field and passage, its readings and
follow-ups, and the list entries asked for its words, each a link to that
request. A request that reads no value, a detail of a work for instance, has
none: what it shares with the other such requests of its field is only that
none of them names a value.

A record does not carry the example reply the run wrote into the instruction, so
the editor reads it back out of the recorded instruction (`prompts._places`):

- exactly, where the file on disk, with its places filled with one line each,
  gives the recorded instruction character for character;
- else from the lines of the record that are one JSON object as the run writes
  an example, taken in order, where there are as many as the prompt has places
  for;
- else there is no preview. The page says that the prompt was worded differently
  when the request was sent and the record does not show as many example replies
  as the prompt has places, and shows the request as it was sent.

The page states two things about every request. The first is whether the files
on disk give the record character for character (`same_as_recorded`); where they
do not, the request was sent with other words of the prompt, and the page says
that its example is taken from the record. The second is whether an edit reaches
the request at all (`changed`): a part is told only to a request whose message
carries its field, so an edit in a part changes nothing in the other requests,
and the page says "Your change does not reach this request" for them.

Which requests can be put together again:

- those of the kinds `find`, `docfield`, `coord`, `list`, `names`, `search`,
  `check`, `work` and `phrase`, whose prompt is cut at its markers
  (`prompts.CUT`);
- `transcribe`, whose prompt is sent whole (`prompts.WHOLE`);
- a request asked again (`follow`) of any of these: its instruction is that
  of the request it follows, and the words after its payload are those of the
  follow-up prompt (`extraction/follow`).

A request of another kind, a request whose record shows no payload in its first
message, and a request for which the loader refuses the edited text is shown as
it was sent, with the reason. The prompts of the other stages (refinement,
visuals, preprocessing, the answer app, the graph) have no recorded requests, so
they have no preview.

## Try

A click on **Try** sends recorded requests once more, with the instruction made
from the text being edited, to see what a model answers (`trying.once`). What is
sent is the recorded request: the same message, the same reply form
(`response_format`) and the settings of the prompt, `temperature` and
`max_tokens`, with the edited instruction in place of the recorded one, and for a
request asked again the edited follow-up words. A try writes nothing.

The model is the one the installation names (`trying.settings`):

- `EDIT_TRY_BASE_URL`, with `EDIT_TRY_API_KEY` and `EDIT_TRY_MODEL` (`LLM_MODEL`
  where that one is not set);
- else the run's text model, where the environment names one (`LLM_BASE_URL`,
  `LLM_API_KEY`, `LLM_MODEL`);
- else nothing is sent, the buttons are disabled and the page says why.

The page is given the model's name and its host, never the address with its path
or the key.

A request is one call and is never repeated: the client is made with no retries,
and a failure of the server or the wire is the result. A click sends 3 requests
at most (`trying.LIMIT`, owner decision 2026-11-10), either the chosen one or the
first listed, and each button names the number it sends. The server refuses a
call that names none, more than three, or no model. Nothing is sent without a
click. A request whose instruction cannot be put together is not sent and says
why.

For each request the page shows the recorded answer and the new one side by
side, with the time and the tokens, and says:

- whether the new answer is the recorded one: the two objects are equal where
  both are one JSON object, else the two texts are;
- whether it is in the reply's form: read as the run reads a reply (exactly one
  JSON object, `runner._loads_object`) and holding every key of the recorded
  reply form (`runner._lacking`). Where it is not, the page names the fault in
  the run's own words (`cut_off`, `syntax`, `missing_key` and so on). An
  endpoint that does not hold a reply to its form answers out of form, and the
  page says so;
- for each address the answer names, whether it holds against the lines the
  request showed, by the run's own check (`addressed.resolve`): it names a line
  the request showed, and its words stand in what it names. An address that does
  not hold says which of the two failed. An answer of 0 names no address and
  holds nothing.

One approximation is made, and the docstring of `trying.py` names it: the lines
are those of the recorded message, so a line's cells are taken from its text, a
row of a table as the run cuts one, any other line where "|" divides it in two
or more.

Above the results one line counts them: how many requests were named, sent,
failed, answered the same and differently, answered out of form, and how many
had addresses that all hold or that do not.

## Sentences

A stage says more to the model than its prompts hold: why an answer was not
taken, what was wrong with a reply that could not be read, the heading over a
task. These sentences are files of the profile, `prompts/<module>/phrases.json`
for the modules `extraction`, `inference` and `reading` (see [the parts every
stage uses](core.md)). The list has one entry per module.

A module's page shows every sentence the profile runs with. The profile's own
file holds only the sentences it words itself, and the page edits that file; a
sentence the profile takes from the profile it extends is shown with the name of
that profile. For each sentence the page shows its note where the stage has one
(`NOTES`), whether the stage cannot run without it (`REQUIRED`), and the names
the code fills in braces, which are the names the wordings on disk use. An own
sentence is edited in place, and where the profile it extends words it too, a
button takes the inherited wording again, which deletes the sentence from the
own file. An inherited sentence is read only until a button words it for this
profile, which adds it at the end of the file with the inherited text.

**Check** (`phrases.judge`, with `phrases._problem` for each sentence) refuses a
table in these cases:

- the table is not one object, a sentence's name to its words;
- a sentence is changed whose name no wording on disk has, in this profile or in
  those it extends: no stage reads a sentence of that name;
- a changed sentence is not what it was: a text where there was a list, a list
  where there was a text, a list of another length, or something in it that is
  no text;
- a changed sentence is no template the code can fill. A sentence is a template
  for `str.format`, and the code fills the names the wordings on disk use. Where
  some wording has braces, the changed text may use those names and no other,
  and a brace that stands for itself has to be doubled. Where no wording on disk
  has a brace, a changed text has none either, since whether such a sentence
  goes through `str.format` cannot be seen from the editor;
- a sentence the stage cannot run without (`REQUIRED`) would be left with no
  wording, its own and the one it inherits both gone.

A sentence that is not changed is not judged again. Check lists what changed
(changed, added or removed, each with the wording before and after, the
inherited wording standing for the one the profile falls back to) and the diff of
the file, and says that a changed sentence makes no harvest stale
(`phrases.NO_STALE`).

**Save** writes the file as one JSON object, two spaces of indentation, every
character as typed, the keys in the order the page holds them, one line break at
the end, in the line endings the file has. Taking an own sentence away is written
only after the page has listed it, with the wording the profile falls back to,
and it is confirmed. A profile with no file for the module gets one, and the page
names it. A file that changed or appeared on disk since the page loaded it is
not overwritten.

With a trace chosen, a button lists where the recorded requests show a sentence
(`phrases.shown_in`): the sentence as it is worded today is searched in the
messages of the requests, with the names in its braces taken as what the record
shows there, and each hit is given as the sentence stood and as the edited
wording would say it. The page gives how many requests were searched and how
many show the sentence, and lists the first twenty. Where the new wording uses a
name the record does not show, the hit says so and has no new wording; a
sentence with no words of its own has nothing to search for, and the page says
that. What the trace showed belongs to the wording it was looked up with: once
the sentence reads differently, the list is hidden until the button is pressed
again.

## Flow

A document is read in steps: it is cut into numbered lines and pieces, the
figures are written off, fields are asked per piece and per document, each
coordinate of each value is asked on its own and searched for where it is open,
and what the checked rows leave open is computed. The steps and the numbers that
bound them stand in one file, `flow.json` (`extraction.flow`). The default
profile's file is the whole flow: `numbers` and `steps`. A profile that extends
it may have a `flow.json` of its own that holds `numbers` only, and only the ones
it sets differently; it is laid over the inherited file number by number, and a
file of a profile that writes steps is refused. The steps describe the flow; the
order they are run in is still the code's. The loader is strict: every request
the code sends stands in the `ask` of at least one step, a step asks no request
the code does not send, every number bounds a step, and an
unknown key, a key written twice, a value that is no whole number or lies below
the number's least is refused by name.

The Flow tab draws the steps top to bottom, one box per request, with what the
step does, for what it is asked, when, and a frame around the steps asked per
coordinate. The bound of a step is a sentence with its numbers as inputs. A step
links to its prompt in the Prompts tab, and shows the switches of the spec that
belong to it (the fields the document has once, the coordinates only the value's
own passage says and so on), each entry a link into the Spec tab. A step that no
run of the profile takes is drawn as off, with the reason: no profile of the
line writes its prompt, or the spec has nothing for it.

The flow has twelve numbers, each a whole number, and each says what it counts:

| the number | what it counts |
|---|---|
| `piece_lines` | lines of a piece a document is read in; a table's head is shown with each of its pieces |
| `title_page_lines` | lines of the document's first page that a request shows as its title page |
| `headings` | headings a request shows up to a value's place, its own last |
| `list_meanings` | entries up to which a list is shown with what each entry means; a longer list shows its names only |
| `search_pieces` | pieces a search shows for an open coordinate or a field the document has once |
| `search_tables`, `search_figures`, `search_text` | the share of a search's pieces that are the best pieces of tables, of figures and of text, taken first; the three are scaled to the pieces of the search, and the rest are the best of any kind |
| `search_per_request` | pieces one request of a search shows |
| `listed_field_factor` | times the pieces of a search that a field the document has once reads where its values come from a list |
| `follow_ups` | times a request whose answer did not hold is asked again, each time with the answer and why it did not hold; 0 asks none |
| `replies` | replies out of their form a request takes before it is left unanswered |

For each number the tab says whether the profile sets it itself or inherits it
and from which profile, and what a run started here would read with and why:
six numbers have a setting, four settings in all (`EXTRACT_SEARCH_PIECES`,
`EXTRACT_SEARCH_SHARES` for the three shares, `EXTRACT_SEARCH_CHUNKS`,
`EXTRACT_MAX_RETRIES`), and where a setting is set it wins over both files,
which the tab says. Editing a number
marks the tab as unsaved.

**Check** writes nothing. It refuses a number the flow does not take with the
loader's words, lists what changed, says what a save would do to the file
(created, changed, removed or unchanged), shows the diff, and says that a changed
flow makes no harvest stale: a stamp names, for each pass that read the
document, the numbers it read with, and compares none of them.

**Save** writes only where every number holds and the file is as the page loaded
it; otherwise the page says the file changed on disk and offers to reload. One
refused number means that nothing of the edit is written. A profile that extends
another gets only the numbers that differ from what it inherits: a number set
back to the inherited value leaves the file, and a file that would hold no number
is removed (`Files.remove`, inside the profile's own folder only). The default
profile's own file is the whole flow, so a save there changes its number lines
and keeps its steps. The file keeps its line endings; a new file is written with
plain ones.

With `--harvest` the tab says, beside the numbers, what the traces of that
harvest measured, recounted as a number is typed (`measured.says`):

- how many searches for an open coordinate ended with an answer that names a
  place and how many without one, after how many shown pieces of the budget
  those answers came (the least, the most and the middle one), and how many came
  after more than the typed budget; how many requests the searches sent;
- for the fields the document has once, how many requests found something and
  how many of them only after more than the typed budget of shown pieces (for a
  field with a list, the budget times `listed_field_factor`);
- how many answers were asked again, per kind of request;
- how many replies were read at the first, second and later attempt, and how many
  could not be read, by cause;
- how many lists were longer than the typed number of entries.

Two limits belong to these counts. A trace does not record whether an answer
held, so the tab counts an answer that names a place, and not a value read. And
"came after more than N" estimates what a smaller budget would have cost, since
a smaller budget also changes which pieces are picked. A trace written before a
search noted which of its pieces count toward its budget (`shows`: `near` for the
pieces beside the value, `found` for those of the budget, `fetched` for those the
model fetched itself, which count toward no budget) is counted over all its
pieces, and the tab says so. The traces are read by `measured.light`, which does
not put the requests back together, and the counts of a trace are kept per state
of its file. Without `--harvest`, or with a folder that holds no trace, the tab
says that and counts nothing.

Below the diagram the tab lists the year rules of the spec as notes (the key
`of` of a plan field that is a year; see [the extraction stage](extraction.md)),
each a link to the plan field in the Spec tab, and the other settings of an
extraction run, read only, each with its value and where it comes from as
`docpipe config` lists them. The value of a secret setting (a key, a token) is
never sent to the page, which shows only whether one is set, and what an address
carries before its host (a user, a password) is replaced by `***@`.

The Spec tab's form of a plan field that is a year has the key `of`: a coordinate
of a group's pair and an entry of its list.

## What the editor does not touch

The editor writes four kinds of file through its own code: the spec, the
prompt files, the sentence files and the profile's `flow.json`, and the write
guard (`server.Files`) lets that code write, and remove the flow file, only
inside the profile's folder. It reads only inside the
folders of the profiles in effect, the harvest it was given, its own page, the
generated documentation and the folder the before and after comparison of the
prompts writes into. A path is resolved first, so `..` and links cannot lead out.
A trace is read by the run's own trace reader, after the guard has checked its
path (`Files.checked`). It commits nothing, pushes nothing and starts no job. It
runs `git` for the branch and for the files of the profile folder that differ
from the last commit, to show both in the header, and changes nothing with it.

It sends over a network in exactly one case: a Try, to the endpoint the
installation names, one request for each request named in the click and at most
three (see Try). The page itself is served on `127.0.0.1` and talks to nothing
else, and no other action of the editor sends a request to a model or to any
other host.

After a spec save a button regenerates the schema and the documentation pages
(`python -m docpipe.extraction.schema <profile> --write`, then
`python scripts/build_docs.py --out docs`) and lists the files that changed.
Those two commands write the profile's `extraction_schema.json` and the pages
under `docs/`, and only on that button. After a save of a prompt or of the
sentences the page runs the profile check and the before and after comparison
(see Prompts); the
comparison writes into a folder outside the repository, and the editor reads
its summary from there.

## What it does not contain yet

The order of the steps of the reading and what a step does cannot be edited in
it: they stay code. The prompts, the sentences the stages say outside them, the
spec and the numbers of the flow are in the page.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/editor/__init__.py</code></summary>

docpipe.editor: `docpipe edit`, a profile's extraction spec, prompts,
sentences and the numbers of its flow in the browser.

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
<summary><code>docpipe/editor/prompts.py</code></summary>

prompts.py: What the editor does with a profile's prompts.

It lists them with the profile each file belongs to, cuts a file into the
pieces a person edits (the settings on top, what every request is told, each
part only some requests are told), checks a text before it is written, and
makes the instruction of a recorded request from a text that is not written
yet, so that a changed sentence is seen in the requests that would carry it.

Nothing here knows how a prompt is read or put together: that is the
loader's (`docpipe.prompts.made`), the cut at the markers is the run's
(`extraction.thread.cut`), and the instruction of a request is made by the
two functions every request of the harvest passes (`runner.request_prompt`,
`runner.system_text`). The one thing a record does not carry is the example
reply the run wrote into the instruction; it is read back out of the
recorded instruction (`_places`).

A text is refused where a run would fail on it: a front matter the loader
cannot read, a parts file its template does not take, a part marked twice, a
follow-up part the file had and lost, and a `{{name}}` the file on disk does
not have or one it has that is gone, since the code fills exactly the names
that are there. And where a run would send what was not meant: a marker of a
part that the text adds and the run would take for text, because it does not
stand on a line of its own.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/phrases.py</code></summary>

phrases.py: What the editor does with the sentences a stage says outside its
prompts (`docpipe/phrases.py`: `prompts/<module>/phrases.json`).

It shows, per module, every sentence the profile runs with: its own wording
or the one it takes from the profile it extends. The page edits the
profile's own table; a sentence it does not word itself is not in it. A
table is checked before it is written:

- a name no stage reads is refused, and a sentence a stage cannot run
  without may not go missing (`REQUIRED` of the stage);
- a sentence stays what it is, a text or a list of as many texts;
- a sentence is a template for `str.format`, and the code fills the names
  the wordings on disk use. So a changed sentence may use those names and no
  other, and where no wording of a sentence has a brace, a changed one has
  none either: whether such a sentence is run through `str.format` is not
  to be seen from here.

A sentence is seen in recorded requests where they show it: a follow-up
names why an answer did not hold in these sentences. `shown_in` finds them
and says each as the changed wording would.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/trying.py</code></summary>

trying.py: A recorded request sent once more with a changed prompt, and what
the new answer is worth.

"Try" takes requests of a trace, makes each one's instruction from the text
being edited (`prompts.preview`) and sends it as it was recorded otherwise:
the same message, reply form and settings, to the model the installation
names for it. One request is one call, never repeated, and a click sends
`LIMIT` at most (owner decision 2026-11-10: "nicht mit 20, max 3"). Nothing
is sent by anything else in the editor.

The new answer is read as the run reads one (`runner._loads_object`,
`runner._lacking`), and each address it names is held against the lines the
request showed with the run's own check (`addressed.resolve`). The lines
are those of the recorded message, so a line's cells are taken from its
text: a row of a table as the run cuts one, any other line where "|"
divides it in two or more.

Where the model is: EDIT_TRY_BASE_URL, EDIT_TRY_API_KEY and EDIT_TRY_MODEL;
without the first, the text model of the run (LLM_BASE_URL, LLM_API_KEY,
LLM_MODEL) where the environment names one. With neither, nothing is sent
and the reason is said.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/requests.py</code></summary>

requests.py: The model requests of an extraction trace, read from its events.

One dict per `*_ask` event with what was sent, what came back and what became
of it (taken, asked again, no answer, unreadable); the chain of one value; the
filter that picks requests; and `Traces`, which reads each trace of a harvest
folder once per state of its file. No page and no server in here. Moved out of
`scripts/chat_view.py` so that the script and the editor share one version.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/sentences.py</code></summary>

sentences.py: A text cut into sentences and the diff of two such texts.

A prompt is compared by sentence, one sentence per line, so that a changed
word shows as one changed line and not as a changed paragraph. The cut only
decides what one line of the diff is; the same rule runs on both sides, so a
wrong cut shows as two lines on each and never hides a change.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/server.py</code></summary>

server.py: The local server of `docpipe edit` and the one file guard.

`App` answers a request as plain data (method, path, query and body in, a
status and an object out), so every promise of the endpoints can be held to
without a socket. What an endpoint says comes from the logic beside it
(`specs.py`, `prompts.py`, `phrases.py`, `flow.py`, `measured.py`); this
module only reads the file, asks the logic and, where the logic says so,
writes.

`Files` is the one place the editor touches a file: it may write, and take a
file away, only inside the profile's own folder and read only inside the
folders of the profiles in
effect, the harvest it was given, the page itself, the generated
documentation and the folder the prompt review writes into
(`<temp>/docpipe-prompt-review`). A path is resolved first, so `..` and links
cannot lead out. A trace is read by the run's own reader after the guard has
checked its path (`Files.checked`).

The HTTP layer binds 127.0.0.1 only, answers only a `Host` it knows (a page
of another site cannot reach the server by a name of its own) and takes a
POST only with the header the page sends (a form on another site cannot send
it). A request it answers without having read it to the end, a refusal, is
read off before the connection closes, so that the answer arrives. The
standard library is all this needs.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
