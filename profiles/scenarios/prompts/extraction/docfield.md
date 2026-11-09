---
temperature: 0
max_tokens: 2048
---
Name every shown line that prints a value of the field under "field" for this publication, with its address and the words of the value.

* A value is what the field means ("means"), of this publication itself, not of a work it cites, presents or compares.
* Each line starts with its address and the letter of its block. In a table row "|" separates the cells, counted from 1: A19.2 is the second cell of line A19.
* "words" are the value as the line prints it, character for character. Where a value runs over several lines, such as an abstract, "at" spans them from the first to the last, such as A3-A5.
* Several values, such as two authors, are several entries. Where no line prints a value, "found" is empty.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: title_page -->
"title_page" are the first lines of the publication's first page, under the letter T.

<!-- with: passages -->
"passages" are pieces of the publication a search for this field found best, each under its letter, with its kind, page and title.
