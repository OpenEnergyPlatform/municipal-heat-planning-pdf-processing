/* The blocks of the drawing (owner request 2026-11-14, wish 4: "die Baublöcke und Einstellungsmöglichkeiten genau wie im
   Flow fein"): where a brick stands, a block may be a brick with its settings, a condition about the reading (for what a
   box or the document takes), steps one after another (on an arrow, for a name), or Python of the drawing's own. A preset
   puts in a block as the shipped drawings have it, to be changed here. An address of a box may be made of parts, each with
   where it comes from, when it counts, how it is written and what an absent one does. Every block can be tried on one
   document of the loaded harvest: what it was given and what it gave, reading by reading. */
import { useEffect, useState } from 'react';
import {
  ActionIcon, Alert, Badge, Box, Button, Code, Group, Loader, NativeSelect, Paper, ScrollArea, Select, SegmentedControl, Stack, Text, Tooltip,
} from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconMinus, IconPlayerPlay, IconPlus, IconX } from '@tabler/icons-react';
import { AreaBox, TextBox } from '../components/Inputs';
import { t, tr } from '../lib/i18n';
import { CondEditor } from '../flow/Conditions';
import { PythonHelp, type PyExample } from '../components/PythonHelp';
import { BrickAbout, BrickSelect, FieldSelect, Flag, SettingsEditor, PairsEditor, bricksOf, type Kit } from './inputs';
import type { BrickInfo, Obj } from './model';

/* which form a block has */
export const formOf = (ref: unknown): 'brick' | 'if' | 'steps' | 'python' | '' => {
  if (typeof ref === 'string') return 'brick';
  if (!ref || typeof ref !== 'object') return '';
  const r = ref as Obj;
  if ('if' in r) return 'if';
  if ('steps' in r) return 'steps';
  if ('python' in r) return 'python';
  return 'brick' in r ? 'brick' : '';
};

const STEP_KINDS = ['object', 'name', 'value'];
const FORMS_OF: Record<string, string[]> = {
  condition: ['brick', 'if', 'python'], object: ['brick', 'steps', 'python'], name: ['brick', 'steps', 'python'],
};
const formWord = (f: string) => ({
  brick: t('A brick'), if: t('A condition'), steps: t('Steps'), python: t('Python'),
} as Record<string, string>)[f] || f;
const PYTHON_START: Record<string, string> = {
  condition: 'def run(call):\n    row = call.row\n    return None\n',
  object: 'def run(call):\n    if call.value is None:\n        return []\n    return [(literal(call.value), call.value)]\n',
  name: 'def run(call):\n    return str(call.value).strip()\n',
};
const pythonStart = (kind: string) => PYTHON_START[kind] || 'def run(call):\n    return None\n';

/* a fresh block of a form, for a place of a kind */
function fresh(k: Kit, kind: string, form: string, was: Obj): Obj {
  const keep: Obj = {};
  for (const key of ['graph', 'document', 'box']) if (key in was) keep[key] = was[key];
  if (form === 'if') return { ...keep, if: { all: [{ of: 'reading', is: 'quantity', op: 'listed' }] }, reason: 'condition' };
  if (form === 'steps') {
    const last = bricksOf(k.d, kind)[0];
    return { ...keep, steps: [{ brick: last ? last.name : 'text' }] };
  }
  if (form === 'python') return { ...keep, python: pythonStart(kind) };
  const first = bricksOf(k.d, kind)[0];
  return { ...keep, brick: first ? first.name : '' };
}

/* a brick as the server sends it: with its own logic as Python */
type PyBrick = BrickInfo & { python?: string };

/* what a block would be in another form, to show and not to store: the drawing changes where it is edited. *made* is
   the block as Python that does the same, as the server writes it for steps and a condition */
function viewOf(k: Kit, kind: string, form: string, was: Obj, made: { python?: string; per?: string; writes?: string } | null): Obj {
  const keep: Obj = {};
  for (const key of ['graph', 'document', 'box']) if (key in was) keep[key] = was[key];
  if (form === 'python' && made && made.python) {
    const own: Obj = { ...keep, python: made.python };
    if (kind === 'object' && made.per && made.per !== 'row') own.per = made.per;
    if (kind === 'object' && made.writes) own.writes = made.writes;
    return own;
  }
  const brick = formOf(was) === 'brick' ? (k.d.bricks as PyBrick[]).find(b => b.name === was.brick) : undefined;
  const carried: Obj = {};
  if (was.settings && typeof was.settings === 'object' && Object.keys(was.settings).length) carried.settings = was.settings;
  if (form === 'brick') return { ...keep, brick: '' };
  if (form === 'steps' && brick) return { ...keep, steps: [{ brick: brick.name, ...carried }] };
  if (form === 'python' && brick && brick.python) {
    const own: Obj = { ...keep, python: brick.python, ...carried };
    if (kind === 'object' && brick.per && brick.per !== 'row') own.per = brick.per;
    if (kind === 'object' && brick.writes) own.writes = brick.writes;
    return own;
  }
  return fresh(k, kind, form, was);
}

/* the presets of a kind, offered to put in */
export function PresetSelect({ k, kind, onPick, label }: { k: Kit; kind: string; onPick: (block: Obj) => void; label?: string }) {
  const list = (k.d.presets || []).filter(p => p.kind === kind);
  if (!list.length) return null;
  return (
    <Select size="xs" label={label} placeholder={t('Put in a preset')} data={list.map(p => ({ value: p.name, label: tr(p.does) }))} value={null}
      comboboxProps={{ width: 460, position: 'bottom-start' }} searchable
      renderOption={({ option }) => (<Box><Text size="sm">{option.label}</Text><Code>{option.value}</Code></Box>)}
      onChange={v => { const p = list.find(x => x.name === v); if (p) onPick(JSON.parse(JSON.stringify(p.block))); }} />
  );
}

/* one block where a brick stands: its form, then what the form has */
/* the preset a block was put in from: the body of a profile finds its arrow by this name */
function PresetFrom({ k, name }: { k: Kit; name: string }) {
  const p = (k.d.presets || []).find(x => x.name === name);
  return (
    <Text size="xs" c="dimmed">{t('Put in from the preset')}: {p ? tr(p.does) : ''} <Code>{name}</Code></Text>
  );
}

export function BlockEditor({ k, kind, refer, onChange, label, withGraph, where }: {
  k: Kit; kind: string; refer: Obj; onChange: (next: Obj) => void; label?: string; withGraph?: boolean; where?: Obj;
}) {
  const stored = formOf(refer) || 'brick';
  const forms = FORMS_OF[kind] || ['brick', 'python'];
  /* the form shown, for the block as it is stored: choosing one changes nothing in the drawing, only what is shown; an edit
     there stores the block in that form */
  const sig = JSON.stringify(refer);
  const [chosen, setChosen] = useState<{ form: string; sig: string } | null>(null);
  const form = chosen && chosen.sig === sig ? chosen.form : stored;
  const previewing = form !== stored;
  /* steps and a condition as Python: the server writes them, the page waits for it */
  const [made, setMade] = useState<{ sig: string; got: { python?: string; per?: string; writes?: string } } | null>(null);
  const asks = previewing && form === 'python' && (stored === 'steps' || stored === 'if') && !!k.pythonOf;
  useEffect(() => {
    if (!asks || (made && made.sig === sig)) return;
    let live = true;
    k.pythonOf!(refer, kind).then(got => { if (live) setMade({ sig, got: got || {} }); }, () => { if (live) setMade({ sig, got: {} }); });
    return () => { live = false; };
  }, [asks, sig]); // eslint-disable-line react-hooks/exhaustive-deps
  const waiting = asks && !(made && made.sig === sig);
  const shown = previewing ? viewOf(k, kind, form, refer, made && made.sig === sig ? made.got : null) : refer;
  const put = (next: Obj) => { setChosen(null); k.edit(() => onChange(next)); };
  const edited = (next: Obj) => { setChosen(null); onChange(next); };
  return (
    <Stack gap="xs">
      {label && <Text size="sm" fw={500}>{label}</Text>}
      <Group gap="xs" align="flex-end" wrap="wrap">
        <SegmentedControl size="xs" value={form} data={forms.map(f => ({ value: f, label: formWord(f) }))}
          onChange={v => setChosen(v === stored ? null : { form: v, sig })} />
        <PresetSelect k={k} kind={kind} onPick={b => put({ ...b, ...(refer.graph ? { graph: refer.graph } : {}) })} />
      </Group>
      {previewing && <Text size="xs" c="orange">{t('Preview: nothing in the drawing changes until you edit here.')}</Text>}
      {refer.preset && !previewing && form !== 'brick' && <PresetFrom k={k} name={refer.preset} />}
      {form === 'brick' && <BrickPart k={k} kind={kind} refer={shown} onChange={edited} />}
      {form === 'if' && <IfPart k={k} refer={shown} onChange={edited} />}
      {form === 'steps' && <StepsPart k={k} kind={kind} refer={shown} onChange={edited} />}
      {form === 'python' && (waiting ? <Loader size="sm" /> : <PythonPart k={k} kind={kind} refer={shown} onChange={edited} />)}
      {withGraph && (
        <Select size="xs" label={t('Which graph')} data={[{ value: 'both', label: t('Both the full and the strict graph') }, { value: 'strict', label: t('Only the strict graph') }, { value: 'full', label: t('Only the full graph') }]}
          value={refer.graph || 'both'} onChange={v => k.edit(() => { const next = { ...refer }; if (!v || v === 'both') delete next.graph; else next.graph = v; onChange(next); })} />
      )}
      {where && !previewing && <TryBlock k={k} where={where} />}
    </Stack>
  );
}

function BrickPart({ k, kind, refer, onChange }: { k: Kit; kind: string; refer: Obj; onChange: (next: Obj) => void }) {
  const brick = k.d.bricks.find(b => b.name === refer.brick);
  return (
    <Stack gap="xs">
      <BrickSelect k={k} kind={kind} value={refer.brick} onChange={v => k.edit(() => {
        if (!v) return;
        const next: Obj = { ...refer, brick: v };
        if (v !== refer.brick) delete next.settings;
        onChange(next);
      })} />
      <BrickAbout brick={brick} />
      <SettingsEditor k={k} brick={brick} settings={refer.settings || {}} onChange={s => {
        const next = { ...refer };
        if (Object.keys(s).length) next.settings = s; else delete next.settings;
        onChange(next);
      }} />
    </Stack>
  );
}

/* a condition about the reading and what is known of the document, and the reason a reading it leaves out is counted
   under */
function IfPart({ k, refer, onChange }: { k: Kit; refer: Obj; onChange: (next: Obj) => void }) {
  const names = k.d.fields.map(f => f.name);
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">{t('A reading is taken where the condition holds. "is an entry of its list in the spec" asks the list of that dimension of the reading\'s field; "names something" asks whether its words name anything once folded.')}</Text>
      <CondEditor subjects={k.d.conditions || []} vars={names} only={null}
        get={() => refer.if || null}
        set={c => k.edit(() => { const next = { ...refer }; if (c) next.if = c; else next.if = { all: [{ of: 'reading', is: 'value', op: 'empty', not: true }] }; onChange(next); })} />
      <TextBox label={t('Reason it is left out')} mono value={refer.reason || ''}
        description={t('Counted in the log for a reading the condition leaves out. {key} is that key of the reading, {a|b|\'?\'} the first of a and b that is there, else the words in quotes.')}
        onText={v => k.edit(() => onChange({ ...refer, reason: v }), 'reason')} />
    </Stack>
  );
}

/* steps one after another: each takes the value the one before it gave; the last one writes the object */
function StepsPart({ k, kind, refer, onChange }: { k: Kit; kind: string; refer: Obj; onChange: (next: Obj) => void }) {
  const steps: Obj[] = Array.isArray(refer.steps) ? refer.steps : [];
  const setSteps = (next: Obj[]) => onChange({ ...refer, steps: next });
  const offered = k.d.bricks.filter(b => STEP_KINDS.includes(b.kind));
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">{kind === 'object'
        ? t('Each step takes the value the one before it gave; the last one writes the object.')
        : t('Each step takes the value the one before it gave; the last one gives the name.')}</Text>
      {steps.map((step, i) => {
        const brick = k.d.bricks.find(b => b.name === step.brick);
        return (
          <Paper key={i} withBorder p="xs" radius="md">
            <Group gap="xs" wrap="nowrap" align="flex-start">
              <Badge variant="light" color="gray">{i + 1}</Badge>
              <Box style={{ flex: 1, minWidth: 0 }}>
                {formOf(step) === 'python'
                  ? (
                    <Stack gap={4}>
                      <AreaBox label={t('Python of this step')} minRows={4} code value={step.python || ''}
                        onText={v => k.edit(() => setSteps(steps.map((x, j) => (j === i ? { ...x, python: v } : x))), 'step-py' + i)} />
                      <PythonHelp where="step" onPut={ex => k.edit(() => setSteps(steps.map((x, j) => (j === i ? { ...x, python: ex.code } : x))))} />
                    </Stack>
                  )
                  : (
                    <Stack gap={4}>
                      <Select size="xs" searchable data={offered.map(b => ({ value: b.name, label: tr(b.does) }))} value={step.brick || null}
                        comboboxProps={{ width: 460 }} onChange={v => v && k.edit(() => setSteps(steps.map((x, j) => (j === i ? { brick: v } : x))))} />
                      <BrickAbout brick={brick} />
                      <SettingsEditor k={k} brick={brick} settings={step.settings || {}} onChange={s => {
                        const next = { ...step };
                        if (Object.keys(s).length) next.settings = s; else delete next.settings;
                        setSteps(steps.map((x, j) => (j === i ? next : x)));
                      }} />
                    </Stack>
                  )}
              </Box>
              <Stack gap={2}>
                <Tooltip label={t('Earlier')}><ActionIcon size="sm" variant="subtle" disabled={i === 0} aria-label={t('Earlier')}
                  onClick={() => k.edit(() => { const n = steps.slice(); [n[i - 1], n[i]] = [n[i], n[i - 1]]; setSteps(n); })}><IconArrowUp size={14} /></ActionIcon></Tooltip>
                <Tooltip label={t('Later')}><ActionIcon size="sm" variant="subtle" disabled={i === steps.length - 1} aria-label={t('Later')}
                  onClick={() => k.edit(() => { const n = steps.slice(); [n[i + 1], n[i]] = [n[i], n[i + 1]]; setSteps(n); })}><IconArrowDown size={14} /></ActionIcon></Tooltip>
                <Tooltip label={t('Remove the step')}><ActionIcon size="sm" variant="subtle" color="red" disabled={steps.length < 2} aria-label={t('Remove the step')}
                  onClick={() => k.edit(() => setSteps(steps.filter((_, j) => j !== i)))}><IconMinus size={14} /></ActionIcon></Tooltip>
              </Stack>
            </Group>
          </Paper>
        );
      })}
      <Group gap="xs">
        <Button size="compact-xs" variant="light" leftSection={<IconPlus size={12} />}
          onClick={() => k.edit(() => setSteps([...steps, { brick: (offered.find(b => b.kind === 'value') || offered[0] || { name: 'text' }).name }]))}>{t('step')}</Button>
        <Button size="compact-xs" variant="subtle" leftSection={<IconPlus size={12} />}
          onClick={() => k.edit(() => setSteps([...steps, { python: 'def run(call):\n    return call.value\n' }]))}>{t('Python step')}</Button>
      </Group>
      {kind === 'object' && (
        <TextBox label={t('What it writes, for the check against the ontology')} mono value={refer.writes || ''}
          description={t('Empty: what the last step writes. answers, entries, key:<name>, xsd:<type>.')}
          onText={v => k.edit(() => { const next = { ...refer }; if (v) next.writes = v; else delete next.writes; onChange(next); }, 'writes')} />
      )}
    </Stack>
  );
}

/* Python of the drawing's own: run(call) gives what a block of this kind gives */
function PythonPart({ k, kind, refer, onChange }: { k: Kit; kind: string; refer: Obj; onChange: (next: Obj) => void }) {
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">{t('The code defines run(call). call has doc, node, row, value, settings, label, source and rows; beside it stand kg (the profile\'s own module of the graph), log, literal, in_graph, is_class and ttl_string. It runs in the run\'s own process.')}</Text>
      <AreaBox label={t('Python')} minRows={8} code value={refer.python || ''} onText={v => k.edit(() => onChange({ ...refer, python: v }), 'python')} />
      <PythonHelp where={kind} onPut={(ex: PyExample) => k.edit(() => {
        const next: Obj = { ...refer, python: ex.code };
        if (kind === 'object') { if (ex.per) next.per = ex.per; else delete next.per; }
        onChange(next);
      })} />
      {kind === 'object' && (
        <NativeSelect size="xs" label={t('Called')} value={refer.per || 'row'}
          data={[{ value: 'row', label: t('once per reading') }, { value: 'node', label: t('once per node, with all its readings') }]}
          onChange={e => { const v = e.currentTarget.value; k.edit(() => { const next = { ...refer }; if (v === 'row') delete next.per; else next.per = v; onChange(next); }); }} />
      )}
      {kind === 'object' && (
        <TextBox label={t('What it writes, for the check against the ontology')} mono value={refer.writes || ''}
          description={t('answers, entries, key:<name>, xsd:<type>; empty: nothing known.')}
          onText={v => k.edit(() => { const next = { ...refer }; if (v) next.writes = v; else delete next.writes; onChange(next); }, 'writes')} />
      )}
      <Box>
        <Text size="sm" fw={500}>{t('Settings')}</Text>
        <Text size="xs" c="dimmed">{t('What the code reads as call.settings.')}</Text>
        <PairsEditor value={refer.settings && typeof refer.settings === 'object' ? refer.settings : {}}
          onChange={v => k.edit(() => { const next = { ...refer }; if (Object.keys(v).length) next.settings = v; else delete next.settings; onChange(next); }, 'py-settings')} />
      </Box>
    </Stack>
  );
}

/* ---- trying one block ---- */
export function TryBlock({ k, where }: { k: Kit; where: Obj }) {
  const [state, setState] = useState<{ loading: boolean; result: any; error: string | null }>({ loading: false, result: null, error: null });
  const [doc, setDoc] = useState<string | null>(null);
  if (!k.tryBlock || !k.d.harvest || !k.d.documents.length) return null;
  const run = async () => {
    setState({ loading: true, result: null, error: null });
    try { setState({ loading: false, result: await k.tryBlock!(where, doc || k.d.documents[0]), error: null }); }
    catch (e) { setState({ loading: false, result: null, error: (e as Error).message }); }
  };
  const r = state.result;
  return (
    <Stack gap={4}>
      <Group gap="xs" align="flex-end" wrap="wrap">
        <Select size="xs" w={260} searchable label={t('Try it on a document')} data={k.d.documents} value={doc || k.d.documents[0]} onChange={setDoc} />
        <Button size="xs" variant="light" leftSection={state.loading ? <Loader size={12} /> : <IconPlayerPlay size={14} />} onClick={run} disabled={state.loading}>{t('Try')}</Button>
        {r && <Button size="compact-xs" variant="subtle" leftSection={<IconX size={12} />} onClick={() => setState({ loading: false, result: null, error: null })}>{t('Close')}</Button>}
      </Group>
      {state.error && <Alert color="red" p="xs">{state.error}</Alert>}
      {r && (
        <Paper withBorder p="xs" radius="md">
          <Text size="xs" c="dimmed">{t('Called {n} times while {document} was written; the first {m} are shown.', { n: r.calls, document: r.document, m: Math.min(r.calls, r.most) })}</Text>
          <ScrollArea.Autosize mah={360}>
            <Stack gap={6}>
              {(r.shown as Obj[]).map((x, i) => (
                <Paper key={i} withBorder p={6} radius="sm">
                  <Text size="xs" fw={600}>{t('Given')}</Text>
                  <Code block fz={10}>{Object.entries(x.reading || {}).map(([a, b]) => a + ': ' + JSON.stringify(b)).join('\n')}</Code>
                  {x.parts && <Text size="xs" fw={600}>{t('Parts')}</Text>}
                  {x.parts && <Code block fz={10}>{(x.parts as unknown[]).map(p => JSON.stringify(p)).join('\n')}</Code>}
                  <Text size="xs" fw={600}>{t('Gave')}</Text>
                  <Code block fz={10}>{x.gives === null || x.gives === undefined ? t('nothing') : typeof x.gives === 'string' ? x.gives : JSON.stringify(x.gives, null, 1)}</Code>
                </Paper>
              ))}
            </Stack>
          </ScrollArea.Autosize>
        </Paper>
      )}
    </Stack>
  );
}

/* ---- an address made of parts ---- */
const partWords = () => ({
  reading: t('a key of the reading'), chosen: t('the one reading of a field the document gives'), name: t('the name of the node'),
  key: t('the key of the node'), fact: t('a fact of the document'), answer_address: t('the address of the answer in the table of a box'),
  wording: t('the words that split a number from another'),
} as Record<string, string>);
const formWords = () => ({
  text: t('as it is'), iri: t('prefix and value'), class: t('prefix and value, only where it is a class'), fold: t('folded words'),
} as Record<string, string>);
const absentWords = () => ({
  refuse: t('no address at all'), empty: t('an empty part'), omit: t('left out'),
} as Record<string, string>);

/* a token of an address as a part: @name, @key, @fact:x, a field's name */
export function asPart(token: unknown): Obj {
  if (token && typeof token === 'object') return token as Obj;
  const s = String(token);
  if (s === '@name') return { from: 'name' };
  if (s === '@key') return { from: 'key' };
  if (s.startsWith('@fact:')) return { from: 'fact', of: s.slice(6) };
  return { from: 'chosen', of: s };
}

export function PartsEditor({ k, parts, onChange }: { k: Kit; parts: unknown[]; onChange: (next: unknown[]) => void }) {
  const boxes = ((k.cur && k.cur.map && k.cur.map.boxes) || []) as Obj[];
  const prefixes = Object.keys((k.cur && k.cur.map && k.cur.map.prefixes) || {});
  const pw = partWords(), fw = formWords(), aw = absentWords();
  const setPart = (i: number, next: Obj, typing?: string) => k.edit(() => onChange(parts.map((x, j) => (j === i ? next : x))), typing);
  return (
    <Stack gap="xs">
      {parts.map((token, i) => {
        const p = asPart(token);
        const from = p.from || 'reading';
        const put = (key: string, v: unknown, typing?: string) => {
          const next = { ...p };
          if (v === undefined || v === null || v === '' || v === false) delete next[key]; else next[key] = v;
          setPart(i, next, typing);
        };
        return (
          <Paper key={i} withBorder p="xs" radius="md">
            <Group gap="xs" wrap="nowrap" align="flex-start">
              <Badge variant="light" color="gray">{i + 1}</Badge>
              <Stack gap={6} style={{ flex: 1, minWidth: 0 }}>
                <Select size="xs" label={t('Made from')} allowDeselect={false} data={(k.d.part_from || []).map(v => ({ value: v, label: pw[v] || v }))} value={from}
                  onChange={v => v && put('from', v === 'reading' ? undefined : v)} />
                {['reading', 'chosen', 'answer_address'].includes(from) && (
                  <FieldSelect k={k} label={from === 'chosen' ? t('Field') : t('Key of the reading')} value={p.of} onChange={v => put('of', v)} />
                )}
                {from === 'fact' && <TextBox label={t('Fact')} mono value={p.of || ''} onText={v => put('of', v, 'part-of' + i)} />}
                {from === 'answer_address' && (
                  <Select size="xs" label={t('Box with the table')} data={boxes.filter(b => b.table).map(b => ({ value: b.id, label: String(b.id) }))} value={p.box || null}
                    onChange={v => put('box', v)} />
                )}
                {from !== 'answer_address' && from !== 'wording' && (
                  <Group gap="xs" grow>
                    <Select size="xs" label={t('Written')} allowDeselect={false} data={(k.d.part_forms || []).map(v => ({ value: v, label: fw[v] || v }))} value={p.form || 'text'}
                      onChange={v => put('form', v === 'text' ? undefined : v)} />
                    {['iri', 'class'].includes(p.form) && (
                      <Select size="xs" label={t('Prefix')} data={prefixes} value={p.prefix || null} onChange={v => put('prefix', v)} />
                    )}
                    {p.form === 'class' && <TextBox label={t('Only the family')} mono value={p.family || ''} onText={v => put('family', v, 'part-fam' + i)} />}
                  </Group>
                )}
                {from === 'reading' && (
                  <Flag label={t('out:total becomes the class the arrow sets for it')} help={t('A number its table does not split by this dimension takes the class the arrow from this dimension writes for it.')}
                    checked={!!p.total} onChange={v => put('total', v)} />
                )}
                <Select size="xs" label={t('Where it is absent')} allowDeselect={false} data={(k.d.part_absent || []).map(v => ({ value: v, label: aw[v] || v }))} value={p.absent || 'refuse'}
                  onChange={v => put('absent', v === 'refuse' ? undefined : v)} />
                <Box>
                  <Text size="xs" fw={500}>{t('Only when')}</Text>
                  <CondEditor subjects={k.d.conditions || []} vars={k.d.fields.map(f => f.name)} only={null} get={() => p.when || null} set={c => put('when', c || undefined)} />
                </Box>
              </Stack>
              <Stack gap={2}>
                <Tooltip label={t('Earlier')}><ActionIcon size="sm" variant="subtle" disabled={i === 0} aria-label={t('Earlier')}
                  onClick={() => k.edit(() => { const n = parts.slice(); [n[i - 1], n[i]] = [n[i], n[i - 1]]; onChange(n); })}><IconArrowUp size={14} /></ActionIcon></Tooltip>
                <Tooltip label={t('Later')}><ActionIcon size="sm" variant="subtle" disabled={i === parts.length - 1} aria-label={t('Later')}
                  onClick={() => k.edit(() => { const n = parts.slice(); [n[i + 1], n[i]] = [n[i], n[i + 1]]; onChange(n); })}><IconArrowDown size={14} /></ActionIcon></Tooltip>
                <Tooltip label={t('Remove the part')}><ActionIcon size="sm" variant="subtle" color="red" aria-label={t('Remove the part')}
                  onClick={() => k.edit(() => onChange(parts.filter((_, j) => j !== i)))}><IconMinus size={14} /></ActionIcon></Tooltip>
              </Stack>
            </Group>
          </Paper>
        );
      })}
      <Box><Button size="compact-xs" variant="light" leftSection={<IconPlus size={12} />} onClick={() => k.edit(() => onChange([...parts, { of: 'value' }]))}>{t('part')}</Button></Box>
    </Stack>
  );
}
