"""
A reply may fetch the section a line stands in, and the part of a figure's
picture it names (owner decision 2026-11-17, from the literature on reading
long documents and figures: after a hit the model reads its whole section;
it cuts a region out of a picture to read what is too small in the whole).

The promises, each with a case that breaks it by construction:

1. `{"get": "section"}` brings the pieces of the section the first shown
   piece stands in, from the section's start in the order of the plan, those
   not shown yet, AND as many as the rule `fetch_section_pieces` says, AND a
   table stands in the section its placeholder stands in, AND a letter of
   the request names the piece whose section comes, AND where the rule
   `fetches` has no "section" the reply form does not offer it and nothing
   is fetched.
2. A region is four numbers from 0 to 1000, the right one past the left one
   and the bottom one past the top one; anything else names none. The reply
   form offers a region only where the picture may be asked and the rule
   `image_regions` is on.
3. The runner cuts the region out of the stored crop and sends it at the
   size of a whole picture, AND the whole picture and a part of it are two
   pictures of its store.
"""
import base64
import io

import pytest

from docpipe import rules
from docpipe.extraction import addressed, runner
from docpipe.extraction.pipeline import Source
from docpipe.extraction.units import Shown

from test_addressed import Model, plan_of, reader_of

LONG = Source("section", 2, " ".join(
    f"Satz {n} des Kapitels." for n in range(1, 9)),
    {"document_id": 7, "page": 2, "section_title": "Bilanz"})
OTHER = Source("section", 4, "Ein anderes Kapitel. Mit zwei Sätzen.",
               {"document_id": 7, "page": 5, "section_title": "Ziele"})
TABLE = Source("table", 3, "| Träger | 2020 |\n| --- | --- |\n"
                           "| Erdgas | 120 |",
               {"document_id": 7, "page": 3, "parent_section": 2,
                "block_id": "p3_tbl0"})


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def keys(pieces):
    return [piece.key for piece in pieces]


def section_of(plan, owner):
    return [piece for piece in plan.pieces(False) if piece.owner == owner]


def test_a_section_comes_from_its_start_as_far_as_the_rule_says():
    plan = plan_of(LONG, TABLE, OTHER, chunk_units=2)
    own = section_of(plan, ("section", 2))
    assert len(own) == 4
    reader = reader_of(Model())
    last = own[-1]
    with rules.overlaid(fetch_section_pieces=2):
        got = reader.fetch(plan, [{"get": "section"}], [last], {last.key})
    assert keys(got) == keys(own[:2])
    # The pieces shown before are not shown again, and the number is the
    # rule's: the breaks by construction.
    with rules.overlaid(fetch_section_pieces=9):
        got = reader.fetch(plan, [{"get": "section"}], [last],
                           {last.key, own[0].key})
    assert keys(got) == keys(own[1:3])


def test_a_table_stands_in_the_section_of_its_placeholder():
    plan = plan_of(LONG, TABLE, OTHER, chunk_units=2)
    (table,) = section_of(plan, ("table", 3))
    reader = reader_of(Model())
    got = reader.fetch(plan, [{"get": "section"}], [table], {table.key})
    assert {piece.owner for piece in got} == {("section", 2)}
    by_name = reader.fetch(plan, [{"get": "section", "id": "p3_tbl0"}],
                           section_of(plan, ("section", 4)), set())
    assert keys(by_name) == keys(got)
    # A table that names no section of its own brings none.
    lone = Source("table", 6, "| a | b |\n| --- | --- |\n| 1 | 2 |",
                  {"document_id": 7, "page": 6})
    plan = plan_of(LONG, lone, chunk_units=2)
    (piece,) = section_of(plan, ("table", 6))
    assert reader.fetch(plan, [{"get": "section"}], [piece], set()) == []


def test_a_letter_names_the_piece_whose_section_comes():
    plan = plan_of(LONG, TABLE, OTHER, chunk_units=2)
    reader = reader_of(Model())
    shown = Shown()
    other = section_of(plan, ("section", 4))
    (letter,) = reader.show_fetched(plan, shown, other)
    first = section_of(plan, ("section", 2))[:1]
    got = reader.fetch(plan, [{"get": "section", "id": letter}], first,
                       set(), shown=shown)
    assert keys(got) == keys(other)
    # Without the letter the first shown piece's section comes.
    got = reader.fetch(plan, [{"get": "section"}], first, set(), shown=shown)
    assert {piece.owner for piece in got} == {("section", 2)}


def test_a_section_is_fetched_only_where_the_rule_allows_it():
    assert "section" in addressed.fetches()
    plan = plan_of(LONG, chunk_units=2)
    piece = section_of(plan, ("section", 2))[-1]
    reader = reader_of(Model())
    with rules.overlaid(fetches=["next", "previous"]):
        assert "section" not in addressed.more_schema()["items"][
            "properties"]["get"]["enum"]
        assert reader.fetch(plan, [{"get": "section"}], [piece],
                            {piece.key}) == []


@pytest.mark.parametrize("raw, region", [
    ([0, 700, 1000, 1000], [0, 700, 1000, 1000]),
    (["10", "20", "30", "40"], [10, 20, 30, 40]),
    ([0, 700, 1000], None),
    ([500, 0, 500, 1000], None),
    ([0, 800, 1000, 700], None),
    ([0, 0, 1001, 1000], None),
    ([-1, 0, 10, 10], None),
    ("0,0,10,10", None),
    (None, None),
])
def test_a_region_is_four_numbers_inside_the_picture(raw, region):
    assert addressed.region_of({"get": "image", "region": raw}) == region


def test_the_reply_form_offers_a_region_where_the_rule_is_on():
    def offered(**values):
        with rules.overlaid(**values):
            return "region" in addressed.more_schema(True)["items"][
                "properties"]
    assert offered()
    assert not offered(image_regions=False)
    # No picture may be asked, no region either.
    assert "region" not in addressed.more_schema(False)["items"][
        "properties"]


def picture(tmp_path):
    """A crop 2000 by 1000 pixels: white on the left half, black on the
    right half."""
    from PIL import Image
    img = Image.new("RGB", (2000, 1000), "white")
    img.paste((0, 0, 0), (1000, 0, 2000, 1000))
    path = tmp_path / "p4_img0.png"
    img.save(path)
    return str(path)


def sent(url):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def test_a_region_is_cut_out_and_sent_at_the_size_of_a_whole_picture(
        tmp_path):
    path = picture(tmp_path)
    runner._IMAGES.clear()
    whole = sent(runner._image_data_url(path))
    assert whole.size == (1280, 640)
    part = sent(runner._image_data_url(path, [500, 0, 1000, 1000]))
    # The right half, 1000 by 1000 pixels in the crop, enlarged to the
    # longer side of a whole picture, and black throughout.
    assert part.size == (1280, 1280)
    assert part.convert("L").getextrema() == (0, 0)
    assert len(runner._IMAGES) == 2
    # The break by construction: the same region asked again is the
    # picture made before.
    assert runner._image_data_url(path, (500, 0, 1000, 1000)) \
        == runner._image_data_url(path, [500, 0, 1000, 1000])
    assert len(runner._IMAGES) == 2
    runner._IMAGES.clear()
