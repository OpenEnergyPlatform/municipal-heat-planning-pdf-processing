<!-- way: answer_with=address -->
Beantworte die Frage unter "question" für den Wert unter "value" mit der Adresse einer Zeile unter "passages", die die Antwort für diesen Wert sagt, und ihren Worten; sagt keine sie, ist "at" 0.
<!-- way: answer_with=quote -->
Beantworte die Frage unter "question" für den Wert unter "value" mit einer Zeile unter "passages", die die Antwort für diesen Wert sagt, unter "quote" Zeichen für Zeichen, und ihren Worten; sagt keine sie, ist "quote" 0.
<!-- /way -->

* "value" nennt die Worte des Werts und seine Adresse unter "passage", seiner eigenen Stelle; dort steht die Antwort nicht. "passages" sind weitere Stücke des Plans, jedes unter seinem Buchstaben, mit Art, Seite und Titel.
* Vor jeder Zeile steht ihre Adresse mit dem Buchstaben ihres Blocks. Eine Zeile, die "|" teilt, hat Zellen, ab 1 gezählt, wo immer sie steht: A19.2 ist die zweite Zelle der Zeile A19.
* Eine Zeile zählt nur, wenn sie über DIESEN Wert spricht: über dieselbe Aussage, über die Tabelle oder Abbildung, in der er steht, oder über den Abschnitt oder den Zustand, von dem seine Stelle spricht. Eine Zeile über eine andere Tabelle, ein anderes Jahr, eine andere Aussage oder den Plan im Allgemeinen zählt nicht, auch wenn sie die gesuchte Angabe nennt.
* "words" sind die Worte dieser Zeile, die die Antwort sagen, Zeichen für Zeichen. Zeigt die Form unten eine Liste "found", nenne darin jede Antwort einzeln.
* "more" holt Stücke, die du noch brauchst: {"get":"next"} das Stück nach dem letzten gezeigten, {"get":"previous"} das davor, {"get":"item","id":"p17_img1"} die Tabelle oder Abbildung, die eine Zeile mit „[p17_img1 …]“ nennt, {"get":"search","pattern":"Bilanzjahr"} die Stücke, in denen ein Muster steht, {"get":"similar","text":"…"} die Stücke, die einem Satz am nächsten sind; der Satz steht so da, wie der Plan ihn drucken würde, nie als Frage.

Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

<!-- with: field -->
"field" ist das Feld des Werts mit seiner Bedeutung ("means").

<!-- with: known -->
"known" sagt, was über diesen Wert schon gelesen ist, in den Worten des Plans.

<!-- with: headings -->
"headings" sind die Überschriften des Plans bis zur Stelle des Werts, die eigene zuletzt, unter dem Buchstaben H.

<!-- with: title_page -->
"title_page" sind die ersten Zeilen der ersten Seite des Plans, unter dem Buchstaben T.

<!-- with: settings -->
"settings" sind Festlegungen, die der Plan für alle seine Werte trifft, unter dem Buchstaben F. Sie gelten auch für diesen Wert, wo sie über ihn sprechen.

<!-- with: get_image -->
{"get":"image"} unter "more" fordert das Bild der Abbildung an, in der der Wert steht, {"get":"image","id":"B"} das Bild der Abbildung unter Buchstabe B: wenn die Zeilen der Abbildung die Antwort nicht sagen, ihr Bild sie aber zeigt, etwa die Farbe eines Legendeneintrags oder das Stück eines Balkens. Die Frage kommt dann mit dem Bild noch einmal; die Antwort bleibt eine gezeigte Zeile, etwa die Legendenzeile dieser Farbe.

<!-- with: image -->
Das Bild der Abbildung unter "image" ("passage": die Abbildung, in der der Wert steht) hängt an. Lies darin, was ihre Zeilen nicht sagen, und antworte mit der gezeigten Zeile, die es nennt, etwa der Legendenzeile der Farbe.
