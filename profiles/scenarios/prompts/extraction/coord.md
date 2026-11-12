<!-- way: answer_with=address -->
Answer the question under "question" with the address of the shown line that says the answer and its words; where no shown line says it, "at" is 0.
<!-- way: answer_with=quote -->
Answer the question under "question" with the shown line that says the answer, under "quote" character for character, and its words; where no shown line says it, "quote" is 0.
<!-- /way -->

* Each line starts with its address, a line of another block with the block's letter before it. A line that "|" divides has cells, counted from 1, wherever it stands: 19.2 is the second cell of line 19.
* "words" are the words of that line that say the answer, character for character.
* Where the form below shows a list "found", name each answer in it on its own, such as two scenarios; where no line says one, it stays empty.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: value -->
The question is about the value under "value": its words and its address under "passage", which shows its line, in a table with the table's title and head, else with the sentences before and after it. The line of the answer has to speak about THIS value: its own line, the head of its column, the title of its table, its sentence and those beside it, the heading of its section.

<!-- with: list -->
<!-- way: answer_with=address -->
"list" holds the works this publication names, each under its number, 1 this publication itself. "entry" is the number of the work whose result the value is, and "at" the address of the shown line that shows it: a line or heading naming that work's study, model or authors, or for this publication words such as "this study", "we" or "our scenarios". Where no shown line shows whose result the value is, "entry" is 0.
<!-- way: answer_with=quote -->
"list" holds the works this publication names, each under its number, 1 this publication itself. "entry" is the number of the work whose result the value is, and "quote" the shown line that shows it, character for character: a line or heading naming that work's study, model or authors, or for this publication words such as "this study", "we" or "our scenarios". Where no shown line shows whose result the value is, "entry" is 0.
<!-- /way -->

<!-- with: work -->
The question asks one detail of the work under "work", a work this publication presents, compares, reviews or cites, which the shown lines name.

<!-- with: field -->
"field" is the value's field with what it means ("means").

<!-- with: known -->
"known" says what is read about this value already, in the publication's words.

<!-- with: headings -->
"headings" are the publication's headings up to the value's place, its own last, under the letter H.

<!-- with: title_page -->
"title_page" are the first lines of the publication's first page, under the letter T.

<!-- with: settings -->
"settings" are what this publication settles for all its values, under the letter F. They hold for this value too where they speak about it.

<!-- with: more -->
"more" fetches pieces a shown line points to or that you still need, such as "see figure 12" or the list of references: {"get":"next"} the piece after the one shown, {"get":"previous"} the one before, {"get":"item","id":"p17_img1"} the table or figure a line names as "[p17_img1 ...]", {"get":"search","pattern":"baseline"} the pieces a pattern stands in, {"get":"similar","text":"..."} the pieces closest to a sentence, written as the publication would print it, never as a question. What you fetch is shown to you in the next request.

<!-- with: get_image -->
{"get":"image"} under "more" asks for the picture of the figure the value stands in, {"get":"image","id":"B"} for the picture of the figure under letter B: where the figure's lines do not say the answer but its picture shows it, such as the colour of a legend entry or the part of a bar. The question is then asked again with the picture; the answer is still a shown line, such as the legend line of that colour.

<!-- with: image -->
The picture of the figure under "image" ("passage": the figure the value stands in) is attached. Read in it what its lines do not say, and answer with the shown line that names it, such as the legend line of the colour.

<!-- with: passages -->
"passages" are further pieces of the publication you asked to see, each under its letter, with its kind, page and title.
