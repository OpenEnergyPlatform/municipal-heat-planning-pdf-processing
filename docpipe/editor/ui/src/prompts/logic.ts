/* The pure part of the Prompts tab: what is sent back for a prompt, settings in its front matter, dirty tests, the
   difference of two wordings, the line numbers an answer names. */
import { clone } from '../lib/util';
import { t } from '../lib/i18n';

export interface Part { mark: string; kind: string; keys: string[]; text: string }
export interface Cut { front: string; common: string; parts: Part[] }
export interface Rep { source: 'check' | 'save'; r?: any; error?: string; stamp: string }
export interface Review { running?: boolean; res?: any; err?: string }
export interface ShownCell { loading?: boolean; trace: string | null; text: string; res?: any; err?: string; all?: boolean }

export interface Ed {
  kind: 'prompt'; id: string; detail: any; cut: Cut; single: boolean; body: string;
  rep: Rep | null; review: Review | null; busy: boolean;
}
export interface Ph {
  kind: 'phrases'; module: string; detail: any; table: Record<string, any>; origJson: string;
  rep: Rep | null; review: Review | null; busy: boolean; shown: Record<string, ShownCell>;
}
export type X = Ed | Ph;

/* The run reads a marker only on a line of its own. So the text before a marker ends its line, and a marker ends its
   line before its text: what is typed at the end of one box must not run into the marker of the next. */
export const lineEnded = (s: string) => (s === '' || s.endsWith('\n')) ? s : s + '\n';

/* the one function that builds the text sent back for a prompt */
export function rawOf(E: Ed): string {
  if (E.single) return E.cut.front + E.body;
  const parts = E.cut.parts;
  let out = E.cut.front + (parts.length ? lineEnded(E.cut.common) : E.cut.common);
  parts.forEach((p, i) => {
    out += (p.text === '' ? p.mark : lineEnded(p.mark)) + (i < parts.length - 1 ? lineEnded(p.text) : p.text);
  });
  return out;
}
export const edDirty = (E: Ed) => rawOf(E) !== E.detail.raw;
export const phDirty = (X: Ph) => JSON.stringify(X.table) !== X.origJson;
export const isDirty = (X: X) => X.kind === 'prompt' ? edDirty(X) : phDirty(X);
export const stampOf = (X: X) => X.kind === 'prompt' ? rawOf(X) : JSON.stringify(X.table);

/* settings in the front matter: only the value after the key is replaced, every other character stays */
export const settingRe = (key: string) => new RegExp('^(' + key + ':)([^\r\n]*)', 'm');
export function settingRest(front: string, key: string): string | null { const m = settingRe(key).exec(front); return m ? m[2] : null; }
export function withSetting(front: string, key: string, lead: string, v: string): string {
  return front.replace(settingRe(key), (_all, a) => a + lead + v);
}

export const bodyFromCut = (cut: Cut) => cut.common + (cut.parts || []).map(p => p.mark + p.text).join('');
export function makeEd(d: any): Ed {
  const cut: Cut = clone(d.cut);
  cut.parts = cut.parts || [];
  const single = !!d.composed || !cut.parts.length;
  return { kind: 'prompt', id: d.id, detail: d, cut, single, body: bodyFromCut(cut), rep: null, review: null, busy: false };
}
export function makePh(d: any): Ph {
  return { kind: 'phrases', module: d.module, detail: d, table: clone(d.table || {}), origJson: JSON.stringify(d.table || {}), rep: null, review: null, busy: false, shown: {} };
}

export const textOf = (v: unknown): string => Array.isArray(v) ? v.join(' / ') : (v == null ? '' : String(v));
export const inheritedOf = (s: any) => s.inherited != null ? s.inherited : s.text;
export const stageOrder = (a: string, b: string) => (a === 'extraction' ? 0 : 1) - (b === 'extraction' ? 0 : 1) || a.localeCompare(b);

/* the common start and end of two wordings are kept, the middle is what differs */
export function diffSegs(a: unknown, b: unknown) {
  const x = a == null ? '' : String(a), y = b == null ? '' : String(b);
  const m = Math.min(x.length, y.length);
  let i = 0;
  while (i < m && x[i] === y[i]) i++;
  let j = 0;
  while (j < m - i && x[x.length - 1 - j] === y[y.length - 1 - j]) j++;
  return {
    a: [x.slice(0, i), x.slice(i, x.length - j), x.slice(x.length - j)] as [string, string, string],
    b: [y.slice(0, i), y.slice(i, y.length - j), y.slice(y.length - j)] as [string, string, string],
  };
}

export const reqLabel = (r: any) => [r.kind, r.parameter, r.coordinate].filter(Boolean).join(' · ') + (r.asked ? ' ' + t('(asks again: {asked})', { asked: r.asked }) : '');
export function reqSub(r: any): string {
  const a: string[] = [];
  if (r.owner != null) a.push(t('section, table or figure {owner}', { owner: String(r.owner) }));
  if (r.value != null) a.push(r.at ? t('value {value}, line {at}', { value: String(r.value), at: String(r.at) }) : t('value {value}', { value: String(r.value) }));
  if (r.ms != null) a.push(t('{n} ms', { n: Math.round(r.ms) }));
  a.push(t('{prompt}/{completion} tokens', { prompt: r.prompt_tokens == null ? '?' : r.prompt_tokens, completion: r.completion_tokens == null ? '?' : r.completion_tokens }));
  if (r.attempt > 1) a.push(t('attempt {n}', { n: r.attempt }));
  return a.join(' · ');
}

/* the lines an answer's line numbers name ("19.2", "A3-A5") */
export function addrs(a: unknown): Set<string> {
  const out: string[] = [];
  const add = (x: unknown) => {
    if (x === undefined || x === null) return;
    const m = String(x).match(/^([A-Za-z]*)(\d+)(?:\.\d+)?(?:-([A-Za-z]*)(\d+)(?:\.\d+)?)?$/);
    if (!m) return;
    const lo = +m[2], hi = m[4] ? +m[4] : lo;
    for (let n = lo; n <= Math.min(hi, lo + 500); n++) out.push(m[1] + n);
  };
  const walk = (o: any) => {
    if (Array.isArray(o)) o.forEach(walk);
    else if (o && typeof o === 'object') { if ('at' in o) add(o.at); Object.values(o).forEach(v => { if (typeof v === 'object') walk(v); }); }
  };
  walk(a);
  return new Set(out);
}
export function lineKey(s: unknown): string | null { const m = String(s).match(/^\s*([A-Za-z]*\d+)\b/); return m ? m[1] : null; }

export function prettyAnswer(a: any): string {
  if (a && a.answer_json) {
    let out = JSON.stringify(a.answer_json, null, 2);
    if (Array.isArray(a.spelled) && a.spelled.length) out += '\n= ' + a.spelled.join('; ');
    return out;
  }
  return a && a.answer != null ? String(a.answer) : '';
}
