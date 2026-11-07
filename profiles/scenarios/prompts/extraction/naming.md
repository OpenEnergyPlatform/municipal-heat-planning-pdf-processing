---
temperature: 0
max_tokens: 2048
---
For the name under "name", give the numbers of every name under "names" that names the same scenario, its own number among them; where it stands for several scenarios, the numbers of the names of each of them instead, without its own.
"name" is one name this publication gives a scenario, with its number and the places it stands in: its quote with the text around it. "names" holds this name and the other names of the publication that may name the same scenario, each under its number with the quote it was read with.
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

* Two names name the same scenario only where either can stand for the other without losing anything the publication says of it: a short and a long form of one scenario's name can; the name of a group of scenarios and the name of one of them cannot.
* A name of one scenario: its own number and the numbers of the other names of that scenario, or its own number alone where "names" holds no other name of it.
* A name that stands for several scenarios, such as "the 2 °C scenarios": the numbers of the names of each of them, without its own.
* Decide by what the places and quotes say of the scenarios, not by how the names are spelled.
* Answer with the numbers from "names", never with the names themselves.

<!-- follow-up: corrections -->
Your last answer has a mistake, under "what". Answer again and fix it.
