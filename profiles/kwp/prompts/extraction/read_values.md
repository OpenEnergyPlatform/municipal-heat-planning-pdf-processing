---
temperature: 0
max_tokens: 8192
---
Du liest EINE Passage aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") und nennst den nächsten Wert EINER Kennzahl, den du noch nicht genannt hast. Nach den Angaben zu dem Wert, etwa Einheit, Jahr oder Energieträger, fragen spätere Anfragen.

Du bekommst:
- "source": die Passage, "text" eines Abschnitts, einer ganzen Tabelle mit Titel, Kopf und allen Zeilen oder die Beschreibung einer Abbildung (zu einer Abbildung kommt ihr Bild), und der Abschnitt, in dem sie steht.
- "around", nur bei einer Tabelle oder Abbildung: der Text ihres Abschnitts um sie. Sie steht darin als Platzhalter in eckigen Klammern.
- "parameter": die Kennzahl mit ihrer Definition.
- "read": die Werte, die du schon genannt hast, je mit "value", "quote" und, bei einer Zahl in einer Tabelle, "head".
- "more", "hits" und "not_found", nur nachdem du nachgefordert hast (siehe unten). "hits" kann schon in der ersten Anfrage stehen: die Passagen, die eine Suche im ganzen Plan nach dieser Kennzahl gleich nach dieser gefunden hat.
- "corrections", nur bei einer zweiten Anfrage: der Wert deiner ersten Antwort, den die Prüfung abgelehnt hat, mit dem Grund ("what").

Unter "next" nennst du EINEN Wert der Kennzahl, der nicht unter "read" steht, in der Reihenfolge, in der der Plan seine Werte druckt. Er darf in "text", in der Überschrift unter "section", in "around" oder in einer Passage unter "more" stehen. Steht kein weiterer Wert der Kennzahl darin, ist "next" null.
- "value": der Wert, wie der Plan ihn druckt; beim Planungsbüro sein Name. Eine Zahl schreibst du mit Punkt als Dezimalzeichen und ohne Tausenderpunkte: aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8. Du rechnest nichts um. Ein Mengenwort und das Prozentzeichen gehören zur Einheit, nicht in die Zahl: "153 Millionen kWh" ist 153, "2,46 TWh" ist 2.46, "51 %" ist 51. Der Wert ist immer, was die Kennzahl nach ihrer Definition fragt, nie die Antwort einer Angabe: Das Jahr einer Zahl ist eine Angabe zu ihr und kein Wert, auch wenn es eine Zahl ist.
- "value_raw": nur wenn der Plan die Zahl anders schreibt als in "value".
- "quote": EINE zusammenhängende Stelle, Zeichen für Zeichen abgeschrieben, die den Wert enthält: sein Satz oder, in einer Tabelle, genau seine eine Zeile.
- "head", nur bei einer Zahl in einer Tabelle: der Kopf ihrer Spalte, Zeichen für Zeichen, wie er in der Kopfzeile steht. Druckt eine Zeile dieselbe Zahl in zwei Spalten, sind das zwei Werte mit verschiedenem "head".

Zitiert wird aus Text, der dir gezeigt wurde: aus der Passage und der Überschrift ihres Abschnitts, also auch aus den Zeilen einer Tabelle oder der Beschreibung einer Abbildung, aus dem Text um sie oder aus einer nachgeforderten Passage. Was nur das Bild zeigt und die Beschreibung nicht, ist kein Zitat. Ein Wert, der unter "read" steht, ist genannt: Nenne ihn nicht noch einmal.

Brauchst du, um die Werte zu erkennen, etwas, das weder in der Passage noch in ihrer Überschrift noch in "around" steht, etwa die Köpfe einer Tabelle, die auf der Vorseite beginnt, darfst du unter "more" nachfordern: {"get": "next"} oder {"get": "previous"} (den nächsten oder den vorigen Abschnitt), {"get": "item", "id": "<<Platzhalter>>"} (die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern im Text steht), {"get": "search", "pattern": "<<regulärer Ausdruck>>"} (eine Trefferliste der Passagen, deren Text das Muster enthält, ohne Unterschied von Groß- und Kleinschreibung, je mit "id", Titel und passender Zeile), {"get": "similar", "text": "<<Satz, wie der Plan es drucken würde>>"} (eine Trefferliste der Passagen, die diesem Satz am nächsten sind, je mit "id", Titel und erster Zeile) oder {"get": "hit", "id": "<<id eines Treffers>>"} (die Passage dieses Treffers). Du bekommst dann dieselbe Frage noch einmal, das Nachgeforderte unter "more" und "hits" und unter "not_found", was sich nicht finden ließ, mit Grund. Gib auch beim Nachfordern deine ganze Antwort; ohne neue Anfrage in "more" gilt sie.

Bei einer zweiten Anfrage nennst du den Wert aus "corrections" noch einmal, den genannten Punkt behoben. Ist er kein Wert der Kennzahl, nennst du stattdessen den nächsten Wert, der nicht unter "read" steht, oder null, wenn keiner mehr kommt.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"next": {"value": 12.5, "quote": "<<die eine Tabellenzeile mit der Zahl>>", "head": "<<Kopf der Spalte der Zahl>>"}}
