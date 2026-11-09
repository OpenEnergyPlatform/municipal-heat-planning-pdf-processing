---
temperature: 0
max_tokens: 2048
---
Nenne jeden Wert des Felds unter "field", der in den Zeilen unter "passage" steht, je Wert mit der Adresse seiner Zeile oder Zelle und seinen Worten.

* Vor jeder Zeile steht ihre Adresse. Eine Zeile, die "|" teilt, hat Zellen, ab 1 gezählt, wo immer sie steht: in „19 | Rathaus | 1912 | 750.940 |“ ist 19.3 die Zelle „750.940“. Titel und Kopf einer Tabelle stehen in jedem ihrer Stücke unter denselben Adressen, ebenso Titel, Achsen und Legende einer Abbildung.
* Ein Wert ist, was das Feld nach seiner Bedeutung ("means") ist, und eine Angabe des Plans über seine Gemeinde oder etwas darin. Ein Beispiel aus einem anderen Ort und eine Vorgabe aus Gesetz, Förderrichtlinie oder Leitfaden zählen nicht, außer der Plan macht sie zu seiner eigenen.
* Worte, die nur benennen, worum es im Feld geht, etwa ein Titel oder eine Überschrift, die das Thema der Zeilen darunter nennt, sind kein Wert.
* "at" ist die Zelle des Werts, wo er in einer Zeile mit Zellen steht, sonst seine Zeile. "words" ist die Zahl, wie die Zeile sie druckt, Zeichen für Zeichen, mit ihrem Vorzeichen und ohne Einheit.
* Nenne jeden Wert einmal, auch mehrere einer Zeile.

Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! Wo Zeilen Werte drucken, in dieser Form:
{{example}}
Wo keine Zeile einen druckt, in dieser Form:
{{nothing}}

<!-- with: list -->
"list" nennt die Einträge, die ein Wert dieses Felds sein kann, jeden unter seiner Nummer. "entry" ist die Nummer des Eintrags, den die Worte eines Werts meinen, nach der Bedeutung, nicht nach der Schreibweise: der genaueste Eintrag, den die Worte tragen, 0 wenn keiner passt. Nennt "list" Gruppen von Einträgen, ist "entry" die Nummer der Gruppe.

<!-- with: headings -->
"headings" sind die Überschriften des Plans bis zu diesem Stück, die eigene zuletzt. Sie sagen, wovon das Stück handelt.
