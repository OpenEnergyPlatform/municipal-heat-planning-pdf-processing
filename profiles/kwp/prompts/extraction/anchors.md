---
temperature: 0.4
max_tokens: 800
---
Du unterstützt die semantische Suche in deutschen kommunalen Wärmeplänen ("Kommunale Wärmeplanung").

Du bekommst die Beschreibung einer Kennzahl, so wie sie in einer Ontologie definiert ist. Formuliere daraus SECHS kurze, sachliche Aussagen, wie sie genau so in einem Wärmeplan stehen könnten und die Kennzahl KONKRET enthalten — mit den Fachbegriffen, die im Dokument tatsächlich stünden.

Steht im Objekt ein Feld "question", ist NICHT die Kennzahl selbst gesucht, sondern die ANTWORT auf genau diese Frage. Schreibe dann Sätze, in denen die Antwort dasteht, nicht Sätze über die Kennzahl. Zur Frage "In welchem Bezugsjahr gilt der Wert?" gehören Sätze wie "Bilanzjahr der Erhebung ist 2022." oder ein Tabellenkopf "| Energieträger | 2019 | 2030 | 2045 |", nicht Sätze über Endenergieverbrauch.

Regeln:

1. Keine Fragen, keine Meta-Sätze. Schreibe so, als STÜNDE die Angabe schon da. FALSCH: "Der Endenergieverbrauch wird in Kapitel 4 dargestellt."
2. Setze plausible Werte samt Einheit ein — sie sind nur Suchanker, nicht Behauptungen. RICHTIG: "Der Endenergieverbrauch für Wärme im Stadtgebiet betrug 2022 rund 512 GWh/a."
3. Streue über die Formen, in denen die Angabe in einem Plan auftaucht: Fließtext einer Bestandsanalyse, Tabellenüberschrift mit Einheit in eckigen Klammern, Abbildungsunterschrift, Zwischenüberschrift, Aufzählung im Ergebniskapitel, Satz aus dem Zielszenario-Kapitel.
4. Nutze die Wörter, die deutsche Wärmepläne benutzen, nicht die der Ontologie: Endenergieverbrauch, Wärmebedarf, Energieträgermix, Bilanzjahr, Zielszenario, THG-Emissionen, Bestandsanalyse, Fokusgebiet.
5. Jede Aussage 12 bis 35 Wörter. Keine zwei Aussagen, die dasselbe anders sagen.

Antworte mit NUR einem JSON-Objekt, kein Markdown, kein Text davor oder danach:
{"anchors": ["<Aussage 1>", "<Aussage 2>", "<Aussage 3>", "<Aussage 4>", "<Aussage 5>", "<Aussage 6>"]}
