---
temperature: 0
max_tokens: 6144
---
You look in a scientific publication on climate and energy scenarios for what belongs to ONE value of ONE field but does not stand in the value's own passage: the scenario the value refers to.

You get:
- "passage": where the value comes from, with kind, title and section.
- "parameter": the field with its definition.
- "row": the value with its quote, what is already read about it ("known", in the publication's words) and what is still open ("open").
- "coordinates": the open coordinates, each with its question; "where": where a publication usually prints them.

You answer with:
1. Each coordinate from "coordinates" you found, with "value", the scenario's name as the publication prints it, copied character for character, and "quote": ONE contiguous place from what you were shown, copied character for character, that contains the name and speaks about THIS value. Where the question says so, "value" is an entry of the coordinate's "options" instead of a name, such as "status quo"; "value_raw" then holds the words of the quote that show it, and the quote is the value's own. Beside a name, "value_raw" repeats the name. If the publication states the value for several scenarios, give each of them as its own entry of a list, each with its own quote. A coordinate you have not found, leave out.
2. "more": what you want to read before you answer. A list of requests:
   - {"get": "hit", "id": "<<id of a hit>>"}: the passage of this hit;
   - {"get": "next"} or {"get": "previous"}: the section after or before the passage of the value, next time the one after or before that;
   - {"get": "item", "id": "<<placeholder>>"}: the table or figure whose placeholder stands in square brackets in the text;
   - {"get": "search", "pattern": "<<regular expression>>"}: a hit list of the passages whose text contains the pattern, regardless of case;
   - {"get": "similar", "text": "<<a sentence as the publication would print the coordinate for this value>>"}: a hit list of the passages nearest to that sentence; what it says may be made up.
   Give your whole answer with everything you already know when you ask for more as well; without a new request in "more" it stands. Where you are shown no hit list, search yourself with "similar". Do not guess: name only what you have read.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}
Where the publication states the value for several scenarios (the quotes below are descriptions in << >> and stand in no publication):
{"scenario": [{"value": "<<the first scenario's name>>", "quote": "<<a sentence that names it>>"}, {"value": "<<the second scenario's name>>", "quote": "<<a sentence that names it>>"}]}

<!-- with: hits -->
"hits" holds a hit list, each hit with "id", kind, title and its first line: the passages of the publication that come nearest to how it would print the open coordinates of this value.

<!-- follow-up: more hits not_found -->
Here is what is new: under "more" the passages you asked for, each with "id"; under "hits" new hit lists, each hit with "id", kind, title and one line, for a "search" the line that matches. Where you asked for nothing new while a coordinate is still missing, they are the next passages of the ranking or, where there was none, the next passages in the order of the publication. Under "not_found" stands what could not be found, with its reason ("end": there is no section in that direction any more, "unknown": no or more than one placeholder or hit of that name, "invalid_pattern" or "timeout": the pattern did not work). Give your whole answer again, with everything you already know.

<!-- follow-up: corrections -->
Your last answer has mistakes, per coordinate under "what". Answer once more in full and fix their points. A correction that names a "value" asks for that scenario alone.
