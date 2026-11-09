---
temperature: 0
max_tokens: 2048
---
Nenne jeden Wert des Felds unter "field", der in den Zeilen unter "passage" steht, je Wert mit der Adresse seiner Zeile oder Zelle und seinen Worten.

* Vor jeder Zeile steht ihre Adresse. In einer Tabellenzeile trennt "|" die Zellen, ab 1 gezählt: in „19 | Rathaus | 1912 | 750.940 |“ ist 19.3 die Zelle „750.940“. Titel und Kopf einer Tabelle stehen in jedem ihrer Stücke unter denselben Adressen.
* Ein Wert ist, was das Feld nach seiner Bedeutung ("means") ist, und eine Angabe des Plans über seine Gemeinde oder etwas darin. Ein Beispiel aus einem anderen Ort und eine Vorgabe aus Gesetz, Förderrichtlinie oder Leitfaden zählen nicht, außer der Plan macht sie zu seiner eigenen.
* "at" ist die Zelle des Werts, wo er in einer Tabellenzeile steht, sonst seine Zeile. "words" ist die Zahl, wie die Zeile sie druckt, Zeichen für Zeichen, mit ihrem Vorzeichen und ohne Einheit.
* Nenne jeden Wert einmal, auch mehrere einer Zeile. Steht keiner in den Zeilen, ist "found" leer.

Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

<!-- with: headings -->
"headings" sind die Überschriften des Plans bis zu diesem Stück, die eigene zuletzt. Sie sagen, wovon das Stück handelt.
