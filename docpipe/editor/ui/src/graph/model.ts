/* The drawing of the Graph tab as data: what GET /api/graph sends, the drawing (`map` of the graph file) the page edits in
   place, and the questions the canvas asks of both (which box an arrow writes on, which property is still without an
   arrow, where everything stands). No position is stored in the file: the page lays out again after every edit. */
import { Position, type Edge, type Node } from '@xyflow/react';
import { t } from '../lib/i18n';
import type { UInput, UResult } from '../lib/untangle';
import { boxIds, classOf, demanded, kindOfArrow, missingOf, rowsOf, subjectOf, type ClassInfo, type Obj, type Row } from './rows';

export { arrowsTo, boxIds, classOf, demanded, isRed, kindOfArrow, localName, missingOf, propOf, rowsOf, subjectOf } from './rows';
export type { ClassInfo, Constraint, Obj, OneOf, PropInfo, Row } from './rows';

export interface FieldInfo {
  name: string; label: string; kind: 'field' | 'dimension' | 'reading'; help?: string; of?: string[];
  example?: { value: string; document: string } | null;
}
export interface BrickSetting { key: string; title?: string; kind: string; help: string; default: unknown }
export interface BrickInfo {
  name: string; kind: string; does: string; takes: string; gives: string; per: string; writes: string; own: boolean;
  settings: BrickSetting[];
}
/* a block ready to put in where a brick stands, as the shipped drawings have it */
export interface PresetInfo { name: string; kind: string; does: string; block: Obj; own: boolean }
export interface GraphData {
  file: string; exists: boolean; base: string | null; rules: Obj[]; classes: ClassInfo[]; skipped: string | null;
  constraints: Record<string, string>; set: { classes: Obj; constraints: Record<string, string> }; effects: string[];
  map: Obj; map_owner: string; fields: FieldInfo[]; bricks: BrickInfo[]; counts: string[]; harvest: boolean;
  documents: string[]; cost: string; gate: string;
  /* the blocks: presets, what a condition can be about, how a part of an address is made */
  presets?: PresetInfo[]; conditions?: any[]; part_from?: string[]; part_forms?: string[]; part_absent?: string[];
}
export interface Cur { classes: Obj; constraints: Record<string, string>; rules: Obj; map: Obj }
export interface Problem { box: string | null; arrow: string | null; message: string }

export const clone = <T,>(v: T): T => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

/* the data the page sends: what the server read, the drawing apart */
export function curOf(d: GraphData): Cur {
  return {
    classes: clone(d.set.classes || {}), constraints: clone(d.set.constraints || {}),
    rules: Object.fromEntries(d.rules.map(r => [r.name, clone(r.value)])), map: clone(d.map || {}),
  };
}

/* ---- words the drawing is read in ---- */
export const COUNT_WORDS = (): Record<string, { label: string; says: string }> => ({
  per_document: { label: t('One node per document'), says: t('Every document gets exactly one node of this box.') },
  per_name: { label: t('One node per name'), says: t('One node for each name the document gives, however often it is repeated.') },
  per_distinct: { label: t('One node per distinct reading'), says: t('One node for each different reading of the field; the same reading twice is one node.') },
  per_answer: { label: t('One node per answer'), says: t('One node for each answer a dimension takes, set by a table of the answers.') },
  per_value: { label: t('One node per number'), says: t('One node for each number the harvest read.') },
  per_object: { label: t('One node per object'), says: t('One node for each node another arrow points at and the graph does not make.') },
});
/* the counts whose nodes are made of fields of the harvest */
export const takesFields = (count: string) => ['per_name', 'per_distinct', 'per_value', 'per_answer'].includes(count);

export const arrowKey = (a: Obj) => `${a.from}>${a.to} ${a.property}`;
export const fieldsOfBox = (box: Obj): string[] => (typeof box.of === 'string' ? [box.of] : Array.isArray(box.of) && box.of.every((x: unknown) => typeof x === 'string') ? box.of : []);
/* which box an arrow writes on, the class of a box, its rows and what the shapes demand of them: graph/rows.ts */

export const humane = (name: string) => { const s = String(name).replace(/_/g, ' ').trim(); return s.charAt(0).toUpperCase() + s.slice(1); };
/* what a box is called on the page: its class as the ontology labels it, else the words of its name in the drawing */
export function boxTitle(d: GraphData, box: Obj): string {
  const c = classOf(d, box);
  return (c && c.label) || humane(String(box.id));
}

/* a free identifier for a new box */
export function freshBoxId(map: Obj, base: string): string {
  const slug = base.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'box';
  const stem = /^[a-z]/.test(slug) ? slug : 'box_' + slug;
  const ids = boxIds(map);
  if (!ids.has(stem)) return stem;
  for (let i = 2; ; i++) if (!ids.has(stem + '_' + i)) return stem + '_' + i;
}

/* removing a box takes every arrow to or from it with it */
export function removeBox(map: Obj, id: string) {
  map.boxes = (map.boxes || []).filter((b: Obj) => b.id !== id);
  map.arrows = (map.arrows || []).filter((a: Obj) => a.from !== id && a.to !== id);
  for (const b of map.boxes) {
    if (b.among === id) delete b.among;
    if (Array.isArray(b.of) && b.count === 'per_object') b.of = b.of.filter((x: Obj) => x.box !== id);
  }
}

/* ---- where everything stands ---- */
export const FIELD_W = 290;
export const FIELD_H = 62;
export const BOX_W = 400;
const HEAD_H = 84;
const ROW_H = 34;
const MORE_H = 34;
const GAP = 26;
const LABEL_H = 34;
const COLUMN_GAP = 150;

export interface Decor {
  selected: { kind: 'box' | 'arrow' | 'field' | null; id: string | null };
  problems: { boxes: Set<string>; arrows: Set<string> };
  expanded: Set<string>;
  d: GraphData;
  map: Obj;
  /* the order the page keeps after "Untangle arrows"; what it does not name stands where the layout puts it */
  kept?: Kept;
}
/* the order of the fields (within a kind) and of the boxes (within a column) the page keeps */
export interface Kept { fields: string[]; boxes: string[] }
export interface FieldData extends Record<string, unknown> { f: FieldInfo }
export interface BoxData extends Record<string, unknown> {
  box: Obj; cls: ClassInfo | null; rows: Row[]; shown: Row[]; hidden: number; foldable: boolean; expanded: boolean; bad: boolean; missing: number;
  selected: boolean; selectedArrow: string | null; badArrows: string[]; sub: string;
}
export interface EdgeData extends Record<string, unknown> {
  kind: 'field' | 'link' | 'of'; text: string; brick: string; bad: boolean; key: string; box?: string; field?: string;
}

/* what a box says of how many nodes it has and of what */
export function countSentence(box: Obj, d: GraphData): string {
  const w = COUNT_WORDS()[box.count];
  const base = w ? w.label : String(box.count);
  const of = fieldsOfBox(box).map(n => (d.fields.find(f => f.name === n) || { label: n }).label);
  if (box.count === 'per_object') return t('{count}: the nodes the arrows of {boxes} point at', { count: base, boxes: ((box.of || []) as Obj[]).map(x => x.box).join(', ') });
  return of.length ? t('{count}, of {fields}', { count: base, fields: of.join(', ') }) : base;
}

/* the entries of `list` that `kept` names stand in the order of `kept`, in the places the named ones took; the rest stay where they are */
function keep<T>(list: T[], name: (x: T) => string, kept: string[] | undefined): T[] {
  if (!kept || !kept.length) return list;
  const rank = new Map(kept.map((n, i) => [n, i]));
  const named = list.filter(x => rank.has(name(x))).sort((p, q) => rank.get(name(p))! - rank.get(name(q))!);
  let next = 0;
  return list.map(x => (rank.has(name(x)) ? named[next++] : x));
}

export function layout(d: GraphData, decor: Decor): { nodes: Node[]; edges: Edge[]; boxHeights: Record<string, number> } {
  const map = decor.map;
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const boxes: Obj[] = map.boxes || [];
  const arrows: Obj[] = map.arrows || [];
  const ids = boxIds(map);
  const yOf = new Map<string, number>();

  /* the fields, in spec order, by what they are */
  const groups: { title: string; list: FieldInfo[] }[] = [
    { title: t('Fields of the harvest'), list: keep(d.fields.filter(f => f.kind === 'field'), f => f.name, decor.kept?.fields) },
    { title: t('What a number says (its dimensions)'), list: keep(d.fields.filter(f => f.kind === 'dimension'), f => f.name, decor.kept?.fields) },
    { title: t('What a reading carries of itself'), list: keep(d.fields.filter(f => f.kind === 'reading'), f => f.name, decor.kept?.fields) },
  ];
  let y = 0;
  for (const g of groups) {
    if (!g.list.length) continue;
    nodes.push({ id: 'l:' + g.title, type: 'label', position: { x: 0, y }, data: { text: g.title }, draggable: false, selectable: false, width: FIELD_W, height: LABEL_H, measured: { width: FIELD_W, height: LABEL_H } });
    y += LABEL_H;
    for (const f of g.list) {
      nodes.push({
        id: 'f:' + f.name, type: 'field', position: { x: 0, y }, data: { f } as FieldData,
        selected: decor.selected.kind === 'field' && decor.selected.id === f.name, width: FIELD_W, height: FIELD_H,
        measured: { width: FIELD_W, height: FIELD_H },
        handles: [{ type: 'source', position: Position.Right, id: 'out', x: FIELD_W - 1, y: FIELD_H / 2 - 0.5, width: 1, height: 1 }],
      });
      yOf.set(f.name, y + FIELD_H / 2);
      y += FIELD_H + 10;
    }
    y += 14;
  }

  /* the box columns: a box some other box points at stands right of it */
  const level = new Map<string, number>();
  for (const b of boxes) level.set(b.id, 0);
  for (let pass = 0; pass < boxes.length; pass++) {
    let moved = false;
    for (const a of arrows) {
      if (kindOfArrow(map, a) !== 'link') continue;
      const want = (level.get(a.from) || 0) + 1;
      if ((level.get(a.to) || 0) < want && want <= boxes.length) { level.set(a.to, want); moved = true; }
    }
    if (!moved) break;
  }
  const boxHeights: Record<string, number> = {};
  const heightOf = new Map<string, { rows: Row[]; shown: Row[]; hidden: number; foldable: boolean; h: number }>();
  for (const b of boxes) {
    const rows = rowsOf(d, map, b);
    const open = decor.expanded.has(b.id);
    const shown = rows.filter(r => open || r.used.length || demanded(r) || r.uuid);
    const hidden = rows.length - shown.length;
    const foldable = rows.some(r => !r.used.length && !demanded(r) && !r.uuid);
    const h = HEAD_H + shown.length * ROW_H + (foldable ? MORE_H : 0) + 8;
    heightOf.set(b.id, { rows, shown, hidden, foldable, h });
  }
  const columns = new Map<number, Obj[]>();
  for (const b of boxes) columns.set(level.get(b.id) || 0, [...(columns.get(level.get(b.id) || 0) || []), b]);
  const bary = (b: Obj): number => {
    const ys: number[] = [];
    for (const a of arrows) {
      if (a.to === b.id && !ids.has(a.from) && yOf.has(a.from)) ys.push(yOf.get(a.from)!);
    }
    for (const f of fieldsOfBox(b)) if (yOf.has(f)) ys.push(yOf.get(f)!);
    return ys.length ? ys.reduce((s, v) => s + v, 0) / ys.length : Infinity;
  };
  const x0 = FIELD_W + COLUMN_GAP;
  const positions = new Map<string, { x: number; y: number }>();
  for (const [col, list] of [...columns.entries()].sort((a, b) => a[0] - b[0])) {
    const sorted = keep(list.map((b, i) => ({ b, i, v: bary(b) })).sort((p, q) => (p.v === q.v ? p.i - q.i : p.v - q.v)), x => String(x.b.id), decor.kept?.boxes);
    let cy = 0;
    for (const { b, v } of sorted) {
      const want = v === Infinity ? cy : Math.max(cy, v - HEAD_H / 2);
      positions.set(b.id, { x: x0 + col * (BOX_W + COLUMN_GAP), y: want });
      cy = want + heightOf.get(b.id)!.h + GAP;
    }
  }

  /* what is red: an arrow or a box the last check names, a demand of the shapes no arrow meets */
  for (const b of boxes) {
    const info = heightOf.get(b.id)!;
    const missing = missingOf(info.rows);
    const mine = arrows.filter(a => subjectOf(map, a) === b.id || a.to === b.id || a.from === b.id).map(arrowKey);
    const pos = positions.get(b.id)!;
    const data: BoxData = {
      box: b, cls: classOf(d, b), rows: info.rows, shown: info.shown, hidden: info.hidden, foldable: info.foldable, expanded: decor.expanded.has(b.id),
      bad: decor.problems.boxes.has(b.id), missing, selected: decor.selected.kind === 'box' && decor.selected.id === b.id,
      selectedArrow: decor.selected.kind === 'arrow' ? decor.selected.id : null,
      badArrows: mine.filter(k => decor.problems.arrows.has(k)), sub: countSentence(b, d),
    };
    const handles = [{ type: 'target' as const, position: Position.Left, id: 'in', x: 0, y: HEAD_H / 2, width: 1, height: 1 }];
    info.shown.forEach((r, i) => {
      const cy = HEAD_H + i * ROW_H + ROW_H / 2 - 0.5;
      handles.push({ type: 'target' as const, position: Position.Left, id: 't:' + r.curie, x: 0, y: cy, width: 1, height: 1 });
      (handles as Obj[]).push({ type: 'source', position: Position.Right, id: 's:' + r.curie, x: BOX_W - 1, y: cy, width: 1, height: 1 });
    });
    boxHeights[b.id] = info.h;
    nodes.push({
      id: 'b:' + b.id, type: 'box', position: pos, data, selected: data.selected, width: BOX_W, height: info.h,
      measured: { width: BOX_W, height: info.h }, handles: handles as any,
    });
  }

  /* the arrows */
  for (const a of arrows) {
    const kind = kindOfArrow(map, a);
    if (kind === 'node' || !ids.has(a.to)) continue;
    const key = arrowKey(a);
    const bad = decor.problems.arrows.has(key);
    const brick = a.brick ? (typeof a.brick === 'string' ? a.brick : a.brick.brick) : '';
    const text = a.label || '';
    if (kind === 'field') {
      if (!yOf.has(a.from)) continue;
      edges.push({
        id: 'a:' + key, source: 'f:' + a.from, sourceHandle: 'out', target: 'b:' + a.to, targetHandle: 't:' + a.property,
        type: 'arrow', data: { kind: 'field', text, brick, bad, key } as EdgeData,
        selected: decor.selected.kind === 'arrow' && decor.selected.id === key, zIndex: 10,
      });
    } else {
      edges.push({
        id: 'a:' + key, source: 'b:' + a.from, sourceHandle: 's:' + a.property, target: 'b:' + a.to, targetHandle: 'in',
        type: 'arrow', data: { kind: 'link', text, brick, bad, key } as EdgeData,
        selected: decor.selected.kind === 'arrow' && decor.selected.id === key, zIndex: 10,
      });
    }
  }
  /* the fields that make a box's nodes */
  for (const b of boxes) {
    for (const f of fieldsOfBox(b)) {
      if (!yOf.has(f)) continue;
      edges.push({
        id: 'o:' + b.id + ':' + f, source: 'f:' + f, sourceHandle: 'out', target: 'b:' + b.id, targetHandle: 'in', type: 'arrow',
        data: { kind: 'of', text: '', brick: '', bad: false, key: '', box: b.id, field: f } as EdgeData,
        selected: false, zIndex: 5,
      });
    }
  }
  return { nodes, edges, boxHeights };
}

/* ---- untangling the arrows ---- */
/* the drawing as columns for lib/untangle: the fields (grouped by kind) left, then the box columns, each arrow from the height of its port to the height of its port */
export function untangleInput(d: GraphData, nodes: Node[], edges: Edge[]): UInput {
  const fields = nodes.filter(n => n.type === 'field').sort((p, q) => p.position.y - q.position.y);
  const boxes = nodes.filter(n => n.type === 'box');
  const kind = new Map(d.fields.map(f => [f.name, f.kind]));
  const xs = [...new Set(boxes.map(n => n.position.x))].sort((p, q) => p - q);
  const byId = new Map(nodes.map(n => [n.id, n]));
  const columns = [
    fields.map(n => ({ id: n.id, height: n.height ?? FIELD_H, group: kind.get(n.id.slice(2)) })),
    ...xs.map(x => boxes.filter(n => n.position.x === x).sort((p, q) => p.position.y - q.position.y).map(n => ({ id: n.id, height: n.height ?? HEAD_H }))),
  ];
  const portY = (id: string, handle: string | null | undefined): number => {
    const n = byId.get(id);
    const h = n && ((n as Obj).handles as { id?: string | null; y: number }[] | undefined)?.find(x => x.id === handle);
    return h ? h.y + 0.5 : HEAD_H / 2;
  };
  return {
    columns,
    edges: edges.map(e => ({ from: e.source, fromY: portY(e.source, e.sourceHandle), to: e.target, toY: portY(e.target, e.targetHandle) })),
  };
}
/* what to keep of an untangled drawing */
export function keptFrom(r: UResult): Kept {
  return {
    fields: (r.columns[0] || []).map(id => id.slice(2)),
    boxes: r.columns.slice(1).flat().map(id => id.slice(2)),
  };
}
