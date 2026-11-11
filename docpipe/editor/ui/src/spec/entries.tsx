/* A list of entries (the list of a field or of a coordinate, or its beside list) as a table: name, spellings, group, details,
   removal through the server, and two dialogs to add an entry (one of the ontology snapshot, one of the profile's own). */
import { Fragment, useEffect, useReducer, useRef, useState } from 'react';
import {
  Alert, Badge, Box, Button, Code, Group, Loader, Pill, Stack, Table, Text, TextInput, Tooltip,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { IconPlus, IconSearch, IconTrash } from '@tabler/icons-react';
import { AreaBox, TextBox } from '../components/Inputs';
import { Help } from '../components/Bits';
import { get } from '../lib/api';
import { showError } from '../lib/dialogs';
import {
  entryMatches, entryParts, hasSpelling, insertSpelling, listWithEntryAfter, newEntryFromTerm, notesFor, setEntryField,
  setEntryName, shortId,
} from '../lib/spec';
import { isObj, own, type Obj } from '../lib/util';
import { findParam, markDirty, removeOnServer, S, structural } from './state';
import { SpecForm } from './widgets';

export interface ListRef {
  uri: string; coordinate: string | null; key: string; markEntry: string | null | undefined;
  holder(): Obj | undefined; orig(): Obj | undefined;
}
export function refFor(uri: string, coordinate: string | null, key: string, markEntry?: string | null): ListRef {
  return {
    uri, coordinate, key, markEntry,
    holder: () => { const p = findParam(S.data, uri); return coordinate == null ? p : (p && p.axes && p.axes[coordinate]); },
    orig: () => { const p = findParam(S.orig, uri); return coordinate == null ? p : (p && p.axes && p.axes[coordinate]); },
  };
}

const useRedraw = () => useReducer((x: number) => x + 1, 0)[1];
const ENTRY_KEYS = ['label', 'spellings', 'definition', 'gloss', 'group'];

function currentList(lref: ListRef): Obj {
  const hd = lref.holder();
  return hd && isObj(hd[lref.key]) ? hd[lref.key] : {};
}

function SpellingAdd({ onAdd }: { onAdd: (v: string) => boolean }) {
  const [text, setText] = useState('');
  return (
    <Box onKeyDown={e => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (text.trim() === '') return;
      if (onAdd(text)) setText('');
    }}>
      <TextBox w={150} placeholder="add spelling" value={text} onText={setText} />
    </Box>
  );
}

function EntryRow({ id, lref, selected, onSelect, open, onToggle, onSpelling }: {
  id: string; lref: ListRef; selected: boolean; onSelect: (id: string) => void; open: boolean; onToggle: (id: string) => void;
  onSpelling: () => void;
}) {
  const redraw = useRedraw();
  const list = () => currentList(lref);
  const p = entryParts(list()[id]);
  const notes = notesFor(S.notes, lref.uri, lref.coordinate, id);
  const flagged = lref.markEntry === id;
  const ref = useRef<HTMLTableRowElement>(null);
  useEffect(() => { if (flagged) ref.current?.scrollIntoView({ block: 'center' }); }, [flagged]);

  const addSpelling = (v: string) => {
    if (hasSpelling(list(), id, v)) { showError(new Error('"' + v + '" is already a name or spelling of ' + id + '.')); return false; }
    insertSpelling(list(), id, v); markDirty(); onSpelling();
    return true;
  };
  const removeSpelling = (s: string) => removeOnServer(
    { kind: 'spelling', field: lref.uri, coordinate: lref.coordinate, list: lref.key, entry: id, spelling: s }, 'the spelling "' + s + '"');
  const removeEntry = () => removeOnServer(
    { kind: 'entry', field: lref.uri, coordinate: lref.coordinate, list: lref.key, entry: id }, 'the entry ' + id);

  return (
    <>
      <Table.Tr ref={ref} className={'dp-spec-row' + (flagged ? ' dp-flag' : '')} data-sel={selected ? 'true' : undefined} data-id={id}
        onFocus={() => onSelect(id)}>
        <Table.Td onClick={() => onSelect(id)} title={id + ' (click to select: a new entry is added after the selected row)'} style={{ cursor: 'pointer' }}>
          <Text size="sm" ff="monospace" style={{ wordBreak: 'break-all' }}>{shortId(id)}</Text>
          {notes.length ? <Tooltip label={<Box style={{ whiteSpace: 'pre-wrap' }}>{notes.map(n => n.text).join('\n')}</Box>}><Badge color="yellow" size="sm">note</Badge></Tooltip> : null}
        </Table.Td>
        <Table.Td miw={200}><TextBox value={p.name} onText={t => { setEntryName(list(), id, t); markDirty(); redraw(); }} /></Table.Td>
        <Table.Td miw={240}>
          <Group gap={6}>
            <Pill.Group>
              {p.spellings.map((s, i) => <Pill key={i + ':' + s} size="md" withRemoveButton onRemove={() => removeSpelling(s)}
                removeButtonProps={{ 'aria-label': 'Remove spelling', title: 'Remove spelling' }}>{s}</Pill>)}
            </Pill.Group>
            <SpellingAdd onAdd={addSpelling} />
          </Group>
        </Table.Td>
        <Table.Td><Text size="sm">{p.group}</Text></Table.Td>
        <Table.Td>
          <Group gap={6} wrap="nowrap">
            <Button size="xs" variant="default" onClick={() => onToggle(id)}>Details</Button>
            <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />} onClick={removeEntry}>Remove</Button>
          </Group>
        </Table.Td>
      </Table.Tr>
      {open ? <Table.Tr><Table.Td colSpan={5}><Detail id={id} lref={lref} onChange={redraw} /></Table.Td></Table.Tr> : null}
    </>
  );
}

function Detail({ id, lref, onChange }: { id: string; lref: ListRef; onChange: () => void }) {
  const list = () => currentList(lref);
  const get_ = () => list()[id];
  const p = entryParts(get_());
  const pin = S.pin && S.pin[id];
  const notes = notesFor(S.notes, lref.uri, lref.coordinate, id);
  const set = (key: string, t: string) => { setEntryField(list(), id, key, t); markDirty(); onChange(); };
  const ff = ((S.form && S.form.entry) || []).filter((f: Obj) => !ENTRY_KEYS.includes(f.key));
  const origList = lref.orig() && isObj(lref.orig()![lref.key]) ? lref.orig()![lref.key] : {};
  return (
    <Stack gap="sm" p="xs">
      {notes.map((n, i) => <Alert key={i} color="yellow" p="xs">{n.kind + ': ' + n.text}</Alert>)}
      <Group align="flex-start" grow>
        <AreaBox label="definition (spec)" minRows={4} value={p.definition} onText={t => set('definition', t)} />
        <Box>
          <Group gap={6}><Text size="sm" fw={500}>definition (ontology snapshot)</Text>{pin && pin.deprecated ? <Badge color="red" size="sm">deprecated</Badge> : null}</Group>
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {pin ? ((pin.label ? pin.label + ': ' : '') + (pin.definition || '(no definition)')) : (id.startsWith('out:') ? '(the profile\'s own entry)' : '(not a term of the snapshot)')}
          </Text>
          {pin && pin.alt_labels && pin.alt_labels.length ? <Help text={'alt labels: ' + pin.alt_labels.join(', ')} /> : null}
        </Box>
      </Group>
      <Group align="flex-start" grow>
        <AreaBox label="gloss" minRows={3} value={p.gloss} onText={t => set('gloss', t)} />
        <TextBox label="group" value={p.group} onText={t => set('group', t)} />
      </Group>
      {!Array.isArray(get_()) && ff.length
        ? <SpecForm fields={ff} obj={get_()} orig={origList[id] && isObj(origList[id]) ? origList[id] : null} ctx={{ skipQuiet: new Set(ENTRY_KEYS) }} />
        : null}
    </Stack>
  );
}

export function EntriesTable({ lref }: { lref: ListRef }) {
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const redraw = useRedraw();
  const list = currentList(lref);
  const ids = Object.keys(list);
  const shownIds = ids.filter(id => entryMatches(id, list[id], q));
  const toggle = (id: string) => setOpen(o => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return (
    <Stack gap="xs">
      <Group gap="sm">
        <TextInput style={{ flex: 1, minWidth: 220 }} leftSection={<IconSearch size={16} />} spellCheck={false}
          placeholder="Filter by id, name or spelling" value={q} onChange={e => setQ(e.currentTarget.value)} />
        <Text size="sm" c="dimmed">{shownIds.length + ' of ' + ids.length + ' entries shown'}</Text>
        <Button variant="light" leftSection={<IconPlus size={16} />} onClick={() => termDialog(lref, selected)}>Add entry…</Button>
        <Button variant="light" leftSection={<IconPlus size={16} />} onClick={() => ownDialog(lref, selected)}>Add own entry (out:)…</Button>
      </Group>
      <Table.ScrollContainer minWidth={760}>
        <Table withTableBorder className="dp-spec-table">
          <Table.Thead><Table.Tr><Table.Th>id</Table.Th><Table.Th>name</Table.Th><Table.Th>spellings</Table.Th><Table.Th>group</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {shownIds.map(id => (
              <Fragment key={id}>
                <EntryRow id={id} lref={lref} selected={selected === id} onSelect={setSelected} open={open.has(id)} onToggle={toggle} onSpelling={redraw} />
              </Fragment>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}

/* a new entry goes after the selected row, else at the end */
function addToList(lref: ListRef, afterId: string | null, id: string, entry: unknown): boolean {
  const hd = lref.holder()!;
  if (!isObj(hd[lref.key])) hd[lref.key] = {};
  if (own(hd[lref.key], id)) { showError(new Error('The entry ' + id + ' is in this list already.')); return false; }
  hd[lref.key] = listWithEntryAfter(hd[lref.key], afterId, id, entry);
  markDirty();
  return true;
}

interface Term { id: string; label?: string; definition?: string | null; deprecated?: boolean }
function TermDialog({ lref, afterId, modalId }: { lref: ListRef; afterId: string | null; modalId: string }) {
  const [q, setQ] = useState('');
  const [res, setRes] = useState<{ terms: Term[]; total: number } | null>(null);
  const [busy, setBusy] = useState(true);
  const seq = useRef(0);
  useEffect(() => {
    const t = setTimeout(async () => {
      const my = ++seq.current;
      setBusy(true);
      try {
        const r = await get('/api/terms?q=' + encodeURIComponent(q) + '&limit=50');
        if (my === seq.current) setRes(r);
      } catch (e) { if (my === seq.current) showError(e); }
      if (my === seq.current) setBusy(false);
    }, q === '' && res === null ? 0 : 250);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  const cur = currentList(lref);
  return (
    <Stack>
      <TextInput data-autofocus leftSection={<IconSearch size={16} />} spellCheck={false} value={q} onChange={e => setQ(e.currentTarget.value)}
        placeholder="Search the ontology snapshot by id, label or alternative label" rightSection={busy ? <Loader size={16} /> : null} />
      {res ? <Text size="sm" c="dimmed">{res.total + ' terms match' + (res.terms.length < res.total ? ' (first ' + res.terms.length + ' shown)' : '')}</Text> : null}
      <Stack gap="xs" mah="55vh" style={{ overflow: 'auto' }}>
        {(res ? res.terms : []).map(t => (
          <Group key={t.id} justify="space-between" wrap="nowrap" align="flex-start">
            <Box style={{ minWidth: 0 }}>
              <Group gap={6}><Code>{t.id}</Code><Text fw={600}>{t.label || ''}</Text>{t.deprecated ? <Badge color="red" size="sm">deprecated</Badge> : null}</Group>
              <Text size="sm" c="dimmed">{(t.definition || '').slice(0, 200)}</Text>
            </Box>
            <Button size="xs" variant="light" disabled={own(cur, t.id)}
              onClick={() => { if (addToList(lref, afterId, t.id, newEntryFromTerm({ label: t.label || '', definition: t.definition }))) { modals.close(modalId); structural(); } }}>
              {own(cur, t.id) ? 'In list' : 'Add'}
            </Button>
          </Group>
        ))}
      </Stack>
      <Group justify="flex-end"><Button variant="default" onClick={() => modals.close(modalId)}>Close</Button></Group>
    </Stack>
  );
}
function termDialog(lref: ListRef, afterId: string | null) {
  const id = 'spec-term-' + Math.random().toString(36).slice(2);
  modals.open({ modalId: id, title: 'Add entry', size: 'lg', centered: true, children: <TermDialog lref={lref} afterId={afterId} modalId={id} /> });
}

function OwnDialog({ lref, afterId, modalId }: { lref: ListRef; afterId: string | null; modalId: string }) {
  const [id, setId] = useState('out:');
  const [name, setName] = useState('');
  const add = () => {
    const i = id.trim(); const n = name;
    if (!i.startsWith('out:') || i.length <= 4) { showError(new Error('The id of an own entry starts with "out:" and has a name after it.')); return; }
    if (!n.trim()) { showError(new Error('An entry needs a name.')); return; }
    if (addToList(lref, afterId, i, { label: n })) { modals.close(modalId); structural(); }
  };
  return (
    <Stack>
      <TextBox label="Id (starts with out:)" value={id} onText={setId} />
      <TextBox label="Name" placeholder="name" value={name} onText={setName} />
      <Group justify="flex-end">
        <Button variant="default" onClick={() => modals.close(modalId)}>Cancel</Button>
        <Button onClick={add}>Add</Button>
      </Group>
    </Stack>
  );
}
function ownDialog(lref: ListRef, afterId: string | null) {
  const id = 'spec-own-' + Math.random().toString(36).slice(2);
  modals.open({ modalId: id, title: 'Add own entry', centered: true, children: <OwnDialog lref={lref} afterId={afterId} modalId={id} /> });
}
