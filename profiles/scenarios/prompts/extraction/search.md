<!-- way: answer_with=address -->
Answer the question under "question" for the value under "value" with the address of a line under "passages" that says the answer for this value and its words; where none says it, "at" is 0.
<!-- way: answer_with=quote -->
Answer the question under "question" for the value under "value" with a line under "passages" that says the answer for this value, under "quote" character for character, and its words; where none says it, "quote" is 0.
<!-- /way -->

* "value" gives the value's words and its address under "passage", its own place, which does not say the answer. "passages" are further pieces of the publication, each under its letter, with its kind, page and title.
* Each line starts with its address and the letter of its block. A line that "|" divides has cells, counted from 1, wherever it stands: A19.2 is the second cell of line A19.
* A line counts only where it speaks about THIS value: about the same statement, about the table or figure the value stands in, or about the section or scenario its place speaks about. A line about another table, another year, another statement or the publication in general does not count, even where it names what is asked.
* "words" are the words of that line that say the answer, character for character. Where the form below shows a list "found", name each answer in it on its own.
* "more" fetches pieces you still need: {"get":"next"} the piece after the last one shown, {"get":"previous"} the one before, {"get":"item","id":"p17_img1"} the table or figure a line names as "[p17_img1 ...]", {"get":"search","pattern":"baseline"} the pieces a pattern stands in, {"get":"similar","text":"..."} the pieces closest to a sentence, written as the publication would print it, never as a question.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

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
