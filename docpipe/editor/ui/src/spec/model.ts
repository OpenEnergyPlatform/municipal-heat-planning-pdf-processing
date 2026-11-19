/* What the Spec tab shows of a spec and the edits it makes on it, from the spec object alone: which dimensions a field
   asks and in which order, which of them several fields share, the entries of a list with the words of the plans each
   one gathers, what follows from the unit, and the moves of a word, of a dimension into or out of the shared ones and
   of the order of the questions. The spec object stays as the server sent it where nothing is edited, so opening and
   saving it writes the file as it was. This file has no import that runs and no words of the page, so
   tests/test_editor_spec_model.py runs it as it stands. */

export type Obj = Record<string, any>;

export const isObj = (v: unknown): v is Obj => v !== null && typeof v === 'object' && !Array.isArray(v);
const own = (o: unknown, k: string): boolean => o != null && Object.prototype.hasOwnProperty.call(o, k);
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));

/* whether a value type with *settings* reads a key of a field that is read only under some of them (*when*, the server's
   `specs.READ_FOR`: {setting: the values it reads the key under}); a setting the type leaves out counts as false, a key
   with no *when* is read under every type, and a type the page does not know reads every key (owner request 2026-11-19,
   A6) */
export function typeReads(when: Record<string, unknown[]> | undefined, settings: Obj | undefined): boolean {
  if (!when) return true;
  if (!settings) return true;
  return Object.entries(when).every(([k, want]) => want.includes(settings[k] === undefined ? false : settings[k]));
}

/* a field's dimension written as this word is the spec's shared dimension of that name */
export const SHARED = 'shared';
/* the coordinate that is the unit a number is printed in */
export const UNIT = 'unit';
/* the row of a field's drawing that is the field's own list: what the value itself is chosen from */
export const VALUE = '@value';
/* the lists of the spec's order of the questions besides the order itself */
export const SPECIAL = ['own_passage', 'own_value', 'frame'] as const;
export type Special = typeof SPECIAL[number];

export const fieldsOf = (data: Obj): Obj[] => (Array.isArray(data?.parameters) ? data.parameters : [])
  .filter((p: unknown) => isObj(p) && typeof (p as Obj).uri === 'string');
export const fieldOf = (data: Obj, uri: string): Obj | undefined => fieldsOf(data).find(p => p.uri === uri);
export const sharedOf = (data: Obj): Obj => (isObj(data?.shared_axes) ? data.shared_axes : {});

/* the dimension a field asks under *name*: its own, or the shared one where the field gives it as "shared" */
export function axisOf(data: Obj, uri: string, name: string): Obj | undefined {
  const p = fieldOf(data, uri);
  if (!p || !isObj(p.axes) || !own(p.axes, name)) return undefined;
  const a = p.axes[name];
  if (a === SHARED) { const s = sharedOf(data)[name]; return isObj(s) ? s : undefined; }
  return isObj(a) ? a : undefined;
}
export const isSharedAt = (data: Obj, uri: string, name: string): boolean => {
  const p = fieldOf(data, uri);
  return !!p && isObj(p.axes) && p.axes[name] === SHARED;
};
/* the fields that ask the shared dimension *name*, in the order of the spec */
export const usersOf = (data: Obj, name: string): string[] =>
  fieldsOf(data).filter(p => isObj(p.axes) && p.axes[name] === SHARED).map(p => p.uri);
/* the fields that ask a dimension of this name at all, shared or their own */
export const askersOf = (data: Obj, name: string): string[] =>
  fieldsOf(data).filter(p => isObj(p.axes) && own(p.axes, name)).map(p => p.uri);

/* the spec's order of the questions and its three lists, as written ([] where missing) */
export const orderOf = (data: Obj): string[] => (isObj(data?.coordinates) && Array.isArray(data.coordinates.order) ? data.coordinates.order : []);
export const specialList = (data: Obj, key: Special): string[] =>
  (isObj(data?.coordinates) && Array.isArray(data.coordinates[key]) ? data.coordinates[key] : []);
export const specialsOf = (data: Obj, name: string): Special[] => SPECIAL.filter(k => specialList(data, k).includes(name));

/* whether a field's numbers are printed in units: it accepts units and the spec asks which one a number is in */
export const hasUnits = (data: Obj, p: Obj): boolean => !!data?.unit_question && isObj(p.units_accepted) && Object.keys(p.units_accepted).length > 0;

/* the coordinates a field is asked, in the spec's order: its unit (where it has units) and each of its dimensions */
export function coordinatesOf(data: Obj, uri: string): string[] {
  const p = fieldOf(data, uri);
  if (!p) return [];
  const names = (hasUnits(data, p) ? [UNIT] : []).concat(isObj(p.axes) ? Object.keys(p.axes) : []);
  const order = orderOf(data);
  const at = (n: string) => { const i = order.indexOf(n); return i < 0 ? order.length : i; };
  return names.map((n, i) => ({ n, i })).sort((a, b) => (at(a.n) - at(b.n)) || (a.i - b.i)).map(x => x.n);
}

/* what a dimension holds: a closed list, a list per document, a number, words, a choice of strings */
export type AxisKind = 'list' | 'per_document' | 'number' | 'words' | 'choice' | 'none';
export function kindOf(axis: Obj | undefined): AxisKind {
  if (!isObj(axis)) return 'none';
  if (isObj(axis.vocabulary)) return 'list';
  if (axis.dynamic) return 'per_document';
  if (Array.isArray(axis.enum)) return 'choice';
  if (axis.type === 'int' || axis.type === 'float') return 'number';
  if (axis.type === 'text') return 'words';
  return 'none';
}

/* an entry of a list as the page shows it: its key, its name, the words of the plans it gathers, its definition */
export interface Entry { id: string; label: string; words: string[]; definition: string; gloss: string; group: string }
export function entryOf(id: string, raw: unknown): Entry {
  if (Array.isArray(raw)) return { id, label: raw[0] == null ? '' : String(raw[0]), words: raw.slice(1).map(String), definition: '', gloss: '', group: '' };
  const o = isObj(raw) ? raw : {};
  return {
    id, label: o.label == null ? '' : String(o.label),
    words: Array.isArray(o.spellings) ? o.spellings.map(String) : [],
    definition: typeof o.definition === 'string' ? o.definition : '',
    gloss: typeof o.gloss === 'string' ? o.gloss : '',
    group: typeof o.group === 'string' ? o.group : '',
  };
}
export const entriesOf = (list: unknown): Entry[] => (isObj(list) ? Object.entries(list).map(([id, raw]) => entryOf(id, raw)) : []);
/* an entry of the spec's own, which no ontology has: the out: answers, and any key that is no term of the snapshot */
export const isOwnEntry = (id: string, inOntology: (id: string) => boolean): boolean => id.startsWith('out:') || !inOntology(id);

/* what the spec decides of a field without asking where no request read it: a dimension from the unit, or under a
   condition about the reading */
export interface Derived { coordinate: string; value: string; byUnit: boolean; condition: unknown }
export function derivedOf(data: Obj, uri: string): Derived[] {
  const p = fieldOf(data, uri);
  if (!p || !isObj(p.axes)) return [];
  const out: Derived[] = [];
  for (const name of Object.keys(p.axes)) {
    const a = axisOf(data, uri, name);
    if (!isObj(a) || !isObj(a.derive)) continue;
    const d = a.derive;
    out.push({ coordinate: name, value: String(d.value ?? ''), byUnit: !own(d, 'if'), condition: own(d, 'if') ? d.if : null });
  }
  return out;
}

/* the units a field accepts: each with its factor onto the field's unit and whether it names a period ("MWh/a") */
export interface UnitOf { unit: string; factor: number | null; perPeriod: boolean | null; target: string | null }
export function unitsOf(p: Obj | undefined): UnitOf[] {
  if (!p || !isObj(p.units_accepted)) return [];
  return Object.entries(p.units_accepted).map(([unit, raw]) => {
    const o = isObj(raw) ? raw : { factor: raw };
    return {
      unit, factor: typeof o.factor === 'number' ? o.factor : null,
      perPeriod: typeof o.names_period === 'boolean' ? o.names_period : null,
      target: typeof o.target === 'string' ? o.target : null,
    };
  });
}

/* ---------- edits ---------- */

/* the field asks its own copy of the shared dimension *name* from now on; the shared one goes where no field asks it */
export function unshare(data: Obj, uri: string, name: string): boolean {
  const p = fieldOf(data, uri);
  const s = sharedOf(data)[name];
  if (!p || !isObj(p.axes) || p.axes[name] !== SHARED || !isObj(s)) return false;
  p.axes[name] = clone(s);
  if (!usersOf(data, name).length) {
    delete data.shared_axes[name];
    if (!Object.keys(data.shared_axes).length) delete data.shared_axes;
  }
  return true;
}

/* the field's own dimension *name* becomes the shared one: 'made' where there was none of that name (the field's
   becomes it), 'joined' where the shared one says the same, 'differs' where it says something else (nothing changes
   unless *replace*, which drops the field's own), 'none' where the field has no own dimension of that name */
export function share(data: Obj, uri: string, name: string, replace = false): 'made' | 'joined' | 'differs' | 'none' {
  const p = fieldOf(data, uri);
  if (!p || !isObj(p.axes) || !isObj(p.axes[name])) return 'none';
  const shared = sharedOf(data);
  if (!own(shared, name)) {
    if (!isObj(data.shared_axes)) data.shared_axes = {};
    data.shared_axes[name] = p.axes[name];
    p.axes[name] = SHARED;
    return 'made';
  }
  if (JSON.stringify(shared[name]) !== JSON.stringify(p.axes[name]) && !replace) return 'differs';
  p.axes[name] = SHARED;
  return 'joined';
}

/* a field gets the shared dimension *name* it does not ask yet */
export function giveShared(data: Obj, uri: string, name: string): boolean {
  const p = fieldOf(data, uri);
  if (!p || !own(sharedOf(data), name)) return false;
  if (!isObj(p.axes)) p.axes = {};
  if (own(p.axes, name)) return false;
  p.axes[name] = SHARED;
  inOrder(data, name);
  return true;
}
/* a field gets a dimension of its own */
export function giveOwn(data: Obj, uri: string, name: string, axis: Obj): boolean {
  const p = fieldOf(data, uri);
  if (!p) return false;
  if (!isObj(p.axes)) p.axes = {};
  if (own(p.axes, name)) return false;
  p.axes[name] = clone(axis);
  inOrder(data, name);
  return true;
}
/* a coordinate the order does not name yet goes to its end */
function inOrder(data: Obj, name: string) {
  if (!isObj(data.coordinates)) data.coordinates = { order: [] };
  if (!Array.isArray(data.coordinates.order)) data.coordinates.order = [];
  if (!data.coordinates.order.includes(name)) data.coordinates.order.push(name);
}

/* a word of the plans moves from one entry of a list to another; the name of an entry is no word that moves */
export function moveWord(list: Obj, from: string, word: string, to: string): boolean {
  if (!isObj(list) || from === to || !own(list, from) || !own(list, to)) return false;
  const a = entryOf(from, list[from]);
  const b = entryOf(to, list[to]);
  if (!a.words.includes(word) || b.words.includes(word) || b.label === word) return false;
  removeWord(list, from, word);
  return addWord(list, to, word);
}
export function addWord(list: Obj, id: string, word: string): boolean {
  const w = word.trim();
  if (!isObj(list) || !own(list, id) || !w) return false;
  const e = entryOf(id, list[id]);
  if (e.label === w || e.words.includes(w)) return false;
  const raw = list[id];
  if (Array.isArray(raw)) raw.push(w);
  else if (isObj(raw)) { if (Array.isArray(raw.spellings)) raw.spellings.push(w); else raw.spellings = [w]; }
  else return false;
  return true;
}
export function removeWord(list: Obj, id: string, word: string): boolean {
  if (!isObj(list) || !own(list, id)) return false;
  const raw = list[id];
  if (Array.isArray(raw)) {
    const i = raw.indexOf(word, 1);
    if (i < 1) return false;
    raw.splice(i, 1);
    return true;
  }
  if (isObj(raw) && Array.isArray(raw.spellings)) {
    const i = raw.spellings.indexOf(word);
    if (i < 0) return false;
    raw.spellings.splice(i, 1);
    return true;
  }
  return false;
}

/* the order of the questions as given, where it names the same coordinates as before, each once */
export function setOrder(data: Obj, order: string[]): boolean {
  const was = orderOf(data);
  if (order.length !== was.length || new Set(order).size !== order.length || order.some(n => !was.includes(n))) return false;
  data.coordinates.order = order.slice();
  return true;
}
/* a coordinate marked or no longer marked with one of the three lists; read only where the value stands and read once
   with the number exclude each other */
export function setSpecial(data: Obj, name: string, key: Special, on: boolean): boolean {
  if (!orderOf(data).includes(name)) return false;
  const c = data.coordinates;
  const list: string[] = Array.isArray(c[key]) ? c[key] : [];
  if (on) {
    if (list.includes(name)) return false;
    const other = key === 'own_passage' ? 'own_value' : key === 'own_value' ? 'own_passage' : null;
    if (other && Array.isArray(c[other])) { c[other] = c[other].filter((n: string) => n !== name); if (!c[other].length) delete c[other]; }
    c[key] = list.concat([name]).sort((a, b) => orderOf(data).indexOf(a) - orderOf(data).indexOf(b));
    return true;
  }
  if (!list.includes(name)) return false;
  c[key] = list.filter(n => n !== name);
  if (!c[key].length) delete c[key];
  return true;
}

/* the spec as every field asks it, each shared dimension written into the fields that ask it: what the run reads */
export function expanded(data: Obj): Obj {
  const out = clone(data);
  const shared = isObj(out.shared_axes) ? out.shared_axes : {};
  delete out.shared_axes;
  for (const p of fieldsOf(out)) {
    if (!isObj(p.axes)) continue;
    const axes: Obj = {};
    for (const [n, a] of Object.entries(p.axes)) axes[n] = a === SHARED && isObj(shared[n]) ? clone(shared[n]) : a;
    p.axes = axes;
  }
  return out;
}

/* ---------- where the entries of a list come from ---------- */

/* a list of the ontology as the profile's sources name it: its root, and the terms the snapshot carries under it */
export interface OntoSet { root: string; kind: string | null; label: string | null; definition: string | null; members: string[] }
/* a term of the snapshot under one of those lists: its name, definition and the terms it stands under */
export interface OntoTerm {
  id: string; label: string | null; definition: string | null; alt_labels: string[]; deprecated: boolean; parents: string[];
}
/* the lists of the sources, which dimension the sources say draws from which of them, and the terms under them */
export interface Onto { sets: Record<string, OntoSet>; axis_sets: Record<string, string>; terms?: Record<string, OntoTerm> }
/* the key of an entry as the ontology names it: the last part of an IRI, else the key itself */
export const termOf = (id: string): string => { const m = /[/#]([^/#]+)$/.exec(id); return m ? m[1] : id; };
/* where a list takes its entries from: the list of the ontology (named by the sources for its dimension, or else the one
   that holds most of its entries), its entries under that root, and its own entries */
export interface Origin { set: string; said: boolean; root: OntoSet; under: string[]; own: string[] }
export function originOf(list: unknown, name: string | null, onto: Onto | undefined): Origin | null {
  if (!onto || !isObj(list)) return null;
  const ids = Object.keys(list);
  const named = name != null ? onto.axis_sets[name] : undefined;
  let set = named && onto.sets[named] ? named : '';
  if (!set) {
    let best = 0;
    for (const [n, s] of Object.entries(onto.sets)) {
      const members = new Set(s.members);
      const held = ids.filter(id => members.has(termOf(id))).length;
      if (held > best || (held === best && held > 0 && s.members.length < onto.sets[set].members.length)) { best = held; set = n; }
    }
    if (!best) return null;
  }
  const root = onto.sets[set];
  const members = new Set(root.members);
  return {
    set, said: !!named && set === named, root,
    under: ids.filter(id => members.has(termOf(id))),
    own: ids.filter(id => !members.has(termOf(id))),
  };
}
