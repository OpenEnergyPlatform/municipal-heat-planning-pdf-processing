/* The state of the Prompts tab and everything that changes it. The state lives here, not in a component: unsaved text
   is kept per prompt id and per module for as long as
   the page is open, and the tab keeps working when another tab is shown. Components read it after `useStore(tick)`. */
import { api, apiR } from '../lib/api';
import { askConfirm, showError } from '../lib/dialogs';
import { t } from '../lib/i18n';
import { clone } from '../lib/util';
import { loadState, Store } from '../lib/nav';
import { type Ed, type Ph, type X, type ShownCell, type Cut, bodyFromCut, edDirty, isDirty, makeEd, makePh, phDirty, rawOf, stampOf } from './logic';

export type Sel = { t: 'prompt'; id: string } | { t: 'phrases'; module: string };
export interface Req {
  prompt: string; trace: string; kind: string; field: string; carries: string; text: string; offset: number;
  listing: any; listErr: string | null; listLoading: boolean; opts: { kinds: string[]; fields: string[]; carried: string[] } | null;
  sel: number | null; pv: any; pvErr: string | null; pvLoading: boolean; pvEdited: boolean; showSent: boolean; sysOpen: boolean;
}
export interface TryCell { running?: boolean; n: number; res?: any; err?: string }

export const P = {
  loaded: false, loading: false, loadErr: null as string | null, list: null as any, sel: null as Sel | null, selErr: null as string | null,
  filter: '', eds: new Map<string, Ed>(), phs: new Map<string, Ph>(), trace: null as string | null,
  req: null as Req | null, tryRes: null as TryCell | null, pvSeq: 0, rqSeq: 0,
  pvTimer: undefined as ReturnType<typeof setTimeout> | undefined, rqTimer: undefined as ReturnType<typeof setTimeout> | undefined,
};

export const tick = new Store<number>(0);
export const bump = () => tick.set(tick.get() + 1);

export function promptsDirty(): boolean {
  for (const E of P.eds.values()) if (edDirty(E)) return true;
  for (const X of P.phs.values()) if (phDirty(X)) return true;
  return false;
}
/* the text of every prompt with unsaved changes, in the order the prompts were first opened */
export function editsMap(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [id, E] of P.eds) if (edDirty(E)) out[id] = rawOf(E);
  return out;
}
export function currentX(): X | null {
  if (!P.sel) return null;
  return P.sel.t === 'prompt' ? P.eds.get(P.sel.id) || null : P.phs.get(P.sel.module) || null;
}
export function kindsOf(id: string): string[] { const p = ((P.list && P.list.prompts) || []).find((x: any) => x.id === id); return p ? (p.kinds || []) : []; }

/* ---------- load and select ---------- */

export async function loadPrompts() {
  if (P.loading || P.loaded) return;
  P.loading = true; P.loadErr = null; bump();
  try {
    P.list = await api('GET', '/api/prompts');
    P.loaded = true;
    const logs = P.list.traces || [];
    if (!P.trace || !logs.some((l: any) => l.name === P.trace)) P.trace = logs.length ? logs[0].name : null;
  } catch (e) {
    P.loadErr = (e as Error).message;
  }
  P.loading = false;
  bump();
}

export async function selectPrompt(id: string) {
  P.sel = { t: 'prompt', id }; P.selErr = null;
  resetRequests(); bump();
  const mine = () => !!P.sel && P.sel.t === 'prompt' && P.sel.id === id;
  if (!P.eds.has(id)) {
    try {
      const d = await api('GET', '/api/prompt?id=' + encodeURIComponent(id));
      if (!P.eds.has(id)) P.eds.set(id, makeEd(d));
    } catch (e) {
      if (mine()) { P.selErr = (e as Error).message; bump(); }
      return;
    }
  }
  if (!mine()) return;
  resetRequests(); bump();
  startRequests();
}
export async function selectModule(m: string) {
  P.sel = { t: 'phrases', module: m }; P.selErr = null;
  resetRequests(); bump();
  const mine = () => !!P.sel && P.sel.t === 'phrases' && P.sel.module === m;
  if (!P.phs.has(m)) {
    try {
      const d = await api('GET', '/api/phrases?module=' + encodeURIComponent(m));
      if (!P.phs.has(m)) P.phs.set(m, makePh(d));
    } catch (e) {
      if (mine()) { P.selErr = (e as Error).message; bump(); }
      return;
    }
  }
  if (!mine()) return;
  bump();
}

export function setTrace(name: string) {
  P.trace = name;
  for (const x of P.phs.values()) x.shown = {};
  if (P.sel && P.sel.t === 'prompt') { resetRequests(); bump(); startRequests(); }
  else bump();
}

/* ---------- edits ---------- */

export function edited(x: X) {
  bump();
  if (x.kind === 'prompt') schedulePreview();
}

/* ---------- check, save, discard, review ---------- */

const urlOf = (x: X) => x.kind === 'prompt' ? '/api/prompt/' : '/api/phrases/';
const bodyOf = (x: X): Record<string, any> => x.kind === 'prompt' ? { id: x.id, raw: rawOf(x) } : { module: x.module, table: x.table };

export async function actCheck(x: X | null) {
  if (!x || x.busy) return;
  const stamp = stampOf(x);
  x.busy = true; bump();
  try { x.rep = { source: 'check', r: await apiR(urlOf(x) + 'check', bodyOf(x)), stamp }; }
  catch (e) { x.rep = { source: 'check', error: (e as Error).message, stamp }; }
  x.busy = false; bump();
}
export async function actSave(x: X | null, confirm = false) {
  if (!x || x.busy) return;
  const stamp = stampOf(x);
  const body = Object.assign(bodyOf(x), { base: x.detail.sha256 == null ? null : x.detail.sha256 });
  if (x.kind === 'phrases') body.confirm = !!confirm;
  x.busy = true; x.review = null; bump();
  let saved = false;
  try {
    const r = await apiR(urlOf(x) + 'save', body);
    x.rep = { source: 'save', r, stamp };
    if (r.saved) { saved = true; await afterSaved(x, stamp); }
  } catch (e) { x.rep = { source: 'save', error: (e as Error).message, stamp }; }
  x.busy = false; bump();
  if (saved) { loadState().catch(showError); runReview(x); }
}
/* the file on disk is the new base; the text in the editor is kept when it was changed again meanwhile */
async function afterSaved(x: X, stamp: string) {
  try {
    if (x.kind === 'prompt') {
      adoptPrompt(x, await api('GET', '/api/prompt?id=' + encodeURIComponent(x.id)), stamp);
      const l = await api('GET', '/api/prompts');
      if (P.list && Array.isArray(l.prompts)) P.list.prompts = l.prompts;
    } else {
      adoptPhrases(x, await api('GET', '/api/phrases?module=' + encodeURIComponent(x.module)), stamp);
    }
  } catch (e) { showError(e); }
  bump();
}
/* stamp null: take the text of the file whatever the editor holds */
function adoptPrompt(E: Ed, d: any, stamp: string | null) {
  const same = stamp === null || stampOf(E) === stamp;
  E.detail = d;
  if (same) {
    E.cut = clone(d.cut) as Cut; E.cut.parts = E.cut.parts || [];
    E.single = !!d.composed || !E.cut.parts.length; E.body = bodyFromCut(E.cut);
  }
}
function adoptPhrases(x: Ph, d: any, stamp: string | null) {
  const same = stamp === null || stampOf(x) === stamp;
  x.detail = d; x.origJson = JSON.stringify(d.table || {});
  if (same) x.table = clone(d.table || {});
}
export async function actDiscard(x: X | null) {
  if (!x) return;
  const what = x.kind === 'prompt' ? x.id : t('the text blocks of {module}', { module: x.module });
  if (!await askConfirm(t('Discard changes'), t('Discard the changes to {what}?', { what }), t('Discard'))) return;
  if (x.kind === 'prompt') { x.cut = clone(x.detail.cut); x.cut.parts = x.cut.parts || []; x.body = bodyFromCut(x.cut); }
  else x.table = clone(x.detail.table || {});
  x.rep = null; x.review = null;
  bump();
  if (x.kind === 'prompt') schedulePreview();
}
export async function reloadFromDisk(x: X) {
  if (isDirty(x) && !await askConfirm(t('Reload from disk'), t('The file changed on disk. Reloading drops the changes in the editor.'), t('Drop my changes and reload'))) return;
  try {
    if (x.kind === 'prompt') adoptPrompt(x, await api('GET', '/api/prompt?id=' + encodeURIComponent(x.id)), null);
    else adoptPhrases(x, await api('GET', '/api/phrases?module=' + encodeURIComponent(x.module)), null);
  } catch (e) { showError(e); return; }
  x.rep = null; x.review = null;
  bump();
  if (x.kind === 'prompt') schedulePreview();
}
async function runReview(x: X) {
  x.review = { running: true }; bump();
  try { x.review = { res: await apiR('/api/review', {}) }; }
  catch (e) { x.review = { err: (e as Error).message }; }
  bump();
}

/* ---------- the text blocks a request log shows ---------- */

export async function fetchShown(x: Ph, key: string, text: string) {
  const cell: ShownCell = { loading: true, trace: P.trace, text };
  x.shown[key] = cell; bump();
  try { cell.res = await apiR('/api/phrases/shown', { module: x.module, key, text, trace: P.trace }); }
  catch (e) { cell.err = (e as Error).message; }
  cell.loading = false;
  if (x.shown[key] === cell) bump();
}

/* ---------- recorded requests ---------- */

export function resetRequests() {
  clearTimeout(P.pvTimer); clearTimeout(P.rqTimer);
  P.pvSeq++; P.rqSeq++;
  P.req = null; P.tryRes = null;
  if (P.sel && P.sel.t === 'prompt' && P.trace && kindsOf(P.sel.id).length) {
    P.req = { prompt: P.sel.id, trace: P.trace, kind: '', field: '', carries: '', text: '', offset: 0, listing: null, listErr: null, listLoading: false,
      opts: null, sel: null, pv: null, pvErr: null, pvLoading: false, pvEdited: false, showSent: false, sysOpen: false };
  }
}
export function startRequests() { if (P.req) fetchRequests(); }

export async function fetchRequests() {
  const R = P.req;
  if (!R) return;
  const my = ++P.rqSeq;
  R.listLoading = true; R.listErr = null; bump();
  const q = new URLSearchParams({ trace: R.trace, prompt: R.prompt, kind: R.kind, field: R.field, carries: R.carries, text: R.text, offset: String(R.offset), limit: '100' });
  try {
    const a = await api('GET', '/api/requests?' + q.toString());
    if (my !== P.rqSeq || P.req !== R) return;
    R.listing = a;
    R.opts = { kinds: a.kinds || [], fields: a.fields || [], carried: a.carried || [] };
    R.listLoading = false;
  } catch (e) {
    if (my !== P.rqSeq || P.req !== R) return;
    R.listErr = (e as Error).message; R.listLoading = false;
  }
  bump();
}
export function setFilter(k: 'kind' | 'field' | 'carries', v: string) {
  const R = P.req; if (!R) return;
  R[k] = v; R.offset = 0; fetchRequests();
}
export function setText(v: string) {
  const R = P.req; if (!R) return;
  R.text = v; R.offset = 0; bump();
  clearTimeout(P.rqTimer); P.rqTimer = setTimeout(fetchRequests, 350);
}
export function page(offset: number) { const R = P.req; if (!R) return; R.offset = offset; fetchRequests(); }

export function selectRequest(index: number) {
  const R = P.req;
  if (!R) return;
  R.sel = index; R.pv = null; R.pvErr = null;
  clearTimeout(P.pvTimer);
  bump();
  doPreview();
}
export function schedulePreview() {
  clearTimeout(P.pvTimer);
  if (!P.req || P.req.sel == null) return;
  P.pvTimer = setTimeout(doPreview, 400);
}
async function doPreview() {
  const R = P.req;
  if (!R || R.sel == null) return;
  const my = ++P.pvSeq;
  const edits = editsMap();
  R.pvLoading = true; bump();
  try {
    const a = await apiR('/api/request/preview', { trace: R.trace, index: R.sel, edits });
    if (my !== P.pvSeq || P.req !== R) return;
    R.pv = a; R.pvErr = null; R.pvEdited = Object.keys(edits).length > 0;
  } catch (e) {
    if (my !== P.pvSeq || P.req !== R) return;
    R.pvErr = (e as Error).message;
  }
  R.pvLoading = false;
  bump();
}

/* Try: the only place that sends anything to a model, one click each */
export async function doTry(indexes: number[]) {
  const R = P.req;
  if (!R || !indexes.length) return;
  const T = (P.list && P.list.try) || {};
  if (!T.configured || (P.tryRes && P.tryRes.running)) return;
  const cell: TryCell = { running: true, n: indexes.length };
  P.tryRes = cell; bump();
  try { cell.res = await apiR('/api/request/try', { trace: R.trace, indexes, edits: editsMap() }); }
  catch (e) { cell.err = (e as Error).message; }
  cell.running = false;
  if (P.tryRes === cell && P.req === R) bump();
}
