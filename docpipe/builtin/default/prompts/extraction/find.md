<!-- way: answer_with=address -->
Name every value of the field under "field" that the lines under "passage" print, each with the address of its line or cell and its words.
<!-- way: answer_with=quote -->
Name every value of the field under "field" that the lines under "passage" print, each with its line, character for character, and its words.
<!-- /way -->

* Each line starts with its address. A line that "|" divides has cells, counted from 1, wherever it stands: in "12 | Oslo | 2030 | 4.2 |" the cell 12.4 is "4.2". A table's title and head stand in every piece of it under the same addresses, and so does a figure's caption.
* A value is what the field means ("means"), as this document states it for itself.
* Words that only name what the field is about, such as a heading that names the topic of the lines below it, are no value of it.
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
"headings" are the document's headings up to this piece, its own last. They say what the piece is about.

<!-- with: title_page -->
"title_page" are the first lines of the document's first page, under the letter T.

<!-- with: passages -->
"passages" stands instead of "passage" where the request shows several pieces: each under its letter, with its kind, page and title. The address of a line carries the letter of its piece, such as A3 or B12.2.

<!-- with: more -->
"more" fetches pieces a shown line points to or that you still need, such as "see figure 12": {"get":"next"} the piece after the one shown, {"get":"previous"} the one before, {"get":"item","id":"p17_img1"} the table or figure a line names as "[p17_img1 ...]", {"get":"search","pattern":"total"} the pieces a pattern stands in, {"get":"similar","text":"..."} the pieces closest to a sentence, written as the document would print it, never as a question. What you fetch is shown to you in the next request.

<!-- with: get_image -->
{"get":"image"} under "more" asks for the picture of the figure shown, {"get":"image","id":"B"} for the picture of the figure under letter B, where its lines do not say what you need and its picture shows it. The request is then asked again with the picture; the answer is still a shown line.

<!-- with: image -->
The picture of the figure under "image" is attached. Read in it what its lines do not say, and answer with the shown line that names it, such as the legend line of a colour.
