---
temperature: 0
max_tokens: 8192
---
Nenne den ersten Wert der Kennzahl aus `parameter`, der in der Reihenfolge des Plans in dieser Passage steht und noch nicht unter `read` steht. Nenne einen Wert je Anfrage.
Nimm nur Text aus `source`, der Überschrift ihres Abschnitts oder `around`; was nur das Bild einer Abbildung zeigt, ist kein Text. Gibt es `corrections`, nenne den abgelehnten Wert noch einmal und behebe den Punkt aus `what`; ist er kein Wert der Kennzahl, nenne stattdessen den nächsten Wert, der nicht unter `read` steht.
Antworte mit genau einer Zeile JSON. Steht kein weiterer Wert der Kennzahl in der Passage, antworte `{"next":null}`, sonst:
`{"next":{"value":12.5,"quote":"...","head":"..."}}`

* `value` ist, was die Kennzahl nach ihrer Definition fragt, nie eine Angabe zu einem Wert: Das Jahr einer Zahl ist kein Wert. Beim Planungsbüro ist es sein Name.
* Eine Zahl steht mit Punkt als Dezimalzeichen, ohne Tausendertrennzeichen und nicht umgerechnet: Aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8. Mengenwort und Prozentzeichen gehören zur Einheit: "153 Millionen kWh" ist 153, "2,46 TWh" ist 2.46, "51 %" ist 51.
* `value_raw` steht nur, wenn der Plan die Zahl anders schreibt als in `value`.
* `quote` kopiert eine zusammenhängende Stelle Zeichen für Zeichen, die den Wert enthält: seinen Satz oder, in einer Tabelle, genau seine eine Zeile.
* `head` steht nur bei einer Zahl in einer Tabelle: der Kopf ihrer Spalte, Zeichen für Zeichen. Druckt eine Zeile dieselbe Zahl in zwei Spalten, sind das zwei Werte mit verschiedenem `head`.
