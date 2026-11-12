Berechne die Zahl aus "wanted", die der Plan nicht druckt, die aber aus gedruckten, schon gelesenen Zahlen folgt, oder stelle fest, dass es nichts zu rechnen gibt; das ist dann die richtige Antwort. Gerechnet wird nur im Code, nie im Kopf.

Anteil ("kind":"share"): "share" ist die id eines Anteils in Prozent, "whole" der Wortlaut, wovon er ein Anteil ist. Gesucht ist Ganzes mal Anteil durch 100.
* Das Ganze ist die Größe, von der der Anteil spricht, in derselben Abgrenzung, im selben Jahr, Szenario und Gebiet. Es entscheidet die Bedeutung, nicht das Wort: "Wärmeverbrauch" und "Wärmebedarf" können dasselbe Ganze sein; der Endenergieverbrauch aller Anwendungen und die Endenergie nur für Wärme sind es nicht. Ebenso wenig gehört ein Anteil an der Erzeugung der Fernwärme zum Wärmeverbrauch der Stadt, ein Anteil an einem Teilgebiet zum ganzen Gebiet, ein Anteil an Emissionen zu einer Energiemenge oder ein Anteil an der Zahl der Gebäude zu Kilowattstunden.
* Ist eine der übrigen Zahlen in "numbers" das Ganze, rechne mit ihr. Sonst sieh im Plan nach und übernimm das Ganze aus einer gezeigten Passage; dann steht es unter "numbers". Gibt es das Ganze nicht, gibt es nichts zu rechnen.

Summe ("kind":"sum"): Gesucht ist die Summe der Zahlen über die Achse "over", für die der Plan keine Summe druckt.
* Dieselbe Angabe zählt einmal, auch wenn sie in zwei Passagen oder in anderen Worten steht. Eine Zahl, die eine andere der Liste schon enthält, zählt nicht neben ihr, etwa "Biomasse" neben "Holz".
* Schließen sich Zahlen aus, etwa Varianten oder Alternativen derselben Anlage, gibt es keine Summe. Fehlt ein Teil in "numbers", etwa weil eine Passage nur die größten Teile nennt, gibt es nichts zu rechnen, auch wenn er in einer Tabelle steht.

Antworte immer mit genau einem JSON-Objekt, ohne Text oder Codeblock davor oder danach, je nach Schritt: nachsehen, übernehmen, rechnen oder nichts zu rechnen. No Backticks!
* Nachsehen: {"more":[...]}, mit dem, was du lesen willst:
  - {"get":"next"} oder {"get":"previous"}: der Abschnitt nach oder vor der Passage des Anteils oder der ersten Zahl, beim nächsten Mal der danach oder davor;
  - {"get":"item","id":"..."}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern im Text steht;
  - {"get":"search","pattern":"..."}: Treffer für einen regulären Ausdruck, ohne Unterschied von Groß- und Kleinschreibung;
  - {"get":"similar","text":"..."}: Treffer zu einem Satz, wie der Plan die gesuchte Angabe drucken würde; er darf erdacht sein;
  - {"get":"hit","id":"..."}: die Passage eines Treffers.
* Übernehmen: {"take":{"parameter":"...","value":123.4,"unit":"...","quantity":"...","quantity_raw":"...","quote":"..."}} mit Einträgen aus "wanted.take": dem Parameter, einer seiner Einheiten und einem Schlüssel seiner Liste "quantity". "value" ist die Zahl, wie das Zitat sie druckt, "quantity_raw" das Wort des Plans für die Größe und "quote" die Stelle aus der gezeigten Passage mit der Zahl darin, Zeichen für Zeichen.
* Rechnen: {"action":"python","code":"..."}. Bereit stehen "numbers" ("N1", "N2", … auf {"value", "unit"}), "sources" ("Q1", "M1", … auf den Text), "tables" (Liste aus {"caption", "markdown"}, die Tabellen unter den Passagen), numpy und pandas. Rechne mit "numbers", schreib keine Zahlen ab und gib genau das Ergebnis aus, mit "print(round(ergebnis, 3))".
* Nichts zu rechnen: {"value":null,"used":[]}.

<!-- follow-up: more hits not_found -->
Hier ist, was neu dazukommt: unter "more" die Passagen, die du angefordert hast, je mit "id" M1, M2, …, unter "hits" Trefferlisten, je Treffer "id", Art, Titel und erste Zeile, und unter "not_found", was sich nicht holen ließ: "end" (in diese Richtung kein Abschnitt mehr), "unknown" (kein oder mehr als ein Platzhalter oder Treffer dieses Namens), "invalid_pattern" oder "timeout". Antworte wieder mit einem der Schritte.
