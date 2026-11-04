---
temperature: 0
max_tokens: 8192
---
Du liest EINE Passage aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") und nennst jeden Wert EINER Kennzahl, der in ihr steht. Nach den Angaben zu den Werten, etwa Einheit, Jahr oder Energieträger, fragen spätere Anfragen.

Du bekommst:
- "source": die Passage, "text" eines Abschnitts oder einer Tabelle oder die Beschreibung einer Abbildung (zu einer Abbildung kommt ihr Bild), und der Abschnitt, in dem sie steht.
- "around", nur bei einer Tabelle oder Abbildung: der Text ihres Abschnitts um sie. Sie steht darin als Platzhalter in eckigen Klammern.
- "parameter": die Kennzahl mit ihrer Definition.
- "corrections", nur bei einer zweiten Anfrage: die Werte deiner ersten Antwort, die die Prüfung abgelehnt hat, je mit "row", "value", "quote" und dem Grund ("what").

Für jeden Wert ein Eintrag in "values":
- "value": der Wert, wie die Passage ihn druckt; beim Planungsbüro sein Name. Eine Zahl schreibst du mit Punkt als Dezimalzeichen und ohne Tausenderpunkte: aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8. Du rechnest nichts um. Ein Mengenwort und das Prozentzeichen gehören zur Einheit, nicht in die Zahl: "153 Millionen kWh" ist 153, "2,46 TWh" ist 2.46, "51 %" ist 51. Der Wert ist immer, was die Kennzahl nach ihrer Definition fragt, nie die Antwort einer Angabe: Das Jahr einer Zahl ist eine Angabe zu ihr und kein Wert, auch wenn es eine Zahl ist.
- "value_raw": nur wenn die Passage die Zahl anders schreibt als in "value".
- "quote": EINE zusammenhängende Stelle aus "text", Zeichen für Zeichen abgeschrieben, die den Wert enthält: sein Satz oder seine Tabellenzeile.

Was nur das Bild einer Abbildung zeigt, ist kein Zitat: zitiert wird aus "text". Nenne jeden Wert einmal.

Bei einer zweiten Anfrage antwortest du nur für die Werte aus "corrections": je ein Eintrag mit ihrer "row", die genannten Punkte behoben.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"values": [{"value": 12.5, "quote": "<<Satz mit der Zahl>>"}]}
