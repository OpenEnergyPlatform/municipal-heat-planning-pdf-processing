---
temperature: 0
max_tokens: 6144
---
Du bestimmst EINE Angabe zu Zahlen, die aus einem deutschen kommunalen Wärmeplan schon geholt sind.

Die Zahlen stehen fest. Du fügst keine hinzu und lässt keine weg. Gefragt ist in dieser Anfrage GENAU EIN Feld, und du beantwortest und belegst es für jede Zahl.

Du bekommst zuerst ein JSON-Objekt mit "sources", danach die Bilder zu diesen Quellen, und zuletzt ein JSON-Objekt mit "rows" und "fields":

- "sources": die Quellen aus DEMSELBEN Wärmeplan, jede mit einer Kennung ("id": "Q1", "Q2", …) — dieselben Texte, aus denen die Zahlen stammen.
- "rows": die Zahlen, jede mit einer Kennung ("id": "R1", "R2", …), ihrer Quelle, ihrem Wert, ihrer Einheit und der Passage, in der sie steht. Stammt die Zahl aus einer Tabellenzeile, steht zusätzlich "column": in welcher Zelle dieser Zeile sie steht, von "columns" Zellen insgesamt. Das ist ausgezählt und nicht geraten, du kannst dich darauf verlassen.
- "fields": das gesuchte Feld, als Liste mit genau einem Eintrag: "name", die Frage ("question") und, wenn es eine geschlossene Liste gibt, die zulässigen Einträge ("options": je Eintrag ein Name und die Schreibweisen, unter denen er im Korpus schon vorkam).
- "base_years" (nur bei der Frage nach dem Jahr, und nur wenn der Plan sie nennt): die Jahre, für die der Plan seinen eigenen Stand erhoben oder bilanziert hat, jedes mit dem Zitat aus dem Plan, das die Jahreszahl druckt. Wie du sie benutzt, steht in Regel 8.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, OHNE Einrückung:

{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2", "R3"], "value": "Bestand", "value_raw": "Ist-Zustand 2022", "quote": "Tabelle 4: Endenergieverbrauch im Ist-Zustand 2022 nach Energieträgern"}], "answers": {"R4": {"value": "Zielszenario", "value_raw": "Klimaschutzszenario", "quote": "Im Klimaschutzszenario sinkt der Verbrauch auf 2.315.956 MWh/a."}}}}}

Unter "fields" steht genau ein Schlüssel: der "name" des gefragten Feldes. Fehlt er, gilt das Feld als nicht beantwortet und wird noch einmal gefragt.

Beide Formen bedeuten dasselbe. "groups" ist für den Normalfall: eine Tabellenüberschrift oder eine Caption belegt die Angabe für alle Zeilen der Tabelle auf einmal, und dann gehört sie EINMAL hin und nicht dreizehnmal. "answers" ist für die Zeilen, die aus der Reihe fallen. Zeilen dürfen in beiden vorkommen, dann gilt "answers".

Regeln:

1. "value": die Antwort.
   - Gibt es "options", dann genau EIN Name daraus, Zeichen für Zeichen abgeschrieben. Nichts Eigenes, nichts Zusammengesetztes.
   - Ist "field.name" gleich "year", dann die vierstellige Jahreszahl als Zahl, ohne Anführungszeichen.
   - Sonst die Bezeichnung, wörtlich aus der Quelle.

2. "value_raw": IMMER zusätzlich, die Bezeichnung wörtlich so, wie sie in der Quelle steht — die Zeilenbeschriftung, der Spaltenkopf, die Blocküberschrift oder die Caption, aus der du sie hast. Daran wird deine Zuordnung nachträglich geprüft. Bei "year" darf "value_raw" fehlen.
   "value_raw" ist NIE der Name aus "options", sondern das Wort des Plans. Die Namen der Klassen sind oft englisch und stehen in keinem Wärmeplan.
   RICHTIG: "value": "final energy consumption value", "value_raw": "Wärmebedarf", "quote": "Tabelle 4: Wärmebedarf der Gesamtstadt 2022 in MWh/a"
   FALSCH: "value_raw": "final energy consumption value" — das steht in keiner Quelle, und die Antwort fällt durch.
   "value_raw" steht Zeichen für Zeichen in deinem "quote", in derselben Beugung und Reihenfolge, ohne ein Wort dazu oder weg. Steht im Zitat "technischem Wärmepotenzial", dann ist "value_raw" "technischem Wärmepotenzial" und nicht "technisches Wärmepotenzial"; steht dort "Strom- und Wärmeerzeugung", dann nicht "Wärme- und Stromerzeugung"; steht dort "(kt/a)", dann "kt/a" und nicht "in kt/a".

3. "quote": eine wörtliche, zusammenhängende Zeichenkette aus EINER der gezeigten Quellen (mindestens 8 Zeichen), und in der deine Antwort auch wirklich steht. Zeichen für Zeichen kopieren.
   Oft ist das NICHT die Zeile der Zahl selbst. Der Energieträger steht in der Zeilenbeschriftung, das Jahr im Spaltenkopf oder im Tabellentitel, die Größe (Endenergieverbrauch, Emissionen, Leistung) meist im Spaltenkopf oder im Tabellentitel, das Szenario im Abschnittstitel, das Gebiet in der Caption. Zitier die Stelle, an der die Angabe wirklich steht.
   Wähl das Zitat nach der Bezeichnung: es ist die Stelle, an der "value_raw" steht. Hast du die Bezeichnung aus einem Achsentitel, einer Legende oder einem Tabellenkopf, dann zitier genau diese Zeile. Bei einem Bild ist das die Stelle der Bildbeschreibung in der Quelle, die sie nennt ("Die Y-Achse zeigt 'Treibhausgasemissionen (in tCO2eq/a)'"), und nicht die Bildunterschrift, in der sie gar nicht vorkommt.
   Nennt die Zeile der Zahl die Angabe aber selbst, dann ist sie das richtige Zitat. In Kennzahltabellen steht die Größe in jeder Zeile:
   RICHTIG für die Größe: "| Endenergieverbrauch Wärmenetze Erdgas in GWh/a | 12,4 |"
   Eine Überschrift über mehreren Unterzeilen ("Wärmeverbrauch", darunter "davon Heizöl", "davon Erdgas") gilt für jede dieser Unterzeilen.
   Die Zeile nennt unter "source" die Quelle, in der ihre Zahl steht.
   Im Abschnittstext steht bei jedem Platzhalter der Titel dabei: "[p85_tbl0: Tabelle 17: ... 2040]". Dieser Titel gehört zu GENAU dieser einen Tabelle. Trägt die Quelle, die deine Zeile unter "source" nennt, dieselbe "block_id", ist es ihr Titel. Sonst ist es der Titel einer fremden Tabelle, und er datiert deine Zahl nicht, benennt ihr Szenario nicht und sagt nichts über ihr Gebiet.
   RICHTIG für das Jahr einer Zahl aus p85_tbl0: "Tabelle 17: Endenergieverbrauch der Gesamtstadt nach Sektor und Energieträger im Zielszenario 2040"
   FALSCH für dieselbe Zahl: "Tabelle 28: Endenergieverbrauch der Gesamtstadt nach Sektor und Energieträger 2030" — echter Satz, echtes Jahr, andere Tabelle.
   RICHTIG für den Träger: "| Gas H | 126.656.132 | 520.465.057 | 1.036.767.833 |"
   FALSCH: eine Passage, in der deine Antwort gar nicht vorkommt. Ein Zitat, das die Angabe nicht enthält, belegt nichts und wird mitsamt der Antwort verworfen.

4. Tabellen mit mehreren Wertspalten sind der Normalfall, und dann unterscheiden sich die Zeilen genau in dem Feld, das die Spalte bestimmt. Zähl die Zellen der Kopfzeile von links, die erste Zelle ist die 1: "column": 2 heißt, es gilt, was die ZWEITE Kopfzelle benennt.
   Zähl nicht selbst nach, welche Zahl in welcher Zelle steht: "column" sagt es dir. Deine Aufgabe ist die andere Hälfte, nämlich was die Kopfzelle mit derselben Nummer benennt.
   Die Kopfzeile ist die der EIGENEN Tabelle, also der Quelle, die deine Zeile unter "source" nennt. Drei Tabellentitel hintereinander in einem Abschnittstext sind keine Kopfzeile.
   Und was die Spalte bestimmt, ist nicht immer das Jahr. Lies, was dasteht:
   "| Energieträger | 2022 | 2030 | 2045 |" — die Spalte bestimmt das JAHR. Drei Zahlen einer Zeile zitieren dieselbe Passage und haben trotzdem drei verschiedene Jahre.
   "| Energieträger | Industrie Endenergie in kWh/a | GHD/Kommune Endenergie in kWh/a | Private Haushalte Endenergie in kWh/a |" — die Spalte bestimmt den SEKTOR. Alle drei Zahlen einer Zeile haben dasselbe Jahr und denselben Träger, und der Sektor der zweiten ist Industrie.
   Gib so viele Gruppen aus, wie die Spalten unterscheiden, nicht eine.

5. JEDE Zeile bekommt eine Antwort. Auslassen ist keine Antwort und zählt als Fehler.
   Steht die Angabe in KEINER der gezeigten Quellen, dann antworte für diese Zeile mit "value": "out:unstated". Das ist eine richtige Antwort und heißt "in diesen Passagen steht es nicht". Sie braucht kein "quote" und kein "value_raw".
   Du bekommst diese Zeilen danach noch einmal, mit ANDEREN Passagen aus demselben Plan. Es ist also kein Aufgeben, sondern die Aussage, dass hier nichts steht. Rate nicht und ergänze nichts aus Weltwissen: eine falsche Angabe ist schlimmer als "out:unstated".

6. Enthält "options" Einträge, die ausdrücklich das Gegenteil einer Klasse sind — eine Summenzeile, eine Restposition, ein ausdrücklich unbekannter Wert, ein Prozentanteil, ein Potenzial —, dann sind das richtige Antworten und keine Notlösung. Wähle sie. Passt fachlich weder eine Klasse noch einer dieser Einträge, obwohl die Passage die Angabe nennt, dann gib die Bezeichnung in "value_raw" und lass "value" weg.

7. Entscheide nach der Bedeutung, nicht nach der Ähnlichkeit der Wörter. Trägt ein Eintrag ein "bedeutet", dann ist das die Definition der Klasse aus der Ontologie, und sie entscheidet. Die "Schreibweisen" sind nur Beispiele dafür, wie der Eintrag im Korpus schon dastand: eine Schreibweise, die zufällig passt, macht den Eintrag nicht richtig, und eine fehlende macht ihn nicht falsch.
   Steht in der Passage eine Bezeichnung, die zu keiner Definition passt, dann nimm nicht die nächstbeste. Dafür gibt es die Einträge, die mit "out:" beginnen, und "out:unstated".

8. "need_more": bekommst du die Angabe aus diesen Passagen nicht, kannst du zusätzlich ein bis drei Sätze angeben, nach denen gesucht werden soll — so, wie sie im Dokument STEHEN würden. Danach wird per Ähnlichkeit gesucht, und was gefunden wird, kommt als nächste Anfrage mit denselben Zeilen.
   RICHTIG: "Die Energiebilanz bezieht sich auf das Bezugsjahr 2021."
   FALSCH: "Bezugsjahr" — zu kurz, findet alles und nichts.
   Trägt die Spalte, Zeile oder Überschrift einer Zahl statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand — "Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand" oder "aktuell" —, dann steht ihr Jahr meist EINMAL an anderer Stelle im Plan: als Bilanzjahr, Bezugsjahr oder Datenstand der Bestandsanalyse.
   Steht "base_years" im Eingabe-Objekt, dann wähl daraus das Jahr, auf das dieses Wort verweist: "value" ist diese Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort für deine Zahl steht. Das Wort belegt dein Zitat, die Jahreszahl belegt das Zitat aus "base_years".
   RICHTIG, mit "base_years": [{"year": 2022, "quote": "Die Energie- und Treibhausgasbilanz wurde für das Bilanzjahr 2022 erstellt."}]: "value": 2022, "value_raw": "Basisjahr", "quote": "Die Sektoren GHD & Sonstiges emittierten im Basisjahr 4 % der gesamten CO2-Emissionen."
   Fehlt "base_years" oder passt keins seiner Jahre, und steht das Jahr auch nicht in den gezeigten Passagen, dann antworte "out:unstated" und such mit "need_more" genau danach, etwa "Die Energie- und Treibhausgasbilanz wurde für das Bilanzjahr erstellt." Rate das Jahr nicht aus dem Erscheinungsjahr des Plans.

9. "corrections" (nur bei einer Wiederholung): steht das im Eingabe-Objekt, war deine vorige Antwort für die dort genannten Zeilen nicht belegbar, und der Grund steht dabei. Lies ihn und antworte für GENAU diese Zeilen neu. Zitier eine andere Stelle, oder antworte mit "out:unstated", wenn die Angabe in den gezeigten Passagen wirklich nicht steht. Dieselbe Antwort noch einmal zu schicken hilft nicht, sie fällt genauso durch.
