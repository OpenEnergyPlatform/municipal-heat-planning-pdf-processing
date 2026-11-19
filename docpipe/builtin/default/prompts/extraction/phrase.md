Write one short sentence as it might stand in exactly this form in this document, naming the parameter "label" names and "description" describes; where it fits, make up a value with its unit, such as "The annual operating budget reached 12.4 million EUR in 2023." The sentence is used to search the document.
If "document" is given, take the document's words from "name" (its title) and "caption" (the heading of a first find); if "frame" is given, name its scenario and year; if "names" is given, name one or two of these entries.
Answer with exactly one JSON object on one line, with no text before or after it.
{"phrase":"..."}

<!-- with: question -->
"question" asks a detail of the value under "value" that its own lines ("lines") do not say. Write the sentence as this document would print the answer for THIS value: the value in the words of its lines, together with an answer to the question, such as the year, the region or the scenario it stands for. The answer may be made up: the sentence is only used to search the rest of the document.

<!-- with: headings -->
"headings" are the document's headings up to the value's place, its own last. Take the document's words from them too.

<!-- with: before -->
"before" are the sentences this value was already searched with, without the answer being found. Write a different sentence: with other words of the document, and as the answer could stand at another place of it, such as in a table instead of the text.
