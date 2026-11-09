---
temperature: 0
max_tokens: 512
---
Say which entry of "list" the name under "name" is: its number, "new" where the list holds no entry for it yet, or 0 where the words name no such thing at all.

* "list" is this publication's list so far, each entry under its number; the scenarios of a work stand under that work ("work: name"). An entry with "means" says what it stands for: take it where the name means that, such as words that a value is measured for a past year, or words for several scenarios the list does not hold one by one.
* A name is an entry where both name the same thing: a short and a long form of one scenario's name, the same work cited twice. The same name in another work is another entry. Decide by what the lines say, not by the spelling.
* Words such as "this report", "this study", "we" or "our" name this publication.
* 0 is for words that name nothing of the list's kind, such as a source note ("Source: JRC."), a year, a number, a unit or a whole sentence.
* Where the form below shows a list, the name may stand for several entries, such as "all scenarios" or "the 2 °C scenarios": give the number of each of them.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: lines -->
"lines" are the lines the name stands in.

<!-- with: work -->
"work" is the work the value with this name belongs to.
