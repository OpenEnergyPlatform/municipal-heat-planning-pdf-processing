/* What the middle of the Spec tab shows besides a field's drawing and a shared dimension's dictionary: the order of the
   questions with what is read otherwise than the rest, the fields of the whole document and the works, the value types,
   and the questions and note of the spec. On the left, the choice of what the middle shows. */
import { ActionIcon, Anchor, Badge, Box, Button, Card, Checkbox, Code, Group, Menu, NavLink, ScrollArea, Stack, Table, Text, Title, Tooltip } from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconPlus } from '@tabler/icons-react';
import { t, tn } from '../lib/i18n';
import { useStore } from '../lib/nav';
import { isObj, type Obj } from '../lib/util';
import { askersOf, fieldsOf, orderOf, sharedOf, specialsOf, usersOf, type Special } from './model';
import { named, nameOf } from './names';
import {
  addField, addOwnPlanField, addPlanField, addValueType, addWorks, orderSet, S, select, show, specialSet, view,
} from './state';

const fieldName = (p: Obj) => p.label || p.uri;

/* ---------- the left column ---------- */

export function Nav() {
  useStore(view);
  const v = S.view;
  const fields = fieldsOf(S.data);
  const shared = Object.keys(sharedOf(S.data));
  const plan = isObj(S.data.plan_fields) ? Object.keys(S.data.plan_fields).length : 0;
  const own = isObj(S.data.value_types) ? Object.keys(S.data.value_types).length : 0;
  return (
    <ScrollArea className="sp-nav" type="auto">
      <Stack gap={2} p="xs">
        <Group justify="space-between" px={6} mt={4}>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">{t('Fields')}</Text>
          <Menu withinPortal position="bottom-start">
            <Menu.Target><Tooltip label={t('Add a field')}><ActionIcon size="sm" variant="subtle" aria-label={t('Add a field')}><IconPlus size={14} /></ActionIcon></Tooltip></Menu.Target>
            <Menu.Dropdown>
              <Menu.Label>{t('A field whose value is…')}</Menu.Label>
              {(S.library.types || []).map(x => <Menu.Item key={x.name} onClick={() => void addField(x.name)}>{x.name}</Menu.Item>)}
            </Menu.Dropdown>
          </Menu>
        </Group>
        {fields.map(p => (
          <NavLink key={p.uri} active={v.t === 'field' && v.uri === p.uri} label={fieldName(p)} description={p.uri}
            rightSection={<Badge size="xs" variant="light" tt="none">{String(p.value_type || 'float')}</Badge>}
            onClick={() => show({ t: 'field', uri: p.uri })} />
        ))}
        {shared.length ? <Text size="xs" fw={700} c="dimmed" tt="uppercase" px={6} mt="sm">{t('Shared dimensions')}</Text> : null}
        {shared.map(name => (
          <NavLink key={name} active={v.t === 'shared' && v.name === name} label={nameOf(name)}
            description={tn(usersOf(S.data, name).length, 'asked by {n} field', 'asked by {n} fields')}
            onClick={() => show({ t: 'shared', name })} />
        ))}
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" px={6} mt="sm">{t('The spec as a whole')}</Text>
        <NavLink active={v.t === 'order'} label={t('Order of the questions')} description={tn(orderOf(S.data).length, '{n} dimension', '{n} dimensions')} onClick={() => show({ t: 'order' })} />
        <NavLink active={v.t === 'plan'} label={t('Fields of the whole document')} description={tn(plan, '{n} field', '{n} fields') + (isObj(S.data.works) ? ' · ' + t('works') : '')} onClick={() => show({ t: 'plan' })} />
        <NavLink active={v.t === 'types'} label={t('Value types')} description={tn(own, '{n} of its own', '{n} of its own')} onClick={() => show({ t: 'types' })} />
        <NavLink active={v.t === 'spec'} label={t('Questions and note of the spec')} onClick={() => show({ t: 'spec' })} />
      </Stack>
    </ScrollArea>
  );
}

/* ---------- the order of the questions ---------- */

const SPECIALS = (): [Special, string, string][] => [
  ['own_passage', t('only where the value stands'), t('Asked again with the lines around the value, never searched for elsewhere in the plan.')],
  ['own_value', t('once with the number'), t('Read once with the value, such as "ca."; never asked again.')],
  ['frame', t('frame of the plan'), t('The pair that the base year and the target year of the plan date a value by.')],
];

export function OrderPage() {
  useStore(view);
  const order = orderOf(S.data);
  const about = ((S.form.coordinates || [])[0] || {}).about || '';
  const move = (i: number, by: number) => {
    const next = order.slice();
    const [x] = next.splice(i, 1);
    next.splice(i + by, 0, x);
    orderSet(next);
  };
  return (
    <Box className="dp-scroll sp-center-page" p="md">
      <Stack gap="md">
        <Title order={3}>{t('Order of the questions')}</Title>
        {about ? <Text size="sm">{about}</Text> : null}
        {!order.length ? <Text size="sm" c="dimmed">{t('The spec names no order of the questions.')}</Text> : (
          <Table striped withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={70}>{t('Order')}</Table.Th>
                <Table.Th>{t('Dimension')}</Table.Th>
                <Table.Th>{t('Asked by')}</Table.Th>
                {SPECIALS().map(([k, label, help]) => <Table.Th key={k}><Tooltip label={help} multiline w={280}><span>{label}</span></Tooltip></Table.Th>)}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {order.map((name, i) => {
                const marks = specialsOf(S.data, name);
                const askers = name === 'unit' ? fieldsOf(S.data).filter(p => isObj(p.units_accepted)).map(p => p.uri) : askersOf(S.data, name);
                return (
                  <Table.Tr key={name}>
                    <Table.Td>
                      <Group gap={2} wrap="nowrap">
                        <ActionIcon size="sm" variant="subtle" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t('Earlier')}><IconArrowUp size={14} /></ActionIcon>
                        <ActionIcon size="sm" variant="subtle" disabled={i === order.length - 1} onClick={() => move(i, 1)} aria-label={t('Later')}><IconArrowDown size={14} /></ActionIcon>
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Tooltip label={named(name).about} disabled={!named(name).about} multiline w={320}>
                        <Group gap={6} wrap="nowrap" style={{ whiteSpace: 'nowrap' }}><Text size="sm" fw={600}>{nameOf(name)}</Text><Code>{name}</Code></Group>
                      </Tooltip>
                    </Table.Td>
                    <Table.Td><Text size="xs" c="dimmed">{tn(askers.length, '{n} field', '{n} fields')}</Text></Table.Td>
                    {SPECIALS().map(([k]) => (
                      <Table.Td key={k}><Checkbox checked={marks.includes(k)} onChange={e => specialSet(name, k, e.currentTarget.checked)} aria-label={k} /></Table.Td>
                    ))}
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        )}
        <Text size="sm" c="dimmed">{t('"Only where the value stands" and "once with the number" exclude each other: marking one takes the other away.')}</Text>
      </Stack>
    </Box>
  );
}

/* ---------- the fields of the whole document, the value types, the questions of the spec ---------- */

export function PlanPage() {
  useStore(view);
  const fields = isObj(S.data.plan_fields) ? S.data.plan_fields : {};
  return (
    <Box className="dp-scroll sp-center-page" p="md">
      <Stack gap="md">
        <Title order={3}>{t('Fields of the whole document')}</Title>
        <Text size="sm">{t('A field of the whole document holds for all values of a document, such as its base year or its municipality. It is asked once per document.')}</Text>
        {Object.entries(fields).map(([key, f]) => (
          <Card key={key} withBorder className={'sp-card' + (S.sel.t === 'plan' && S.sel.key === key ? ' is-sel' : '')} onClick={() => select({ t: 'plan', key })}>
            <Group gap="sm"><Text fw={650}>{(f as Obj).name || key}</Text><Code>{key}</Code></Group>
            <Text size="sm" c="dimmed" lineClamp={2}>{(f as Obj).means || ''}</Text>
          </Card>
        ))}
        <Group gap="xs">
          <Button variant="light" size="xs" leftSection={<IconPlus size={14} />} onClick={() => void addOwnPlanField('settings')}>{t('Field of the whole document: settings')}</Button>
          <Button variant="light" size="xs" leftSection={<IconPlus size={14} />} onClick={() => void addOwnPlanField('year')}>{t('Field of the whole document: a year')}</Button>
          {!isObj(fields.settings) ? <Button variant="subtle" size="xs" onClick={() => addPlanField('settings')}>{t('Add the settings')}</Button> : null}
        </Group>
        <Title order={4} mt="md">{t('Works')}</Title>
        {isObj(S.data.works) ? (
          <Card withBorder className={'sp-card' + (S.sel.t === 'works' ? ' is-sel' : '')} onClick={() => select({ t: 'works' })}>
            <Text fw={650}>{S.data.works.name || t('Works')}</Text>
            <Text size="sm" c="dimmed" lineClamp={2}>{S.data.works.means || ''}</Text>
          </Card>
        ) : <Button variant="light" size="xs" w="fit-content" leftSection={<IconPlus size={14} />} onClick={addWorks}>{t('Add works')}</Button>}
      </Stack>
    </Box>
  );
}

export function TypesPage() {
  useStore(view);
  return (
    <Box className="dp-scroll sp-center-page" p="md">
      <Stack gap="md">
        <Title order={3}>{t('Value types')}</Title>
        <Text size="sm">{t('A value type says what a value of a field is: how its answer is given, whether a number has units and is converted, and how the answer is found in its quote.')}</Text>
        {(S.library.types || []).map(x => (
          <Card key={x.name} withBorder className={'sp-card' + (S.sel.t === 'vtype' && S.sel.name === x.name ? ' is-sel' : '')} onClick={() => select({ t: 'vtype', name: x.name })}>
            <Group gap="sm"><Code>{x.name}</Code>{x.builtin ? <Badge size="xs" variant="light" color="gray" tt="none">{t('built in')}</Badge> : null}</Group>
            <Text size="xs" c="dimmed">{Object.entries(x.settings || {}).map(([k, val]) => `${k}: ${String(val)}`).join(' · ')}</Text>
          </Card>
        ))}
        <Button variant="light" size="xs" w="fit-content" leftSection={<IconPlus size={14} />} onClick={() => void addValueType()}>{t('A value type of its own')}</Button>
      </Stack>
    </Box>
  );
}

export function SpecPage() {
  useStore(view);
  const note = Array.isArray(S.data._comment) ? S.data._comment : [];
  return (
    <Box className="dp-scroll sp-center-page" p="md">
      <Stack gap="md">
        <Title order={3}>{t('Questions and note of the spec')}</Title>
        {note.length ? <Card withBorder>{note.map((line: string, i: number) => <Text key={i} size="sm">{line || ' '}</Text>)}</Card> : null}
        {typeof S.data.parameter_question === 'string' ? <Text size="sm"><b>{t('Which field a value belongs to:')}</b> {S.data.parameter_question}</Text> : null}
        {typeof S.data.unit_question === 'string' ? <Text size="sm"><b>{t('Which unit a number is in:')}</b> {S.data.unit_question}</Text> : null}
        <Anchor component="button" type="button" size="sm" w="fit-content" onClick={() => select({ t: 'spec' })}>{t('Edit them on the right')}</Anchor>
      </Stack>
    </Box>
  );
}
