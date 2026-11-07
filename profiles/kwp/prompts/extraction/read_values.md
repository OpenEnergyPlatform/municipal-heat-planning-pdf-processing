---
temperature: 0
max_tokens: 8192
---
Nenne den ersten Wert der Kennzahl aus "parameter", der in der Reihenfolge des Plans in dieser Passage steht.
Prüfe vor der Antwort, was die Definition ausschließt.
Nimm nur Text aus "source" und der Überschrift ihres Abschnitts; was nur das Bild einer Abbildung zeigt, ist kein Text.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! Steht kein Wert der Kennzahl in der Passage, antworte {"value":null}, sonst in dieser Form:
{{example}}

* "value" ist, was die Kennzahl nach ihrer Definition fragt, nie eine Angabe zu einem Wert: Das Jahr einer Zahl ist kein Wert. Beim Planungsbüro ist es sein Name.
* Werte des Plans zählen: was er über seine Gemeinde oder etwas darin angibt. Ein Beispiel aus einem anderen Ort, eine Vorgabe aus Gesetz, Förderrichtlinie oder Leitfaden und eine allgemeine Angabe, die für keinen bestimmten Ort gilt, zählen nicht, außer der Plan macht die Vorgabe zu seinem eigenen Ziel.
* Eine Zahl steht mit Punkt als Dezimalzeichen, ohne Tausendertrennzeichen und nicht umgerechnet: Aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8. Mengenwort und Prozentzeichen gehören zur Einheit: "153 Millionen kWh" ist 153, "2,46 TWh" ist 2.46, "51 %" ist 51.
* "value_raw" steht nur, wenn der Plan die Zahl anders schreibt als in "value".
* "quote" kopiert eine zusammenhängende Stelle Zeichen für Zeichen, die den Wert enthält: seinen Satz oder, in einer Tabelle, genau seine eine Zeile.
* "head" steht nur bei einer Zahl in einer Tabelle: der Kopf ihrer Spalte, Zeichen für Zeichen. Druckt eine Zeile dieselbe Zahl in zwei Spalten, sind das zwei Werte mit verschiedenem "head".

<!-- with: title_page -->
"title_page" ist die Zeile des Titelblatts, die die Gemeinde des Plans nennt.

<!-- with: around -->
"around" ist der Text des Abschnitts um die Tabelle oder Abbildung. Auch daraus darfst du einen Wert nehmen.

<!-- with: table_before -->
"table_before" sind Titel und Kopf der Tabelle direkt davor, auf derselben Seite oder der Seite davor: Setzt "source" diese Tabelle fort, ist ihr Kopf auch der Kopf von "source".

<!-- with: read -->
Unter "read" stehen die Werte, die du in dieser Passage schon genannt hast: Nenne den ersten, der nicht darunter steht.

<!-- follow-up: next -->
Nenne den nächsten Wert der Kennzahl in dieser Passage, den du noch nicht genannt hast, in derselben Form. Steht keiner mehr darin, antworte {"value":null}.

<!-- follow-up: corrections -->
Dein letzter Wert ist nicht übernommen. Warum und was du tun sollst, steht unter "what".
