/* The Graph tab: the drawing of how the harvest becomes the graph. Left the fields of the harvest as the spec asks them,
   right the boxes (a class each) with the properties the shapes give it; arrows from a field to a property, from a field
   to a box (it makes the box's nodes) and from a box to a box over a property. A click opens the settings of a box, an
   arrow or the document; below, with a harvest loaded, the triples of one document as the run would write them. The
   drawing (`map` of the graph file) is edited in place and sent whole by Check and Save; no position is kept. */
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import {
  Background, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow, type Connection, type Edge, type Node,
} from '@xyflow/react';
import {
  Accordion, ActionIcon, Alert, Anchor, Badge, Box, Button, Center, Code, Collapse, Drawer, Group, List, Loader, Modal, ScrollArea, Select, Stack,
  Switch, Text, TextInput, Tooltip, UnstyledButton,
} from '@mantine/core';
import {
  IconArrowBackUp, IconArrowForwardUp, IconBox, IconCheck, IconChevronDown, IconChevronUp, IconDeviceFloppy, IconFocusCentered,
  IconPlayerPlay, IconPlus, IconSearch, IconSettings, IconX,
} from '@tabler/icons-react';
import { api, apiR } from '../lib/api';
import { askConfirm, showError, showInfo } from '../lib/dialogs';
import { loadState, setDirty, tabStore, useRequests, useTabActions } from '../lib/nav';
import { rich, t, tn, tr, useLang } from '../lib/i18n';
import { wrote } from '../lib/util';
import { Diff } from '../components/Bits';
import { TextBox } from '../components/Inputs';
import { GroupedRules } from '../rules/RuleInputs';
import { Put } from '../prompts/Reports';
import type { Edit, Kit } from './inputs';
import {
  arrowKey, clone, curOf, freshBoxId, isRed, layout, localName, removeBox, rowsOf, takesFields,
  type Cur, type Decor, type GraphData, type Obj, type Problem,
} from './model';
import { ArrowEdge, BoxNode, Ctx, FieldNode, LabelNode, type GraphCtx } from './nodes';
import { ArrowSettings, BoxSettings, DocumentSettings, type Panel } from './Settings';
import './graph.css';

const nodeTypes = { field: FieldNode, box: BoxNode, label: LabelNode };
const edgeTypes = { arrow: ArrowEdge };
const edgeDefaults = { markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 } };
const flowWords = () => ({
  'node.a11yDescription.default': t('Press Enter or Space to choose this and Escape to cancel.'),
  'node.a11yDescription.keyboardDisabled': t('Press Enter or Space to choose this and Escape to cancel.'),
  'edge.a11yDescription.default': t('Press Enter or Space to choose this arrow and Escape to cancel.'),
  'controls.ariaLabel': t('View of the drawing'),
  'controls.zoomIn.ariaLabel': t('Zoom in'),
  'controls.zoomOut.ariaLabel': t('Zoom out'),
  'controls.fitView.ariaLabel': t('Show the whole drawing'),
  'minimap.ariaLabel': t('Overview of the drawing'),
  'handle.ariaLabel': t('End of an arrow'),
});

interface Report { source: 'check' | 'save'; r?: any; error?: string }
type Sel = { kind: 'box' | 'arrow' | 'field' | null; id: string | null };
interface Preview { open: boolean; doc: string | null; strict: boolean; seq: number; loading: boolean; result: any; error: string | null }
interface State {
  data: GraphData | null; cur: Cur | null; error: string | null; undo: string[]; redo: string[]; snap: string; was: string;
  lastKey: string | null; lastAt: number; sel: Sel; expanded: Set<string>; report: Report | null; busy: boolean; fit: number;
  pv: Preview; probe: any; probing: boolean; db: string;
}

export function GraphTab() {
  return <ReactFlowProvider><GraphInner /></ReactFlowProvider>;
}

function GraphInner() {
  const lang = useLang();
  const G = useRef<State>({
    data: null, cur: null, error: null, undo: [], redo: [], snap: '', was: '', lastKey: null, lastAt: 0, sel: { kind: null, id: null },
    expanded: new Set(), report: null, busy: false, fit: 0,
    pv: { open: true, doc: null, strict: false, seq: 0, loading: false, result: null, error: null }, probe: null, probing: false, db: '',
  }).current;
  const [version, touch] = useReducer((x: number) => x + 1, 0);
  const [adding, setAdding] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [probeOpen, setProbeOpen] = useState(false);
  const flow = useReactFlow();
  const canvas = useRef<HTMLDivElement>(null);

  const stamp = () => JSON.stringify(G.cur);
  const dirty = () => !!G.data && stamp() !== G.was;

  /* ---- loading, undo, check, save ---- */
  const load = async () => {
    try {
      const d = await api<GraphData>('GET', '/api/graph');
      G.data = d; G.cur = curOf(d); G.error = null; G.snap = G.was = stamp(); G.undo = []; G.redo = []; G.report = null; G.fit++;
      G.sel = { kind: null, id: null };
      if (!G.pv.doc && d.documents.length) G.pv.doc = d.documents[0];
    } catch (e) { G.error = (e as Error).message; }
    touch();
  };
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setDirty('graph', dirty()); });

  const remember = (key?: string) => {
    const now = stamp();
    if (now === G.snap) return;
    const together = !!key && key === G.lastKey && Date.now() - G.lastAt < 1500;
    if (!together) { G.undo.push(G.snap); G.redo = []; }
    G.snap = now; G.lastKey = key || null; G.lastAt = Date.now();
  };
  const edit: Edit = (fn, key) => { fn(); G.report = null; remember(key); touch(); };
  const restore = (s: string) => {
    G.cur = JSON.parse(s); G.snap = s; G.report = null; G.lastKey = null;
    const ids = new Set(((G.cur as Cur).map.boxes || []).map((b: Obj) => b.id));
    if (G.sel.kind === 'box' && !ids.has(G.sel.id)) G.sel = { kind: null, id: null };
    if (G.sel.kind === 'arrow' && !((G.cur as Cur).map.arrows || []).some((a: Obj) => arrowKey(a) === G.sel.id)) G.sel = { kind: null, id: null };
    touch();
  };
  const undo = () => { if (!G.undo.length) return; G.redo.push(G.snap); restore(G.undo.pop()!); };
  const redo = () => { if (!G.redo.length) return; G.undo.push(G.snap); restore(G.redo.pop()!); };

  const send = async (what: 'check' | 'save') => {
    if (G.busy || !G.data || !G.cur) return;
    if (what === 'save' && !dirty()) return;
    G.busy = true; touch();
    try {
      const r = await apiR('/api/graph/' + what, what === 'save' ? { data: G.cur, base: G.data.base } : { data: G.cur });
      if (what === 'save' && r.saved) {
        showInfo(t('Saved {file} ({writes}).', { file: r.file, writes: wrote(r.writes) }));
        G.busy = false;
        loadState().catch(showError);
        await load();
        return;
      }
      G.report = { source: what, r };
    } catch (e) { G.report = { source: what, error: (e as Error).message }; }
    G.busy = false; touch();
  };
  /* the Sources tab hands over the drawing a merge or a new field changed */
  useRequests('graph', !!G.data, (p: { map?: Obj }) => {
    if (p.map) edit(() => { G.cur!.map = clone(p.map as Obj); G.fit++; });
  });
  useTabActions('graph', { check: () => send('check'), save: () => send('save') });
  useEffect(() => {
    const keys = (ev: KeyboardEvent) => {
      const cur = tabStore.get();
      if (cur.tab !== 'graph' || cur.rules || !(ev.ctrlKey || ev.metaKey)) return;
      const el = ev.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
      const k = ev.key.toLowerCase();
      if (k === 'z' && !ev.shiftKey) { ev.preventDefault(); undo(); }
      else if (k === 'y' || (k === 'z' && ev.shiftKey)) { ev.preventDefault(); redo(); }
    };
    window.addEventListener('keydown', keys);
    return () => window.removeEventListener('keydown', keys);
  });

  /* ---- the preview of one document ---- */
  const pvKey = G.pv.open && G.pv.doc && G.data && G.data.harvest ? G.snap + '|' + G.pv.doc + '|' + G.pv.strict + '|' + G.db : '';
  useEffect(() => {
    if (!pvKey || !G.cur) return;
    const seq = ++G.pv.seq;
    const handle = setTimeout(async () => {
      G.pv.loading = true; touch();
      try {
        const r = await api('POST', '/api/graph/preview', { data: G.cur, document: G.pv.doc, strict: G.pv.strict, db: G.db || null });
        if (seq === G.pv.seq) { G.pv.result = r; G.pv.error = null; }
      } catch (e) { if (seq === G.pv.seq) { G.pv.error = (e as Error).message; G.pv.result = null; } }
      if (seq === G.pv.seq) { G.pv.loading = false; touch(); }
    }, 500);
    return () => clearTimeout(handle);
  }, [pvKey]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- what is red ---- */
  const problems = useMemo(() => {
    const boxes = new Set<string>(), arrows = new Set<string>();
    const r = G.report && G.report.r;
    for (const p of ((r && r.problems) || []) as Problem[]) { if (p.box) boxes.add(p.box); if (p.arrow) arrows.add(p.arrow); }
    return { boxes, arrows };
  }, [version]); // eslint-disable-line react-hooks/exhaustive-deps

  const placed = useMemo(() => {
    if (!G.data || !G.cur) return { nodes: [] as Node[], edges: [] as Edge[] };
    const decor: Decor = { selected: G.sel, problems, expanded: G.expanded, d: G.data, map: G.cur.map };
    return layout(G.data, decor);
  }, [version, problems, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  const fitAll = useCallback((duration = 300) => { flow.fitView({ padding: 0.08, maxZoom: 1, duration }); }, [flow]);
  useEffect(() => {
    if (!G.fit) return;
    const h = setTimeout(() => fitAll(300), 150);
    return () => clearTimeout(h);
  }, [G.fit]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- edits of the drawing ---- */
  const select = (kind: Sel['kind'], id: string | null) => { G.sel = { kind, id }; touch(); };
  const removeArrow = (a: Obj) => edit(() => {
    const key = arrowKey(a);
    G.cur!.map.arrows = (G.cur!.map.arrows || []).filter((x: Obj) => arrowKey(x) !== key);
    if (G.sel.kind === 'arrow' && G.sel.id === key) G.sel = { kind: null, id: null };
  });
  const dropBox = async (id: string) => {
    const n = (G.cur!.map.arrows || []).filter((a: Obj) => a.from === id || a.to === id).length;
    if (n && !await askRemove(id, n)) return;
    edit(() => { removeBox(G.cur!.map, id); if (G.sel.kind === 'box' && G.sel.id === id) G.sel = { kind: null, id: null }; });
  };
  const addNodeArrow = (boxId: string, curie: string) => {
    const brick = G.data!.bricks.find(b => b.kind === 'object' && b.per === 'node');
    edit(() => {
      const map = G.cur!.map;
      map.arrows = [...(map.arrows || []), { from: boxId, to: boxId, property: curie, ...(brick ? { brick: brick.name } : {}) }];
      G.sel = { kind: 'arrow', id: `${boxId}>${boxId} ${curie}` };
    });
  };
  const addBox = (cls: { curie: string | null; label: string } | null) => {
    edit(() => {
      const map = G.cur!.map;
      const id = freshBoxId(map, cls ? cls.label : 'box');
      const box: Obj = { id, count: 'per_document', address: { folder: id, key: id, from: [], fold: true } };
      if (cls && cls.curie) box.class = cls.curie;
      map.boxes = [...(map.boxes || []), box];
      if (!map.prefixes) map.prefixes = {};
      G.sel = { kind: 'box', id };
      G.fit++;
    });
    setAdding(false);
  };
  const connect = (c: Connection) => {
    const d = G.data!, map = G.cur!.map;
    const from = c.source || '', to = c.target || '';
    if (!to.startsWith('b:')) return;
    const box = to.slice(2);
    if (from.startsWith('f:') && c.targetHandle && c.targetHandle.startsWith('t:')) {
      const field = from.slice(2), property = c.targetHandle.slice(2);
      const key = arrowKey({ from: field, to: box, property });
      if ((map.arrows || []).some((a: Obj) => arrowKey(a) === key)) { select('arrow', key); return; }
      edit(() => { map.arrows = [...(map.arrows || []), { from: field, to: box, property }]; G.sel = { kind: 'arrow', id: key }; });
    } else if (from.startsWith('f:') && c.targetHandle === 'in') {
      const field = from.slice(2);
      const b = (map.boxes || []).find((x: Obj) => x.id === box);
      if (!b) return;
      if (!takesFields(b.count)) {
        showError(new Error(t('This box has one node per document, so a field cannot make its nodes. Change "How many nodes" in its settings first, or draw the arrow to one of its properties.')));
        return;
      }
      edit(() => {
        if (b.count === 'per_answer') b.of = field;
        else { const list: string[] = typeof b.of === 'string' ? [b.of] : Array.isArray(b.of) ? b.of.filter((x: unknown) => typeof x === 'string') : []; if (!list.includes(field)) b.of = [...list, field]; }
        G.sel = { kind: 'box', id: box };
      });
    } else if (from.startsWith('b:') && c.sourceHandle && c.sourceHandle.startsWith('s:') && c.targetHandle === 'in') {
      const property = c.sourceHandle.slice(2), source = from.slice(2);
      if (source === box) return;
      const key = arrowKey({ from: source, to: box, property });
      if ((map.arrows || []).some((a: Obj) => arrowKey(a) === key)) { select('arrow', key); return; }
      edit(() => { map.arrows = [...(map.arrows || []), { from: source, to: box, property }]; G.sel = { kind: 'arrow', id: key }; });
    }
    void d;
  };
  const isValid = (c: Connection | Edge) => {
    const s = c.source || '', tg = c.target || '';
    const th = (c as Connection).targetHandle || '', sh = (c as Connection).sourceHandle || '';
    if (!tg.startsWith('b:')) return false;
    if (s.startsWith('f:')) return th === 'in' || th.startsWith('t:');
    if (s.startsWith('b:')) return sh.startsWith('s:') && th === 'in' && s !== tg;
    return false;
  };
  const onEdgesDelete = (gone: Edge[]) => {
    edit(() => {
      for (const e of gone) {
        const dd = e.data as Obj;
        if (dd.kind === 'of') {
          const b = (G.cur!.map.boxes || []).find((x: Obj) => x.id === dd.box);
          if (b) { if (typeof b.of === 'string') delete b.of; else if (Array.isArray(b.of)) { b.of = b.of.filter((x: unknown) => x !== dd.field); if (!b.of.length) delete b.of; } }
        } else {
          G.cur!.map.arrows = (G.cur!.map.arrows || []).filter((x: Obj) => arrowKey(x) !== dd.key);
        }
      }
      G.sel = { kind: null, id: null };
    });
  };

  /* ---- showing a problem ---- */
  const reveal = (p: Problem) => {
    if (p.arrow) G.sel = { kind: 'arrow', id: p.arrow };
    else if (p.box) G.sel = { kind: 'box', id: p.box };
    else return;
    touch();
    const ids = p.arrow ? [p.arrow.split('>')[0], (p.arrow.split('>')[1] || '').split(' ')[0]] : [p.box!];
    setTimeout(() => {
      const nodes = ids.map(i => G.cur!.map.boxes.find((b: Obj) => b.id === i) ? { id: 'b:' + i } : { id: 'f:' + i });
      flow.fitView({ nodes, maxZoom: 1, duration: 400, padding: 0.5 });
    }, 80);
  };

  const discard = async () => {
    if (!G.data || !dirty() || G.busy) return;
    if (!await askConfirm(t('Discard changes'), t('Discard the edited drawing? Ctrl+Z brings it back.'), t('Discard'))) return;
    const old = G.snap;
    G.cur = curOf(G.data); G.undo.push(old); G.redo = []; G.snap = stamp(); G.report = null; G.lastKey = null;
    G.sel = { kind: null, id: null }; G.fit++; touch();
  };

  const probe = async () => {
    if (G.probing || !G.cur) return;
    G.probing = true; touch();
    try { G.probe = await api('POST', '/api/graph/probe', { data: G.cur, db: G.db || null }); } catch (e) { showError(e); }
    G.probing = false; touch();
  };

  if (G.error) return <Alert color="red" m="md">{G.error}</Alert>;
  if (!G.data || !G.cur) return <Center h="100%"><Loader /></Center>;
  const d = G.data, cur = G.cur;
  const map = cur.map;
  const missing = ((map.boxes || []) as Obj[]).reduce((n, b) => n + rowsOf(d, b).filter(isRed).length, 0);
  const isDirty = dirty();

  const ctx: GraphCtx = {
    selectBox: id => select('box', id), selectArrow: key => select('arrow', key),
    toggleRows: id => { if (G.expanded.has(id)) G.expanded.delete(id); else G.expanded.add(id); touch(); },
    addNodeArrow, removeBox: id => { void dropBox(id); },
    does: name => { const b = d.bricks.find(x => x.name === name); return b ? tr(b.does) : ''; }, d,
  };
  const kit: Kit = { d, edit };
  const panel: Panel = { d, cur, kit, remove: removeArrow, removeBox: id => { void dropBox(id); }, select: (k, id) => select(k, id) };
  const selBox = G.sel.kind === 'box' ? (map.boxes || []).find((b: Obj) => b.id === G.sel.id) : null;
  const selArrow = G.sel.kind === 'arrow' ? (map.arrows || []).find((a: Obj) => arrowKey(a) === G.sel.id) : null;
  const selField = G.sel.kind === 'field' ? d.fields.find(f => f.name === G.sel.id) : null;
  const status = !d.exists ? t('not written yet') : d.map_owner ? t('drawing of {owner}', { owner: d.map_owner }) : t('this profile has no drawing yet');

  return (
    <Ctx.Provider value={ctx}>
      <Stack gap={0} h="100%">
        <Group px="md" py={8} gap="sm" justify="space-between" className="gr-bar" wrap="nowrap">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <Code>{d.file}</Code>
            <Text size="sm" c="dimmed" lineClamp={1}>{status}</Text>
            {missing > 0 && <Tooltip label={t('Required by the shapes, and no arrow leads to them yet')}><Badge color="red" variant="light" tt="none" size="lg">{tn(missing, '{n} required property without an arrow', '{n} required properties without an arrow')}</Badge></Tooltip>}
          </Group>
          <Group gap={6} wrap="nowrap">
            <Tooltip label={t('Undo (Ctrl+Z)')}><ActionIcon variant="default" size="lg" disabled={!G.undo.length} onClick={undo} aria-label={t('Undo')}><IconArrowBackUp size={18} /></ActionIcon></Tooltip>
            <Tooltip label={t('Redo (Ctrl+Y)')}><ActionIcon variant="default" size="lg" disabled={!G.redo.length} onClick={redo} aria-label={t('Redo')}><IconArrowForwardUp size={18} /></ActionIcon></Tooltip>
            <Tooltip label={t('Show the whole drawing')}><ActionIcon variant="default" size="lg" onClick={() => fitAll()} aria-label={t('Show the whole drawing')}><IconFocusCentered size={18} /></ActionIcon></Tooltip>
            <Button variant="default" leftSection={<IconBox size={16} />} onClick={() => setAdding(true)}>{t('Add a box')}</Button>
            <Button variant="default" leftSection={<IconSettings size={16} />} onClick={() => setRulesOpen(true)}>{t('Rules')}</Button>
            {d.harvest && <Button variant="light" color="orange" leftSection={<IconPlayerPlay size={16} />} loading={G.probing} onClick={() => { setProbeOpen(true); }}>{t('Test write')}</Button>}
            <Button variant="default" leftSection={<IconCheck size={16} />} loading={G.busy} onClick={() => send('check')} title={t('Ctrl+Enter')}>{t('Check')}</Button>
            <Button leftSection={<IconDeviceFloppy size={16} />} disabled={G.busy || !isDirty} onClick={() => send('save')} title={t('Ctrl+S')}>{t('Save')}</Button>
            <Button variant="default" leftSection={<IconX size={16} />} disabled={G.busy || !isDirty} onClick={discard}>{t('Discard')}</Button>
          </Group>
        </Group>
        <ReportStrip R={G.report} onReveal={reveal} onReload={load} />
        <Group gap={0} wrap="nowrap" style={{ flex: 1, minHeight: 0 }} align="stretch">
          <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
            <Box ref={canvas} style={{ flex: 1, minHeight: 0, position: 'relative' }} className="gr-canvas">
              {!(map.boxes || []).length && (
                <Center className="gr-empty"><Alert color="blue" title={t('Nothing is drawn yet')}>{t('Add a box for a class of the shapes, then draw arrows from the fields on the left to its properties.')}</Alert></Center>
              )}
              <ReactFlow nodes={placed.nodes} edges={placed.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} defaultEdgeOptions={edgeDefaults}
                nodesDraggable={false} nodesConnectable elementsSelectable deleteKeyCode={['Backspace', 'Delete']} selectionKeyCode={null}
                multiSelectionKeyCode={null} panOnScroll zoomOnDoubleClick={false} minZoom={0.15} maxZoom={1.6} proOptions={{ hideAttribution: true }}
                ariaLabelConfig={flowWords()} onConnect={connect} isValidConnection={isValid} onEdgesDelete={onEdgesDelete}
                onEdgeClick={(_, e) => { const dd = e.data as Obj; if (dd.kind === 'of') select('box', dd.box); else select('arrow', dd.key); }}
                onNodeClick={(_, n) => { if (n.type === 'field') select('field', String(n.id).slice(2)); }}
                onPaneClick={() => { if (G.sel.kind) select(null, null); }}>
                <Background gap={24} size={1} />
                <MiniMap pannable zoomable nodeStrokeWidth={2} />
                <Controls showInteractive={false} />
              </ReactFlow>
            </Box>
            {d.harvest && <PreviewPane G={G} d={d} touch={touch} />}
          </Stack>
          <ScrollArea w={420} className="gr-side" type="auto">
            <Box p="md">
              {selBox ? <BoxSettings key={String(selBox.id)} P={panel} box={selBox} />
                : selArrow ? <ArrowSettings key={arrowKey(selArrow)} P={panel} arrow={selArrow} />
                  : selField ? <FieldPanel P={panel} f={selField} onArrow={k => select('arrow', k)} />
                    : <DocumentSettings P={panel} />}
            </Box>
          </ScrollArea>
        </Group>
      </Stack>
      <AddBox d={d} opened={adding} onClose={() => setAdding(false)} onPick={addBox} />
      <Drawer opened={rulesOpen} onClose={() => setRulesOpen(false)} position="right" size="lg" title={<Text fw={650}>{t('Rules of the program that writes the graph')}</Text>}>
        <Stack gap="sm">
          <Text size="sm" c="dimmed">{rich(tr(d.cost) + ' ' + tr(d.gate))}</Text>
          <GroupedRules rules={d.rules} epoch={G.fit} curOf={n => cur.rules[n]} onChange={(n, v) => { edit(() => { cur.rules[n] = v; }, 'rule:' + n); }} />
        </Stack>
      </Drawer>
      <ProbeModal G={G} opened={probeOpen} onClose={() => setProbeOpen(false)} run={probe} touch={touch} d={d} />
    </Ctx.Provider>
  );
}

async function askRemove(id: string, n: number): Promise<boolean> {
  return askConfirm(t('Remove the box'), t('Removing {box} also removes the {n} arrows that start or end at it. Ctrl+Z brings them back.', { box: id, n }), t('Remove'));
}

/* ---- what the last check or save said ---- */
function ReportStrip({ R, onReveal, onReload }: { R: Report | null; onReveal: (p: Problem) => void; onReload: () => void }) {
  useLang();
  if (!R) return null;
  if (R.error) return <Box px="md" pb={8}><Alert color="red">{R.error}</Alert></Box>;
  const r = R.r || {};
  const errs: string[] = r.errors || [];
  const located: Problem[] = r.problems || [];
  return (
    <ScrollArea.Autosize mah="30vh" px="md" pb={8}>
      <Stack gap="xs">
        {R.source === 'save' && r.reason === 'moved' && (
          <Alert color="red"><Group justify="space-between"><Text size="sm">{rich(tr(r.message))}</Text><Button size="xs" color="red" variant="white" onClick={onReload}>{t('Reload from disk')}</Button></Group></Alert>
        )}
        {errs.length > 0 && (
          <Alert color="red" title={t('The run could not write this drawing ({n})', { n: errs.length })}>
            <List size="sm" spacing={2}>
              {errs.map((e, i) => {
                const p = located.find(x => x.message === e || e.endsWith(x.message));
                return (
                  <List.Item key={i}>
                    {p && (p.box || p.arrow)
                      ? <Anchor component="button" type="button" ta="left" onClick={() => onReveal(p)}>{e}</Anchor>
                      : e}
                  </List.Item>
                );
              })}
            </List>
          </Alert>
        )}
        {!errs.length && r.ok && <Alert color="teal" title={t('The run can write this drawing.')} />}
        {(r.diff || []).length > 0 && (
          <Accordion variant="contained">
            <Accordion.Item value="diff"><Accordion.Control>{t('Diff of {file}', { file: r.file || t('the file') })}</Accordion.Control>
              <Accordion.Panel><Diff text={r.diff} /></Accordion.Panel></Accordion.Item>
          </Accordion>
        )}
        {(r.says || []).map((s: string, i: number) => <Text key={i} size="sm" c="dimmed">{rich(tr(s))}</Text>)}
      </Stack>
    </ScrollArea.Autosize>
  );
}

/* ---- the triples of one document ---- */
function PreviewPane({ G, d, touch }: { G: State; d: GraphData; touch: () => void }) {
  useLang();
  const pv = G.pv;
  const r = pv.result;
  return (
    <Box className="gr-preview">
      <Group px="md" py={6} gap="sm" justify="space-between" wrap="nowrap" onClick={() => { pv.open = !pv.open; touch(); }} style={{ cursor: 'pointer' }}>
        <Group gap="xs">
          {pv.open ? <IconChevronDown size={16} /> : <IconChevronUp size={16} />}
          <Text fw={650}>{t('The triples of one document, as the run would write them')}</Text>
          {pv.loading && <Loader size="xs" />}
          {r && r.triples != null && !pv.loading && <Badge variant="light" tt="none">{tn(r.triples, '{n} triple', '{n} triples')}</Badge>}
        </Group>
        <Group gap="sm" wrap="nowrap" onClick={e => e.stopPropagation()}>
          <Switch size="sm" checked={pv.strict} label={t('Strict graph')} onChange={e => { pv.strict = e.currentTarget.checked; touch(); }} />
          <TextBox size="xs" w={260} mono placeholder={t("corpus database (default: the profile's)")} value={G.db} onText={v => { G.db = v; touch(); }} />
          <Select size="xs" w={300} searchable allowDeselect={false} data={d.documents} value={pv.doc} onChange={v => { pv.doc = v; touch(); }} aria-label={t('Document')} />
        </Group>
      </Group>
      <Collapse expanded={pv.open}>
        <Box className="gr-pre" px="md" pb="sm">
          {pv.error ? <Alert color="red">{rich(tr(pv.error))}</Alert>
            : r ? (
              <Stack gap={4}>
                {!r.text && !r.database && <Alert color="orange">{t('This drawing writes nothing for this document. The profile may need its corpus database: give its path above.')}</Alert>}
                <pre className="gr-ttl">{r.text || t('This drawing writes nothing for this document.')}</pre>
              </Stack>)
              : <Text size="sm" c="dimmed">{t('Choose a document.')}</Text>}
        </Box>
      </Collapse>
    </Box>
  );
}

/* ---- a field of the harvest ---- */
function FieldPanel({ P, f, onArrow }: { P: Panel; f: GraphData['fields'][number]; onArrow: (key: string) => void }) {
  const mine = (P.cur.map.arrows || []).filter((a: Obj) => a.from === f.name);
  const boxes = (P.cur.map.boxes || []).filter((b: Obj) => (Array.isArray(b.of) ? b.of : [b.of]).includes(f.name));
  return (
    <Stack gap="sm" data-settings="field">
      <Text fw={700} size="lg">{f.label}</Text>
      {f.help && <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>{f.help}</Text>}
      {f.example ? <Text size="sm">{t('For example: {value}', { value: f.example.value })}</Text> : null}
      {f.example ? <Text size="xs" c="dimmed">{t('Read in {document}', { document: f.example.document })}</Text> : null}
      <Text size="xs" c="dimmed">{rich(t('In the drawing: `{key}`', { key: f.name }))}</Text>
      <Text size="sm" fw={500}>{t('Arrows from this field')}</Text>
      {mine.length ? (
        <Stack gap={2}>
          {mine.map((a: Obj) => (
            <Anchor key={arrowKey(a)} component="button" type="button" ta="left" size="sm" onClick={() => onArrow(arrowKey(a))}>
              {t('{property} of {box}', { property: localName(a.property), box: String(a.to) })}
            </Anchor>
          ))}
        </Stack>
      ) : <Text size="sm" c="dimmed">{t('No arrow starts here yet. Drag from the dot on the right of the field to a property of a box.')}</Text>}
      {boxes.length > 0 && <Text size="sm">{t('It makes the nodes of {boxes}.', { boxes: boxes.map((b: Obj) => b.id).join(', ') })}</Text>}
    </Stack>
  );
}

/* ---- the classes a new box can be made of ---- */
function AddBox({ d, opened, onClose, onPick }: {
  d: GraphData; opened: boolean; onClose: () => void; onPick: (c: { curie: string | null; label: string } | null) => void;
}) {
  useLang();
  const [q, setQ] = useState('');
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = d.classes.filter(c => c.curie).filter(c => words.every(w => ((c.label || '') + ' ' + c.id + ' ' + (c.shape || '')).toLowerCase().includes(w)));
  return (
    <Modal opened={opened} onClose={() => { setQ(''); onClose(); }} size="lg" title={<Text fw={650}>{t('Add a box')}</Text>}>
      <Stack gap="sm">
        <TextInput leftSection={<IconSearch size={16} />} placeholder={t('Search the classes of the shapes')} value={q} data-autofocus onChange={e => setQ(e.currentTarget.value)} />
        {d.skipped && <Alert color="orange">{rich(tr(d.skipped))}</Alert>}
        <ScrollArea.Autosize mah="55vh">
          <Stack gap={4}>
            {shown.map(c => (
              <UnstyledButton key={c.id} className="gr-pick" onClick={() => { setQ(''); onPick({ curie: c.curie, label: c.label || c.id }); }}>
                <Group gap="sm" justify="space-between" wrap="nowrap">
                  <Box style={{ minWidth: 0 }}>
                    <Text fw={600} size="sm">{c.label || c.id}</Text>
                    <Text size="xs" c="dimmed">{tn(c.properties.length, '{n} property in the shapes', '{n} properties in the shapes')}</Text>
                  </Box>
                  <IconPlus size={16} />
                </Group>
              </UnstyledButton>
            ))}
            {!shown.length && <Text size="sm" c="dimmed">{t('No class matches.')}</Text>}
          </Stack>
        </ScrollArea.Autosize>
        <Button variant="default" onClick={() => { setQ(''); onPick(null); }}>{t('A box without a class')}</Button>
      </Stack>
    </Modal>
  );
}

/* ---- "Test write": the saved file and the edited one, on the whole harvest ---- */
function ProbeModal({ G, opened, onClose, run, touch, d }: { G: State; opened: boolean; onClose: () => void; run: () => void; touch: () => void; d: GraphData }) {
  useLang();
  const P = G.probe && G.probe.differs;
  void d;
  return (
    <Modal opened={opened} onClose={onClose} size="xl" title={<Text fw={650}>{t('Test write')}</Text>}>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">{t('Writes the graph of the harvest of this page twice into the temp directory, once with the saved file and once with your edits, and compares the two. Nothing in the profile changes.')}</Text>
        <Group gap="xs" wrap="nowrap">
          <TextBox style={{ flex: 1 }} placeholder={t('corpus database (default: the profile\'s)')} mono value={G.db} onText={text => { G.db = text; touch(); }} />
          <Button loading={G.probing} onClick={run}>{t('Write and compare')}</Button>
        </Group>
        {P && (
          <Stack gap="xs">
            <Text fw={700}>{rich(t('Test write in `{folder}`', { folder: G.probe.folder }))}</Text>
            <Text size="sm">{P.also
              ? t('triples {before} → {after}, nodes given a new name: {renamed}; also written under another property of the spec: {also}', { before: P.triples.before, after: P.triples.after, renamed: P.readdressed, also: P.also })
              : t('triples {before} → {after}, nodes given a new name: {renamed}', { before: P.triples.before, after: P.triples.after, renamed: P.readdressed })}</Text>
            <Accordion variant="contained">
              <Accordion.Item value="docs">
                <Accordion.Control>{t('documents that differ ({n})', { n: P.documents.length })}</Accordion.Control>
                <Accordion.Panel>
                  <Stack gap={2}>
                    {P.documents.map((x: any) => (
                      <Text size="sm" key={x.document}>{x.after.left_out && x.after.left_out.length
                        ? <Put text={t('{doc}: nodes {nb} → {na}, violations {vb} → {va}, left out: {left}')} slots={{ doc: <Code>{x.document}</Code>, nb: x.before.kept || 0, na: x.after.kept || 0, vb: x.before.violations || 0, va: x.after.violations || 0, left: x.after.left_out.map((l: any) => l.constraint).join('; ') }} />
                        : <Put text={t('{doc}: nodes {nb} → {na}, violations {vb} → {va}')} slots={{ doc: <Code>{x.document}</Code>, nb: x.before.kept || 0, na: x.after.kept || 0, vb: x.before.violations || 0, va: x.after.violations || 0 }} />}</Text>
                    ))}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
              <Accordion.Item value="viol">
                <Accordion.Control>{t('violations by constraint')}</Accordion.Control>
                <Accordion.Panel>
                  <Stack gap={2}>
                    {(P.violations || []).map((v: any) => <Text size="sm" key={v.key}><Code>{v.key}</Code>: {v.before} → {v.after}</Text>)}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>
          </Stack>
        )}
      </Stack>
    </Modal>
  );
}
