---
template: field
without: [base_years, year_value, no_guessing, closed_out, by_meaning, found_next]
temperature: 0
max_tokens: 5120
---
<!-- part: subject -->
Werten, die aus einer wissenschaftlichen Publikation schon geholt sind

<!-- part: rows_more -->
Benennt die Kopfzeile je Spalte ein Szenario, dann entscheidet diese Nummer, welches gilt.

<!-- part: example_reply -->
{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2"], "value": "EN_NPi2020_400", "value_raw": "the NDC scenario", "quote": "In the NDC scenario, emissions peak before 2030 and the remaining budget is 400 GtCO2."}], "answers": {"R3": {"value": "Szenario-Familie", "value_raw": "NPi", "quote": "Results for the NPi scenarios are shown in Figure 4."}}}}}

<!-- part: groups_note -->
ein Absatz führt ein Szenario ein und belegt die Zuordnung für alle Werte, die aus ihm stammen.

<!-- part: value_raw_is -->
der Name so, wie das Dokument ihn schreibt — "Current Policies", "the NDC scenario", "unser 1,5-Grad-Pfad"

<!-- part: value_raw_more -->
"das erste Szenario" ist kein Name aus dem Dokument und keine gültige Antwort.

<!-- part: quote_more -->
Kurz halten: der Satzteil, der die Antwort trägt, nicht der ganze Absatz. Zeichen für Zeichen kopieren, auch Zahlen, die mitten im Text stehen, etwa Zeilennummern eines Manuskripts („Horizon 311 2020“): sie gehören zur Zeichenkette. Erfundene oder geglättete Passagen werden verworfen, und mit ihnen die Antwort.

<!-- part: domain_rule_1 -->
Die Kennungen sind Lauf-Kennungen wie "EN_INDCi2030_300f". Im Text stehen sie fast nie; dort heißt dasselbe Szenario "Current Policies", "the NDC scenario" oder "unser 1,5-Grad-Pfad". Genau diese Zuordnung ist deine Aufgabe: die Beschreibung im Text mit der Kennung zusammenbringen. Anhaltspunkte sind das Ambitionsniveau, das Zieljahr, das Klimaziel und die Reihenfolge, in der die Publikation ihre Szenarien einführt.

<!-- part: domain_rule_2 -->
Viele Kennungen teilen sich einen Anfang: EN_NPi2020_400, EN_NPi2020_1000 und EN_NPi2020_3000 sind DREI verschiedene Läufe. Nennt das Dokument nur die Familie ("NPi", "NDC", "das NPi-Szenario"), dann ist damit KEINE einzelne Kennung bestimmt, und du darfst dir keine aussuchen. Dafür führt die Liste den Eintrag "Szenario-Familie" — WÄHLE IHN. Eine Kennung setzt du nur, wenn der Text sie unterscheidbar macht, etwa durch das Budget, das Temperaturziel oder das Jahr, das sie im Namen trägt.
   Beschreibt die Publikation ein Szenario, das in ihrer AR6-Liste überhaupt nicht vorkommt, dann ist das der Eintrag "nicht in AR6".

<!-- part: need_more_example -->
   RICHTIG: "The NDC scenario assumes that pledges are implemented by 2030."
   FALSCH: "scenario" — zu kurz, findet alles und nichts.

<!-- part: rows_carry -->
die Werte, jeder mit einer Kennung ("id": "R1", "R2", …), seiner Quelle und der Passage, in der er steht.

<!-- part: unstated_when -->
Nennen die gezeigten Passagen überhaupt kein Szenario
