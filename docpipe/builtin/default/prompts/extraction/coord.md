<!-- way: answer_with=address -->
Answer the question under "question" for the value under "value" with the address of the shown line that says the answer for this value and its words; where no shown line says it, "at" is 0.
<!-- way: answer_with=quote -->
Answer the question under "question" for the value under "value" with the shown line that says the answer for this value, under "quote" character for character, and its words; where no shown line says it, "quote" is 0.
<!-- /way -->

* "value" gives the value's words and its address under "passage". "passage" shows its line, in a table with the table's title and head, else with the sentences before and after it.
* Each line starts with its address, a line of another block with the block's letter before it. A line that "|" divides has cells, counted from 1, wherever it stands: 19.2 is the second cell of line 19.
* The line has to speak about THIS value: its own line, the head of its column, the title of its table, its sentence and those beside it, the heading of its section.
* "words" are the words of that line that say the answer, character for character.
* Where the form below shows a list "found", name each answer in it on its own; where no line says one, it stays empty.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: field -->
"field" is the value's field with what it means ("means").

<!-- with: known -->
"known" says what is read about this value already, in the document's words.

<!-- with: headings -->
"headings" are the document's headings up to the value's place, its own last, under the letter H.

<!-- with: title_page -->
"title_page" are the first lines of the document's first page, under the letter T.

<!-- with: settings -->
"settings" are what this document settles for all its values, under the letter F. They hold for this value too where they speak about it.

<!-- with: more -->
"more" fetches pieces a shown line points to or that you still need, such as "see figure 12": {"get":"next"} the piece after the one shown, {"get":"previous"} the one before, {"get":"item","id":"p17_img1"} the table or figure a line names as "[p17_img1 ...]", {"get":"search","pattern":"total"} the pieces a pattern stands in, {"get":"similar","text":"..."} the pieces closest to a sentence, written as the document would print it, never as a question. What you fetch is shown to you in the next request.

<!-- with: get_image -->
{"get":"image"} under "more" asks for the picture of the figure the value stands in, {"get":"image","id":"B"} for the picture of the figure under letter B, where the figure's lines do not say the answer and its picture shows it, such as the colour of a legend entry. The question is then asked again with the picture; the answer is still a shown line.

<!-- with: image -->
The picture of the figure under "image" ("passage": the figure the value stands in) is attached. Read in it what its lines do not say, and answer with the shown line that names it, such as the legend line of the colour.

<!-- with: passages -->
"passages" are further pieces of the document you asked to see, each under its letter, with its kind, page and title.
