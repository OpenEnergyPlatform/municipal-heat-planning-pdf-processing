<!-- way: answer_with=address -->
Nenne jede gezeigte Zeile, die einen Wert des Felds unter "field" sagt, mit ihrer Adresse und den Worten des Werts.
<!-- way: answer_with=quote -->
Nenne jede gezeigte Zeile, die einen Wert des Felds unter "field" sagt, unter "quote" Zeichen für Zeichen, mit den Worten des Werts.
<!-- /way -->

* Ein Wert ist, was das Feld nach seiner Bedeutung ("means") ist.
* Vor jeder Zeile steht ihre Adresse mit dem Buchstaben ihres Blocks. Eine Zeile, die "|" teilt, hat Zellen, ab 1 gezählt, wo immer sie steht: A19.2 ist die zweite Zelle der Zeile A19.
* Worte, die nur benennen, worum es im Feld geht, etwa ein Titel oder eine Überschrift, die das Thema der Zeilen darunter nennt, sind kein Wert.
<!-- way: answer_with=address -->
* "words" sind die Worte des Werts, wie die Zeile sie druckt, Zeichen für Zeichen. Geht eine Angabe über mehrere Zeilen, reicht "at" von der ersten bis zur letzten, etwa A3-A5.
<!-- way: answer_with=quote -->
* "words" sind die Worte des Werts, wie die Zeile sie druckt, Zeichen für Zeichen. Geht eine Angabe über mehrere Zeilen, steht unter "quote" der Text aller dieser Zeilen, ohne ihre Adressen.
<!-- /way -->
* Mehrere Werte, etwa zwei Organisationen, sind mehrere Einträge.

Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! Wo Zeilen Werte drucken, in dieser Form:
{{example}}
Wo keine Zeile einen druckt, in dieser Form:
{{nothing}}

<!-- with: list -->
"list" nennt die Einträge, die ein Wert dieses Felds sein kann, jeden unter seiner Nummer. "entry" ist die Nummer des Eintrags, den die Worte eines Werts meinen, nach der Bedeutung, nicht nach der Schreibweise: der genaueste Eintrag, den die Worte tragen, 0 wenn keiner passt. Nennt "list" Gruppen von Einträgen, ist "entry" die Nummer der Gruppe.

<!-- with: title_page -->
"title_page" sind die ersten Zeilen der ersten Seite des Plans, unter dem Buchstaben T.

<!-- with: passages -->
"passages" sind Stücke des Plans, die eine Suche nach diesem Feld am besten fand, jedes unter seinem Buchstaben, mit Art, Seite und Titel.
