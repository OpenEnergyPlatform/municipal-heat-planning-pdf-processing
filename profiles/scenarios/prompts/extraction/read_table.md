---
temperature: 0
max_tokens: 6144
---
You read ONE table of a scientific publication on climate and energy scenarios as a whole for ONE field whose values are numbers. You copy no numbers. You say which columns and rows hold values of the field and where each coordinate of these values stands. A program then reads the numbers from the cells, each by its row and its column.

You get:
- "table": the table, "text" with its title and Markdown, and the section it stands in.
- "around": the text of this section around the table, with the sentence that announces it and the paragraph below it. The table stands in it as a placeholder in square brackets.
- "columns": every column with its number and head, "rows": every row below the head with its number and label.
- "parameter": the field with its definition.
- "coordinates": what belongs to each value, each with its question and, where there is one, its list ("options").
- "known": empty for publications.
- "more", "hits" and "not_found", only after you asked for more (see below): the passages you asked for, each with "id", the hit lists of your searches and what could not be found, with its reason ("end": there is no section in that direction any more, "unknown": no or more than one placeholder or hit of that name, "invalid_pattern" or "timeout": the pattern did not work).
- "corrections": only in a second request. What was wrong with your first answer, per coordinate ("coordinate") with its row ("row") or column ("column"), neither for the whole table, and the reason ("what"). You then answer once more in full and fix these points.

You answer with:
1. "value_columns" and "value_rows": the numbers of the columns and rows whose cells are values of the field. A row of units, a head row and a column of labels or of values of another field do not belong to them.
2. "coordinates": per coordinate, where it stands:
   - under "rows" one entry with "row" for every row whose label names the coordinate;
   - under "columns" one entry with "column" for every column whose head names the coordinate (a scenario, a region or a year, or the unit where a row of units names a different one per column);
   - under "table" one entry for EVERY coordinate: its value where it holds for the whole table (the unit in the title or in a row of units, the scenario in the sentence that announces the table), otherwise "out:unstated" without "quote". An entry under "rows" or "columns" goes before the one under "table".
   Every entry has "value" (with a list exactly one of its keys, otherwise the coordinate itself), "value_raw" (the publication's own words, where they are not the key) and "quote": ONE contiguous place from "table" or "around", copied character for character, that contains the coordinate, such as the head row, the row, the title or the sentence that announces the table. From "around" only what speaks about THIS table counts: the scenario of another table or figure of the same section does not.
3. "more", only where a coordinate stands neither in the table nor in "around": a list of requests, instead of answering "out:unstated".
   - {"get": "next"} or {"get": "previous"}: the next or the previous section of the publication;
   - {"get": "item", "id": "<<placeholder>>"}: another table or figure whose placeholder stands in square brackets in the text;
   - {"get": "search", "pattern": "<<regular expression>>"}: a hit list of the passages whose text contains the pattern, regardless of case, each with "id", title and matching line;
   - {"get": "hit", "id": "<<id of a hit>>"}: the passage of this hit.
   You then get the same question once more, with what you asked for under "more" and "hits". Give your whole answer with everything you already know when you ask for more as well; without a new request in "more" it stands. The quote of a coordinate may come from "more".
4. "faulty", only where the table looks broken as Markdown (shifted columns, merged heads, rows with the wrong number of cells): briefly, what is wrong.

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"value_columns": [2, 3], "value_rows": [1, 2], "coordinates": {"scenario": {"columns": [{"column": 2, "value": "<<one key of the list>>", "value_raw": "<<head of the column>>", "quote": "<<the head row>>"}], "table": {"value": "out:unstated"}}}}
