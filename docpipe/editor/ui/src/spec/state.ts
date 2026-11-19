/* The state of the Spec tab and what changes it. The spec object is the one the server sent: it is changed in place by the
   widgets and sent back whole. The left column chooses what the middle shows (`S.view`: a field as a drawing, a shared
   dimension as a dictionary, the order of the questions, the fields of the whole document, the value types, the questions
   of the spec); the right column edits what is selected (`S.sel`). `view` redraws the page, `meta` the toolbar and the
   result, so typing in a form does not draw everything again. Every edit is a step Ctrl+Z takes back. */
import { askConfirm, askText, showError, showInfo } from '../lib/dialogs';
import { t, tn } from '../lib/i18n';
import { errText, get, post } from '../lib/api';
import { loadState, setDirty, Store } from '../lib/nav';
import { clone, isObj, own, type Obj } from '../lib/util';
import type { Moved } from '../lib/moved';
import { locate, type Flag, type Note, type SpecNode } from '../lib/spec';
import {
  addWord, axisOf, fieldOf, giveOwn, giveShared, moveWord, removeWord, setOrder, setSpecial, share, sharedOf, unshare,
  usersOf, type Onto, type Special,
} from './model';
import { nameOf } from './names';
import { withTerms, type ListWhere } from './terms';

export interface Result { source: 'check' | 'save'; r: any }

/* what the middle of the tab shows */
export type View =
  | { t: 'field'; uri: string } | { t: 'shared'; name: string } | { t: 'order' } | { t: 'plan' } | { t: 'types' }
  | { t: 'spec' };

export const S = {
  loaded: false, data: {} as Obj, orig: {} as Obj, base: '', form: {} as Obj, pin: {} as Obj, notes: [] as Note[],
  onto: { sets: {}, axis_sets: {}, terms: {} } as Onto,
  view: { t: 'spec' } as View, sel: { t: 'spec' } as SpecNode, dirty: false, result: null as Result | null, stale: false,
  generate: null as any, busy: false, panelOpen: true, flag: null as Flag | null, rev: 0, resetScroll: false,
  library: {} as Library,
  /* a profile with only a draft of its spec: what the draft still lacks before the strict check takes it */
  draft: false, missing: [] as string[],
  /* the spec as it was loaded, as JSON: an edit that comes back to it leaves nothing to save */
  origText: '',
  /* the dimension whose entries a field's drawing shows; whether it shows the entries without a word of the plans too */
  pick: {} as Record<string, string>, open: false,
  /* the list open wide over the page */
  list: null as { uri: string; coordinate: string | null; key: string; entry: string | null } | null,
  /* the order of the left column of a field's drawing after untangling, until the page is loaded again */
  kept: {} as Record<string, string[]>,
  /* the boxes of a field's drawing moved by hand, by field, until the page is loaded again or the arrows are untangled */
  moved: {} as Record<string, Moved>,
  /* a count the drawing shows the whole drawing on */
  fit: 0,
};
/* the steps Ctrl+Z and Ctrl+Y go: the spec as JSON before each edit, and after it */
export const H = { undo: [] as string[], redo: [] as string[], snap: '', lastAt: 0, lastSel: '' };

/* what the server knows of what can be put in: the value types with their settings and the field each puts in, the kinds
   of a dimension, a unit, a check, a value type of one's own, and what a condition of a check and of a derived dimension
   is about */
export interface TypeInfo { name: string; settings: Obj; builtin: boolean; field: Obj }
export interface Library {
  types?: TypeInfo[]; dimensions?: Record<string, Obj>; unit?: Obj; check?: Obj; value_type?: Obj;
  conditions?: any[]; reading?: any[];
}

export const view = new Store(0);
export const meta = new Store(0);
export const touch = () => { view.set(view.get() + 1); meta.set(meta.get() + 1); };
const bumpMeta = () => meta.set(meta.get() + 1);

export const findParam = (data: Obj, uri: string) => ((data && data.parameters) || []).find((p: Obj) => p.uri === uri);
/* the object a node of the tab edits */
export function nodeObj(data: Obj, n: SpecNode): any {
  if (!data) return undefined;
  switch (n.t) {
    case 'spec': return data;
    case 'plan': return data.plan_fields && data.plan_fields[n.key];
    case 'works': return data.works;
    case 'coordinates': return isObj(data.coordinates) ? data.coordinates : undefined;
    case 'param': case 'units': case 'plist': return findParam(data, n.uri);
    case 'axis': return axisOf(data, n.uri, n.name);
    case 'shared': return sharedOf(data)[n.name];
    case 'entry': { const l = listOf(data, n); return l && own(l, n.id) ? l[n.id] : undefined; }
    case 'root': return S.onto.sets[n.set];
    case 'vtype': {
      const mine = data.value_types && data.value_types[n.name];
      if (mine) return mine;
      const built = (S.library.types || []).find(x => x.builtin && x.name === n.name);
      return built ? built.settings : undefined;
    }
  }
}
/* what holds the list an entry stands in: the field for its own list, the field's dimension, or the shared dimension */
function holderOf(data: Obj, w: { uri: string | null; name: string | null }): Obj | undefined {
  const holder = w.name == null ? (w.uri ? findParam(data, w.uri) : undefined)
    : w.uri ? axisOf(data, w.uri, w.name) : sharedOf(data)[w.name];
  return isObj(holder) ? holder : undefined;
}
/* the list an entry stands in: a field's own list, a field's dimension's, or a shared dimension's */
export function listOf(data: Obj, w: { uri: string | null; name: string | null; key: string }): Obj | undefined {
  const holder = holderOf(data, w);
  return holder && isObj(holder[w.key]) ? holder[w.key] : undefined;
}
export const nodeKey = (n: SpecNode) => JSON.stringify(n);
function viewOk(v: View): boolean {
  if (v.t === 'field') return !!fieldOf(S.data, v.uri);
  if (v.t === 'shared') return isObj(sharedOf(S.data)[v.name]);
  return true;
}
export function ensureSel() {
  if (!nodeObj(S.data, S.sel)) S.sel = S.view.t === 'field' ? { t: 'param', uri: S.view.uri } : { t: 'spec' };
  if (!viewOk(S.view)) S.view = { t: 'spec' };
  if (!nodeObj(S.data, S.sel)) S.sel = { t: 'spec' };
}
export const listCount = (l: unknown) => (isObj(l) ? Object.keys(l).length : 0);

/* an edit: a step to go back to, the spec differs from the file or not, and a result shown is about older data */
export function markDirty() {
  const now = JSON.stringify(S.data);
  remember(now);
  S.dirty = now !== S.origText;
  if (S.result) S.stale = true;
  setDirty('spec', S.dirty);
  bumpMeta();
}
/* an edit that is a step of its own, not a part of the typing before it */
export function markStep() { H.lastAt = 0; markDirty(); }
/* the typing in one form within a moment is one step */
function remember(now: string) {
  if (now === H.snap) return;
  const key = nodeKey(S.sel);
  const together = key === H.lastSel && Date.now() - H.lastAt < 1500;
  if (!together) { H.undo.push(H.snap); if (H.undo.length > 200) H.undo.shift(); H.redo = []; }
  H.snap = now; H.lastSel = key; H.lastAt = Date.now();
}
function restore(text: string) {
  S.data = JSON.parse(text); H.snap = text; H.lastAt = 0;
  S.dirty = text !== S.origText; setDirty('spec', S.dirty);
  if (S.result) S.stale = true;
  ensureSel();
  S.rev++; touch();
}
export function undo() { if (!H.undo.length) return; H.redo.push(H.snap); restore(H.undo.pop()!); }
export function redo() { if (!H.redo.length) return; H.undo.push(H.snap); restore(H.redo.pop()!); }
export async function discard() {
  if (!S.dirty || S.busy) return;
  if (!await askConfirm(t('Discard changes'), t('Discard the edited spec? Ctrl+Z brings it back.'), t('Discard'))) return;
  H.undo.push(H.snap); H.redo = [];
  restore(S.origText);
  S.fit++; touch();
}

/* the middle shows *v*; the right column what goes with it */
export function show(v: View) {
  S.view = v;
  S.sel = v.t === 'field' ? { t: 'param', uri: v.uri } : v.t === 'shared' ? { t: 'shared', name: v.name }
    : v.t === 'order' ? (isObj(S.data.coordinates) ? { t: 'coordinates' } : { t: 'spec' }) : v.t === 'plan' ? planSel() : { t: 'spec' };
  S.flag = null; S.list = null; S.open = false;
  S.rev++; S.resetScroll = true; S.fit++;
  touch();
}
function planSel(): SpecNode {
  const keys = isObj(S.data.plan_fields) ? Object.keys(S.data.plan_fields) : [];
  return keys.length ? { t: 'plan', key: keys[0] } : isObj(S.data.works) ? { t: 'works' } : { t: 'spec' };
}
/* the right column edits *n* */
export function select(n: SpecNode, flag?: Flag | null) {
  S.sel = n;
  S.flag = flag || null;
  S.rev++; S.resetScroll = true;
  touch();
}
/* the dimension whose entries a field's drawing shows */
export function pickList(uri: string, name: string) { S.pick[uri] = name; S.open = false; touch(); }
export function toggleOpen() { S.open = !S.open; touch(); }
/* a node chosen from another tab or from a problem: the middle shows where it stands, the right column edits it */
export function reveal(n: SpecNode, flag?: Flag | null) {
  if (n.t === 'param' || n.t === 'units' || n.t === 'plist') S.view = { t: 'field', uri: n.uri };
  else if (n.t === 'axis') { S.view = { t: 'field', uri: n.uri }; S.pick[n.uri] = n.name; }
  else if (n.t === 'shared') S.view = { t: 'shared', name: n.name };
  else if (n.t === 'coordinates') S.view = { t: 'order' };
  else if (n.t === 'plan' || n.t === 'works') S.view = { t: 'plan' };
  else if (n.t === 'vtype') S.view = { t: 'types' };
  else if (n.t === 'spec') S.view = { t: 'spec' };
  if (n.t === 'plist') {
    S.sel = { t: 'param', uri: n.uri };
    S.list = { uri: n.uri, coordinate: null, key: n.list, entry: (flag && flag.entry) || null };
  } else S.sel = n;
  if ((n.t === 'axis' || n.t === 'shared') && flag && (flag.field === 'vocabulary' || flag.field === 'beside') && flag.entry) {
    const uri = n.t === 'axis' ? n.uri : usersOf(S.data, n.name)[0];
    if (uri) S.list = { uri, coordinate: n.name, key: flag.field, entry: flag.entry };
  }
  S.flag = flag || null;
  S.rev++; S.resetScroll = true; S.fit++;
  touch();
}
export function openList(uri: string, coordinate: string | null, key: string) { S.list = { uri, coordinate, key, entry: null }; touch(); }
export function closeList() { S.list = null; touch(); }
/* the form is drawn again from the data (after the data object was replaced) */
export function structural() { S.rev++; touch(); }

export async function run(fn: () => Promise<void>) {
  if (S.busy) return;
  S.busy = true; touch();
  try { await fn(); } catch (e) { showError(e); }
  S.busy = false; touch();
}
const commitFocus = () => { const a = document.activeElement as HTMLElement | null; if (a && a !== document.body && a.blur) a.blur(); };

export async function loadAll() {
  const [, spec] = await Promise.all([loadState(), get('/api/spec')]);
  S.data = spec.data; S.orig = clone(spec.data); S.base = spec.base; S.origText = JSON.stringify(spec.data);
  H.undo = []; H.redo = []; H.snap = S.origText; H.lastAt = 0;
  S.list = null; S.fit++;
  S.form = spec.form || {}; S.pin = spec.pin || {}; S.notes = spec.notes || [];
  S.onto = spec.ontology || { sets: {}, axis_sets: {}, terms: {} };
  S.library = spec.library || {};
  S.draft = !!spec.draft; S.missing = spec.missing || [];
  S.dirty = false; S.result = null; S.stale = false; S.generate = null; S.flag = null; S.loaded = true;
  setDirty('spec', false);
  const first = (S.data.parameters || [])[0];
  if (S.view.t === 'spec' && first && first.uri) { S.view = { t: 'field', uri: first.uri }; S.sel = { t: 'param', uri: first.uri }; }
  ensureSel(); S.rev++; touch();
}
export async function reload() {
  if (S.dirty && !await askConfirm(t('Reload from disk'), t('There are unsaved edits. Reloading discards them.'), t('Discard and reload'))) return;
  await run(loadAll);
}

export async function doCheck() {
  commitFocus();
  await run(async () => {
    const r = await post('/api/spec/check', { data: S.data });
    S.result = { source: 'check', r }; S.stale = false; S.generate = null;
    if (r.notes) S.notes = r.notes;
    S.panelOpen = true;
  });
}
export async function doSave(confirm: boolean) {
  commitFocus();
  await run(async () => {
    const r = await post('/api/spec/save', { data: S.data, base: S.base, confirm: !!confirm });
    S.result = { source: 'save', r }; S.stale = false; S.generate = null;
    if (r.notes) S.notes = r.notes;
    if (r.saved) {
      S.base = r.base; S.orig = clone(S.data); S.origText = JSON.stringify(S.data); S.dirty = false;
      setDirty('spec', false);
      if (r.draft) S.missing = r.missing || [];
      try { await loadState(); } catch (e) { showError(e); }
      /* the draft lacked nothing: the spec is written, and the tab edits it from now on */
      if (r.spec_written) {
        await loadAll();
        showInfo(t('The draft lacks nothing: the spec is written to {file}.', { file: r.spec_written })
          + (r.draft_kept ? ' ' + t('The draft is kept in {folder}.', { folder: r.draft_kept }) : ''));
      }
    }
    S.panelOpen = true;
  });
}
export async function doGenerate() {
  await run(async () => {
    S.generate = await post('/api/generate', {});
    try { await loadState(); } catch (e) { showError(e); }
  });
}
export function goToError(err: { where?: string }) {
  const loc = locate(err.where || '', S.data);
  reveal(loc.node, { field: loc.field, entry: loc.entry });
}

/* ---------- structural edits through the server ---------- */

/* a removal the server makes: an entry or a spelling of a list */
export async function removeOnServer(body: Obj, what: string) {
  await run(async () => {
    const r = await post('/api/spec/remove', Object.assign({ data: S.data }, body));
    if (!r.ok) throw new Error(errText(r.error));
    S.data = r.data; markStep();
    S.rev++;
    showInfo(t('Removed {what} here. It is written with the next confirmed save.', { what }));
  });
}

/* a copy of a field or of a field's dimension under a new key */
export async function copyNode(kind: 'field' | 'coordinate', n: { uri: string; name?: string }) {
  const key = await askText(kind === 'field' ? t('Copy as new field') : t('Copy as new dimension'), t('New key'), '');
  if (!key) return;
  await run(async () => {
    const r = await post('/api/spec/copy', { data: S.data, kind, field: n.uri, coordinate: kind === 'coordinate' ? n.name : null, key });
    if (!r.ok) throw new Error(errText(r.error));
    S.data = r.data;
    if (kind === 'field') { S.view = { t: 'field', uri: key }; S.sel = { t: 'param', uri: key }; }
    else { S.pick[n.uri] = key; S.sel = { t: 'axis', uri: n.uri, name: key }; }
    markStep();
    ensureSel(); S.rev++; S.resetScroll = true; S.fit++;
    showInfo(t('Copied. A copied field has no example: write its own before saving.'));
  });
}
/* a removal of a field, a field's dimension, a field of the whole document or the works */
export async function deleteNode(kind: 'field' | 'coordinate' | 'plan_field' | 'works', n: Obj) {
  /* named as the page names them, never by their keys */
  const fieldName = (uri: string) => (fieldOf(S.data, uri) || {}).label || uri;
  const what = kind === 'field' ? t('the field {name}', { name: fieldName(n.uri) })
    : kind === 'coordinate' ? t('the dimension {name} of {field}', { name: nameOf(n.name), field: fieldName(n.uri) })
      : kind === 'plan_field' ? t('the field of the whole document {name}', { name: ((S.data.plan_fields || {})[n.key] || {}).name || n.key })
        : t('the works');
  if (!await askConfirm(t('Delete'), t('Delete {what}?\nIt is removed here and written with the next confirmed save.', { what }), t('Delete'))) return;
  const body: Obj = { kind };
  if (kind === 'field' || kind === 'coordinate') body.field = n.uri;
  if (kind === 'coordinate') body.coordinate = n.name;
  if (kind === 'plan_field') body.key = n.key;
  await run(async () => {
    const r = await post('/api/spec/remove', Object.assign({ data: S.data }, body));
    if (!r.ok) throw new Error(errText(r.error));
    S.data = r.data;
    if (kind === 'coordinate') { S.sel = { t: 'param', uri: n.uri }; delete S.pick[n.uri]; }
    else if (kind === 'field') { S.view = { t: 'spec' }; S.sel = { t: 'spec' }; }
    else S.sel = planSel();
    markStep();
    ensureSel(); S.rev++; S.resetScroll = true; S.fit++;
    showInfo(t('Removed {what} here. It is written with the next confirmed save.', { what }));
  });
}
export function addPlanField(k: string, kind?: string) {
  if (!isObj(S.data.plan_fields)) S.data.plan_fields = {};
  S.data.plan_fields[k] = kind ? { name: '', means: '', kind } : { name: '', means: '' };
  markStep(); S.view = { t: 'plan' }; select({ t: 'plan', key: k });
}
/* a field of the whole document under a key of one's own: it says what it is (kind) */
export async function addOwnPlanField(kind: string) {
  const k = await askText(t('Add field of the whole document'), t('New key'), '');
  if (!k) return;
  if (isObj(S.data.plan_fields) && own(S.data.plan_fields, k)) { showError(new Error(t('The key {key} is taken.', { key: k }))); return; }
  addPlanField(k, kind);
}

export const typeOf = (name: string) => (S.library.types || []).find(x => x.name === name);

/* a new field of a value type, at the end */
export async function addField(typeName: string) {
  const info = typeOf(typeName);
  if (!info) return;
  const uri = await askText(t('New field'), t('New key'), '');
  if (!uri) return;
  const ps: Obj[] = S.data.parameters || (S.data.parameters = []);
  if (ps.some(p => p.uri === uri)) { showError(new Error(t('The key {key} is taken.', { key: uri }))); return; }
  const field = clone(info.field);
  field.uri = uri;
  ps.push(field);
  markStep();
  S.view = { t: 'field', uri }; S.sel = { t: 'param', uri }; S.rev++; S.fit++; touch();
  showInfo(t('A new field is empty: write its label, description and example before saving.'));
}
/* a field gets a shared dimension, or a new dimension of a kind of its own */
export async function addAxis(uri: string, what: { shared?: string; kind?: string }) {
  if (what.shared) {
    if (!giveShared(S.data, uri, what.shared)) return;
    markStep(); S.pick[uri] = what.shared; select({ t: 'axis', uri, name: what.shared }); return;
  }
  const made = (S.library.dimensions || {})[what.kind || ''];
  if (!made) return;
  const name = await askText(t('New dimension'), t('New key'), '');
  if (!name) return;
  const p = findParam(S.data, uri);
  if (p && isObj(p.axes) && own(p.axes, name)) { showError(new Error(t('The key {key} is taken.', { key: name }))); return; }
  if (!giveOwn(S.data, uri, name, made)) return;
  markStep(); S.pick[uri] = name; select({ t: 'axis', uri, name });
}
/* a new accepted unit into a field with units */
export async function addUnit(uri: string) {
  const p = findParam(S.data, uri);
  if (!p) return;
  if (!(typeOf(p.value_type || 'float')?.settings || {}).units) { showError(new Error(t('A field of this value type has no units.'))); return; }
  const unit = await askText(t('New unit'), t('The unit as the field accepts it, such as MWh/a'), '');
  if (!unit) return;
  if (!isObj(p.units_accepted)) p.units_accepted = {};
  p.units_accepted[unit] = clone(S.library.unit || { factor: 1 });
  markStep(); select({ t: 'units', uri }, { field: 'units_accepted', entry: null });
}
/* a new check of its own into a field */
export function addCheck(uri: string) {
  const p = findParam(S.data, uri);
  if (!p) return;
  if (!Array.isArray(p.checks)) p.checks = [];
  p.checks.push(clone(S.library.check || { name: '', refuse: null, sentence: '' }));
  markStep(); select({ t: 'param', uri }, { field: 'checks', entry: null });
}
/* a value type of one's own */
export async function addValueType() {
  const name = await askText(t('New value type'), t('New key'), '');
  if (!name) return;
  if (typeOf(name) || (isObj(S.data.value_types) && own(S.data.value_types, name))) { showError(new Error(t('The key {key} is taken.', { key: name }))); return; }
  if (!isObj(S.data.value_types)) S.data.value_types = {};
  S.data.value_types[name] = clone(S.library.value_type || { answer: 'number' });
  S.library.types = [...(S.library.types || []), { name, settings: S.data.value_types[name], builtin: false, field: { uri: '', label: '', description: '', value_type: name, unit_target: '', units_accepted: {}, example: { source: '', tuples: [] }, axes: {} } }];
  markStep(); S.view = { t: 'types' }; select({ t: 'vtype', name });
}
export async function removeValueType(name: string) {
  const used = (S.data.parameters || []).filter((p: Obj) => p.value_type === name).map((p: Obj) => p.uri);
  if (used.length) { showError(new Error(t('The value type {name} is the type of {fields}.', { name, fields: used.join(', ') }))); return; }
  if (!await askConfirm(t('Delete'), t('Delete {what}?\nIt is removed here and written with the next confirmed save.', { what: name }), t('Delete'))) return;
  delete S.data.value_types[name];
  if (!Object.keys(S.data.value_types).length) delete S.data.value_types;
  S.library.types = (S.library.types || []).filter(x => x.name !== name);
  markStep(); select({ t: 'spec' });
}
export function addWorks() {
  S.data.works = { name: '', means: '', fields: {} };
  markStep(); S.view = { t: 'plan' }; select({ t: 'works' });
}

/* the Sources tab's "Take": its data replaces the spec; the node selected stays where it still exists */
export function takeData(data: Obj) {
  S.data = data; S.result = null; S.stale = false; S.generate = null;
  markStep();
  ensureSel(); S.rev++; S.fit++; touch();
}

/* ---------- shared dimensions ---------- */

/* the field asks its own copy of the shared dimension from now on */
export function unshareAt(uri: string, name: string) {
  if (!unshare(S.data, uri, name)) return;
  markStep(); select({ t: 'axis', uri, name });
  showInfo(t('The field {field} has its own copy of {name} now. An edit of it reaches this field only.', { field: uri, name }));
}
/* the field's own dimension becomes the shared one of its name; one that says something else is asked first */
export async function shareAt(uri: string, name: string) {
  let said = share(S.data, uri, name);
  if (said === 'differs') {
    if (!await askConfirm(t('Share the dimension'), t('The shared dimension {name} says something else than the one of {field}. Let {field} ask the shared one and drop its own?', { name, field: uri }), t('Share'))) return;
    said = share(S.data, uri, name, true);
  }
  if (said === 'none') return;
  markStep(); select({ t: 'axis', uri, name });
}

/* ---------- the terms of a list of the ontology ---------- */

/* the list of the spec the terms of the list of the ontology selected are held against */
export function rootAt(at: ListWhere) {
  if (S.sel.t !== 'root') return;
  S.sel = { ...S.sel, at };
  touch();
}
/* terms of the list of the ontology *set* put into the list of the spec *at*, those it does not hold yet (terms.ts
   withTerms); the page knows each new entry's term at once */
export function termsPut(at: ListWhere, set: string, ids: string[]) {
  const holder = holderOf(S.data, at);
  const root = S.onto.sets[set];
  if (!holder || !root) return;
  const r = withTerms(holder[at.key], root, ids, S.onto.terms);
  if (!r.added.length) return;
  holder[at.key] = r.list;
  for (const a of r.added) if (S.onto.terms && S.onto.terms[a.id]) S.pin[a.key] = S.onto.terms[a.id];
  markStep(); S.rev++; touch();
  showInfo(tn(r.added.length, 'Put {n} term into the list here. It is written with the next confirmed save.',
    'Put {n} terms into the list here. They are written with the next confirmed save.'));
}

/* ---------- words, the order of the questions ---------- */

export function wordMoved(w: { uri: string | null; name: string | null; key: string }, from: string, word: string, to: string) {
  const l = listOf(S.data, w);
  if (!l || !moveWord(l, from, word, to)) return;
  markStep(); S.rev++; touch();
}
export function wordAdded(w: { uri: string | null; name: string | null; key: string }, id: string, word: string): boolean {
  const l = listOf(S.data, w);
  if (!l || !addWord(l, id, word)) return false;
  markStep(); S.rev++; touch();
  return true;
}
export function wordRemoved(w: { uri: string | null; name: string | null; key: string }, id: string, word: string) {
  const l = listOf(S.data, w);
  if (!l || !removeWord(l, id, word)) return;
  markStep(); S.rev++; touch();
}
export function orderSet(order: string[]) {
  if (!setOrder(S.data, order)) return;
  markStep(); S.rev++; touch();
}
export function specialSet(name: string, key: Special, on: boolean) {
  if (!setSpecial(S.data, name, key, on)) return;
  markStep(); S.rev++; touch();
}

/* the name in words of a setting of a value type (`answer`, `units`, ...), as the form names it (owner request
   2026-11-19, A5); '' where the form has none */
export function typeSettingTitle(key: string): string {
  const one = ((S.form && S.form.value_type) || []).find((f: { key: string }) => f.key === key);
  return (one && one.title) || '';
}
