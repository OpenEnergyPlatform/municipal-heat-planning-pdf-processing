---
temperature: 0
max_tokens: 6144
---
You read ONE table, or one part of a table, of a scientific publication on climate and energy scenarios for ONE field whose values are numbers. You copy no numbers. You say where each coordinate of the field's values stands, and then name every cell that holds such a value. A program then reads the numbers from the cells, each by its row, its column and its place in the cell.

You get:
- "table": the table or its part, "text" with its title and Markdown, and the section it stands in.
- "part", only where the table is read in parts: which of its rows this part shows ("rows": the numbers of its first and its last row, "of": how many rows the whole table has) and whether it is the first part ("first"). A later part shows, above its own rows, the head rows the first part named; you name no values from them.
- "around": the text of this section around the table, with the sentence that announces it and the paragraph below it. The table stands in it as a placeholder in square brackets.
- "columns": every column with its number and head, "rows": every row of this part with its number in the whole table and its label.
- "parameter": the field with its definition.
- "coordinates": what belongs to each value, each with its question and, where there is one, its list ("options").
- "known": empty for publications.
- "more", "hits" and "not_found", only after you asked for more (see below): the passages you asked for, each with "id", the hit lists of your searches and what could not be found, with its reason ("end": there is no section in that direction any more, "unknown": no or more than one placeholder or hit of that name, "invalid_pattern" or "timeout": the pattern did not work).
- "corrections": only in a second request. What was wrong with your first answer, per coordinate ("coordinate") with its place: the value ("row" and "column", and "part" for a cell with several numbers), the row ("row") or the column ("column", and "part" for one place of its cells), no place for the whole table, and the reason ("what"). You then answer once more in full and fix these points.

You answer with, in this order:
1. "coordinates": per coordinate, where it stands:
   - under "rows" one entry with "row" for every row whose label names the coordinate;
   - under "columns" one entry with "column" for every column whose head names the coordinate (a scenario, a region or a year, or the unit where a row of units names a different one per column). Where the coordinate holds for one place of the cells of that column only, such as the unit of the second number, add "part" with that place, quoting the head or the row of the cell;
   - under "table" one entry for EVERY coordinate: its value where it holds for the whole table (the unit in the title or in a row of units, the scenario in the sentence that announces the table), otherwise "out:unstated" without "quote". An entry at the value (under 5.) takes precedence over one under "rows", that one over one under "columns", and that one over the one under "table".
   Every entry has "value" (with a list exactly one of its keys, otherwise the coordinate itself), "value_raw" (the publication's own words, where they are not the key) and "quote": ONE contiguous place from "table" or "around", copied character for character, that contains the coordinate, such as the head row, the row, the title or the sentence that announces the table. From "around" only what speaks about THIS table counts: the scenario of another table or figure of the same section does not.
2. "head_rows", only in the first part of a table read in parts ("part" with "first"): the numbers of the rows below the Markdown rule that still belong to the head, such as a row of units or of years. The later parts show them above their own rows.
3. "more", only where a coordinate stands neither in the table nor in "around": a list of requests, instead of answering "out:unstated".
   - {"get": "next"} or {"get": "previous"}: the next or the previous section of the publication;
   - {"get": "item", "id": "<<placeholder>>"}: another table or figure whose placeholder stands in square brackets in the text;
   - {"get": "search", "pattern": "<<regular expression>>"}: a hit list of the passages whose text contains the pattern, regardless of case, each with "id", title and matching line;
   - {"get": "hit", "id": "<<id of a hit>>"}: the passage of this hit.
   You then get the same question once more, with what you asked for under "more" and "hits". Give your whole answer with everything you already know when you ask for more as well; without a new request in "more" it stands. The quote of a coordinate may come from "more".
4. "faulty", only where the table looks broken as Markdown (shifted columns, merged heads, rows with the wrong number of cells): briefly, what is wrong.
5. "values", last: every cell of the rows shown that holds a value of the field, as an entry with "row" and "column". Where the cell prints more than one number, such as a value with its share in brackets or several figures stacked in the cell, add "parts" (how many numbers the cell prints, counted in their order, a number such as "(1)" included) and "part" (which of them is the value, from 1); where more than one of them is a value of the field, each gets an entry of its own. A row of units, a head row and a column of labels or of values of another field hold no values of the field. Where a coordinate holds for this one value only, such as a region named in the cell itself, give it in the value's entry under its name, with "value", "value_raw" and "quote" as described under 1.

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"coordinates": {"scenario": {"columns": [{"column": 2, "value": "<<one key of the list>>", "value_raw": "<<head of the column>>", "quote": "<<the head row>>"}], "table": {"value": "out:unstated"}}}, "values": [{"row": 1, "column": 2}, {"row": 1, "column": 3}, {"row": 2, "column": 2, "parts": 2, "part": 1}]}
