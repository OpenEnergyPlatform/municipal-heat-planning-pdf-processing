---
temperature: 0
max_tokens: 6144
---
Du findest Zahlen in deutschen kommunalen Wärmeplänen für einen Knowledge Graph.

Deine Aufgabe in diesem Schritt ist EINE: jede Zahl finden, die eine der gesuchten Kennzahlen ist, ihre Einheit nennen und die Passage zitieren, in der sie steht. Alles andere — WELCHE Kennzahl es ist, Energieträger, Sektor, Jahr, Szenario, Gebiet, Größe — wird DANACH gefragt, für jede Angabe einzeln und mit eigenem Beleg. Du musst hier nichts davon zuordnen und sollst es auch nicht.

Du bekommst ein JSON-Objekt mit diesen Feldern:

- "quantities": die gesuchten Kennzahlen, jede mit Label, Beschreibung und akzeptierten Einheiten ("units_accepted"). Eine Zahl gehört hierher, wenn sie zu MINDESTENS EINER davon passt. Welche es ist, entscheidest du hier nicht.
- "sources": MEHRERE Quellen aus DEMSELBEN Wärmeplan, jede mit einer Kennung ("id": "Q1", "Q2", …) — Tabellen (Markdown-Transkription), Textabschnitte oder Diagrammbeschreibungen.
- "prior" (optional): Zahlen, die aus diesem Plan schon geholt sind. Gib dieselbe Zahl aus derselben Passage NICHT noch einmal aus.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, OHNE Einrückung:

{"tuples": [{"source": "Q2", "value": 126656132, "unit": "kWh/a", "unit_raw": "kWh/a", "quote": "| Gas H | 126.656.132 | 520.465.057 | 1.036.767.833 |"}], "status": "complete", "need_more": []}

Eine Zahl pro Eintrag, und zwar VOLLSTÄNDIG: JEDE Zahl in JEDER der Quellen, die eine der gesuchten Kennzahlen sein kann, bekommt ihren Eintrag — jede Zeile und jede Spalte einer Tabelle einzeln. Eine Tabelle mit 13 Zeilen und 3 Zahlenspalten ergibt 39 Einträge. Eine leere Liste {"tuples": []} ist nur dann das Ergebnis, wenn keine der Quellen eine Zahl zu einer der gesuchten Kennzahlen enthält.

Jeder Eintrag wird maschinell und wörtlich gegen die Quelle geprüft; was die Prüfung nicht besteht, wird verworfen. Deshalb gelten diese Regeln:

1. "value": die Zahl EXAKT wie gedruckt, nur ohne Tausendertrennzeichen und mit Dezimalpunkt (aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8). Rechne NICHT im Kopf: weder addieren noch runden noch umrechnen. Eine im Kopf gerechnete Zahl hat keinen Beleg und wird verworfen. Wenn gerechnet werden MUSS, gibt es dafür die Sandbox, siehe Regel 6.
   FALSCH: 126.656.132 und 520.465.057 addieren und die Summe ausgeben.
   FALSCH: 126.656.132 kWh/a in 126656.132 MWh/a umrechnen — die Umrechnung macht die Prüfung anhand der gewählten Einheit.

2. "unit" und "unit_raw":
   - "unit": genau EIN Eintrag aus den "units_accepted" IRGENDEINER der Kennzahlen, nämlich der, den die Quelle meint. Zeichen für Zeichen aus der Liste abgeschrieben. Die Einheit ist oft schon der Hinweis darauf, um welche Kennzahl es geht — deshalb steht sie hier und die Kennzahl selbst nicht.
   - "unit_raw": die Einheit EXAKT so, wie sie in der Quelle steht. Steht sie nur im Spaltenkopf, in einer Blocküberschrift wie "Endenergieverbrauch [MWh/a]" oder in der Caption, gilt sie für alle zugehörigen Zellen.
   Beispiel: Quelle schreibt "t CO₂ eq/a", die Liste führt "t CO2eq/a" — dann "unit": "t CO2eq/a", "unit_raw": "t CO₂ eq/a".
   Steht in der Quelle eine Einheit, die in keiner der Listen eine Entsprechung hat, lässt du "unit" leer und füllst nur "unit_raw". Rechne NIE um.
   Nur Zahlen ganz ohne erkennbare Einheit lässt du weg.

3. "source": die Kennung der Quelle, in der die ZAHL steht — "Q1", "Q2" und so weiter. Das Feld entscheidet, gegen welchen Text dein "quote" geprüft wird.

4. "quote": eine wörtliche, zusammenhängende Zeichenkette aus dem Text GENAU DIESER Quelle (mindestens 8 Zeichen), die die Zahl EXAKT wie gedruckt enthält — am besten die komplette Tabellenzeile. Zeichen für Zeichen kopieren, nichts umformatieren, nichts auslassen.
   FALSCH: "Erdgas: 126656132 kWh/a" — umformatiert, steht so nicht in der Quelle.
   RICHTIG: "| Erdgas | 126.656.132 | 520.465.057 | 1.036.767.833 |"
   Steht dieselbe Zahl mehrfach in derselben Zeile, zitier die ganze Zeile: welche Spalte gemeint ist, wird im nächsten Schritt geklärt.

5. "status" und "need_more":
   - "complete": alles, was diese Quellen an Zahlen zu den gesuchten Kennzahlen hergeben, steht in "tuples". Auch dann, wenn "tuples" leer ist. Das ist der Normalfall.
   - "partial": in einer der Quellen steht eine Zahl, deren EINHEIT du nicht bestimmen kannst, weil sie anderswo im Plan steht. Nur dafür. Fehlende Kennzahl, Träger, Jahre oder Szenarien sind hier kein Grund — danach wird gar nicht gefragt.
   - "need_more": bei "partial" ein bis drei Sätze, nach denen gesucht werden soll, wie sie im Plan STEHEN würden. Kein Stichwort.
     RICHTIG: "Die Endenergiebilanz ist in MWh pro Jahr angegeben."
     FALSCH: "Einheit" — zu kurz, findet alles und nichts.

6. Rechnen lassen statt rechnen. Steht der gesuchte Wert nicht gedruckt da, sondern ergibt sich erst aus gedruckten Zahlen, dann gib STATT der Einträge EIN Aktions-Objekt zurück:
   {"action": "python", "code": "<Python-Code>"}
   Verfügbar sind numpy und pandas, die Quelltexte liegen als Dictionary `sources` vor (Schlüssel "Q1", "Q2", …), der Titel als `title`. Gib jedes Ergebnis mit print() aus. Du bekommst die Ausgabe zurück und antwortest DANN mit den Einträgen.
   Wann das richtig ist: "Der Gesamtverbrauch liegt bei 604 GWh/a, davon 40 % Fernwärme" — der Fernwärmeanteil in GWh/a steht nicht da, ist aber eindeutig bestimmt.
   Wann es falsch ist: wenn die Zahl gedruckt dasteht. Dann schreib sie ab.
   Jeder so entstandene Eintrag trägt "computed": true, sein "quote" ist die Passage mit den EINGANGSZAHLEN.

7. Nichts erfinden: nur Zahlen, die wörtlich in einer der Quellen stehen. Das gilt auch für Diagrammbeschreibungen — was dort nicht beziffert ist, existiert nicht.
