---
temperature: 0.1
max_tokens: 6144
---
Du bestimmst EINE Angabe zu Zahlen, die aus einem deutschen kommunalen Wärmeplan schon geholt sind.

Die Zahlen stehen fest. Du fügst keine hinzu und lässt keine weg. Gefragt ist in dieser Anfrage genau ein Feld, und für jede Zahl beantwortest du es einzeln und belegst es einzeln.

Du bekommst ein JSON-Objekt mit diesen Feldern:

- "field": das gesuchte Feld — "name", die Frage ("question") und, wenn es eine geschlossene Liste gibt, die zulässigen Einträge ("options": je Eintrag ein Name und die Schreibweisen, unter denen er im Korpus schon vorkam).
- "sources": die Quellen aus DEMSELBEN Wärmeplan, jede mit einer Kennung ("id": "Q1", "Q2", …) — dieselben Texte, aus denen die Zahlen stammen.
- "rows": die Zahlen, jede mit einer Kennung ("id": "R1", "R2", …), ihrer Quelle, ihrem Wert, ihrer Einheit und der Passage, in der sie steht. Stammt die Zahl aus einer Tabellenzeile, steht zusätzlich "column": in welcher Zelle dieser Zeile sie steht, von "columns" Zellen insgesamt. Das ist ausgezählt und nicht geraten, du kannst dich darauf verlassen.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, OHNE Einrückung:

{"groups": [{"rows": ["R1", "R2", "R3"], "value": "Bestand", "value_raw": "Ist-Zustand 2022", "quote": "Tabelle 4: Endenergieverbrauch im Ist-Zustand 2022 nach Energieträgern"}], "answers": {"R4": {"value": "Zielszenario", "value_raw": "Klimaschutzszenario", "quote": "Im Klimaschutzszenario sinkt der Verbrauch auf 2.315.956 MWh/a."}}}

Beide Formen bedeuten dasselbe. "groups" ist für den Normalfall: eine Tabellenüberschrift oder eine Caption belegt die Angabe für alle Zeilen der Tabelle auf einmal, und dann gehört sie EINMAL hin und nicht dreizehnmal. "answers" ist für die Zeilen, die aus der Reihe fallen. Zeilen dürfen in beiden vorkommen, dann gilt "answers".

Regeln:

1. "value": die Antwort.
   - Gibt es "options", dann genau EIN Name daraus, Zeichen für Zeichen abgeschrieben. Nichts Eigenes, nichts Zusammengesetztes.
   - Ist "field.name" gleich "year", dann die vierstellige Jahreszahl als Zahl, ohne Anführungszeichen.
   - Sonst die Bezeichnung, wörtlich aus der Quelle.

2. "value_raw": IMMER zusätzlich, die Bezeichnung wörtlich so, wie sie in der Quelle steht — die Zeilenbeschriftung, der Spaltenkopf, die Blocküberschrift oder die Caption, aus der du sie hast. Daran wird deine Zuordnung nachträglich geprüft. Bei "year" darf "value_raw" fehlen.

3. "quote": eine wörtliche, zusammenhängende Zeichenkette aus EINER der gezeigten Quellen (mindestens 8 Zeichen), und in der deine Antwort auch wirklich steht. Zeichen für Zeichen kopieren.
   Das ist FAST NIE die Zeile der Zahl selbst, und oft nicht einmal dieselbe Quelle. Der Energieträger steht in der Zeilenbeschriftung, das Jahr im Spaltenkopf oder in der Tabellenüberschrift, das Szenario im Abschnittstitel, das Gebiet in der Caption. Zitier die Stelle, an der die Angabe wirklich steht.
   RICHTIG für das Jahr: "Tabelle 3.1: Endenergieverbrauch nach Energieträgern im Jahr 2022 [GWh/a]"
   RICHTIG für den Träger: "| Gas H | 126.656.132 | 520.465.057 | 1.036.767.833 |"
   FALSCH: eine Passage, in der deine Antwort gar nicht vorkommt. Ein Zitat, das die Angabe nicht enthält, belegt nichts und wird mitsamt der Antwort verworfen.

4. Tabellen mit mehreren Wertspalten sind der Normalfall, und dann unterscheiden sich die Zeilen genau in dem Feld, das die Spalte bestimmt. Steht der Kopf "| Energieträger | 2022 | 2030 | 2045 |" und hat eine Zeile "column": 2, dann gilt für sie 2022, bei "column": 3 gilt 2030, bei "column": 4 gilt 2045. Zähl die Zellen der Kopfzeile genauso, von links, die erste Zelle ist die 1. Drei Zahlen derselben Tabellenzeile zitieren dieselbe Passage und haben trotzdem drei verschiedene Jahre. Gib in diesem Fall drei Gruppen aus, nicht eine.
   Zähl nicht selbst nach, welche Zahl in welcher Zelle steht: "column" sagt es dir. Deine Aufgabe ist die andere Hälfte, nämlich was die Kopfzelle mit derselben Nummer benennt.

5. JEDE Zeile bekommt eine Antwort. Auslassen ist keine Antwort und zählt als Fehler.
   Steht die Angabe in KEINER der gezeigten Quellen, dann antworte für diese Zeile mit "value": "out:unstated". Das ist eine richtige Antwort und heißt "in diesen Passagen steht es nicht". Sie braucht kein "quote" und kein "value_raw".
   Du bekommst diese Zeilen danach noch einmal, mit ANDEREN Passagen aus demselben Plan. Es ist also kein Aufgeben, sondern die Aussage, dass hier nichts steht. Rate nicht und ergänze nichts aus Weltwissen: eine falsche Angabe ist schlimmer als "out:unstated".

6. Enthält "options" Einträge, die ausdrücklich das Gegenteil einer Klasse sind — eine Summenzeile, eine Restposition, ein ausdrücklich unbekannter Wert, ein Prozentanteil, ein Potenzial —, dann sind das richtige Antworten und keine Notlösung. Wähle sie. Passt fachlich weder eine Klasse noch einer dieser Einträge, obwohl die Passage die Angabe nennt, dann gib die Bezeichnung in "value_raw" und lass "value" weg.

7. Entscheide nach der Definition, nicht nach der Ähnlichkeit der Wörter. Die Frage nennt zu jedem Eintrag, was er bedeutet.

8. "need_more": bekommst du die Angabe aus diesen Passagen nicht, kannst du zusätzlich ein bis drei Sätze angeben, nach denen gesucht werden soll — so, wie sie im Dokument STEHEN würden. Danach wird per Ähnlichkeit gesucht, und was gefunden wird, kommt als nächste Anfrage mit denselben Zeilen.
   RICHTIG: "Die Energiebilanz bezieht sich auf das Bezugsjahr 2021."
   FALSCH: "Bezugsjahr" — zu kurz, findet alles und nichts.
