/* A JSON value as a form, nothing typed as JSON. forms.js turns the value into a state and back (lib/forms.ts); this
   draws a state and hands every edit to forms.js, which keeps the order of the keys and every key no field shows. */
import { useMemo, useReducer, useRef, type ReactNode } from 'react';
import { ActionIcon, Box, Button, Code, Group, NativeSelect, Stack, Table, Text, Tooltip } from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconMinus, IconPlus } from '@tabler/icons-react';
import { DF, type FormState, type Kind, type Path } from '../lib/forms';
import { AreaBox, NumberBox, TextBox } from './Inputs';

export interface FormApi {
  edit(path: Path, text: string | boolean): void;
  add(path: Path): void;
  remove(path: Path, i: number): void;
  move(path: Path, i: number, d: number): void;
  addPair(path: Path): void;
  removePair(path: Path, i: number): void;
}

/* The state of one value, kept for as long as `deps` stay the same; every edit calls emit with the value forms.js gives
   back (undefined where nothing is left) and draws again. */
export function useFormState(spec: Kind, value: unknown, deps: unknown[], emit: (v: any) => void) {
  const specSig = JSON.stringify(spec);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const root = useMemo(() => DF().stateOf(spec, value), [specSig, ...deps]);
  const [, redraw] = useReducer((x: number) => x + 1, 0);
  const emitRef = useRef(emit);
  emitRef.current = emit;
  const api: FormApi = useMemo(() => {
    const F = DF();
    const after = () => { emitRef.current(F.valueOf(root)); redraw(); };
    return {
      edit: (p, t) => { F.edit(root, p, t); after(); },
      add: p => { F.addRow(root, p); after(); },
      remove: (p, i) => { F.removeRow(root, p, i); after(); },
      move: (p, i, d) => { F.moveRow(root, p, i, d); after(); },
      addPair: p => { F.addPair(root, p); after(); },
      removePair: (p, i) => { F.removePair(root, p, i); after(); },
    };
  }, [root]);
  return { root, api };
}

/* obj[key] as a form: a key with no value left is removed */
export function useFormField(obj: Record<string, any>, key: string, spec: Kind, onChange: () => void, deps: unknown[] = []) {
  return useFormState(spec, obj[key], [obj, key, ...deps], v => {
    if (v === undefined) delete obj[key]; else obj[key] = v;
    onChange();
  });
}

const Kept = ({ children, title }: { children: ReactNode; title?: string }) =>
  <Text size="sm" c="dimmed" fs="italic" title={title}>{children}</Text>;

export function FormNode({ spec, st, api, path, lists }: {
  spec: Kind; st: FormState; api: FormApi; path: Path; lists?: Record<string, string[]>;
}): ReactNode {
  const F = DF();
  if (st.odd) {
    return <Kept title="This value is not in the shape of the form; it is kept as it is.">
      kept as it is: <Code>{typeof st.raw === 'string' ? st.raw : JSON.stringify(st.raw)}</Code></Kept>;
  }
  switch (spec.k) {
    case 'text': {
      if (spec.choices) {
        const opts = spec.choices.slice();
        if (st.v != null && st.v !== '' && !opts.includes(st.v)) opts.push(st.v);
        return <NativeSelect value={st.v == null ? '' : String(st.v)} onChange={e => api.edit(path, e.currentTarget.value)}
          data={[{ value: '', label: '(not set)' }, ...opts.map(o => ({ value: String(o), label: String(o) }))]} />;
      }
      if (spec.area) return <AreaBox value={F.textOf(st)} onText={t => api.edit(path, t)} mono />;
      return <TextBox value={F.textOf(st)} onText={t => api.edit(path, t)} list={spec.list && lists ? lists[spec.list] : undefined} />;
    }
    case 'number':
      return <NumberBox value={F.textOf(st)} onText={t => api.edit(path, t)} />;
    case 'bounds':
      return (
        <Group gap="md">
          <Group gap={6}><Text size="sm">from</Text>
            <NumberBox step={1} placeholder="no bound" value={st.lo == null ? '' : String(st.lo)} onText={t => api.edit(path.concat(['lo']), t)} /></Group>
          <Group gap={6}><Text size="sm">to</Text>
            <NumberBox step={1} placeholder="no bound" value={st.hi == null ? '' : String(st.hi)} onText={t => api.edit(path.concat(['hi']), t)} /></Group>
        </Group>
      );
    case 'record': {
      const fields = spec.fields || [];
      const known = new Set(fields.map(x => x.key));
      const grey = (st.order as string[]).filter(k => !known.has(k));
      return (
        <Stack gap="xs" className="dp-record">
          {fields.map(fld => (
            <Box key={fld.key}>
              <Text size="sm" fw={600} title={fld.help || ''}><Code>{fld.key}</Code></Text>
              {fld.help ? <Text size="xs" c="dimmed">{fld.help}</Text> : null}
              <FormNode spec={fld.kind} st={st.cells[fld.key]} api={api} path={path.concat([fld.key])} lists={lists} />
            </Box>
          ))}
          {grey.map(k => <Kept key={k}><Code>{k}</Code> kept untouched: the writer does not name this key.</Kept>)}
        </Stack>
      );
    }
    case 'rows': {
      const item = spec.item!;
      const rows = st.rows as FormState[];
      const flat = item.k === 'record' && (item.fields || []).every(x => x.kind.k === 'text' || x.kind.k === 'number');
      const btns = (i: number) => (
        <Group gap={2} wrap="nowrap">
          <Tooltip label="Earlier"><ActionIcon variant="subtle" disabled={i === 0} onClick={() => api.move(path, i, -1)} aria-label="Earlier"><IconArrowUp size={16} /></ActionIcon></Tooltip>
          <Tooltip label="Later"><ActionIcon variant="subtle" disabled={i === rows.length - 1} onClick={() => api.move(path, i, 1)} aria-label="Later"><IconArrowDown size={16} /></ActionIcon></Tooltip>
          <Tooltip label="Remove"><ActionIcon variant="subtle" color="red" onClick={() => api.remove(path, i)} aria-label="Remove"><IconMinus size={16} /></ActionIcon></Tooltip>
        </Group>
      );
      const add = <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => api.add(path)}>Add</Button>;
      if (flat) {
        const fields = item.fields || [];
        const known = new Set(fields.map(x => x.key));
        const kept = (r: FormState): string[] => r.odd ? [] : (r.order as string[]).filter(k => !known.has(k));
        return (
          <Stack gap="xs">
            {rows.length ? (
              <Table.ScrollContainer minWidth={300}>
                <Table withTableBorder withColumnBorders className="dp-formtable">
                  <Table.Thead><Table.Tr>{fields.map(x => <Table.Th key={x.key} title={x.help || ''}>{x.key}</Table.Th>)}<Table.Th /></Table.Tr></Table.Thead>
                  <Table.Tbody>
                    {rows.map((r, i) => r.odd
                      ? <Table.Tr key={i}><Table.Td colSpan={fields.length + 1}><FormNode spec={item} st={r} api={api} path={path.concat([i])} lists={lists} /></Table.Td></Table.Tr>
                      : <Table.Tr key={i}>
                          {fields.map(x => <Table.Td key={x.key}><FormNode spec={x.kind} st={r.cells[x.key]} api={api} path={path.concat([i, x.key])} lists={lists} /></Table.Td>)}
                          <Table.Td>{btns(i)}{kept(r).length ? <Kept title={'kept untouched: ' + kept(r).join(', ')}>+{kept(r).length} kept</Kept> : null}</Table.Td>
                        </Table.Tr>)}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            ) : null}
            <Box>{add}</Box>
          </Stack>
        );
      }
      return (
        <Stack gap="xs">
          {rows.map((r, i) => (
            <Group key={i} align="flex-start" wrap="nowrap" className="dp-formrow">
              <Box style={{ flex: 1 }}><FormNode spec={item} st={r} api={api} path={path.concat([i])} lists={lists} /></Box>
              {btns(i)}
            </Group>
          ))}
          <Box>{add}</Box>
        </Stack>
      );
    }
    case 'map': {
      const pairs = st.pairs as { key: string; state: FormState }[];
      return (
        <Stack gap="xs">
          {pairs.length ? (
            <Table withTableBorder className="dp-formtable">
              <Table.Tbody>
                {pairs.map((p, i) => (
                  <Table.Tr key={i}>
                    <Table.Td w="30%"><TextBox value={p.key} placeholder="name" onText={t => api.edit(path.concat([i, 'key']), t)} /></Table.Td>
                    <Table.Td><FormNode spec={spec.value!} st={p.state} api={api} path={path.concat([i, 'value'])} lists={lists} /></Table.Td>
                    <Table.Td w={40}><Tooltip label="Remove"><ActionIcon variant="subtle" color="red" onClick={() => api.removePair(path, i)} aria-label="Remove"><IconMinus size={16} /></ActionIcon></Tooltip></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          ) : null}
          <Box><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => api.addPair(path)}>Add</Button></Box>
        </Stack>
      );
    }
  }
  return <Text c="red">no form for {spec.k}</Text>;
}
