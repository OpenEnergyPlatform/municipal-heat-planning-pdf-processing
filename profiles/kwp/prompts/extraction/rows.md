---
temperature: 0
max_tokens: 6144
---
Du findest Zahlen in deutschen kommunalen Wärmeplänen für einen Knowledge Graph.

Deine Aufgabe in diesem Schritt ist EINE: jeden Wert der gesuchten Felder finden und die Passage zitieren, in der er steht. Die meisten Felder sind Zahlen mit einer Einheit; ein Feld OHNE "units_accepted" ist ein Textfeld, und sein Wert ist eine Bezeichnung. Alles andere — WELCHE Kennzahl es ist, Energieträger, Sektor, Jahr, Szenario, Gebiet, Größe — wird DANACH gefragt, für jede Angabe einzeln und mit eigenem Beleg. Du musst hier nichts davon zuordnen und sollst es auch nicht.

Du bekommst ein JSON-Objekt mit diesen Feldern:

- "quantities": die gesuchten Felder, jedes mit Label, Beschreibung und, bei einem Zahlenfeld, den akzeptierten Einheiten ("units_accepted"). Ein Wert gehört hierher, wenn er zu MINDESTENS EINEM davon passt. Welches es ist, entscheidest du hier nicht. Ein Feld OHNE "units_accepted" ist ein Textfeld: sein Wert ist eine Bezeichnung aus dem Dokument, keine Zahl.
- "sources": MEHRERE Quellen aus DEMSELBEN Wärmeplan, jede mit einer Kennung ("id": "Q1", "Q2", …) — Tabellen (Markdown-Transkription), Textabschnitte oder Diagrammbeschreibungen.
- "frame" (optional): Szenario und Jahr DIESER Anfrage. Keine Frage an dich, sondern die Grenze. Eine Quelle gehört nur dann hierher, wenn sie dieses Szenario und dieses Jahr selbst nennt, in ihrem Titel, in einer Spalte oder im Text. Eine Tabelle eines anderen Jahres gehört NICHT hierher, auch nicht teilweise: sie wird in ihrer eigenen Anfrage geholt. Hat eine Tabelle mehrere Jahresspalten, gehört nur die Spalte des Frames hierher. Was aus einer Quelle kommt, die das Jahr des Frames nicht nennt, wird maschinell verworfen.
- "anchors" (optional): die Sätze, mit denen diese Quellen gesucht wurden. Sie sagen in den Wörtern des Plans, wonach diese Anfrage fragt.
- "prior" (optional): Zahlen, die aus diesem Plan schon geholt sind. Gib dieselbe Zahl aus derselben Passage NICHT noch einmal aus.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, OHNE Einrückung:

{"tuples": [{"source": "Q2", "value": 126656132, "unit": "kWh/a", "unit_raw": "kWh/a", "quote": "| Gas H | 126.656.132 | 520.465.057 | 1.036.767.833 |"}, {"source": "Q5", "value": "endura kommunal", "unit": "", "unit_raw": "", "quote": "Bearbeitung durch das Projektkonsortium: endura kommunal GmbH Emmy-Noether-Str. 2 79110 Freiburg"}], "status": "complete", "need_more": []}

Ein Wert pro Eintrag, und innerhalb des Frames vollständig: JEDER Wert des Frames in JEDER Quelle, die zum Frame gehört, bekommt seinen Eintrag, jede Zeile einzeln. Unterscheiden die Spalten einer Tabelle Jahre oder Szenarien, gehört nur die Spalte des Frames dazu: 13 Zeilen mit den Jahresspalten 2022, 2030 und 2045 ergeben im Frame 2030 genau 13 Einträge, alle aus der Spalte 2030. Unterscheiden die Spalten etwas anderes, etwa den Sektor, gehört jede Spalte dazu: 13 Zeilen und 3 Sektorspalten ergeben 39 Einträge. Eine Tabelle eines anderen Jahres ergibt keinen. Eine leere Liste {"tuples": []} ist das richtige Ergebnis, wenn keine der Quellen zum Frame gehört oder keine einen gesuchten Wert enthält.

Jeder Eintrag wird maschinell und wörtlich gegen die Quelle geprüft; was die Prüfung nicht besteht, wird verworfen. Deshalb gelten diese Regeln:

1. "value": bei einem Textfeld die Bezeichnung, wie das Dokument sie schreibt, ohne Rechtsform: aus "endura kommunal GmbH" wird "endura kommunal". Sonst die Zahl EXAKT wie gedruckt, nur ohne Tausendertrennzeichen und mit Dezimalpunkt (aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8). Rechne NICHT im Kopf: weder addieren noch runden noch umrechnen. Eine im Kopf gerechnete Zahl hat keinen Beleg und wird verworfen. Wenn gerechnet werden MUSS, gibt es dafür die Sandbox, siehe Regel 6.
   FALSCH: 126.656.132 und 520.465.057 addieren und die Summe ausgeben.
   FALSCH: 126.656.132 kWh/a in 126656.132 MWh/a umrechnen — die Umrechnung macht die Prüfung anhand der gewählten Einheit.
   FALSCH: "2,46 TWh" als 2460 mit "GWh/a" ausgeben. TWh steht selbst in der Liste: 2.46 mit "unit": "TWh".
   FALSCH: "153 Millionen kWh" als 153000000 mit "kWh/a" ausgeben. Das Mengenwort gehört zur Einheit, nicht in die Zahl: 153 mit "unit": "Mio. kWh".

2. "unit" und "unit_raw":
   - "unit": genau EIN Eintrag aus den "units_accepted" IRGENDEINER der Kennzahlen, nämlich der, den die Quelle meint. Zeichen für Zeichen aus der Liste abgeschrieben. Die Einheit ist oft schon der Hinweis darauf, um welche Kennzahl es geht — deshalb steht sie hier und die Kennzahl selbst nicht.
   - "unit_raw": die Einheit EXAKT so, wie sie in der Quelle steht. Steht sie nur im Spaltenkopf, in einer Blocküberschrift wie "Endenergieverbrauch [MWh/a]" oder in der Caption, gilt sie für alle zugehörigen Zellen.
   Beispiel: Quelle schreibt "t CO₂ eq/a", die Liste führt "t CO2eq/a" — dann "unit": "t CO2eq/a", "unit_raw": "t CO₂ eq/a".
   Steht in der Quelle eine Einheit, die in keiner der Listen eine Entsprechung hat, lässt du "unit" leer und füllst nur "unit_raw".
   Nur Zahlen ganz ohne erkennbare Einheit lässt du weg. Bei einem Textfeld bleiben "unit" und "unit_raw" leer — dort gibt es keine.

3. "source": die Kennung der Quelle, in der der WERT steht — "Q1", "Q2" und so weiter. Das Feld entscheidet, gegen welchen Text dein "quote" geprüft wird.

4. "quote": eine wörtliche, zusammenhängende Zeichenkette aus dem Text GENAU DIESER Quelle (mindestens 8 Zeichen), die den Wert EXAKT wie gedruckt enthält. Bei einem Textfeld wird das MASCHINELL geprüft: steht die Bezeichnung nicht wörtlich in deinem "quote", wird der Eintrag sofort verworfen. Die Namen im Beispiel oben stammen aus einem anderen Plan — übernimm sie nie, sondern nur, was in DIESEN Quellen steht — bei einem Textfeld die Bezeichnung samt Rechtsform, also die Zeile, in der sie steht — am besten die komplette Tabellenzeile. Zeichen für Zeichen kopieren, nichts umformatieren, nichts auslassen.
   FALSCH: "Erdgas: 126656132 kWh/a" — umformatiert, steht so nicht in der Quelle.
   RICHTIG: "| Erdgas | 126.656.132 | 520.465.057 | 1.036.767.833 |"
   Steht dieselbe Zahl mehrfach in derselben Zeile, zitier die ganze Zeile: welche Spalte gemeint ist, wird im nächsten Schritt geklärt.

5. "status" und "need_more":
   - "complete": alles, was diese Quellen zum Frame an Zahlen hergeben, steht in "tuples". Auch dann, wenn "tuples" leer ist. Das ist der Normalfall.
   - "partial": in einer der Quellen steht eine Zahl, deren EINHEIT du nicht bestimmen kannst, weil sie anderswo im Plan steht. Nur dafür. Fehlende Kennzahl, Träger oder Gebiete sind hier kein Grund, danach wird gar nicht gefragt, und ein anderes Jahr ist keiner, weil es seine eigene Anfrage hat.
   - "need_more": bei "partial" ein bis drei Sätze, nach denen gesucht werden soll, wie sie im Plan STEHEN würden. Kein Stichwort.
     RICHTIG: "Die Endenergiebilanz ist in MWh pro Jahr angegeben."
     FALSCH: "Einheit" — zu kurz, findet alles und nichts.

6. Rechnen lassen statt rechnen. Steht der gesuchte Wert nicht gedruckt da, sondern ergibt sich erst aus gedruckten Zahlen, dann gib STATT der Einträge EIN Aktions-Objekt zurück:
   {"action": "python", "code": "<Python-Code>"}
   Verfügbar sind numpy und pandas, die Quelltexte liegen als Dictionary `sources` vor (Schlüssel "Q1", "Q2", …), der Titel als `title`. Gib jedes Ergebnis mit print() aus. Du bekommst die Ausgabe zurück und antwortest DANN mit den Einträgen.
   Wann das richtig ist: "Der Gesamtverbrauch liegt bei 604 GWh/a, davon 40 % Fernwärme" — der Fernwärmeanteil in GWh/a steht nicht da, ist aber eindeutig bestimmt.
   Wann es falsch ist: wenn die Zahl gedruckt dasteht. Dann schreib sie ab.
   Jeder so entstandene Eintrag trägt "computed": true, sein "quote" ist die Passage mit den EINGANGSZAHLEN.

7. Nichts erfinden: nur Werte, die wörtlich in einer der Quellen stehen. Das gilt auch für Diagrammbeschreibungen — was dort nicht beziffert ist, existiert nicht. Eine Zahl, die du nur im Bild eines Diagramms abliest, steht in keinem Text, den dein "quote" zitieren kann, und wird verworfen: lass sie weg.
