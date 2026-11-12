Nenne die Nummer des Eintrags unter "list", den die Worte unter "words" als Antwort auf die Frage unter "question" bedeuten.

* Entscheide nach der Bedeutung, nicht nach der Schreibweise: was ein Eintrag bedeutet, steht hinter "means". „Gigawattstunden“ meint GWh, „Wärmebedarf“ einen Verbrauch.
* Wähle den genauesten Eintrag, den die Worte tragen. Ob eine Menge je Jahr gilt, sagt oft erst die Zeile: „pro Jahr“ oder „im Jahr 2021“ machen aus kWh den Eintrag kWh/a. Rechne nie um.
* 0 heißt: kein Eintrag meint diese Worte, etwa eine Einheit je Fläche, je Einwohner oder je Kilowattstunde.
* Zeigt die Form unten eine Liste, nenne jeden Eintrag, den die Worte meinen, etwa zwei Energieträger.

Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

<!-- with: lines -->
"lines" sind die Zeilen des Plans, in denen die Worte stehen.

<!-- with: table -->
"table" ist der Titel der Tabelle, in der sie stehen.

<!-- with: settings -->
"settings" sind Festlegungen, die der Plan für alle seine Werte trifft. Sie gelten auch hier, wo sie über diese Worte sprechen.

<!-- with: value -->
Hier zeigt "passage" die Stelle des Werts unter "value", vor jeder Zeile ihre Adresse, und "list" nennt Basis- und Zieljahr des Plans (base, target) mit der Zeile, die sie sagt. Nenne unter "at" die Adresse der gezeigten Zeile, die für diesen Wert das Wort des Plans für seinen Stand oder sein Ziel trägt, etwa „Basisjahr“, „Ist-Zustand“ oder „Zieljahr“, unter "words" dieses Wort und unter "entry" das Jahr der Liste, das es meint. Trägt keine Zeile ein solches Wort, ist "entry" 0.

<!-- with: headings -->
"headings" sind die Überschriften des Plans bis zur Stelle des Werts, die eigene zuletzt, unter dem Buchstaben H.

<!-- with: title_page -->
"title_page" sind die ersten Zeilen der ersten Seite des Plans, unter dem Buchstaben T.
