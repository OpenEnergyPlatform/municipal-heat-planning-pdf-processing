---
template: field
without: [rows_source, same_forms, by_similarity, domain_slot_2]
temperature: 0
max_tokens: 6144
---
<!-- part: subject -->
Zahlen, die aus einem deutschen kommunalen Wärmeplan schon geholt sind

<!-- part: example_reply -->
{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2", "R3"], "value": "Bestand", "value_raw": "Ist-Zustand 2022", "quote": "<<Titel der eigenen Tabelle, wörtlich, mit „Ist-Zustand 2022“ darin>>"}], "answers": {"R4": {"value": "Zielszenario", "value_raw": "Klimaschutzszenario", "quote": "<<Satz einer gezeigten Quelle, wörtlich, mit „Klimaschutzszenario“ darin>>"}}}}}

<!-- part: groups_note -->
eine Tabellenüberschrift oder Caption belegt die Angabe für alle Zeilen der Tabelle auf einmal und gehört EINMAL hin.

<!-- part: value_raw_is -->
das Wort des Plans, aus dem du die Antwort hast: Zeilenbeschriftung, Spaltenkopf, Blocküberschrift oder Caption

<!-- part: value_raw_more -->
   Es ist NIE der Name aus "options": die Klassennamen sind oft englisch und stehen in keinem Wärmeplan.
   RICHTIG: "value": "final energy consumption value", "value_raw": "Wärmebedarf", "quote": "<<Titel der eigenen Tabelle, wörtlich, mit „Wärmebedarf“ darin>>"
   FALSCH: "value_raw": "final energy consumption value". Das steht in keiner Quelle, und die Antwort fällt durch.
   "value_raw" steht Zeichen für Zeichen in deinem "quote": dieselbe Beugung, dieselbe Reihenfolge, kein Wort und kein Satzzeichen dazu oder weg. Steht im Zitat "technischem Wärmepotenzial", dann nicht "technisches Wärmepotenzial"; steht dort "Strom- und Wärmeerzeugung", dann nicht "Wärme- und Stromerzeugung"; steht dort "(kt/a)", dann "kt/a" und nicht "in kt/a"; steht dort "Erdgas-Bestand", dann nicht "Erdgas Bestand".

<!-- part: quote_more -->
Es ist die Stelle, an der "value_raw" steht, und oft NICHT die Zeile der Zahl: der Energieträger steht in der Zeilenbeschriftung, Jahr und Größe im Spaltenkopf oder Tabellentitel, das Szenario im Abschnittstitel, das Gebiet in der Caption. Aus Achsentitel, Legende oder Tabellenkopf zitier genau diese Zeile; bei einem Bild die Stelle der Bildbeschreibung, die sie nennt ("<<Satz der Bildbeschreibung, wörtlich, der den Achsentitel nennt>>"), nicht die Bildunterschrift, in der sie fehlt.
   Nennt die Zeile der Zahl die Angabe selbst, ist sie das richtige Zitat; in Kennzahltabellen steht die Größe in jeder Zeile, vorn in der Zeilenbeschriftung: "| <<Größe mit Energieträger und Einheit>> | <<Zahl>> |". Eine Überschrift über Unterzeilen ("Wärmeverbrauch", darunter "davon Heizöl") gilt für jede Unterzeile.
   Im Abschnittstext steht bei jedem Platzhalter der Titel: "[p85_tbl0: <<Titel der Tabelle>>]". Er gehört zu GENAU dieser Tabelle: nur wenn die Quelle unter "source" dieselbe "block_id" trägt, ist es ihr Titel. Der Titel einer fremden Tabelle datiert deine Zahl nicht, benennt ihr Szenario nicht und sagt nichts über ihr Gebiet.
   RICHTIG für das Jahr einer Zahl aus p85_tbl0: "<<Titel hinter „[p85_tbl0:“, wörtlich, mit der Jahreszahl darin>>"
   FALSCH für dieselbe Zahl: "<<Titel hinter „[p91_tbl0:“, auch mit einer Jahreszahl darin>>". Echter Satz, echtes Jahr, andere Tabelle.
   FALSCH: eine Passage, in der deine Antwort nicht vorkommt. Sie belegt nichts, und Antwort und Zitat werden verworfen.
   Was in den Beispielen dieser Anleitung zwischen << und >> steht, beschreibt eine Stelle und ist keine. Es steht in keiner Quelle: schreib es nie ab, auch nicht in "need_more".

<!-- part: domain_rule_1 -->
Tabellen mit mehreren Wertspalten sind der Normalfall; die Zeilen unterscheiden sich dann genau in dem Feld, das die Spalte bestimmt. "column": 2 heißt: es gilt, was die ZWEITE Kopfzelle benennt, von links gezählt, die erste ist 1. Zähl nicht selbst nach. Die Kopfzeile ist die der EIGENEN Tabelle (Quelle unter "source"); drei Tabellentitel hintereinander im Abschnittstext sind keine Kopfzeile.
   Die Spalte bestimmt nicht immer das Jahr: "| Energieträger | <<Jahr>> | <<Jahr>> | <<Jahr>> |" bestimmt das JAHR, drei Zahlen einer Zeile haben drei Jahre. "| Energieträger | <<Sektor 1>> Endenergie in kWh/a | <<Sektor 2>> Endenergie in kWh/a | <<Sektor 3>> Endenergie in kWh/a |" bestimmt den SEKTOR, und die Zahl mit "column": 2 gehört zu <<Sektor 1>>. Gib so viele Gruppen aus, wie die Spalten unterscheiden.

<!-- part: closed_out_text -->
Enthält "options" Einträge, die ausdrücklich das Gegenteil einer Klasse sind (Summenzeile, Restposition, ausdrücklich unbekannter Wert, Prozentanteil, Potenzial), sind das richtige Antworten und keine Notlösung. Wähle sie. Regel {{rule:quote}} gilt auch für sie: dein "quote" trägt das Wort, das "value_raw" nennt ("Gesamt", "Summe", "insgesamt", "Erzeugung", "Potenzial"). Steht kein solches Wort in den Quellen und ist die Eigenschaft nur aus dem Zusammenhang zu erschließen, antworte "{{unstated}}", statt eine Stelle zu zitieren, die die Angabe nicht trägt. Passt fachlich weder eine Klasse noch einer dieser Einträge, obwohl die Passage die Angabe nennt, gib die Bezeichnung in "value_raw" und lass "value" weg.

<!-- part: need_more_example -->
RICHTIG: ein ganzer Satz mit dem Wort des Plans für die gesuchte Angabe, wie er im Plan stehen würde. FALSCH: "Bezugsjahr", zu kurz, findet alles und nichts.

<!-- part: base_years_rule -->
   Trägt Spalte, Zeile oder Überschrift einer Zahl statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell"), steht ihr Jahr meist EINMAL an anderer Stelle im Plan. Steht "base_years" im Eingabe-Objekt, wähl daraus das Jahr, auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort für deine Zahl steht. Das Wort belegt dein Zitat, die Jahreszahl belegt das Zitat aus "base_years".
   RICHTIG, mit "base_years": [{"year": 2022, "quote": "<<Satz des Plans, der das Jahr seines Bestands druckt>>"}]: "value": 2022, "value_raw": "Basisjahr", "quote": "<<Stelle einer gezeigten Quelle, wörtlich, an der „Basisjahr“ bei deiner Zahl steht>>"
   Fehlt "base_years" oder passt keins seiner Jahre, und steht das Jahr auch nicht in den Passagen, antworte "{{unstated}}" und such mit "need_more" nach dem Satz, der das Jahr des Bestands nennt. Rate das Jahr nicht aus dem Erscheinungsjahr des Plans.

<!-- part: target_years_rule -->
   Dasselbe gilt für das Wort des Plans für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), wenn es statt einer Jahreszahl dasteht. Steht "target_years" im Eingabe-Objekt, wähl daraus das Jahr, auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort für deine Zahl steht. Nennt "target_years" mehrere Jahre, ist das Zieljahr das, das der Plan selbst so nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel und kein Stützjahr. Lässt sich das nicht entscheiden, antworte "{{unstated}}".
   RICHTIG, mit "target_years": [{"year": 2045, "quote": "<<Satz des Plans, der sein Zieljahr druckt>>"}]: "value": 2045, "value_raw": "Zieljahr", "quote": "<<Stelle einer gezeigten Quelle, wörtlich, an der „Zieljahr“ bei deiner Zahl steht>>"
   Fehlt "target_years" oder passt keins seiner Jahre, und steht das Jahr auch nicht in den Passagen, antworte "{{unstated}}" und such mit "need_more" nach dem Satz, der das Zieljahr nennt.
