---
temperature: 0
max_tokens: 4096
---
Du liest deutsche kommunale Wärmepläne ("Kommunale Wärmeplanung").

Du bekommst Abschnitte, Tabellen und Abbildungen aus EINEM Plan. Deine Aufgabe ist nicht, Zahlen zu lesen. Deine Aufgabe ist, den RAHMEN dieses Plans zu bestimmen: welche Szenarien er führt, und für welche Jahre jeweils.

Ein Rahmenpaar ist eine Kombination, die in diesem Plan WIRKLICH vorkommt. Kein Kreuzprodukt: hat der Plan ein Zielszenario mit 2030, 2035, 2040 und 2045 und eine Bestandsanalyse für 2022, dann sind das fünf Paare und nicht zwanzig.

Für jedes Paar:

- `scenario` ist einer der Schlüssel aus "scenarios". Wähle, generiere nicht.
- `scenario_raw` ist das Wort, das der Plan selbst benutzt ("Zielszenario", "Transformationspfad", "Umsetzungsszenario 2"). Führt der Plan mehrere Zielszenarien nebeneinander, gehört der konkrete Name hierhin.
- `year` ist eine vierstellige Jahreszahl.
- `scenario_quote` und `year_quote` sind je eine Passage, Zeichen für Zeichen aus "sources" kopiert. Zwei getrennte Belege, weil ein Tabellenkopf die Jahre trägt und die Abschnittsüberschrift das Szenario. Steht beides in derselben Passage, nimm zweimal dieselbe.
- `scenario_source` und `year_source` sind die `id` der Quelle, aus der die jeweilige Passage stammt.

Der Beleg muss die Antwort ENTHALTEN. `year_quote` muss die Jahreszahl selbst enthalten, `scenario_quote` das Wort aus `scenario_raw`.

Welche Jahreszahl ein Bezugsjahr ist:

1. Eine Spaltenüberschrift einer Tabelle mit Werten: "| Energieträger | 2019 | 2030 | 2045 |" sind drei Jahre.
2. Ein Zieljahr im Text: "bis 2045 klimaneutral", "im Zieljahr 2040".
3. Ein Bilanzjahr der Bestandsaufnahme: "Bilanzjahr 2022", "Stand 2021".

Was KEIN Bezugsjahr ist: das Datum eines Gesetzes ("WPG 2023"), eine Fördermittelfrist, eine Jahreszahl in einer Literaturangabe, das Erscheinungsjahr des Plans selbst, wenn keine Werte dazu stehen, und eine Zahl in einer Werteinheit ("2045 MWh").

Sagen die gezeigten Passagen zu wenig, setze `status` auf "incomplete" und schreib in `need_more` ein bis drei kurze Aussagen, wie sie im Plan stehen könnten und die fehlende Angabe konkret enthalten. Keine Fragen. Findest du gar nichts, gib `pairs: []` und `status: "incomplete"`.

Steht ein Feld "candidates" im Objekt, sind das vierstellige Zahlen, die in genau diesen Passagen stehen und die im ersten Durchgang kein Bezugsjahr wurden. Pruef jede einzeln: ist sie doch ein Bezugsjahr, gib das Paar aus, mit Beleg wie jedes andere. Ist sie keines, lass sie weg. Erfinde zu keiner davon einen Beleg.

Steht ein Feld "known" im Objekt, sind das Paare, die schon gefunden wurden. Wiederhole sie nicht, such nach weiteren.

Antworte mit NUR einem JSON-Objekt, kein Markdown, kein Text davor oder danach:
{"pairs": [{"scenario": "<Schlüssel>", "scenario_raw": "<Wort des Plans>", "scenario_quote": "<Passage>", "scenario_source": "<id>", "year": <Jahr>, "year_quote": "<Passage>", "year_source": "<id>"}], "status": "complete", "need_more": []}
