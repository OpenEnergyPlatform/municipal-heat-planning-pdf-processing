/* How an edit of the Spec tab writes into the spec object. The page keeps the object the server sent and changes it in
   place, key by key, so a key no form knows stays where it is and the file keeps its order (CONTRACT, section 4). */
import { isObj, own, type Obj } from './util';

export function writeString(obj: Obj, key: string, val: unknown) {
  if (val === '' || val == null) delete obj[key]; else obj[key] = val;
}
export function writeNumber(obj: Obj, key: string, val: unknown) {
  if (val === '' || val == null || Number.isNaN(val)) delete obj[key]; else obj[key] = val;
}
/* keep: never remove the key (an enum list stays a list) */
export function writeStrings(obj: Obj, key: string, arr: string[], keep?: boolean) {
  const a = arr.filter(s => s !== '');
  if (!a.length && !keep) delete obj[key]; else obj[key] = a;
}
/* lines widget: one list element per line; an empty text removes the key */
export function writeLines(obj: Obj, key: string, text: string) {
  if (text === '') delete obj[key]; else obj[key] = text.split('\n');
}
export function linesText(v: unknown): string { return Array.isArray(v) ? v.join('\n') : (v == null ? '' : String(v)); }
/* a bool set to its default is removed only where the key was absent when the spec was loaded */
export function writeBool(obj: Obj, key: string, val: boolean, def: boolean | undefined, origObj: Obj | null | undefined) {
  const wasAbsent = !origObj || !own(origObj, key);
  if (def !== undefined && val === def && wasAbsent) delete obj[key]; else obj[key] = val;
}

export interface EntryParts { short: boolean; name: string; spellings: string[]; definition: string; gloss: string; group: string }
export function entryParts(e: unknown): EntryParts {
  if (Array.isArray(e)) return { short: true, name: e[0] == null ? '' : String(e[0]), spellings: e.slice(1), definition: '', gloss: '', group: '' };
  const o = isObj(e) ? e : {};
  return {
    short: false, name: o.label == null ? '' : String(o.label),
    spellings: Array.isArray(o.spellings) ? o.spellings : [],
    definition: typeof o.definition === 'string' ? o.definition : '',
    gloss: typeof o.gloss === 'string' ? o.gloss : '',
    group: typeof o.group === 'string' ? o.group : '',
  };
}
export function entryMatches(id: string, e: unknown, q: string): boolean {
  const words = String(q || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const p = entryParts(e);
  const hay = [id, p.name].concat(p.spellings).join('\n').toLowerCase();
  return words.every(w => hay.includes(w));
}
export function hasSpelling(list: Obj, id: string, text: string): boolean {
  const p = entryParts(list[id]);
  return p.name === text || p.spellings.includes(text);
}
/* a new spelling goes right after the name: index 1 of a short entry, index 0 of "spellings" */
export function insertSpelling(list: Obj, id: string, text: string) {
  const e = list[id];
  if (Array.isArray(e)) e.splice(1, 0, text);
  else if (Array.isArray(e.spellings)) e.spellings.unshift(text);
  else e.spellings = [text];
}
export function setEntryName(list: Obj, id: string, v: string) {
  const e = list[id];
  if (Array.isArray(e)) e[0] = v; else e.label = v;
}
/* definition, gloss, group: a short entry becomes the object form only when the user sets one */
export function setEntryField(list: Obj, id: string, key: string, val: string) {
  const e = list[id];
  if (Array.isArray(e)) {
    if (val === '') return;
    const o: Obj = { label: e[0] == null ? '' : e[0] };
    const rest = e.slice(1);
    if (rest.length) o.spellings = rest;
    o[key] = val;
    list[id] = o;
  } else writeString(e, key, val);
}
/* a new list with the entry placed after afterId (else at the end); existing values are carried over untouched */
export function listWithEntryAfter(list: Obj, afterId: string | null, id: string, entry: unknown): Obj {
  const out: Obj = {};
  let placed = false;
  for (const k of Object.keys(list)) {
    out[k] = list[k];
    if (k === afterId) { out[id] = entry; placed = true; }
  }
  if (!placed) out[id] = entry;
  return out;
}
/* an entry whose id is an IRI is shown by its last part; the whole id is its title */
export function shortId(id: string): string { const m = /^[a-z][a-z0-9+.-]*:\/\/.*[/#]([^/#]+)$/i.exec(String(id)); return m ? m[1] : String(id); }
export interface Note { where: string; id: string; kind: string; text: string }
export function notesFor(notes: Note[] | undefined, uri: string, coordinate: string | null, id: string): Note[] {
  const base = coordinate == null ? uri : uri + '.' + coordinate;
  return (notes || []).filter(n => n.id === id &&
    (n.where === base || n.where === base + '.vocabulary' || n.where === base + '.beside' || n.where === base + '.' + id));
}
export function axisKinds(axis: unknown): string[] {
  return ['vocabulary', 'type', 'enum', 'dynamic'].filter(x => own(axis, x));
}

/* what the Spec tab shows: the top-level questions, a plan field, the works, the order of the questions, a field, a
   field's units, a field's list, a dimension of a field, a shared dimension, a value type, an entry of a list (of a
   field: name null; of a shared dimension: uri null), a list of the ontology a dimension draws from (with the list of
   the spec it was opened from, which its terms are held against first) */
export type SpecNode =
  | { t: 'spec' } | { t: 'plan'; key: string } | { t: 'works' } | { t: 'coordinates' }
  | { t: 'param'; uri: string } | { t: 'units'; uri: string } | { t: 'plist'; uri: string; list: string }
  | { t: 'axis'; uri: string; name: string } | { t: 'shared'; name: string } | { t: 'vtype'; name: string }
  | { t: 'entry'; uri: string | null; name: string | null; key: string; id: string }
  | { t: 'root'; set: string; at?: { uri: string | null; name: string | null; key: string } | null };
/* the keys of a field that its units box shows, where it has units */
export const UNIT_KEYS = ['unit_target', 'units_accepted', 'integrated'];
export interface Flag { field: string | null; entry: string | null }

/* names that may contain dots are matched as prefixes, the longest first */
export function matchPrefix(names: string[], rest: string): { name: string; rest: string } | null {
  const sorted = names.slice().sort((a, b) => b.length - a.length);
  for (const n of sorted) {
    if (rest === n) return { name: n, rest: '' };
    if (rest.startsWith(n + '.')) return { name: n, rest: rest.slice(n.length + 1) };
  }
  return null;
}
function firstSeg(s: string) { const i = s.indexOf('.'); return i < 0 ? s : s.slice(0, i); }
/* the node of the tree that error.where names, the form key at its end, an entry id */
export function locate(where: string, data: Obj): { node: SpecNode; field: string | null; entry: string | null } {
  let w = String(where || '');
  if (w === 'spec') return { node: { t: 'spec' }, field: null, entry: null };
  if (w.startsWith('spec.')) w = w.slice(5);
  let m: RegExpExecArray | null;
  if ((m = /^parameters\[(\d+)\](?:\.(.*))?$/.exec(w))) {
    const param = (data.parameters || [])[+m[1]];
    if (!param) return { node: { t: 'spec' }, field: null, entry: null };
    const rest = m[2] || '';
    const entryIn = (list: unknown, r: string) => {
      if (!isObj(list)) return null;
      const f = matchPrefix(Object.keys(list), r);
      return f ? f.name : null;
    };
    if (rest === 'axes' || rest.startsWith('axes.')) {
      const r = rest === 'axes' ? '' : rest.slice(5);
      const ax = isObj(param.axes) ? matchPrefix(Object.keys(param.axes), r) : null;
      if (!ax) return { node: { t: 'param', uri: param.uri }, field: null, entry: null };
      const field = ax.rest ? firstSeg(ax.rest) : null;
      /* a dimension the field shares is fixed where the shared one stands */
      const shared = param.axes[ax.name] === 'shared';
      const held = shared ? (isObj(data.shared_axes) ? data.shared_axes[ax.name] : null) : param.axes[ax.name];
      let entry: string | null = null;
      if ((field === 'vocabulary' || field === 'beside') && ax.rest.length > field.length + 1 && isObj(held)) {
        entry = entryIn(held[field], ax.rest.slice(field.length + 1));
      }
      return { node: shared ? { t: 'shared', name: ax.name } : { t: 'axis', uri: param.uri, name: ax.name }, field, entry };
    }
    const seg = rest ? firstSeg(rest) : null;
    if (seg && UNIT_KEYS.includes(seg) && isObj(param.units_accepted)) return { node: { t: 'units', uri: param.uri }, field: seg, entry: null };
    if (seg === 'vocabulary' || seg === 'beside') {
      const entry = rest.length > seg.length + 1 ? entryIn(param[seg], rest.slice(seg.length + 1)) : null;
      return { node: { t: 'plist', uri: param.uri, list: seg }, field: seg, entry };
    }
    return { node: { t: 'param', uri: param.uri }, field: seg, entry: null };
  }
  if (w === 'plan_fields' || w.startsWith('plan_fields.')) {
    const r = w === 'plan_fields' ? '' : w.slice(12);
    const k = isObj(data.plan_fields) ? matchPrefix(Object.keys(data.plan_fields), r) : null;
    if (!k) return { node: { t: 'spec' }, field: null, entry: null };
    return { node: { t: 'plan', key: k.name }, field: k.rest ? firstSeg(k.rest) : null, entry: null };
  }
  if (w.startsWith('value_types.')) {
    const r = w.slice(12);
    const k = isObj(data.value_types) ? matchPrefix(Object.keys(data.value_types), r) : null;
    if (k) return { node: { t: 'vtype', name: k.name }, field: k.rest ? firstSeg(k.rest) : null, entry: null };
  }
  if (w === 'works' || w.startsWith('works.')) {
    const r = w === 'works' ? '' : w.slice(6);
    return { node: { t: 'works' }, field: r ? firstSeg(r) : null, entry: null };
  }
  if (w === 'coordinates' || w.startsWith('coordinates.')) {
    const r = w === 'coordinates' ? '' : w.slice(12);
    return { node: { t: 'coordinates' }, field: r ? firstSeg(r) : null, entry: null };
  }
  if (w === 'shared_axes' || w.startsWith('shared_axes.')) {
    const r = w === 'shared_axes' ? '' : w.slice(12);
    const s = isObj(data.shared_axes) ? matchPrefix(Object.keys(data.shared_axes), r) : null;
    if (!s) return { node: { t: 'spec' }, field: 'shared_axes', entry: null };
    const field = s.rest ? firstSeg(s.rest) : null;
    let entry: string | null = null;
    const held = data.shared_axes[s.name];
    if ((field === 'vocabulary' || field === 'beside') && s.rest.length > field.length + 1 && isObj(held) && isObj(held[field])) {
      const f = matchPrefix(Object.keys(held[field]), s.rest.slice(field.length + 1));
      entry = f ? f.name : null;
    }
    return { node: { t: 'shared', name: s.name }, field, entry };
  }
  return { node: { t: 'spec' }, field: firstSeg(w) || null, entry: null };
}
