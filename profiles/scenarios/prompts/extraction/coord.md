---
temperature: 0
max_tokens: 1024
---
Answer the question under "question" with the address of the shown line that says the answer and its words; where no shown line says it, with 0 and a search sentence.

* Each line starts with its address, a line of another block with the block's letter before it. In a table row "|" separates the cells, counted from 1: 19.2 is the second cell of line 19.
* "words" are the words of that line that say the answer, character for character.
* Where no shown line says it, "at" is 0 and "hyde" is one sentence as this publication would print the answer, with its own names, such as "The scenarios of this study cover the 27 member states of the EU." It may be made up: it is only used to search the rest of the publication.
* Where the form below shows a list "found", name each answer in it on its own, such as two scenarios; where no line says one, it stays empty and "hyde" is the search sentence.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: value -->
The question is about the value under "value": its words and its address under "passage", which shows its line, in a table with the table's title and head, else with the sentences before and after it. The line of the answer has to speak about THIS value: its own line, the head of its column, the title of its table, its sentence and those beside it, the heading of its section.

<!-- with: work -->
The question asks one detail of the work under "work", a work this publication presents, compares, reviews or cites, at the line under "passage" that names it.

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
