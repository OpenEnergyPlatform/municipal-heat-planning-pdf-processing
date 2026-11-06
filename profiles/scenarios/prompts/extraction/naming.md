---
temperature: 0
max_tokens: 8192
---
For every name under "names", give the numbers of the names it means: its own number, the number of another name of the same scenario, or several numbers where it stands for several scenarios.
"names" holds every name this publication gives a scenario under its number, each with the places under "places" it stands in: its quote with the text around it. If "corrections" is present, answer in full again and fix each point under "what".
Answer with exactly one JSON object on one line, one entry per name, with no text or code block before or after it. No Backticks! In this form:
{"N1":["N1"],"N2":["N1"],"N3":["N3"],"N4":["N4"],"N5":["N3","N4"]}

* Answer every name under "names", each under its number.
* A name of one scenario means one name: itself, or another name under "names" of the same scenario. If no other name under "names" names its scenario, it means itself, even where you know the scenario by a name that is not under "names".
* A name that stands for several scenarios, such as "the 2 °C scenarios", means the names of each of them.
* Decide by what the places say of the scenarios, not by how the names are spelled. Names of different scenarios each mean themselves.
* Answer with the numbers from "names", never with the names themselves.
