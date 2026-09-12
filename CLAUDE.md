# Vor jeder Änderung

Jeder Defekt, der hier einen GPU-Lauf gekostet hat, hatte dieselbe Form: die
Änderung war in ihrer Datei richtig und über etwas außerhalb falsch. Der Lock
lag um die Memo-Dicts statt um den MuPDF-Aufruf. Die Klassenprüfung kam an die
Träger-Kante und nicht an die Sektor-Kante. Die Stempel wurden gelöscht, um ein
Neuernten zu erzwingen, und der Code, der sie liest, hält einen fehlenden
Stempel für „erledigt" — 165 Dokumente übersprungen, Job exit 0.

Vier Regeln, in dieser Reihenfolge.

## 1. Das andere Ende lesen

    python scripts/change_audit.py

Listet, was diese Änderung außerhalb ihrer eigenen Zeilen berührt:

- **CONSUMERS** — ein Literal, das die Änderung schreibt und andere Stellen
  lesen. `*.stamp.json` löschen heißt, was `already_done` daraus macht.
- **SIBLINGS** — ein Name, den die Änderung anfasst und andere Stellen auch.
  Jede Stelle ändern oder je Stelle entscheiden, es nicht zu tun.
- **UNTESTED** — eine neue Funktion, die kein Test nennt.

Jeden Treffer aufmachen und lesen. Nicht überfliegen, aufmachen. Das ist der
Schritt, der zweimal an einem Tag gefehlt hat.

## 2. Den Test aus der Zusage schreiben, nicht aus dem Code

Ein Test, der aus dem Code abgeleitet ist, kann eine fehlende Hälfte nie
finden. `merge_field` versprach im Docstring „sitzt in der Quelle UND enthält
die Antwort" und prüfte die erste Hälfte; der Test dazu prüfte genau die
gebaute Hälfte. 27,6 % der Jahre eines Korpuslaufs belegten sich mit einer
Passage ohne Jahreszahl.

Also: die Zusage als **einen Satz** hinschreiben. Jedes UND darin ist eine
eigene Zusicherung und braucht einen eigenen Test.

## 3. Jede Prüfung muss durchfallen können

Zu jedem Torwächter, Test und Gate: welche Eingabe bringt ihn zum Melden? Wenn
sich in dreißig Sekunden keine bauen lässt, ist er Dekoration.

- Der Trockenlauf stubbt das Modell mit dem Beispiel des Profils, also mit per
  Konstruktion perfekt belegten Daten. Er konnte die fehlende Belegprüfung
  nicht finden, weil ihm nie ein falsches Zitat vorgelegt wurde.
- Der Kanarienvogel hat eine Datei gemessen, die kein Lauf geschrieben hat,
  und „trägt" gemeldet.

Zu jedem neuen Test gehört ein Fall, der die Zusage **per Konstruktion**
verletzt: ein falsches Zitat, eine veraltete Datei, ein leeres Ergebnis.

## 4. Zahlen tragen Einheiten

`kept = tuples - dropped_coordinates` ergab −253.666. Jede berichtete Zahl
sagt, wovon sie zählt: Tupel, Koordinaten, Dokumente, Anfragen.

# Die Vorgaben des Eigentümers

Geprüft wird bei einem Wert und bei jeder Koordinate genau zweierlei: das
Zitat steht in einer gezeigten Passage, und die Antwort steht im Zitat. Dazu
kommt nur die Mindestlänge, damit ein Zitat eine Stelle benennt. Wo die
Passage steht, welche Tabelle sie ist und über welcher Spalte eine Zahl
steht, ist Lesen und keine Prüfung.

Dazu kommt, entschieden am 2026-09-11: eine Antwort auf eine geschlossene
Liste ist einer ihrer Einträge. Eine Antwort außerhalb der Liste wird mit
Begründung neu gefragt und nie als gelesen markiert (`not_an_option`).

Und, entschieden am 2026-09-12: kein JSON wird repariert. Weder werden
Klammern geschlossen noch Codefences oder `<think>`-Blöcke entfernt, noch
wird ein Objekt aus umgebendem Text herausgeschnitten, noch werden aus einer
abgeschnittenen Antwort die fertigen Tupel gerettet. Gelesen wird genau ein
JSON-Objekt. Alles andere wird neu gefragt, und die Rückfrage nennt die
Ursache (`_reply_fault`: cut_off, empty, no_object, syntax, outside_text,
missing_key, not_an_object, wrong_shape). Passt eine Antwort nicht in ihr
Token-Limit, wird die Anfrage geteilt statt die Antwort gerettet: der
Zeilen-Harvester halbiert seine Passagen, der Feld-Frager seine Zeilen, der
Rahmen-Frager seine Quellen, und eine einzelne Passage bekommt mehr Platz.
Bleibt nichts zu teilen, ist das Ergebnis ein Loch mit Grund (`_why:
cut_off`) und kein halb gelesener Wert. Ein Wert, der die Prüfung nicht
überlebt, verliert seinen Stempel: `read` wird zu `unbacked`, und Zitat und
Quelle gehen mit.

Drei Prüfungen darüber hinaus (Belegregel own/local/any, „eine Antwort, zwei
Spalten", „falsche Spalte") sind ohne Auftrag gebaut worden und haben den
Kassel-Pilot 12881827 mitgekippt. Deshalb:

- Keine neue Prüfung, kein neuer Ablehnungsgrund, kein neuer Filter ohne
  ausdrückliche Zustimmung. Wer eine für nötig hält, fragt und baut nicht.
  `tests/test_extraction_reasons.py` hält die Gründe fest; ein neuer Grund
  muss dort offen eingetragen werden, sonst fällt der Test.
- Den Ablauf so bauen, wie er vorgegeben ist. Weicht ein Entwurf ab, wird die
  Abweichung vor dem Bauen genannt und entschieden, nicht hinterher berichtet.
- Bei Details, die der Auftrag offenlässt, im Chat fragen statt selbst
  entscheiden. Eine kurze Frage hätte hier viel Arbeit erspart: der
  Eigentümer hätte seine Vorstellung direkt genannt, statt dass Prüfungen
  gebaut, gemessen und wieder ausgebaut werden.
- Ein Frame-Paar wird über jede Passage gelesen, die es druckt, und die
  Zeilen bekommen das Jahr ihres Paars.
- Anker sind kurze Sätze: einer je Dokument und Wert, ein Satz je
  Achsenfrage. Keine langen Passagen als Anker, keine eingefrorenen Anker
  im Profil.
- Keine Closure liest einen Namen, der danach neu gebunden wird. Derselbe
  Test prüft das für `docpipe/extraction`.

# Was der Lauf hinterlässt

Eine Koordinate endet immer mit einem Zustand, nie leer:

| | |
|---|---|
| `read` | gelesen, die Passage trägt die Angabe |
| `derived` | nicht gefragt, die Spec entscheidet sie aus der Einheit |
| `unstated` | gefragt, das Dokument sagt es nicht — erst nach dem Durchkämmen |
| `unbacked` | geantwortet, die zitierte Passage trägt es nicht |
| `exhausted` | noch offen, als das Budget endete |
| `unanswered` | keine Antwort auf diese Zeile |
| `out_of_slice` | nie gefragt, eine Torkoordinate hat die Zeile ausgeschlossen |

`unstated` ist ein Befund über den Plan, `exhausted` einer über den Lauf. Sie
zusammenzuwerfen ist der Fehler, wegen dem es diese Zustände gibt.

Jede Erntedatei endet mit einer `kind: summary`-Zeile: Verteilung über die
Vertrauensstufen A, B und C, die Gründe und die Bildherkunft. Konflikt und
Zweitlesung stehen nicht darin, die kennt erst der Serializer.

Neben dem Wert steht immer der Wortlaut (`<achse>_raw`) und die Passage
(`<achse>_quote`). Deshalb kostet eine gewachsene Optionsliste `--remap`
statt eines Korpuslaufs, und der Stempel trägt je Parameter und je Achse
einen Fingerabdruck, damit ein Lauf sieht, welche Frage sich geändert hat.

Verglichen werden nur diese Schlüssel. Der Hash über die ganze Spec-Datei
steht weiter im Stempel, damit jemand sagen kann, aus welcher Datei eine
Ernte stammt, entscheidet aber nichts: er bewegt sich bei einem Kommentar,
einer Einrückung, einem kg-Block, und verglichen überstimmt er jeden
feineren Schlüssel. Ebenso hängt der Ankerschlüssel an den Fragen und nicht
an den Dateibytes, sonst schriebe das Modell bei jeder Anmerkung alle Anker
neu und der Korpus würde aus anderen Passagen gelesen. Nur wenn der Stempel
die feinen Schlüssel gar nicht hat, entscheidet der Dateihash wieder.
