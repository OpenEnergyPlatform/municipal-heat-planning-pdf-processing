"""
cli.py: `docpipe compile`, from the shapes of a graph to an extraction spec.

    docpipe compile spec --shapes shapes.ttl --ontology onto.owl --out draft.json
    docpipe compile check draft.json
    docpipe compile examples draft.json --db corpus.db --index faiss_index.bin
    docpipe compile apply draft.json --out profiles/mine/extraction_spec.json
    docpipe compile diff --shapes shapes.ttl --profile scenarios

`spec` drafts, `check` says what the draft still lacks, `examples` proposes
the missing examples from a processed corpus into a review file, `apply`
carries the accepted ones over and writes the spec once nothing is missing.
`diff` holds a spec somebody wrote by hand against the shapes and changes
nothing.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from ..profile import add_profile_argument, program, resolve_profile
from . import draft as drafting
from . import examples as proposing

log = logging.getLogger(__name__)

# Requests for one passage: the first, and one that says what was wrong
# with the reply to it.
ASK_ATTEMPTS = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.compile"),
        description="Draft an extraction spec from the shapes and the "
                    "ontology of a graph.")
    add_profile_argument(parser)
    levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
    parser.add_argument("--log-level", default="INFO", choices=levels)
    # The same two after the command, where they are also looked for; left
    # out there, they do not undo what stood before it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    common.add_argument("--log-level", default=argparse.SUPPRESS,
                        choices=levels, help=argparse.SUPPRESS)
    added = parser.add_subparsers(dest="command", required=True)

    class commands:
        @staticmethod
        def add_parser(name, **options):
            return added.add_parser(name, parents=[common], **options)

    def sources(sub):
        sub.add_argument("--shapes", nargs="+", required=True, type=Path,
                         help="SHACL files")
        sub.add_argument("--ontology", nargs="*", default=[], type=Path,
                         help="ontology files the labels and definitions "
                              "are read from")
        sub.add_argument("--lang", default="en",
                         help="language of the labels to prefer (default: "
                              "en)")

    spec = commands.add_parser("spec", help="draft a spec from shapes")
    sources(spec)
    spec.add_argument("--base", help="IRI the nodes of the graph live under")
    spec.add_argument("--out", required=True, type=Path)

    check = commands.add_parser("check", help="what a draft still lacks")
    check.add_argument("draft", type=Path)

    diff = commands.add_parser(
        "diff", help="what a spec says differently from the shapes")
    sources(diff)
    diff.add_argument("--spec", type=Path,
                      help="the spec (default: the profile's)")
    diff.add_argument("--json", type=Path, dest="json_out",
                      help="also write the differences as JSON")

    examples = commands.add_parser(
        "examples", help="propose the missing examples from a corpus")
    examples.add_argument("draft", type=Path)
    examples.add_argument("--db", type=Path, help="default: the profile's")
    examples.add_argument("--index", type=Path, help="default: the profile's")
    examples.add_argument("--review", type=Path,
                          help=f"default: <draft>.{proposing.REVIEW_FILE} "
                               f"beside the draft")
    examples.add_argument("--only", nargs="*", default=None,
                          help="parameters to propose for (default: every "
                               "one without an example)")
    examples.add_argument("--per-parameter", type=int, default=2,
                          help="proposals to keep per parameter")
    examples.add_argument("--documents", type=int, default=8,
                          help="documents to look in")

    apply = commands.add_parser(
        "apply", help="carry the accepted examples into the draft")
    apply.add_argument("draft", type=Path)
    apply.add_argument("--review", type=Path)
    apply.add_argument("--out", type=Path,
                       help="write the finished spec here once the draft "
                            "lacks nothing")
    return parser


def _read(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{path}: {exc}")


def _write(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")


def _sources(args) -> tuple:
    from . import shapes
    from .terms import Terms
    for path in (*args.shapes, *args.ontology):
        if not Path(path).is_file():
            raise SystemExit(f"{path} is not a file")
    found, prefixes = shapes.read(args.shapes)
    terms = Terms.read(args.ontology, args.lang) if args.ontology \
        else Terms(language=args.lang)
    return found, prefixes, terms


def draft_of(path: Path) -> dict:
    """The draft `compile spec` writes for one shapes file, with no ontology
    and the placeholder base: what `docpipe init --shapes` puts into a new
    project. A file that cannot be read, or that has no node with a property
    to ask for, stops it with the file's name; no draft is made up instead.
    rdflib is missing as ModuleNotFoundError, for the caller to say."""
    import rdflib  # noqa: F401  (a missing one is the caller's to say)

    from . import shapes
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f"{path} is not a file")
    try:
        found, prefixes = shapes.read([path])
    except Exception as exc:
        # The parsers of rdflib fail in no one family of errors (a cut-off
        # N3 file ends in an IndexError), so any failure of the reading is
        # the file's, named with its kind.
        raise SystemExit(f"{path} cannot be read as SHACL shapes "
                         f"({type(exc).__name__}: {exc})")
    raw = drafting.draft(found, prefixes, sources=(path.name,))
    if not raw["parameters"]:
        left_out = "; ".join(raw.get("_notes") or ())
        raise SystemExit(f"{path} holds no shape with a target class and a "
                         f"property to ask for ({len(found)} shape(s) read"
                         + (f"; {left_out}" if left_out else "") + ")")
    return raw


def _spec(args) -> int:
    found, prefixes, terms = _sources(args)
    raw = drafting.draft(found, prefixes, terms, base=args.base,
                         sources=tuple(path.name for path in args.shapes))
    _write(args.out, raw)
    open_points = drafting.todo(raw)
    print(f"{args.out}: {len(raw['parameters'])} parameter(s) from "
          f"{len(found)} shape(s), {len(open_points)} point(s) open")
    for note in raw.get("_notes") or ():
        print(f"  note: {note}")
    return 0


def _check(args) -> int:
    open_points = drafting.todo(_read(args.draft))
    for line in open_points:
        print(line)
    print(f"{len(open_points)} point(s) open" if open_points
          else "nothing open: this is a spec")
    return 1 if open_points else 0


def _diff(args) -> int:
    found, _prefixes, terms = _sources(args)
    path = args.spec
    if path is None:
        profile = resolve_profile(args)
        path = profile.component("extraction", "SPEC_PATH") if profile \
            else None
        if path is None:
            raise SystemExit("no spec: give --spec, or a --profile that "
                             "has one")
    rows = drafting.differences(found, _read(path), terms)
    kinds: dict = {}
    for row in rows:
        kinds.setdefault(row["kind"], []).append(row)
    for kind in sorted(kinds):
        print(f"{kind} ({len(kinds[kind])})")
        for row in kinds[kind]:
            who = row["parameter"] or "-"
            print(f"  {who:<28} {row['path'] or '-':<18} {row['detail']}")
    print(f"{len(rows)} difference(s); nothing was changed")
    if args.json_out:
        _write(args.json_out, {"spec": str(path), "differences": rows})
    return 0


def _corpus(args, profile):
    """(find, ask) over a processed corpus and the configured text model."""
    import sqlite3

    from .. import prompts
    from .. import usage as token_usage
    from ..extraction import runner
    from ..inference import db as inference_db
    from ..inference import faiss_store, query_cache

    db = args.db or (profile.db_path if profile else None)
    index_path = args.index or (profile.index_path if profile else None)
    if not db or not index_path:
        raise SystemExit("give --db and --index, or a --profile to take "
                         "them from")
    for path in (db, index_path):
        if not Path(path).is_file():
            raise SystemExit(f"{path} is not a file: `examples` reads a "
                             f"corpus that `docpipe chunk` has written")
    # The probes are embedded with the configured model: the same line the
    # harvest says when the index was built with another.
    runner.note_index_model(db, "compile")
    conn = inference_db.connect_readonly(db)
    conn.row_factory = sqlite3.Row
    index, id_to_pos = faiss_store.load_global_index(index_path)
    cache = query_cache.connect(Path(db).with_name("compile_query_cache.db"))
    retrieve = runner.make_retrieve(conn, index, id_to_pos, cache, limit=2)
    documents = [(row["id"], row["filename"]) for row in conn.execute(
        "SELECT id, filename FROM Documents WHERE is_current = 1 "
        "ORDER BY id LIMIT ?", (args.documents,))]
    if not documents:
        raise SystemExit(f"{db} holds no documents")

    def find(parameter: dict) -> list:
        """The passages to ask about, the best of every document before
        the second best of any: each document that was asked for can give
        a proposal."""
        probe = f"{parameter.get('label')}. {parameter.get('description')}"
        return proposing.by_rank(
            [[{"document": name, "text": source.text,
               "where": [source.owner_kind, source.owner_id]}
              for source in retrieve([probe], document, set())]
             for document, name in documents])

    prompt = prompts.load(proposing.EXAMPLE_PROMPT_ID, profile)
    client = runner._client()
    token_usage.begin("compile")
    return find, lambda parameter, passage: ask_for_example(
        client, prompt, parameter, passage)


def ask_for_example(client, prompt, parameter: dict, passage: str):
    """The reply to one example request as an object, or why there is none
    (a text). A reply that is not the one object that was asked for is
    asked again with what was wrong with it, as the harvest does; nothing
    is repaired."""
    from .. import providers
    from .. import usage as token_usage
    from ..extraction import runner
    from ..llm_preflight import request_extras

    meta = prompt.meta or {}
    numeric = parameter.get("value_type") in ("float", "int")
    name, shape = proposing.reply_shape(numeric)
    limit = int(meta.get("max_tokens", 1024))
    conversation = [{"role": "user", "content": json.dumps(
        proposing.payload(parameter, passage), ensure_ascii=False)}]
    cause = "not_served"
    for attempt in range(1, ASK_ATTEMPTS + 1):
        try:
            answer = client.chat.completions.create(
                model=runner.LLM_MODEL,
                messages=[{"role": "system", "content": prompt.text},
                          *conversation],
                temperature=float(meta.get("temperature", 0)),
                max_tokens=limit,
                extra_body=request_extras(),
                **providers.formatted("llm", name, shape))
        except Exception as exc:        # not served: no proposal from here
            log.warning("%s: request not served (%s)",
                        parameter.get("uri"), exc)
            cause = "not_served"
            continue
        token_usage.reply(answer, runner.LLM_MODEL)
        reply = answer.choices[0]
        found = runner._loads_object(reply.message.content)
        if isinstance(found, dict) and isinstance(found.get("tuples"), list):
            return found
        cause, correction = runner._reply_fault(reply, limit, key="tuples")
        log.warning("%s attempt %d: %s reply", parameter.get("uri"),
                    attempt, cause)
        conversation += [
            {"role": "assistant", "content": reply.message.content or ""},
            {"role": "user", "content": correction}]
    return cause


def _examples(args) -> int:
    raw = _read(args.draft)
    path = Path(args.review or proposing.review_path(args.draft))
    # What a person already accepted stays, and is not asked for again: a
    # second run must not cost the reading of the first.
    before = (_read(path).get("parameters") or {}) if path.is_file() else {}
    settled = {name for name, entry in before.items()
               if any(proposal.get("accept") is True
                      for proposal in entry.get("proposals") or ())}
    wanted = [parameter for parameter in proposing.lacking(raw, args.only)
              if parameter.get("uri") not in settled]
    if not wanted:
        print("every parameter has an example or an accepted proposal")
        return 0
    profile = resolve_profile(args)
    if profile is None:
        raise SystemExit("`examples` asks a model with the profile's "
                         "prompt: pass --profile")
    find, ask = _corpus(args, profile)
    review = proposing.propose(
        raw, find, ask, only=[parameter["uri"] for parameter in wanted],
        per_parameter=args.per_parameter,
        passages=max(6, 2 * args.documents))
    got = sum(1 for entry in review["parameters"].values()
              if entry["proposals"])
    review["parameters"] = {**before, **review["parameters"]}
    # A number is held to its quote the way this profile's documents write
    # one; `apply` holds it the same way.
    review["profile"] = getattr(profile, "name", None)
    proposing.write_review(path, review)
    print(f"{path}: proposals for {got} of {len(wanted)} parameter(s). "
          f"Read them, set \"accept\": true, then `docpipe compile apply`.")
    return 0


def _apply(args) -> int:
    raw = _read(args.draft)
    path = args.review or proposing.review_path(args.draft)
    review = _read(path)
    proposed_with = review.get("profile")
    profile = resolve_profile(args)
    if proposed_with and getattr(profile, "name", None) != proposed_with:
        raise SystemExit(
            f"{path} was proposed with profile {proposed_with!r}. A number "
            f"is held to its quote the way that profile's documents write "
            f"one, so it is applied with the same profile: add "
            f"--profile {proposed_with}")
    done, applied, problems = proposing.apply(raw, review)
    for line in problems:
        print(line)
    if problems:
        print("nothing was written")
        return 1
    _write(args.draft, done)
    print(f"{args.draft}: {len(applied)} example(s) carried over")
    open_points = drafting.todo(done)
    if args.out:
        if open_points:
            print(f"{args.out} not written: {len(open_points)} point(s) "
                  f"open (`docpipe compile check`)")
            return 1
        _write(args.out, drafting.finished(done))
        print(f"{args.out}: written")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s [%(levelname)s] %(name)s "
                               "%(message)s", datefmt="%H:%M:%S")
    try:
        return {"spec": _spec, "check": _check, "diff": _diff,
                "examples": _examples, "apply": _apply}[args.command](args)
    except ModuleNotFoundError as exc:
        if exc.name != "rdflib":
            raise
        # Shapes and ontologies are read with rdflib, which comes with the
        # graph extra and not with the package itself.
        raise SystemExit("compile reads shapes and ontologies with rdflib, "
                         "which is not installed: pip install "
                         "\"docpipe[kg]\"")


if __name__ == "__main__":
    sys.exit(main())
