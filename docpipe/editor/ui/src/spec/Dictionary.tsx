/* A shared dimension as a dictionary: where its entries come from in the ontology, which fields ask it, and each entry
   with the words of the plans it gathers. A word is typed in, taken out, or dragged onto another entry; the whole list,
   with entries of the ontology to put in, opens wide over the page. */
import { useState } from 'react';
import { Alert, Anchor, Badge, Box, Button, Code, Group, Stack, Switch, Text, TextInput, Title } from '@mantine/core';
import { IconList, IconSearch, IconX } from '@tabler/icons-react';
import { t, tn } from '../lib/i18n';
import { useStore } from '../lib/nav';
import { entriesOf, fieldOf, isOwnEntry, kindOf, originOf, sharedOf, termOf, usersOf, type Entry } from './model';
import { named } from './names';
import { WORD } from './nodes';
import { openList, S, select, show, toggleOpen, view, wordAdded, wordMoved, wordRemoved } from './state';

const inOntology = (id: string) => !!S.pin[id] || Object.values(S.onto.sets).some(s => s.members.includes(termOf(id)));
const fieldName = (uri: string) => (fieldOf(S.data, uri) || {}).label || uri;

export function WordAdd({ onAdd }: { onAdd: (w: string) => boolean }) {
  const [text, setText] = useState('');
  return (
    <TextInput size="xs" w={150} placeholder={t('add a word')} value={text} onChange={e => setText(e.currentTarget.value)}
      onKeyDown={e => { if (e.key === 'Enter' && text.trim()) { e.preventDefault(); if (onAdd(text)) setText(''); } }} />
  );
}

function EntryLine({ e, where }: { e: Entry; where: { uri: string | null; name: string | null; key: string } }) {
  const term = S.pin[e.id];
  const own = isOwnEntry(e.id, inOntology);
  const sel = S.sel.t === 'entry' && S.sel.id === e.id && S.sel.name === where.name;
  return (
    <Box className={'sp-dict-row' + (sel ? ' is-sel' : '')}
      onDragOver={ev => { if (ev.dataTransfer.types.includes(WORD)) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'move'; } }}
      onDrop={ev => {
        const raw = ev.dataTransfer.getData(WORD);
        if (!raw) return;
        ev.preventDefault();
        const w = JSON.parse(raw);
        wordMoved(where, w.from, w.word, e.id);
      }}>
      <Box className="sp-dict-name">
        <Anchor component="button" type="button" fw={650} size="sm" ta="left"
          onClick={() => select({ t: 'entry', uri: where.uri, name: where.name, key: where.key, id: e.id })}>{e.label || e.id}</Anchor>
        {own ? <Badge size="xs" variant="light" color="gray" tt="none">{t('own entry')}</Badge>
          : <Text size="xs" c="dimmed">{(term && term.label ? term.label + ' · ' : '') + termOf(e.id)}</Text>}
      </Box>
      <Group gap={6} className="sp-dict-words">
        {e.words.map(w => (
          <span key={w} className="sp-word" draggable title={t('Drag onto another entry to move the word there.')}
            onDragStart={ev => { ev.dataTransfer.setData(WORD, JSON.stringify({ from: e.id, word: w })); ev.dataTransfer.effectAllowed = 'move'; }}>
            {w}
            <button type="button" className="sp-word-x" aria-label={t('Take the word out')} onClick={() => wordRemoved(where, e.id, w)}><IconX size={11} /></button>
          </span>
        ))}
        <WordAdd onAdd={w => wordAdded(where, e.id, w)} />
      </Group>
    </Box>
  );
}

export function Dictionary({ name }: { name: string }) {
  useStore(view);
  const [q, setQ] = useState('');
  const axis = sharedOf(S.data)[name];
  const about = named(name);
  const users = usersOf(S.data, name);
  if (!axis) return null;
  const kind = kindOf(axis);
  const where = { uri: null, name, key: 'vocabulary' };
  const head = (
    <Stack gap={6}>
      <Group gap="sm" align="baseline"><Title order={3}>{about.name}</Title><Code>{name}</Code></Group>
      {about.about ? <Text size="sm">{about.about}</Text> : null}
      <Group gap={6}>
        <Text size="sm" c="dimmed">{tn(users.length, 'Asked by {n} field:', 'Asked by {n} fields:')}</Text>
        {users.map(u => <Anchor key={u} component="button" type="button" size="sm" onClick={() => show({ t: 'field', uri: u })}>{fieldName(u)}</Anchor>)}
      </Group>
      {typeof axis.question === 'string' ? <Text size="sm"><b>{t('The question:')}</b> {axis.question}</Text> : null}
    </Stack>
  );
  if (kind !== 'list') {
    return <Box className="dp-scroll sp-center-page" p="md">{head}<Alert mt="md" color="gray">{t('This dimension has no list: the model answers it with the words or the number of the plan.')}</Alert></Box>;
  }
  const all = entriesOf(axis.vocabulary);
  const origin = originOf(axis.vocabulary, name, S.onto);
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const hit = (e: Entry) => !words.length || words.every(w => [e.id, e.label, ...e.words].join('\n').toLowerCase().includes(w));
  const found = all.filter(hit);
  const shown = found.filter(e => S.open || e.words.length || words.length);
  const folded = found.length - shown.length;
  return (
    <Box className="dp-scroll sp-center-page" p="md">
      <Stack gap="md">
        {head}
        {origin ? (
          <Alert color="blue" variant="light" title={t('From the ontology')}>
            <Text size="sm">{t('The entries come from the list {label} ({root}) of the ontology: {members} terms stand under it there. {under} entries of this list come from it, {own} are the spec\'s own.', { label: origin.root.label || origin.set, root: origin.root.root, members: origin.root.members.length, under: origin.under.length, own: origin.own.length })}</Text>
            <Anchor component="button" type="button" size="sm" onClick={() => select({ t: 'root', set: origin.set })}>{t('What the ontology says of it')}</Anchor>
          </Alert>
        ) : <Alert color="gray">{t('No list of the ontology holds an entry of this list: all its entries are the spec\'s own.')}</Alert>}
        <Group gap="sm" align="flex-end">
          <TextInput leftSection={<IconSearch size={14} />} w={280} placeholder={t('Find an entry or a word')} value={q} onChange={e => setQ(e.currentTarget.value)} />
          <Switch checked={S.open} onChange={toggleOpen} label={tn(all.filter(e => !e.words.length).length, 'Show the {n} entry without a word too', 'Show the {n} entries without a word too')} />
          <Button variant="light" leftSection={<IconList size={16} />} disabled={!users.length} onClick={() => openList(users[0], name, 'vocabulary')}>{t('Edit the whole list…')}</Button>
        </Group>
        <Text size="sm" c="dimmed">{t('Each entry gathers the words the plans write for it. Drag a word onto another entry to move it there.')}</Text>
        <Stack gap={4}>
          {shown.map(e => <EntryLine key={e.id} e={e} where={where} />)}
          {folded > 0 ? <Text size="sm" c="dimmed">{tn(folded, '{n} more entry without a word of the plans', '{n} more entries without a word of the plans')}</Text> : null}
          {!found.length ? <Text size="sm" c="dimmed">{t('No entry matches.')}</Text> : null}
        </Stack>
      </Stack>
    </Box>
  );
}
