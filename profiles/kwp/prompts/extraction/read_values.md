---
temperature: 0
max_tokens: 8192
---
Du liest EINE Passage aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") und nennst den nächsten Wert EINER Kennzahl, den du noch nicht genannt hast. Nach den Angaben zu dem Wert, etwa Einheit, Jahr oder Energieträger, fragen spätere Anfragen.

Du bekommst:
- "parameter": die Kennzahl mit ihrer Definition.
- "source": die Passage, "text" eines Abschnitts, einer ganzen Tabelle mit Titel, Kopf und allen Zeilen oder die Beschreibung einer Abbildung (zu einer Abbildung kommt ihr Bild), und der Abschnitt, in dem sie steht.
- "around", nur bei einer Tabelle oder Abbildung: der Text ihres Abschnitts direkt vor und nach ihr. Sie steht darin als Platzhalter in eckigen Klammern.
- "read": die Werte, die du schon genannt hast, je mit "value", "quote" und, bei einer Zahl in einer Tabelle, "head".
- "corrections", nur bei einer zweiten Anfrage: der Wert deiner ersten Antwort, den die Prüfung abgelehnt hat, mit dem Grund ("what").

Unter "next" nennst du EINEN Wert der Kennzahl, der nicht unter "read" steht, in der Reihenfolge, in der der Plan seine Werte druckt. Er darf in "text", in der Überschrift unter "section" oder in "around" stehen. Steht kein weiterer Wert der Kennzahl darin, ist "next" null.
- "value": der Wert, wie der Plan ihn druckt; beim Planungsbüro sein Name. Eine Zahl schreibst du mit Punkt als Dezimalzeichen und ohne Tausenderpunkte: aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8. Du rechnest nichts um. Ein Mengenwort und das Prozentzeichen gehören zur Einheit, nicht in die Zahl: "153 Millionen kWh" ist 153, "2,46 TWh" ist 2.46, "51 %" ist 51. Der Wert ist immer, was die Kennzahl nach ihrer Definition fragt, nie die Antwort einer Angabe: Das Jahr einer Zahl ist eine Angabe zu ihr und kein Wert, auch wenn es eine Zahl ist.
- "value_raw": nur wenn der Plan die Zahl anders schreibt als in "value".
- "quote": EINE zusammenhängende Stelle, Zeichen für Zeichen abgeschrieben, die den Wert enthält: sein Satz oder, in einer Tabelle, genau seine eine Zeile.
- "head", nur bei einer Zahl in einer Tabelle: der Kopf ihrer Spalte, Zeichen für Zeichen, wie er in der Kopfzeile steht. Druckt eine Zeile dieselbe Zahl in zwei Spalten, sind das zwei Werte mit verschiedenem "head".

Zitiert wird aus Text, der dir gezeigt wurde: aus der Passage und der Überschrift ihres Abschnitts, also auch aus den Zeilen einer Tabelle oder der Beschreibung einer Abbildung, oder aus dem Text um sie. Was nur das Bild zeigt und die Beschreibung nicht, ist kein Zitat. Ein Wert, der unter "read" steht, ist genannt: Nenne ihn nicht noch einmal.

Bei einer zweiten Anfrage nennst du den Wert aus "corrections" noch einmal, den genannten Punkt behoben. Ist er kein Wert der Kennzahl, nennst du stattdessen den nächsten Wert, der nicht unter "read" steht, oder null, wenn keiner mehr kommt.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"next": {"value": 12.5, "quote": "<<die eine Tabellenzeile mit der Zahl>>", "head": "<<Kopf der Spalte der Zahl>>"}}
