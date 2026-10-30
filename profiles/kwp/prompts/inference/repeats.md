Du bekommst den Auftrag ("task") und eine nummerierte Liste von Aussagen ("statements"), die alle schon an ihrer Quelle geprüft sind. Sie stammen aus verschiedenen Stellen eines Plans, darum kann dieselbe Sache mehrfach darin stehen.

Nenne jede Aussage, die nur wiederholt, was eine frühere Aussage der Liste schon sagt.

Regeln:
- Eine Wiederholung sagt dasselbe über dieselbe Sache: gleicher Wert, gleiches Jahr, gleicher Bezug. Andere Worte ändern daran nichts.
- Weicht ein Wert, ein Jahr, eine Einheit oder der Bezug ab, ist es keine Wiederholung, auch wenn die Aussagen ähnlich klingen.
- Sagt die spätere Aussage mehr als die frühere, ist sie keine Wiederholung.
- Im Zweifel ist es keine Wiederholung.

Antworte mit NUR einem JSON-Objekt: {"repeats": [{"statement": <Nummer der späteren Aussage>, "of": <Nummer der früheren Aussage>}]}
Gibt es keine Wiederholung, ist die Liste leer.
