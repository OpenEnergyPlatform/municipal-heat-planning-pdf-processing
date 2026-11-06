---
temperature: 0
max_tokens: 2048
---
For the name under "name", give the numbers of the names under "names" it means: its own number, the number of another name of the same scenario, or several numbers where it stands for several scenarios.
"name" is one name this publication gives a scenario, with its number and the places it stands in: its quote with the text around it. "names" holds every name the publication gives a scenario under its number, this one included, each with the quote it was read with. If "corrections" is present, answer again and fix the point under "what".
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

* A name of one scenario means one name: itself, or another name under "names" of the same scenario. If no other name under "names" names its scenario, it means itself, even where you know the scenario by a name that is not under "names".
* A name that stands for several scenarios, such as "the 2 °C scenarios", means the names of each of them.
* Decide by what the places and quotes say of the scenarios, not by how the names are spelled. Names of different scenarios each mean themselves.
* Answer with the numbers from "names", never with the names themselves.
