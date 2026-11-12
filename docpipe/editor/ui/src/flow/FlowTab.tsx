/* The Flow tab: the flow of steps, loops, rounds and branchings a run does (extraction/flow.py, engine.py) on a canvas,
   its library, its numbers, checked and saved through /api/flow, run dry on one document with placeholder answers
   (/api/flow/try). The tree the server sent is kept and edited in place, so a key no control shows goes back as it came;
   every edit can be undone until the next save. */
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import {
  Background, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow, type Node,
} from '@xyflow/react';
import {
  Accordion, ActionIcon, Alert, Anchor, Badge, Box, Button, Center, Code, Group, List, Loader, Menu, ScrollArea,
  SegmentedControl, Select, Stack, Text, Tooltip,
} from '@mantine/core';
import {
  IconArrowBackUp, IconArrowDown, IconArrowForwardUp, IconArrowUp, IconCheck, IconCopy, IconDeviceFloppy,
  IconFocusCentered, IconFrame, IconArrowsMinimize, IconArrowsMaximize, IconPlayerPlay, IconPower, IconTrash, IconX,
} from '@tabler/icons-react';
import { api, apiR } from '../lib/api';
import { rich, t, tr, useLang } from '../lib/i18n';
import { askConfirm, showError, showInfo } from '../lib/dialogs';
import { loadState, setDirty, tabStore, useRequests, useTabActions } from '../lib/nav';
import { clone, wrote } from '../lib/util';
import { Diff } from '../components/Bits';
import { layout, type Decor } from './layout';
import {
  ancestors, duplicate, find, fresh, insertAt, kindOf, labelOf, listOf, moveBy, remove, siblingsRun, stepBox, walk,
  wrap, type FlowData, type Step,
} from './model';
import { Ctx, DotNode, FrameNode, StepEdge, StepNode, WayNode, frameWord, type FlowCtx } from './nodes';
import { LibraryModal, type Pick } from './Library';
import { NumbersPane, StepSettings, type Panel } from './Settings';
import { TryPane } from './TryPane';
import { HowTo } from './HowTo';
import './flow.css';

const nodeTypes = { step: StepNode, frame: FrameNode, way: WayNode, dot: DotNode };
const edgeTypes = { step: StepEdge };
const edgeDefaults = { markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 } };
/* React Flow's own words (the tooltips of its buttons, the title of the overview, what a screen reader says of a step
   or an arrow), in the page's language */
const flowWords = () => ({
  'node.a11yDescription.default': t('Press Enter or Space to choose this step and Escape to cancel.'),
  'node.a11yDescription.keyboardDisabled': t('Press Enter or Space to choose this step and Escape to cancel.'),
  'edge.a11yDescription.default': t('Press Enter or Space to choose this arrow and Escape to cancel.'),
  'controls.ariaLabel': t('View of the flow'),
  'controls.zoomIn.ariaLabel': t('Zoom in'),
  'controls.zoomOut.ariaLabel': t('Zoom out'),
  'controls.fitView.ariaLabel': t('Show the whole flow'),
  'minimap.ariaLabel': t('Overview of the flow'),
  'handle.ariaLabel': t('End of an arrow'),
});
const READABLE = 0.8;    // below this zoom the words of a step are too small to read

interface Report { source: 'check' | 'save'; r?: any; error?: string }

/* a flow of a follow-up pass the run can start (/api/flow/passes), and one of them as the server draws it
   (/api/flow/pass) */
interface PassRef { name: string; file: string; own: boolean; starts_from: string | null }
interface PassView {
  name: string; file: string; exists: boolean; base: string | null; tree: Step[]; inherited_tree: Step[] | null;
  library: FlowData['library']; problems: FlowData['problems']; not_started: string | null;
}
/* the flows of the follow-up passes in the order the plan of a run takes them */
const PASS_ORDER = ['top_up', 'top_up_open', 'top_up_parameters', 'remap', 'recheck', 'review', 'start_at', 'example'];
/* the name of each flow of a follow-up pass, with the switch of the call that starts it */
const passWord = (name: string): string => ({
  top_up: t('Read changed questions again (--top-up)'),
  top_up_open: t('Read the open places again (--top-up-open)'),
  top_up_parameters: t('Read further parameters (--top-up-parameters)'),
  remap: t('Map the lists again (--remap)'),
  recheck: t('Check the quotes again (--recheck)'),
  review: t('Second reading (--review)'),
  start_at: t('Start at the places found (--start-at)'),
  example: t('Example for a field (while a spec is compiled)'),
} as Record<string, string>)[name] || name;

interface State {
  loaded: boolean; loading: boolean; data: FlowData | null; tree: Step[]; cur: Record<string, number | string>;
  sel: string | null; multi: Set<string>; open: Set<string>; report: Report | null; busy: boolean;
  meas: any; trial: any; trying: boolean; docs: { id: number | string; title: string }[] | null;
  tryst: { doc: string; pages: string; mode: string }; side: 'numbers' | 'try';
  undo: string[]; redo: string[]; snap: string; fit: number; epoch: number;
  /* the flow shown: '' the main flow, else the name of a flow of a follow-up pass */
  which: string; passes: PassRef[] | null; main: FlowData | null; notStarted: string | null;
}

export function FlowTab() {
  return <ReactFlowProvider><FlowInner /></ReactFlowProvider>;
}

function FlowInner() {
  const lang = useLang();
  const F = useRef<State>({
    loaded: false, loading: false, data: null, tree: [], cur: {}, sel: null, multi: new Set(), open: new Set(),
    report: null, busy: false, meas: null, trial: null, trying: false, docs: null,
    tryst: { doc: '', pages: '', mode: 'nothing' }, side: 'numbers', undo: [], redo: [], snap: '', fit: 0, epoch: 0,
    which: '', passes: null, main: null, notStarted: null,
  }).current;
  const [version, touch] = useReducer((x: number) => x + 1, 0);
  const [menu, setMenu] = useState<{ x: number; y: number; id: string } | null>(null);
  const [lib, setLib] = useState<{ list: string; at: number; after: string | null } | null>(null);
  const flow = useReactFlow();

  const numbers = () => { const o: Record<string, number | string> = {}; for (const n of F.data!.numbers) o[n.name] = F.cur[n.name]; return o; };
  const numDirty = () => !!F.data && F.data.numbers.some(n => F.cur[n.name] !== n.value);
  const treeDirty = () => !!F.data && JSON.stringify(F.tree) !== JSON.stringify(F.data.tree);
  const dirty = () => numDirty() || treeDirty();
  const stamp = () => JSON.stringify({ tree: F.tree, cur: F.cur });

  /* An edit lays the flow out anew, and a loop, round or branching that opens or grows pushes everything around it aside. So before
     the layout changes, the screen place of the step being worked on is noted (with its neighbours and the loops,
     rounds and branchings around it, in case it goes), and after the new layout the canvas is moved so that the first of them still drawn
     stands where it stood. */
  const placedNow = useRef<Node[]>([]);
  const anchor = useRef<{ id: string; x: number; y: number }[] | null>(null);
  const absolute = (nodes: Node[], id: string) => {
    const by = new Map(nodes.map(n => [n.id, n]));
    let n = by.get(id), x = 0, y = 0;
    if (!n) return null;
    while (n) { x += n.position.x; y += n.position.y; n = n.parentId ? by.get(n.parentId) : undefined; }
    return { x, y };
  };
  const pin = (...ids: (string | null | undefined)[]) => {
    if (anchor.current) return;
    const vp = flow.getViewport();
    const got: { id: string; x: number; y: number }[] = [];
    for (const id of ids) {
      if (!id) continue;
      const p = absolute(placedNow.current, id);
      if (p) got.push({ id, x: p.x * vp.zoom + vp.x, y: p.y * vp.zoom + vp.y });
    }
    anchor.current = got.length ? got : null;
  };
  /* a step, then the steps beside it in its column, then the loops, rounds and branchings around it */
  const around = (id: string | null): string[] => {
    if (!id) return [];
    const got = find(F.tree, id);
    if (!got) return [id];
    const i = got.steps.indexOf(got.n);
    return [id, got.steps[i - 1]?.id, got.steps[i + 1]?.id, ...ancestors(F.tree, id).reverse()].filter(Boolean) as string[];
  };

  /* every edit: what the last check or try said is gone, and the state before it can be had back */
  const remember = () => { const now = stamp(); if (now !== F.snap) { F.undo.push(F.snap); F.redo = []; F.snap = now; } };
  const edited = () => { pin(...around(F.sel)); F.report = null; F.trial = null; remember(); touch(); };
  const restore = (s: string) => {
    pin(...around(F.sel));
    const o = JSON.parse(s);
    const numbersMoved = JSON.stringify(o.cur) !== JSON.stringify(F.cur);
    F.tree = o.tree; F.cur = o.cur; F.snap = s; F.report = null; F.trial = null; F.epoch++;
    if (F.sel && !find(F.tree, F.sel)) F.sel = null;
    F.multi = new Set([...F.multi].filter(id => find(F.tree, id)));
    touch();
    if (numbersMoved) measured();
  };
  const undo = () => { if (!F.undo.length) return; F.redo.push(F.snap); restore(F.undo.pop()!); };
  const redo = () => { if (!F.redo.length) return; F.undo.push(F.snap); restore(F.redo.pop()!); };

  const measured = useCallback(async () => {
    if (!F.data || F.which) return;     // a follow-up pass has no numbers of its own
    try { F.meas = await apiR('/api/flow/measured', { numbers: numbers(), trace: null }); }
    catch { F.meas = null; }
    touch();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* the main flow as the server sends it, or a flow of a follow-up pass drawn on it: its own boxes and loops, no
     numbers, the conditions and words of the main flow */
  const fetchFlow = async (): Promise<FlowData> => {
    if (F.passes === null) {
      try { F.passes = (await api<{ passes: PassRef[] }>('GET', '/api/flow/passes')).passes || []; }
      catch { F.passes = []; }
    }
    if (!F.which) { F.notStarted = null; return F.main = await api<FlowData>('GET', '/api/flow'); }
    const main = F.main || (F.main = await api<FlowData>('GET', '/api/flow'));
    const p = await api<PassView>('GET', '/api/flow/pass?name=' + encodeURIComponent(F.which));
    const ref = (F.passes || []).find(x => x.name === F.which);
    F.notStarted = p.not_started;
    return {
      ...main, file: p.file, exists: p.exists, base: p.base, whole: true, starts_from: (ref && ref.starts_from) || '',
      drawn_by: (ref && ref.starts_from) || '', inherited_tree: p.inherited_tree, numbers: [], tree: p.tree,
      library: p.library, problems: p.problems || [], notes: [], switches: {},
    };
  };

  const load = async (keep: boolean) => {
    if (F.loading) return;
    F.loading = true; touch();
    try {
      const d = await fetchFlow();
      const prevCur = F.cur, prevTree = F.loaded ? F.tree : null;
      F.data = d; F.cur = {};
      for (const n of d.numbers) F.cur[n.name] = keep && Object.prototype.hasOwnProperty.call(prevCur, n.name) ? prevCur[n.name] : n.value;
      F.tree = keep && prevTree ? prevTree : clone(d.tree);
      F.report = null; F.loaded = true;
      if (!keep) { F.undo = []; F.redo = []; }
      F.snap = stamp();
      if (F.sel && !find(F.tree, F.sel)) F.sel = null;
      F.fit++;
    } catch (e) {
      F.loading = false;
      if (F.loaded) showError(e); else F.report = { source: 'check', error: (e as Error).message };
      touch();
      return;
    }
    F.loading = false; touch();
    measured();
  };
  useEffect(() => { load(true); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const check = async () => {
    if (!F.data || F.busy) return;
    F.busy = true; touch();
    try {
      F.report = { source: 'check', r: F.which ? await apiR('/api/flow/pass/check', { name: F.which, tree: F.tree })
        : await apiR('/api/flow/check', { numbers: numbers(), tree: F.tree }) };
    }
    catch (e) { F.report = { source: 'check', error: (e as Error).message }; }
    F.busy = false; touch();
  };
  const save = async () => {
    if (!F.data || F.busy || !dirty()) return;
    F.busy = true; touch();
    let saved: any = null;
    try {
      const base = F.data.base == null ? null : F.data.base;
      const r = F.which ? await apiR('/api/flow/pass/save', { name: F.which, tree: F.tree, base })
        : await apiR('/api/flow/save', { numbers: numbers(), tree: F.tree, base });
      if (r.saved) saved = r; else F.report = { source: 'save', r };
    } catch (e) { F.report = { source: 'save', error: (e as Error).message }; }
    F.busy = false;
    if (saved) {
      showInfo(t('Saved {file} ({writes}).', { file: saved.file || t('the flow file'), writes: wrote(saved.writes) }));
      await load(false);
      loadState().catch(() => {});
    } else touch();
  };
  const discard = async () => {
    if (!F.data || !dirty() || F.busy) return;
    if (!await askConfirm(t('Discard changes'), t('Discard the edited flow and numbers? Ctrl+Z brings them back.'), t('Discard'))) return;
    const numbersMoved = numDirty();
    F.tree = clone(F.data.tree); for (const n of F.data.numbers) F.cur[n.name] = n.value; F.epoch++;
    edited();
    if (numbersMoved) measured();   // what the last runs measured is shown at the numbers in the fields
  };
  const reload = async () => {
    if (dirty() && !await askConfirm(t('Reload from disk'), t('The flow file changed on disk. Reloading drops the edits.'), t('Drop my edits and reload'))) return;
    await load(false);
  };
  const tryIt = async () => {
    if (F.trying || !F.data) return;
    F.trying = true; touch();
    const body: Record<string, unknown> = { tree: F.tree, numbers: numbers(), mode: F.tryst.mode };
    if (F.tryst.doc) {
      body.document = Number(F.tryst.doc);
      const m = /^\s*(\d+)\s*-\s*(\d+)\s*$/.exec(F.tryst.pages || '');
      if (m) body.pages = [Number(m[1]), Number(m[2])];
    }
    try { F.trial = await apiR('/api/flow/try', body); }
    catch (e) { F.trial = { error: (e as Error).message }; }
    F.trying = false; touch();
  };
  const loadDocs = async () => {
    if (F.docs) return;
    try { F.docs = (await api('GET', '/api/flow/documents')).documents || []; } catch { F.docs = []; }
    touch();
  };

  useTabActions('flow', { check, save });
  useEffect(() => { setDirty('flow', F.loaded && dirty()); });
  useEffect(() => {
    const keys = (ev: KeyboardEvent) => {
      const cur = tabStore.get();
      if (cur.tab !== 'flow' || cur.rules || !(ev.ctrlKey || ev.metaKey)) return;
      const t = ev.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      const k = ev.key.toLowerCase();
      if (k === 'z' && !ev.shiftKey) { ev.preventDefault(); undo(); }
      else if (k === 'y' || (k === 'z' && ev.shiftKey)) { ev.preventDefault(); redo(); }
    };
    window.addEventListener('keydown', keys);
    return () => window.removeEventListener('keydown', keys);
  });

  /* -- what the canvas shows -- */
  const problems = useMemo(() => {
    const m = new Map<string, string[]>();
    if (!F.data) return m;
    const R = F.report && F.report.r;
    const said: { id?: string; message: string }[] = R && R.errors ? R.errors : F.data.problems || [];
    for (const p of said) if (p.id) m.set(p.id, [...(m.get(p.id) || []), p.message]);
    return m;
  }, [version]); // eslint-disable-line react-hooks/exhaustive-deps
  const placed = useMemo(() => {
    if (!F.data) return { nodes: [], edges: [] };
    const boxes = F.trial && F.trial.boxes ? F.trial.boxes as Record<string, { requests: number }> : null;
    const tried = boxes ? Object.fromEntries(Object.entries(boxes).map(([k, v]) => [k, v.requests])) : null;
    const decor: Decor = {
      open: F.open, selected: new Set([...F.multi, ...(F.sel ? [F.sel] : [])]), problems,
      measured: F.meas && F.meas.steps ? F.meas.steps : null, tried,
      triedMost: tried ? Math.max(1, ...Object.values(tried)) : 0,
    };
    return layout(F.data, F.tree, decor);
  }, [version, problems, lang]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const a = anchor.current;
    anchor.current = null;
    placedNow.current = placed.nodes;
    if (!a) return;
    const vp = flow.getViewport();
    for (const p of a) {
      const now = absolute(placed.nodes, p.id);
      if (now) { flow.setViewport({ x: p.x - now.x * vp.zoom, y: p.y - now.y * vp.zoom, zoom: vp.zoom }); return; }
    }
  }, [placed]); // eslint-disable-line react-hooks/exhaustive-deps

  /* the first view: the whole flow if it can be read whole, else its top at a size that can be read, scrolled down
     with the wheel */
  const canvas = useRef<HTMLDivElement>(null);
  const showTop = (duration: number) => {
    const el = canvas.current;
    const top = placed.nodes.filter(n => !n.parentId);
    if (!el || !top.length) return;
    const W = el.clientWidth, H = el.clientHeight;
    const b = flow.getNodesBounds(top);
    const whole = Math.min(W / (b.width * 1.12), H / (b.height * 1.12));
    if (whole >= READABLE) { flow.fitView({ padding: 0.06, maxZoom: 1, duration }); return; }
    const z = Math.max(READABLE, Math.min(1, W / (b.width + 80)));
    flow.setViewport({ x: (W - b.width * z) / 2 - b.x * z, y: 28 - b.y * z, zoom: z }, { duration });
  };
  useEffect(() => {
    if (!F.fit) return;
    const t = setTimeout(() => showTop(300), 120);
    return () => clearTimeout(t);
  }, [F.fit]); // eslint-disable-line react-hooks/exhaustive-deps

  /* opens every loop, round and branching around a step, chooses it and brings it to the middle */
  const reveal = (id: string) => {
    for (const a of ancestors(F.tree, id)) F.open.add(a);
    F.sel = id; F.multi = new Set([id]); touch();
    setTimeout(() => flow.fitView({ nodes: [{ id }], maxZoom: 1.1, duration: 400, padding: 0.6 }), 60);
  };
  useRequests('flow', F.loaded, p => { if (p && p.id && find(F.tree, p.id)) reveal(p.id); });
  const toggle = (id: string) => { pin(...around(id)); if (F.open.has(id)) F.open.delete(id); else F.open.add(id); touch(); };
  const openAll = (open: boolean) => {
    F.open = new Set(open ? [...walk(F.tree)].filter(([n]) => kindOf(n) !== 'box').map(([n]) => n.id) : []);
    F.fit++; touch();
  };
  const focusNumber = (name: string) => {
    F.sel = null; F.side = 'numbers'; touch();
    setTimeout(() => { const el = document.querySelector<HTMLInputElement>('[data-number="' + name + '"] input'); if (el) { el.scrollIntoView({ block: 'center' }); el.focus(); } }, 50);
  };

  /* -- edits of the flow -- */
  const put = (list: string, at: number, p: Pick) => {
    const steps = listOf(F.tree, list);
    if (!steps || !F.data) return;
    const n = fresh(F.tree, F.data.conditions, p.kind, 'arg' in p ? p.arg : undefined);
    insertAt(steps, at, n);
    for (const a of ancestors(F.tree, n.id)) F.open.add(a);
    F.sel = n.id; F.multi = new Set([n.id]);
    edited();
  };
  const listKeyOf = (id: string): { list: string; at: number } | null => {
    const got = find(F.tree, id);
    if (!got) return null;
    const keyOf = (steps: Step[]): string => {
      if (steps === F.tree) return 'root';
      for (const [n] of walk(F.tree)) {
        const k = kindOf(n);
        if ((k === 'each' || k === 'round') && n.steps === steps) return n.id;
        if (k === 'if') {
          const i = (n.if || []).findIndex((w: { steps: Step[] }) => w.steps === steps);
          if (i >= 0) return n.id + '#' + i;
          if (n.else === steps) return n.id + '#else';
        }
      }
      return 'root';
    };
    return { list: keyOf(got.steps), at: got.steps.indexOf(got.n) + 1 };
  };
  const removable = (n: Step) => { const b = kindOf(n) === 'box' && F.data ? stepBox(F.data.library, n) : null; return !(b && (b.fixed || !b.switch)); };
  const act = (what: string, id: string, arg?: string) => {
    const got = find(F.tree, id);
    if (!got || !F.data) return;
    pin(...around(id));
    if (what === 'up' || what === 'down') { if (moveBy(F.tree, id, what === 'up' ? -1 : 1)) edited(); return; }
    if (what === 'duplicate') { const c = duplicate(F.tree, id); if (c) { F.sel = c.id; F.multi = new Set([c.id]); edited(); } return; }
    if (what === 'delete') { if (remove(F.tree, id)) { if (F.sel === id) F.sel = null; F.multi.delete(id); edited(); } return; }
    if (what === 'off') { if (got.n.off) delete got.n.off; else got.n.off = true; edited(); return; }
    if (what === 'wrap') {
      const ids = F.multi.has(id) && F.multi.size > 1 ? [...F.multi] : [id];
      if (!siblingsRun(F.tree, ids)) { showError(new Error(t('Only steps, loops, rounds and branchings that stand right after one another in the same column can be wrapped together.'))); return; }
      const [kind, each] = (arg || 'round').split(':');
      const f = wrap(F.tree, F.data.conditions, ids, kind as 'each' | 'round' | 'if', each);
      if (f) { F.open.add(f.id); for (const a of ancestors(F.tree, f.id)) F.open.add(a); F.sel = f.id; F.multi = new Set([f.id]); edited(); }
    }
  };

  const ctx: FlowCtx | null = F.data ? {
    lib: F.data.library, never: F.data.never || {}, toggle, loopsOnly: !!F.which,
    add: (list, at) => setLib({ list, at, after: null }),
  } : null;

  const onNodeClick = (ev: React.MouseEvent, node: Node) => {
    if (node.type !== 'step' && node.type !== 'frame') return;
    if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
      if (F.multi.has(node.id)) F.multi.delete(node.id); else F.multi.add(node.id);
      F.sel = node.id;
    } else { F.sel = node.id; F.multi = new Set([node.id]); }
    touch();
  };
  const onNodeContextMenu = (ev: React.MouseEvent, node: Node) => {
    if (node.type !== 'step' && node.type !== 'frame') return;
    ev.preventDefault();
    if (!F.multi.has(node.id)) { F.sel = node.id; F.multi = new Set([node.id]); touch(); }
    setMenu({ x: ev.clientX, y: ev.clientY, id: node.id });
  };

  if (!F.data || !ctx) {
    return <Center h="100%">{F.report && F.report.error ? <Alert color="red">{F.report.error}</Alert> : <Loader />}</Center>;
  }
  const d = F.data;
  const status = F.which ? (d.exists ? t('its own flow') : t('not written yet: the flow comes from {name}', { name: d.starts_from || t('the program') }))
    : !d.exists ? t('not written yet: the flow and every number come from {name}', { name: d.starts_from })
    : d.whole ? t('the whole flow of this profile') : (d.drawn_by === d.starts_from ? t('numbers of its own, the flow of {name}', { name: d.drawn_by }) : t('its own flow'));
  /* another flow is shown: edits not saved are given up first, as on a reload */
  const choose = async (name: string) => {
    if (name === F.which || F.busy) return;
    if (dirty() && !await askConfirm(t('Show another flow'), t('The flow shown has changes that are not saved. Showing another flow drops them.'), t('Drop my edits'))) return;
    F.which = name; F.sel = null; F.multi = new Set(); F.open = new Set(); F.trial = null; F.meas = null;
    F.side = 'numbers';
    await load(false);
  };
  const rank = (name: string) => { const i = PASS_ORDER.indexOf(name); return i < 0 ? PASS_ORDER.length : i; };
  const flows = [{ value: '', label: t('Main flow') }, ...[...(F.passes || [])]
    .sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))
    .map(p => ({ value: p.name, label: passWord(p.name) }))];
  const sel = F.sel ? find(F.tree, F.sel) : null;
  const panel: Panel = {
    data: d, tree: F.tree, epoch: F.epoch, cur: F.cur, meas: F.meas, trial: F.trial,
    problemsOf: id => (problems.get(id) || []).map(message => ({ message })),
    edited,
    numberSet: (name, v) => { F.cur[name] = v; F.report = null; remember(); touch(); measured(); },
    select: id => { F.sel = id; F.multi = new Set(id ? [id] : []); touch(); },
    focusNumber, reload: () => { load(true); }, pass: !!F.which,
    availableOf: id => (((F.report && F.report.r && F.report.r.available) || d.available || {}) as Record<string, string[]>)[id] || [],
  };
  const isDirty = dirty();
  const menuStep = menu ? find(F.tree, menu.id) : null;

  return (
    <Ctx.Provider value={ctx}>
      <Stack gap={0} h="100%">
        <Group px="md" py={8} gap="sm" justify="space-between" className="fl-bar" wrap="nowrap">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <Select aria-label={t('Flow shown')} data={flows} value={F.which} allowDeselect={false} w={280}
              style={{ flex: '0 0 auto' }} comboboxProps={{ withinPortal: true, width: 360 }}
              onChange={v => { if (v !== null) choose(v); }} />
            <Code>{d.file}</Code>
            <Text size="sm" c="dimmed" lineClamp={1}>{status}</Text>
          </Group>
          <Group gap={6} wrap="nowrap">
            <Tooltip label={t('Undo (Ctrl+Z)')}><ActionIcon variant="default" size="lg" disabled={!F.undo.length} onClick={undo} aria-label={t('Undo')}><IconArrowBackUp size={18} /></ActionIcon></Tooltip>
            <Tooltip label={t('Redo (Ctrl+Y)')}><ActionIcon variant="default" size="lg" disabled={!F.redo.length} onClick={redo} aria-label={t('Redo')}><IconArrowForwardUp size={18} /></ActionIcon></Tooltip>
            <Tooltip label={t('Open every loop, round and branching')}><ActionIcon variant="default" size="lg" onClick={() => openAll(true)} aria-label={t('Open every loop, round and branching')}><IconArrowsMaximize size={18} /></ActionIcon></Tooltip>
            <Tooltip label={t('Close every loop, round and branching')}><ActionIcon variant="default" size="lg" onClick={() => openAll(false)} aria-label={t('Close every loop, round and branching')}><IconArrowsMinimize size={18} /></ActionIcon></Tooltip>
            <Tooltip label={t('Show the whole flow')}><ActionIcon variant="default" size="lg" onClick={() => flow.fitView({ padding: 0.08, maxZoom: 1, duration: 300 })} aria-label={t('Show the whole flow')}><IconFocusCentered size={18} /></ActionIcon></Tooltip>
            <Button variant="default" leftSection={<IconCheck size={16} />} loading={F.busy} onClick={check} title={t('Ctrl+Enter')}>{t('Check')}</Button>
            <Button leftSection={<IconDeviceFloppy size={16} />} disabled={F.busy || !isDirty} onClick={save} title={t('Ctrl+S')}>{t('Save')}</Button>
            <Button variant="default" leftSection={<IconX size={16} />} disabled={F.busy || !isDirty} onClick={discard}>{t('Discard')}</Button>
            {!F.which && <Button variant="light" color="orange" leftSection={<IconPlayerPlay size={16} />} loading={F.trying}
              onClick={() => { F.sel = null; F.multi = new Set(); F.side = 'try'; touch(); }}>{t('Dry run')}</Button>}
          </Group>
        </Group>
        <Box px="md" pb={8}><HowTo /></Box>
        <ReportStrip R={F.report} problems={d.problems} onStep={reveal} onNumber={focusNumber} onReload={reload} />
        <Group gap={0} wrap="nowrap" style={{ flex: 1, minHeight: 0 }} align="stretch">
          <Box ref={canvas} style={{ flex: 1, minWidth: 0, position: 'relative' }} className="fl-canvas">
            <ReactFlow nodes={placed.nodes} edges={placed.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
              defaultEdgeOptions={edgeDefaults} nodesDraggable={false} nodesConnectable={false} elementsSelectable
              deleteKeyCode={null} selectionKeyCode={null} multiSelectionKeyCode={null} panOnScroll zoomOnDoubleClick={false}
              minZoom={0.15} maxZoom={1.6} proOptions={{ hideAttribution: true }} ariaLabelConfig={flowWords()}
              onNodeClick={onNodeClick} onNodeContextMenu={onNodeContextMenu}
              onPaneClick={() => { if (F.sel || F.multi.size) { F.sel = null; F.multi = new Set(); touch(); } }}>
              <Background gap={24} size={1} />
              <MiniMap pannable zoomable nodeStrokeWidth={2} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </Box>
          <ScrollArea w={380} className="fl-side" type="auto">
            <Box p="md">
              {sel ? <StepSettings key={sel.n.id} P={panel} n={sel.n} /> : F.which ? (
                <Stack gap="sm">
                  <Text fw={650}>{passWord(F.which)}</Text>
                  <Text size="sm">{t('A follow-up pass runs on a stored harvest, its steps one after the other in the order shown. The switch of the call in brackets starts it, and so does --flow with its name. To change it: put steps in or take them out, switch them off, or choose a step to set what it does and the values it reads. Where a step needs what another one gives, the check says so.')}</Text>
                  {F.notStarted && <Alert color="gray">{rich(tr(F.notStarted))}</Alert>}
                </Stack>
              ) : (
                <Stack gap="md">
                  <SegmentedControl fullWidth value={F.side} onChange={v => { F.side = v as 'numbers' | 'try'; touch(); }}
                    data={[{ value: 'numbers', label: t('Numbers') }, { value: 'try', label: t('Dry run') }]} />
                  {F.side === 'numbers' ? <NumbersPane P={panel} /> : (
                    <TryPane st={F.tryst} set={s => { Object.assign(F.tryst, s); touch(); }} docs={F.docs} loadDocs={loadDocs}
                      trying={F.trying} trial={F.trial} run={tryIt} subjects={d.conditions} />
                  )}
                </Stack>
              )}
            </Box>
          </ScrollArea>
        </Group>
      </Stack>
      <LibraryModal lib={d.library} opened={!!lib} after={lib ? lib.after : null} onClose={() => setLib(null)} loopsOnly={!!F.which}
        onPick={p => { const l = lib; setLib(null); if (l) put(l.list, l.at, p); }} />
      <Menu opened={!!menu} onChange={o => { if (!o) setMenu(null); }} position="bottom-start" withinPortal shadow="md" width={240}>
        <Menu.Target><Box style={{ position: 'fixed', left: menu ? menu.x : 0, top: menu ? menu.y : 0, width: 1, height: 1 }} /></Menu.Target>
        <Menu.Dropdown>
          {menuStep && (<>
            <Menu.Label>{labelOf(d.library, menuStep.n)}</Menu.Label>
            <Menu.Item leftSection={<IconArrowUp size={16} />} disabled={menuStep.steps.indexOf(menuStep.n) === 0} onClick={() => act('up', menuStep.n.id)}>{t('Move up')}</Menu.Item>
            <Menu.Item leftSection={<IconArrowDown size={16} />} disabled={menuStep.steps.indexOf(menuStep.n) === menuStep.steps.length - 1} onClick={() => act('down', menuStep.n.id)}>{t('Move down')}</Menu.Item>
            <Menu.Item leftSection={<IconCopy size={16} />} onClick={() => act('duplicate', menuStep.n.id)}>{t('Duplicate')}</Menu.Item>
            <Menu.Item leftSection={<IconFrame size={16} />} onClick={() => { const at = listKeyOf(menuStep.n.id); if (at) setLib({ ...at, after: labelOf(d.library, menuStep.n) }); }}>{F.which ? t('Put a step or loop after it…') : t('Put a step, loop, round or branching after it…')}</Menu.Item>
            <Menu.Divider />
            <Menu.Label>{F.multi.size > 1 && F.multi.has(menuStep.n.id) ? t('Wrap the {n} chosen in', { n: F.multi.size }) : t('Wrap it in')}</Menu.Label>
            {!F.which && <Menu.Item onClick={() => act('wrap', menuStep.n.id, 'round')}>{frameWord('round')}</Menu.Item>}
            {!F.which && <Menu.Item onClick={() => act('wrap', menuStep.n.id, 'if')}>{frameWord('if')}</Menu.Item>}
            {Object.keys(d.library.each).map(e => <Menu.Item key={e} onClick={() => act('wrap', menuStep.n.id, 'each:' + e)}>{rich(tr((d.library.each_titles || {})[e]) || t('For each {name}', { name: e }))}</Menu.Item>)}
            <Menu.Divider />
            {removable(menuStep.n) && <Menu.Item leftSection={<IconPower size={16} />} onClick={() => act('off', menuStep.n.id)}>{menuStep.n.off ? t('Switch on') : t('Switch off')}</Menu.Item>}
            {removable(menuStep.n) && <Menu.Item color="red" leftSection={<IconTrash size={16} />} onClick={() => act('delete', menuStep.n.id)}>{t('Delete')}</Menu.Item>}
          </>)}
        </Menu.Dropdown>
      </Menu>
    </Ctx.Provider>
  );
}

/* what the last check or save said, above the canvas */
function ReportStrip({ R, problems, onStep, onNumber, onReload }: {
  R: Report | null; problems: { id?: string; name?: string; message: string }[];
  onStep: (id: string) => void; onNumber: (name: string) => void; onReload: () => void;
}) {
  useLang();
  const item = (e: { id?: string; name?: string; message: string }, i: number) => (
    <List.Item key={i}>
      {e.id ? <><Anchor component="button" type="button" onClick={() => onStep(e.id!)}>{e.id}</Anchor>: </> : null}
      {e.name ? <><Anchor component="button" type="button" onClick={() => onNumber(e.name!)}>{e.name}</Anchor>: </> : null}
      {rich(tr(e.message))}
    </List.Item>
  );
  if (!R) {
    if (!problems || !problems.length) return null;
    return <Box px="md" pb={8}><Alert color="red" title={t('The flow on disk has problems')}><List size="sm">{problems.map(item)}</List></Alert></Box>;
  }
  if (R.error) return <Box px="md" pb={8}><Alert color="red">{R.error}</Alert></Box>;
  const r = R.r || {};
  const errs: { id?: string; name?: string; message: string }[] = r.errors || [];
  return (
    <ScrollArea.Autosize mah="32vh" px="md" pb={8}>
      <Stack gap="xs">
        {R.source === 'save' && r.reason === 'moved' && (
          <Alert color="red"><Group justify="space-between"><Text size="sm">{r.message}</Text><Button size="xs" color="red" variant="white" onClick={onReload}>{t('Reload from disk')}</Button></Group></Alert>
        )}
        {errs.length > 0 && <Alert color="red" title={t('The run could not do this ({n})', { n: errs.length })}><List size="sm" spacing={2}>{errs.map(item)}</List></Alert>}
        {!errs.length && r.ok && <Alert color="teal" title={t('The run can do this flow.')} />}
        {!errs.length && (r.changed || []).length > 0 && (
          <Alert color="gray" title={t('Changes')}>
            <List size="sm" spacing={2}>{r.changed.map((c: any, i: number) => <List.Item key={i}>{c.name === 'flow' ? tr(c.to) : <><Code>{c.name}</Code>: {String(c.from)} → {String(c.to)}</>}</List.Item>)}</List>
          </Alert>
        )}
        {(r.diff || []).length > 0 && (
          <Accordion variant="contained">
            <Accordion.Item value="diff"><Accordion.Control>{t('Diff of {file}', { file: r.file || t('the file') })}</Accordion.Control>
              <Accordion.Panel><Diff text={r.diff} /></Accordion.Panel></Accordion.Item>
          </Accordion>
        )}
        {(r.says || []).map((s: string, i: number) => <Text key={i} size="sm" c="dimmed">{rich(tr(s))}</Text>)}
        {R.source === 'save' && !r.saved && r.reason === 'invalid' && <Badge color="red">{t('Not saved')}</Badge>}
      </Stack>
    </ScrollArea.Autosize>
  );
}
