---
temperature: 0
max_tokens: 512
---
Give the number of the entry under "list" that the words under "words" mean as the answer to the question under "question".

* Decide by meaning, not by spelling: what an entry means stands after "means".
* Take the most specific entry the words support: where they say offshore wind, that is the offshore wind entry, not merely wind. An entry such as "none of these sectors" is for words that name something of this kind that no other entry matches.
* 0 means that no entry is what the words mean.
* Where the form below shows a list, name every entry the words mean, such as two sectors.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: lines -->
"lines" are the lines of the publication the words stand in.

<!-- with: table -->
"table" is the title of the table they stand in.

<!-- with: settings -->
"settings" are what this publication settles for all its values. They hold here too where they speak about these words.
