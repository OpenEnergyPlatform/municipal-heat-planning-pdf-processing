---
temperature: 0
max_tokens: 4096
---
Find the passages of this publication on climate and energy scenarios that state a value of the field under "parameter", and name each by its "id".
Before you answer, check what the definition excludes.
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

* "walked" are passages the field was looked for in already, where no value came: search elsewhere, for instance with the words a publication names it with ("prepared by", "on behalf of" for its authors).
* "places" names each passage that states a value of the field, by the "id" it was shown under: a hit ("H…") or a passage you fetched. An empty list is an answer.
* "more" names what you want to read before you answer. Give your whole answer with everything you already know when you ask for more as well; without a new request in "more" it stands.
  - {"get":"hit","id":"..."}: the passage of a hit;
  - {"get":"item","id":"..."}: the table or figure whose placeholder stands in square brackets in a text;
  - {"get":"search","pattern":"..."}: hits for a regular expression, regardless of case;
  - {"get":"similar","text":"..."}: hits for a sentence as the publication would print a value of the field; it may be made up.

<!-- follow-up: more hits not_found -->
Here is what is new: under "more" the passages you asked for, each with "id"; under "hits" new hit lists, each hit with "id", kind, title and one line, for a "search" the line that matches. Under "not_found" stands what could not be fetched: "end", "unknown" (no or more than one placeholder or hit of that name), "invalid_pattern" or "timeout". Give your whole answer again, with everything you already know.

<!-- follow-up: corrections -->
Your last answer has mistakes, per passage under "what". Answer once more in full and fix every point.
