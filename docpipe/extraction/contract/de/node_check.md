---
required: [role, example_reply]
optional: [language_note]
blocks: [corpus_language]
omittable: [corpus_language]
---
{{role}}

Du bekommst EINEN Knoten, der schon aus einem Dokument gelesen ist, und prüfst ihn.

Unter "node" steht der Knoten: das Feld, zu dem er gehört, sein "value" und jede gelesene Koordinate, jeweils mit Wortlaut ("_raw") und Zitat ("_quote").

Unter "quotes" steht jedes Zitat des Knotens mit "around": dem Text des Dokuments um das Zitat herum, das Zitat mittendrin. Mehr siehst du vom Dokument nicht.

Entscheide für "value" und für jede Koordinate des Knotens, ob der Text um ihr Zitat trägt, was der Knoten sagt:

- "holds": true, wenn der Text es sagt, auch mit anderen Worten oder als Tabellenzeile mit ihrem Kopf,
- "holds": false, wenn der Text etwas anderes sagt, es nicht sagt oder das Zitat nicht in seinem Text steht,
- "why": ein kurzer Satz, bei false, was der Text stattdessen sagt.

Prüfe, was dasteht. Lies keinen Wert neu und korrigiere nichts.

<!-- block: corpus_language -->
{{language_note}}

<!-- /block -->
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. Keine Backticks! In dieser Form:
{{example_reply}}
