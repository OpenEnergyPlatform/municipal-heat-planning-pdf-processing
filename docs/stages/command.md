# The command and its settings

## What it is for

`docpipe` is the one command. It starts every stage, the chat and the tools
around them:

```
docpipe [--profile P] [--config FILE] <command> [arguments]
```

`pip install .` puts it on the path; `python -m docpipe` does the same.
`--profile` names the profile (a name, or the directory of one) and
`--config` the project file; both are also taken after the command. A
`--profile` after the command is bound for every command before its stage is
imported, also for those whose module is its own entry point (`export`,
`evaluate`, `lexical`) and have no `__main__` that could do it in time.
`docpipe <command> --help` shows what a command takes; for `sandbox` it says
that the service takes no arguments, that where it listens and what a run may
use are settings, and that `KWP_SANDBOX_TOKEN` has to be set.

A stage command runs the stage the way `python -m docpipe.<stage>` runs it,
with the same arguments, and that form keeps working. The command module
imports no stage on purpose: a stage binds part of what the profile and the
project file say when it is imported, so the command settles both first.

| command | runs |
|---|---|
| `run` | stages 1 to 6 and the word index in one go, each as its own command (see below) |
| `status` | which stage has left output for which document (see below) |
| `estimate` | before a run: the requests, tokens and price each stage still has ahead of it, no model called (see below) |
| `ingest` | stage 1: register the documents the profile's source names |
| `preprocess` | stages 2 and 3: layout, reading order, sections |
| `refine` | stage 4: repair the text of each section |
| `visuals` | stage 5: transcribe tables, describe figures |
| `chunk` | stage 6: merge, database, embeddings |
| `extract` | stages 7 and 8: harvest, top up, review, serialize; `--spec FILE` harvests a column of one's own instead of the profile's spec |
| `reanchor` | after a rebuilt database: find each harvested row's passage again |
| `compile` | draft an extraction spec from shapes (see [the spec compiler](compile.md)) |
| `column` | the spec of one question of one's own, for a trial harvest over a few documents (see [a column of one's own](extraction.md)) |
| `preflight` | before a corpus run: check a profile's spec, prompts, schema and graph writer (see [the extraction stage](extraction.md)) |
| `evaluate`, `benchmark` | measure a harvest; `evaluate NEW --diff OLD` compares two harvests without decisions (see [measuring a harvest](evaluation.md)) |
| `export`, `serve` | hand the harvested values on, with the states and refusals beside them and a search over the corpus passages (see [handing the values on](serve.md)) |
| `lexical` | build the word index the chat searches beside the vectors |
| `chat` | the chat over a processed corpus (see [the app](app.md)) |
| `sandbox` | the service that runs code a model wrote, in a container without a network |
| `init` | start a project in this folder |
| `doctor` | check this installation |
| `config` | every setting, its value and where the value comes from |
| `profiles` | the profiles this installation finds, and where |

## The project file

A project is one `docpipe.toml` instead of a hundred environment variables.
The nearest one from the working directory upwards applies, or the one
`DOCPIPE_CONFIG` names. Its keys are the settings the environment already
has, grouped by table (`[llm]`, `[extract]`, `[chat]`, and so on), and its
values are put into the environment before a stage is imported, for the
names the environment does not set. So the environment still wins, and a
stage reads what it always read. A key that names no setting is refused
with the nearest ones; so is a key or a token, which belongs in `.env` or
the environment. A `.env` beside the project file is read too.

`docpipe config` prints every setting with its value and where the value
comes from (the default, the project file, a `.env`, the environment);
`--stage S` narrows it to the settings one command reads and `--set` to the
ones that are not at their default. `--stage` offers the commands that have
settings of their own; one that has none (`compile`, `evaluate`, `export`)
reads those of the stage it works for. A test holds the list against every
environment name the code reads, so a setting cannot exist without a line
there.

## Running the stages and seeing where they stand

```
docpipe run [--from STAGE] [--to STAGE] [--skip STAGE ...]
docpipe status
docpipe estimate [STAGE ...] [--pdf-dir DIR] [--processed DIR] [--db FILE] [--out DIR]
```

`docpipe run` starts ingest, preprocess, refine, visuals, chunk and lexical in
that order, for the profile in effect (`docpipe/run.py`). `--from` and `--to`
bound the range and `--skip` leaves stages out. Each stage is its own
process, `docpipe <stage>` with the arguments the profile gives it, and the
profile and the project file travel in the environment. The command prints
which stage starts before it starts. It stops at the first stage that ends
non-zero and ends with that stage's exit code (a stage killed by a signal is
told as 128 plus the signal, Ctrl-C as 130), naming the stages that did not
run. No stage behaves differently for being started this way, and the harvest
(`extract`) is not among them, because it needs a spec and says for itself what
it costs.

What a stage is given is what its own command line needs and the profile
knows: ingest takes its paths from the profile, preprocess the profile's PDF
folder as its input, refine and visuals `--batch` (their input is the profile's
processed folder, which holds one directory per document), chunk and lexical
nothing. Where a selected stage lacks an argument the profile cannot give, the
command names it, starts nothing and ends 2. That is the case for ingest under
`kwp` and `scenarios`, whose document list has no default place: run
`docpipe ingest --source FILE` first, then `docpipe run --skip ingest`, or
start with `--from preprocess`. An empty or reversed range (`--from` after
`--to`, or `--skip` naming every stage between them) is refused with exit 2.
Two things stay as they are in the single commands. Preprocess ends 0 even when
single PDFs failed, so `run` goes on, and `docpipe status` is where the gap
shows. And `run` passes no `--transcribe-missing-text`, so the PDFs that ingest
listed as scans are not read by the model.

`docpipe status` prints one line per document and one column per stage of
`run`, an `x` where that stage's output for the document is there and a `-`
where it is not, then for each stage how many documents have its output, and a
`word index:` line that says current, stale or missing. A document is every
name the corpus knows: a row of the database, a PDF directly in the profile's
PDF folder, a directory directly in its processed folder. "There" is what the
stage itself calls done, asked of the stage's own code where it has a function
for it:

| stage | its output is there when |
|---|---|
| ingest | a `Documents` row exists for the file, as ingest looks it up |
| preprocess | `pages.json` and `sections.json` exist |
| refine | `sections_refined.json` exists and no partial file (`sections_refined.partial.json`) sits beside it: one stays beside a finished output too, while a window ended as a hole |
| visuals | `visuals.json` exists and every table and figure of its input has the markdown or description the stage looks for |
| chunk | `document.json` is not older than its inputs and an embedding is recorded for a section, table or figure of the document |
| lexical | the word index is current and holds a passage of the document |

It changes nothing: the database and the word index are opened for reading, no
file is created, and a stage that has not run (no database, no processed
folder) is a column of dashes. A database that cannot be read ends the command
with its path. Two rules are looser than the stages': a half-embedded document
shows chunk as done when any embedding of it exists, and a `pages.json` that
exists but is corrupt shows preprocess as done where preprocessing would redo
it. It imports the stages' own modules, so it needs what they import (`faiss`
and `numpy` among them) and ends with an import error where they are missing.

`docpipe estimate` says, before a run, what the stages named (all of them
without a name: ingest, preprocess, refine, visuals, chunk, extract) still
have to do and what that costs (`docpipe/estimate.py`). Per stage it counts
the pending work by that stage's own rule, then the requests, the tokens in,
out and embedded, and a price. It calls no model and writes nothing. The
pending work is what the stage itself would find to do: preprocess, the PDFs
with no `sections.json`; refine, the documents with no refined result and, of
a pass left unfinished (a partial file beside the output), only the windows it
holds no reply for, whether the server did not serve them or the model's reply
could not be read; visuals,
the tables and figures with no markdown or description; chunk, the inputs with
no embedding in the database; extract, the documents the harvest has no
current stamp for. Ingest asks no model, so it has no request to count.

Every figure names its basis, and the two are not mixed in one figure.
"Measured" takes what a request of this stage under this profile and model has
cost on average from the usage ledger (`docpipe/usage.py`); "counted" takes the
size of the prompt, with the stage's own over-estimate of tokens per word,
where the ledger holds none, and says nothing about the length of a reply. The
ledger rows from before it kept profiles belong to no profile and are left out,
and the line says how many. The harvest cannot be counted before it runs, since
what retrieval finds and what the model reads are not known; its basis is the
trace of documents already harvested under `--out`, requests and tokens per
section by kind of request, scaled to the sections still to harvest. Without
such a trace, or with one that holds no answered request, it says it cannot
estimate. The command ends 1 when a stage could not be estimated, a stage
whose imports are missing among them (the others are still counted), or a
directory is missing.

The price comes from the `[prices]` table of the project file, per million
tokens in whatever currency its author used:

```toml
[prices]
"some-model" = { input = 2.0, output = 10.0, cached = 0.2 }
```

`input`, `output`, `embedding` and `cached` are the keys. `cached` is what an
input token costs that the provider served from its cache; without it a cached
token costs the `input` price, so a cache the table says nothing about never
makes the bill smaller. The line says "at least" where output tokens could not
be counted and "not counted" for a model the table does not name. The
estimate does not follow `--force`, `--force-stale` or chunk's `--step`, nor
the vectors the index has lost, which only the stage's own run reads. The
figure for the harvest leaves out the retries of replies that could not be
read, the review, top-up and top-up-parameters passes, and the requests that write each
document's search sentences.

## Starting and checking a project

`docpipe init [NAME]` writes `docpipe.toml`, a profile under
`profiles/NAME/` that extends the built-in `default` profile (see
[profiles](../profiles.md)), `.env.example`, `.gitignore` and the folder the
PDFs go into. It stops where a project file or a profile of that name
exists, and leaves an existing `.env.example` or `.gitignore` as it is. The
new `docpipe.toml` carries `[refine] return_corrections = true`, with a
comment, so a new project asks refinement for corrections (find and replace)
and not for every section retyped; the setting's own default stays off, so a
project without the line is unchanged. The command ends by saying what to run
next: `docpipe doctor`, `docpipe run` and `docpipe chat`, with `docpipe ingest
--source FOLDER` and then `docpipe run --skip ingest` for PDFs lying in
another folder.

`docpipe init NAME --shapes [FILE]` also writes the draft of an extraction
spec, `profiles/NAME/extraction_spec.draft.json`, from SHACL shapes: those in
FILE, or, with the option alone, the small metadata shape the package brings
(a node on `schema:CreativeWork` with eight text fields: title, author,
publisher, date, version, language, abstract, keywords). Give the project's name
before the option, or the option takes it for its file. The shapes are read
before any folder is made, so a file that is missing, is a folder, cannot be
parsed or holds no shape with a target class and a property stops the command
with a message that names the file and ends "nothing was written"; an empty
name (what an unset variable gives in `--shapes "$FILE"`) stops it as well and
does not fall back to the bundled shape. Reading shapes needs `rdflib`
(`pip install "docpipe[kg]"`).

What the user has after that is a draft and not a spec, and the command says
so. The file is not called `extraction_spec.json`, so the profile has no spec
and `docpipe extract` stops (it names the missing `SPEC_PATH`) until one lies
beside `extraction.py`. `docpipe compile check` lists what the draft lacks: the
placeholder base IRI of the graph and one example for each field. Examples are
proposed by `docpipe compile examples`, which needs a corpus that `docpipe run`
has processed and a model, and `docpipe compile apply ... --out
profiles/NAME/extraction_spec.json` writes the spec only from the proposals a
person accepted. A spec written some other way does not pass `docpipe
preflight` as it stands: the eight fields have no closed list, so `out:unstated
is selectable` fails, the profile's `extraction_schema.json` has to be written
first (`python -m docpipe.extraction.schema NAME --write`), and the graph's
base IRI has to be a real one. `docpipe extract` itself runs no preflight.
The built-in `default` profile has no `SPEC_PATH` on purpose: a profile that
extends it would otherwise inherit a spec it never wrote.
`docpipe doctor` asks, without a GPU or a document: are the Python and the
packages the chosen stages need installed, does the profile load and what does
it provide, do the model servers answer and serve the model named, does what
each stage asks of the server and of the profile hold, are the PDFs, the
database and the index there. One line per check, the remedy on the line, exit
1 when something fails. Where a hosted API turns the key down, the remedy names
the environment variable that holds it (`LLM_API_KEY`, `VLM_API_KEY`), not the
project file's key, which takes no secret. A stage whose packages are missing
is a warning, so an installation that only chats needs no layout model; named
with `--stage` the same finding fails.

Beyond the packages, the profile and the endpoint, these lines are looked at
where the stages themselves say what they ask:

- `context`: the tokens per request that refine, extract, `extract --review`
  and visuals compute for their own budget, against the window the server
  reports (the vision stage against the vision server). For extract that is
  the largest request over the prompts a harvest sends, the number
  `--print-context-budget` prints; `extract --review` counts the review prompt
  alone. One that is too small fails, one that is not reported is a warning,
  and a hosted API is told to check the model and not to start a server.
- `request`: the one request of one token that the stages' preflight sends,
  sent on its own to each server asked, to see whether the server takes the
  request fields (the reasoning settings, or the reply schema of a hosted
  API). A refusal fails. A server that could not be asked, or that answered
  429 or a 5xx, gives a warning, "no verdict", and the exit stays 0. The chat
  sends these fields as well (`LLM_ENABLE_THINKING`, `LLM_REASONING_EFFORT`), so
  a chat-only check sends the request too, and a server that refuses
  `chat_template_kwargs` or `reasoning_effort` fails it. With `--stage`, the
  request is sent for `refine`, `extract`, `visuals` and `chat`
  (`doctor.SENDS_FIELDS`) and for no other command.
- `prompts`: one line per stage that loads prompts, read the way the stage
  reads them, so a prompt that is missing and one that is there but cannot be
  read (front matter that is no mapping) are told apart.
- `wording`: the profile's phrase and UI tables for extraction and the chat,
  and the hooks of the graph route, each checked by the code that raises for
  what is missing.
- `embedding`: the model and the dimension the database records for its
  index, against the ones configured for queries. A model or a dimension that
  differs fails, because their vectors do not compare; one the database does
  not record is a warning.

The `profile` line fails when no profile is named. `--stage chat` is the
exception: the chat runs on the built-in `default` profile then, so the line
says so and the chat's lines are checked against that profile.

A group never raises: a package that is missing is a warning, a part the profile
does not provide is skipped, a module of `docpipe` or of the profile that is
missing is a failure, and anything else is a failure line in its own words.
Each server is asked once and the lines that need its answer share it; a client
that cannot be built is a failed endpoint line. `--offline` asks no server: the
endpoint, `context` and `request` lines are skipped with "--offline" on them,
and prompts, wording and the database file are still read. With `--stage
compile` no model server is asked, although `compile` sends the request
fields; without `--stage` the language-model lines cover it. With no vision
server configured and no `--stage` there is no `context` line for visuals at
all, not a skipped one.

`docpipe preflight [PROFILE ...]` checks a profile for a corpus run, again
without a GPU or a model question: the spec the profile names, its extraction
prompts and the passages it says they hold, the shape it publishes and the
writer of its graph. It prints one line per check (48 for each of `kwp` and
`scenarios`, 96 for the two), checks the profile in effect when none is named,
and exits 1 when a check fails, so it can stand before a corpus run. Lines
marked as warnings never fail it. It works for any profile, in this repository or in a
project of one's own, which may be named by its directory as for `--profile`;
a name that is no profile is one failed line, and so is a profile the audit
cannot get through, while the tables of the others are still printed (see [the
extraction stage](extraction.md)).

## Installing

`pip install .` brings what every stage needs that asks a model over an API.
The stages that run a model in the process are extras, named in
`pyproject.toml`: `layout` (stage 2), `embed` (stage 6 and the chat's local
embedder), `app` (the chat), `kg` (the graph and its checks), `kwp` (what the profiles in this
repository read their document lists with), `sandbox`, `anthropic` and `dev`.
`requirements.txt` stays the lock the container image is built from.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/cli.py</code></summary>

cli.py: The one command.

    docpipe [--profile P] [--config FILE] <command> [arguments]

A stage binds part of what a profile and a project say when it is imported.
So this module imports no stage. It settles the profile and the project file
first, and then runs the stage the way `python -m docpipe.<stage>` runs it,
which keeps working and takes the same arguments.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/settings.py</code></summary>

settings.py: What an installation can set, in one list, and where each value
came from.

A stage reads its settings from the environment, most of them when it is
imported. That stays the interface: a variable set there wins over
everything else. Underneath it sits the project file, `docpipe.toml`. Its
values are put into the environment, for the names not set there, before a
stage is imported. A stage reads what it always read, and a project is one
file instead of a hundred variables.

    profile = "kwp"                 # top level: the DOCPIPE_* names
    data_root = "data"              # a relative path is relative to the file
    [llm]
    base_url = "http://localhost:8000/v1"
    [extract]
    batch_sources = 2
    [env]                           # a profile's own names, verbatim
    MY_SETTING = "x"
    [prices]                        # per million tokens, in one currency
    "some-model" = { input = 2.0, output = 10.0 }

A key that names no setting is refused with the nearest ones. So is a secret:
a key or a token belongs in `.env` or the environment, not in a file that is
checked in. That holds for the [env] table too, by the name's ending.

SETTINGS is that list. A test holds it against every environment name the
code reads, so a new setting cannot be added without a line here.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/doctor.py</code></summary>

doctor.py: Can this installation run? One line per thing looked at.

    docpipe doctor [--stage S] [--offline] [--json]

Nothing here needs a GPU or reads a document: a server is asked which models
it serves and answers one request of one token, a database says how many
documents it holds and which embedding model built its index. What fails
makes the command exit 1, with what to do about it on the line, so a first
start and a CI job can both stop on it.

What the stages ask of the setup is looked at where the stages say it: the
context a stage needs is the budget the stage computes, the request fields
are probed by the preflight the stages run, the completeness of a stage's
prompts and wording is the loader's and the wording tables' own. Nothing here
counts any of it again.

A stage whose packages are not installed is a warning, not a failure: an
installation that only chats needs no layout model. Named with --stage, the
same finding is a failure. With --offline no server is asked, and each
group of lines that needs one says it was skipped.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/run.py</code></summary>

run.py: `docpipe run`, the stages that turn a folder into a corpus.

    docpipe run [--from STAGE] [--to STAGE] [--skip STAGE ...]

ingest, preprocess, refine, visuals, chunk and lexical, in that order, for
the profile in effect. Each is started the way `docpipe <stage>` starts it,
in a process of its own: a stage that holds a model, or dies, leaves nothing
behind for the next one. The harvest (`extract`) is not among them: it needs
a spec, and what it costs is for its own command to say.

A stage is given the arguments its command line needs and the profile
knows, and no others: ingest takes its paths from the profile and needs
`--source` only where the profile's source has a document list to name,
preprocess takes the profile's PDF folder as its input, refine and visuals
take `--batch` (their input is the profile's processed folder). A stage that
cannot start without an argument the profile cannot give is named before any
stage starts. The run stops at the first stage that ends non-zero, with that
stage's exit code.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/status.py</code></summary>

status.py: `docpipe status`, which stage left what for each document.

    docpipe status

One line per document and one column per stage `docpipe run` starts, an x
where that stage's output for the document is there, then how many documents
each stage has output for. A document is every name the corpus knows: a row
of the database, a PDF in the profile's folder, a directory in its processed
folder.

"There" is what the stage itself calls done, asked of the stage's own code
where it has a function for it and of its own file names where the rule is
the file:

  ingest      a Documents row for the file (what ingest skips)
  preprocess  pages.json and sections.json (what preprocessing resumes on)
  refine      sections_refined.json, and no unfinished pass beside it
  visuals     visuals.json, and every table and figure of its input in it
              with the markdown or description the stage looks for
  chunk       document.json not older than its inputs, and an embedding
              recorded in the database for a section, table or figure of it
              (which takes its Sections rows)
  lexical     a word index that is current and holds a passage of it

Nothing here writes. The database and the word index are opened for reading
only, and a stage that has not run (no database, no processed folder) is a
column of dashes, not an error.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/estimate.py</code></summary>

estimate.py: What a run will cost, before it runs.

    docpipe estimate [STAGE ...] [--out DIR] [--db FILE] [--processed DIR]

For each stage named (default: all) it counts the work the stage still has,
by that stage's own rule for what is pending, and says how many requests that
is, how many tokens go in and out, and what that costs when the project file's
[prices] table names the model. It is an estimate and says so: it never calls
a model, and it stops nothing. It is a number to read before `docpipe <stage>`,
not a limit on it.

Every figure carries its basis, and there are two. Where this installation's
ledger (usage.py) holds requests of the stage under this profile and this
model, a request is taken to cost what those requests cost on average:
"measured". Where it holds none, the request is counted from the size of its
prompt: "counted", which is the stage's own over-estimate of tokens per word
and says nothing about the length of a reply. The two are not mixed inside one
figure, and the line says which one it used. A ledger kept the profile only
from the version that added the column on, so its older rows are no profile's.

The harvest (stage 7) is the exception to "counted". How many requests it
asks follows what retrieval finds and what the model reads, and neither is
known before it asks. So its basis is the trace of documents this profile has
harvested already, in the harvest directory (`--out`): requests and tokens
per section by kind of request, scaled to the sections still to harvest. With
no such trace it says it cannot estimate, and the command ends non-zero.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/column.py</code></summary>

column.py: `docpipe column`, a column of one's own for a trial harvest.

    docpipe column NAME DESCRIPTION [--dir FOLDER]

A profile asks what its spec asks, and a spec comes from an ontology. A
question of one's own, put to a few documents, has no place there. This
writes the spec of one such question into a folder of its own: one parameter,
read as text, from a name and a description in plain words ("Renovation
rate", "How many percent of the buildings are renovated each year"). It
writes no example, because the spec loader wants a real one and a person has
to read it. The rest is commands that exist, each given the folder's names:

    docpipe compile examples DRAFT --profile P   propose the example
    docpipe compile apply DRAFT --out SPEC --profile P
                                                 carry the one a person
                                                 accepted into the spec
    docpipe extract DB INDEX HARVEST --spec SPEC --document ID
    docpipe export HARVEST --out TABLE

The harvest checks every value as every harvest does: its quote stands in a
shown passage, and the answer stands in the quote. It is a trial. Nothing
here adopts the column into a profile's spec and nothing here hands the
folder to the serializer. The folder keeps itself out of version control,
because its example and its harvest are passages of the corpus.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
