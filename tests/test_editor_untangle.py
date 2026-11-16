"""
test_editor_untangle.py: the crossing reduction of `docpipe edit`
(docpipe/editor/ui/src/lib/untangle.ts), used by "Untangle arrows" of the
Graph tab.

The promises, each one sentence with each AND a test of its own: the count
of crossings follows the heights of the ports AND counts an arrow that
skips a column; the result is a new order of the same nodes in each column,
never more crossings than the order given, and the count it reports is the
count of the order it returns; groups stay together AND keep the order they
stood in; the same input gives the same output. Each has a case that breaks
it by construction (a count that ignores the ports or the skipping arrows,
a result that is reversed, one that is not the best found, one that ignores
the groups).

The module is the page's own TypeScript, run by node with its types
stripped; the tests are skipped where node cannot do that.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "editor_untangle_driver.mjs"
NODE = shutil.which("node")


def _strips_types() -> bool:
    if NODE is None:
        return False
    done = subprocess.run([NODE, "-p", "process.features.typescript"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0 and done.stdout.strip() in ("strip",
                                                            "transform")


pytestmark = pytest.mark.skipif(not _strips_types(),
                                reason="no node that strips TypeScript types")


def run_node(jobs):
    done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(jobs),
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def node(i, height=10, group=None):
    out = {"id": i, "height": height}
    if group is not None:
        out["group"] = group
    return out


def edge(a, ay, b, by):
    return {"from": a, "fromY": ay, "to": b, "toY": by}


def count(inp, broken=None) -> int:
    return run_node([{"op": "count", "input": inp, "broken": broken}])[0]["n"]


def untangle(inp, broken=None, options=None) -> dict:
    return run_node([{"op": "untangle", "input": inp, "broken": broken,
                      "options": options}])[0]


def reordered(inp, columns):
    """*inp* with the nodes of each column in the order of *columns*."""
    out = []
    for col, ids in zip(inp["columns"], columns):
        by = {n["id"]: n for n in col}
        out.append([by[i] for i in ids])
    return {"columns": out, "edges": inp["edges"]}


# -- the drawings the tests use ------------------------------------------------

TWO_ARROWS = {"columns": [[node("a1"), node("a2")], [node("b1"), node("b2")]],
              "edges": [edge("a1", 5, "b2", 5), edge("a2", 5, "b1", 5)]}
PARALLEL = {"columns": TWO_ARROWS["columns"],
            "edges": [edge("a1", 5, "b1", 5), edge("a2", 5, "b2", 5)]}
# one tall node whose upper port leads to the lower node and its lower port to
# the upper one: the arrows cross although they leave one node
PORTS = {"columns": [[node("a", 40)], [node("b1"), node("b2")]],
         "edges": [edge("a", 5, "b2", 5), edge("a", 35, "b1", 5)]}
SAME_PORT = {"columns": [[node("a", 40)], [node("b1"), node("b2")]],
             "edges": [edge("a", 5, "b2", 5), edge("a", 5, "b1", 5)]}
# a -> d skips the middle column, b -> m crosses the point it passes there
SKIP = {"columns": [[node("a"), node("b")], [node("m")],
                    [node("c"), node("d")]],
        "edges": [edge("a", 5, "d", 5), edge("b", 5, "m", 5),
                  edge("m", 5, "c", 5)]}
# two kinds on each side, every arrow wanting the kinds swapped on one side
GROUPED = {
    "columns": [[node("a1", 10, "A"), node("a2", 10, "A"),
                 node("b1", 10, "B"), node("b2", 10, "B")],
                [node("t1", 10, "X"), node("t2", 10, "X"),
                 node("t3", 10, "Y"), node("t4", 10, "Y")]],
    "edges": [edge("a1", 5, "t3", 5), edge("a2", 5, "t4", 5),
              edge("b1", 5, "t1", 5), edge("b2", 5, "t2", 5)]}


def random_drawing(seed: int) -> dict:
    rnd = random.Random(seed)
    columns = []
    for c in range(rnd.randint(3, 4)):
        col = [node(f"n{c}_{i}", rnd.randint(10, 60))
               for i in range(rnd.randint(3, 7))]
        if c == 0:
            for i, n in enumerate(col):
                n["group"] = "ABC"[min(2, i * 3 // len(col))]
        columns.append(col)
    edges = []
    for c in range(1, len(columns)):
        for n in columns[c]:
            for _ in range(rnd.randint(1, 2)):
                src = rnd.choice(columns[rnd.randint(0, c - 1)])
                edges.append(edge(src["id"], rnd.uniform(0, src["height"]),
                                  n["id"], rnd.uniform(0, n["height"])))
    return {"columns": columns, "edges": edges}


SEEDS = range(40)


def groups_problems(inp, columns) -> list:
    """Groups of *inp* that are split, or stand in another order in *columns*."""
    out = []
    for col, ids in zip(inp["columns"], columns):
        group = {n["id"]: n.get("group") for n in col}
        runs = []
        for i in ids:
            if not runs or runs[-1] != group[i]:
                runs.append(group[i])
        named = [g for g in runs if g is not None]
        if len(named) != len(set(named)):
            out.append("a group is split")
        first = list(dict.fromkeys(g for g in (n.get("group") for n in col)
                                   if g is not None))
        if list(dict.fromkeys(named)) != first:
            out.append("the groups stand in another order")
    return out


# -- 1. the count follows the ports AND counts the arrows that skip a column ---

def test_the_count_is_right_on_hand_made_drawings():
    assert count(TWO_ARROWS) == 1
    assert count(PARALLEL) == 0
    assert count(PORTS) == 1
    # arrows that leave one port do not cross each other
    assert count(SAME_PORT) == 0


def test_an_arrow_that_skips_a_column_is_counted():
    assert count(SKIP) == 1


@pytest.mark.parametrize("broken, inp", [("ignore_ports", PORTS),
                                         ("drop_skipping", SKIP)])
def test_a_count_that_leaves_something_out_is_found(broken, inp):
    assert count(inp, broken) != count(inp)


# -- 2. a new order of the same nodes, never worse, reported as it is ----------

def test_two_arrows_that_cross_are_untangled_to_none():
    got = untangle(TWO_ARROWS)
    assert (got["before"], got["after"]) == (1, 0)
    assert count(reordered(TWO_ARROWS, got["columns"])) == 0
    got = untangle(PORTS)
    assert (got["before"], got["after"]) == (1, 0)


def test_a_drawing_without_crossings_is_left_as_it_is():
    got = untangle(PARALLEL)
    assert got["columns"] == [["a1", "a2"], ["b1", "b2"]]
    assert (got["before"], got["after"]) == (0, 0)


def test_the_skipping_arrow_is_untangled_too():
    got = untangle(SKIP)
    assert got["after"] == 0
    assert count(reordered(SKIP, got["columns"])) == 0


def test_the_result_is_never_worse_and_is_what_it_says():
    worse = better = 0
    for seed in SEEDS:
        inp = random_drawing(seed)
        got = untangle(inp)
        assert [sorted(c) for c in got["columns"]] == \
            [sorted(n["id"] for n in col) for col in inp["columns"]]
        assert got["after"] <= got["before"] == count(inp)
        assert count(reordered(inp, got["columns"])) == got["after"]
        worse += got["after"] > got["before"]
        better += got["after"] < got["before"]
    assert worse == 0 and better > 10


def test_a_result_that_is_not_the_best_found_is_caught():
    spoiled = 0
    for seed in SEEDS:
        inp = random_drawing(seed)
        got = untangle(inp, "no_best")
        spoiled += got["after"] > got["before"]
    assert spoiled > 0


def test_a_result_that_is_not_the_order_it_reports_is_caught():
    spoiled = 0
    for seed in SEEDS:
        inp = random_drawing(seed)
        got = untangle(inp, "reverse")
        spoiled += count(reordered(inp, got["columns"])) != got["after"]
    assert spoiled > 0


# -- 3. groups stay together and in their order --------------------------------

def test_a_group_stays_together_and_in_order():
    got = untangle(GROUPED)
    assert got["after"] == got["before"] == 4
    assert {tuple(sorted(c[:2])) for c in got["columns"]} ==         {("a1", "a2"), ("t1", "t2")}
    assert groups_problems(GROUPED, got["columns"]) == []
    for seed in SEEDS:
        inp = random_drawing(seed)
        assert groups_problems(inp, untangle(inp)["columns"]) == [], seed


def test_a_result_that_ignores_the_groups_is_caught():
    assert groups_problems(
        GROUPED, untangle(GROUPED, "ignore_groups")["columns"])
    assert any(groups_problems(random_drawing(s),
                               untangle(random_drawing(s),
                                        "ignore_groups")["columns"])
               for s in SEEDS)


# -- 4. the same input gives the same output -------------------------------------

def test_the_same_input_gives_the_same_output():
    for seed in SEEDS:
        inp = random_drawing(seed)
        assert untangle(inp) == untangle(json.loads(json.dumps(inp)))
