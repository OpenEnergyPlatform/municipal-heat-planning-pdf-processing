---
temperature: 0
max_tokens: 8192
---
For every name under "names", give the names under "names" of the scenarios it means.
"names" holds every name this publication gives a scenario, each with the places under "places" it stands in: its quote with the text around it. If "corrections" is present, answer in full again and fix each point under "what".
Answer with exactly one JSON object on one line, one entry per name, with no text or code block before or after it. No Backticks! In this form:
{"<<a full name>>":["<<the same full name>>"],"<<its abbreviation>>":["<<the full name>>"],"<<a name for several scenarios>>":["<<the first one's name>>","<<the second one's name>>"]}

* A name of one scenario means one name: itself, or another name under "names" of the same scenario.
* A name that stands for several scenarios, such as "the 2 °C scenarios", means the names of each of them.
* Decide by what the places say of the scenarios, not by how the names are spelled. Names of different scenarios each mean themselves.
* Copy every name character for character from "names".
