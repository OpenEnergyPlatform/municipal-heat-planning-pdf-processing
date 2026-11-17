<!-- way: answer_with=address -->
Answer the question under "question" for the value under "value" with the address of a line under "passages" that says the answer for this value and its words; where none says it, "at" is 0.
<!-- way: answer_with=quote -->
Answer the question under "question" for the value under "value" with a line under "passages" that says the answer for this value, under "quote" character for character, and its words; where none says it, "quote" is 0.
<!-- /way -->

* "value" gives the value's words and its address under "passage", its own place, which does not say the answer. "passages" are further pieces of the document, each under its letter, with its kind, page and title.
* Each line starts with its address and the letter of its block. A line that "|" divides has cells, counted from 1, wherever it stands: A19.2 is the second cell of line A19.
* A line counts only where it speaks about THIS value: about the same statement, about the table or figure the value stands in, or about the section its place speaks about. A line about another table, another year or the document in general does not count, even where it names what is asked.
* "words" are the words of that line that say the answer, character for character. Where the form below shows a list "found", name each answer in it on its own.

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
"more" fetches pieces you still need: {"get":"next"} the piece after the last one shown, {"get":"previous"} the one before, {"get":"item","id":"p17_img1"} the table or figure a line names as "[p17_img1 ...]", {"get":"search","pattern":"total"} the pieces a pattern stands in, {"get":"similar","text":"..."} the pieces closest to a sentence, written as the document would print it, never as a question.

<!-- with: outline -->
"outline" lists, for each section the hits stand in, its heading and the tables and figures of it that are not shown, each as its id and title: {"get":"item","id":"..."} under "more" fetches one. The outline says nothing about this value; the answer is still a shown line.

<!-- with: get_image -->
{"get":"image"} under "more" asks for the picture of the figure the value stands in, {"get":"image","id":"B"} for the picture of the figure under letter B, where the figure's lines do not say the answer and its picture shows it. The question is then asked again with the picture; the answer is still a shown line.

<!-- with: get_region -->
With "region":[left,top,right,bottom], each from 0 to 1000 of the picture's width and height, only that part comes, enlarged and sharper, such as {"get":"image","region":[0,700,1000,1000]} for a legend in its lower third.

<!-- with: get_section -->
{"get":"section"} under "more" fetches the section the value stands in, from its start, {"get":"section","id":"B"} the section of the piece under letter B, {"get":"section","id":"p17_img1"} the section that table or figure stands in: where a setting such as the unit or the scenario of all its numbers may stand at the start of the section.

<!-- with: image -->
The picture of the figure under "image" ("passage": the figure the value stands in) is attached. Read in it what its lines do not say, and answer with the shown line that names it, such as the legend line of the colour.

<!-- with: image_region -->
The picture shows only the part under "image_region" (left, top, right, bottom, from 0 to 1000 of the figure's width and height), enlarged.

