/* Small helpers every tab uses. */
import { num, t } from './i18n';

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Obj = Record<string, any>;

export const own = (o: unknown, k: string): boolean => o != null && Object.prototype.hasOwnProperty.call(o, k);
export const isObj = (v: unknown): v is Obj => v !== null && typeof v === 'object' && !Array.isArray(v);
export const clone = <T,>(v: T): T => (v === undefined ? v : JSON.parse(JSON.stringify(v)));
export const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);
export const sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));

/* sizes and counts as the page's language writes numbers */
export const mb = (b: number) => num(b / 1e6, 1) + ' MB';
export const thousands = (n: number) => num(n);

/* a value as one short line: a text as it is, anything else as JSON ("(none)" for nothing) */
export function shown(v: unknown): string {
  if (v === null || v === undefined) return t('(none)');
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

/* what a save did to its file (the server's "writes"), in the page's language */
export function wrote(w: string | undefined): string {
  const words: Record<string, string> = { created: t('created'), changed: t('changed'), removed: t('removed'),
    unchanged: t('unchanged') };
  return (w && words[w]) || w || t('written');
}

/* the class of one line of a unified diff */
export function diffClass(line: string): '' | 'hdr' | 'hunk' | 'add' | 'del' {
  if (line.startsWith('+++') || line.startsWith('---')) return 'hdr';
  if (line.startsWith('@@')) return 'hunk';
  if (line.startsWith('+')) return 'add';
  if (line.startsWith('-')) return 'del';
  return '';
}
