---
temperature: 0
max_tokens: 8192
---
For every name under "names" that means another name under "names", or several of them, give the numbers of the names it means.
"names" holds every name this publication gives a scenario under its number, each with the places under "places" it stands in: its quote with the text around it. If "corrections" is present, answer in full again and fix each point under "what".
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{"N2":["N1"],"N5":["N3","N4"]}

* Leave out every name that means only itself. If every name means only itself, answer {}.
* A name of one scenario means one name: another name under "names" of the same scenario.
* A name that stands for several scenarios, such as "the 2 °C scenarios", means the names of each of them.
* Decide by what the places say of the scenarios, not by how the names are spelled. Names of different scenarios each mean themselves.
* Answer with the numbers from "names", never with the names themselves.
