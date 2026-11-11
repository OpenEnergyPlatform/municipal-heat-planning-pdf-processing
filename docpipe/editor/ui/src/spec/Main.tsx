/* The form of the selected node, on the right of the tree. */
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { Alert, Badge, Box, Button, Group, NativeSelect, Stack, Text, Title } from '@mantine/core';
import { IconCopy, IconTrash } from '@tabler/icons-react';
import { useStore } from '../lib/nav';
import { t, tn } from '../lib/i18n';
import { axisKinds, type SpecNode } from '../lib/spec';
import { isObj, type Obj } from '../lib/util';
import { copyNode, deleteNode, ensureSel, listCount, nodeObj, S, touch, view } from './state';
import { FlaggedKey, SpecForm, StringsEditor, useEdit } from './widgets';
import { EntriesTable, refFor } from './entries';

export function titleOf(n: SpecNode): [string, string] {
  switch (n.t) {
    case 'spec': return [t('Questions and note of the spec'), ''];
    case 'plan': return [t('Field of the whole document {key}', { key: n.key }), t('A field of the whole document holds for all values of a document, such as its base year or its municipality.')];
    case 'works': return [t('Works'), t('The works are the other studies or plans that a document presents, compares or cites besides itself. Here you set what is asked about each new work.')];
    case 'group': return [t('Group {name}', { name: n.name }), t('A group holds dimensions that a document prints together, for example in one table.')];
    case 'param': return [t('Field {uri}', { uri: n.uri }), ''];
    case 'plist': return [n.list === 'beside' ? t('Field {uri} · answers outside the list', { uri: n.uri }) : t('Field {uri} · list', { uri: n.uri }), t('These are the entries of the list. A value the model reads for this field must be one of them. Your edits to the entries are written with the next save.')];
    case 'axis': return [t('Dimension {name} of field {uri}', { name: n.name, uri: n.uri }), ''];
  }
}

function Actions({ n }: { n: SpecNode }) {
  const busy = S.busy;
  if (n.t === 'param') return (
    <Group gap="xs">
      <Button variant="default" disabled={busy} leftSection={<IconCopy size={16} />} onClick={() => copyNode('field', n)}>{t('Copy as new field…')}</Button>
      <Button variant="light" color="red" disabled={busy} leftSection={<IconTrash size={16} />} onClick={() => deleteNode('field', n)}>{t('Delete field')}</Button>
    </Group>
  );
  if (n.t === 'axis') return (
    <Group gap="xs">
      <Button variant="default" disabled={busy} leftSection={<IconCopy size={16} />} onClick={() => copyNode('coordinate', n)}>{t('Copy as new dimension…')}</Button>
      <Button variant="light" color="red" disabled={busy} leftSection={<IconTrash size={16} />} onClick={() => deleteNode('coordinate', n)}>{t('Delete dimension')}</Button>
    </Group>
  );
  if (n.t === 'plan') return <Button variant="light" color="red" disabled={busy} leftSection={<IconTrash size={16} />} onClick={() => deleteNode('plan_field', n)}>{t('Remove field of the whole document')}</Button>;
  if (n.t === 'works') return <Button variant="light" color="red" disabled={busy} leftSection={<IconTrash size={16} />} onClick={() => deleteNode('works', n)}>{t('Remove works')}</Button>;
  return null;
}

function TypeSelect({ obj }: { obj: Obj }) {
  const edit = useEdit();
  const opts = ['int', 'text'];
  if (!opts.includes(obj.type)) opts.push(obj.type);
  return <NativeSelect w={160} value={String(obj.type)} data={opts.map(o => ({ value: String(o), label: String(o) }))}
    onChange={e => { const v = e.currentTarget.value; edit(() => { obj.type = v; }); }} />;
}

const Section = ({ children }: { children: ReactNode }) => <Title order={4} mt="md">{children}</Title>;

function AxisView({ n, obj, orig }: { n: Extract<SpecNode, { t: 'axis' }>; obj: Obj; orig: Obj | null }) {
  const f = S.form || {};
  const kinds = axisKinds(obj);
  const quiet = new Set(['vocabulary', 'type', 'enum', 'dynamic', 'beside']);
  const mark = S.flag && S.flag.entry;
  return (
    <Stack gap="md">
      <Section>{t('Possible answers of the dimension')}</Section>
      {kinds.length !== 1 ? (
        <Alert color="yellow">{kinds.length ? t('More than one of vocabulary, type, enum and dynamic is set for this dimension, but the run needs exactly one of them. Remove the others so that the Spec can be saved.') : t('None of vocabulary, type, enum and dynamic is set for this dimension, but the run needs exactly one of them. Set one so that the Spec can be saved.')}</Alert>
      ) : null}
      {kinds.map(k => {
        if (k === 'vocabulary') return (
          <Stack key={k} gap="xs">
            <Group gap="xs"><Badge variant="light">{t('a list of entries')}</Badge><Text size="sm">{tn(listCount(obj.vocabulary), '{n} entry', '{n} entries')}</Text></Group>
            <EntriesTable lref={refFor(n.uri, n.name, 'vocabulary', mark)} />
          </Stack>
        );
        if (k === 'type') return (
          <FlaggedKey key={k} k="type">
            <Group gap="xs"><Badge variant="light">{t('a free value')}</Badge><Text fw={600}>type</Text>{/* i18n-ignore: the key's name */}<TypeSelect obj={obj} /></Group>
          </FlaggedKey>
        );
        if (k === 'enum') return (
          <FlaggedKey key={k} k="enum">
            <Stack gap="xs"><Badge variant="light" w="fit-content">{t('a list of strings')}</Badge><StringsEditor obj={obj} k="enum" keep /></Stack>
          </FlaggedKey>
        );
        return (
          <FlaggedKey key={k} k="dynamic">
            <Group gap="xs"><Badge variant="light">{t('set per document')}</Badge><Text size="sm">{t('The list of this dimension is not fixed in the Spec: the profile sets it anew for each document.')}</Text></Group>
          </FlaggedKey>
        );
      })}
      {isObj(obj.beside) ? (
        <>
          <Section>{t('Answers outside the list')}</Section>
          <EntriesTable lref={refFor(n.uri, n.name, 'beside', mark)} />
        </>
      ) : null}
      <Section>{t('The other keys of the dimension')}</Section>
      <SpecForm fields={f.axis} obj={obj} orig={orig} ctx={{ skip: quiet, skipQuiet: quiet }} />
    </Stack>
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

  const skipAll = new Set(['plan_fields', 'works', 'groups', 'parameters']);
  const skipAxes = new Set(['axes', 'vocabulary', 'beside']);
  let body: ReactNode = null;
  switch (n.t) {
    case 'spec': body = <SpecForm fields={f.spec} obj={obj} orig={orig} ctx={{ skip: skipAll, skipQuiet: skipAll }} />; break;
    case 'plan': body = <SpecForm fields={f.plan_field} obj={obj} orig={orig} />; break;
    case 'works': body = <SpecForm fields={f.works} obj={obj} orig={orig} />; break;
    case 'group': body = <SpecForm fields={f.group} obj={obj} orig={orig} ctx={{ coordNames: [...coordNames] }} />; break;
    case 'param':
      body = <SpecForm fields={f.parameter} obj={obj} orig={orig} ctx={{
        skip: skipAxes, skipQuiet: skipAxes,
        onUri: v => { if (n.t === 'param' && v !== n.uri) { S.sel = { t: 'param', uri: v }; S.expanded.add(v); touch(); } },
      }} />;
      break;
    case 'plist': body = <EntriesTable lref={refFor(n.uri, null, n.list, S.flag && S.flag.entry)} />; break;
    case 'axis': body = <AxisView n={n} obj={obj} orig={orig} />; break;
  }
  return (
    <Box ref={el} className="dp-scroll" style={{ flex: 1 }} p="md">
      <Stack gap="md" key={S.rev}>
        <Group justify="space-between" align="flex-start">
          <Box>
            <Title order={3}>{title}</Title>
            {sub ? <Text size="sm" c="dimmed">{sub}</Text> : null}
          </Box>
          <Actions n={n} />
        </Group>
        {body}
      </Stack>
    </Box>
  );
}
