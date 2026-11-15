Say which entry of "list" the words under "name" are: the entry's number, "new" where they name a thing of the list's kind that it does not hold yet, or 0 where they name no such thing.

* "list" is this publication's list so far, each entry under its number; the scenarios of a work stand under that work ("work: name"). An entry with "means" stands for what it says, such as words that a value is measured for a past year, or words for several scenarios the list does not hold one by one: take it where the words mean that.
* Words are an entry where both name the same thing, such as a short and a long form of one scenario's name or the same work cited twice. Decide by what the lines say, not by the spelling. The same name in another work is another entry.
* Words such as "this report", "this study", "we" or "our" name this publication.
* 0 is for words that name nothing of the list's kind: words that only give a region ("Asia"), a year, a number or a unit, a source note ("Source: JRC.") or a whole sentence.
* Where the form below shows a list, the words may stand for several entries, such as "all scenarios" or "the 2 °C scenarios": give the number of each of them.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: holds -->
"holds" is what the list holds, by its name and what it means ("means"). Words name a thing of the list's kind only where they fit this meaning.

<!-- with: lines -->
"lines" are the lines the words stand in.

<!-- with: work -->
"work" is the work the value with these words belongs to.

<!-- with: more -->
"more" fetches pieces a shown line points to or that you still need, such as "see figure 12" or the list of references: {"get":"next"} the piece after the one shown, {"get":"previous"} the one before, {"get":"item","id":"p17_img1"} the table or figure a line names as "[p17_img1 ...]", {"get":"search","pattern":"baseline"} the pieces a pattern stands in, {"get":"similar","text":"..."} the pieces closest to a sentence, written as the publication would print it, never as a question. What you fetch is shown to you in the next request.

<!-- with: passages -->
"passages" are further pieces of the publication you asked to see, each under its letter, with its kind, page and title.
