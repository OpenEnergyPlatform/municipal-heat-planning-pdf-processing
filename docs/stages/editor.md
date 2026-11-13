# Editing a profile in the browser

## What it is for

A profile's `extraction_spec.json` holds the questions a harvest asks, the
closed lists the answers are chosen from, the texts a model is shown about a
document and the examples. It is a long file, and one line of it can make a
stored harvest stale. A profile also holds its prompts, the files a model is
told its task in, and the sentences its stages say to the model outside them.
`docpipe edit` shows these as a page in the browser with five tabs and a Rules
drawer. The Spec tab shows the spec, one form per question, and says what an
edit costs the next run before it is written. The Prompts tab edits the prompt
files and the sentence files of the profile; with a harvest folder it also shows
what an edit does to the requests recorded there, and it can send a few of them
once more. The Flow tab draws how a document is read, as steps, loops, rounds
and branchings, edits that flow, the numbers that bound it and the rules each
step reads, which stand in the profile's `flow.json`, and runs it on a
document as a dry run with placeholder answers. It also draws the flows of the
follow-up passes. What a box does is code and is not in the page. The Sources
tab edits `sources.json`, the Graph tab `graph.json`, and the Rules drawer,
which the Rules button of a tab opens, the rules of that tab.

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

The profile is switched in the head of the page. A process runs on one
profile, because a stage binds part of what its profile says when it is
imported (`profile.resolve_profile` refuses to name another one after that).
So the command runs the server as a process of its own (`start.py`): a switch
writes the other profile and the server's port into a note in a temporary
folder of the command's own and ends the server once it has answered, and the
command starts the server again with that profile at the same port, without
opening the page; the page waits for it and loads itself anew. Unsaved edits
are asked about first, as when leaving the page. The harvest of `--harvest`
belongs to the profile the command was started with: it comes back with that
profile, and any other profile runs without one. Ctrl+C ends the command and
the server, and a server whose command is gone, also a command that was
killed, ends by itself, because its standard input is a pipe the command
holds.

## The page

The server binds `127.0.0.1` only, answers a request only if its `Host` is
`127.0.0.1` or `localhost` with its own port, and takes a POST only with
`Content-Type: application/json` and the header `X-Docpipe-Edit: 1`, which the
page sends and a form on another site cannot. A request it refuses is read to
its end before the connection closes, so the refusal arrives instead of a
reset connection. The page loads nothing from outside and uses the system's
fonts. The server serves only `/` (`index.html`), `/forms.js` and the files
`/assets/<name>.js` and `/assets/<name>.css` with a plain name.

The page is built from the sources in `docpipe/editor/ui/` (React, TypeScript,
Mantine, React Flow and Tabler icons, built by Vite), and the built page is
committed in `docpipe/editor/web/`: `index.html`, `assets/index-<hash>.js` and
`.css`, `forms.js` (the form logic the page and the node tests share) and
`third-party-licenses.md` (name, version, licence and licence text of every
library inside the built page, written by the build). Running `docpipe edit`
needs no Node. Node is needed only to change the page: in `docpipe/editor/ui`,
`npm ci`, then `npm run build` (a type check, then Vite writes into `web/` and
replaces `web/assets/` whole). `npm run dev` serves the sources and passes
`/api` and `/forms.js` to a running `docpipe edit` (`DOCPIPE_EDIT_URL`, default
`http://127.0.0.1:8765`).

The head shows the profile, as a choice among every profile the installation
finds (`docpipe profiles`; a server not started by `docpipe edit` shows only
its own), and the branch, the five tabs **Spec**, **Prompts**,
**Flow**, **Sources** and **Graph** as pills with a dot on a tab that holds
edits not yet saved, a badge that says **Unsaved edits** or **All saved**, a
**Rules** button on the tabs that have rules, which opens the rules of the tab
in a drawer on the right (with Check, Save and Discard there), and a switch
between light and dark colours and one between English and German, which the
browser remembers. Ctrl+S saves and Ctrl+Enter checks the tab, or the open
drawer. Leaving the page with unsaved edits asks first. A tab is loaded the
first time it is opened and kept while the page is open.

The page speaks English or German. The switch in the head picks the language;
the browser remembers it (`docpipe-edit-language` in `localStorage`) and, the
first time, follows its own. Every text the page writes goes through `t()` or
`tn()` (for counts) with an English literal, and its German stands in
`docpipe/editor/ui/src/i18n/de.json`, keyed by that English text. Every
explanation the server sends (what a step does, the help of a rule or of a key
of the spec, the details of the sources, what the request logs measured) goes
through `tr()`: the exact entry, or one of the server's own templates in
`i18n/templates.json`, English texts with `{names}` the server fills in. A
reason the check of a flow gives (its problems, the reasons of a condition, the
dry run's refusal, the lines of what changed) goes through `trCheck()`: as
`tr()`, but what the server filled in (a step's label, the name of a form, a
reason inside the reason) is made German the same way, and where no template
fits, "where: what", reasons joined with "; " and words joined with " or " are
made German part by part; what has no German, such as a step's id, stays. The
numbers the server filled in are written the page's way (German "9.206", "4,2"),
and a server text shown as an element goes through `rich()`, so its `code` shows
as code. What comes from a source is never translated: labels and definitions of
the ontology, field names and texts of the spec, prompts, text of documents,
file names and code names. `tests/test_editor_i18n.py` holds the promise that
every text the page shows has a German version, each part with a case that
breaks it. The page says step, loop, round and branching, chunk, dimension, line
number and request log where the flow file, the code and this page say box,
frame, piece, coordinate, address and trace (see the glossary).

The rest of this section is the Spec tab. On the left is a tree, on the right
the form of the selected node:

- the top-level questions (`_comment`, `parameter_question`, `unit_question`);
- the fields of the whole document (`plan_fields`) and its other
  works (`works`), where the spec has them, with a button to add one it does
  not have;
- the groups, and the fields. A field opens into its own list (`vocabulary`),
  the entries a list closed per document always has beside the document's
  own (`beside`) and its dimensions (`coordinates`), each with its own list.

The keys of a form are the ones `docpipe/extraction/spec.py` reads (`specs.form`),
each with what the page says of it, written for someone who edits the spec,
not for the code (`specs.HELP`); the lists of the fields of the whole document
and of the works have a sentence above them (`specs.ABOUT`). A key the form
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
an edit that moves no question, such as a changed `_comment`, a text in `plan_fields`, `works` or `beside`, or the key `of` of a plan field that
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

## Forms, not JSON

No value of the Spec, Rules, Graph or Flow tab is typed as JSON; JSON stands only in
the files the page writes. The Flow tab draws its file (`docpipe/editor/ui/src/flow/`, see Flow);
for the other three the conversion between a value and its form is
`web/forms.js`, which runs in the page and in node. A form given a value and
no edit gives the identical value back, key order included, so the file is
written back byte for byte; an edit through one field changes only the key
that field shows; a key the form does not know is kept where it stood and shown
greyed. A value that does not fit its form is kept as it is. A range with one bound and
the other empty stays editable in its form (the server still refuses it: two
whole numbers or empty). Every value a form writes fits the same form again.
`tests/test_editor_forms.py` holds all of these for both profiles' real files.

- The Spec tab has no form for what a field becomes in the graph: that is an
  arrow of the drawing in the Graph tab, and a spec that holds a `kg` block is
  refused by Check with a pointer to the drawing. The settings of a brick in
  the Graph tab are forms of the kinds the brick declares (a text, a list of
  texts, a number, a flag, a class, a rule, a table, labels, fields or prose),
  a property or class a text field that offers those of the shapes.
- `derive` is "derived from" a select of the field's coordinates and "value" a
  select of the entries of the coordinate's own list.
- `example` is the source as plain text, the defaults as one row of fields and
  the rows as a table with the columns value, quote and the coordinates (and
  their wordings) some row uses; a select adds a column.
- `of` of a plan field is always two selects, the coordinate and its entry.
- The address of a box in the Graph tab is a folder and a key, and the fields
  (or `@name`, `@key`) its name is made of, with up and down to change the
  order.

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
(`runner.request_prompt`, which gives what every request is told, the part of
each field the message carries and the parts its recorded reply form offers,
such as `more` where the answer may fetch, and `runner.system_text`, which
writes the example reply in). The editor has no rule of its own for this.

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

A document is read by a drawing: boxes in the order they stand, frames that
repeat boxes for each thing of the document, rounds, and ways chosen by a
condition. The run does exactly this drawing (`extraction.engine`); there is no
second order in the code. The drawing and the numbers that bound it stand in
one file, `flow.json` (`extraction.flow`); a step or a frame may also carry
`rules`, values of its own for the rules it reads (see "Rules at a step"):

```
{"numbers": {"piece_lines": 8, ...},
 "flow": [{"id": "document", "box": "document"}, ..., {"id": "write", "box": "write"}]}
```

The default profile's file is the whole flow: every number and the drawing. A
profile that extends it writes only the numbers that differ, laid over the
inherited ones number by number, and the drawing only where it differs; a
drawing of its own is then the whole drawing. The loader is strict: an unknown
key, a key written twice, a number that is no whole number or lies below its
least, and a drawing the run could not do (below) are refused by name.

### The library

A box is one kind of the library (`extraction.blocks`). Each kind has a name,
a group (start, prepare, order, questions, check, remember, state, logic, end),
the variables it takes and gives (shown at the box and on its arrows), its
settings with their defaults, and an explanation for someone who did not write
it: what goes in, what comes out, what for, an example and how it differs from a
similar step (owner decision 2026-11-12). Every step that asks the model is
the box "Ask the model" with a preset (`{"box": "ask", "preset": NAME}`;
`extraction.presets`, owner decision 2026-11-12 evening), and the library lists
the presets beside the other kinds: write out the figures, order the chunks for
each field, ask a field once for the whole document, ask for the values in a
chunk, ask a dimension at the value's line or over the search hits, write a
search sentence, check that a find is about the value, choose a list entry and
compute shares and sums; the second reading and the example of a field are
presets of the library of the passes. A step has five parts, each shown as a
setting that "as its preset" takes back to the preset's: the request (the kind
it is in the log, which decides the rules and numbers it reads), the prompt, the
inputs, the reply (the form of the answer, `extraction.forms`) and where the
answer goes (`extraction.targets`: a variable, values of a field, a dimension of
a value, a sentence and so on). Switching a part back to the kind its preset has
(a prompt of the profile, a form the reading knows, the preset's target) takes
it back to the preset's as well. How an input is shown is a choice of
`extraction.shows`. The page offers the boxes and presets of the core and those
of the open profile (`profiles/<name>/blocks.py`: `PRESETS` and `TARGETS`). The
library is a searchable dialog: the "+" on an arrow opens it and puts the
picked box or frame there. A right click on a box or frame opens a menu: Move
up, Move down, Duplicate, Put a box after it, Wrap in Round, If / else or For
each, Switch off or on, Delete. Shift or Ctrl click chooses several steps that
stand one after another, so they can be wrapped together.

Only the writing of the harvest is fixed, once at the end; every other box can
be removed, and switched off (`"off": true`) where its kind allows it. A box that
is off is not there for any check of the drawing; a step that takes what no step
before it gives is refused with that reason.
A box that asks a model shows the fixed checks that hold its answers (the quote
is a line the request showed, the answer stands in its quote, a quote names a
place, an answer to a list is one of its entries) and cannot lose them.
A target that names the forms it reads takes an answer in one of them only: a
step whose answer goes there in another form, named or of its own, is refused,
since the target could read none of its answers (owner decision 2026-11-12
evening); a variable names none and takes any.
A new step needs no code: "Ask the model" takes a prompt of the profile or a
text of its own (`{{key}}` writes an input into it), the inputs it shows, the
form of its answer as a JSON schema, drawn in a window with jsonjoy-builder or
written as JSON, and where the answer goes (a variable, for the item or the whole
document, or values of a field); the model may be allowed to fetch what a line
points to. Search, order by a text, set a variable, keep what a condition holds
for, join lists, a step in Python and a loop over any list stand beside it, and a
condition row may be about any variable. A step with code of its own is a
target of a profile's `blocks.py` (`TARGETS`), named by a preset of the profile.

The catalogue search is a box of its own (`catalogue`) with settings of its
own; it stands after the calculation, at the end, and where it is switched off
nothing is looked up. A box keeps its settings under `set`. A setting that takes a number of the flow
takes the named number, unless the box has an own value for it, "only here"
(`own`): the own value wins in that box only, and a setting of the run wins over
the named number, never over an own value. A box that asks has a prompt, and the
card shows the switches of the spec that belong to it, each entry a link into
the Spec tab. A box that no run of the profile takes is drawn as such, with the
reason: the profile writes no prompt for it, or the spec has nothing for it.

### Rules at a step

Every value of the reading is a rule (see [the parts every stage uses](core.md)),
and a step or a frame may set its own value for each rule it reads, under
`rules` in `flow.json`; the rules of the graph file count too. The card of a
step offers every rule the step reads, each with its value, a switch "only
here" that gives the step a value of its own, where the value in effect comes
from (the step, a frame around it, the setting of the start, or the rules file
and which profile's) and a link to the rule's own tab. The value of the step
wins over the rules file, which wins over the default profile's; a setting
from the environment or the project file is laid over the rules files. A rule
that has no `steps` is the run's only and is read as the run's whatever step
asks; the Run section of the tab shows these, folded. The Rules drawer shows,
per rule, at which steps it has a value of its own.

Values of the machine (a model's address, its key, the slots per model, the
connections) are set in the project file `docpipe.toml`, which git ignores:
never in a rules file and never at a step, and a key only in `.env` or the
environment. The Run section writes the others into `docpipe.toml`
(`/api/machine/save`) and refuses the rest.

### Frames

- **each** repeats its boxes for each thing the document settles, each field
  (all, the fields the document has once, or the fields read in pieces), each
  piece of a field, each value or each coordinate of a value, in an order the
  frame names, and only for the items a condition holds for, where it has one.
  "Side by side" asks the items together instead of one after the other.
- **round** runs its boxes again, at most N times or until the supply is used up,
  and stops where its stop condition holds after a turn. A round until the supply
  is used up also ends after a turn that showed nothing of the supply. The box
  that writes the search sentence may write a new one from round 2 on, shown the
  sentences before; the pieces not yet shown are then ordered again with it.
- **if** takes the first way whose condition holds, else its else way; the ways
  join again below it.

A frame of coordinates has a state box in it: every coordinate ends in a state.
The state box gives a coordinate that is still open its state: by the search hits
(open where pieces of the search were never shown, else not stated), not stated,
no answer (a request about it got no answer in form), or not asked (only where it
has no state yet).

### Conditions

A box, an each frame, a way of an if and the stop of a round have a condition,
written in the page as rows, never as JSON. A row says what it is about, which
of its properties, a comparison and a value, and may be negated ("not"); the rows
are joined by "all" or by "any" (`extraction.conditions`). A property is a yes
or no, a number, a text or one of a list. What a row can be about is what is
there at the box's place: the document, the run, the field, the value, the
coordinate (its state, its kind, whether only its value's own place says it,
whether it is printed with the number, whether a request about it got no answer
in form and so on), the pieces (shown, left), the round and, after a box that asks, the
answer and its quote. A condition about the answer reads the answer of its own
item; where no box of that item asked, because it is off or its condition passed
it by, nothing came back. A row about something there is not yet at its place is
a problem of the drawing.

An own check is a box that refuses an answer where its condition holds; the
answer is asked again with its sentence, as often as the question's follow-ups,
then stays unbacked. It never takes what the fixed checks refuse. Its refusals
are counted as `check:<name>`.

### What the run refuses

Before a drawing is kept, `flow.problems` says everything the run could not do
with it, each at its box or frame: a box where it cannot stand (a question of a
coordinate outside each coordinate, a find outside each piece of each field), a
round that may not end, a search without a supply before it, a frame of
coordinates without a state, a condition that cannot be evaluated where it
stands, an id used twice, and the order the run needs (the document, the figures,
the pieces and the lists first, in this order; the writing at the end, only the
calculation after it). `flow.prompt_problems` adds a box that is on and asks a
request whose prompt neither the profile nor a profile it extends writes.

### The tab

The drawing is a canvas, and on the right stand the settings of the chosen step:
for a box its settings, its own values, its condition ("only when"), whether it
is on, and the first request a dry run made at it; a frame has its own form
(what it repeats, its order, side by side, the times of a round and its stop,
the ways of an if). With nothing chosen the right side shows the numbers of the
flow or the dry run. The drawing runs top to bottom: a frame (For each, Round,
If / else) is a coloured area around its column of boxes, the ways of an if
stand side by side, and each arrow is labelled with what the box before it gives
and the condition of the step it leads to. A frame opens and closes with its
arrow button or a double click; toolbar buttons open or close every frame and
show the whole drawing, and the first view shows the top of the drawing at a
readable size. The layout is computed from the nesting; no position is stored in
the flow file. Ctrl+Z undoes an edit and Ctrl+Y does it again, until the next
save. A short guide, "How to use this tab", stands above the canvas, folded
until opened. A problem is marked red at its box and listed above the canvas; a
click on it opens the frames around that box and brings it into view. A card
shows the number of requests its box asked in the recorded request logs and in
the last dry run. After Discard the page asks for the measurements again for the
numbers it puts back.

The flow has twelve numbers, each a whole number, and each says what it counts:

| the number | what it counts |
|---|---|
| `piece_lines` | lines of a piece a document is read in; a table's head is shown with each of its pieces |
| `title_page_lines` | lines of the document's first page that a request shows as its title page |
| `headings` | headings a request shows up to a value's place, its own last |
| `list_meanings` | entries up to which a list is shown with what each entry means; a longer list shows its names only, and one whose entries name groups is asked group first |
| `search_pieces` | pieces a search shows for an open coordinate or a field the document has once |
| `search_tables`, `search_figures`, `search_text` | the share of a search's pieces that are the best pieces of tables, of figures and of text, taken first; the three are scaled to the pieces of the search, and the rest are the best of any kind |
| `search_per_request` | pieces one request of a search shows |
| `listed_field_factor` | times the pieces of a search that a field the document has once reads where its values come from a list |
| `follow_ups` | times a request whose answer did not hold is asked again, each time with the answer and why it did not hold; 0 asks none |
| `replies` | replies out of their form a request takes before it is left unanswered; a request the server refuses is asked as often |

For each number the tab says whether the profile sets it itself or inherits it
and from which profile, and what a run started here would read with and why:
six numbers have a setting, four settings in all (`EXTRACT_SEARCH_PIECES`,
`EXTRACT_SEARCH_SHARES` for the three shares, `EXTRACT_SEARCH_CHUNKS`,
`EXTRACT_MAX_RETRIES`), and where a setting is set it wins over both files,
which the tab says. Editing a number or the drawing marks the tab as unsaved.

**Check** writes nothing. It refuses a number the flow does not take and a
drawing the run could not do, each with its words and at its box, lists what
changed (numbers, and boxes and frames added, removed, changed or moved, a line
naming its box first as every reason does: `own_place: changed`), says
what a save would do to the file (created, changed, removed or unchanged), shows
the diff, and says that a changed flow makes no harvest stale: a stamp names, for
each pass that read the document, the numbers it read with, and compares none of
them.

**Save** writes only where the numbers and the drawing hold and the file is as
the page loaded it; otherwise the page says the file changed on disk and offers
to reload. One refusal means that nothing of the edit is written. A profile that
extends another gets only the numbers that differ from what it inherits and the
drawing where it differs from the inherited one: a number set back to the
inherited value leaves the file, and a file that would hold neither is removed
(`Files.remove`, inside the profile's own folder only). The default profile's
own file is the whole flow, so a save there writes every number and the drawing.
The file keeps its line endings; a new file is written with plain ones.

### Flows of the follow-up passes

A follow-up pass over a stored harvest is a flow of its own, `top_up`,
`top_up_open`, `top_up_parameters`, `remap`, `recheck`, `review`, `start_at` or
`example`, each a file under `flows/` of the default profile that a profile may
replace by a file of the same name. The tab chooses which flow it shows: the
main flow, or one of these in the order a run takes them, each named with the
switch that starts it. A pass flow is loaded, checked and saved through
`/api/flow/pass`. It has a library of its own, its boxes and one frame, "for
each dimension"; it offers no rounds, no branchings, no conditions and no
numbers, and the page says where no run starts it. Rules at a step work in it as in the main flow.

### Dry run

The Flow tab's **Dry run** reads one document by the drawing on the page, with
the numbers as edited, and sends nothing (`flowtry.py`). Every request is built
in full as it would go out and kept. The document is one of the corpus database,
optionally some pages of it, or, without one, a plan made up from the examples
of the profile's spec. The answers are placeholders, each in its request's own
form, in one of two modes:

- "nothing": a find, and the question of a field the document has once, names
  the first number its piece prints where the field is a number (nothing where
  the piece prints none), else the piece's first word, so that there are values;
  every other answer is the empty answer of its request's own form (0, an empty
  list, an empty text, no). Each coordinate goes through its whole search, which
  shows how far rounds and searches go at most;
- "first_line": every answer names the first line the request showed, which shows
  the shortest way.

Every way the run asks stands in the dry run, built by the run's own code: a step
with a prompt of its own is asked with its inputs written in as the run writes
them, and the sentence each field's chunks are ordered by is asked from the
inputs of the step that writes it, once per field and kept at that step.
No embedder and no reranker are asked, so a search shows its pieces in the
document's order, which a run never does; the page says so. Per box the Try
gives the number of requests and the first one in full, and it lists the states
the coordinates of the values ended in, the number of values and the pieces the
document was cut into.

### What a trace measured

With `--harvest` the tab says, beside the number it measures, what the request
logs of that harvest measured, recounted as a number is typed (`measured.says`).
A request of a trace names the box that asked it, which is how the cards count
requests; a trace written before names none, and its requests are counted at the
box of the default drawing that asks their kind.

Every sentence is one template of `measured.SAID` (a form for one and one for
many where a count is the subject) in the page's words, with its numbers as
`{names}`; the page finds its German by the template. A kind of request (`find`,
`coord`, ...) and the cause of an unreadable reply (`missing_key`, ...) are
named as code, as the request log names them. The sentences say:

- of the searches for an open dimension, how many ended with an answer that
  gives a line number and how many without one; after how many shown chunks of
  the budget those answers came (the least, the most and the middle one), and how
  many came only after more than the typed budget; how many requests the
  searches sent, and the mean per search;
- for the fields asked once per document, how many requests found something and
  how many of them only after more than the typed budget of shown chunks (for a
  field with a list, the budget times `listed_field_factor`);
- how many answers did not pass the checks and were asked again, by kind of
  request, or that none was;
- how many replies were read, how many only after more than the typed number of
  attempts, and the replies read per attempt ("Attempt → replies read: 1 →
  9,206; 2 → 239"); how many could not be read, by cause;
- how many requests for the entry of a list showed a list longer than the typed
  number of entries, whose entries are then shown by their names only.

Two limits belong to these counts. A trace does not record whether an answer
passed the checks, so the tab counts an answer that gives a line number, and not
a value read. And "came after more than N" estimates what a smaller budget would
have cost, since a smaller budget also changes which pieces are picked. A trace
written before a search noted which of its pieces count toward its budget
(`shows`: `near` for the pieces beside the value, `found` for those of the
budget, `fetched` for those the model fetched itself, which count toward no
budget) is counted over all its pieces, and the tab says so
(`measured.NOT_NOTED`). The traces are read by `measured.light`, which does not
put the requests back together, and the counts of a trace are kept per state of
its file. Without `--harvest`, or with a folder that holds no trace, the tab
says that and counts nothing.

Below the drawing the tab lists the year rules of the spec as notes (the key
`of` of a plan field that is a year; see [the extraction stage](extraction.md)),
each a link to the field of the whole document in the Spec tab, and the folded
Run section (see Rules at a step). The value of a secret setting (a key, a
token) is never sent to the page, and what an address carries before its host
(a user, a password) is replaced by `***@`.

The Spec tab's form of a plan field that is a year has the key `of`: a coordinate
of a group's pair and an entry of its list.

## Rules

Each tab that has rules shows them in a drawer, opened by its Rules button: each rule with its help, its
kind and its bounds, taken from the profile's `rules.json` (the default
profile's file names all of them, a profile's file only what it sets
differently). A value is checked against the bounds before it is saved
(`/api/rules`, `/check`, `/save` in `rulespage.py`). An `EXTRACT_*` setting
wins over the file and the drawer says so. A rule that steps may set shows at
which steps of the flow it has a value of its own. A value of the machine is
not written here but in the Run section of the Flow tab. No rule makes a
harvest stale.
A rule of kind map is a table of names and values with + and -, one of kind
table a table with its columns and a row to add, one of kind range two number
fields, from and to, an empty one meaning no bound; no value is typed as JSON
(`forms.js`, `rulespage.FORMS`).

## Sources

The Sources tab shows `sources.json`: the ontology, the shapes and the graph
queries the profile is written against, the lists drawn from them and which
coordinate answers from which list. It checks and saves the file. Fetch pulls
the sources into a temporary folder; Apply writes the files a refresh writes
into the profile and the fetched files and the lock into the upstream cache. The
differences of the fetched shapes against the spec and the drawing are shown
per field, and a chosen row can be taken into the Spec tab (a new field, a
draft) or into the drawing (`sourcespage.py`). "Also write a field under it"
takes a property of the shapes into a field: the merge draws an arrow from the
field (listed by `merge_targets`) to the box of the property's class, adding the
box where the drawing has none, and hands the drawing back with the spec (`take`,
its `map`). A new field brings its arrow in the same way. The arrows drawn are
in the Graph tab; check and save them there. The graph then holds what the
field reads under the further property as well (see [the graph](graph.md)).

## Graph

The Graph tab is the drawing of how the harvest becomes the graph: the `map` of
`graph.json`, which the run's one program, `docpipe/extraction/graph.py`, writes
every graph from (see [the graph](graph.md)). The page is `graphpage.py` and the
graph endpoints of `server.py`, with the sources in `docpipe/editor/ui/src/graph/`.

On the left are the fields of the harvest as the spec asks them, with a real
example value each where a harvest is loaded. On the right are the boxes, one
for each class of the graph, each with the properties the shapes give that class
and the effect of each constraint; a property the shapes require is red until an
arrow leads to it. An arrow is drawn by dragging from the dot of a field to a
property of a box (the field is written under that property), from a field to a
box (the field makes the box's nodes), or from a box to a box over a property
(the nodes are linked). A box says how many nodes it has in a document (one,
one for each name, one for each distinct reading, one for each answer, one for
each number, one for each object another arrow wrote), how a node is named (its
address) and what is admitted; an arrow says its property, the brick that makes
the object of its triple and the brick's settings, whether one reading is
written, which readings count and a note. A click on a box, an arrow or the
document opens its settings in a panel; a brick comes from a list that says what
it does, what it takes and what it gives. The order of the boxes is the order of
the nodes in the graph, the order of the arrows the order of the properties. The
rules of the program (the graph file's `rules`) are in the Rules drawer; the
effect of a constraint (report, leave out the value, leave out the paper, stop)
is set in the settings of the box whose properties it holds.

Check holds the edited drawing to the run's own checks (`graphfile.map_problem`,
`graph.check`) and names the box or arrow each problem is about; Save writes
`map` into `graph.json` if the checks pass; Discard and Reload from disk return
to the file; Undo and Redo walk back through the edits until saved. With a
harvest loaded, the page also shows the triples one document would be written
as, by the edited drawing and, with a switch, as the strict graph
(`POST /api/graph/preview`); it writes into a temporary folder and sends no
request to a model. Test write writes the graph of the page's harvest twice,
once with the saved file and once with the edit, and compares the two (nodes
kept and left out, violations by constraint, nodes named anew;
`graphpage.py`, `graphprobe.py`). A change of the graph needs no model: it takes
effect the next time the graph is written from the stored harvest.

## What the editor does not touch

The editor writes these kinds of file through its own code: the spec, the
prompt files, the sentence files and the profile's `flow.json`, its
`flows/<name>.json`, `rules.json`, `sources.json` and `graph.json`, and the write
guard (`server.Files`) lets that code write, and remove the flow file, only
inside the profile's folder. The one other file it writes is the project file
`docpipe.toml`, from the Run section of the Flow tab, and only values of the
machine. A second
guard may write only the upstream cache, for Apply in the Sources tab. It reads only inside the
folders of the profiles in effect, the harvest it was given, its own page, the
generated documentation and the folder the before and after comparison of the
prompts writes into. A path is resolved first, so `..` and links cannot lead out.
A trace is read by the run's own trace reader, after the guard has checked its
path (`Files.checked`). It commits nothing, pushes nothing and starts no job. It
runs `git` for the branch and for the files of the profile folder that differ
from the last commit, to show both in the header, and changes nothing with it.

It sends over a network in exactly one case: a Try of the Prompts tab, to the
endpoint the installation names, one request for each request named in the click
and at most three (see Try). The dry run of the Flow tab sends nothing. The page
itself is served on `127.0.0.1` and talks to nothing else, and no other action
of the editor sends a request to a model or to any other host.

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

What a box does cannot be edited in it: that stays code. The prompts, the
sentences the stages say outside them, the spec, the flow, the rules, the sources
and the graph file are in the page.

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
(`<temp>/docpipe-prompt-review`). One more guard writes the upstream cache
and nothing else: "Apply" of a fetch puts the fetched files and the lock
there (`sourcespage.apply`); a fetch itself writes only into a folder of its
own in the temp directory (`<temp>/docpipe-sources-fetch`). A path is
resolved first, so `..` and links cannot lead out. A trace is read by the run's own reader after the guard has
checked its path (`Files.checked`). A server that `docpipe edit` started
(start.py) has one more guard, which writes the note of a switch of the
profile and nothing else, into the temporary folder the command made for it.

A server runs on one profile. Where `docpipe edit` started it, the head of
the page offers every profile the installation finds; a switch to another
writes that profile and the server's port into the note and ends the server
once its answer is sent, and the command starts it again with that profile
(start.py). A server started otherwise offers only its own profile.

The HTTP layer binds 127.0.0.1 only, answers only a `Host` it knows (a page
of another site cannot reach the server by a name of its own) and takes a
POST only with the header the page sends (a form on another site cannot send
it). A request it answers without having read it to the end, a refusal, is
read off before the connection closes, so that the answer arrives. The
standard library is all this needs.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/rulespage.py</code></summary>

rulespage.py: The rules of a profile as `docpipe edit` shows and sets them,
each in the tab it belongs to.

The rules themselves are the run's (`docpipe.rules`): their files, their
strict loader, what each is and where the code applies it. A tab shows the
rules of its kind (spec, prompts, flow, sources, graph) in their groups, each
with its value, the value it has where the profile says nothing (the
inherited one), who says it, the dates of the owner's decisions, and the
setting that wins over it where one is set. Saving writes the profile's own
rules.json with the rules it sets differently from what it inherits, and
every rule it declares itself (that file is where those start from); a file
with no rule left is removed. Nothing a rule says makes a harvest stale.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/sourcespage.py</code></summary>

sourcespage.py: Where a profile's ontology, shapes and graph come from, as
`docpipe edit` shows, fetches and applies them, and what they say differently
from the spec.

The sources themselves are the run's (`docpipe.sources`, `docpipe.upstream`):
the profile's sources.json, the fetch of each kind, the lock that names what
the last refresh took. This module turns them into what the page shows and
decides what each button does (owner, 2026-11-10: "einfach die URLs angeben
für Ontologie und KG und dann eben die auch die Felder auswählen und
zusammenlegen"):

- `view`: every source with its address, the kind of version it stands at
  (a release, the head of a branch, a live query) and the version the lock
  holds; a token only as set or not set, never its value; the lists and
  which coordinate answers from which.
- `judge` and `save`: an edited sources.json, read strictly by the run's own
  parser before it is written.
- `fetch`: the profile's own refresh into a folder of the temp directory,
  never into the profile or the cache: which source moved, what that does
  to each list (entries added, gone, renamed, redefined) and to the other
  files the refresh writes.
- `apply`: a fetch made the profile's: the files the refresh writes into the
  profile's folder, the fetched files into the cache and the lock beside
  them, its paths moved from the temp folder to the cache. The spec never.
- `differences`: per field, what the shapes and the ontology say otherwise
  than the spec (`draft.differences`, held to the shapes as the profile names
  its properties; `ontology.definition_differences`), each row the page can
  act on with an id.
- `take`: the chosen rows applied to the spec, for the Spec tab to check and
  save with what it costs: a new entry of a list with the ontology's name
  and definition, a definition replaced by the ontology's, a property no
  field asks as a new field (a draft: it needs an example before the strict
  check takes it), or merged into an existing field as one more property it
  writes: an arrow of the drawing of the profile's graph file, from the
  field to the box of the property's class (`take` hands the drawing back
  beside the spec).

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/graphpage.py</code></summary>

graphpage.py: How a profile's harvest becomes its graph, as `docpipe edit`
shows and sets it (owner, 2026-11-10: "sodass man steuern kann, wie die
Ernte in den Graphen aufgenommen wird und welche constraints erfüllt sein
müssen").

The file and what it does are the run's (`docpipe.graphfile`); the shapes
are the ones the profile's last refresh pulled. This module turns them into
what the page draws and decides what a save writes:

- `view`: every class of the shapes with its properties, each with the
  fields that write it, its constraints (required, at most so many, a closed
  list, a class, a datatype) and the effect the graph file gives each; per
  class whether it is written and its address rule; the rules the writer
  declares, each with its value, what it inherits and the setting that wins
  over it.
- `judge` and `save`: an edited graph file, read by the run's own parser.
  A profile that extends another writes only what differs from what it
  inherits, and the rules its writer reads.
- the drawing: `view` also returns `map` (how the harvest becomes the
  graph, `graphfile.get_map`), the fields of the harvest as the spec asks
  them (with a real example of each where a harvest is loaded), the bricks
  the run knows and the harvest's documents. `judge` holds an edited drawing
  to the run's own checks (`graphfile.map_problem`, `graph.check`) and
  names the box or arrow each problem is about. `preview` writes one
  document of the harvest as the edited drawing says.
- `probe`: the graph of the harvest the page was given, written twice into
  the temp directory, with the saved file and with the edited one, and what
  differs: per document the nodes kept and left out, per constraint its
  violations, the nodes named anew. No model is asked and nothing is saved.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/editor/graphprobe.py</code></summary>

graphprobe.py: The graph of a local harvest as a profile's graph file has
it written, into a folder of the temp directory, for the Graph tab of
`docpipe edit` ("Test write"). A process of its own, because a writer reads
its rules when it is imported:

    python -m docpipe.editor.graphprobe PROFILE HARVEST DB OUT

with `DOCPIPE_GRAPH_FILE` naming the graph file to write with (the page's,
unsaved) or unset for the profile's own. Writes OUT/graph.ttl and
OUT/probe.json: per document the nodes it has in the graph and what left it
with which constraint, the nodes of each class, the violations of each
constraint and how many nodes were named anew. Nothing is written but into
OUT; no model is asked.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
