/* The drawing of a flow as data: the steps of the profile's flow file (extraction/flow.py, blocks.py, conditions.py) and
   every edit of it. The page keeps the tree the server sent and changes it in place, so a key no control shows goes back
   as it came. */
import { isObj, type Obj } from '../lib/util';

export type Step = Obj & { id: string };
export interface Way { when?: Cond; steps: Step[] }
export interface Row { of: string; is: string; op?: string; value?: unknown; not?: boolean }
export type Cond = { all: Row[] } | { any: Row[] };

export interface LibSetting { key: string; kind: string; label: string; default?: unknown; number?: string; choices?: string[]; help?: string; where?: string[] }
export interface LibBox {
  type: string; label: string; group: string; takes: string; gives: string; says: string; code: string; asks: string | null;
  needs: string[]; settings: LibSetting[]; fixed: string; switch: boolean; decided: string; attached: string[];
  prepares: boolean; spec: string | null; top: boolean; marks: string[];
}
export interface Library { boxes: LibBox[]; each: Record<string, string>; which: Record<string, string>; orders: Record<string, string[]> }
export interface Prop { name: string; kind: string; label: string; ops: string[]; choices?: string[] }
export interface Subject { name: string; label: string; props: Prop[] }
export interface FlowNumber {
  name: string; help: string; least: number; value: number; own: boolean; inherited: number | null; owner: string;
  setting: string | null; in_effect: number; origin: string;
}
export interface FlowData {
  file: string; exists: boolean; base: string | null; whole: boolean; starts_from: string; drawn_by: string;
  inherited_tree: Step[] | null; numbers: FlowNumber[]; tree: Step[]; library: Library; conditions: Subject[];
  prompts: Record<string, { id: string; written: boolean; owner: string | null }>;
  never: Record<string, string>; switches: Record<string, { name: string; label: string; none: string; items: { label: string; to: unknown }[] }>;
  problems: { id?: string; name?: string; message: string }[];
  notes: { says: string; to: unknown }[];
  settings: { key: string; env: string; value: string | null; origin: string; help: string; secret: boolean; set: boolean }[];
}

export type Kind = 'box' | 'each' | 'round' | 'if' | '';
export const kindOf = (n: unknown): Kind =>
  (['box', 'each', 'round', 'if'] as const).find(k => isObj(n) && Object.prototype.hasOwnProperty.call(n, k)) || '';

/* the lists of steps inside a frame: one for each and round, one per way of an if (and its else) */
export interface StepList { key: string; label: string; way?: Way; steps: Step[] }
export function lists(n: Step): StepList[] {
  const k = kindOf(n);
  if (k === 'each' || k === 'round') { n.steps = n.steps || []; return [{ key: n.id, label: '', steps: n.steps }]; }
  if (k === 'if') {
    const out: StepList[] = (n.if || []).map((w: Way, i: number) => ({ key: n.id + '#' + i, label: 'way ' + (i + 1), way: w, steps: (w.steps = w.steps || []) }));
    if (Object.prototype.hasOwnProperty.call(n, 'else')) out.push({ key: n.id + '#else', label: 'else', steps: n.else });
    return out;
  }
  return [];
}
export function* walk(steps: Step[], parent: Step | null = null): Generator<[Step, Step[], Step | null]> {
  for (const n of steps) { yield [n, steps, parent]; for (const l of lists(n)) yield* walk(l.steps, n); }
}
export function find(tree: Step[], id: string) {
  for (const [n, steps, parent] of walk(tree)) if (n.id === id) return { n, steps, parent };
  return null;
}
/* the list a key names: "root", a frame's id, "<if id>#<way index>", "<if id>#else" */
export function listOf(tree: Step[], key: string): Step[] | null {
  if (key === 'root') return tree;
  const [id, part] = key.split('#');
  const got = find(tree, id);
  if (!got) return null;
  const l = lists(got.n).find(x => x.key === (part === undefined ? id : key));
  return l ? l.steps : null;
}
/* the frames around a step, outermost first */
export function ancestors(tree: Step[], id: string): string[] {
  const out: string[] = [];
  const down = (steps: Step[], path: string[]): boolean => {
    for (const n of steps) {
      if (n.id === id) { out.push(...path); return true; }
      for (const l of lists(n)) if (down(l.steps, path.concat([n.id]))) return true;
    }
    return false;
  };
  down(tree, []);
  return out;
}
export function newId(tree: Step[], base: string, taken: Set<string> = new Set()): string {
  const ids = new Set([...walk(tree)].map(([n]) => n.id));
  let i = 1;
  while (ids.has(base + '_' + i) || taken.has(base + '_' + i)) i++;
  return base + '_' + i;
}
export const libBox = (lib: Library, t: string) => (lib.boxes || []).find(b => b.type === t);

export function labelOf(lib: Library, n: Step): string {
  const k = kindOf(n);
  if (k === 'box') { const b = libBox(lib, n.box); return b ? b.label : n.box; }
  if (k === 'each') return 'For each ' + n.each + (n.which ? ' (' + (lib.which[n.which] || n.which) + ')' : '');
  if (k === 'round') return n.round && n.round.most ? 'Round, at most ' + n.round.most + (n.round.most === 1 ? ' time' : ' times') : 'Round, until the supply is used up';
  return 'If';
}
export function giveOf(lib: Library, n: Step): string {
  const k = kindOf(n);
  if (k === 'box') { const b = libBox(lib, n.box); return b ? b.gives : ''; }
  if (k === 'each') return n.each === 'coordinate' ? 'coordinates' : n.each === 'value' ? 'values' : n.each === 'field' ? 'fields' : n.each;
  return '';
}

/* -- conditions ------------------------------------------------------------------------------------------------- */

export const OPS: Record<string, string> = {
  is: 'is', is_not: 'is not', less: 'less than', more: 'more than', at_least: 'at least', at_most: 'at most',
  contains: 'contains', empty: 'is empty', one_of: 'is one of',
};
export const subjectOf = (subjects: Subject[], name: string) => subjects.find(s => s.name === name);
export const propOf = (subjects: Subject[], row: Row) => { const s = subjectOf(subjects, row.of); return s && s.props.find(p => p.name === row.is); };
export const firstProp = (subjects: Subject[], s: string) => { const x = subjectOf(subjects, s); return x ? x.props[0].name : ''; };
export const rowsOf = (c: Cond): Row[] => ('all' in c ? c.all : c.any) || [];

/* "when the coordinate's state is one of read and the coordinate is a year" */
export function sentence(subjects: Subject[], c: unknown): string {
  if (!isObj(c)) return '';
  const joiner = c.all ? ' and ' : ' or ';
  return 'when ' + ((c.all || c.any || []) as Row[]).map(r => {
    const s = subjectOf(subjects, r.of), p = propOf(subjects, r);
    if (!s || !p) return '(?)';
    if (p.kind === 'yes') return s.label + (r.not ? ' not: ' : ' ') + p.label;
    const v = Array.isArray(r.value) ? r.value.join(' or ') : r.value;
    return s.label + "'s " + p.label + (r.not ? ' not ' : ' ') + (OPS[r.op || ''] || r.op) + (r.op === 'empty' ? '' : ' ' + v);
  }).join(joiner);
}
/* What the old editor did each time it drew a row: a property that is a yes has no comparison and no value, any other
   takes the first comparison it offers where the row has none it knows. */
export function normRow(subjects: Subject[], r: Row): Row {
  const p = propOf(subjects, r);
  if (p && p.kind !== 'yes') { if (!p.ops.includes(r.op || '')) r.op = p.ops[0]; }
  else { delete r.op; delete r.value; }
  return r;
}
export function freshRow(subjects: Subject[], of: string): Row { return normRow(subjects, { of, is: firstProp(subjects, of) }); }

/* -- edits ----------------------------------------------------------------------------------------------------- */

export function fresh(tree: Step[], subjects: Subject[], kind: 'box' | 'each' | 'round' | 'if', arg?: string): Step {
  if (kind === 'box') return { id: newId(tree, arg!), box: arg };
  if (kind === 'each') return { id: newId(tree, 'each_' + arg), each: arg, steps: [] };
  if (kind === 'round') return { id: newId(tree, 'round'), round: { most: 1 }, steps: [] };
  return { id: newId(tree, 'if'), if: [{ when: { all: [normRow(subjects, { of: 'coordinate', is: 'year' })] }, steps: [] }], else: [] };
}
export function insertAt(steps: Step[], at: number, n: Step) { steps.splice(at, 0, n); }
/* moves a step to another place; false where the place lies inside the step itself */
export function moveTo(tree: Step[], id: string, steps: Step[], at: number): boolean {
  const got = find(tree, id);
  if (!got) return false;
  for (const [n] of walk([got.n])) if (n.steps === steps || (n.if || []).some((w: Way) => w.steps === steps) || n.else === steps) return false;
  const i = got.steps.indexOf(got.n);
  got.steps.splice(i, 1);
  if (got.steps === steps && i < at) at--;
  steps.splice(at, 0, got.n);
  return true;
}
export function moveBy(tree: Step[], id: string, by: number): boolean {
  const got = find(tree, id);
  if (!got) return false;
  const i = got.steps.indexOf(got.n), j = i + by;
  if (j < 0 || j >= got.steps.length) return false;
  got.steps.splice(i, 1); got.steps.splice(j, 0, got.n);
  return true;
}
export function remove(tree: Step[], id: string): boolean {
  const got = find(tree, id);
  if (!got) return false;
  got.steps.splice(got.steps.indexOf(got.n), 1);
  return true;
}
/* a copy right after the original; every step of the copy gets a new id */
export function duplicate(tree: Step[], id: string): Step | null {
  const got = find(tree, id);
  if (!got) return null;
  const copy: Step = JSON.parse(JSON.stringify(got.n));
  const taken = new Set<string>();
  for (const [n] of walk([copy])) { n.id = newId(tree, n.id.replace(/_\d+$/, ''), taken); taken.add(n.id); }
  got.steps.splice(got.steps.indexOf(got.n) + 1, 0, copy);
  return copy;
}
/* steps that stand next to each other in one list, in their order; null where they do not */
export function siblingsRun(tree: Step[], ids: string[]): { steps: Step[]; from: number; count: number } | null {
  if (!ids.length) return null;
  const got = ids.map(id => find(tree, id));
  if (got.some(g => !g)) return null;
  const steps = got[0]!.steps;
  if (got.some(g => g!.steps !== steps)) return null;
  const at = got.map(g => steps.indexOf(g!.n)).sort((a, b) => a - b);
  for (let i = 1; i < at.length; i++) if (at[i] !== at[i - 1] + 1) return null;
  return { steps, from: at[0], count: at.length };
}
/* a frame around steps that stand next to each other: it takes their place and holds them */
export function wrap(tree: Step[], subjects: Subject[], ids: string[], kind: 'each' | 'round' | 'if', arg?: string): Step | null {
  const run = siblingsRun(tree, ids);
  if (!run) return null;
  const frame = fresh(tree, subjects, kind, arg);
  const inner = run.steps.splice(run.from, run.count, frame);
  if (kind === 'if') frame.if[0].steps = inner; else frame.steps = inner;
  return frame;
}
/* the steps inside a frame, all of them, for "N boxes and frames inside" */
export const inside = (n: Step) => [...walk(lists(n).flatMap(l => l.steps))].length;
