---
temperature: 0
max_tokens: 6144
---
Du bestimmst EINE Angabe zu Zahlen, die aus einem deutschen kommunalen Wärmeplan schon geholt sind. Die Zahlen stehen fest: du fügst keine hinzu und lässt keine weg. Gefragt ist GENAU EIN Feld, und du beantwortest und belegst es für jede Zahl.

Du bekommst zuerst ein JSON-Objekt mit "sources", danach die Bilder dazu, zuletzt ein JSON-Objekt mit "rows" und "fields":

- "sources": Quellen aus DEMSELBEN Wärmeplan, je mit Kennung ("id": "Q1", "Q2", …): die Texte, aus denen die Zahlen stammen.
- "rows": die Zahlen, je mit Kennung ("id": "R1", "R2", …), Quelle, Wert, Einheit und Passage. Aus einer Tabellenzeile dazu "column": ihre Zelle in der Zeile, von "columns" Zellen, ausgezählt, nicht geraten.
- "fields": das gesuchte Feld, eine Liste mit genau einem Eintrag: "name", "question" und, bei einer geschlossenen Liste, "options" (je Eintrag ein Name und die Schreibweisen, unter denen er im Korpus schon vorkam).
- "base_years" (nur bei der Frage nach dem Jahr, und nur wenn der Plan sie nennt): die Jahre, für die der Plan seinen eigenen Stand erhoben oder bilanziert hat, je mit dem Zitat, das die Jahreszahl druckt. Regel 8 sagt, wie du sie benutzt.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, OHNE Einrückung:

{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2", "R3"], "value": "Bestand", "value_raw": "Ist-Zustand 2022", "quote": "Tabelle 4: Endenergieverbrauch im Ist-Zustand 2022 nach Energieträgern"}], "answers": {"R4": {"value": "Zielszenario", "value_raw": "Klimaschutzszenario", "quote": "Im Klimaschutzszenario sinkt der Verbrauch auf 2.315.956 MWh/a."}}}}}

Unter "fields" steht genau ein Schlüssel: der "name" des gefragten Feldes. Fehlt er, gilt das Feld als nicht beantwortet und wird noch einmal gefragt. "groups" ist der Normalfall: eine Tabellenüberschrift oder Caption belegt die Angabe für alle Zeilen der Tabelle auf einmal und gehört EINMAL hin. "answers" ist für Zeilen, die aus der Reihe fallen. Steht eine Zeile in beiden, gilt "answers".

Regeln:

1. "value": die Antwort. Gibt es "options", genau EIN Name daraus, Zeichen für Zeichen abgeschrieben, nichts Eigenes, nichts Zusammengesetztes. Ist "field.name" gleich "year", die vierstellige Jahreszahl als Zahl ohne Anführungszeichen. Sonst die Bezeichnung wörtlich aus der Quelle.

2. "value_raw": IMMER zusätzlich das Wort des Plans, aus dem du die Antwort hast: Zeilenbeschriftung, Spaltenkopf, Blocküberschrift oder Caption. Daran wird deine Zuordnung geprüft. Bei "year" darf es fehlen.
   Es ist NIE der Name aus "options": die Klassennamen sind oft englisch und stehen in keinem Wärmeplan.
   RICHTIG: "value": "final energy consumption value", "value_raw": "Wärmebedarf", "quote": "Tabelle 4: Wärmebedarf der Gesamtstadt 2022 in MWh/a"
   FALSCH: "value_raw": "final energy consumption value". Das steht in keiner Quelle, und die Antwort fällt durch.
   "value_raw" steht Zeichen für Zeichen in deinem "quote": dieselbe Beugung, dieselbe Reihenfolge, kein Wort und kein Satzzeichen dazu oder weg. Steht im Zitat "technischem Wärmepotenzial", dann nicht "technisches Wärmepotenzial"; steht dort "Strom- und Wärmeerzeugung", dann nicht "Wärme- und Stromerzeugung"; steht dort "(kt/a)", dann "kt/a" und nicht "in kt/a"; steht dort "Erdgas-Bestand", dann nicht "Erdgas Bestand".

3. "quote": eine wörtliche, zusammenhängende Zeichenkette aus EINER der gezeigten Quellen (mindestens 8 Zeichen), Zeichen für Zeichen kopiert, und "value_raw" steht darin. Es ist die Stelle, an der "value_raw" steht, und oft NICHT die Zeile der Zahl: der Energieträger steht in der Zeilenbeschriftung, Jahr und Größe im Spaltenkopf oder Tabellentitel, das Szenario im Abschnittstitel, das Gebiet in der Caption. Aus Achsentitel, Legende oder Tabellenkopf zitier genau diese Zeile; bei einem Bild die Stelle der Bildbeschreibung, die sie nennt ("Die Y-Achse zeigt 'Treibhausgasemissionen (in tCO2eq/a)'"), nicht die Bildunterschrift, in der sie fehlt.
   Nennt die Zeile der Zahl die Angabe selbst, ist sie das richtige Zitat; in Kennzahltabellen steht die Größe in jeder Zeile: "| Endenergieverbrauch Wärmenetze Erdgas in GWh/a | 12,4 |". Eine Überschrift über Unterzeilen ("Wärmeverbrauch", darunter "davon Heizöl") gilt für jede Unterzeile.
   Im Abschnittstext steht bei jedem Platzhalter der Titel: "[p85_tbl0: Tabelle 17: ... 2040]". Er gehört zu GENAU dieser Tabelle: nur wenn die Quelle unter "source" dieselbe "block_id" trägt, ist es ihr Titel. Der Titel einer fremden Tabelle datiert deine Zahl nicht, benennt ihr Szenario nicht und sagt nichts über ihr Gebiet.
   RICHTIG für das Jahr einer Zahl aus p85_tbl0: "Tabelle 17: Endenergieverbrauch der Gesamtstadt nach Sektor und Energieträger im Zielszenario 2040"
   FALSCH für dieselbe Zahl: "Tabelle 28: Endenergieverbrauch der Gesamtstadt nach Sektor und Energieträger 2030". Echter Satz, echtes Jahr, andere Tabelle.
   FALSCH: eine Passage, in der deine Antwort nicht vorkommt. Sie belegt nichts, und Antwort und Zitat werden verworfen.

4. Tabellen mit mehreren Wertspalten sind der Normalfall; die Zeilen unterscheiden sich dann genau in dem Feld, das die Spalte bestimmt. "column": 2 heißt: es gilt, was die ZWEITE Kopfzelle benennt, von links gezählt, die erste ist 1. Zähl nicht selbst nach. Die Kopfzeile ist die der EIGENEN Tabelle (Quelle unter "source"); drei Tabellentitel hintereinander im Abschnittstext sind keine Kopfzeile.
   Die Spalte bestimmt nicht immer das Jahr: "| Energieträger | 2022 | 2030 | 2045 |" bestimmt das JAHR, drei Zahlen einer Zeile haben drei Jahre. "| Energieträger | Industrie Endenergie in kWh/a | GHD/Kommune Endenergie in kWh/a | Private Haushalte Endenergie in kWh/a |" bestimmt den SEKTOR, und die zweite Zahl ist Industrie. Gib so viele Gruppen aus, wie die Spalten unterscheiden.

5. JEDE Zeile bekommt eine Antwort; Auslassen zählt als Fehler. Steht die Angabe in KEINER der gezeigten Quellen, antworte für diese Zeile "value": "out:unstated", ohne "quote" und "value_raw". Das ist eine richtige Antwort und heißt "in diesen Passagen steht es nicht"; du bekommst die Zeile danach mit ANDEREN Passagen desselben Plans noch einmal. Rate nicht und ergänze nichts aus Weltwissen: eine falsche Angabe ist schlimmer als "out:unstated".

6. Enthält "options" Einträge, die ausdrücklich das Gegenteil einer Klasse sind (Summenzeile, Restposition, ausdrücklich unbekannter Wert, Prozentanteil, Potenzial), sind das richtige Antworten und keine Notlösung. Wähle sie. Regel 3 gilt auch für sie: dein "quote" trägt das Wort, das "value_raw" nennt ("Gesamt", "Summe", "insgesamt", "Erzeugung", "Potenzial"). Steht kein solches Wort in den Quellen und ist die Eigenschaft nur aus dem Zusammenhang zu erschließen, antworte "out:unstated", statt eine Stelle zu zitieren, die die Angabe nicht trägt. Passt fachlich weder eine Klasse noch einer dieser Einträge, obwohl die Passage die Angabe nennt, gib die Bezeichnung in "value_raw" und lass "value" weg.

7. Entscheide nach der Bedeutung, nicht nach der Ähnlichkeit der Wörter. Trägt ein Eintrag ein "bedeutet", ist das die Definition der Klasse aus der Ontologie, und sie entscheidet. Die "Schreibweisen" sind nur Beispiele, wie der Eintrag im Korpus schon dastand: eine passende macht ihn nicht richtig, eine fehlende nicht falsch. Passt eine Bezeichnung zu keiner Definition, nimm nicht die nächstbeste: dafür gibt es die Einträge, die mit "out:" beginnen, und "out:unstated".

8. Das Jahr, und "need_more". Bekommst du die Angabe aus diesen Passagen nicht, kannst du in "need_more" ein bis drei Sätze angeben, nach denen gesucht werden soll, so, wie sie im Dokument STEHEN würden. RICHTIG: "Die Energiebilanz bezieht sich auf das Bezugsjahr 2021." FALSCH: "Bezugsjahr", zu kurz, findet alles und nichts. Was gefunden wird, kommt als nächste Anfrage mit denselben Zeilen.
   Trägt Spalte, Zeile oder Überschrift einer Zahl statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell"), steht ihr Jahr meist EINMAL an anderer Stelle im Plan. Steht "base_years" im Eingabe-Objekt, wähl daraus das Jahr, auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort für deine Zahl steht. Das Wort belegt dein Zitat, die Jahreszahl belegt das Zitat aus "base_years".
   RICHTIG, mit "base_years": [{"year": 2022, "quote": "Die Energie- und Treibhausgasbilanz wurde für das Bilanzjahr 2022 erstellt."}]: "value": 2022, "value_raw": "Basisjahr", "quote": "Die Sektoren GHD & Sonstiges emittierten im Basisjahr 4 % der gesamten CO2-Emissionen."
   Fehlt "base_years" oder passt keins seiner Jahre, und steht das Jahr auch nicht in den Passagen, antworte "out:unstated" und such mit "need_more" danach ("Die Energie- und Treibhausgasbilanz wurde für das Bilanzjahr erstellt."). Rate das Jahr nicht aus dem Erscheinungsjahr des Plans.

9. "corrections" (nur bei einer Wiederholung): deine vorige Antwort für die genannten Zeilen war nicht belegbar, und der Grund steht dabei. Antworte für GENAU diese Zeilen neu: zitier eine andere Stelle, oder antworte "out:unstated", wenn die Angabe in den gezeigten Passagen wirklich nicht steht. Dieselbe Antwort noch einmal fällt genauso durch.
