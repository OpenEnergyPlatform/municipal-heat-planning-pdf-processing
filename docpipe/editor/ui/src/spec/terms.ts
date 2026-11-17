/* The terms a list of the ontology carries, as the Spec tab lists them beside a list of the spec that draws its entries
   from it: each under the term it stands under, whether the list holds it and under which key, and the entry a term
   becomes when it is put in. A list holds a term whatever spelling it gives it, the bare identifier or an IRI ending in
   it; a term put in is spelled as the list spells the terms of its family. No import that runs and no words of the
   page, so tests/test_editor_spec_terms.py runs it as it stands. */
import { fieldsOf, isObj, originOf, sharedOf, SHARED, termOf, type Obj, type Onto, type OntoSet, type OntoTerm } from './model';

/* where a list of the spec stands: a field's own (name null), a field's dimension's, a shared dimension's (uri null) */
export interface ListWhere { uri: string | null; name: string | null; key: string }
/* a term as the list shows it: how deep under the root it stands (0 right under it), and the key the list holds it
   under, null where it does not hold it */
export interface TermRow { id: string; term: OntoTerm | null; depth: number; held: string | null }

const IDENTIFIER = /^[A-Za-z]{2,8}_[0-9]{4,}$/;
const hasKey = (o: Obj, k: string) => Object.prototype.hasOwnProperty.call(o, k);

/* the key under which *list* holds the term *id*, in whatever spelling; null where it does not hold it */
export function heldKey(list: unknown, id: string): string | null {
  if (!isObj(list)) return null;
  if (hasKey(list, id)) return id;
  for (const k of Object.keys(list)) if (termOf(k) === id) return k;
  return null;
}

/* the key the term *id* gets in *list*: an IRI where the list writes a term of the same family (the letters before
   "_") as an IRI, with that IRI's beginning, else the bare identifier, which every list takes */
export function keyFor(list: unknown, id: string): string {
  const family = id.slice(0, id.indexOf('_') + 1);
  if (family && isObj(list)) {
    for (const k of Object.keys(list)) {
      const term = termOf(k);
      if (term !== k && IDENTIFIER.test(term) && term.startsWith(family)) return k.slice(0, k.length - term.length) + id;
    }
  }
  return id;
}

/* the entry a term becomes: the name and the definition of the ontology */
export function entryOfTerm(term: { label?: string | null; definition?: string | null } | null | undefined, id: string): Obj {
  const e: Obj = { label: (term && term.label) || id };
  if (term && term.definition) e.definition = term.definition;
  return e;
}

/* the terms of *set*, each once, under the term it stands under (a term under two of them under the one that comes
   first), the terms right under the root first; brothers by name. *list* is the list of the spec they are held
   against. */
export function termRows(set: OntoSet, terms: Record<string, OntoTerm> | undefined, list: unknown): TermRow[] {
  const known = terms || {};
  const inSet = new Set(set.members);
  const name = (id: string) => ((known[id] && known[id].label) || id).toLowerCase();
  const byName = (a: string, b: string) => name(a).localeCompare(name(b)) || (a < b ? -1 : a > b ? 1 : 0);
  const under = new Map<string, string[]>();
  const tops: string[] = [];
  for (const id of set.members) {
    const above = ((known[id] && known[id].parents) || []).filter(p => p !== id && inSet.has(p));
    if (!above.length) tops.push(id);
    for (const p of above) { const c = under.get(p); if (c) c.push(id); else under.set(p, [id]); }
  }
  const rows: TermRow[] = [];
  const seen = new Set<string>();
  const visit = (id: string, depth: number) => {
    if (seen.has(id)) return;
    seen.add(id);
    rows.push({ id, term: known[id] || null, depth, held: heldKey(list, id) });
    for (const c of (under.get(id) || []).slice().sort(byName)) visit(c, depth + 1);
  };
  for (const id of tops.sort(byName)) visit(id, 0);
  /* a term whose terms above it only reach each other in a circle */
  for (const id of set.members.slice().sort(byName)) visit(id, 0);
  return rows;
}

/* the lists of the spec that take their entries from the list of the ontology *set*: the shared dimensions', then each
   field's own list and its own dimensions' (a dimension it shares stands once, as the shared one) */
export function listsFrom(data: Obj, onto: Onto | undefined, set: string): ListWhere[] {
  const out: ListWhere[] = [];
  const from = (list: unknown, name: string | null) => { const o = originOf(list, name, onto); return !!o && o.set === set; };
  for (const [name, axis] of Object.entries(sharedOf(data))) {
    if (isObj(axis) && from(axis.vocabulary, name)) out.push({ uri: null, name, key: 'vocabulary' });
  }
  for (const p of fieldsOf(data)) {
    if (from(p.vocabulary, null)) out.push({ uri: p.uri, name: null, key: 'vocabulary' });
    for (const [name, axis] of Object.entries(isObj(p.axes) ? p.axes : {})) {
      if (axis !== SHARED && isObj(axis) && from(axis.vocabulary, name)) out.push({ uri: p.uri, name, key: 'vocabulary' });
    }
  }
  return out;
}

/* the list of *lists* the terms are held against: the one *at* names (where the panel was opened from), else the first */
export function listChosen(lists: ListWhere[], at: ListWhere | null | undefined): ListWhere | null {
  const same = (w: ListWhere) => !!at && w.uri === at.uri && w.name === at.name && w.key === at.key;
  return lists.find(same) || lists[0] || null;
}

/* *list* with the terms *ids* put in that it does not hold yet: each under the key the list spells its family with,
   with the name and definition of the ontology, after the last entry the list takes from *set*, where it takes none
   before its first answer of its own ("out:"), else at its end. Every entry it had stays as it was and where it was;
   the list given is not changed. */
export function withTerms(list: unknown, set: OntoSet, ids: string[], terms: Record<string, OntoTerm> | undefined):
  { list: Obj; added: { key: string; id: string }[] } {
  const was: Obj = isObj(list) ? list : {};
  const known = terms || {};
  const added: { key: string; id: string }[] = [];
  const fresh: [string, Obj][] = [];
  for (const id of ids) {
    if (heldKey(was, id) != null || added.some(a => a.id === id)) continue;
    const key = keyFor(was, id);
    fresh.push([key, entryOfTerm(known[id], id)]);
    added.push({ key, id });
  }
  if (!fresh.length) return { list: was, added };
  const keys = Object.keys(was);
  const members = new Set(set.members);
  let after = -1;
  for (let i = keys.length - 1; i >= 0; i--) if (members.has(termOf(keys[i]))) { after = i; break; }
  if (after < 0) { const own = keys.findIndex(k => k.startsWith('out:')); after = own < 0 ? keys.length - 1 : own - 1; }
  const out: Obj = {};
  if (after < 0) for (const [k, e] of fresh) out[k] = e;
  keys.forEach((k, i) => {
    out[k] = was[k];
    if (i === after) for (const [nk, e] of fresh) out[nk] = e;
  });
  return { list: out, added };
}
