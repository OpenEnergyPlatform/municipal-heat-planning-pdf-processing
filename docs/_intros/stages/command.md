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
| `ingest` | stage 1: register the documents the profile's source names |
| `preprocess` | stages 2 and 3: layout, reading order, sections |
| `refine` | stage 4: repair the text of each section |
| `visuals` | stage 5: transcribe tables, describe figures |
| `chunk` | stage 6: merge, database, embeddings |
| `extract` | stages 7 and 8: harvest, top up, review, serialize |
| `reanchor` | after a rebuilt database: find each harvested row's passage again |
| `compile` | draft an extraction spec from shapes (see [the spec compiler](compile.md)) |
| `evaluate`, `benchmark` | measure a harvest (see [measuring a harvest](evaluation.md)) |
| `export`, `serve` | hand the harvested values on (see [handing the values on](serve.md)) |
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

## Starting and checking a project

`docpipe init [NAME]` writes `docpipe.toml`, a profile under
`profiles/NAME/` that extends the built-in `default` profile (see
[profiles](../profiles.md)), `.env.example`, `.gitignore` and the folder the
PDFs go into. It stops where a project file or a profile of that name
exists, and leaves an existing `.env.example` or `.gitignore` as it is.

`docpipe doctor` asks, without a GPU, a document or a model question: are
the Python and the packages the chosen stages need installed, does the
profile load and what does it provide, do the model servers answer and
serve the model named, are the PDFs, the database and the index there. One
line per check, the remedy on the line, exit 1 when something fails. Where a
hosted API turns the key down, the remedy names the environment variable that
holds it (`LLM_API_KEY`, `VLM_API_KEY`), not the project file's key, which
takes no secret. A stage whose packages are missing is a warning, so
an installation that only chats needs no layout model; named with `--stage`
the same finding fails. `--offline` skips the servers.

## Installing

`pip install .` brings what every stage needs that asks a model over an API.
The stages that run a model in the process are extras, named in
`pyproject.toml`: `layout` (stage 2), `embed` (stage 6 and the chat's local
embedder), `app` (the chat), `kg` (the graph and its checks), `kwp` (what the profiles in this
repository read their document lists with), `sandbox`, `anthropic` and `dev`.
`requirements.txt` stays the lock the container image is built from.
