/* Boxes of a drawing moved by hand. The layout places every box; a box dragged elsewhere keeps its new place over what the
   layout gives, while the page is open and never in a file. A box that carries others (`data.carries`, the ids of the boxes
   drawn inside it without being its children) takes them along. Pure: the page and the tests' node both run it. */

export interface At { x: number; y: number }
/* by the id of a box: its place, as the drawing gives positions (relative to its parent box where it has one) */
export type Moved = Map<string, At>;

interface Placed { id: string; position: At; data?: unknown }
interface Change { type: string; id?: string; position?: At }

/* the boxes as they are shown: each moved one at its new place */
export function shownNodes<N extends Placed>(nodes: N[], moved: Moved | null | undefined): N[] {
  if (!moved || !moved.size) return nodes;
  return nodes.map(n => {
    const at = moved.get(n.id);
    return at ? { ...n, position: { x: at.x, y: at.y } } : n;
  });
}

/* the moves of a drag (the changes the drawing reports) into `moved`, measured from the boxes as `shown`; true where a box
   moved */
export function takeMoves(changes: Change[], shown: Placed[], moved: Moved): boolean {
  const by = new Map(shown.map(n => [n.id, n]));
  let any = false;
  for (const c of changes) {
    if (c.type !== 'position' || !c.position || !c.id) continue;
    const n = by.get(c.id);
    if (!n) continue;
    const was = moved.get(c.id) || n.position;
    const dx = c.position.x - was.x, dy = c.position.y - was.y;
    if (!dx && !dy) continue;
    moved.set(c.id, { x: c.position.x, y: c.position.y });
    const carries = ((n.data || {}) as { carries?: string[] }).carries || [];
    for (const id of carries) {
      const m = by.get(id);
      if (!m) continue;
      const at = moved.get(id) || m.position;
      moved.set(id, { x: at.x + dx, y: at.y + dy });
    }
    any = true;
  }
  return any;
}
