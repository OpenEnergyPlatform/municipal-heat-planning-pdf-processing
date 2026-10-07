---
# An optional part that joins a sentence (quote_why, scenario_raw_more,
# candidates_examples) starts with a space: a part is put in as it is written,
# and one that is left out leaves nothing behind.
required: [role, pair_example, raw_word, year_rules]
optional: [quote_why, scenario_raw_more, candidates_examples]
---
{{role}}

Du bekommst Abschnitte, Tabellen und Abbildungen aus EINEM Dokument. Deine Aufgabe ist nicht, Zahlen zu lesen. Deine Aufgabe ist, den RAHMEN dieses Dokuments zu bestimmen: welche Szenarien es führt, und für welche Jahre jeweils.

Ein Rahmenpaar ist eine Kombination, die in diesem Dokument WIRKLICH vorkommt. Kein Kreuzprodukt: {{pair_example}}

Für jedes Paar:

- `scenario` ist einer der Schlüssel aus "{{frame_options}}". Wähle, generiere nicht.
- `scenario_raw` ist {{raw_word}}{{scenario_raw_more}}
- `year` ist eine vierstellige Jahreszahl.
- `scenario_quote` und `year_quote` sind je eine Passage, Zeichen für Zeichen aus "sources" kopiert.{{quote_why}} Steht beides in derselben Passage, nimm zweimal dieselbe.
- `scenario_source` und `year_source` sind die `id` der Quelle, aus der die jeweilige Passage stammt.

Der Beleg muss die Antwort ENTHALTEN. `year_quote` muss die Jahreszahl selbst enthalten, `scenario_quote` das Wort aus `scenario_raw`.

{{year_rules}}

Sagen die gezeigten Passagen zu wenig, setze `status` auf "incomplete" und schreib in `need_more` ein bis drei kurze Aussagen, wie sie im Dokument stehen könnten und die fehlende Angabe konkret enthalten. Keine Fragen. Findest du gar nichts, gib `pairs: []` und `status: "incomplete"`.

Steht ein Feld "candidates" im Objekt, sind das vierstellige Zahlen, die in genau diesen Passagen stehen und die im ersten Durchgang kein Bezugsjahr wurden. Pruef jede einzeln: ist sie doch ein Bezugsjahr, gib das Paar aus, mit Beleg wie jedes andere. Ist sie keines{{candidates_examples}}, lass sie weg. Erfinde zu keiner davon einen Beleg.

Steht ein Feld "known" im Objekt, sind das Paare, die schon gefunden wurden. Wiederhole sie nicht, such nach weiteren.

Steht ein Feld "corrections" im Objekt, sind das die Gründe, aus denen Paare deiner letzten Antwort verworfen wurden. Lies jeden und antworte erneut: mit dem Beleg, der gefehlt hat, oder mit dem Schlüssel aus "{{frame_options}}", der gepasst hätte. Ein Paar, das du nicht belegen kannst, lässt du weg.

Antworte mit NUR einem JSON-Objekt, kein Markdown, kein Text davor oder danach:
{"pairs": [{"scenario": "<Schlüssel>", "scenario_raw": "<Wort des Dokuments>", "scenario_quote": "<Passage>", "scenario_source": "<id>", "year": <Jahr>, "year_quote": "<Passage>", "year_source": "<id>"}], "status": "complete", "need_more": []}
