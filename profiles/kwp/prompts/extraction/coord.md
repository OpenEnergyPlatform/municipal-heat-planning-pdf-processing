---
temperature: 0
max_tokens: 1024
---
Beantworte die Frage unter "question" für den Wert unter "value" mit der Adresse der gezeigten Zeile, die die Antwort für diesen Wert sagt, und ihren Worten; sagt keine gezeigte Zeile sie, mit 0 und einem Suchsatz.

* "value" nennt die Worte des Werts und seine Adresse unter "passage". "passage" zeigt seine Zeile, bei einer Tabelle mit ihrem Titel und Kopf, sonst mit dem Satz davor und danach.
* Vor jeder Zeile steht ihre Adresse, bei einem anderen Block mit seinem Buchstaben davor. In einer Tabellenzeile trennt "|" die Zellen, ab 1 gezählt: 19.2 ist die zweite Zelle der Zeile 19.
* Die Zeile muss über DIESEN Wert sprechen: seine eigene Zeile, der Kopf seiner Spalte, der Titel seiner Tabelle, sein Satz und die Sätze daneben, die Überschrift seines Abschnitts.
* "words" sind die Worte dieser Zeile, die die Antwort sagen, Zeichen für Zeichen, etwa „2019 bis 2021“ für einen Zeitraum.
* Sagt keine gezeigte Zeile die Antwort, ist "at" 0 und "hyde" ein Satz, wie dieser Plan die Antwort für diesen Wert drucken würde, mit seinen Namen und Bezeichnungen, etwa „Die Verbrauchswerte der kommunalen Liegenschaften beziehen sich auf das Jahr 2019.“ Der Satz darf erdacht sein: mit ihm wird nur im übrigen Plan gesucht.
* Zeigt die Form unten eine Liste "found", nenne darin jede Antwort einzeln, etwa zwei Energieträger einer Zahl; sagt keine Zeile eine, bleibt sie leer und "hyde" ist der Suchsatz.

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
