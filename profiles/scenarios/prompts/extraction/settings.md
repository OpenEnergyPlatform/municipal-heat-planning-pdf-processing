---
temperature: 0
max_tokens: 4096
---
Find what this publication on climate and energy scenarios settles for all its values, each setting with a place that prints it: for instance the region all its scenarios cover, the model they are run with, or that every emission is given in CO2 equivalents.
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

* Under "settings", each setting has "about", what it holds for, and "value", what it settles, both in the publication's words, and "quote", one contiguous place copied character for character that contains both.
* Only settings of this publication itself that hold for more than one value count: no single value, nothing attributed to other works.
* Name only what you have read. An empty list is an answer.
* "hits" lists each passage of the publication with "id", kind, title and one line, in the order of the publication.
* "more" names what you want to read before you answer. Give your whole answer with everything you already know when you ask for more as well; without a new request in "more" it stands.
  - {"get":"hit","id":"..."}: the passage of a hit;
  - {"get":"next"} or {"get":"previous"}: the section after or before the first passage, next time the one after or before that;
  - {"get":"item","id":"..."}: the table or figure whose placeholder stands in square brackets in a text;
  - {"get":"search","pattern":"..."}: hits for a regular expression, regardless of case;
  - {"get":"similar","text":"..."}: hits for a sentence as the publication would print a setting; it may be made up.

<!-- follow-up: more hits not_found -->
Here is what is new: under "more" the passages you asked for, under "hits" new hit lists, each hit with "id", kind, title and one line, for a "search" the line that matches. Where you asked for nothing, they are the next passages of the publication, until every one was listed. Under "not_found" stands what could not be fetched: "end" (no section in that direction any more), "unknown" (no or more than one placeholder or hit of that name), "invalid_pattern" or "timeout". Give your whole answer again, with everything you already know.

<!-- follow-up: corrections -->
Your last answer has mistakes, per setting under "what". Answer once more in full and fix every point.
