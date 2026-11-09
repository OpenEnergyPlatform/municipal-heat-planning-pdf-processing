---
temperature: 0
max_tokens: 2048
---
Name every value of the field under "field" that the lines under "passage" print, each with the address of its line or cell and its words.

* Each line starts with its address. In a table row "|" separates the cells, counted from 1: in "12 | IRENA | Reference | 2050 |" the cell 12.2 is "Reference". A table's title and head stand in every piece of it under the same addresses.
* A value is what the field means ("means"). Take what this publication states for itself, its study and its scenarios; skip what it attributes to other works, unless the field itself asks for other works.
* "at" is the value's cell where it stands in a table row, else its line; where a value runs over several lines, from the first to the last, such as 4-6. "words" are the value as the line prints it, character for character.
* Name each value once, several of one line each on its own. Where the lines print none, "found" is empty.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: headings -->
"headings" are the publication's headings up to this piece, its own last. They say what the piece is about.
