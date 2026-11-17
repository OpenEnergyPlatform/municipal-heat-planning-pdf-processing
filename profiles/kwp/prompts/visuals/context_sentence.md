---
temperature: 0.1
max_tokens: 400
---
Du schreibst einen Satz Kontext zu einer Tabelle oder einer Abbildung eines Dokuments, damit eine Suche die Tabelle oder die Abbildung findet, wenn jemand nach ihren Zahlen fragt.

Eingabe: ein JSON-Objekt mit "kind" ("table" oder "figure"), "section_heading" (die Überschrift des Abschnitts, in dem sie steht), "caption" (ihre Beschriftung, kann leer sein) und "head" (die ersten Zeilen der Tabelle oder der Anfang der Beschreibung der Abbildung).

Schreibe einen Satz, der sagt, wovon die Tabelle oder Abbildung handelt, in welcher Einheit, für welches Gebiet, für welches Szenario und für welche Jahre, soweit Beschriftung, Kopf und Abschnittsüberschrift es sagen. Nimm die Wörter des Dokuments. Lass weg, was sie nicht sagen: rate keine Einheit, kein Gebiet, kein Szenario und kein Jahr, und füge keine Zahl hinzu.

Antworte mit genau einem JSON-Objekt und sonst nichts: {"sentence": "<der Satz>"}.

Beispieleingabe: {"kind": "table", "section_heading": "Endenergiebedarf", "caption": "Endenergiebedarf nach Energieträgern", "head": "| Energieträger | 2019 | 2030 | 2045 |
| --- | --- | --- | --- |
| Erdgas (GWh/a) | 410 | 300 | 20 |"}
Beispielantwort: {"sentence": "Endenergiebedarf nach Energieträgern in GWh pro Jahr für die Jahre 2019, 2030 und 2045."}
