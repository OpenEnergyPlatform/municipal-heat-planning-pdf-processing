"""A table the layout cut in parts is one table (owner decision 2026-11-06):
a table may continue the table before it when that one stands on its page or
the page before and no section starts between them on its page; it is asked
after that table, shown its caption and head and what stands between them,
and the merge joins each part the model found to continue it.

Built on the shape of a real case: a table of municipal buildings in three
parts on two pages, the second part on the page of the first, after the end
of another table on the page before. Each promise has a case that breaks it
by construction beside the one that keeps it."""
import copy

from docpipe.visuals import continuation

HEAD = "| Liegenschaft | Wärmeverbrauch |\n| --- | --- |"
END = {"id": "p112_tbl0", "page_number": 113,
       "caption": "Denkmalgeschützte Gebäude",
       "markdown": "| Adresse | Gebäude |\n| --- | --- |\n"
                   "| Hauptstraße 1 | Wohnhaus |"}
START = {"id": "p113_tbl1", "page_number": 114,
         "caption": "Tabelle 5: Kommunale Liegenschaften",
         "markdown": HEAD + "\n| Kita Nord | 61.400 |"}
SECOND = {"id": "p113_tbl0", "page_number": 114,
          "markdown": HEAD + "\n| Schule Süd | 230.000 |"}
THIRD = {"id": "p114_tbl0", "page_number": 115,
         "markdown": HEAD + "\n| Gemeinschaftsschule | 910.000 |"}


def section(*tables, segments=None):
    tables = [copy.deepcopy(t) for t in tables]
    if segments is None:
        segments = [
            {"page": 113, "kind": "table", "ref": "p112_tbl0"},
            {"page": 113, "kind": "text", "text": "Anhang | Seite 113"},
            {"page": 114, "kind": "table", "ref": "p113_tbl1"},
            {"page": 114, "kind": "table", "ref": "p113_tbl0"},
            {"page": 114, "kind": "text", "text": "Anhang | Seite 114"},
            {"page": 115, "kind": "table", "ref": "p114_tbl0"}]
    return {"title": "Anhang", "page_number": 108, "segments": segments,
            "tables": tables, "figures": []}


def test_a_table_may_continue_the_table_before_on_its_page_or_the_one_before():
    sections = [section(END, START, SECOND, THIRD)]
    found = continuation.links(sections)
    assert found == {
        "p113_tbl1": {"after": "p112_tbl0", "between": "Anhang | Seite 113"},
        "p113_tbl0": {"after": "p113_tbl1", "between": ""},
        "p114_tbl0": {"after": "p113_tbl0", "between": "Anhang | Seite 114"}}
    assert continuation.runs(sections, found) == [
        [(0, 0), (0, 1), (0, 2), (0, 3)]]
    # A section that starts on its page stands between, and so does a page:
    # each starts a run of its own.
    later = section(START, segments=[{"page": 114, "kind": "table",
                                      "ref": "p113_tbl1"}])
    later["page_number"] = 114
    sections = [section(END, segments=[{"page": 113, "kind": "table",
                                        "ref": "p112_tbl0"}]), later]
    assert continuation.links(sections) == {}
    far = section(END, dict(START, page_number=115), segments=[
        {"page": 113, "kind": "table", "ref": "p112_tbl0"},
        {"page": 115, "kind": "table", "ref": "p113_tbl1"}])
    assert continuation.links([far]) == {}
    assert continuation.runs([far], {}) == [[(0, 0)], [(0, 1)]]
    # What else stands between them is shown, a figure by its caption.
    figure = section(END, START, segments=[
        {"page": 113, "kind": "table", "ref": "p112_tbl0"},
        {"page": 113, "kind": "figure", "ref": "p112_img0"},
        {"page": 114, "kind": "table", "ref": "p113_tbl1"}])
    figure["figures"] = [{"id": "p112_img0", "caption": "Abbildung 9: Lage"}]
    assert continuation.links([figure])["p113_tbl1"]["between"] \
        == "[Figure: Abbildung 9: Lage]"


def asker(answers):
    """transcribe(item, before) -> the item read, continuing the table
    before it where *answers* says so; [(id, before)] as asked."""
    asked = []

    def transcribe(item, before):
        asked.append((item["id"], before))
        out = dict(item)
        if before is not None:
            out["after"] = before["after"]
            out["continues"] = answers.get(item["id"], False)
        return out
    return transcribe, asked


def test_a_part_is_asked_after_the_table_it_may_continue_shown_its_head():
    sections = [section(END, START, SECOND, THIRD)]
    found = continuation.links(sections)
    items = sections[0]["tables"]
    transcribe, asked = asker({"p113_tbl0": True, "p114_tbl0": True})
    done = continuation.transcribe_run(items, found, {}, transcribe)
    assert [(one, before and (before["caption"], before["head"]))
            for one, before in asked] == [
        ("p112_tbl0", None),
        # The start of the table is asked against the end of another; the
        # model said it does not continue it, so it is shown to the rest.
        ("p113_tbl1", (END["caption"],
                       "| Adresse | Gebäude |\n| --- | --- |")),
        ("p113_tbl0", (START["caption"], HEAD)),
        ("p114_tbl0", (START["caption"], HEAD))]
    assert [d.get("continues") for d in done] == [None, False, True, True]
    # A cached part asked against the table right before it stands; one
    # from before this was asked, or asked against another, is asked again.
    cached = {d["id"]: d for d in done}
    cached["p114_tbl0"] = dict(THIRD)
    transcribe, asked = asker({"p114_tbl0": True})
    continuation.transcribe_run(items, found, cached, transcribe)
    assert [one for one, _ in asked] == ["p114_tbl0"]
    # A table before without a transcription shows nothing: asked alone.
    failed = [dict(END, markdown=None), *items[1:]]
    transcribe, asked = asker({})
    continuation.transcribe_run(failed, found, {}, transcribe)
    assert asked[1] == ("p113_tbl1", None)


def test_the_merge_joins_each_part_to_the_table_it_continues():
    second = dict(SECOND, after="p113_tbl1", continues=True,
                  bbox=[[10, 20, 500, 700]])
    third = dict(THIRD, after="p113_tbl0", continues=True)
    start = dict(START, after="p112_tbl0", continues=False)
    sections = [section(END, start, second, third)]
    assert continuation.join(sections) == 2
    tables = sections[0]["tables"]
    assert [t["id"] for t in tables] == ["p112_tbl0", "p113_tbl1"]
    assert tables[1]["markdown"] == "\n".join([
        HEAD, "| Kita Nord | 61.400 |",
        "| Schule Süd | 230.000 |",
        "| Gemeinschaftsschule | 910.000 |"])
    assert tables[1]["parts"] == [
        {"id": "p113_tbl0", "page_number": 114, "bbox": [[10, 20, 500, 700]]},
        {"id": "p114_tbl0", "page_number": 115}]
    assert tables[0]["markdown"] == END["markdown"]
    # A part the model found not to continue the table before it stays a
    # table of its own, and so does one whose start has no transcription.
    sections = [section(END, start, dict(second, continues=False), third)]
    assert continuation.join(sections) == 1
    assert [t["id"] for t in sections[0]["tables"]] == [
        "p112_tbl0", "p113_tbl1", "p113_tbl0"]
    sections = [section(END, dict(start, markdown=None), second)]
    assert continuation.join(sections) == 0
