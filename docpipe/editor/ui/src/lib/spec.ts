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
export function newEntryFromTerm(t: { label: string; definition?: string | null }): Obj {
  const e: Obj = { label: t.label };
  if (t.definition != null && t.definition !== '') e.definition = t.definition;
  return e;
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

/* a node of the tree: the top-level questions, a plan field, the works, a group, a field, a field's list, a coordinate */
export type SpecNode =
  | { t: 'spec' } | { t: 'plan'; key: string } | { t: 'works' } | { t: 'group'; name: string }
  | { t: 'param'; uri: string } | { t: 'plist'; uri: string; list: string } | { t: 'axis'; uri: string; name: string };
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
      let entry: string | null = null;
      if ((field === 'vocabulary' || field === 'beside') && ax.rest.length > field.length + 1) {
        entry = entryIn(param.axes[ax.name][field], ax.rest.slice(field.length + 1));
      }
      return { node: { t: 'axis', uri: param.uri, name: ax.name }, field, entry };
    }
    const seg = rest ? firstSeg(rest) : null;
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
  if (w === 'works' || w.startsWith('works.')) {
    const r = w === 'works' ? '' : w.slice(6);
    return { node: { t: 'works' }, field: r ? firstSeg(r) : null, entry: null };
  }
  if (w === 'groups' || w.startsWith('groups.')) {
    const r = w === 'groups' ? '' : w.slice(7);
    const g = isObj(data.groups) ? matchPrefix(Object.keys(data.groups), r) : null;
    if (!g) return { node: { t: 'spec' }, field: null, entry: null };
    return { node: { t: 'group', name: g.name }, field: g.rest ? firstSeg(g.rest) : null, entry: null };
  }
  return { node: { t: 'spec' }, field: firstSeg(w) || null, entry: null };
}
