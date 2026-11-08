---
temperature: 0
max_tokens: 8192
---
Nenne alle Werte der Kennzahl aus "parameter", die in dieser Passage stehen, in der Reihenfolge des Plans.
Prüfe vor der Antwort, was die Definition ausschließt.
Nimm nur Text aus "source" und der Überschrift ihres Abschnitts; was nur das Bild einer Abbildung zeigt, ist kein Text.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! Steht kein Wert der Kennzahl in der Passage, antworte {"values":[],"incomplete":false}, sonst in dieser Form:
{{example}}

* "values" nennt jeden Wert einmal. Passen nicht alle Werte in deine Antwort, setze "incomplete" auf true; dann fragen wir nach den übrigen.
* "value" ist, was die Kennzahl nach ihrer Definition fragt, nie eine Angabe zu einem Wert: Das Jahr einer Zahl ist kein Wert. Beim Planungsbüro ist es sein Name.
* Werte des Plans zählen: was er über seine Gemeinde oder etwas darin angibt. Ein Beispiel aus einem anderen Ort, eine Vorgabe aus Gesetz, Förderrichtlinie oder Leitfaden und eine allgemeine Angabe, die für keinen bestimmten Ort gilt, zählen nicht, außer der Plan macht die Vorgabe zu seinem eigenen Ziel.
* Eine Zahl steht mit Punkt als Dezimalzeichen, ohne Tausendertrennzeichen und nicht umgerechnet: Aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8. Mengenwort und Prozentzeichen gehören zur Einheit: "153 Millionen kWh" ist 153, "2,46 TWh" ist 2.46, "51 %" ist 51.
* "value_raw" steht nur, wenn der Plan die Zahl anders schreibt als in "value".
* "quote" kopiert eine zusammenhängende Stelle Zeichen für Zeichen, die im Gezeigten nur einmal steht und den Wert genau einmal enthält: seinen Satz oder in einer Tabelle so viel seiner Zeile, wie es dafür braucht, etwa "410.662,44 | 1.109 | 6%" für 1.109. Zwei Werte dürfen dasselbe Zitat haben, wenn jeder genau einmal darin steht.

<!-- with: title_page -->
"title_page" ist die Zeile des Titelblatts, die die Gemeinde des Plans nennt.

<!-- with: image -->
Zu dieser Abbildung kommt ihr Bild. "drawn" ist true, wo das Bild die Zahl nur zeichnet, als Balken, Tortenstück, Fläche oder Punkt einer Kurve, sonst false. Steht die Zahl in keinem gezeigten Text, lies sie aus dem Bild ab: Statt "quote" sagt "reading", was du abgelesen hast, mit dem Eintrag der Legende, der Kategorie und der Einheit der Achse, bei einem gestapelten Balken mit Unter- und Oberkante, etwa so:
{"value":120,"drawn":true,"reading":"<<Balken, Eintrag der Legende, Kategorie: Oberkante bei 120 auf der Achse in GWh>>"}
Nennt die Beschreibung des Bildes die Zahl, zitiere sie wie jede andere.

<!-- with: around -->
"around" ist der Text des Plans direkt vor und nach der Tabelle oder Abbildung. Auch daraus darfst du einen Wert nehmen.

<!-- with: table_before -->
"table_before" sind Titel und Kopf der Tabelle direkt davor, auf derselben Seite oder der Seite davor: Setzt "source" diese Tabelle fort, ist ihr Kopf auch der Kopf von "source".

<!-- with: read -->
Unter "read" stehen die Werte, die du in dieser Passage schon genannt hast: Nenne alle übrigen.

<!-- follow-up: go_on -->
Deine Antwort war unvollständig. Nenne die übrigen Werte der Kennzahl in dieser Passage, die du noch nicht genannt hast, in derselben Form.

<!-- follow-up: nothing_new -->
Deine letzte Antwort enthielt keinen Wert, den du nicht schon genannt hattest. Nenne die Werte der Kennzahl in dieser Passage, die noch fehlen, in derselben Form. Fehlt keiner, antworte {"values":[],"incomplete":false}.

<!-- follow-up: remaining -->
Stehen in dieser Passage noch Werte der Kennzahl, die du nicht genannt hast? Nenne sie in derselben Form. Steht keiner mehr darin, antworte {"values":[],"incomplete":false}.

<!-- follow-up: wrong -->
Der Wert unter "wrong" ist kein Wert der Kennzahl; warum, steht unter "what". Nenne die Werte in dieser Passage, die zur Definition passen und die du noch nicht genannt hast, in derselben Form. Steht keiner darin, antworte {"values":[],"incomplete":false}.

<!-- follow-up: corrections -->
Diese Werte deiner letzten Antwort sind nicht übernommen. Warum und was du tun sollst, steht je Wert unter "what". Nenne sie in derselben Form.
