/* What the tabs share: which tab is open, which have unsaved edits, what one tab asks another to show, and the Check and
   Save of the open tab for the keyboard. Small stores read with useSyncExternalStore, no library. */
import { useEffect, useRef, useSyncExternalStore } from 'react';
import { get } from './api';
import { t } from './i18n';

export type TabName = 'spec' | 'prompts' | 'flow' | 'sources' | 'graph';
/* the name of a tab in the page's language (read where it is shown, so it follows a change of the language) */
export function tabLabel(name: string): string {
  switch (name) {
    case 'spec': return t('Spec');
    case 'prompts': return t('Prompts');
    case 'flow': return t('Flow');
    case 'sources': return t('Sources');
    case 'graph': return t('Graph');
    default: return name;
  }
}
/* the tabs whose rules stand in the profile's rules file (GET /api/rules?tab=...) */
export const RULE_TABS = ['spec', 'prompts', 'flow', 'sources'];

export class Store<T> {
  private listeners = new Set<() => void>();
  constructor(private value: T) {}
  get = (): T => this.value;
  set = (next: T) => { this.value = next; for (const l of [...this.listeners]) l(); };
  subscribe = (l: () => void) => { this.listeners.add(l); return () => { this.listeners.delete(l); }; };
}
export function useStore<T>(s: Store<T>): T { return useSyncExternalStore(s.subscribe, s.get); }

/* GET /api/state */
export interface PageState {
  profile: string; spec: string; branch: string | null; changed: string[];
  harvest: string | null; harvest_documents: number | null; tabs: string[];
}
export const stateStore = new Store<PageState | null>(null);
export async function loadState() { stateStore.set(await get<PageState>('/api/state')); }

export const tabStore = new Store<{ tab: TabName; rules: string | null }>({ tab: 'spec', rules: null });
export function setTab(tab: TabName) { tabStore.set({ ...tabStore.get(), tab }); }
export function openRules(tab: string) { tabStore.set({ ...tabStore.get(), rules: tab }); }
export function closeRules() { tabStore.set({ ...tabStore.get(), rules: null }); }

/* unsaved edits, by tab ("rules" for the rules drawer) */
export const dirtyStore = new Store<Record<string, boolean>>({});
export function setDirty(name: string, dirty: boolean) {
  const cur = dirtyStore.get();
  if (!!cur[name] === dirty) return;
  dirtyStore.set({ ...cur, [name]: dirty });
}
export const anyDirty = () => Object.values(dirtyStore.get()).some(Boolean);

/* Check and Save of a tab, for Ctrl+Enter and Ctrl+S */
export interface TabActions { check?: () => void; save?: () => void }
const actions: Record<string, TabActions> = {};
export function useTabActions(name: string, a: TabActions) {
  const ref = useRef(a);
  ref.current = a;
  useEffect(() => {
    const proxy: TabActions = { check: () => ref.current.check?.(), save: () => ref.current.save?.() };
    actions[name] = proxy;
    return () => { if (actions[name] === proxy) delete actions[name]; };
  }, [name]);
}
export function runAction(name: string, which: keyof TabActions) { actions[name]?.[which]?.(); }

/* what one tab asks another to show: a tab handles a request once it has loaded (ready) */
const requests = new Store<Record<string, { seq: number; payload: any }>>({});
let seq = 0;
export function request(tab: string, payload: unknown) { requests.set({ ...requests.get(), [tab]: { seq: ++seq, payload } }); }
export function useRequests(tab: string, ready: boolean, handle: (payload: any) => void) {
  const r = useStore(requests)[tab];
  const last = useRef(0);
  const fn = useRef(handle);
  fn.current = handle;
  useEffect(() => {
    if (ready && r && r.seq !== last.current) { last.current = r.seq; fn.current(r.payload); }
  }, [r, ready]);
}

/* the node of the Spec tab a link opens (see lib/spec.ts SpecNode) */
export function openSpec(node?: unknown, flag?: unknown) { setTab('spec'); if (node) request('spec', { node, flag: flag ?? null }); }
export function openPrompt(id: string) { setTab('prompts'); request('prompts', { id }); }

/* A link to a rule opens the tab the rule stands in: the rules drawer of that tab, or the tab itself where its rules
   are not in the drawer (the Graph tab shows its own). The numbers of the flow stand in the Flow tab, not in its drawer. */
export function openRule(tab: string) { if (RULE_TABS.includes(tab)) openRules(tab); else setTab(tab as TabName); }
/* the step of the Flow tab a rule's count points at */
export function openStep(id: string) { closeRules(); setTab('flow'); request('flow', { id }); }
