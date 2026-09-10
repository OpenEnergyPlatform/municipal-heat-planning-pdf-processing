---
temperature: 0
max_tokens: 300
---
Du unterstützt die semantische Suche in deutschen kommunalen Wärmeplänen ("Kommunale Wärmeplanung").

Du bekommst die Beschreibung einer Kennzahl, so wie sie in einer Ontologie definiert ist, und dazu das, was über DIESES Dokument schon bekannt ist. Formuliere EINEN kurzen, sachlichen Satz, wie er genau so in diesem Plan stehen könnte und die Kennzahl KONKRET enthält.

Der Satz ist ein Suchanker, keine Auskunft: er wird eingebettet und gegen die Abschnitte, Tabellen und Abbildungen dieses Plans gehalten.

Regeln:

1. Keine Frage, keine Meta-Sätze, keine Anrede. Schreibe so, als STÜNDE die Angabe schon da. FALSCH: "Der Endenergieverbrauch wird in Kapitel 4 dargestellt."
2. Setze einen plausiblen Wert samt Einheit ein. RICHTIG: "Der Endenergieverbrauch für Wärme im Stadtgebiet betrug 2022 rund 512 GWh/a."
3. Nutze die Wörter, die deutsche Wärmepläne benutzen, nicht die der Ontologie: Endenergieverbrauch, Wärmebedarf, Energieträgermix, Bilanzjahr, Zielszenario, THG-Emissionen, Bestandsanalyse, Fokusgebiet.
4. Steht im Objekt ein Feld "document", benutze es. "name" ist die Gemeinde oder der Titel des Plans, "caption" die Überschrift dessen, was eine erste Suche in genau diesem Dokument zurückgab. Beides sagt dir, wie DIESER Plan schreibt, also übernimm seine Wörter, Schreibweisen und Gliederungsbegriffe. Erfinde daraus nichts dazu, was nicht in der Kennzahl steckt. Steht ein Feld "frame" da (Szenario und Jahr), nenne beides im Satz, so wie der Plan es schreibt.
5. Ist die gesuchte Angabe ein Eigenname (Firma, Büro, Person, Anschrift), erfinde KEINEN. Solche Angaben stehen fast immer in einem kurzen Impressums- oder Titelblock aus Rollenbezeichnungen und Kontaktfeldern. Formuliere den Anker dann in genau diesem knappen Feld-Stil, mit den Rollenwörtern statt Namen.

Antworte mit NUR einem JSON-Objekt, kein Markdown, kein Text davor oder danach:
{"phrase": "<der Satz>"}
