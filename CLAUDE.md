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

# Was der Lauf hinterlässt

Eine Koordinate endet immer mit einem Zustand, nie leer:

| | |
|---|---|
| `read` | gelesen, die Passage trägt die Angabe |
| `unstated` | gefragt, das Dokument sagt es nicht — erst nach dem Durchkämmen |
| `exhausted` | noch offen, als das Budget endete |
| `unanswered` | keine Antwort auf diese Zeile |

`unstated` ist ein Befund über den Plan, `exhausted` einer über den Lauf. Sie
zusammenzuwerfen ist der Fehler, wegen dem es diese Zustände gibt.
