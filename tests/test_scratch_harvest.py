"""A column of one's own, from its folder to its table.

Promised: `docpipe column` writes the spec of one question, from a name and a
description, into a folder of its own, without an example; the spec is
finished only by an example that `docpipe compile` proposed AND a person
accepted; `docpipe extract --spec` reads that spec and not the profile's AND
writes only below the folder of the spec, with stamps of its own; the values
come out of `docpipe export` as a table with their quotes; and a run without
--spec reads the profile's spec as it always did.

The model is stubbed and nothing else of the run is.
"""
import csv
import hashlib
import io
import json
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docpipe import cli, column
from docpipe.compile import cli as compile_cli
from docpipe.compile import draft as drafting
from docpipe.compile import examples as proposing
from docpipe.extraction import fields, runner, scratch, trace
from docpipe.extraction.pipeline import Source, WorkItem, group_items
from docpipe.extraction.spec import fingerprints, load as load_spec
from docpipe.profile import load_profile
from docpipe.serve import cli as serve_cli

NAME = "Renovation rate"
DESCRIPTION = "How many percent of the buildings are renovated in one year"
URI = "renovation_rate"
PASSAGE = ("The renovation rate of the municipality is 1.2 % per year, "
           "measured over all residential buildings.")
QUOTE = "The renovation rate of the municipality is 1.2 % per year"
ANSWER = "1.2 % per year"


def _write(tmp_path, *words):
    """`docpipe column` through the one command, in a folder of its own."""
    home = tmp_path / "col"
    code = cli.main(["column", *(words or (NAME, DESCRIPTION)),
                     "--dir", str(home)])
    assert code == 0
    return home


def _finish(home, monkeypatch, accept=True, quote=QUOTE):
    """What the person does: `compile examples`, a reading, `compile apply`.
    Returns the exit code of the last one."""
    draft_file = home / scratch.DRAFT
    monkeypatch.setattr(compile_cli, "resolve_profile",
                        lambda args: NS(name="kwp"))
    monkeypatch.setattr(compile_cli, "_corpus", lambda args, profile: (
        lambda parameter: [{"document": "a.pdf", "where": ["section", 1],
                            "text": PASSAGE}],
        lambda parameter, passage: {"tuples": [
            {"value": ANSWER, "quote": quote}]}))
    assert compile_cli.main(["examples", str(draft_file)]) == 0
    review_file = proposing.review_path(draft_file)
    review = json.loads(review_file.read_text(encoding="utf-8"))
    for proposal in review["parameters"][URI]["proposals"]:
        proposal["accept"] = accept
    review_file.write_text(json.dumps(review), encoding="utf-8")
    return compile_cli.main(["apply", str(draft_file), "--out",
                             str(home / scratch.SPEC)])


# ---------------------------------------------------------------------------
# The command writes the spec of one question into a folder of its own
# ---------------------------------------------------------------------------

def test_the_command_writes_one_parameter_and_no_example(tmp_path, capsys):
    home = _write(tmp_path)
    raw = json.loads((home / scratch.DRAFT).read_text(encoding="utf-8"))
    (parameter,) = raw["parameters"]
    assert parameter["uri"] == URI
    assert parameter["label"] == NAME
    assert parameter["description"] == DESCRIPTION
    assert parameter["value_type"] == "text"
    assert "example" not in parameter, (
        "the example is a real passage a person has read, not a placeholder")
    said = capsys.readouterr().out
    assert f"{URI}.example: missing" in said
    # the folder keeps itself out of version control: it holds passages
    assert (home / ".gitignore").read_text(encoding="utf-8").strip() == "*"


def test_the_spec_is_the_one_the_loader_wants_once_it_has_an_example(
        tmp_path, monkeypatch):
    home = _write(tmp_path)
    # open until then, and the loader is the judge: no spec without it
    assert drafting.todo(json.loads(
        (home / scratch.DRAFT).read_text(encoding="utf-8")))
    assert _finish(home, monkeypatch) == 0
    spec = load_spec(home / scratch.SPEC)
    assert [p.uri for p in spec.parameters] == [URI]
    assert spec.parameters[0].example["tuples"][0]["quote"] == QUOTE
    assert not spec.parameters[0].is_numeric


def test_a_proposal_nobody_accepted_makes_no_spec(tmp_path, monkeypatch):
    home = _write(tmp_path)
    assert _finish(home, monkeypatch, accept=False) == 1
    assert not (home / scratch.SPEC).exists(), (
        "what a model proposed is no example until a person said so")


def test_an_accepted_example_whose_quote_is_not_in_its_source_is_refused(
        tmp_path, monkeypatch, capsys):
    """The checks of every value hold here too: nothing of this package
    loosens them for a column of one's own."""
    home = _write(tmp_path)
    draft_file = home / scratch.DRAFT
    _finish(home, monkeypatch, accept=False)
    review_file = proposing.review_path(draft_file)
    review = json.loads(review_file.read_text(encoding="utf-8"))
    proposal = review["parameters"][URI]["proposals"][0]
    proposal["accept"] = True
    proposal["tuples"][0]["quote"] = "a sentence the passage never says"
    review_file.write_text(json.dumps(review), encoding="utf-8")
    assert compile_cli.main(["apply", str(draft_file), "--out",
                             str(home / scratch.SPEC)]) == 1
    assert "does not carry its own evidence" in capsys.readouterr().out
    assert not (home / scratch.SPEC).exists()


def test_the_label_is_the_name_as_written_and_the_identifier_is_made_of_it():
    (parameter,) = column.draft("  Renovation   rate\n", "  " + DESCRIPTION
                                + " ")["parameters"]
    assert parameter["label"] == NAME
    assert parameter["description"] == DESCRIPTION
    assert parameter["uri"] == URI
    # two names, two identifiers: a name is not folded onto another's
    other = column.draft("Renovation rate (heat)", DESCRIPTION)
    assert other["parameters"][0]["uri"] == "renovation_rate_heat"


def test_a_name_without_a_letter_or_a_digit_writes_nothing(tmp_path):
    home = tmp_path / "col"
    with pytest.raises(SystemExit) as caught:
        cli.main(["column", "!!!", DESCRIPTION, "--dir", str(home)])
    assert "cannot name a column" in str(caught.value)
    assert not home.exists()


def test_a_gitignore_that_is_there_is_left_as_it_is(tmp_path):
    """The folder keeps itself out of version control, and does it only
    where nobody has said anything about it."""
    home = tmp_path / "col"
    home.mkdir()
    (home / ".gitignore").write_text("mine", encoding="utf-8")
    assert cli.main(["column", NAME, DESCRIPTION, "--dir", str(home)]) == 0
    assert (home / ".gitignore").read_text(encoding="utf-8") == "mine"
    assert (home / scratch.DRAFT).is_file()


def test_a_folder_that_has_its_draft_is_left_as_it_is(tmp_path):
    home = _write(tmp_path)
    draft_file = home / scratch.DRAFT
    draft_file.write_text("mine", encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        cli.main(["column", "Other", DESCRIPTION, "--dir", str(home)])
    assert "nothing was written" in str(caught.value)
    assert draft_file.read_text(encoding="utf-8") == "mine"


def test_a_description_too_short_for_the_loader_is_listed_as_open(
        tmp_path, capsys):
    _write(tmp_path, NAME, "too short")
    assert f"{URI}.description: 2 word(s)" in capsys.readouterr().out


def test_the_help_says_the_folder_is_not_for_the_graph(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["column", "--help"])
    assert caught.value.code == 0
    said = " ".join(capsys.readouterr().out.split())
    assert "serializer" in said and "profile's spec" in said
    # and it is one of the commands the command lists
    assert "column" in cli.OWN


def test_a_column_without_a_folder_goes_into_scratch_by_its_identifier(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["column", NAME, DESCRIPTION]) == 0
    assert cli.main(["column", "Other rate", DESCRIPTION]) == 0
    home = tmp_path / scratch.HOME
    assert (home / URI / scratch.DRAFT).is_file()
    assert (home / "other_rate" / scratch.DRAFT).is_file(), (
        "another name is another folder")
    assert (home / URI / ".gitignore").is_file()


def test_the_help_gives_the_length_the_loader_holds_a_description_to(
        capsys, monkeypatch):
    monkeypatch.setattr(drafting, "MIN_DESCRIPTION_WORDS", 11)
    with pytest.raises(SystemExit):
        cli.main(["column", "--help"])
    assert "at least 11 words" in " ".join(capsys.readouterr().out.split())


def test_the_next_steps_are_commands_that_exist_with_options_they_have(
        tmp_path, capsys):
    """Each printed line is typed as it stands: the options it names are the
    options its command has, and a path with a space is in quotes."""
    import shlex

    helps = {}

    def help_of(key, call):
        try:
            call()
        except SystemExit:
            pass
        helps[key] = capsys.readouterr().out

    # --profile is the option of `compile` itself, accepted after the
    # subcommand too, so the help of both is where it is looked for
    help_of("compile", lambda: compile_cli.main(["--help"]))
    top = helps.pop("compile")
    help_of("compile examples", lambda: compile_cli.main(["examples",
                                                         "--help"]))
    help_of("compile apply", lambda: compile_cli.main(["apply", "--help"]))
    helps = {key: top + text if key.startswith("compile") else text
             for key, text in helps.items()}
    help_of("extract", lambda: cli.main(["extract", "--help"]))
    help_of("export", lambda: serve_cli.export_main(["--help"]))

    home = tmp_path / "a folder"
    text = column._next_steps(home, "kwp")
    typed = [shlex.split(line, posix=False) for line in text.splitlines()
             if line.startswith("  docpipe ")]
    assert [words[1] if words[1] != "compile" else " ".join(words[1:3])
            for words in typed] == list(helps)
    for words in typed:
        key = " ".join(words[1:3]) if words[1] == "compile" else words[1]
        for option in (w for w in words if w.startswith("--")):
            assert option in helps[key], f"{key} has no {option}"
    quoted = f'"{home / scratch.HARVEST}"'
    assert quoted in text, "a path with a space is typed in quotes"
    assert f'"{home / scratch.SPEC}"' in text
    plain = column._next_steps(tmp_path / "col", "kwp")
    assert '"' not in plain.replace('\"accept\"', ""), (
        "and one without is not")


# ---------------------------------------------------------------------------
# The harvest
# ---------------------------------------------------------------------------

def _corpus(monkeypatch, tmp_path, harvester_stubbed):
    """(a function that runs `runner.main`, what the harvester was built
    with) over one document, with everything that is a server, an index or a
    card stubbed. With *harvester_stubbed* the harvester answers for the
    scratch parameter when the run's spec has it, and with nothing when it
    does not; without, the harvester is the real one and the caller stubs the
    model."""
    from docpipe.inference import faiss_store
    db = tmp_path / "corpus.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                is_current INTEGER DEFAULT 1);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                               content TEXT);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,
                             markdown TEXT, caption TEXT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,
                             description TEXT, caption TEXT);
        CREATE TABLE Scenarios (id INTEGER PRIMARY KEY, ar6_id INTEGER,
                                name TEXT);
        CREATE TABLE DocumentScenarios (document INTEGER, scenario INTEGER);
        INSERT INTO Documents VALUES (1, 'a.pdf', 1);
    """)
    conn.execute("INSERT INTO Sections VALUES (10, 1, ?)", (PASSAGE,))
    conn.commit()
    conn.close()

    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    monkeypatch.setenv("EXTRACT_ANCHORS", "0")
    monkeypatch.delenv("INFERENCE_DB_PATH", raising=False)
    monkeypatch.setattr(runner, "ATTACH_IMAGES", False)
    monkeypatch.setattr(runner, "BATCH_SOURCES", runner.BATCH_SOURCES)
    monkeypatch.setattr(runner, "assert_serving", lambda *a, **k: 40960)
    monkeypatch.setattr(runner, "set_model_len", lambda n: None)
    monkeypatch.setattr(runner, "start_limit", lambda: None)
    monkeypatch.setattr(runner, "watch_server", lambda *a, **k: None)
    monkeypatch.setattr(runner, "install_stop_handler", lambda: None)
    monkeypatch.setattr(runner, "prime_probe_cache", lambda *a, **k: 0)
    # The search sentence is a request to the model like any other. Left in,
    # the run asked whatever server the environment names and ended as that
    # server answered: once in two full runs a 5xx left the document unstamped.
    monkeypatch.setattr(runner, "document_anchor", lambda *a, **k: {})
    monkeypatch.setattr(runner, "make_more_sources",
                        lambda *a, **k: (lambda *x: []))
    monkeypatch.setattr(runner, "make_rest_of_document", lambda *a, **k: None)
    monkeypatch.setattr(runner, "make_parents", lambda *a, **k: None)
    monkeypatch.setattr(runner, "make_structure",
                        lambda *a, **k: (lambda d: []))
    monkeypatch.setattr(faiss_store, "load_global_index",
                        lambda p: (None, {}))
    monkeypatch.setattr(runner, "LLM_PARALLEL", 1)

    def make_retrieve(conn, index, id_to_pos, cache_conn, fetch, limit=0):
        return lambda probes, document_id, exclude: [Source(
            "section", 10, PASSAGE,
            {"document_id": document_id, "page": 1, "title": "Renovation"})]

    built: list = []

    def make_fieldwise(*a, **k):
        built.append(k)
        spec = k["spec"]

        def harvest(batch, prior=None):
            if URI not in spec.by_uri:
                return {"tuples": [], "status": "complete", "need_more": []}
            return {"tuples": [
                {"source": batch.label(0), "parameter": URI,
                 "parameter_state": fields.DERIVED,
                 "value": ANSWER, "value_raw": ANSWER, "quote": QUOTE}],
                "status": "complete", "need_more": []}
        return harvest

    monkeypatch.setattr(runner, "make_retrieve", make_retrieve)
    if harvester_stubbed:
        monkeypatch.setattr(runner, "fit_batch_sources", lambda *a, **k: 1)
        monkeypatch.setattr(runner, "make_fieldwise_harvester",
                            make_fieldwise)

    def run(out, *more):
        return runner.main([str(db), "no.index", str(out), "--image-root",
                            str(tmp_path), "--document", "1", *more])

    return run, built


@pytest.fixture
def corpus_run(monkeypatch, tmp_path):
    """The run with the harvester stubbed: what it was built with is `built`."""
    yield _corpus(monkeypatch, tmp_path, True)
    trace.close()


@pytest.fixture
def real_run(monkeypatch, tmp_path):
    """The run with the real harvester: only the model is a stub, so the
    value request, its reply schema, the sweep and the verifier are the real
    ones."""
    yield _corpus(monkeypatch, tmp_path, False)[0]
    trace.close()


def _files(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*")) if path.is_file()}


def _scratch_spec(tmp_path, monkeypatch) -> Path:
    home = _write(tmp_path)
    assert _finish(home, monkeypatch) == 0
    return home


def test_the_run_reads_the_spec_file_and_not_the_profiles_and_stamps_it(
        tmp_path, monkeypatch, corpus_run):
    run, built = corpus_run
    home = _scratch_spec(tmp_path, monkeypatch)
    spec_file = home / scratch.SPEC
    out = home / scratch.HARVEST
    assert run(out, "--spec", str(spec_file)) == 0

    assert [list(k["spec"].by_uri) for k in built] == [[URI]], (
        "the run was built from the spec file, not from the profile's")
    written = [json.loads(line) for line in (out / "a.jsonl").read_text(
        encoding="utf-8").splitlines()]
    tuples = [row for row in written if row.get("kind") == "tuple"]
    assert [row["parameter"] for row in tuples] == [URI]
    assert tuples[0]["quote"] == QUOTE

    stamp = json.loads((out / "a.stamp.json").read_text(encoding="utf-8"))
    assert stamp["spec"] == hashlib.sha256(
        spec_file.read_bytes()).hexdigest()
    own = fingerprints(load_spec(spec_file))
    assert {key: stamp[key] for key in own} == own
    profile_spec = load_spec(load_profile("kwp").component(
        "extraction", "SPEC_PATH"))
    kwp_only = set(fingerprints(profile_spec)) - set(own)
    assert kwp_only and not kwp_only & set(stamp), (
        "no key of the profile's questions is in this harvest's stamp")


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_run_without_the_option_reads_the_profiles_spec_as_before(
        tmp_path, monkeypatch, corpus_run, name):
    run, built = corpus_run
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    profile = load_profile(name)
    spec_path = Path(profile.component("extraction", "SPEC_PATH"))
    out = tmp_path / "profile_harvest"
    assert run(out) == 0

    assert [list(k["spec"].by_uri) for k in built] == [
        list(load_spec(spec_path).by_uri)]
    stamp = json.loads((out / "a.stamp.json").read_text(encoding="utf-8"))
    assert stamp["spec"] == hashlib.sha256(
        spec_path.read_bytes()).hexdigest()
    own = fingerprints(load_spec(spec_path))
    assert {key: stamp[key] for key in own} == own
    assert URI not in " ".join(stamp), "the column is nobody's question here"
    assert runner.run_spec_path(NS(spec=None), profile) \
        == profile.component("extraction", "SPEC_PATH")
    # and the option is what moves it: the same call with a file
    assert runner.run_spec_path(NS(spec=Path("mine.json")), profile) \
        == Path("mine.json")


def test_a_spec_file_never_writes_beside_the_profiles_harvest(
        tmp_path, monkeypatch, corpus_run):
    """The folder is the column's own. A profile's harvest lies elsewhere,
    and a run that was pointed at it is refused before it writes a byte:
    forced, it would have overwritten the profile's file of the document."""
    run, _built = corpus_run
    own = tmp_path / "profile_harvest"
    assert run(own) == 0
    before = _files(own)
    assert before

    home = _scratch_spec(tmp_path, monkeypatch)
    for target in (own, tmp_path / "elsewhere", home):
        with pytest.raises(SystemExit) as caught:
            run(target, "--spec", str(home / scratch.SPEC), "--force")
        assert caught.value.code == 2
    assert _files(own) == before
    assert not (tmp_path / "elsewhere").exists()
    assert not (home / "a.jsonl").exists(), (
        "the spec's own folder is not the harvest's: it holds the draft "
        "and the proposals")

    assert run(home / scratch.HARVEST, "--spec",
               str(home / scratch.SPEC), "--force") == 0
    assert _files(own) == before, "and a column of one's own leaves it alone"
    assert scratch.folder_problem(home / scratch.SPEC,
                                  home / scratch.HARVEST) is None
    assert scratch.folder_problem(home / scratch.SPEC, own) is not None


def test_a_folder_that_is_not_there_yet_is_judged_where_it_would_be(
        tmp_path, monkeypatch):
    """The first run of a column writes into a folder that does not exist,
    named relative to where the person stands: beside the spec, it is right.
    Before Python 3.10 `Path.resolve` leaves such a path relative on Windows
    and the folder was refused for not lying below the spec's."""
    home = _write(tmp_path)
    (home / scratch.SPEC).write_text("{}", encoding="utf-8")
    monkeypatch.chdir(home)
    assert scratch.folder_problem(scratch.SPEC, scratch.HARVEST) is None
    assert scratch.folder_problem(
        scratch.SPEC, Path(scratch.HARVEST) / "deeper") is None
    assert scratch.folder_problem(
        scratch.SPEC, Path("..") / home.name / scratch.HARVEST) is None
    # and what lies elsewhere is still refused, written however it is
    for elsewhere in (".", "..", Path("..") / "elsewhere",
                      Path("..") / home.name / ".." / "harvest"):
        assert scratch.folder_problem(scratch.SPEC, elsewhere), elsewhere


def test_the_stamps_of_a_column_are_its_own_and_say_which_question_moved(
        tmp_path, monkeypatch, corpus_run, caplog):
    run, built = corpus_run
    home = _scratch_spec(tmp_path, monkeypatch)
    spec_file = home / scratch.SPEC
    out = home / scratch.HARVEST
    assert run(out, "--spec", str(spec_file)) == 0
    assert run(out, "--spec", str(spec_file)) == 0
    assert len(built) == 1, "a document that is current is not read again"

    raw = json.loads(spec_file.read_text(encoding="utf-8"))
    raw["parameters"][0]["description"] += " and no others at all"
    spec_file.write_text(json.dumps(raw), encoding="utf-8")
    caplog.clear()
    assert run(out, "--spec", str(spec_file)) == 0
    assert len(built) == 1, "a stale document waits until it is asked for"
    assert f"older parameter/{URI}" in " ".join(
        record.getMessage() for record in caplog.records)
    assert run(out, "--spec", str(spec_file), "--force-stale") == 0
    assert len(built) == 2, "a changed question reads the document again"


def test_the_passes_over_a_harvest_read_the_spec_it_was_made_with(
        tmp_path, monkeypatch, corpus_run, caplog):
    """--recheck and --remap read the spec file too. Under the profile's spec
    the parameter of the column is one nobody asks for: the pass keeps its
    rows as they are and counts them as unknown, and holds them to nothing."""
    caplog.set_level(logging.INFO)
    run, _built = corpus_run
    home = _scratch_spec(tmp_path, monkeypatch)
    spec_file = str(home / scratch.SPEC)
    out = home / scratch.HARVEST
    assert run(out, "--spec", spec_file) == 0

    def said(*options):
        caplog.clear()
        assert run(out, *options) == 0
        return " ".join(record.getMessage() for record in caplog.records)

    for options in (["--recheck", "--keep-stamps"], ["--remap"]):
        assert "unknown parameter kept" not in said(
            *options, "--spec", spec_file)
        assert "unknown parameter kept" in said(*options), (
            "the same pass without the file reads another spec")


def test_serialize_says_it_does_not_read_the_spec_file(tmp_path, monkeypatch,
                                                      corpus_run, caplog):
    """Said and not refused: the graph is the profile's, so --serialize reads
    the profile's spec and hands the harvest in OUT on as it always did. It
    says so, because a flag that is dropped without a word reads as honoured."""
    from docpipe.extraction import serialize
    run, built = corpus_run
    home = _scratch_spec(tmp_path, monkeypatch)
    harvest = home / scratch.HARVEST
    assert run(harvest, "--spec", str(home / scratch.SPEC)) == 0
    handed = []
    monkeypatch.setattr(serialize, "run", lambda folder, out, writer,
                        provenance=None, **more: handed.append(folder)
                        or {"a": 1})
    monkeypatch.setattr(serialize, "validate", lambda *a, **k: None)
    caplog.set_level(logging.WARNING)

    def said(*options):
        caplog.clear()
        assert run(harvest, *options, "--serialize",
                   str(tmp_path / "graph.ttl")) == 0
        return " ".join(record.getMessage() for record in caplog.records)

    assert "--spec is not read here" in said(
        "--spec", str(home / scratch.SPEC))
    assert handed == [harvest], "and the serializer got what it always gets"
    assert len(built) == 1, "nothing was harvested on the way"
    assert "--spec is not read here" not in said(), (
        "without the option there is nothing to say")


def test_the_option_is_in_the_help_with_what_it_is_not_for(capsys):
    assert cli.main(["extract", "--help"]) == 0
    said = " ".join(capsys.readouterr().out.split())
    assert "--spec FILE" in said
    assert "not meant for the graph" in said and "serializer" in said
    assert "does not read --spec" in said


# ---------------------------------------------------------------------------
# The real request path
# ---------------------------------------------------------------------------

class Client:
    """The model, as far as a request goes. A request for the sentence a
    document is searched with gets one; a request that shows sources gets
    what *answer* makes of the label of the first."""

    def __init__(self, answer):
        self.requests = []
        self.answer = answer
        self.chat = NS(completions=NS(create=self._create))

    @staticmethod
    def shown(request) -> dict:
        """What the request showed: its first user message, as an object."""
        user = request["messages"][1]["content"]
        return json.loads(user if isinstance(user, str) else user[0]["text"])

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        shown = self.shown(kwargs)
        body = ({"phrase": QUOTE} if "sources" not in shown
                else self.answer(shown["sources"][0]["id"]))
        message = NS(content=json.dumps(body, ensure_ascii=False))
        return NS(choices=[NS(message=message, finish_reason="stop")],
                  usage=NS(prompt_tokens=1, completion_tokens=1))

    def value_requests(self) -> list:
        """What the requests showed that carried the quantities of the
        spec."""
        return [shown for shown in map(self.shown, self.requests)
                if "quantities" in shown]


def _read_with(monkeypatch, answer):
    """A client for the next run, and the real harvester behind it."""
    client = Client(answer)
    monkeypatch.setattr(runner, "_client", lambda: client)
    return client


def _rows(folder: Path) -> list:
    return [json.loads(line) for line in (folder / "a.jsonl").read_text(
        encoding="utf-8").splitlines()]


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_column_is_read_through_the_real_request_path(
        tmp_path, monkeypatch, real_run, name):
    """The spec of one text parameter and no axes goes through the value
    request, the reply schema and the verifier of each profile as any spec
    does: the request names the column and nobody else's parameter, and the
    value comes out read, with its quote, derived because it is the spec's
    only text parameter."""
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    home = _scratch_spec(tmp_path, monkeypatch)
    client = _read_with(monkeypatch, lambda label: {
        "tuples": [{"source": label, "value": ANSWER, "value_raw": ANSWER,
                    "quote": QUOTE}],
        "status": "complete", "need_more": []})
    out = home / scratch.HARVEST
    assert real_run(out, "--spec", str(home / scratch.SPEC),
                    "--profile", name) == 0

    (asked,) = client.value_requests()
    assert [q["uri"] for q in asked["quantities"]] == [URI]
    rows = _rows(out)
    (value,) = [row for row in rows if row.get("kind") == "tuple"]
    assert (value["parameter"], value["value"], value["quote"])         == (URI, ANSWER, QUOTE)
    assert value["parameter_state"] == fields.DERIVED
    (state,) = [row for row in rows if row.get("kind") == "parameter_state"]
    assert state["parameter"] == URI and state["state"] == fields.READ


def test_a_column_is_held_to_its_quote_like_every_value(
        tmp_path, monkeypatch, real_run):
    """The case that violates it by construction: the model cites a sentence
    the passage never says. The value is refused and the column ends not read;
    nothing of this package let it through."""
    home = _scratch_spec(tmp_path, monkeypatch)
    _read_with(monkeypatch, lambda label: {
        "tuples": [{"source": label, "value": ANSWER, "value_raw": ANSWER,
                    "quote": "a sentence the passage never says"}],
        "status": "complete", "need_more": []})
    out = home / scratch.HARVEST
    assert real_run(out, "--spec", str(home / scratch.SPEC)) == 0
    rows = _rows(out)
    assert not [row for row in rows if row.get("kind") == "tuple"]
    assert [row for row in rows if row.get("kind") == "refusal"]
    (state,) = [row for row in rows if row.get("kind") == "parameter_state"]
    assert state["state"] != fields.READ


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

def test_the_table_comes_out_of_export_with_the_quote(tmp_path, monkeypatch,
                                                      corpus_run):
    run, _built = corpus_run
    home = _scratch_spec(tmp_path, monkeypatch)
    out = home / scratch.HARVEST
    assert run(out, "--spec", str(home / scratch.SPEC)) == 0
    table = home / scratch.TABLE
    assert serve_cli.export_main([str(out), "--out", str(table)]) == 0
    lines = list(csv.DictReader(io.StringIO(
        table.read_text(encoding="utf-8"))))
    assert len(lines) == 1, "one value, one line"
    line = lines[0]
    assert line["parameter"] == URI and line["value"] == ANSWER
    assert line["quote"] == QUOTE and line["level"] in ("A", "B", "C")

    # a harvest with nothing in it is a table with no line, not a table
    # with a made-up one
    empty = tmp_path / "empty"
    assert run(empty) == 0
    nothing = tmp_path / "nothing.csv"
    assert serve_cli.export_main([str(empty), "--out", str(nothing)]) == 0
    assert list(csv.DictReader(io.StringIO(
        nothing.read_text(encoding="utf-8")))) == []


# ---------------------------------------------------------------------------
# What kwp's frame and slice do to a column of its own
# ---------------------------------------------------------------------------

def _harvester_under_kwp(monkeypatch, spec):
    """The real field-wise harvester, under the frame and the slice of the
    kwp profile, with the two model calls stubbed. Returns (what it was
    asked, a function that harvests one batch)."""
    profile = load_profile("kwp")
    gate = profile.component("extraction", "SLICE") or {}
    frame = fields.frame_slots(spec, profile.component("extraction", "FRAME"))
    asked: list = []
    row = {"source": "Q1", "parameter": URI, "value": ANSWER,
           "value_raw": ANSWER, "quote": QUOTE}
    monkeypatch.setattr(runner, "make_harvester", lambda *a, **kw: (
        lambda batch, prior=None: {"tuples": [dict(row)],
                                   "status": "complete", "need_more": []}))

    def make_asker(image_root=None):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None, bases=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            asked.extend(slot.name for slot in slots)
            return {"fields": {slot.name: {"answers": {}} for slot in slots}}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    harvest = runner.make_fieldwise_harvester(spec=spec, slice_gate=gate,
                                              frame_axes=frame)
    batch = group_items([WorkItem(7, None, Source(
        "section", 1, PASSAGE, {"document_id": 7, "page": 1}))],
        max_sources=runner.BATCH_SOURCES)[0]
    return asked, frame, lambda: harvest(batch)


def test_kwps_frame_and_slice_ask_a_column_with_no_such_axes_nothing(
        tmp_path, monkeypatch):
    """Reported, not special-cased. The frame is the first parameter that
    has every frame coordinate, the gate holds the coordinates it names, and
    a column of one's own has neither: so the profile's settings neither ask
    it a frame nor drop one of its values."""
    home = _scratch_spec(tmp_path, monkeypatch)
    spec = load_spec(home / scratch.SPEC)
    asked, frame, harvest = _harvester_under_kwp(monkeypatch, spec)
    assert frame == [], "no frame: no pair is found and no pair is asked"
    reply = harvest()
    assert asked == [], "no coordinate is asked: the column has none"
    (row,) = reply["tuples"]
    assert row["parameter_state"] == fields.DERIVED
    assert not any(key.endswith("_state") and row[key] == fields.OUT_OF_SLICE
                   for key in row), "and the gate dropped nothing"


def test_the_same_settings_do_bite_a_column_that_names_their_axes(
        tmp_path, monkeypatch):
    """The case that violates the claim above by construction: give the
    column the axes the profile's settings are about, and the frame and the
    gate are there. Without it, the test above would pass on a harvester
    that never looked at them."""
    home = _scratch_spec(tmp_path, monkeypatch)
    raw = json.loads((home / scratch.SPEC).read_text(encoding="utf-8"))
    raw["parameters"][0]["axes"] = {
        "scenario": {"type": "text", "question": "Which scenario is it?"},
        "year": {"type": "int", "question": "Which year is it?"},
        "quantity": {"type": "text", "question": "Which quantity is it?"}}
    asked, frame, harvest = _harvester_under_kwp(monkeypatch,
                                                 load_spec(raw))
    assert [slot.name for slot in frame] == ["scenario", "year"]
    harvest()
    assert "quantity" in asked, "the gate asks its coordinate first"
