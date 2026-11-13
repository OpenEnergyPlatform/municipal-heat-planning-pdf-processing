/* The state of the Spec tab and what changes it. The spec object is the one the server sent: it is changed in place by the
   widgets and sent back whole. `view` redraws the tree and the form, `meta` only the toolbar and the
   result, so an edit does not draw the whole form again. */
import { askConfirm, askText, showError, showInfo } from '../lib/dialogs';
import { t } from '../lib/i18n';
import { errText, get, post } from '../lib/api';
import { loadState, setDirty, Store } from '../lib/nav';
import { clone, isObj, type Obj } from '../lib/util';
import { locate, type Flag, type Note, type SpecNode } from '../lib/spec';

export interface Result { source: 'check' | 'save'; r: any }

export const S = {
  loaded: false, data: {} as Obj, orig: {} as Obj, base: '', form: {} as Obj, pin: {} as Obj, notes: [] as Note[],
  sel: { t: 'spec' } as SpecNode, dirty: false, expanded: new Set<string>(), result: null as Result | null, stale: false,
  generate: null as any, busy: false, panelOpen: true, flag: null as Flag | null, rev: 0, resetScroll: false,
};

export const view = new Store(0);
export const meta = new Store(0);
export const touch = () => { view.set(view.get() + 1); meta.set(meta.get() + 1); };
const bumpMeta = () => meta.set(meta.get() + 1);

export const findParam = (data: Obj, uri: string) => ((data && data.parameters) || []).find((p: Obj) => p.uri === uri);
export function nodeObj(data: Obj, n: SpecNode): any {
  if (!data) return undefined;
  switch (n.t) {
    case 'spec': return data;
    case 'plan': return data.plan_fields && data.plan_fields[n.key];
    case 'works': return data.works;
    case 'group': return data.groups && data.groups[n.name];
    case 'param': return findParam(data, n.uri);
    case 'plist': return findParam(data, n.uri);
    case 'axis': { const p = findParam(data, n.uri); return p && p.axes && p.axes[n.name]; }
  }
}
export const nodeKey = (n: SpecNode) => JSON.stringify(n);
export function ensureSel() { if (!nodeObj(S.data, S.sel)) S.sel = { t: 'spec' }; }
export const listCount = (l: unknown) => (isObj(l) ? Object.keys(l).length : 0);

/* an edit: the spec differs from the file, and a result shown is about older data */
export function markDirty() {
  S.dirty = true;
  if (S.result) S.stale = true;
  setDirty('spec', true);
  bumpMeta();
}

export function select(n: SpecNode, flag?: Flag | null) {
  S.sel = n;
  S.flag = flag || null;
  if ('uri' in n) S.expanded.add(n.uri);
  S.rev++; S.resetScroll = true;
  touch();
}
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
  S.data = spec.data; S.orig = clone(spec.data); S.base = spec.base;
  S.form = spec.form || {}; S.pin = spec.pin || {}; S.notes = spec.notes || [];
  S.dirty = false; S.result = null; S.stale = false; S.generate = null; S.flag = null; S.loaded = true;
  setDirty('spec', false);
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
      S.base = r.base; S.orig = clone(S.data); S.dirty = false;
      setDirty('spec', false);
      try { await loadState(); } catch (e) { showError(e); }
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
  select(loc.node, { field: loc.field, entry: loc.entry });
}

/* ---------- structural edits through the server ---------- */

export async function removeOnServer(body: Obj, what: string) {
  await run(async () => {
    const r = await post('/api/spec/remove', Object.assign({ data: S.data }, body));
    if (!r.ok) throw new Error(errText(r.error));
    S.data = r.data; markDirty();
    S.rev++;
    showInfo(t('Removed {what} here. It is written with the next confirmed save.', { what }));
  });
}

export async function copyNode(kind: 'field' | 'coordinate', n: { uri: string; name?: string }) {
  const key = await askText(kind === 'field' ? t('Copy as new field') : t('Copy as new dimension'), t('New key'), '');
  if (!key) return;
  await run(async () => {
    const r = await post('/api/spec/copy', { data: S.data, kind, field: n.uri, coordinate: kind === 'coordinate' ? n.name : null, key });
    if (!r.ok) throw new Error(errText(r.error));
    S.data = r.data; markDirty();
    S.sel = kind === 'field' ? { t: 'param', uri: key } : { t: 'axis', uri: n.uri, name: key };
    S.expanded.add(n.uri); S.expanded.add(key);
    ensureSel(); S.rev++; S.resetScroll = true;
    showInfo(t('Copied. A copied field has no example: write its own before saving.'));
  });
}
export async function deleteNode(kind: 'field' | 'coordinate' | 'plan_field' | 'works', n: Obj) {
  const what = kind === 'field' ? t('field {uri}', { uri: n.uri })
    : kind === 'coordinate' ? t('dimension {name} of {uri}', { name: n.name, uri: n.uri })
    : kind === 'plan_field' ? t('field of the whole document {key}', { key: n.key }) : t('the works block');
  if (!await askConfirm(t('Delete'), t('Delete {what}?\nIt is removed here and written with the next confirmed save.', { what }), t('Delete'))) return;
  const body: Obj = { kind };
  if (kind === 'field') body.field = n.uri;
  if (kind === 'coordinate') { body.field = n.uri; body.coordinate = n.name; }
  if (kind === 'plan_field') body.key = n.key;
  await run(async () => {
    const r = await post('/api/spec/remove', Object.assign({ data: S.data }, body));
    if (!r.ok) throw new Error(errText(r.error));
    S.data = r.data; markDirty();
    S.sel = kind === 'coordinate' ? { t: 'param', uri: n.uri } : { t: 'spec' };
    ensureSel(); S.rev++; S.resetScroll = true;
    showInfo(t('Removed {what} here. It is written with the next confirmed save.', { what }));
  });
}
export function addPlanField(k: string) {
  if (!isObj(S.data.plan_fields)) S.data.plan_fields = {};
  S.data.plan_fields[k] = { name: '', means: '' };
  markDirty(); select({ t: 'plan', key: k });
}
export function addWorks() {
  S.data.works = { name: '', means: '', fields: {} };
  markDirty(); select({ t: 'works' });
}

/* the Sources tab's "Take": its data replaces the spec; the selected node stays where it still exists */
export function takeData(data: Obj) {
  S.data = data; S.dirty = true; S.result = null; S.stale = false; S.generate = null;
  setDirty('spec', true);
  ensureSel(); S.rev++; touch();
}
