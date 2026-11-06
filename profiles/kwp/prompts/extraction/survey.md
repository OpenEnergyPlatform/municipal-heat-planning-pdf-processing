---
temperature: 0
max_tokens: 4096
---
Nenne für jede Passage aus "sources" unter ihrer "id" die Kennzahlen aus "parameters", deren Werte in genau dieser Passage stehen, und je Gruppe aus "groups" die Tupel, die für diese Werte gelten. Die Kennzahlen nennst du nur, ohne Zitat; lies dabei keine Werte ab.
Antworte mit genau einem JSON-Objekt in einer Zeile, mit einem Eintrag für jede Passage, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{"passages":{"P1":{"parameters":["emission"],"frame":[{"scenario":"Bestand","scenario_quote":"...","scenario_raw":"...","year":2022,"year_quote":"..."}]}}}

* "parameters" nennt die Schlüssel der Kennzahlen, oder genau ["out:none"], wenn kein solcher Wert darin steht. Nenne eine Kennzahl im Zweifel lieber einmal zu oft: Eine Passage mit "out:none" wird für keine Kennzahl gelesen.
* Es zählt die Art der Zahl, nicht ihr Bezug: Jede Energiemenge gehört zum Energieverbrauch, ob sie für die Gemeinde, ein Teilgebiet, ein Gebäude oder eine Maßnahme gilt und ob der Plan sie Verbrauch, Bedarf, Potenzial, Erzeugung oder Einsparung nennt; ebenso jede Emission, jede Leistung, jeder Anteil und jede Gebäudezahl. Druckt eine Tabellenzelle mehrere Zahlen, etwa einen Wert und seinen Anteil, zählt jede für ihre Kennzahl. Eine Abbildung zählt, wenn ihr Bild oder ihre Beschreibung solche Werte zeigt. Das Planungsbüro zählt, wo sein Name steht.
* Unter dem Namen jeder Gruppe steht jedes Tupel, das für die Werte dieser Passage gilt und dessen Angaben die gezeigten Passagen alle drucken; ein anderes lässt du weg. Eine Angabe mit Liste ist einer ihrer Schlüssel, "number" eine Jahreszahl mit vier Ziffern. Zu jeder Angabe gehört "<angabe>_quote": eine Stelle aus den gezeigten Passagen, Zeichen für Zeichen, die die Antwort enthält, bei einer Liste den Namen des Eintrags, eine seiner Schreibweisen oder das eigene Wort des Plans, das dann in "<angabe>_raw" steht, bei einer Jahreszahl die Zahl.
* Gibt es "corrections", antworte für alle Passagen neu und behebe die genannten Punkte.
