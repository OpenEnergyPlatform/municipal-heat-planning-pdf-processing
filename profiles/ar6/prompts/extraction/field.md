---
temperature: 0.1
max_tokens: 5120
---
Du bestimmst EINE Angabe zu Werten, die aus einer wissenschaftlichen Publikation schon geholt sind.

Die Werte stehen fest. Du fügst keine hinzu und lässt keine weg. Gefragt ist in dieser Anfrage genau ein Feld, und für jeden Wert beantwortest du es einzeln und belegst es einzeln.

Du bekommst ein JSON-Objekt mit diesen Feldern:

- "field": das gesuchte Feld — "name", die Frage ("question") und, wenn es eine geschlossene Liste gibt, die zulässigen Einträge ("options": je Eintrag ein Name und die Schreibweisen, unter denen er vorkommt).
- "sources": die Quellen aus DERSELBEN Publikation, jede mit einer Kennung ("id": "Q1", "Q2", …) — dieselben Texte, aus denen die Werte stammen.
- "rows": die Werte, jeder mit einer Kennung ("id": "R1", "R2", …), seiner Quelle und der Passage, in der er steht. Stammt der Wert aus einer Tabellenzeile, steht zusätzlich "column": in welcher Zelle dieser Zeile er steht, von "columns" Zellen insgesamt. Das ist ausgezählt und nicht geraten. Benennt die Kopfzeile je Spalte ein Szenario, dann entscheidet diese Nummer, welches gilt.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, ohne Einrückung:

{"groups": [{"rows": ["R1", "R2"], "value": "EN_NPi2020_400", "value_raw": "the NDC scenario", "quote": "In the NDC scenario, emissions peak before 2030 and the remaining budget is 400 GtCO2."}], "answers": {"R3": {"value": "Szenario-Familie", "value_raw": "NPi", "quote": "Results for the NPi scenarios are shown in Figure 4."}}}

Beide Formen bedeuten dasselbe. "groups" ist für den Normalfall: ein Absatz führt ein Szenario ein und belegt die Zuordnung für alle Werte, die aus ihm stammen. "answers" ist für die Zeilen, die aus der Reihe fallen. Zeilen dürfen in beiden vorkommen, dann gilt "answers".

Regeln:

1. "value": die Antwort. Gibt es "options", dann genau EIN Name daraus, Zeichen für Zeichen abgeschrieben. Nichts Eigenes, nichts Zusammengesetztes. Sonst die Bezeichnung, wörtlich aus der Quelle.

2. "value_raw": IMMER zusätzlich, der Name so, wie das Dokument ihn schreibt — "Current Policies", "the NDC scenario", "unser 1,5-Grad-Pfad". Daran wird deine Zuordnung nachträglich geprüft. "das erste Szenario" ist kein Name aus dem Dokument und keine gültige Antwort.

3. "quote": eine wörtliche, zusammenhängende Zeichenkette aus dem Text DER QUELLE, die die Zeile nennt (mindestens 8 Zeichen), und in der der Name aus "value_raw" steht. Zeichen für Zeichen kopieren. Eine Passage aus einer anderen Quelle wird verworfen.
   Das ist oft NICHT die Passage des Wertes selbst. Das Szenario wird meist einen Absatz vorher eingeführt und danach nur noch vorausgesetzt. Zitier die Stelle, an der es benannt ist.

4. Die Kennungen sind Lauf-Kennungen wie "EN_INDCi2030_300f". Im Text stehen sie fast nie; dort heißt dasselbe Szenario "Current Policies", "the NDC scenario" oder "unser 1,5-Grad-Pfad". Genau diese Zuordnung ist deine Aufgabe: die Beschreibung im Text mit der Kennung zusammenbringen. Anhaltspunkte sind das Ambitionsniveau, das Zieljahr, das Klimaziel und die Reihenfolge, in der die Publikation ihre Szenarien einführt.

5. Viele Kennungen teilen sich einen Anfang: EN_NPi2020_400, EN_NPi2020_1000 und EN_NPi2020_3000 sind DREI verschiedene Läufe. Nennt das Dokument nur die Familie ("NPi", "NDC", "das NPi-Szenario"), dann ist damit KEINE einzelne Kennung bestimmt, und du darfst dir keine aussuchen. Dafür führt die Liste den Eintrag "Szenario-Familie" — WÄHLE IHN. Eine Kennung setzt du nur, wenn der Text sie unterscheidbar macht, etwa durch das Budget, das Temperaturziel oder das Jahr, das sie im Namen trägt.
   Beschreibt die Publikation ein Szenario, das in ihrer AR6-Liste überhaupt nicht vorkommt, dann ist das der Eintrag "nicht in AR6".

6. Nennt die Quelle der Zeile überhaupt kein Szenario, lass die Zeile weg. Eine ausgelassene Zeile ist eine richtige Antwort und sagt "die Quelle sagt es nicht". Eine falsche Kennung ist schlechter als keine.
