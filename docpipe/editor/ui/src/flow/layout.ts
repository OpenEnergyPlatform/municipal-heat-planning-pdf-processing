/* Where every step stands. The flow is a nested list, so its picture follows from the nesting: a list is a column from
   top to bottom, a loop, round or branching is a coloured area around its column, the branches of a branching stand side
   by side. No position is stored; the page lays the flow out again after every edit. */
import { Position, type Edge, type Node } from '@xyflow/react';
import { t } from '../lib/i18n';
import { giveOf, inside, kindOf, labelOf, lists, sentence, type FlowData, type Step } from './model';

export const BOX_W = 300;
export const BOX_H = 54;
const GAP = 34;          // between two steps of a column: the arrow, its "+" and beside it what it carries
const DOT = 12;          // where a column begins and ends
const PAD = 22;          // inside a loop, round or branching, left and right
const HEAD = 58;         // the head of a loop, round or branching
const FOOT = 18;
const WAY_GAP = 36;      // between the branches of a branching
const WAY_HEAD = 34;     // the condition of a branch

export interface Decor {
  open: Set<string>;                       // the loops, rounds and branchings drawn open
  selected: Set<string>;
  problems: Map<string, string[]>;         // step id -> what the check says about it
  measured: Record<string, number> | null; // step id -> requests of the recorded runs
  tried: Record<string, number> | null;    // step id -> requests of the dry run
  triedMost: number;
}

export interface StepData extends Record<string, unknown> {
  step: Step; kind: string; label: string; open?: boolean; inside?: number; depth: number;
  problems: string[]; measured: number | null; tried: number | null; triedShare: number;
}
export interface EdgeData extends Record<string, unknown> { list: string; at: number; gives: string; when: string }

interface Size { w: number; h: number }
interface Placed { nodes: Node[]; edges: Edge[] }

export function layout(data: FlowData, tree: Step[], decor: Decor): Placed {
  const out: Placed = { nodes: [], edges: [] };
  const lib = data.library;
  const subjects = data.conditions;

  const sizeOf = (n: Step): Size => {
    const k = kindOf(n);
    if (k === 'box' || !decor.open.has(n.id)) return { w: BOX_W, h: BOX_H };
    const cols = lists(n).map(l => column(l.steps, k === 'if'));
    const w = cols.reduce((s, c) => s + c.w, 0) + WAY_GAP * Math.max(0, cols.length - 1);
    const h = cols.reduce((m, c) => Math.max(m, c.h), 0);
    return { w: Math.max(BOX_W + 2 * PAD, w + 2 * PAD), h: HEAD + h + FOOT };
  };
  const column = (steps: Step[], way: boolean): Size => {
    const sizes = steps.map(sizeOf);
    const w = Math.max(BOX_W, ...sizes.map(s => s.w));
    const h = (way ? WAY_HEAD : DOT) + sizes.reduce((s, x) => s + GAP + x.h, 0) + GAP + DOT;
    return { w, h };
  };

  /* one column at (x, y), relative to its parent node; returns nothing, places its nodes and the arrows between them */
  const place = (key: string, steps: Step[], x: number, y: number, parent: string | undefined, depth: number, way: { label: string } | null) => {
    const col = column(steps, !!way);
    const items: string[] = [];
    const beginId = (way ? 'way:' : 'begin:') + key;
    if (way) {
      out.nodes.push({ id: beginId, type: 'way', position: { x, y }, parentId: parent, draggable: false, selectable: false,
        data: { label: way.label }, width: col.w, height: WAY_HEAD, zIndex: depth * 2 + 1 });
    } else {
      out.nodes.push({ id: beginId, type: 'dot', position: { x: x + col.w / 2 - DOT / 2, y }, parentId: parent, draggable: false,
        selectable: false, data: {}, width: DOT, height: DOT, zIndex: depth * 2 + 1 });
    }
    items.push(beginId);
    let cy = y + (way ? WAY_HEAD : DOT);
    for (const n of steps) {
      cy += GAP;
      const s = sizeOf(n);
      const k = kindOf(n);
      const open = k !== 'box' && decor.open.has(n.id);
      const nx = x + (col.w - s.w) / 2;
      const d: StepData = {
        step: n, kind: k || 'bad', label: labelOf(lib, n), open, inside: k === 'box' ? undefined : inside(n), depth,
        problems: decor.problems.get(n.id) || [],
        measured: decor.measured ? decor.measured[n.id] ?? null : null,
        tried: decor.tried ? decor.tried[n.id] ?? null : null,
        triedShare: decor.tried && decor.triedMost ? (decor.tried[n.id] || 0) / decor.triedMost : 0,
      };
      out.nodes.push({ id: n.id, type: open ? 'frame' : 'step', position: { x: nx, y: cy }, parentId: parent, draggable: false,
        selected: decor.selected.has(n.id), data: d, width: s.w, height: s.h, zIndex: open ? depth * 2 : 1000 + depth });
      if (open) {
        const ls = lists(n);
        const cols = ls.map(l => column(l.steps, k === 'if'));
        const total = cols.reduce((sum, c) => sum + c.w, 0) + WAY_GAP * Math.max(0, cols.length - 1);
        let wx = (s.w - total) / 2;
        ls.forEach((l, i) => {
          const label = k === 'if' ? (l.key.endsWith('#else') ? t('else') : t('only {condition}', { condition: sentence(subjects, l.way && l.way.when) })) : '';
          place(l.key, l.steps, wx, HEAD, n.id, depth + 1, k === 'if' ? { label } : null);
          wx += cols[i].w + WAY_GAP;
        });
      }
      items.push(n.id);
      cy += s.h;
    }
    cy += GAP;
    const endId = 'end:' + key;
    out.nodes.push({ id: endId, type: 'dot', position: { x: x + col.w / 2 - DOT / 2, y: cy }, parentId: parent, draggable: false,
      selectable: false, data: { end: true }, width: DOT, height: DOT, zIndex: depth * 2 + 1 });
    items.push(endId);
    for (let j = 0; j + 1 < items.length; j++) {
      const before = j === 0 ? null : steps[j - 1];
      const after = j < steps.length ? steps[j] : null;
      const e: EdgeData = {
        list: key, at: j, gives: before ? giveOf(lib, before) : '',
        when: after && after.when ? t('only {condition}', { condition: sentence(subjects, after.when) }) : '',
      };
      out.edges.push({ id: 'e:' + key + ':' + j, source: items[j], target: items[j + 1], type: 'step', data: e,
        zIndex: 1000 + depth, selectable: false, focusable: false });
    }
  };

  place('root', tree, 0, 0, undefined, 0, null);
  /* the sizes are known, so they are given as measured: React Flow then keeps where each node's handles are when the
     flow is laid out anew, and the arrows stay drawn */
  for (const n of out.nodes) {
    const w = n.width!, h = n.height!;
    n.measured = { width: w, height: h };
    /* where the arrows meet a node: the middle of its top and of its bottom, known without measuring */
    n.handles = [
      { type: 'target', position: Position.Top, x: w / 2 - 0.5, y: 0, width: 1, height: 1 },
      { type: 'source', position: Position.Bottom, x: w / 2 - 0.5, y: h - 1, width: 1, height: 1 },
    ];
  }
  return out;
}
