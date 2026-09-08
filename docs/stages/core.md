# The parts every stage uses

| | |
|---|---|
| **In** | DOCPIPE_PROFILE and profiles/<name>/ (profile.py, prompts/<stage>/*.md, schema.sql); a stage's section text and Stage-2-linked caption; the vLLM server's GET /models response. |
| **Out** | .prompt_versions.json written next to a stage's output; resolved caption strings; PreflightError or SystemExit raised before a run starts -- no artifact files of its own. |
| **Resumes on** | check()/stale() in prompts.py flag stale results by comparing each prompt's sha256 to .prompt_versions.json; force a redo by deleting that file or the stage's own output artifact named in artifacts.py. |

This page is not one of the six numbered stages in the pipeline table. It documents the five modules every one of those stages is built on top of: `artifacts.py`, `profile.py`, `prompts.py`, `llm_preflight.py` and `captions.py`. Where the numbered stages turn a PDF into layout, then text, then refined text, then enrichments, then a database, these modules give all of them one shared vocabulary instead of five separate ones: one place that names an intermediate file, one place that resolves a profile's paths and overrides, one place that loads and versions a prompt, one check that a vLLM server can actually serve what a stage is about to ask of it, and one rule for where a table's real caption sits. A change to a numbered stage tends to touch one of these five files too, which is why they get their own page instead of being folded into each stage's write-up.

`profile.py` reads the `DOCPIPE_PROFILE` environment variable, imports `profiles/<name>/profile.py`, and from the `PROFILE` object it finds there derives every path a stage needs: `data/<name>/pdf`, `.../pdf/processed`, `<name>.db`, `faiss_index.bin`, and `profiles/<name>/prompts/`. `prompts.py` reads Markdown files under that prompts directory, `<stage>/<name>.md`, with optional YAML front matter for `temperature` and `max_tokens`, and writes one file back: `.prompt_versions.json`, dropped next to a stage's output by `record()`. `artifacts.py` contributes no I/O of its own -- it is the single list of the JSON filenames the numbered stages write under `<doc>/results/` (`pages.json`, `sections.json`, `page_transcription_report.json`, `sections_refined.json`, `refinement_report.json`, `visuals.json`, `document.json`), so a filename spelled out once cannot drift between the module that writes it and the module that reads it. `llm_preflight.py` reads one thing over the network, `GET {base_url}/models` on the vLLM server, and writes nothing but a log line. `captions.py` reads a section's assembled text and whatever caption Stage 2 already linked to a table or figure, and returns a resolved title string -- it touches no file and calls no model.

Three decisions here are easy to get backwards without reading the comments. First, `prompts.py` has no core fallback: `load()` raises `FileNotFoundError` if a profile has no prompt for a given id, rather than falling back to generic wording, because a prompt necessarily names the corpus it argues about and the language it answers in, and the core cannot guess either -- a fallback could only be some other project's prompt. Second, `Profile.component()` treats a profile module that does not exist as an absence (returns `None`) but re-raises one that exists and fails to import, because swallowing that second case would silently run the generic behaviour in place of a typo in the profile's own code, which is worse than crashing. `resolve_profile()` extends the same care to timing: prompts bind to a stage at import time, before argparse runs, so passing `--profile` on the command line without `$DOCPIPE_PROFILE` already set is refused with `SystemExit` rather than silently running the core prompts against a profile that meant to override them. Third, `captions.py` does not trust the caption block Stage 2 linked by proximity -- in a plan whose tables carry a rounding footnote, that link points at the footnote, not the sentence naming the table, and the effect was not cosmetic: 240 of 379 tuples from Kassel's twelve titled tables ended up carrying a year read off another table's caption. `resolve_title()` instead takes the text between the previous item's placeholder and this one, and never overwrites a caption that already looks like a caption, because a caption Stage 2 already linked is a link and this is only a guess.

Of the five, only `llm_preflight.py` costs anything external: one HTTP request to the server's `/models` endpoint, given 30 seconds and one retry by default, run once before a stage touches its first document. If the server does not answer, `assert_serving()` raises `PreflightError` immediately and the run stops before any document or GPU time is spent. If the server answers but does not serve the model named in `LLM_MODEL`/`VLM_MODEL`, the error lists what it actually serves. If it serves the right model but was started with too small a `--max-model-len`, the error names the flag and the token count to raise it to -- because the alternative, found the hard way, is a request rejected mid-run with the document simply keeping its unrefined text, a failure that showed up as a slow trickle of truncated replies (42 windows silently kept their raw text) hours into a run rather than as one error at the start. The other four modules cost nothing beyond a filesystem access: `profile.py` a Python import, `prompts.py` a file read and a sha256 hash, `captions.py` pure string matching, `artifacts.py` constants.

Staleness, not the passage of time, is what these modules track. `prompts.py` writes a prompt's sha256 next to a stage's output (`record()`), and `check()`/`stale()` compare that against the profile's current prompts, returning the ids that changed -- an absent `.prompt_versions.json` counts as changed too, because a result produced before prompts were versioned cannot be vouched for either. The check only tells a stage what is stale; forcing a redo means deleting `.prompt_versions.json` (or the artifact file itself, named in `artifacts.py`) so the stage's own resume logic sees the output as missing and reprocesses it -- the same missing-output rule the README describes for every stage. `profile_value()` in `profile.py` caches a profile's attribute the first time it is asked for, keyed by `(profile.name, module, attr)`, so editing a profile module mid-process and expecting the change to take effect will not work: it needs a fresh process.

The rest of the defensive code is aimed at failures that would otherwise ship silently. `Prompt.render()` raises `KeyError` on a missing placeholder and on an extra one, so a placeholder renamed in the prompt text, or a caller still passing an old keyword argument, fails immediately instead of sending a literal `{{foo}}` to the model. `_max_model_len()` in `llm_preflight.py` checks both `card.max_model_len` and `card.model_extra["max_model_len"]`, because the OpenAI client schema does not know the field vLLM reports it under, and a check that only looked in one place would pass preflight against a server it cannot actually verify. `Profile.__post_init__` rejects a profile name containing a slash, since the name flows straight into filesystem paths (`package_dir`, `root`) and a stray separator would silently write into the wrong directory tree. And `resolve_title()` caps a resolved caption at 300 characters and, where Stage 2 already stored its own caption, trims to where that stored text ends -- measured against the corpus's three textless plans, 23 of 169 tables resolved a title this way, and one of them ran 60 characters into the paragraph that followed before that trim was added.

## The modules

Verbatim from the module docstrings, generated by `scripts/build_docs.py`. Edit the docstring, not this page.

### `docpipe/artifacts.py`

artifacts.py – The per-document files under ``<doc>/results/``, in the order
the pipeline writes them.

One definition for all five modules: a filename spelled out in four config.py
files drifts, and the module that reads it is rarely the one that wrote it.

Author: Felix Vossel

### `docpipe/prompts.py`

prompts.py – Prompts belong to the profile, as Markdown per stage:

    profiles/<profile>/prompts/<stage>/<name>.md

There is no core default. A prompt names the corpus it is written for and the
language it answers in, and the core knows neither — a fallback here could only
be some other project's prompt, which is worse than a missing file.

Optional YAML front matter carries the model parameters that belong to the
prompt (temperature, max_tokens), so the two never drift apart.

Every prompt has a sha256 over its file. Stages record those hashes with their
output; when a hash no longer matches, the result was produced by a different
prompt and is stale (see `stale()`).

Author: Felix Vossel

### `docpipe/profile.py`

profile.py – A profile is everything a project contributes to the generic
pipeline: where its documents come from, what extra tables it needs, which
prompts it overrides and which filters its app offers.

The core never imports a profile; it receives one.

Author: Felix Vossel

### `docpipe/llm_preflight.py`

llm_preflight.py – Ask the server what it can do, before the first document.

A stage knows what one request costs it (`config.max_request_tokens()`); the
server knows how much context it was started with. Nothing compared the two,
so a `--max-model-len` that was too small surfaced as a slow trickle of
truncated replies hours into a run — 42 windows silently kept their raw text —
instead of as one error in second one.

Two questions, both answered by GET {base_url}/models:
  * does this server serve the model we are about to name?
  * is its context at least as large as our worst-case request?

### `docpipe/captions.py`

captions.py – What a caption looks like, and where a table's title really sits.

Stage 2 links a caption block to a table by distance, and in a plan whose
tables carry a rounding footnote it links the footnote. The sentence that
names the table then stands unlinked in the section text, a few words before
the table's own placeholder. Measured over Kassel: 15 of 89 tables were
captioned "Hinweis: Wegen der Rundung von Zahlenwerten ...".

Both ends of the pipeline need the same rule about that -- Stage 3, which is
assembling the section text when the placeholder is written, and the read
side, which has only the finished database. A second copy of the rule is how
the section text and the stored title start disagreeing, which is the defect
this module exists to fix. So it lives above both.

Author: Felix Vossel

[Back to the index](../README.md)
