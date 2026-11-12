/* The page in English or German. Every text the page writes goes through t() (tn() where it counts something), every
   explanation the server sends (what a step of the flow does, the help of a rule or of a key of the spec) through tr().
   The German texts stand in ../i18n/de.json, keyed by the English text; {name} in a text is filled in from its values.
   A text the server fills in with a name is found by the English words around it, with one of the server's own
   templates (../i18n/templates.json), never with a text of the page: the page's "For each {name}" would take any
   sentence of the server that begins with "For each" and show it half translated. The numbers the server filled in are
   written as the page's language writes them. What comes from a source (the ontology, the spec, a prompt, a document,
   a check of the pipeline) goes through neither and is shown as it is; a server text shows its `code` as code when
   it goes through rich(). */
import { Fragment, useSyncExternalStore, type ReactNode } from 'react';
import { Code } from '@mantine/core';
import de from '../i18n/de.json';
import serverTemplates from '../i18n/templates.json';

export type Lang = 'en' | 'de';
/* each language named in its own words */
export const LANGS: { value: Lang; label: string }[] = [
  { value: 'de', label: 'Deutsch' }, // i18n-ignore
  { value: 'en', label: 'English' }, // i18n-ignore
];
const KEY = 'docpipe-edit-language';
const DE: Record<string, string> = de;

/* the language chosen last in this browser, else the browser's own */
function first(): Lang {
  try { const v = localStorage.getItem(KEY); if (v === 'de' || v === 'en') return v; } catch { /* the page works without it */ }
  return /^de\b/i.test(navigator.language || '') ? 'de' : 'en';
}
let lang: Lang = first();
document.documentElement.lang = lang;
const listeners = new Set<() => void>();
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
export const getLang = (): Lang => lang;
export function setLang(next: Lang) {
  if (next === lang) return;
  lang = next;
  document.documentElement.lang = next;
  try { localStorage.setItem(KEY, next); } catch { /* the page works without it */ }
  for (const l of [...listeners]) l();
}
/* A component whose texts are not drawn anew with its parent (a node of the canvas, a value kept in useMemo) calls
   this, so it follows a change of the language. */
export const useLang = (): Lang => useSyncExternalStore(subscribe, getLang);

export type Vars = Record<string, string | number>;
const fill = (s: string, vars?: Vars) =>
  vars ? s.replace(/\{(\w+)\}/g, (m, k: string) => (Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m)) : s;

/* a number as the page's language writes it */
export const num = (n: number, digits?: number) =>
  n.toLocaleString(lang === 'de' ? 'de-DE' : 'en-US', digits == null ? undefined : { minimumFractionDigits: digits, maximumFractionDigits: digits });

/* a text of the page; vars fill its {names}, a number as num() writes it */
export function t(en: string, vars?: Vars): string {
  const said = lang === 'de' ? DE[en] : undefined;
  const shown: Vars | undefined = vars && Object.fromEntries(Object.entries(vars).map(([k, v]) => [k, typeof v === 'number' ? num(v) : v]));
  return fill(said || en, shown);
}
/* a text with a count: tn(3, '{n} document', '{n} documents') */
export function tn(n: number, one: string, many: string, vars?: Vars): string {
  return t(n === 1 ? one : many, { ...vars, n });
}

/* The server's templates, as patterns a server text is matched against, the longest words first. Only a template with
   words of its own (six letters at least besides its names) is one: "{subject} {prop}" would fit any text. */
interface Template { key: string; re: RegExp; names: string[] }
let templates: Template[] | null = null;
const LETTERS = /[A-Za-zÄÖÜäöüß]/g;
const templateWords = (k: string) => (k.replace(/\{\w+\}/g, '').match(LETTERS) || []).length;
function templatesOf(): Template[] {
  if (templates) return templates;
  const words = (k: string) => k.replace(/\{\w+\}/g, '').length;
  templates = (serverTemplates as string[]).filter(k => DE[k] && /\{\w+\}/.test(k) && templateWords(k) >= 6)
    .sort((a, b) => words(b) - words(a)).map(key => {
    const names: string[] = [];
    const body = key.split(/(\{\w+\})/).map(part => {
      const m = /^\{(\w+)\}$/.exec(part);
      if (m) { names.push(m[1]); return '([\\s\\S]+?)'; }
      return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('');
    return { key, re: new RegExp('^' + body + '$'), names };
  });
  return templates;
}

/* A number the server wrote into a text, as the page's language writes it: a filled-in value that is one number
   ("4.2", "9,206"), and inside a longer value every number with its thousands marked ("1 → 9,206"). Words, names
   and `code` stay as they are, and so does a number without thousands inside a longer value ("1.5 °C"). */
const ONE_NUMBER = /^-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$/;
const GROUPED = /\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b/g;
const german = (n: string) => n.replace(/[.,]/g, c => (c === ',' ? '.' : ','));
export function localNumbers(value: string): string {
  if (lang !== 'de') return value;
  if (ONE_NUMBER.test(value)) return german(value);
  return value.split(/(`[^`]*`)/).map((part, i) => (i % 2 ? part : part.replace(GROUPED, german))).join('');
}

/* an explanation the server sent, in the page's language */
export function tr(en: string | null | undefined): string {
  if (en == null) return '';
  if (lang !== 'de' || !en) return en;
  if (DE[en]) return DE[en];
  for (const tpl of templatesOf()) {
    const m = tpl.re.exec(en);
    if (!m) continue;
    const vars: Vars = {};
    tpl.names.forEach((name, i) => { vars[name] = localNumbers(m[i + 1]); });
    return fill(DE[tpl.key], vars);
  }
  return en;
}

/* A reason the check of a flow gives (its problems, the dry run's refusal, the changes of an edit), in the page's
   language: a sentence of the server's, or one of its templates with what the server filled in translated the same way
   (a step's label, the words of a variable, a reason inside the reason); else "where: what" and reasons joined with
   "; " part by part, and words joined with " or " each. What has no German (an id, a key, a name) stays as it is. */
const JOINS: [string, string][] = [['; ', '; '], [': ', ': '], [' or ', ' oder ']];
export function trCheck(en: string | null | undefined, depth = 0): string {
  if (en == null) return '';
  if (lang !== 'de' || !en) return en;
  if (DE[en]) return DE[en];
  if (depth > 8) return localNumbers(en);
  for (const tpl of templatesOf()) {
    const m = tpl.re.exec(en);
    if (!m) continue;
    const vars: Vars = {};
    tpl.names.forEach((name, i) => { vars[name] = trCheck(m[i + 1], depth + 1); });
    return fill(DE[tpl.key], vars);
  }
  for (const [sep, said] of JOINS) {
    const at = en.indexOf(sep);
    if (at > 0) return trCheck(en.slice(0, at), depth + 1) + said + trCheck(en.slice(at + sep.length), depth + 1);
  }
  return localNumbers(en);
}

/* a translated sentence with **bold** and `code` in it, as elements */
export function rich(text: string): ReactNode {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) => {
    if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) return <b key={i}>{part.slice(2, -2)}</b>;
    if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) return <Code key={i}>{part.slice(1, -1)}</Code>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}
