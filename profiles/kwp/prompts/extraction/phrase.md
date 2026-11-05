---
temperature: 0
max_tokens: 300
---
Schreibe EINEN kurzen Satz, wie er genau so in diesem Wärmeplan stehen könnte und die beschriebene Kennzahl mit einem plausiblen Wert samt Einheit nennt. Er wird eingebettet und als Suchanker gegen die Abschnitte, Tabellen und Abbildungen des Plans gehalten.
* Schreib, als stünde die Angabe schon da: keine Frage, kein Meta-Satz ("Der Endenergieverbrauch wird in Kapitel 4 dargestellt."), keine Anrede, keine Verneinung ("keine", "nicht enthalten", "liegen nicht vor").
* Nimm die Wörter deutscher Wärmepläne, nicht die der Ontologie: Endenergieverbrauch, Wärmebedarf, Energieträgermix, Bilanzjahr, Zielszenario, THG-Emissionen, Bestandsanalyse, Fokusgebiet. Zum Beispiel: "Der Endenergieverbrauch für Wärme im Stadtgebiet betrug 2022 rund 512 GWh/a."
* Steht `document` da, übernimm Wörter, Schreibweisen und Gliederungsbegriffe dieses Plans aus `name` (Gemeinde oder Titel) und `caption` (Überschrift dessen, was eine erste Suche in ihm fand), aber erfinde daraus nichts, was nicht in der Kennzahl steckt. Steht `frame` da, nenne Szenario und Jahr, wie der Plan sie schreibt. Steht `names` da (die Einträge der Liste der Kennzahl), nenne einen oder zwei davon, wie ein Plan es tut, ohne sie aufzuzählen.
* Ist die gesuchte Angabe ein Eigenname (Firma, Büro, Person, Anschrift), erfinde keinen: Schreib im knappen Stil eines Impressums- oder Titelblocks, mit den Rollenwörtern statt Namen.
* 12 bis 35 Wörter, ein Satz, höchstens zwei.
Antworte mit genau einem JSON-Objekt, ohne Markdown und ohne Text davor oder danach: `{"phrase":"..."}`
