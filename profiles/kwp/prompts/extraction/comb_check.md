---
temperature: 0
max_tokens: 512
---
Prüfe EINEN Fund der Suche im Plan: Spricht die Stelle, aus der er zitiert ist, über diesen Wert?

Du bekommst:
- "passage": woher der Wert stammt, mit Art, Titel und Abschnitt.
- "parameter": das Feld mit seiner Definition.
- "row": den Wert mit seinem Zitat, was über ihn schon gelesen ist ("known") und was offen war ("open").
- "coordinate": die Angabe, nach der gesucht wurde, mit ihrer Frage.
- "answer": was die Suche für sie gefunden hat, mit Zitat.
- "place": die Passage, in der dieses Zitat steht, mit Art, Titel, Abschnitt und Text.

"about" ist "yes", wo die Stelle sagt, worauf sich die Aussage des Werts bezieht: Sie spricht über dieselbe Aussage, über die Tabelle oder Abbildung, in der der Wert steht, oder über den Abschnitt oder das Szenario, von dem das Zitat des Werts spricht. Es ist "no", wo die Stelle über etwas anderes spricht, etwa eine andere Tabelle, ein anderes Jahr, eine andere Aussage oder den Plan im Allgemeinen, auch wenn sie die gesuchte Angabe nennt.

Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

<!-- follow-up: corrections -->
Deine letzte Antwort hat einen Fehler, unter "what". Antworte noch einmal in derselben Form.
