/* The data files of the profile that no other tab edits (owner request 2026-11-19, A2): the regions of a profile with their
   spellings, the exceptions of a register (GET /api/data). A file a person keeps is edited entry by entry, checked and saved
   on its own (POST /api/data/check, /api/data/save); a file a fetch writes is only shown, since the next fetch writes it again.
   An entry is edited as the JSON it is in the file. */
import { useEffect, useReducer, useRef } from 'react';
import { Accordion, ActionIcon, Alert, Badge, Button, Code, Group, Loader, Stack, Table, Text, TextInput } from '@mantine/core';
import { IconCheck, IconDeviceFloppy, IconPlus, IconTrash } from '@tabler/icons-react';
import { api, apiR } from '../lib/api';
import { showError, showInfo } from '../lib/dialogs';
import { rich, t, tn, tr } from '../lib/i18n';
import { AreaBox, TextBox } from '../components/Inputs';
import { Muted } from '../components/Bits';

/* how many entries of a file are shown before "Show more" */
const PAGE = 50;

interface Open {
  d: any; rows: [string, string][]; filter: string; shown: number; problems: string[]; busy: boolean; err: string | null;
  newKey: string; newValue: string;
}

const textOf = (value: any) => JSON.stringify(value);
const rowsOf = (entries: Record<string, any>): [string, string][] => Object.entries(entries || {}).map(([k, v]) => [k, textOf(v)]);

/* the entries the rows stand for; null with the key whose text is no JSON */
function entriesOf(rows: [string, string][]): { entries: Record<string, any> | null; bad: string | null } {
  const entries: Record<string, any> = {};
  for (const [key, text] of rows) {
    try { entries[key] = JSON.parse(text); } catch { return { entries: null, bad: key }; }
  }
  return { entries, bad: null };
}

function dirtyOf(o: Open): boolean {
  const original = rowsOf(o.d.entries);
  return o.rows.length !== original.length || o.rows.some(([k, v], i) => k !== original[i][0] || v !== original[i][1]);
}

export function DataFiles({ onDirty }: { onDirty: (dirty: boolean) => void }) {
  const R = useRef({ list: null as any[] | null, err: null as string | null, open: new Map<string, Open>() });
  const [, touch] = useReducer((x: number) => x + 1, 0);
  const D = R.current;

  async function load() {
    try { D.list = (await api('GET', '/api/data')).files || []; D.err = null; }
    catch (e) { D.err = (e as Error).message; }
    touch();
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { onDirty([...D.open.values()].some(o => dirtyOf(o))); });

  async function openFile(name: string) {
    if (D.open.has(name)) return;
    try {
      const d = await api('GET', '/api/data/file?name=' + encodeURIComponent(name));
      D.open.set(name, { d, rows: rowsOf(d.entries), filter: '', shown: PAGE, problems: [], busy: false, err: null, newKey: '', newValue: '' });
    } catch (e) { showError(e); }
    touch();
  }

  async function send(name: string, what: 'check' | 'save') {
    const o = D.open.get(name);
    if (!o || o.busy) return;
    const { entries, bad } = entriesOf(o.rows);
    if (!entries) { o.problems = [t('{key}: the entry is no JSON', { key: bad || '' })]; touch(); return; }
    o.busy = true; o.err = null; touch();
    try {
      const r = await apiR('/api/data/' + what, what === 'save' ? { name, entries, base: o.d.sha256 } : { name, entries });
      o.problems = r.problems || [];
      if (what === 'save' && r.saved) {
        showInfo(t('Saved {file}: {added} added, {edited} changed, {removed} removed.', {
          file: r.file, added: (r.added || []).length, edited: (r.edited || []).length, removed: (r.removed || []).length }));
        D.open.delete(name);
        await load();
        await openFile(name);
        return;
      }
      if (what === 'save' && r.saved === false) o.err = tr(r.message || '');
      else if (what === 'check' && r.ok) o.err = null;
      if (what === 'check' && r.ok) showInfo(r.changed
        ? t('The entries can be written: {added} added, {edited} changed, {removed} removed.', {
          added: (r.added || []).length, edited: (r.edited || []).length, removed: (r.removed || []).length })
        : t('Nothing is changed.'));
    } catch (e) { o.err = (e as Error).message; }
    o.busy = false; touch();
  }

  if (D.err) return <Alert color="red">{D.err}</Alert>;
  if (!D.list) return <Group gap="xs"><Loader size="xs" /><Muted>{t('Reading the data files…')}</Muted></Group>;
  if (!D.list.length) return null;
  return (
    <Stack gap="xs">
      <Text fw={700} size="lg">{t('Data files of the profile')}</Text>
      <Muted>{t('What the profile reads besides the spec, the prompts and the rules: a file kept by hand is edited here, a file written by a fetch is only shown, because the next fetch writes it again.')}</Muted>
      <Accordion multiple variant="separated" onChange={(names: string[]) => names.forEach(openFile)}>
        {D.list.map(f => {
          const o = D.open.get(f.name);
          return (
            <Accordion.Item key={f.name} value={f.name}>
              <Accordion.Control>
                <Group gap="xs" wrap="nowrap">
                  <Code>{f.name}</Code>
                  <Badge variant="light" color={f.kept ? 'teal' : 'gray'}>{f.kept ? t('kept by hand') : t('written by a fetch')}</Badge>
                  <Text size="sm" c="dimmed">{tn(f.entries, '{n} entry', '{n} entries')}</Text>
                  {o && dirtyOf(o) && <Badge color="orange" variant="light">{t('unsaved changes')}</Badge>}
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="xs">
                  <Text size="sm">{rich(tr(f.about))}</Text>
                  {!o ? <Loader size="xs" /> : <FileBody o={o} kept={f.kept} touch={touch} send={(what) => send(f.name, what)} />}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          );
        })}
      </Accordion>
    </Stack>
  );
}

function FileBody({ o, kept, touch, send }: { o: Open; kept: boolean; touch: () => void; send: (what: 'check' | 'save') => void }) {
  const needle = o.filter.trim().toLowerCase();
  const matching = o.rows.map((row, i) => ({ row, i })).filter(({ row }) => !needle
    || row[0].toLowerCase().includes(needle) || row[1].toLowerCase().includes(needle));
  const shown = matching.slice(0, o.shown);
  const dirty = dirtyOf(o);
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <TextInput placeholder={t('Search keys and entries')} value={o.filter} onChange={e => { o.filter = e.currentTarget.value; o.shown = PAGE; touch(); }} w={320} />
        <Text size="sm" c="dimmed">{t('{m} of {total} entries', { m: matching.length, total: o.rows.length })}</Text>
        {kept && <Button size="xs" variant="default" leftSection={<IconCheck size={14} />} disabled={o.busy} onClick={() => send('check')}>{t('Check')}</Button>}
        {kept && <Button size="xs" leftSection={<IconDeviceFloppy size={14} />} disabled={o.busy || !dirty} onClick={() => send('save')}>{t('Save')}</Button>}
      </Group>
      {o.err && <Alert color="red">{o.err}</Alert>}
      {o.problems.length > 0 && <Alert color="red">{o.problems.slice(0, 12).map((p, i) => <div key={i}>{rich(tr(p))}</div>)}</Alert>}
      <Table striped withTableBorder>
        <Table.Thead><Table.Tr><Table.Th w="30%">{t('key')}</Table.Th><Table.Th>{t('entry')}</Table.Th>{kept && <Table.Th w={40} />}</Table.Tr></Table.Thead>
        <Table.Tbody>
          {shown.map(({ row, i }) => (
            <Table.Tr key={row[0]}>
              <Table.Td><Code style={{ wordBreak: 'break-all' }}>{row[0]}</Code></Table.Td>
              <Table.Td>{kept
                ? <AreaBox mono minRows={1} maxRows={8} value={row[1]} aria-label={row[0]} onText={text => { o.rows[i] = [row[0], text]; touch(); }} />
                : <Code block style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 160, overflow: 'auto' }}>{row[1]}</Code>}</Table.Td>
              {kept && <Table.Td><ActionIcon variant="subtle" color="red" aria-label={t('Remove the entry')} title={t('Remove the entry')}
                onClick={() => { o.rows.splice(i, 1); touch(); }}><IconTrash size={16} /></ActionIcon></Table.Td>}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {matching.length > shown.length && <Button size="xs" variant="default" onClick={() => { o.shown += PAGE; touch(); }}>{t('Show {n} more', { n: Math.min(PAGE, matching.length - shown.length) })}</Button>}
      {kept && (
        <Group gap="xs" align="flex-end" wrap="nowrap">
          <TextBox mono label={t('New key')} value={o.newKey} onText={text => { o.newKey = text; touch(); }} w={260} />
          <TextBox mono label={t('Its entry, as JSON')} value={o.newValue} onText={text => { o.newValue = text; touch(); }} style={{ flex: 1 }} />
          <Button variant="default" leftSection={<IconPlus size={16} />}
            disabled={!o.newKey.trim() || !o.newValue.trim() || o.rows.some(r => r[0] === o.newKey.trim())}
            onClick={() => { o.rows.push([o.newKey.trim(), o.newValue.trim()]); o.newKey = ''; o.newValue = ''; touch(); }}>{t('Add the entry')}</Button>
        </Group>
      )}
    </Stack>
  );
}
