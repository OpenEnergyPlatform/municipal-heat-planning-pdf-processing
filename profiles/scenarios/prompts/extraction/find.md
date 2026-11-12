<!-- way: answer_with=address -->
Name every value of the field under "field" that the lines under "passage" print, each with the address of its line or cell and its words.
<!-- way: answer_with=quote -->
Name every value of the field under "field" that the lines under "passage" print, each with its line, character for character, and its words.
<!-- /way -->

* Each line starts with its address. A line that "|" divides has cells, counted from 1, wherever it stands: in "12 | IRENA | Reference | 2050 |" the cell 12.2 is "Reference". A table's title and head stand in every piece of it under the same addresses, and so does a figure's caption.
* A value is what the field means ("means"). Take what this publication states for itself, its study and its scenarios; skip what it attributes to other works, unless the field itself asks for other works.
* Words that only name what the field is about, such as a title or a heading that names the topic of the lines below it, are no value of it.
<!-- way: answer_with=address -->
* "at" is the value's cell where it stands in a line with cells, else its line; where a value runs over several lines, from the first to the last, such as 4-6. "words" are the value as the line prints it, character for character.
<!-- way: answer_with=quote -->
* "quote" is the value's line, character for character, without the address before it; where a value runs over several lines, the text of all of them. "words" are the value as the line prints it, character for character.
<!-- /way -->
* Name each value once, several of one line each on its own.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! Where lines print values, in this form:
{{example}}
Where no line prints one, in this form:
{{nothing}}

<!-- with: list -->
"list" holds the entries a value of this field can be, each under its number. "entry" is the number of the entry a value's words mean, decided by meaning, not by spelling: the most specific entry the words support, 0 where none fits. Where "list" names groups of entries, "entry" is the number of the group.

<!-- with: headings -->
"headings" are the publication's headings up to this piece, its own last. They say what the piece is about.

<!-- with: passages -->
"passages" stands instead of "passage" where a piece holds lines of several passages: each passage under its letter, with its kind, page and title. The address of a line carries the letter of its passage, such as A3 or B12.2.
