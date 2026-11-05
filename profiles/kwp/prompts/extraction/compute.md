---
temperature: 0
max_tokens: 2048
---
Berechne die Zahl aus `wanted`, die der Plan nicht druckt, die aber aus gedruckten, schon gelesenen Zahlen folgt, oder stelle fest, dass es nichts zu rechnen gibt; das ist dann die richtige Antwort. Gerechnet wird nur im Code, nie im Kopf.
Antworte immer mit genau einem JSON-Objekt ohne Text davor oder danach, je nach Schritt (unten): nachsehen, übernehmen, rechnen oder das Ergebnis.

Anteil (`"kind":"share"`): `share` ist die id eines Anteils in Prozent, `whole` der Wortlaut, wovon er ein Anteil ist. Gesucht ist Ganzes mal Anteil durch 100.
* Das Ganze ist die Größe, von der der Anteil spricht, in derselben Abgrenzung, im selben Jahr, Szenario und Gebiet. Es entscheidet die Bedeutung, nicht das Wort: "Wärmeverbrauch" und "Wärmebedarf" können dasselbe Ganze sein; der Endenergieverbrauch aller Anwendungen und die Endenergie nur für Wärme sind es nicht. Ebenso wenig gehört ein Anteil an der Erzeugung der Fernwärme zum Wärmeverbrauch der Stadt, ein Anteil an einem Teilgebiet zum ganzen Gebiet, ein Anteil an Emissionen zu einer Energiemenge oder ein Anteil an der Zahl der Gebäude zu Kilowattstunden.
* Ist eine der übrigen Zahlen in `numbers` das Ganze, rechne mit ihr. Sonst sieh im Plan nach und übernimm das Ganze aus einer gezeigten Passage; dann steht es unter `numbers`. Gibt es das Ganze nicht, gibt es nichts zu rechnen.

Summe (`"kind":"sum"`): Gesucht ist die Summe der Zahlen über die Achse `over`, für die der Plan keine Summe druckt.
* Dieselbe Angabe zählt einmal, auch wenn sie in zwei Passagen oder in anderen Worten steht. Eine Zahl, die eine andere der Liste schon enthält, zählt nicht neben ihr, etwa "Biomasse" neben "Holz".
* Schließen sich Zahlen aus, etwa Varianten oder Alternativen derselben Anlage, gibt es keine Summe. Fehlt ein Teil in `numbers`, etwa weil eine Passage nur die größten Teile nennt, gibt es nichts zu rechnen, auch wenn er in einer Tabelle steht.

Die Schritte:
* Nachsehen: `{"more":[...]}`. Du bekommst dieselbe Frage noch einmal, das Nachgeforderte unter `more` (je mit `id` M1, M2, …), Trefferlisten unter `hits` (je Treffer `id`, Art, Titel und erste Zeile) und unter `not_found`, was sich nicht holen ließ: "end" (in diese Richtung kein Abschnitt mehr), "unknown" (kein oder mehr als ein Platzhalter oder Treffer dieses Namens), "invalid_pattern" oder "timeout".
  - `{"get":"next"}` oder `{"get":"previous"}`: der Abschnitt nach oder vor der Passage des Anteils oder der ersten Zahl, beim nächsten Mal der danach oder davor;
  - `{"get":"item","id":"..."}`: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern im Text steht;
  - `{"get":"search","pattern":"..."}`: Treffer für einen regulären Ausdruck, ohne Unterschied von Groß- und Kleinschreibung;
  - `{"get":"similar","text":"..."}`: Treffer zu einem Satz, wie der Plan die gesuchte Angabe drucken würde; er darf erdacht sein;
  - `{"get":"hit","id":"..."}`: die Passage eines Treffers.
* Übernehmen: `{"take":{"parameter":"...","value":123.4,"unit":"...","quantity":"...","quantity_raw":"...","quote":"..."}}` mit Einträgen aus `wanted.take`: dem Parameter, einer seiner Einheiten und einem Schlüssel seiner Liste `quantity`. `value` ist die Zahl, wie das Zitat sie druckt, `quantity_raw` das Wort des Plans für die Größe und `quote` die Stelle aus der gezeigten Passage mit der Zahl darin, Zeichen für Zeichen.
* Rechnen: `{"action":"python","code":"..."}`. Bereit stehen `numbers` ("N1", "N2", … auf {"value", "unit"}), `sources` ("Q1", "M1", … auf den Text), `tables` (Liste aus {"caption", "markdown"}, die Tabellen unter den Passagen), numpy und pandas. Rechne mit `numbers`, schreib keine Zahlen ab und gib genau das Ergebnis aus, mit `print(round(ergebnis, 3))`.
* Ergebnis, nach der Ausgabe: `{"value":123.456,"used":["N1","N3"],"quote":"..."}`. `value` ist die ausgegebene Zahl, Zeichen für Zeichen. `used` nennt die Zahlen, mit denen du gerechnet hast: Aus ihnen wird das Ergebnis als Anteil mal Ganzes durch 100 oder als ihre Summe nachgerechnet, und eine Zahl, die nicht aus ihnen folgt, wird verworfen. `quote` steht nur bei einem Anteil: die Stelle aus der Passage des Ganzen, Zeichen für Zeichen, die sagt, was dieses Ganze ist. Die Einheit ist die des Ganzen oder der Zahlen in `numbers`.
* Nichts zu rechnen: `{"value":null,"used":[]}`.
