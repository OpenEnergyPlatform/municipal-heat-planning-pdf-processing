---
temperature: 0
max_tokens: 2048
---
Nenne jede gezeigte Zeile, die einen Wert des Felds unter "field" sagt, mit ihrer Adresse und den Worten des Werts.

* Ein Wert ist, was das Feld nach seiner Bedeutung ("means") ist.
* Vor jeder Zeile steht ihre Adresse mit dem Buchstaben ihres Blocks. In einer Tabellenzeile trennt "|" die Zellen, ab 1 gezählt: A19.2 ist die zweite Zelle der Zeile A19.
* "words" sind die Worte des Werts, wie die Zeile sie druckt, Zeichen für Zeichen. Geht eine Angabe über mehrere Zeilen, reicht "at" von der ersten bis zur letzten, etwa A3-A5.
* Mehrere Werte, etwa zwei Organisationen, sind mehrere Einträge. Sagt keine Zeile einen Wert, ist "found" leer.

Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

<!-- with: title_page -->
"title_page" sind die ersten Zeilen der ersten Seite des Plans, unter dem Buchstaben T.

<!-- with: passages -->
"passages" sind Stücke des Plans, die eine Suche nach diesem Feld am besten fand, jedes unter seinem Buchstaben, mit Art, Seite und Titel.
