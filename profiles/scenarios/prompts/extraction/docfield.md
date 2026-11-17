<!-- way: answer_with=address -->
Name every shown line that prints a value of the field under "field" for this publication, with its address and the words of the value.
<!-- way: answer_with=quote -->
Name every shown line that prints a value of the field under "field" for this publication, under "quote" character for character, with the words of the value.
<!-- /way -->

* A value is what the field means ("means"), of this publication itself, not of a work it cites, presents or compares.
* Each line starts with its address and the letter of its block. A line that "|" divides has cells, counted from 1, wherever it stands: A19.2 is the second cell of line A19.
* Words that only name what the field is about, such as a title or a heading that names the topic of the lines below it, are no value of it.
<!-- way: answer_with=address -->
* "words" are the value as the line prints it, character for character. Where a value runs over several lines, such as an abstract, "at" spans them from the first to the last, such as A3-A5.
<!-- way: answer_with=quote -->
* "words" are the value as the line prints it, character for character. Where a value runs over several lines, such as an abstract, "quote" is the text of all of them, without their addresses.
<!-- /way -->
* Several values, such as two authors, are several entries.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! Where lines print values, in this form:
{{example}}
Where no line prints one, in this form:
{{nothing}}

<!-- with: list -->
"list" holds the entries a value of this field can be, each under its number, with what it means ("means") where the list says so. "entry" is the number of the entry whose meaning the value's words fit, also where they use other words than the entry's name: the most specific such entry, 0 where none fits. Where "list" names groups of entries, "entry" is the number of the group.

<!-- with: title_page -->
"title_page" are the first lines of the publication's first page, under the letter T.

<!-- with: passages -->
"passages" are pieces of the publication a search for this field found best, each under its letter, with its kind, page and title.

<!-- with: more -->
"more" fetches pieces a shown line points to or that you still need, such as "see figure 12" or the list of references: {"get":"next"} the piece after the one shown, {"get":"previous"} the one before, {"get":"item","id":"p17_img1"} the table or figure a line names as "[p17_img1 ...]", {"get":"search","pattern":"baseline"} the pieces a pattern stands in, {"get":"similar","text":"..."} the pieces closest to a sentence, written as the publication would print it, never as a question. What you fetch is shown to you in the next request.

<!-- with: get_section -->
{"get":"section"} under "more" fetches the section of the first piece shown, from its start, {"get":"section","id":"B"} the section of the piece under letter B, {"get":"section","id":"p17_img1"} the section that table or figure stands in: where a setting such as the unit of all its numbers may stand at the start of the section.

