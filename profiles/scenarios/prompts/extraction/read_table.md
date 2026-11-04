---
temperature: 0
max_tokens: 6144
---
You read ONE table, or one part of a table, of a scientific publication on climate and energy scenarios and say, for the values of ONE field, where the coordinates asked about them stand.

You get:
- "table": the table or its part, "text" with its title and Markdown, and the section it stands in; "around": the text of this section around the table, with the sentence that announces it.
- "columns": every column with its number and head, "rows": every row with its number and label, "part", only where the table is read in parts: which rows this part shows.
- "parameter": the field with its definition.
- "values": the cells that hold values of the field, each with "row" and "column" and, where the cell prints several numbers, the place of the value ("part").
- "coordinates": the coordinates asked, each with its question and its list ("options"); "where": where a publication usually prints them.
- "known": empty for publications.
- "more", "hits" and "not_found", only after you asked for more (see below).
- "corrections", only in a second request: what was wrong with your first answer, per coordinate ("coordinate") with its place and the reason ("what"). You then answer once more in full and fix these points.

You answer under "coordinates", for every coordinate asked, where it stands, in this order:
- "rows": one entry with "row" for every row whose label names the coordinate;
- "columns": one entry with "column" for every column whose head names the coordinate; where it holds for one place of the cells of that column only, add "part";
- "cells": for a value the coordinate holds for alone, such as a scenario named in its own cell, one entry with "row", "column" and, where needed, "part";
- "table": one entry for EVERY coordinate: its value where it holds for the whole table (the scenario in the title or in the sentence that announces the table), otherwise "out:unstated" without "quote".
An entry at a cell takes precedence over one at the row, that one over one at the column, and that one over the one at the table.

Every entry has "value" (exactly one key of its list), "value_raw" (the publication's own words, where they are not the key) and "quote": ONE contiguous place from "table" or "around", copied character for character, that contains the coordinate, such as the head row, the row, the title or the sentence that announces the table. From "around" only what speaks about THIS table counts: the scenario of another table or figure of the same section does not.

The scenarios of the list are run identifiers of the AR6 database, such as "EN_INDCi2030_300f". They almost never stand in the text; there the same scenario is called "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Matching the text's name with the identifier is your task: clues are the level of ambition, the target year, the climate target, the budget and the order in which the publication introduces its scenarios. Identifiers that differ in one part only, such as EN_NPi2020_400 and EN_NPi2020_1000, are different runs. Pick an identifier only where the text's name, with what the table says about it, fits exactly one run of the list. A name that fits several runs and none of them exactly names a family, and the answer is "scenario family", whatever the runs share: their beginning ("NPi", "the NDC scenarios"), their climate target ("the 1.5 °C scenarios", where several runs carry that target) or their variant alone ("the reference case", where the list holds it with several targets). A scenario the list does not hold at all is "not in AR6".

If a coordinate stands neither in the table nor in "around", you may ask for more under "more" instead of answering "out:unstated": {"get": "next"} or {"get": "previous"} (the next or the previous section), {"get": "item", "id": "<<placeholder>>"} (another table or figure whose placeholder stands in square brackets in the text), {"get": "search", "pattern": "<<regular expression>>"} (a hit list of the passages whose text contains the pattern, regardless of case, each with "id", title and matching line) or {"get": "hit", "id": "<<id of a hit>>"} (the passage of this hit). You then get the same question once more, with what you asked for under "more" and "hits" and under "not_found" what could not be found, with its reason. Give your whole answer when you ask for more as well; without a new request in "more" it stands. The quote of a coordinate may come from "more".

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"coordinates": {"scenario": {"columns": [{"column": 2, "value": "<<one key of the list>>", "value_raw": "<<head of the column>>", "quote": "<<the head row>>"}], "table": {"value": "out:unstated"}}}}
