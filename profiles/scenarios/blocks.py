"""
blocks.py: What only scenario papers ask (owner decisions 2026-11-12: the
plan of the general blocks, point 8, and in the evening every question is
"Ask the model" with a preset): the works a publication presents, compares
or cites, the work of a value, and the entry of a scenario's name in the
document's list. The page offers the presets beside the general ones where
this profile is open (`blocks.offered`), and a flow of another profile
cannot take them.

Author: Felix Vossel
"""
from docpipe.extraction.presets import VALUE_PLACE, Preset, i
from docpipe.extraction.targets import Target


def works(ask, counts, details: bool = True, each=None):
    """The works the document presents, compares or cites beside itself
    (owner decisions 2026-11-08, h, and 2026-11-09): every piece asked once
    which of its lines speak of another work and which line shows the rest
    are this publication's own, kept for the values found in it
    (`Plan.works_of`, `inherit_work`); each name of a work asked against
    the document's list of works, piece by piece in the plan's order, and
    each new work asked at its line for what the profile asks of a work
    (its title, its organisation, its year, its short name), side by side:
    values of that work, never of this publication, which the graph does
    not take. Without *details* only the list and the works of the pieces
    are built, as a pass needs them for the work of its values; *each* runs
    the pieces' requests side by side, the reader's way where None."""
    from docpipe.extraction.addressed import PieceWork
    from docpipe.extraction.pipeline import Batch, WorkItem
    from docpipe.extraction.reading import Read
    reader, plan = ask.reader, ask.plan
    doc = ask.doc
    if reader.works_field is None or "work" not in plan.names \
            or not ask.asks():
        return None
    field_ = reader.works_field or {}
    shown_field = {"name": field_.get("name", "work"),
                   "means": field_.get("means", "")}
    chunks = list(plan.pieces(False))
    asked = (each or reader.each)(chunks, lambda chunk: _piece(
        ask, shown_field, chunk, counts))
    names = plan.names["work"]
    new: list = []
    for chunk, got in zip(chunks, asked):
        if got is None:
            continue
        shown, held, own = got
        finds = []
        for one in held:
            before = len(names.entries)
            picked = reader.name_of(plan, "work", one.words, one, counts)
            if not picked:
                continue
            number = picked[0][1]
            if number > before:
                new.append((number, one, chunk))
            finds.append((reader.covered(chunk, one), number, one))
        plan.works_of[chunk.key] = PieceWork(finds, own, shown.evidence())
    plan.works_built = True
    if not details:
        reader._traced("works", plan.document_id,
                       works=len(names.entries), new=len(new))
        return None
    jobs = [(number, one, uri, question, chunk)
            for number, one, chunk in new
            for uri, question in (field_.get("fields") or {}).items()
            if reader.spec.by_uri.get(uri) is not None]
    made = reader.each(jobs, lambda job: _detail(
        ask, reader.spec.by_uri[job[2]], job[3], job[1],
        names.entries[job[0] - 1].label, counts, job[4]))
    reads: dict = {}
    for job, got in zip(jobs, made):
        if got is None:
            continue
        claim, source = got
        parameter = reader.spec.by_uri[job[2]]
        key = (parameter.uri, source.owner_kind, source.owner_id,
               source.text if claim.get("at") is None else None)
        read = reads.get(key)
        if read is None:
            read = reads[key] = Read(Batch(
                plan.document_id, parameter,
                [WorkItem(plan.document_id, parameter, source)],
                spec=reader.spec), [])
        read.claims.append(claim)
    reader._traced("works", plan.document_id,
                   works=len(names.entries), new=len(new))
    doc.reads.extend(reads.values())
    return None


def _piece(ask, shown_field: dict, chunk, counts):
    """(shown, [Found] of other works, the line of this publication's own
    or None) of one piece's request: the piece with the headings up to it
    and the title page; what does not hold is asked again with its reason
    (as often as the flow says). None where no answer came."""
    from docpipe.extraction import forms
    from docpipe.extraction.addressed import refusals
    from docpipe.extraction.addressed import joined
    reader, plan = ask.reader, ask.plan
    req = ask.request({"chunk": chunk, "works_field": shown_field})
    shape, example = forms.of(ask.reply, req)
    noted = {"parameter": "work", "kind": chunk.passage.kind,
             "owner": chunk.passage.source.owner_id, "chunk": chunk.index}
    reply = ask.ask(req, shape, example, counts, **noted)
    if not isinstance(reply, dict):
        return None
    held, refused = reader._finds(plan, req.shown, reply)
    own, why = reader.own_line(plan, req.shown, chunk, reply.get("own"))
    if why is not None:
        refused.append((reply.get("own"), why))
    for _, reason in refused:
        counts.fail(reason)
    for _ in range(reader.follow_ups()):
        if not refused:
            break
        reply = ask.follow(req, shape, example, reply, refusals(refused),
                           counts, **noted)
        if not isinstance(reply, dict):
            break
        more, refused = reader._finds(plan, req.shown, reply)
        held = joined(held, more)
        if own is None:
            own, why = reader.own_line(plan, req.shown, chunk,
                                       reply.get("own"))
            if why is not None:
                refused.append((reply.get("own"), why))
    return req.shown, held, own


def _detail(ask, parameter, question: str, one, label: str, counts, chunk):
    """One detail of a work, asked with the piece that names it, as the
    step "Ask a detail of a cited work" says (`work_detail`): (the claim of
    a value of *parameter* whose work is that work, with the line as its
    quote, the passage it is checked against); None where no line gives
    it. A heading is quoted as it is shown, and checked against itself.
    Where the piece names the work in short ("(Prognos 2021)", "[12]"),
    the reply may fetch the place that says it in full, such as the entry
    of the list of references, and the detail is asked again with it
    (owner decision 2026-11-12); its line is then the quote."""
    from docpipe.extraction import fields, forms
    from docpipe.extraction.addressed import (ANOTHER_WORK, field_shown,
                                              resolve)
    from docpipe.extraction.fields import READ
    from docpipe.extraction.general import nested
    from docpipe.extraction.units import letter_headings
    from docpipe.extraction.verify import flat
    reader, plan = ask.reader, ask.plan
    sub = nested(reader, "work_detail", plan, {
        "chunk": chunk, "detail_field": field_shown(parameter),
        "work": label, "question": question})
    req = sub.request()
    shape, example = forms.of(sub.reply, req, several=False,
                              more=sub.fetch)
    noted = {"parameter": parameter.uri, "coordinate": "work"}
    reply = sub.ask(req, shape, example, counts, **noted)
    with sub.prompting():
        reply, _payload, shown = reader.asked_with_fetched(
            sub.kind, plan, req.payload, reply, shape, example, counts,
            noted, [chunk] if chunk is not None
            else reader.anchor_of(plan, one), req.shown)
    finds = reader.coord_finds(reply)
    if not finds:
        return None
    got = resolve(shown, finds[0], plan.passages)
    if got.why is not None or got.passage is None:
        return None
    if got.letter == letter_headings():
        claim = {"source": "Q1", "value": got.words, "quote": got.quote}
        source = got.source
    else:
        claim = reader.claim(plan, parameter, got, counts)
        source = got.passage.source
    work = next((s for s in fields.axis_slots(parameter)
                 if s.name == "work"), None)
    if claim is None or work is None:
        return (claim, source) if claim is not None else None
    option = next((o.label for o in work.options
                   if o.uri == ANOTHER_WORK), ANOTHER_WORK)
    named = one.words if flat(one.words).casefold() \
        in flat(one.quote).casefold() else label
    claim.update({"work": option, "work_state": READ,
                  "work_raw": named, "work_quote": one.quote,
                  "work_source": [one.source.owner_kind,
                                  one.source.owner_id],
                  "work_window": ["piece", 1], "work_means": [label]})
    return claim, source


def works_for_pass(ask, counts) -> None:
    """The works of the pieces where their step did not run, as in a pass
    over the places an earlier harvest found, the passages nobody read, or
    a coordinate asked again (owner decision 2026-11-13, point 10): asked
    once, for the first value that asks its work, as the drawing's step
    asks them, without the details of new works; not where the drawing has
    no such step or it is off. The values that wait for them hold the
    run's threads, so the pieces are asked on threads of their own
    (`apart`)."""
    from docpipe.extraction import blocks
    from docpipe.extraction import flow as flow_map
    from docpipe.extraction.general import nested
    reader, plan = ask.reader, ask.plan
    with plan.key_lock(("works",)):
        if plan.works_built:
            return
        node = next((n for n, _frames in flow_map.on(reader.engine.tree)
                     if blocks.target_of(n) == "works"), None)
        if node is not None:
            works(nested(reader, "works", plan, {}, node=node), counts,
                  details=False, each=apart)
        plan.works_built = True


def apart(jobs: list, run) -> list:
    """*run(job)* for each of *jobs* on threads of their own, the results
    in the order of the jobs (as `runner.run_each`, which runs them on the
    run's threads): work that jobs on the run's threads wait for cannot
    wait for those threads itself. The requests still go through the run's
    one queue."""
    import concurrent.futures
    import contextvars
    from docpipe.extraction import runner
    jobs = list(jobs)
    if runner.AHEAD is None or runner.LIMIT is None or len(jobs) < 2:
        return [run(job) for job in jobs]
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(runner.LIMIT.maximum)),
            thread_name_prefix="works") as pool:
        futures = [pool.submit(contextvars.copy_context().run, run, job)
                   for job in jobs]
        try:
            return [future.result() for future in futures]
        except BaseException:
            for future in futures:
                future.cancel()
            raise


def work_of_value(ask, counts):
    """The work of one value (owner decisions 2026-11-09): the work of the
    line it stands in where its piece's work request named one
    (`inherit_work`), else asked as an entry of the document's list of
    works with the value's line, the headings and the title page, the
    answer the entry and the line that shows it; 0 leaves it `unstated`,
    and it is never searched. What does not hold is asked again with its
    reason (as often as the flow says), then stays `unbacked`."""
    from docpipe.extraction import forms, shows
    from docpipe.extraction.engine import Answer
    from docpipe.extraction.fields import UNBACKED
    from docpipe.extraction.targets import coord_notes
    reader, plan = ask.reader, ask.plan
    coord = ask.scope.get("coord")
    row, slot = coord.row, coord.slot
    if "work" not in plan.names:
        return None
    if not plan.works_built:
        works_for_pass(ask, counts)
    if reader.inherit_work(plan, row, slot) \
            or not shows.has_place(plan, row.claim):
        return Answer(True)
    names = plan.names["work"]
    req = ask.request({"options": [f"{number} {text}"
                                   for number, text in names.shown()]})
    shape, example = forms.of(ask.reply, req)
    noted = coord_notes(coord)
    reply = ask.ask(req, shape, example, counts, **noted)
    if not isinstance(reply, dict):
        return Answer(True)
    failed = reader.read_work(plan, row, slot, req.shown, reply)
    if failed:
        for _ in range(reader.follow_ups()):
            reply = ask.follow(req, shape, example, reply, failed, counts,
                               **noted)
            if not isinstance(reply, dict):
                break
            failed = reader.read_work(plan, row, slot, req.shown, reply)
            if not failed:
                break
        if failed:
            row.claim[f"{slot.name}_state"] = UNBACKED
    return Answer(True)


def value_names(ask, counts):
    """The entry of the document's list each row of a value names, a new
    one where it is not on the list yet (`addressed.Reader.named_value`),
    asked as this step says."""
    value = ask.scope.get("value")
    plan = ask.plan
    parameter = value.read.batch.parameter
    merged = getattr(parameter, "merged", None)
    if not merged or merged not in plan.names:
        return None
    for one in value.rows:
        ask.reader.named_value(plan, parameter, one, counts, node=ask.node)
    return None


TARGETS = (
    Target("works", "the works of the document",
           "Every chunk asked which of its lines name another work and "
           "which line shows the rest are this publication's own; each "
           "named work looked up in the document's list of works, each new "
           "one asked for its details.", works,
           gives=("chunk", "works_field"), forms=("works",),
           outputs=("values", "lists")),
    Target("work_detail", "a detail of a cited work",
           "A detail of a new work (its title, organisation, year) read at "
           "the line of the chunk that names it.", nested=True,
           gives=("chunk", "detail_field", "work", "question"),
           forms=("place",)),
    Target("work_of_value", "the work of a value",
           "The work a value belongs to: the work of its line where its "
           "chunk named one, else the entry of the document's list of works "
           "the model chooses, with the line that shows it; 0 is not "
           "stated.", work_of_value, gives=("options",),
           forms=("work_choice",)),
    Target("value_name", "the entry of a value's name",
           "The entry of the document's list of names each row of a value "
           "names, a new one where it is not on the list yet.", value_names,
           gives=("words", "find", "work", "options"), forms=("name",),
           outputs=("values",)),
)

# The question inside the works' answers that asks a new work's details.
NESTED_PRESETS = {"work_detail": "work_detail"}

PRESETS = (
    Preset(
        "works", "Ask the works of each chunk",
        "For each chunk the model says which lines speak of another work, a "
        "study or plan that is presented, compared or cited, and which line "
        "shows that the remaining lines belong to this publication. Each "
        "named work is looked up in the document's list of works, and each "
        "new work is asked for its details. Example: \"IEA (2021) Net Zero by "
        "2050\" in a comparison table becomes a work with its title, "
        "organisation and year. To change it: the inputs, the follow-up "
        "questions and the answers in the wrong form; what is asked about a "
        "new work is set under the works in the Spec tab.",
        "work",
        (i("field", "works_field", "field"),
         i("headings", "chunk", "headings"),
         i("title_page", "document", "title_page"),
         i("passage", "chunk", "own_lines")),
        "works", {"to": "works"},
        top=True, decided="2026-11-09, 2026-11-12", spec="works"),
    Preset(
        "work_detail", "Ask a detail of a cited work",
        "A new work named in a chunk is asked at that chunk for each detail "
        "the profile asks of a work: its title, its organisation, its year. "
        "Where the chunk names the work in short (\"(Prognos 2021)\", "
        "\"[12]\"), the answer may fetch the place that says it in full, "
        "such as the list of references. It stands after the step that asks "
        "the works; one asked where no such step stands is asked as its "
        "preset says. To change it: the inputs, what the model may ask to "
        "see (`fetches`, `fetch_rounds`) and the prompt `coord`.",
        "coord",
        (i("field", "detail_field", "field"),
         i("headings", "chunk", "headings"),
         i("title_page", "document", "title_page"),
         i("passage", "chunk", "own_lines"),
         i("work", "work", "always"),
         i("question", "question", "always")),
        "place", {"to": "work_detail"},
        values={"fetch": True}, attached=("work",),
        decided="2026-11-09, 2026-11-12", spec="works", rules_as="works"),
    Preset(
        "work_coordinate", "Ask a value's work",
        "Decides which work a value belongs to: where the value's line names "
        "a work, that is its work; otherwise the model chooses an entry of "
        "the document's list of works, and 0 means the work is not stated. It "
        "never searches the document. Example: a number in a row labelled "
        "\"IEA NZE\" belongs to that study, not to this publication. To "
        "change it: the inputs and the follow-up questions; the step needs "
        "the works in the Spec tab, and the prompt `coord` shapes the "
        "question.",
        "coord",
        VALUE_PLACE + (
            i("field", "field", "field"),
            i("question", "dimension", "question"),
            i("list", "options", "always")),
        "work_choice", {"to": "work_of_value"},
        needs=("coordinate",), decided="2026-11-09", spec="works"),
    Preset(
        "names", "Ask the list entry of a name",
        "Looks up a value that names a scenario in the document's list: the "
        "entry it is, or a new entry where the name is not on the list yet; 0 "
        "keeps the value without an entry. Words for several entries (\"all "
        "scenarios\") become one row per member where the field allows it. "
        "Example: \"NDC\" in a figure is the entry \"Nationally Determined "
        "Contributions\" named in chapter 2. To change it: the inputs, what "
        "the model may ask to see (`fetches`, `fetch_rounds`), and the keys "
        "`merged` and `takes_group` of the field in the Spec tab, which this "
        "step needs.",
        "names",
        (i("name", "words", "always"),
         i("lines", "find", "find_lines_if"),
         i("work", "work", "as_is"),
         i("list", "options", "always")),
        "name", {"to": "value_name"},
        values={"fetch": True}, needs=("value",),
        decided="2026-11-08, 2026-11-12", spec="names"),
)
