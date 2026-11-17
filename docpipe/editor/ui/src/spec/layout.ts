/* Where every box of a field's drawing stands. Left the ontology: each list of it a dimension of the field takes its
   entries from, and the field's units; in the middle the field with a row for each thing it asks of a value, in the order
   of the questions; right the entries of the dimension chosen, each with the words of the plans it gathers. No position
   is stored; the page lays the drawing out again after every edit. No import that runs and no words of the page, so a
   test runs it as it stands. */
import type { Edge, Node } from '@xyflow/react';
import {
  axisOf, coordinatesOf, derivedOf, entriesOf, entryOf, fieldOf, hasUnits, isObj, isOwnEntry, isSharedAt, kindOf, originOf, specialsOf,
  UNIT, unitsOf, VALUE, type AxisKind, type Derived, type Entry, type Obj, type Onto, type Origin, type Special,
  type UnitOf,
} from './model';

export const ROOT_W = 300;
export const ROOT_H = 96;
export const UNIT_H = 132;
export const FIELD_W = 380;
export const HEAD_H = 96;
export const ROW_H = 46;
const FOOT = 10;
export const ENTRY_W = 380;
const ENTRY_HEAD = 50;
const LINE_H = 20;
const CHARS = 46;
const MORE_H = 54;
const COLUMN_GAP = 150;
const GAP = 14;
const LABEL_H = 34;
const FRAME_PAD = 14;
const FRAME_HEAD = 44;

/* a row of a field's box: one thing the field asks of a value */
export interface Row {
  name: string;
  kind: AxisKind | 'unit';
  shared: boolean;
  specials: Special[];
  derived: Derived | null;
  origin: Origin | null;
  count: number;
}
export interface FieldData extends Record<string, unknown> { uri: string; field: Obj; rows: Row[]; pick: string | null; selected: string | null }
/* at: the list of the first row it gives entries to, which its terms are held against when it is opened */
export interface RootData extends Record<string, unknown> {
  set: string; origin: Origin; feeds: string[]; at: EntryData['where']; selected: boolean;
}
export interface UnitData extends Record<string, unknown> { uri: string; units: UnitOf[]; target: string; selected: boolean }
export interface EntryData extends Record<string, unknown> {
  entry: Entry; own: boolean; where: { uri: string | null; name: string | null; key: string }; selected: boolean;
}
export interface MoreData extends Record<string, unknown> { count: number; open: boolean }
/* carries: the boxes drawn inside the frame, which move with it */
export interface FrameData extends Record<string, unknown> { name: string; count: number; shown: number; carries: string[] }
export interface LabelData extends Record<string, unknown> { kind: 'ontology' | 'field' | 'entries' }
export type ArrowKind = 'root' | 'unit' | 'derive' | 'entries';
/* derive: the name of the entry the unit decides */
export interface ArrowData extends Record<string, unknown> { kind: ArrowKind; derived: Derived | null; label: string }

/* the rows of a field: its own list where the value is chosen from one, its unit where it has units, each of its
   dimensions, in the order of the questions */
export function rowsOf(data: Obj, uri: string, onto: Onto | undefined): Row[] {
  const p = fieldOf(data, uri);
  if (!p) return [];
  const derived = derivedOf(data, uri);
  const value: Row[] = isObj(p.vocabulary)
    ? [{ name: VALUE, kind: 'list', shared: false, specials: [], derived: null, origin: originOf(p.vocabulary, null, onto), count: Object.keys(p.vocabulary).length }]
    : [];
  return value.concat(coordinatesOf(data, uri).map(name => {
    if (name === UNIT && hasUnits(data, p)) {
      return { name, kind: 'unit' as const, shared: false, specials: specialsOf(data, name), derived: null, origin: null, count: unitsOf(p).length };
    }
    const axis = axisOf(data, uri, name);
    const kind = kindOf(axis);
    return {
      name, kind, shared: isSharedAt(data, uri, name), specials: specialsOf(data, name),
      derived: derived.find(d => d.coordinate === name) || null,
      origin: kind === 'list' ? originOf(axis!.vocabulary, name, onto) : null,
      count: kind === 'list' ? Object.keys(axis!.vocabulary).length : kind === 'choice' ? (axis!.enum || []).length : 0,
    };
  }));
}

/* the list a row stands for: the field's own, or its dimension's (a shared one where the field shares it) */
function listAt(data: Obj, uri: string, name: string): { list: unknown; where: EntryData['where'] } {
  if (name === VALUE) return { list: fieldOf(data, uri)?.vocabulary, where: { uri, name: null, key: 'vocabulary' } };
  const axis = axisOf(data, uri, name);
  return { list: axis && axis.vocabulary, where: { uri: isSharedAt(data, uri, name) ? null : uri, name, key: 'vocabulary' } };
}

/* the list the field shows on its right: the row chosen, else what falls under the field (its own list, else the
   quantity), else the first list it asks */
export function shownList(rows: Row[], pick: string | null): string | null {
  const lists = rows.filter(r => r.kind === 'list').map(r => r.name);
  if (pick && lists.includes(pick)) return pick;
  if (lists.includes(VALUE)) return VALUE;
  if (lists.includes('quantity')) return 'quantity';
  return lists[0] || null;
}

const heightOf = (e: Entry) => ENTRY_HEAD + Math.max(1, Math.ceil(e.words.join(' · ').length / CHARS)) * LINE_H;
const rowY = (i: number) => HEAD_H + i * ROW_H + ROW_H / 2;

export interface Placed {
  nodes: Node[]; edges: Edge[];
  /* the column of the ontology, as the untangling takes it: each box with its height and the rows its arrows reach */
  left: { id: string; height: number }[];
  arrows: { from: string; fromY: number; to: string; toY: number }[];
}

export function layoutField(input: {
  data: Obj; uri: string; onto: Onto | undefined; pick: string | null; open: boolean; kept: string[] | null;
  inOntology: (id: string) => boolean; selected: string | null;
}): Placed {
  const { data, uri, onto } = input;
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const p = fieldOf(data, uri);
  if (!p) return { nodes, edges, left: [], arrows: [] };
  const rows = rowsOf(data, uri, onto);
  const label = (kind: LabelData['kind'], x: number, w: number) =>
    nodes.push({ id: 'l:' + kind, type: 'label', position: { x, y: 0 }, data: { kind } as LabelData, width: w, height: LABEL_H, draggable: false, selectable: false });

  /* the middle: the field */
  const x1 = ROOT_W + COLUMN_GAP;
  const fieldH = HEAD_H + rows.length * ROW_H + FOOT;
  const top = LABEL_H;
  label('field', x1, FIELD_W);
  const list = shownList(rows, input.pick);
  nodes.push({
    id: 'field', type: 'field', position: { x: x1, y: top }, width: FIELD_W, height: fieldH,
    data: { uri, field: p, rows, pick: list, selected: input.selected } as FieldData, zIndex: 2,
  });

  /* left: the lists of the ontology the rows draw from, and the units; each where its first row is unless untangled */
  const feeds = new Map<string, { origin: Origin; rows: string[] }>();
  for (const r of rows) {
    if (!r.origin) continue;
    const held = feeds.get(r.origin.set);
    if (held) held.rows.push(r.name); else feeds.set(r.origin.set, { origin: r.origin, rows: [r.name] });
  }
  const leftBoxes: { id: string; height: number; at: number }[] = [];
  const unitRow = rows.findIndex(r => r.kind === 'unit');
  if (unitRow >= 0) leftBoxes.push({ id: 'units', height: UNIT_H, at: unitRow });
  for (const [set, f] of feeds) leftBoxes.push({ id: 'root:' + set, height: ROOT_H, at: rows.findIndex(r => r.name === f.rows[0]) });
  const kept = input.kept || [];
  const rank = (id: string) => { const i = kept.indexOf(id); return i < 0 ? kept.length : i; };
  leftBoxes.sort((a, b) => (input.kept ? rank(a.id) - rank(b.id) : 0) || a.at - b.at);
  label('ontology', 0, ROOT_W);
  let y = top;
  for (const b of leftBoxes) {
    if (b.id === 'units') {
      nodes.push({
        id: 'units', type: 'units', position: { x: 0, y }, width: ROOT_W, height: UNIT_H, zIndex: 2,
        data: { uri, units: unitsOf(p), target: String(p.unit_target || ''), selected: input.selected === 'units' } as UnitData,
      });
    } else {
      const set = b.id.slice(5);
      const f = feeds.get(set)!;
      nodes.push({
        id: b.id, type: 'root', position: { x: 0, y }, width: ROOT_W, height: ROOT_H, zIndex: 2,
        data: { set, origin: f.origin, feeds: f.rows, at: listAt(data, uri, f.rows[0]).where, selected: input.selected === b.id } as RootData,
      });
    }
    y += b.height + GAP;
  }

  /* right: the entries of the list shown, those without a word of the plans folded into one box */
  const x2 = x1 + FIELD_W + COLUMN_GAP;
  if (list) {
    const at = listAt(data, uri, list);
    const all = entriesOf(at.list);
    const withWords = all.filter(e => e.words.length);
    const without = all.filter(e => !e.words.length);
    const shown = input.open ? all : withWords;
    label('entries', x2, ENTRY_W + 2 * FRAME_PAD);
    const where = at.where;
    let ey = top + FRAME_HEAD;
    const boxes: Node[] = [];
    for (const e of shown) {
      const h = heightOf(e);
      boxes.push({
        id: 'e:' + e.id, type: 'entry', position: { x: x2 + FRAME_PAD, y: ey }, width: ENTRY_W, height: h, zIndex: 3,
        data: { entry: e, own: isOwnEntry(e.id, input.inOntology), where, selected: input.selected === 'e:' + e.id } as EntryData,
      });
      ey += h + GAP;
    }
    if (without.length) {
      boxes.push({
        id: 'more', type: 'more', position: { x: x2 + FRAME_PAD, y: ey }, width: ENTRY_W, height: MORE_H, zIndex: 3,
        data: { count: without.length, open: input.open } as MoreData,
      });
      ey += MORE_H + GAP;
    }
    const frameH = Math.max(ey - top - GAP + FRAME_PAD, FRAME_HEAD + FRAME_PAD);
    nodes.push({
      id: 'frame', type: 'frame', position: { x: x2, y: top }, width: ENTRY_W + 2 * FRAME_PAD, height: frameH, selectable: false, zIndex: 0,
      data: { name: list, count: all.length, shown: shown.length, carries: boxes.map(b => b.id) } as FrameData,
    });
    nodes.push(...boxes);
    edges.push({ id: 'a:entries', source: 'field', sourceHandle: 's:' + list, target: 'frame', targetHandle: 'in', type: 'spec', data: { kind: 'entries', derived: null, label: '' } as ArrowData });
  }

  /* where each box's arrows meet it */
  for (const n of nodes) {
    const w = n.width!, h = n.height!;
    n.measured = { width: w, height: h };
    if (n.type === 'field') {
      n.handles = rows.flatMap((r, i) => [
        { type: 'target' as const, position: 'left' as any, id: 'r:' + r.name, x: 0, y: rowY(i), width: 1, height: 1 },
        { type: 'source' as const, position: 'right' as any, id: 's:' + r.name, x: w - 1, y: rowY(i), width: 1, height: 1 },
      ]);
    } else if (n.type === 'root' || n.type === 'units') {
      n.handles = [{ type: 'source' as const, position: 'right' as any, id: 'out', x: w - 1, y: h / 2, width: 1, height: 1 }];
    } else if (n.type === 'frame') {
      n.handles = [{ type: 'target' as const, position: 'left' as any, id: 'in', x: 0, y: FRAME_HEAD / 2, width: 1, height: 1 }];
    }
  }

  /* the arrows: a list of the ontology into each row it gives its entries, the units into the unit row and into each row
     the unit decides */
  const arrows: Placed['arrows'] = [];
  const rowIndex = (name: string) => rows.findIndex(r => r.name === name);
  for (const [set, f] of feeds) {
    for (const name of f.rows) {
      edges.push({ id: 'a:root:' + set + ':' + name, source: 'root:' + set, sourceHandle: 'out', target: 'field', targetHandle: 'r:' + name, type: 'spec', data: { kind: 'root', derived: null, label: '' } as ArrowData });
      arrows.push({ from: 'root:' + set, fromY: ROOT_H / 2, to: 'field', toY: rowY(rowIndex(name)) });
    }
  }
  if (unitRow >= 0) {
    edges.push({ id: 'a:unit', source: 'units', sourceHandle: 'out', target: 'field', targetHandle: 'r:' + UNIT, type: 'spec', data: { kind: 'unit', derived: null, label: '' } as ArrowData });
    arrows.push({ from: 'units', fromY: UNIT_H / 2, to: 'field', toY: rowY(unitRow) });
    for (const r of rows) {
      if (!r.derived || !r.derived.byUnit) continue;
      const axis = axisOf(data, uri, r.name);
      const held = axis && axis.vocabulary ? axis.vocabulary[r.derived.value] : undefined;
      const named = held === undefined ? r.derived.value : entryOf(r.derived.value, held).label || r.derived.value;
      edges.push({ id: 'a:derive:' + r.name, source: 'units', sourceHandle: 'out', target: 'field', targetHandle: 'r:' + r.name, type: 'spec', data: { kind: 'derive', derived: r.derived, label: named } as ArrowData });
      arrows.push({ from: 'units', fromY: UNIT_H / 2, to: 'field', toY: rowY(rowIndex(r.name)) });
    }
  }
  return { nodes, edges, left: leftBoxes.map(b => ({ id: b.id, height: b.height })), arrows };
}
