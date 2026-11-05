Du bekommst den Auftrag ("task") und eine nummerierte Liste von Aussagen ("statements"), alle schon an ihrer Quelle geprüft. Sie stammen aus verschiedenen Stellen eines Plans, darum kann dieselbe Sache mehrfach darin stehen.

Nenne jede Aussage, die nur wiederholt, was eine frühere Aussage der Liste schon sagt.

- Eine Wiederholung sagt dasselbe über dieselbe Sache: gleicher Wert, gleiches Jahr, gleiche Einheit, gleicher Bezug. Andere Worte ändern daran nichts.
- Weicht ein Wert, ein Jahr, eine Einheit oder der Bezug ab, oder sagt die spätere Aussage mehr als die frühere, ist es keine Wiederholung, auch wenn die Aussagen ähnlich klingen. Im Zweifel ist es keine Wiederholung.

Antworte mit NUR einem JSON-Objekt: {"repeats": [{"statement": <Nummer der späteren Aussage>, "of": <Nummer der früheren Aussage>}]}
Gibt es keine Wiederholung, ist die Liste leer.
