/* The form of the selected node, on the right of the tree. */
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { Alert, Badge, Box, Button, Group, NativeSelect, Stack, Text, Title } from '@mantine/core';
import { IconCopy, IconTrash } from '@tabler/icons-react';
import { useStore } from '../lib/nav';
import { axisKinds, type SpecNode } from '../lib/spec';
import { isObj, type Obj } from '../lib/util';
import { copyNode, deleteNode, ensureSel, listCount, nodeObj, S, touch, view } from './state';
import { FlaggedKey, SpecForm, StringsEditor, useEdit } from './widgets';
import { EntriesTable, refFor } from './entries';

export function titleOf(n: SpecNode): [string, string] {
  switch (n.t) {
    case 'spec': return ['Top-level questions', ''];
    case 'plan': return ['Plan field ' + n.key, 'What a document settles once for all its values.'];
    case 'works': return ['Works', 'Other works a document presents beside itself.'];
    case 'group': return ['Group ' + n.name, 'Coordinates a document prints together.'];
    case 'param': return ['Field ' + n.uri, ''];
    case 'plist': return ['Field ' + n.uri + ' · ' + (n.list === 'beside' ? 'beside list' : 'list'), 'Fixed entries; edits are written with the next save.'];
    case 'axis': return ['Coordinate ' + n.name + ' of field ' + n.uri, ''];
  }
}

function Actions({ n }: { n: SpecNode }) {
  const busy = S.busy;
  if (n.t === 'param') return (
    <Group gap="xs">
      <Button variant="default" disabled={busy} leftSection={<IconCopy size={16} />} onClick={() => copyNode('field', n)}>Copy as new field…</Button>
      <Button variant="light" color="red" disabled={busy} leftSection={<IconTrash size={16} />} onClick={() => deleteNode('field', n)}>Delete field</Button>
    </Group>
  );
  if (n.t === 'axis') return (
    <Group gap="xs">
      <Button variant="default" disabled={busy} leftSection={<IconCopy size={16} />} onClick={() => copyNode('coordinate', n)}>Copy as new coordinate…</Button>
      <Button variant="light" color="red" disabled={busy} leftSection={<IconTrash size={16} />} onClick={() => deleteNode('coordinate', n)}>Delete coordinate</Button>
    </Group>
  );
  if (n.t === 'plan') return <Button variant="light" color="red" disabled={busy} leftSection={<IconTrash size={16} />} onClick={() => deleteNode('plan_field', n)}>Remove plan field</Button>;
  if (n.t === 'works') return <Button variant="light" color="red" disabled={busy} leftSection={<IconTrash size={16} />} onClick={() => deleteNode('works', n)}>Remove works</Button>;
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
      <Section>What the coordinate reads</Section>
      {kinds.length !== 1 ? (
        <Alert color="yellow">{kinds.length ? 'More than one of vocabulary, type, enum, dynamic is set; the loader wants exactly one.' : 'None of vocabulary, type, enum, dynamic is set; the loader wants exactly one.'}</Alert>
      ) : null}
      {kinds.map(k => {
        if (k === 'vocabulary') return (
          <Stack key={k} gap="xs">
            <Group gap="xs"><Badge variant="light">a list of entries</Badge><Text size="sm">{listCount(obj.vocabulary) + ' entries'}</Text></Group>
            <EntriesTable lref={refFor(n.uri, n.name, 'vocabulary', mark)} />
          </Stack>
        );
        if (k === 'type') return (
          <FlaggedKey key={k} k="type">
            <Group gap="xs"><Badge variant="light">a free value</Badge><Text fw={600}>type</Text><TypeSelect obj={obj} /></Group>
          </FlaggedKey>
        );
        if (k === 'enum') return (
          <FlaggedKey key={k} k="enum">
            <Stack gap="xs"><Badge variant="light" w="fit-content">a list of strings</Badge><StringsEditor obj={obj} k="enum" keep /></Stack>
          </FlaggedKey>
        );
        return (
          <FlaggedKey key={k} k="dynamic">
            <Group gap="xs"><Badge variant="light">closed per document</Badge><Text size="sm">The profile closes the list of this coordinate for each document.</Text></Group>
          </FlaggedKey>
        );
      })}
      {isObj(obj.beside) ? (
        <>
          <Section>Beside list</Section>
          <EntriesTable lref={refFor(n.uri, n.name, 'beside', mark)} />
        </>
      ) : null}
      <Section>The other keys of the coordinate</Section>
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
