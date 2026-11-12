/* The settings of the general steps (owner decision 2026-11-12): the prompt (a prompt of the profile or a text of the
   step's own), what a request shows (each input a key of the message, the variable it comes from and how it is
   shown), the form of the answer as a JSON schema drawn with jsonjoy-builder, where the answer goes, names of variables
   and paths to them, a value in JSON, a piece of Python and several choices. Each control writes into the step's "set";
   a setting emptied is removed. */
import { lazy, Suspense, useState } from 'react';
import {
  ActionIcon, Box, Button, Checkbox, Group, JsonInput, Loader, Modal, NativeSelect, Paper, SegmentedControl, Stack,
  Switch, TagsInput, Text, Tooltip,
} from '@mantine/core';
import { IconMinus, IconPlus } from '@tabler/icons-react';
import { AreaBox, TextBox } from '../components/Inputs';
import { rich, t, tr, useLang } from '../lib/i18n';
import { libBox, type FlowData, type Library, type LibSetting, type Step } from './model';

/* the visual editor of a schema, loaded when it is opened */
const SchemaEditor = lazy(() => import('./SchemaEditor'));

export const GENERAL_KINDS = new Set(['prompt', 'inputs', 'schema', 'into', 'varname', 'path', 'paths', 'varnames', 'json',
  'code', 'multi']);

type Put = (v: unknown) => void;
interface Input { key: string; from: string; show?: string }

const Label = ({ s }: { s: LibSetting }) => <Text size="sm" fw={600} mb={4}>{rich(tr(s.label))}</Text>;
const Help = ({ s }: { s: LibSetting }) => s.help ? <Text size="xs" c="dimmed" mt={4}>{rich(tr(s.help))}</Text> : null;

/* one setting of a general step; *vars* are the variables there before it */
export function GeneralField({ s, value, put, vars, data }: {
  s: LibSetting; value: unknown; put: Put; vars: string[]; data: FlowData;
}) {
  useLang();
  let body: React.ReactNode = null;
  if (s.kind === 'prompt') body = <PromptField value={value ?? s.default} put={put} ids={data.prompt_ids || []} />;
  else if (s.kind === 'inputs') body = <InputsField value={value} put={put} vars={vars} data={data} />;
  else if (s.kind === 'schema') body = <SchemaField value={value} put={put} />;
  else if (s.kind === 'into') body = <IntoField value={value} put={put} data={data} />;
  else if (s.kind === 'varname') {
    body = <TextBox mono value={String(value ?? s.default ?? '')} onText={() => {}} aria-label={tr(s.label)}
      onCommit={v => put(v.trim() || undefined)} />;
  } else if (s.kind === 'path') {
    body = <TextBox mono list={vars} value={String(value ?? '')} onText={() => {}} aria-label={tr(s.label)}
      placeholder={t('variable, e.g. answer.finds')} onCommit={v => put(v.trim() || undefined)} />;
  } else if (s.kind === 'paths' || s.kind === 'varnames') {
    body = <TagsInput data={s.kind === 'paths' ? vars : []} value={Array.isArray(value) ? value as string[] : []}
      aria-label={tr(s.label)} placeholder={t('type and press Enter')}
      onChange={v => put(v.length ? v : undefined)} />;
  } else if (s.kind === 'json') body = <JsonField value={value} put={put} label={tr(s.label)} />;
  else if (s.kind === 'code') {
    body = <AreaBox mono minRows={8} maxRows={30} value={String(value ?? '')} onText={() => {}} aria-label={tr(s.label)}
      placeholder={'def run(inputs):\n    return {"result": inputs}'} onCommit={v => put(v.trim() ? v : undefined)} />;
  } else if (s.kind === 'multi') {
    const on = new Set(Array.isArray(value) ? value as string[] : []);
    body = <Stack gap={4}>{(s.choices || []).map(ch => (
      <Checkbox key={ch} size="xs" label={tr((s.words || {})[ch] || ch)} checked={on.has(ch)}
        onChange={e => {
          if (e.currentTarget.checked) on.add(ch); else on.delete(ch);
          const v = (s.choices || []).filter(x => on.has(x));
          put(v.length ? v : undefined);
        }} />))}</Stack>;
  }
  return <Box><Label s={s} />{body}<Help s={s} /></Box>;
}

/* a prompt of the profile, or a text of the step's own ({"text": ...}) */
function PromptField({ value, put, ids }: { value: unknown; put: Put; ids: string[] }) {
  const own = typeof value === 'object' && value !== null;
  const text = own ? String((value as { text?: string }).text || '') : '';
  return (
    <Stack gap={6}>
      <SegmentedControl size="xs" value={own ? 'own' : 'file'}
        data={[{ value: 'file', label: t('a prompt of the profile') }, { value: 'own', label: t('a text of its own') }]}
        onChange={v => put(v === 'own' ? { text: text || '' } : (ids[0] || undefined))} />
      {own
        ? <AreaBox mono minRows={6} value={text} onText={() => {}} aria-label={t('prompt')}
            placeholder={t('What the model is told. An input whose key you write as {{key}} stands here instead of in the message.')}
            onCommit={v => put({ text: v })} />
        : <NativeSelect value={typeof value === 'string' ? value : ''} aria-label={t('prompt')}
            data={[{ value: '', label: t('choose a prompt') }, ...ids.map(id => ({ value: id, label: id }))]}
            onChange={e => put(e.currentTarget.value || undefined)} />}
    </Stack>
  );
}

/* the inputs of a request: each a key of the message, the variable it comes from and how it is shown */
function InputsField({ value, put, vars, data }: { value: unknown; put: Put; vars: string[]; data: FlowData }) {
  const rows: Input[] = Array.isArray(value) ? (value as Input[]).map(r => ({ ...r })) : [];
  const shows = data.shows || {};
  const write = (next: Input[]) => put(next.length ? next : undefined);
  return (
    <Paper withBorder p="xs" radius="md">
      <Stack gap={6}>
        {rows.map((r, i) => (
          <Group key={i} gap={6} wrap="wrap" align="center">
            <TextBox mono w={110} value={r.key} onText={() => {}} aria-label={t('key in the message')} placeholder={t('key')}
              onCommit={v => { if (v === r.key) return; rows[i].key = v.trim(); write(rows); }} />
            <TextBox mono w={150} list={vars} value={r.from} onText={() => {}} aria-label={t('from the variable')}
              placeholder={t('variable')} onCommit={v => { if (v === r.from) return; rows[i].from = v.trim(); write(rows); }} />
            <NativeSelect size="xs" value={r.show || 'as_is'} aria-label={t('shown as')}
              data={Object.entries(shows).map(([k, v]) => ({ value: k, label: tr(v.label) }))}
              onChange={e => { rows[i].show = e.currentTarget.value; write(rows); }} />
            <Tooltip label={t('Remove the input')}>
              <ActionIcon size="sm" variant="subtle" color="red" aria-label={t('Remove the input')}
                onClick={() => { rows.splice(i, 1); write(rows); }}><IconMinus size={14} /></ActionIcon>
            </Tooltip>
          </Group>
        ))}
        <Box><Button size="compact-xs" variant="light" leftSection={<IconPlus size={12} />}
          onClick={() => write([...rows, { key: 'input_' + (rows.length + 1), from: vars[0] || 'document', show: 'as_is' }])}>
          {t('input')}</Button></Box>
        {rows.length > 0 && <Text size="xs" c="dimmed">{rows.map(r => `${r.key} ← ${r.from} (${tr((shows[r.show || 'as_is'] || { label: r.show || '' }).label)})`).join(' · ')}</Text>}
      </Stack>
    </Paper>
  );
}

/* the form of the answer: a JSON schema, drawn with jsonjoy-builder in a window, or written as JSON */
function SchemaField({ value, put }: { value: unknown; put: Put }) {
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const schema = (typeof value === 'object' && value !== null ? value : {
    type: 'object', properties: { answer: { type: 'string' } }, required: ['answer'],
  }) as Record<string, unknown>;
  const [draft, setDraft] = useState<Record<string, unknown>>(schema);
  const keys = Object.keys((schema.properties as Record<string, unknown>) || {});
  return (
    <Stack gap={6}>
      <Group gap={6}>
        <Text size="sm" className="dp-mono">{keys.length ? keys.join(', ') : t('no keys yet')}</Text>
        <Button size="compact-xs" variant="light" onClick={() => { setDraft(schema); setOpen(true); }}>{t('Edit the form')}</Button>
        {value !== undefined && <Button size="compact-xs" variant="subtle" color="gray" onClick={() => put(undefined)}>{t('one text answer')}</Button>}
      </Group>
      <Modal opened={open} onClose={() => setOpen(false)} size="xl" title={t('Form of the answer')}>
        <Stack gap="sm">
          <Box className="dp-schema">
            <Suspense fallback={<Loader size="sm" />}>
              <SchemaEditor value={draft} onChange={setDraft} lang={lang} />
            </Suspense>
          </Box>
          <JsonInput label={t('as JSON')} autosize minRows={4} maxRows={14} value={JSON.stringify(draft, null, 2)}
            onChange={v => { try { setDraft(JSON.parse(v)); } catch { /* typed half */ } }} />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpen(false)}>{t('Cancel')}</Button>
            <Button onClick={() => { put(draft); setOpen(false); }}>{t('Take this form')}</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

/* where the answer goes: a variable of its own name, for this item or for the whole document, or the values of a field
   of the Spec, each with its line */
function IntoField({ value, put, data }: { value: unknown; put: Put; data: FlowData }) {
  const into = (typeof value === 'object' && value !== null ? value : {}) as { var?: string; lasting?: boolean; field?: string };
  const field = 'field' in into;
  const fields = data.spec_fields || [];
  return (
    <Stack gap={6}>
      <SegmentedControl size="xs" value={field ? 'field' : 'var'}
        data={[{ value: 'var', label: t('a variable') }, { value: 'field', label: t('values of a field') }]}
        onChange={v => put(v === 'field' ? { field: fields[0] ? fields[0].uri : '' } : { var: 'answer_1' })} />
      {field
        ? <NativeSelect value={into.field || ''} aria-label={t('field of the Spec')}
            data={fields.map(f => ({ value: f.uri, label: f.label }))} onChange={e => put({ field: e.currentTarget.value })} />
        : <Group gap="sm">
            <TextBox mono w={160} value={into.var || ''} onText={() => {}} aria-label={t('name of the variable')}
              onCommit={v => put({ ...into, var: v.trim() })} />
            <Switch size="xs" label={t('holds for the whole document')} checked={!!into.lasting}
              onChange={e => put(e.currentTarget.checked ? { ...into, lasting: true } : { var: into.var || '' })} />
          </Group>}
    </Stack>
  );
}

function JsonField({ value, put, label }: { value: unknown; put: Put; label: string }) {
  const [text, setText] = useState(value === undefined ? '' : JSON.stringify(value, null, 2));
  return <JsonInput aria-label={label} autosize minRows={2} maxRows={12} value={text} validationError={t('not JSON')}
    onChange={setText} onBlur={() => { if (!text.trim()) { put(undefined); return; } try { put(JSON.parse(text)); } catch { /* shown */ } }} />;
}

/* what a step takes and gives, in the words of the variables: a step of the library by its inputs and outputs, a
   general step by its settings (as inputs_of and outputs_of of extraction/flow.py say it) */
export function ioOf(lib: Library, n: Step): { takes: string[]; gives: string[] } {
  const b = libBox(lib, n.box);
  if (!b) return { takes: [], gives: [] };
  const known = lib.variables || {};
  const word = (name: string) => tr((known[name] || { label: name }).label);
  const spec = (one: string) => one.replace(/\?$/, '').split('|').map(word).join(' ' + t('or') + ' ')
    + (one.endsWith('?') ? ' ' + t('(where a step gives it)') : '');
  const set = (n.set || {}) as Record<string, any>;
  const root = (p: unknown) => (typeof p === 'string' && p ? p.split('.')[0] : '');
  const uniq = (xs: string[]) => [...new Set(xs.filter(Boolean))];
  switch (b.type) {
    case 'ask': return {
      takes: uniq((set.inputs || []).map((i: { from?: string }) => root(i.from))).map(word),
      gives: (set.into && set.into.field ? ['answer', 'values'] : ['answer', (set.into && set.into.var) || n.id]).map(word),
    };
    case 'retrieve': return { takes: uniq([root(set.query)]).map(word), gives: [word(set.into || 'hits')] };
    case 'rerank': return { takes: uniq([root(set.list), root(set.query)]).map(word), gives: [word(set.into || n.id)] };
    case 'set': return { takes: uniq([root(set.from)]).map(word), gives: set.name ? [word(set.name)] : [] };
    case 'filter': return { takes: uniq([root(set.list)]).map(word), gives: [word(set.into || n.id)] };
    case 'merge': return { takes: uniq((set.lists || []).map(root)).map(word), gives: [word(set.into || n.id)] };
    case 'python': return { takes: uniq((set.inputs || []).map(root)).map(word), gives: (set.outputs || []).map(word) };
    default: return { takes: (b.inputs || []).map(spec), gives: (b.outputs || []).map(word) };
  }
}
