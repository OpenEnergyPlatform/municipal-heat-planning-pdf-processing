---
temperature: 0
max_tokens: 512
---
Give the key of `options` that is the scenario `name`, as the publication prints it in `quote`. `options` are this publication's runs in the AR6 database.
Return exactly one line of JSON: `{"value":"..."}`

* The keys are run identifiers such as "EN_INDCi2030_300f", which the text almost never prints. Match by what `quote`, `source` and `around` say of the scenario: its level of ambition, target year, climate target and budget, and the order in which the publication introduces its scenarios.
* Identifiers that differ in one part only, such as EN_NPi2020_400 and EN_NPi2020_1000, are different runs. Choose a run only when these details identify exactly one.
* "scenario family" is the answer when several runs fit, "not in AR6" when the scenario is none of them.
* If `corrections` is present, answer again and fix the point under `what`.

Answer with exactly one JSON object, with no text or code block before or after it.
