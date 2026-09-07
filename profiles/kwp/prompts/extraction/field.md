---
temperature: 0
max_tokens: 6144
---
Du bestimmst EINE Angabe zu Zahlen, die aus einem deutschen kommunalen Wärmeplan schon geholt sind.

Die Zahlen stehen fest. Du fügst keine hinzu und lässt keine weg. Gefragt sind in dieser Anfrage EIN ODER MEHRERE Felder, und für jede Zahl beantwortest du JEDES gefragte Feld einzeln und belegst es einzeln. Ein Feld mit dem Beleg eines anderen ist kein Beleg.

Du bekommst ein JSON-Objekt mit diesen Feldern:

- "fields": die gesuchten Felder, je Feld "name", die Frage ("question") und, wenn es eine geschlossene Liste gibt, die zulässigen Einträge ("options": je Eintrag ein Name und die Schreibweisen, unter denen er im Korpus schon vorkam). Jedes Feld hat seine eigene Frage und braucht seine eigene Antwort mit eigenem Zitat.
- "sources": die Quellen aus DEMSELBEN Wärmeplan, jede mit einer Kennung ("id": "Q1", "Q2", …) — dieselben Texte, aus denen die Zahlen stammen.
- "rows": die Zahlen, jede mit einer Kennung ("id": "R1", "R2", …), ihrer Quelle, ihrem Wert, ihrer Einheit und der Passage, in der sie steht. Stammt die Zahl aus einer Tabellenzeile, steht zusätzlich "column": in welcher Zelle dieser Zeile sie steht, von "columns" Zellen insgesamt. Das ist ausgezählt und nicht geraten, du kannst dich darauf verlassen.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, OHNE Einrückung:

{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2", "R3"], "value": "Bestand", "value_raw": "Ist-Zustand 2022", "quote": "Tabelle 4: Endenergieverbrauch im Ist-Zustand 2022 nach Energieträgern"}], "answers": {"R4": {"value": "Zielszenario", "value_raw": "Klimaschutzszenario", "quote": "Im Klimaschutzszenario sinkt der Verbrauch auf 2.315.956 MWh/a."}}}, "year": {"groups": [{"rows": ["R1", "R2", "R3", "R4"], "value": 2022, "quote": "Tabelle 4: Endenergieverbrauch im Ist-Zustand 2022 nach Energieträgern"}]}}}

Ein Schlüssel unter "fields" je gefragtem Feld, genau der "name" aus der Anfrage. Ein Feld, das du wegläßt, gilt als nicht beantwortet und wird noch einmal gefragt — das kostet eine ganze Runde, also lass keines weg.

Innerhalb eines Feldes bedeuten beide Formen dasselbe. "groups" ist für den Normalfall: eine Tabellenüberschrift oder eine Caption belegt die Angabe für alle Zeilen der Tabelle auf einmal, und dann gehört sie EINMAL hin und nicht dreizehnmal. "answers" ist für die Zeilen, die aus der Reihe fallen. Zeilen dürfen in beiden vorkommen, dann gilt "answers".

Regeln:

1. "value": die Antwort.
   - Gibt es "options", dann genau EIN Name daraus, Zeichen für Zeichen abgeschrieben. Nichts Eigenes, nichts Zusammengesetztes.
   - Ist "field.name" gleich "year", dann die vierstellige Jahreszahl als Zahl, ohne Anführungszeichen.
   - Sonst die Bezeichnung, wörtlich aus der Quelle.

2. "value_raw": IMMER zusätzlich, die Bezeichnung wörtlich so, wie sie in der Quelle steht — die Zeilenbeschriftung, der Spaltenkopf, die Blocküberschrift oder die Caption, aus der du sie hast. Daran wird deine Zuordnung nachträglich geprüft. Bei "year" darf "value_raw" fehlen.

3. "quote": eine wörtliche, zusammenhängende Zeichenkette aus EINER der gezeigten Quellen (mindestens 8 Zeichen), und in der deine Antwort auch wirklich steht. Zeichen für Zeichen kopieren.
   Das ist FAST NIE die Zeile der Zahl selbst. Der Energieträger steht in der Zeilenbeschriftung, das Jahr im Spaltenkopf oder im Tabellentitel, das Szenario im Abschnittstitel, das Gebiet in der Caption. Zitier die Stelle, an der die Angabe wirklich steht.
   AUS WELCHER Quelle du zitieren darfst, hängt vom Feld ab, und die Zeile sagt dir, welche ihre eigene ist: "source" nennt die Quelle, in der die Zahl steht, "section" den Abschnitt, in dem diese Quelle steht (eine Quelle mit "holds" ist so ein Abschnitt).
   - "carrier" und "sector": nur aus der eigenen Quelle oder ihrem Abschnitt. Beide stehen in der Zeilenbeschriftung oder in der Kopfzeile DERSELBEN Tabelle.
   - "year", "scenario" und "quantity": zusätzlich aus einer Quelle auf der Nachbarseite ("page" um 1 daneben). Der ankündigende Satz steht oft im Absatz davor.
   Ein Zitat aus einer anderen Quelle wird abgelehnt, auch wenn es richtig klingt. Die Angabe darin ist echt, sie gehört nur einer anderen Zeile.
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

9. "corrections" (nur bei einer Wiederholung): steht das im Eingabe-Objekt, war deine vorige Antwort für die dort genannten Zeilen nicht belegbar, und der Grund steht dabei. Lies ihn und antworte für GENAU diese Zeilen neu. Zitier eine andere Stelle, oder antworte mit "out:unstated", wenn die Angabe in den gezeigten Passagen wirklich nicht steht. Dieselbe Antwort noch einmal zu schicken hilft nicht, sie fällt genauso durch.
