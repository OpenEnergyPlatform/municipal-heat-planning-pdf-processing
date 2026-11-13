Write ONE short sentence as it might stand in exactly this form in this publication, naming the described parameter with a plausible value and unit. It is embedded and held as a search anchor against the publication's sections, tables and figures, so it must sound like the publication, not like the ontology.
* Write as if the information already stood there: no question, no meta sentence ("The scenario names are listed in Section 2."), no form of address, no negation ("not reported", "not available").
* Write in English with the words these publications use: scenario, pathway, mitigation, carbon budget, Integrated Assessment Model, funded by, corresponding author. For example: "Global CO2 emissions fall to 12.4 GtCO2/yr by 2050 in the NDC pathway."
* If "document" is given, take this publication's words and structural terms from "name" (its title) and "caption" (the heading of what a first search in it returned), but invent nothing from them that is not in the parameter. If "names" is given (the entries of the parameter's list), name one or two of them as a publication would, without listing them.
* If the information sought is a proper name (institution, person, grant number), invent none: write in the terse style of a block of role labels and contact fields, with the role words instead of names.
* 12 to 35 words, one sentence, two at most.
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{"phrase":"..."}

<!-- with: question -->
"question" asks a detail of the value under "value" that its own lines ("lines") do not say. Write the sentence as this publication would print the answer for THIS value: the value in the words of its lines, together with an answer to the question, such as the region, the year or the scenario it stands for. The answer may be made up: the sentence is only used to search the rest of the publication.

<!-- with: headings -->
"headings" are the publication's headings up to the value's place, its own last. Take the publication's words from them too.

<!-- with: before -->
"before" are the sentences this value was already searched with, without the answer being found. Write a different sentence: with other words of the publication, and as the answer could stand at another place of it, such as in a table instead of the text.
