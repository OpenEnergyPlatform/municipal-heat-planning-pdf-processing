/* The right column of the Spec tab: the settings of what is selected. A field, its units, a dimension of a field (one it
   shares with other fields says so, and can become the field's own), a shared dimension, an entry of a list with the words
   of the plans it gathers, a list of the ontology a dimension takes its entries from, the order of the questions, a field
   of the whole document, the works, a value type, the questions of the spec. A list opens wide over the page
   (ListModal). */
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { Alert, Anchor, Badge, Box, Button, Code, Group, Menu, Modal, NativeSelect, Stack, Text, Title } from '@mantine/core';
import { IconCopy, IconList, IconPlus, IconShare, IconTrash, IconX } from '@tabler/icons-react';
import { AreaBox, TextBox } from '../components/Inputs';
import { useStore } from '../lib/nav';
import { t, tn } from '../lib/i18n';
import { axisKinds, entryParts, setEntryField, setEntryName, UNIT_KEYS, type SpecNode } from '../lib/spec';
import { isObj, type Obj } from '../lib/util';
import {
  addAxis, addCheck, addUnit, closeList, copyNode, deleteNode, ensureSel, listCount, listOf, markDirty, meta, nodeObj, openList,
  removeValueType, S, select, shareAt, show, touch, typeOf, unshareAt, view, wordAdded, wordRemoved,
} from './state';
import { fieldOf, isSharedAt, originOf, sharedOf, termOf, usersOf } from './model';
import { named, nameOf } from './names';
import { FlaggedKey, SpecForm, StringsEditor, useEdit } from './widgets';
import { EntriesTable, refFor } from './entries';
import { WordAdd } from './Dictionary';

const labelOf = (uri: string) => (fieldOf(S.data, uri) || {}).label || uri;

export function titleOf(n: SpecNode): [string, string] {
  switch (n.t) {
    case 'spec': return [t('Questions and note of the spec'), ''];
    case 'plan': return [((S.data.plan_fields || {})[n.key] || {}).name || n.key, t('A field of the whole document holds for all values of a document, such as its base year or its municipality.')];
    case 'works': return [t('Works'), t('The works are the other studies or plans that a document presents, compares or cites besides itself. Here you set what is asked about each new work.')];
    case 'coordinates': return [t('Order of the questions'), ''];
    case 'param': return [labelOf(n.uri), ''];
    case 'units': return [t('Units of {field}', { field: labelOf(n.uri) }), t('The units a number of this field may be printed in, each with its factor into the target unit.')];
    case 'plist': return [t('List of {field}', { field: labelOf(n.uri) }), ''];
    case 'axis': return [nameOf(n.name), named(n.name).about];
    case 'shared': return [nameOf(n.name), named(n.name).about];
    case 'vtype': return [t('Value type {name}', { name: n.name }), ''];
    case 'entry': return [t('Entry'), ''];
    case 'root': return [t('A list of the ontology'), ''];
  }
}

function Actions({ n }: { n: SpecNode }) {
  const busy = S.busy;
  if (n.t === 'param') return (
    <Group gap="xs">
      <Button size="xs" variant="default" disabled={busy} leftSection={<IconCopy size={14} />} onClick={() => copyNode('field', n)}>{t('Copy as new field…')}</Button>
      <Button size="xs" variant="light" color="red" disabled={busy} leftSection={<IconTrash size={14} />} onClick={() => deleteNode('field', n)}>{t('Delete field')}</Button>
    </Group>
  );
  if (n.t === 'axis') return (
    <Group gap="xs">
      <Button size="xs" variant="default" disabled={busy} leftSection={<IconCopy size={14} />} onClick={() => copyNode('coordinate', n)}>{t('Copy as new dimension…')}</Button>
      <Button size="xs" variant="light" color="red" disabled={busy} leftSection={<IconTrash size={14} />} onClick={() => deleteNode('coordinate', n)}>{t('Take the dimension from this field')}</Button>
    </Group>
  );
  if (n.t === 'plan') return <Button size="xs" variant="light" color="red" disabled={busy} leftSection={<IconTrash size={14} />} onClick={() => deleteNode('plan_field', n)}>{t('Remove field of the whole document')}</Button>;
  if (n.t === 'works') return <Button size="xs" variant="light" color="red" disabled={busy} leftSection={<IconTrash size={14} />} onClick={() => deleteNode('works', n)}>{t('Remove works')}</Button>;
  if (n.t === 'vtype' && !typeOf(n.name)?.builtin) return <Button size="xs" variant="light" color="red" disabled={busy} leftSection={<IconTrash size={14} />} onClick={() => void removeValueType(n.name)}>{t('Delete value type')}</Button>;
  return null;
}

function TypeSelect({ obj }: { obj: Obj }) {
  const edit = useEdit();
  const opts = ['int', 'text'];
  if (!opts.includes(obj.type)) opts.push(obj.type);
  return <NativeSelect w={160} value={String(obj.type)} data={opts.map(o => ({ value: String(o), label: String(o) }))}
    onChange={e => { const v = e.currentTarget.value; edit(() => { obj.type = v; }); }} />;
}

const Section = ({ children }: { children: ReactNode }) => <Title order={5} mt="sm">{children}</Title>;

function ListButton({ uri, coordinate, k, count }: { uri: string; coordinate: string | null; k: string; count: number }) {
  return (
    <Group gap="xs">
      <Button size="xs" variant="light" leftSection={<IconList size={14} />} onClick={() => openList(uri, coordinate, k)}>{t('Edit the whole list…')}</Button>
      <Text size="sm">{tn(count, '{n} entry', '{n} entries')}</Text>
    </Group>
  );
}

/* whether a field's dimension is the shared one, and the way to make it the field's own or the shared one again */
function SharedNote({ uri, name }: { uri: string; name: string }) {
  useStore(meta);
  const users = usersOf(S.data, name);
  if (isSharedAt(S.data, uri, name)) return (
    <Alert color="indigo" variant="light" title={tn(users.length, 'Shared by {n} field', 'Shared by {n} fields')}>
      <Stack gap={6}>
        <Text size="sm">{t('These fields ask this dimension alike: an edit here changes it in each of them.')}</Text>
        <Group gap={6}>{users.map(u => <Anchor key={u} component="button" type="button" size="sm" onClick={() => show({ t: 'field', uri: u })}>{labelOf(u)}</Anchor>)}</Group>
        <Group gap="xs">
          <Button size="compact-xs" variant="light" onClick={() => unshareAt(uri, name)}>{t('Change only for this field')}</Button>
          <Button size="compact-xs" variant="subtle" onClick={() => show({ t: 'shared', name })}>{t('Show as a dictionary')}</Button>
        </Group>
      </Stack>
    </Alert>
  );
  if (isObj(sharedOf(S.data)[name])) return (
    <Alert color="yellow" variant="light" title={t('Only for {field}', { field: labelOf(uri) })}>
      <Stack gap={6}>
        <Text size="sm">{t('This field asks its own copy of {name}; other fields ask the shared one.', { name: nameOf(name) })}</Text>
        <Box><Button size="compact-xs" variant="light" leftSection={<IconShare size={12} />} onClick={() => void shareAt(uri, name)}>{t('Ask the shared one again')}</Button></Box>
      </Stack>
    </Alert>
  );
  return (
    <Group gap="xs">
      <Text size="sm" c="dimmed">{t('Only this field asks this dimension.')}</Text>
      <Button size="compact-xs" variant="subtle" leftSection={<IconShare size={12} />} onClick={() => void shareAt(uri, name)}>{t('Make it a shared dimension')}</Button>
    </Group>
  );
}

/* what a dimension may answer and its other keys, for a field's dimension and for a shared one alike */
function AxisForm({ obj, orig, uri, name }: { obj: Obj; orig: Obj | null; uri: string | null; name: string }) {
  const f = S.form || {};
  const kinds = axisKinds(obj);
  const quiet = new Set(['vocabulary', 'type', 'enum', 'dynamic', 'beside']);
  const listUri = uri || usersOf(S.data, name)[0] || '';
  const origin = isObj(obj.vocabulary) ? originOf(obj.vocabulary, name, S.onto) : null;
  return (
    <Stack gap="sm">
      <Section>{t('What the dimension may answer')}</Section>
      {kinds.length !== 1 ? (
        <Alert color="yellow">{kinds.length ? t('More than one of vocabulary, type, enum and dynamic is set for this dimension, but the run needs exactly one of them. Remove the others so that the Spec can be saved.') : t('None of vocabulary, type, enum and dynamic is set for this dimension, but the run needs exactly one of them. Set one so that the Spec can be saved.')}</Alert>
      ) : null}
      {kinds.map(k => {
        if (k === 'vocabulary') return (
          <FlaggedKey key={k} k="vocabulary">
            <Stack gap="xs">
              <Badge variant="light" w="fit-content" tt="none">{t('a list of entries')}</Badge>
              {origin ? <Text size="sm">{t('{under} of its entries come from the list {label} of the ontology, {own} are the spec\'s own.', { under: origin.under.length, label: origin.root.label || origin.set, own: origin.own.length })}</Text> : null}
              {listUri ? <ListButton uri={listUri} coordinate={name} k="vocabulary" count={listCount(obj.vocabulary)} /> : null}
            </Stack>
          </FlaggedKey>
        );
        if (k === 'type') return (
          <FlaggedKey key={k} k="type">
            <Group gap="xs"><Badge variant="light" tt="none">{t('a free value')}</Badge><Text fw={600}>type</Text>{/* i18n-ignore: the key's name */}<TypeSelect obj={obj} /></Group>
          </FlaggedKey>
        );
        if (k === 'enum') return (
          <FlaggedKey key={k} k="enum">
            <Stack gap="xs"><Badge variant="light" w="fit-content" tt="none">{t('a list of strings')}</Badge><StringsEditor obj={obj} k="enum" keep /></Stack>
          </FlaggedKey>
        );
        return (
          <FlaggedKey key={k} k="dynamic">
            <Group gap="xs"><Badge variant="light" tt="none">{t('set per document')}</Badge><Text size="sm">{t('The list of this dimension is not fixed in the Spec: the profile sets it anew for each document.')}</Text></Group>
          </FlaggedKey>
        );
      })}
      {isObj(obj.beside) && listUri ? (
        <FlaggedKey k="beside">
          <Section>{t('Answers outside the list')}</Section>
          <ListButton uri={listUri} coordinate={name} k="beside" count={listCount(obj.beside)} />
        </FlaggedKey>
      ) : null}
      <Section>{t('The other keys of the dimension')}</Section>
      <SpecForm fields={f.axis} obj={obj} orig={orig} ctx={{ skip: quiet, skipQuiet: quiet }} />
    </Stack>
  );
}

/* an entry of a list: its name, the words of the plans it gathers, what the ontology says of it */
function EntryPanel({ n }: { n: Extract<SpecNode, { t: 'entry' }> }) {
  const edit = useEdit();
  const list = listOf(S.data, n);
  if (!list || !(n.id in list)) return <Text size="sm" c="dimmed">{t('The entry is no longer in its list.')}</Text>;
  const p = entryParts(list[n.id]);
  const term = S.pin[n.id];
  const f = (S.form && S.form.entry) || [];
  const help = (k: string) => (f.find((x: Obj) => x.key === k) || {}).help || '';
  const where = { uri: n.uri, name: n.name, key: n.key };
  return (
    <Stack gap="sm">
      <Group gap="xs"><Code>{n.id}</Code>{n.name ? <Badge variant="light" tt="none">{nameOf(n.name)}</Badge> : null}</Group>
      {isObj(term) ? (
        <Alert color="blue" variant="light" title={t('In the ontology: {label}', { label: term.label || termOf(n.id) })}>
          <Text size="sm">{term.definition || t('The ontology gives no definition.')}</Text>
        </Alert>
      ) : <Text size="sm" c="dimmed">{t('An entry of the spec\'s own: no ontology has it.')}</Text>}
      <TextBox label={t('Name')} description={help('label')} value={p.name} onText={v => edit(() => { setEntryName(list, n.id, v); })} />
      <Box>
        <Text size="sm" fw={500}>{t('Words of the plans')}</Text>
        <Text size="xs" c="dimmed" mb={4}>{help('spellings')}</Text>
        <Group gap={6}>
          {p.spellings.map(w => (
            <span key={w} className="sp-word">{w}<button type="button" className="sp-word-x" aria-label={t('Take the word out')} onClick={() => wordRemoved(where, n.id, w)}><IconX size={11} /></button></span>
          ))}
        </Group>
        <Box mt={6}><WordAdd onAdd={w => wordAdded(where, n.id, w)} /></Box>
      </Box>
      <AreaBox label={t('Definition')} description={help('definition')} minRows={3} value={p.definition} onText={v => edit(() => { setEntryField(list, n.id, 'definition', v); })} />
      <AreaBox label={t('Gloss')} description={help('gloss')} minRows={2} value={p.gloss} onText={v => edit(() => { setEntryField(list, n.id, 'gloss', v); })} />
      <TextBox label={t('Group')} description={help('group')} value={p.group} onText={v => edit(() => { setEntryField(list, n.id, 'group', v); })} />
    </Stack>
  );
}

/* a list of the ontology: what it is and how many of its terms a list of the spec takes */
function RootPanel({ set }: { set: string }) {
  const s = S.onto.sets[set];
  if (!s) return null;
  return (
    <Stack gap="sm">
      <Group gap="xs"><Text fw={650}>{s.label || s.root}</Text><Code>{s.root}</Code></Group>
      <Text size="sm">{s.kind === 'individual' ? t('Its entries are the individuals of this class.') : t('Its entries are this class and the classes under it.')}</Text>
      {s.definition ? <Alert color="blue" variant="light" title={t('Definition in the ontology')}><Text size="sm">{s.definition}</Text></Alert> : null}
      <Text size="sm">{tn(s.members.length, 'The snapshot of the ontology carries {n} term under it.', 'The snapshot of the ontology carries {n} terms under it.')}</Text>
      <Text size="sm" c="dimmed">{t('Which list of the ontology a dimension draws from stands in the Sources tab; new entries of it are put in under "Edit the whole list".')}</Text>
    </Stack>
  );
}

/* what a field asks besides what the drawing shows: the dimensions it can get */
function AddDimension({ uri }: { uri: string }) {
  const p = fieldOf(S.data, uri);
  const shared = Object.keys(sharedOf(S.data)).filter(name => !(p && isObj(p.axes) && name in p.axes));
  const kinds = Object.keys(S.library.dimensions || {});
  const KIND_WORDS = (): Record<string, string> => ({
    list: t('A list of entries'), year: t('A year'), words: t('The words of the document'), per_document: t('A list per document'),
  });
  return (
    <Menu withinPortal position="bottom-start">
      <Menu.Target><Button size="xs" variant="light" leftSection={<IconPlus size={14} />}>{t('Ask one more dimension')}</Button></Menu.Target>
      <Menu.Dropdown>
        {shared.length ? <Menu.Label>{t('A shared dimension')}</Menu.Label> : null}
        {shared.map(name => <Menu.Item key={name} onClick={() => void addAxis(uri, { shared: name })}>{nameOf(name)}</Menu.Item>)}
        <Menu.Label>{t('A dimension of its own')}</Menu.Label>
        {kinds.map(k => <Menu.Item key={k} onClick={() => void addAxis(uri, { kind: k })}>{KIND_WORDS()[k] || k}</Menu.Item>)}
      </Menu.Dropdown>
    </Menu>
  );
}

export function Main() {
  useStore(view);
  const el = useRef<HTMLDivElement>(null);
  ensureSel();
  const n = S.sel;
  const obj = nodeObj(S.data, n);
  const orig = nodeObj(S.orig, n) ?? null;
  const [title, sub] = titleOf(n);
  const f = S.form || {};
  const coordNames = new Set<string>();
  for (const p of S.data.parameters || []) for (const k of Object.keys(p.axes || {})) coordNames.add(k);

  // a new node starts at the top, or at the field an error names
  useLayoutEffect(() => {
    if (!S.resetScroll) return;
    S.resetScroll = false;
    const fl = S.flag;
    const target = fl && fl.field ? el.current?.querySelector('.dp-flag') : null;
    if (target) target.scrollIntoView({ block: 'center' });
    else if (el.current) el.current.scrollTop = 0;
  });

  const skipAll = new Set(['plan_fields', 'works', 'coordinates', 'shared_axes', 'parameters']);
  let body: ReactNode = null;
  switch (n.t) {
    case 'spec': body = <SpecForm fields={f.spec} obj={obj} orig={orig} ctx={{ skip: skipAll, skipQuiet: skipAll }} />; break;
    case 'plan': body = <SpecForm fields={f.plan_field} obj={obj} orig={orig} />; break;
    case 'works': body = <SpecForm fields={f.works} obj={obj} orig={orig} />; break;
    case 'coordinates': body = (
      <Stack gap="sm">
        <Text size="sm">{((f.coordinates || [])[0] || {}).about || ''}</Text>
        <Anchor component="button" type="button" size="sm" onClick={() => show({ t: 'order' })}>{t('Show the order of the questions')}</Anchor>
        <SpecForm fields={f.coordinates} obj={obj} orig={orig} ctx={{ coordNames: [...coordNames] }} />
      </Stack>
    ); break;
    case 'param': case 'plist': {
      const units = isObj(obj.units_accepted);
      const skip = new Set(['axes', 'vocabulary', 'beside', ...(units ? UNIT_KEYS : [])]);
      body = (
        <Stack gap="md">
          <Group gap="xs">
            <AddDimension uri={n.uri} />
            {units ? <Button size="xs" variant="light" onClick={() => select({ t: 'units', uri: n.uri })}>{t('Units')}</Button> : null}
            {units ? <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => void addUnit(n.uri)}>{t('An accepted unit')}</Button> : null}
            <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => addCheck(n.uri)}>{t('A check of its own')}</Button>
          </Group>
          {(['vocabulary', 'beside'] as const).filter(k => isObj(obj[k])).map(k => (
            <Box key={k}><Text fw={600} mb={4}>{k === 'vocabulary' ? t('List') : t('Answers outside the list')}</Text>
              <ListButton uri={n.uri} coordinate={null} k={k} count={listCount(obj[k])} /></Box>
          ))}
          <SpecForm fields={f.parameter} obj={obj} orig={orig} ctx={{
            skip, skipQuiet: skip,
            onUri: v => { if (n.t === 'param' && v !== n.uri) { S.sel = { t: 'param', uri: v }; if (S.view.t === 'field') S.view = { t: 'field', uri: v }; touch(); } },
          }} />
        </Stack>
      );
      break;
    }
    case 'units': {
      const keep = new Set(UNIT_KEYS);
      const rest = new Set(Object.keys(obj).filter(k => !keep.has(k)).concat((f.parameter || []).map((x: Obj) => x.key).filter((k: string) => !keep.has(k))));
      body = <SpecForm fields={f.parameter} obj={obj} orig={orig} ctx={{ skip: rest, skipQuiet: rest }} />;
      break;
    }
    case 'axis': body = <Stack gap="md"><SharedNote uri={n.uri} name={n.name} /><AxisForm obj={obj} orig={orig} uri={n.uri} name={n.name} /></Stack>; break;
    case 'shared': body = (
      <Stack gap="md">
        <Text size="sm">{tn(usersOf(S.data, n.name).length, 'Asked alike by {n} field: an edit here changes it in each of them.', 'Asked alike by {n} fields: an edit here changes it in each of them.')}</Text>
        <AxisForm obj={obj} orig={orig} uri={null} name={n.name} />
      </Stack>
    ); break;
    case 'entry': body = <EntryPanel n={n} />; break;
    case 'root': body = <RootPanel set={n.set} />; break;
    case 'vtype': body = typeOf(n.name)?.builtin
      ? <Stack gap="xs"><Text size="sm" c="dimmed">{t('A built-in value type: a preset that cannot be changed. Add a value type of your own to change these settings.')}</Text>
        {Object.entries(obj || {}).map(([k, v]) => <Text key={k} size="sm"><b>{k}</b>: {String(v)}</Text>)}</Stack>
      : <SpecForm fields={f.value_type} obj={obj} orig={orig} />;
      break;
  }
  return (
    <Box ref={el} className="dp-scroll sp-side-panel" p="md">
      <Stack gap="md" key={S.rev}>
        <Group justify="space-between" align="flex-start">
          <Box>
            <Title order={4}>{title}</Title>
            {sub ? <Text size="sm" c="dimmed">{sub}</Text> : null}
          </Box>
          <Actions n={n} />
        </Group>
        {obj === undefined && n.t !== 'spec' ? <Text size="sm" c="dimmed">{t('Nothing selected.')}</Text> : body}
      </Stack>
    </Box>
  );
}

/* a list wide over the page: the entries of a field's list or of a dimension's, or its answers outside the list */
export function ListModal() {
  useStore(view);
  const L = S.list;
  const shared = L && L.coordinate && isSharedAt(S.data, L.uri, L.coordinate) ? usersOf(S.data, L.coordinate).length : 0;
  const title = !L ? '' : L.coordinate
    ? (L.key === 'beside' ? t('Answers outside the list of {name}', { name: nameOf(L.coordinate) }) : t('List of {name}', { name: nameOf(L.coordinate) }))
    : (L.key === 'beside' ? t('Answers outside the list of {field}', { field: labelOf(L.uri) }) : t('List of {field}', { field: labelOf(L.uri) }));
  return (
    <Modal opened={!!L} onClose={closeList} size="90%" title={<Text fw={650}>{title}</Text>}>
      {L ? (
        <Stack gap="sm">
          {shared > 1 ? <Alert color="indigo" p="xs">{t('An edit here changes the list in each of the {n} fields that share it.', { n: shared })}</Alert> : null}
          <EntriesTable lref={refFor(L.uri, L.coordinate, L.key, L.entry)} />
        </Stack>
      ) : null}
    </Modal>
  );
}

export { markDirty };
