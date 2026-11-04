---
temperature: 0
max_tokens: 6144
---
You read ONE table, or one part of a table, of a scientific publication on climate and energy scenarios and name every cell that holds a value of ONE field whose values are numbers. You copy no numbers: a program reads them from the cells you name.

You get:
- "table": the table or its part, "text" with its title and Markdown, and the section it stands in.
- "around": the text of this section around the table. The table stands in it as a placeholder in square brackets.
- "columns": every column with its number and head, "rows": every row of this part with its number in the whole table and its label.
- "part", only where the table is read in parts: which of its rows this part shows ("rows": the numbers of its first and its last row, "of": how many rows the whole table has) and whether it is the first part ("first"). A later part shows, above its own rows, the head rows the first part named; you name no values from them.
- "parameter": the field with its definition.

You answer with, in this order:
1. "head_rows", only in the first part of a table read in parts: the numbers of the rows below the Markdown rule that still belong to the head, such as a row of units or of years.
2. "faulty", only where the table looks broken as Markdown (shifted columns, merged heads, rows with the wrong number of cells): briefly, what is wrong.
3. "values": every cell of the rows shown that holds a value of the field, with "row" and "column". Where the cell prints more than one number, such as a value with its share in brackets or several figures stacked in the cell, add "parts" (how many numbers the cell prints, counted in their order, a number such as "(1)" included) and "part" (which of them is the value, from 1). Where more than one of them is a value of the field, each gets an entry of its own. A row of units, a head row and a column of labels or of values of another field hold no values of the field.

Answer with exactly one JSON object, on one line, with no text before or after it:
{"values": [{"row": 1, "column": 2}, {"row": 1, "column": 3}, {"row": 2, "column": 2, "parts": 2, "part": 1}]}
