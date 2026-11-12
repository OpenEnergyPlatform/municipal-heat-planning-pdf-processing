/* The flow as data: the steps of the profile's flow file (extraction/flow.py, blocks.py, conditions.py) and every edit
   of it. The page keeps the tree the server sent and changes it in place, so a key no control shows goes back as it
   came. */
import { isObj, type Obj } from '../lib/util';
import { t, tn, tr } from '../lib/i18n';

export type Step = Obj & { id: string };
export interface Way { when?: Cond; steps: Step[] }
export interface Row { of: string; is: string; op?: string; value?: unknown; not?: boolean }
export type Cond = { all: Row[] } | { any: Row[] };

export interface LibSetting { key: string; kind: string; label: string; default?: unknown; number?: string; choices?: string[]; words?: Record<string, string>; help?: string; where?: string[] }
export interface LibBox {
  type: string; label: string; group: string; takes: string; gives: string; says: string; code: string; asks: string | null;
  needs: string[]; settings: LibSetting[]; fixed: string; switch: boolean; decided: string; attached: string[];
  prepares: boolean; spec: string | null; top: boolean; marks: string[];
  /* what it takes and gives by name (extraction/variables.py); "a|b" one of them, "?" where it does without */
  inputs?: string[]; outputs?: string[];
}
/* a preset of "Ask the model" (extraction/presets.py): the box it is, with its name, explanation, settings and frames
   (blocks.box_of), the kind of step whose rules it reads, its request and the parts it gives a step that sets none */
export interface LibPreset extends LibBox {
  name: string; kind: string; request: string; parts: { inputs: Obj[]; reply: unknown; into: Obj };
  values: Obj; flow: string; scope: string; after: string[];
}
/* a form of an answer the reading knows, and a target: what becomes of an answer (extraction/forms.py, targets.py) */
export interface LibForm { label: string; says: string }
export interface LibTarget {
  label: string; says: string; nested: boolean; gives: string[]; forms: string[]; profile: string; apart?: boolean;
  outputs?: string[];
}
/* a variable a step can take: what the page calls it, what it holds, its JSON schema, whether it holds for the whole
   document */
export interface Variable { label: string; says: string; schema: unknown; lasting: boolean }
export interface Library {
  boxes: LibBox[]; each: Record<string, string>; which: Record<string, string>; orders: Record<string, string[]>;
  arrows: Record<string, string>; each_titles: Record<string, string>; order_words: Record<string, string>;
  variables?: Record<string, Variable>; items?: Record<string, (string | null)[]>; start?: string[];
  presets?: LibPreset[]; forms?: Record<string, LibForm>; targets?: Record<string, LibTarget>;
}
export interface Prop { name: string; kind: string; label: string; ops: string[]; choices?: string[]; words?: Record<string, string> }
/* a thing a condition is about; "variable" takes any variable by its path and every comparison */
export interface Subject { name: string; label: string; props: Prop[]; variable?: boolean; ops?: string[] }
export interface FlowNumber {
  name: string; help: string; least: number; value: number; own: boolean; inherited: number | null; owner: string;
  setting: string | null; in_effect: number; origin: string; own_at?: StepRef[];
}
/* a step of the saved flow that gives a rule or number a value of its own */
export interface StepRef { id: string; kind: string }
/* a rule or number a step can read (editor/flow.py step_rules); a key has no value here */
export interface StepRule {
  name: string; source: 'rule' | 'number'; tab: string; group: string; kind: string; help: string;
  least: number | null; most: number | null; choices: string[]; columns: string[]; of: string; empty: boolean;
  decided: string; setting: string | null; machine: boolean; secret: boolean; steps: string[];
  standard: unknown; standard_from: string; in_effect: unknown; origin: string;
}
/* a value of the machine, written into the project file only */
export interface MachineRule extends Omit<StepRule, 'steps' | 'standard' | 'standard_from' | 'source' | 'machine' | 'secret'> {
  key: string | null; value: unknown;
}
export interface FlowData {
  file: string; exists: boolean; base: string | null; whole: boolean; starts_from: string; drawn_by: string;
  inherited_tree: Step[] | null; numbers: FlowNumber[]; tree: Step[]; library: Library; conditions: Subject[];
  prompts: Record<string, { id: string; written: boolean; owner: string | null }>;
  never: Record<string, string>; switches: Record<string, { name: string; label: string; none: string; items: { label: string; to: unknown }[] }>;
  problems: { id?: string; name?: string; message: string }[];
  notes: { says: string; to: unknown }[];
  settings: { key: string; env: string; value: string | null; origin: string; help: string; secret: boolean; set: boolean }[];
  step_rules: { rules: StepRule[]; kinds: Record<string, string[]>; tabs: Record<string, string> };
  run: { machine: MachineRule[]; project: { file: string; exists: boolean; refused: string | null } | null };
  /* what the general steps choose from: how an input is shown, the profile's prompts, the fields of the Spec, the
     variables there before each step */
  shows?: Record<string, { label: string; says: string }>;
  prompt_ids?: string[];
  spec_fields?: { uri: string; label: string }[];
  available?: Record<string, string[]>;
}

/* how a rule names the kind of a step (rules.step_kind): a box by its kind, a step of "Ask the model" by its preset's,
   a frame as "each <what>", "round" or "if" */
export const stepKind = (n: Step, lib?: Library): string => {
  const k = kindOf(n);
  if (k === 'box') { const p = lib ? presetOf(lib, n) : undefined; return p ? p.kind : n.box; }
  return k === 'each' ? 'each ' + n.each : k;
};

export type Kind = 'box' | 'each' | 'round' | 'if' | '';
export const kindOf = (n: unknown): Kind =>
  (['box', 'each', 'round', 'if'] as const).find(k => isObj(n) && Object.prototype.hasOwnProperty.call(n, k)) || '';

/* the lists of steps inside a loop, round or branching: one for a loop and a round, one per branch of a branching (and its else) */
export interface StepList { key: string; label: string; way?: Way; steps: Step[] }
export function lists(n: Step): StepList[] {
  const k = kindOf(n);
  if (k === 'each' || k === 'round') { n.steps = n.steps || []; return [{ key: n.id, label: '', steps: n.steps }]; }
  if (k === 'if') {
    const out: StepList[] = (n.if || []).map((w: Way, i: number) => ({ key: n.id + '#' + i, label: t('branch {n}', { n: i + 1 }), way: w, steps: (w.steps = w.steps || []) }));
    if (Object.prototype.hasOwnProperty.call(n, 'else')) out.push({ key: n.id + '#else', label: t('else'), steps: n.else });
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
/* the list a key names: "root", the id of a loop or round, "<if id>#<branch index>", "<if id>#else" */
export function listOf(tree: Step[], key: string): Step[] | null {
  if (key === 'root') return tree;
  const [id, part] = key.split('#');
  const got = find(tree, id);
  if (!got) return null;
  const l = lists(got.n).find(x => x.key === (part === undefined ? id : key));
  return l ? l.steps : null;
}
/* the loops, rounds and branchings around a step, outermost first */
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
/* the preset a step of "Ask the model" names, where the library has it */
export const presetOf = (lib: Library, n: Step): LibPreset | undefined =>
  n.box === 'ask' && n.preset ? (lib.presets || []).find(p => p.name === n.preset) : undefined;
/* the box a step is: a step of "Ask the model" with a preset is that preset (blocks.box_of) */
export const stepBox = (lib: Library, n: Step): LibBox | undefined => presetOf(lib, n) || libBox(lib, n.box);
/* what a step of "Ask the model" has of *key* where it sets nothing of its own: its preset's part or value; the prompt
   of its request (general.parts_of) */
export function presetPart(lib: Library, n: Step, key: string): unknown {
  const p = presetOf(lib, n);
  if (key === 'request') return p ? p.request : undefined;
  if (key === 'prompt') {
    const request = String((n.set && n.set.request) || (p ? p.request : 'own'));
    return request === 'own' ? 'extraction/ask' : 'extraction/' + request;
  }
  if (p && key in p.parts) return (p.parts as Obj)[key];
  return p ? (p.values || {})[key] : undefined;
}
/* the five parts of a step of "Ask the model": its own where it sets them, else its preset's (general.parts_of) */
export function partsOf(lib: Library, n: Step): { request: string; prompt: unknown; inputs: Obj[]; reply: unknown; into: Obj } {
  const set = (n.set || {}) as Obj;
  const part = (key: string) => (set[key] !== undefined ? set[key] : presetPart(lib, n, key));
  const into = { ...((part('into') as Obj) || {}) };
  if (into.to === undefined) into.to = into.field ? 'values' : 'var';
  return { request: String(part('request') || 'own'), prompt: part('prompt'), inputs: (part('inputs') as Obj[]) || [],
    reply: part('reply'), into };
}

export function labelOf(lib: Library, n: Step): string {
  const k = kindOf(n);
  if (k === 'box') { const b = stepBox(lib, n); return b ? tr(b.label) : n.box; }
  if (k === 'each' && n.each === 'list') {
    const title = tr((lib.each_titles || {}).list) || t('For each entry of a list');
    return n.list ? t('{title}: {list}', { title, list: String(n.list) }) : title;
  }
  if (k === 'each') {
    const title = tr((lib.each_titles || {})[n.each]) || t('For each {name}', { name: n.each });
    return n.which ? t('{title} ({which})', { title, which: tr(lib.which[n.which] || n.which) }) : title;
  }
  if (k === 'round') return n.round && n.round.most ? tn(n.round.most, 'Round, at most {n} time', 'Round, at most {n} times') : t('Round, until the search hits are used up');
  return t('Branching (if / else)');
}
/* what an arrow after a step carries, in words: a step gives a key of library.arrows, a loop what it goes through */
/* what a loop hands on: the kind of thing it goes through, as an arrow says it */
const ARROW_OF_EACH: Record<string, string> = { coordinate: 'coordinates', value: 'values', field: 'fields', piece: 'pieces', settled: 'fields' };
export function giveOf(lib: Library, n: Step): string {
  const k = kindOf(n);
  const arrows = lib.arrows || {};
  const word = (key: string) => tr(arrows[key] || key);
  if (k === 'box') { const b = stepBox(lib, n); return b && b.gives ? word(b.gives) : ''; }
  if (k === 'each') return word(ARROW_OF_EACH[n.each] || n.each);
  return '';
}

/* -- conditions ------------------------------------------------------------------------------------------------- */

/* the comparisons of a condition in words */
export const opWord = (op: string): string => ({
  is: t('is'), is_not: t('is not'), less: t('less than'), more: t('more than'), at_least: t('at least'), at_most: t('at most'),
  contains: t('contains'), empty: t('is empty'), one_of: t('is one of'),
} as Record<string, string>)[op] || op;
/* a value of a property of kind "choice", in words */
export const choiceWord = (p: Prop, v: string): string => tr((p.words || {})[v] || v);
export const subjectOf = (subjects: Subject[], name: string) => subjects.find(s => s.name === name);
/* a row about a variable has no property of a list: the path of the variable is its property, of kind "var" */
export const propOf = (subjects: Subject[], row: Row): Prop | undefined => {
  const s = subjectOf(subjects, row.of);
  if (s && s.variable) return { name: row.is, kind: 'var', label: row.is, ops: s.ops || [] };
  return s && s.props.find(p => p.name === row.is);
};
export const firstProp = (subjects: Subject[], s: string) => {
  const x = subjectOf(subjects, s);
  return x ? (x.variable ? 'answer' : x.props[0].name) : '';
};
export const rowsOf = (c: Cond): Row[] => ('all' in c ? c.all : c.any) || [];

/* "when the dimension's state is one of read and the dimension is a year" */
export function sentence(subjects: Subject[], c: unknown): string {
  if (!isObj(c)) return '';
  const joiner = c.all ? ' ' + t('and') + ' ' : ' ' + t('or') + ' ';
  const rows = ((c.all || c.any || []) as Row[]).map(r => {
    const s = subjectOf(subjects, r.of), p = propOf(subjects, r);
    if (!s || !p) return '(?)';
    if (s.variable) {
      const no = r.not ? t('not') + ' ' : '';
      if (!r.op) return no + r.is;
      if (r.op === 'empty') return t('{path} {op}', { path: no + r.is, op: opWord('empty') });
      const v = Array.isArray(r.value) ? r.value.join(' ' + t('or') + ' ') : String(r.value);
      return t('{path} {op} {value}', { path: no + r.is, op: opWord(r.op), value: v });
    }
    const subject = tr(s.label), prop = tr(p.label);
    if (p.kind === 'yes') return r.not ? t('not ({subject} · {prop})', { subject, prop }) : t('{subject} · {prop}', { subject, prop });
    const op = opWord(r.op || '');
    if (r.op === 'empty') return r.not ? t('not ({subject} · {prop} {op})', { subject, prop, op }) : t('{subject} · {prop} {op}', { subject, prop, op });
    const value = Array.isArray(r.value) ? r.value.map(v => p.kind === 'choice' ? choiceWord(p, String(v)) : String(v)).join(' ' + t('or') + ' ') : String(r.value);
    return r.not ? t('not ({subject} · {prop} {op} {value})', { subject, prop, op, value }) : t('{subject} · {prop} {op} {value}', { subject, prop, op, value });
  }).join(joiner);
  return t('when {condition}', { condition: rows });
}
/* A property that is a yes has no comparison and no value; any other takes the first comparison it offers where the row
   has none it knows. */
export function normRow(subjects: Subject[], r: Row): Row {
  const p = propOf(subjects, r);
  if (p && p.kind === 'var') { if (r.op && !p.ops.includes(r.op)) delete r.op; return r; }
  if (p && p.kind !== 'yes') { if (!p.ops.includes(r.op || '')) r.op = p.ops[0]; }
  else { delete r.op; delete r.value; }
  return r;
}
export function freshRow(subjects: Subject[], of: string): Row { return normRow(subjects, { of, is: firstProp(subjects, of) }); }

/* -- edits ----------------------------------------------------------------------------------------------------- */

export function fresh(tree: Step[], subjects: Subject[], kind: 'box' | 'preset' | 'each' | 'round' | 'if', arg?: string): Step {
  if (kind === 'box') return { id: newId(tree, arg!), box: arg };
  if (kind === 'preset') return { id: newId(tree, arg!), box: 'ask', preset: arg };
  if (kind === 'each' && arg === 'list') return { id: newId(tree, 'each_list'), each: 'list', list: '', as: 'item', steps: [] };
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
/* a loop, round or branching around steps that stand next to each other: it takes their place and holds them */
export function wrap(tree: Step[], subjects: Subject[], ids: string[], kind: 'each' | 'round' | 'if', arg?: string): Step | null {
  const run = siblingsRun(tree, ids);
  if (!run) return null;
  const frame = fresh(tree, subjects, kind, arg);
  const inner = run.steps.splice(run.from, run.count, frame);
  if (kind === 'if') frame.if[0].steps = inner; else frame.steps = inner;
  return frame;
}
/* the steps inside a loop, round or branching, all of them, for "N steps inside" */
export const inside = (n: Step) => [...walk(lists(n).flatMap(l => l.steps))].length;
