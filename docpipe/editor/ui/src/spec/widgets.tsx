/* The widgets of the forms of the Spec tab: one per kind of key the server's form description names. Each writes into the
   spec object in place (the write rules are lib/spec.ts) and marks the spec edited. */
import { useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react';
import { ActionIcon, Alert, Box, Button, Checkbox, Code, Group, NativeSelect, Stack, Table, Text, Tooltip } from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconPlus, IconTrash, IconX } from '@tabler/icons-react';
import { AreaBox, NumberBox, TextBox } from '../components/Inputs';
import { FormNode, useFormField } from '../components/FormNode';
import { Help, K } from '../components/Bits';
import { DF, type Kind } from '../lib/forms';
import { showError } from '../lib/dialogs';
import {
  entryParts, linesText, writeBool, writeLines, writeNumber, writeString, writeStrings,
} from '../lib/spec';
import { isObj, own, type Obj } from '../lib/util';
import { rich, t, tr } from '../lib/i18n';
import { markDirty, S } from './state';
import { EntriesTable, type ListRef } from './entries';

export interface FormField { key: string; widget: string; help?: string; choices?: string[]; default?: any; of?: string; only?: string[] }
export interface WidgetCtx {
  coordNames?: string[];
  onUri?: (v: string) => void;
  refFor?: (key: string) => ListRef | null;
  skip?: Set<string>;
  skipQuiet?: Set<string>;
}

const useRedraw = () => useReducer((x: number) => x + 1, 0)[1];
/* write into the object, mark the spec edited, draw the widget again; a write that returns false changed nothing */
function useEdit() {
  const redraw = useRedraw();
  return (fn: () => void | false) => { if (fn() === false) return; markDirty(); redraw(); };
}

function FieldWrap({ k, help, children }: { k: string; help?: string; children: ReactNode }) {
  const flagged = S.flag != null && S.flag.field === k;
  return (
    <Box data-key={k} className={flagged ? 'dp-flag' : undefined} p={flagged ? 6 : 0}>
      <Text fw={600} mb={2}><K>{k}</K></Text>
      <Help text={tr(help)} />
      <Box mt={4}>{children}</Box>
    </Box>
  );
}

const str = (v: unknown) => (typeof v === 'string' ? v : v == null ? '' : String(v));

function LineW({ f, obj, ctx }: { f: FormField; obj: Obj; ctx: WidgetCtx }) {
  const edit = useEdit();
  return <TextBox value={str(obj[f.key])} onText={t => edit(() => writeString(obj, f.key, t))}
    onCommit={f.key === 'uri' && ctx.onUri ? t => ctx.onUri!(t) : undefined} />;
}
function TextW({ f, obj }: { f: FormField; obj: Obj }) {
  const edit = useEdit();
  return <AreaBox minRows={4} value={str(obj[f.key])} onText={t => edit(() => writeString(obj, f.key, t))} />;
}
function LinesW({ f, obj }: { f: FormField; obj: Obj }) {
  const edit = useEdit();
  return <AreaBox minRows={6} mono value={linesText(obj[f.key])} onText={t => edit(() => writeLines(obj, f.key, t))} />;
}
function BoolW({ f, obj, orig }: { f: FormField; obj: Obj; orig: Obj | null }) {
  const edit = useEdit();
  const cur = own(obj, f.key) ? !!obj[f.key] : !!f.default;
  return <Checkbox checked={cur} label={own(obj, f.key) ? undefined : t('(not set; default {value})', { value: f.default ? 'true' : 'false' })}
    onChange={e => { const v = e.currentTarget.checked; edit(() => writeBool(obj, f.key, v, f.default, orig)); }} />;
}
function ChoiceW({ f, obj }: { f: FormField; obj: Obj }) {
  const edit = useEdit();
  const cur = obj[f.key];
  const opts = (f.choices || []).slice();
  if (cur != null && !opts.includes(cur)) opts.push(cur);
  return <NativeSelect value={cur == null ? '' : String(cur)}
    data={[{ value: '', label: own(obj, f.key) ? t('(remove)') : t('(not set)') }, ...opts.map(o => ({ value: String(o), label: String(o) }))]}
    onChange={e => { const v = e.currentTarget.value; edit(() => writeString(obj, f.key, v)); }} />;
}
function NumberW({ f, obj }: { f: FormField; obj: Obj }) {
  const edit = useEdit();
  return <NumberBox value={obj[f.key] == null ? '' : String(obj[f.key])} onText={t => edit(() => {
    if (t === '') writeNumber(obj, f.key, '');
    else { const n = Number(t); if (Number.isNaN(n)) return false; writeNumber(obj, f.key, n); }
  })} />;
}

/* a list of strings: one input each, ↑ ↓ × and + Add; keep: an emptied list stays a list */
export function StringsEditor({ obj, k, keep, list }: { obj: Obj; k: string; keep?: boolean; list?: string[] }) {
  const [items, setItems] = useState<string[]>(() => (Array.isArray(obj[k]) ? obj[k].map(String) : []));
  const box = useRef<HTMLDivElement>(null);
  const focusLast = useRef(false);
  useEffect(() => {
    if (!focusLast.current) return;
    focusLast.current = false;
    const ins = box.current?.querySelectorAll('input');
    ins?.[ins.length - 1]?.focus();
  });
  const commit = (next: string[]) => { setItems(next); writeStrings(obj, k, next, keep); markDirty(); };
  const swap = (i: number, j: number) => { const n = items.slice(); [n[i], n[j]] = [n[j], n[i]]; commit(n); };
  return (
    <Stack gap="xs" ref={box}>
      {items.map((s, i) => (
        <Group key={i} gap="xs" wrap="nowrap">
          <TextBox style={{ flex: 1 }} value={s} list={list} onText={t => { const n = items.slice(); n[i] = t; commit(n); }} />
          <Tooltip label={t('Earlier')}><ActionIcon variant="subtle" disabled={i === 0} aria-label={t('Earlier')} onClick={() => swap(i - 1, i)}><IconArrowUp size={16} /></ActionIcon></Tooltip>
          <Tooltip label={t('Later')}><ActionIcon variant="subtle" disabled={i === items.length - 1} aria-label={t('Later')} onClick={() => swap(i, i + 1)}><IconArrowDown size={16} /></ActionIcon></Tooltip>
          <Tooltip label={t('Remove')}><ActionIcon variant="subtle" color="red" aria-label={t('Remove')} onClick={() => { const n = items.slice(); n.splice(i, 1); commit(n); }}><IconX size={16} /></ActionIcon></Tooltip>
        </Group>
      ))}
      <Box><Button size="xs" variant="light" leftSection={<IconPlus size={14} />}
        onClick={() => { focusLast.current = true; setItems([...items, '']); }}>{t('Add')}</Button></Box>
    </Stack>
  );
}

function parameterOf(obj: Obj): Obj | undefined {
  return (S.data.parameters || []).find((p: Obj) => p === obj || (isObj(p.axes) && Object.values(p.axes).includes(obj)));
}

const RECORD_FROM_VALUE: Kind = { k: 'record', fields: [{ key: 'from', kind: { k: 'text' }, help: '' }, { key: 'value', kind: { k: 'text' }, help: '' }] };

/* derive: "derived from [coordinate]", "value [an entry of this coordinate's list]" */
function DeriveW({ f, obj }: { f: FormField; obj: Obj }) {
  const p = parameterOf(obj);
  const coords = ['unit'].concat(p && isObj(p.axes) ? Object.keys(p.axes) : []);
  const voc = isObj(obj.vocabulary) ? obj.vocabulary : {};
  const { root: st, api } = useFormField(obj, f.key, RECORD_FROM_VALUE, markDirty);
  if (st.odd) return <FormNode spec={RECORD_FROM_VALUE} st={st} api={api} path={[]} />;
  const sel = (key: string, opts: { value: string; text: string }[], none: string) => {
    const cur = st.cells[key].v;
    const all = opts.slice();
    if (cur && !all.some(o => o.value === cur)) all.push({ value: cur, text: cur });
    return <NativeSelect value={cur == null ? '' : String(cur)} data={[{ value: '', label: none }, ...all.map(o => ({ value: o.value, label: o.text }))]}
      onChange={e => api.edit([key], e.currentTarget.value)} />;
  };
  return (
    <Stack gap="xs">
      <Group gap="md" align="flex-end">
        <Box><Text size="sm">{t('derived from')}</Text>{sel('from', coords.map(c => ({ value: c, text: c })), t('(not derived)'))}</Box>
        <Box><Text size="sm">{t('value')}</Text>{sel('value', Object.keys(voc).map(k => ({ value: k, text: entryParts(voc[k]).name ? entryParts(voc[k]).name + ' (' + k + ')' : k })), t('(choose)'))}</Box>
      </Group>
      {(st.order as string[]).filter(k => k !== 'from' && k !== 'value').map(k => <Text key={k} size="sm" c="dimmed" fs="italic">{rich(t('`{k}` kept untouched', { k }))}</Text>)}
    </Stack>
  );
}

/* example: the source as text, the defaults as one row, the rows as a table with a column for value, quote and each coordinate */
function ExampleW({ f, obj }: { f: FormField; obj: Obj }) {
  const p = parameterOf(obj) || obj;
  const coords: string[] = isObj(p.axes) ? Object.keys(p.axes) : [];
  const numeric = ['float', 'int'].includes(p.value_type || 'float');
  const [extra, setExtra] = useState<string[]>([]);
  // the columns are fixed when the form is built and when a column is added, not while the rows are typed
  const { cols, spec } = useMemo(() => {
    const F = DF();
    const ex = own(obj, f.key) ? obj[f.key] : undefined;
    const shown = F.exampleColumns(coords, ex);
    const cols = shown.concat(extra.filter(c => !shown.includes(c)));
    return { cols, spec: F.exampleSpec(cols, F.defaultKeysOf(coords, ex), numeric) };
  }, [obj, extra]); // eslint-disable-line react-hooks/exhaustive-deps
  const { root: st, api } = useFormField(obj, f.key, spec, markDirty, [extra.join('\u0000')]);
  if (st.odd) return <FormNode spec={spec} st={st} api={api} path={[]} />;
  const part = (key: string, label: string, help: string) => (
    <Box>
      <Text size="sm" fw={600}><Code>{label}</Code></Text>
      <Text size="xs" c="dimmed">{help}</Text>
      <FormNode spec={spec.fields!.find(x => x.key === key)!.kind} st={st.cells[key]} api={api} path={[key]} />
    </Box>
  );
  const offers = DF().exampleOffers(coords).filter(c => !cols.includes(c));
  return (
    <Stack gap="sm">
      {part('source', 'source', t('The text as the document prints it, plain text.'))}
      {part('defaults', 'defaults', t('What every row says unless the row says otherwise.'))}
      {part('tuples', 'rows', t('One row per value the text states: its value, its quote and its dimensions.'))}
      {offers.length ? (
        <NativeSelect w={200} value="" data={[{ value: '', label: t('+ column') }, ...offers.map(c => ({ value: c, label: c }))]}
          onChange={e => { const v = e.currentTarget.value; if (v) setExtra([...extra, v]); }} />
      ) : null}
      {(st.order as string[]).filter(k => !['source', 'defaults', 'tuples'].includes(k)).map(k => <Text key={k} size="sm" c="dimmed" fs="italic">{rich(t('`{k}` kept untouched', { k }))}</Text>)}
    </Stack>
  );
}

/* units_accepted: a bare number is the short form, an object has factor, names_period, target */
function UnitsW({ f, obj, orig }: { f: FormField; obj: Obj; orig: Obj | null }) {
  const redraw = useRedraw();
  const [nu, setNu] = useState('');
  const [nf, setNf] = useState('');
  const units = () => obj[f.key];
  const origUnit = (u: string) => (orig && isObj(orig[f.key]) ? orig[f.key][u] : undefined);
  const u: Obj = isObj(units()) ? units() : {};
  const done = () => { markDirty(); redraw(); };
  const rows = Object.keys(u).map(name => {
    const bare = !isObj(u[name]);
    const factor = bare ? u[name] : u[name].factor;
    const cur = () => units()[name];
    const toObj = () => { if (!isObj(cur())) units()[name] = { factor: cur() }; return units()[name]; };
    return (
      <Table.Tr key={name}>
        <Table.Td><Text ff="monospace" size="sm">{name}</Text></Table.Td>
        <Table.Td><NumberBox w={110} value={factor == null ? '' : String(factor)} onText={t => {
          const n = Number(t);
          if (t === '' || Number.isNaN(n)) return;
          if (isObj(cur())) cur().factor = n; else units()[name] = n;
          done();
        }} /></Table.Td>
        <Table.Td><Checkbox checked={!bare && !!u[name].names_period} aria-label={t('names a period')} onChange={e => {
          const on = e.currentTarget.checked;
          if (!isObj(cur())) { if (!on) return; toObj().names_period = true; }
          else writeBool(cur(), 'names_period', on, false, isObj(origUnit(name)) ? origUnit(name) : null);
          done();
        }} /></Table.Td>
        <Table.Td><TextBox value={bare ? '' : str(u[name].target)} onText={t => {
          if (!isObj(cur())) { if (t === '') return; toObj().target = t; }
          else writeString(cur(), 'target', t);
          done();
        }} /></Table.Td>
        <Table.Td>
          <Tooltip label={t('Removed here, written with the next confirmed save')}>
            <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />}
              onClick={() => { delete units()[name]; if (!Object.keys(units()).length) delete obj[f.key]; done(); }}>{t('Remove')}</Button>
          </Tooltip>
        </Table.Td>
      </Table.Tr>
    );
  });
  return (
    <Stack gap="xs">
      {rows.length ? (
        <Table withTableBorder className="dp-formtable">
          <Table.Thead><Table.Tr><Table.Th>{t('unit')}</Table.Th><Table.Th>{t('factor')}</Table.Th><Table.Th>{t('names a period')}</Table.Th><Table.Th>{t('target')}</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>{rows}</Table.Tbody>
        </Table>
      ) : null}
      <Group gap="xs" align="flex-end">
        <TextBox placeholder={t('new unit')} value={nu} onText={setNu} />
        <NumberBox placeholder={t('factor')} value={nf} onText={setNf} />
        <Button variant="light" leftSection={<IconPlus size={16} />} onClick={() => {
          const name = nu.trim(); const n = Number(nf);
          if (!name || nf === '' || Number.isNaN(n)) { showError(new Error(t('A unit needs a name and a factor.'))); return; }
          if (isObj(units()) && own(units(), name)) { showError(new Error(t('The unit {name} exists already.', { name }))); return; }
          if (!isObj(units())) obj[f.key] = {};
          obj[f.key][name] = n; setNu(''); setNf(''); done();
        }}>{t('Add unit')}</Button>
      </Group>
    </Stack>
  );
}

/* works.fields: one row per question, the field chosen among the fields of the spec */
function QuestionsW({ f, obj }: { f: FormField; obj: Obj }) {
  const redraw = useRedraw();
  const q = () => obj[f.key];
  const cur: Obj = isObj(q()) ? q() : {};
  const uris: string[] = (S.data.parameters || []).map((p: Obj) => p.uri);
  const done = () => { markDirty(); redraw(); };
  return (
    <Stack gap="xs">
      {Object.keys(cur).map(k => {
        const opts = uris.includes(k) ? uris : uris.concat([k]);
        return (
          <Group key={k} align="flex-start" wrap="nowrap" gap="xs">
            <NativeSelect w={240} style={{ flex: 'none' }} value={k} data={opts}
              onChange={e => {
                const v = e.currentTarget.value;
                if (own(q(), v)) { showError(new Error(t('A question for {field} exists already.', { field: v }))); return; }
                const nq: Obj = {}; for (const [kk, val] of Object.entries(q())) nq[kk === k ? v : kk] = val;
                obj[f.key] = nq; done();
              }} />
            <AreaBox style={{ flex: 1 }} minRows={3} value={str(cur[k])} onText={t => { q()[k] = t; markDirty(); }} />
            <Tooltip label={t('Remove')}><ActionIcon variant="subtle" color="red" aria-label={t('Remove')} onClick={() => { delete q()[k]; done(); }}><IconX size={16} /></ActionIcon></Tooltip>
          </Group>
        );
      })}
      <Box><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => {
        const free = uris.find(u => !own(cur, u));
        if (!free) { showError(new Error(t('Every field has a question already.'))); return; }
        if (!isObj(q())) obj[f.key] = {};
        obj[f.key][free] = ''; done();
      }}>{t('Add question')}</Button></Box>
    </Stack>
  );
}

function vocabOf(c: string): Obj | null {
  const p = (S.data.parameters || []).find((x: Obj) => isObj(x.axes) && own(x.axes, c));
  const ax = p && p.axes[c];
  return isObj(ax) && isObj(ax.vocabulary) ? ax.vocabulary : null;
}
const MAP_OF_TEXT: Kind = { k: 'map', value: { k: 'text' } };

/* entry_of: {"<dimension>": "<entry key>"} as two selects; further pairs of the file are kept as they are */
function EntryOfW({ f, obj }: { f: FormField; obj: Obj }) {
  const coords: string[] = [];
  for (const g of Object.values(isObj(S.data.groups) ? S.data.groups : {}) as Obj[]) {
    for (const c of (isObj(g) && Array.isArray(g.pair) ? g.pair : [])) if (!coords.includes(c) && vocabOf(c)) coords.push(c);
  }
  const { root: st, api } = useFormField(obj, f.key, MAP_OF_TEXT, markDirty);
  const pair = st.odd ? null : st.pairs[0];
  const coord: string = pair ? pair.key : '';
  const cOpts = coords.slice();
  if (coord && !cOpts.includes(coord)) cOpts.push(coord);
  const voc = coord ? vocabOf(coord) || {} : {};
  const keys = Object.keys(voc);
  const now: string = pair && !pair.state.odd ? pair.state.v || '' : '';
  if (now && !keys.includes(now)) keys.push(now);
  const first = (c: string) => Object.keys(vocabOf(c) || {})[0] || '';
  const onCoord = (v: string) => {
    if (st.odd) return;
    if (!v) { if (pair) api.removePair([], 0); }
    else if (!pair) { api.addPair([]); api.edit([0, 'key'], v); api.edit([0, 'value'], first(v)); }
    else { api.edit([0, 'key'], v); api.edit([0, 'value'], first(v)); }
  };
  return (
    <Stack gap="xs">
      <Group gap="sm" align="flex-end">
        <NativeSelect aria-label={t('dimension')} value={coord} data={[{ value: '', label: t('(none)') }, ...cOpts.map(c => ({ value: c, label: c }))]}
          onChange={e => onCoord(e.currentTarget.value)} />
        <NativeSelect aria-label={t('entry')} disabled={!coord} value={now}
          data={[{ value: '', label: coord ? t('(choose)') : '' }, ...keys.map(k => {
            const nm = own(voc, k) ? entryParts(voc[k]).name : '';
            return { value: k, label: nm ? nm + ' (' + k + ')' : k };
          })]}
          onChange={e => { if (pair) api.edit([0, 'value'], e.currentTarget.value); }} />
      </Group>
      {st.odd ? null : st.pairs.slice(1).map((p: { key: string }, i: number) => <Text key={i} size="sm" c="dimmed" fs="italic">{rich(t('`{k}` kept untouched', { k: p.key }))}</Text>)}
    </Stack>
  );
}

function Widget({ f, obj, orig, ctx }: { f: FormField; obj: Obj; orig: Obj | null; ctx: WidgetCtx }) {
  switch (f.widget) {
    case 'line': return <LineW f={f} obj={obj} ctx={ctx} />;
    case 'text': return <TextW f={f} obj={obj} />;
    case 'lines': return <LinesW f={f} obj={obj} />;
    case 'bool': return <BoolW f={f} obj={obj} orig={orig} />;
    case 'choice': return <ChoiceW f={f} obj={obj} />;
    case 'number': return <NumberW f={f} obj={obj} />;
    case 'strings': return <StringsEditor obj={obj} k={f.key} list={ctx.coordNames} />;
    case 'derive': return <DeriveW f={f} obj={obj} />;
    case 'example': return <ExampleW f={f} obj={obj} />;
    case 'units': return <UnitsW f={f} obj={obj} orig={orig} />;
    case 'questions': return <QuestionsW f={f} obj={obj} />;
    case 'entry_of': return <EntryOfW f={f} obj={obj} />;
    case 'entries': {
      const ref = ctx.refFor ? ctx.refFor(f.key) : null;
      return ref ? <EntriesTable lref={ref} /> : <Text c="orange">{t('No list here.')}</Text>;
    }
    default: return <Alert color="yellow">{t('Unknown widget "{widget}" for this key; it is kept as it is.', { widget: f.widget })}</Alert>;
  }
}

/* the form of one object: every key the description names, then a line for the keys it does not */
export function SpecForm({ fields, obj, orig, ctx }: { fields: FormField[] | undefined; obj: Obj; orig: Obj | null; ctx?: WidgetCtx }) {
  const c = ctx || {};
  const skip = c.skip || new Set<string>();
  const shown = new Set<string>();
  const parts: ReactNode[] = [];
  for (const f of fields || []) {
    if (skip.has(f.key)) { shown.add(f.key); continue; }
    if (f.only && !(S.sel.t === 'plan' && f.only.includes(S.sel.key))) continue;
    shown.add(f.key);
    parts.push(<FieldWrap key={f.key} k={f.key} help={f.help}><Widget f={f} obj={obj} orig={orig} ctx={c} /></FieldWrap>);
  }
  const other = Object.keys(obj).filter(k => !shown.has(k) && !(c.skipQuiet && c.skipQuiet.has(k)));
  return (
    <Stack gap="lg">
      {parts}
      {other.length ? <Text size="sm" c="dimmed">{t('Other keys kept untouched:')} {other.map(k => <Code key={k} mr={6}>{k}</Code>)}</Text> : null}
    </Stack>
  );
}

/* a key of its own that is not in the form description (the type of a dimension, its enum) */
export function FlaggedKey({ k, children }: { k: string; children: ReactNode }) {
  const flagged = S.flag != null && S.flag.field === k;
  return <Box data-key={k} className={flagged ? 'dp-flag' : undefined} p={flagged ? 6 : 0}>{children}</Box>;
}
export { useEdit };
