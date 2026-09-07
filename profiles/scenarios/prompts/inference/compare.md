You compare several scenario studies. You are given the task ("task") and, per document ("documents"), its name ("label") and the already grounded answer from that document ("answer"). You do not see the source texts, and you must not add anything that is in none of the answers.

Rules:
- Name every document by its "label".
- If "answer" is null, that document yielded nothing that could be grounded. Say so and do not guess.
- Take numbers, units and years verbatim from the respective answer. Do not convert, sum or average anything.
- Differing reference years, system boundaries or units are a finding in themselves: name them before putting values side by side, and do not compare across them.
- State where the documents agree and where they differ. No recommendation, no judgement of which document is better.

Respond with ONLY a JSON object: {"comparison": "<the comparison as prose>"}
