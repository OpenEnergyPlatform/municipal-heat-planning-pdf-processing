/* A condition as rows of [what][property][comparison][value][not], joined by "and" or "or", read back as a sentence.
   Every change writes into the condition object the step holds and calls changed(). */
import { ActionIcon, Box, Button, Checkbox, Group, NativeSelect, Paper, Stack, Text, Tooltip } from '@mantine/core';
import { IconMinus, IconPlus } from '@tabler/icons-react';
import { TextBox, NumberBox } from '../components/Inputs';
import { firstProp, freshRow, normRow, OPS, propOf, rowsOf, sentence, subjectOf, type Cond, type Row, type Subject } from './model';

export function CondEditor({ subjects, get, set, only }: {
  subjects: Subject[]; get: () => Cond | null; set: (c: Cond | null) => void; only?: string | null;
}) {
  const c = get();
  if (!c) {
    return <Box><Button size="xs" variant="light" leftSection={<IconPlus size={14} />}
      onClick={() => set({ all: [freshRow(subjects, only || 'coordinate')] })}>condition</Button></Box>;
  }
  const joiner = 'all' in c ? 'all' : 'any';
  const rows = rowsOf(c);
  const changed = () => set(c);
  return (
    <Paper withBorder p="xs" radius="md">
      <Stack gap={6}>
        <Group gap="xs" justify="space-between">
          <NativeSelect size="xs" value={joiner} aria-label="how the rows join"
            data={[{ value: 'all', label: 'all rows hold (and)' }, { value: 'any', label: 'one row holds (or)' }]}
            onChange={e => { const o = { [e.currentTarget.value]: rows } as Cond; set(o); }} />
          <Button size="compact-xs" variant="subtle" color="red" onClick={() => set(null)}>remove condition</Button>
        </Group>
        {rows.map((r, i) => (
          <RowEditor key={i} subjects={subjects} r={r} only={only} changed={changed}
            remove={() => { rows.splice(i, 1); if (!rows.length) set(null); else set(c); }} />
        ))}
        <Group gap="xs">
          <Button size="compact-xs" variant="light" leftSection={<IconPlus size={12} />}
            onClick={() => { rows.push(freshRow(subjects, only || 'coordinate')); set(c); }}>row</Button>
        </Group>
        <Text size="sm" c="dimmed" fs="italic">{sentence(subjects, c)}</Text>
      </Stack>
    </Paper>
  );
}

function RowEditor({ subjects, r, only, changed, remove }: {
  subjects: Subject[]; r: Row; only?: string | null; changed: () => void; remove: () => void;
}) {
  const offered = subjects.filter(s => (only ? s.name === only : s.name !== 'line'));
  const s = subjectOf(subjects, r.of);
  const p = propOf(subjects, r);
  return (
    <Group gap={6} wrap="wrap" align="center">
      <NativeSelect size="xs" value={r.of} aria-label="what" data={offered.map(x => ({ value: x.name, label: x.label }))}
        onChange={e => { r.of = e.currentTarget.value; r.is = firstProp(subjects, r.of); delete r.op; delete r.value; normRow(subjects, r); changed(); }} />
      <NativeSelect size="xs" value={r.is} aria-label="property" data={(s ? s.props : []).map(x => ({ value: x.name, label: x.label }))}
        onChange={e => { r.is = e.currentTarget.value; delete r.op; delete r.value; normRow(subjects, r); changed(); }} />
      {p && p.kind !== 'yes' && (
        <NativeSelect size="xs" value={r.op || p.ops[0]} aria-label="comparison" data={p.ops.map(o => ({ value: o, label: OPS[o] || o }))}
          onChange={e => { r.op = e.currentTarget.value; if (r.op === 'empty') delete r.value; changed(); }} />
      )}
      {p && p.kind !== 'yes' && r.op !== 'empty' && (p.kind === 'choice'
        ? <Group gap={8}>{(p.choices || []).map(ch => (
            <Checkbox key={ch} size="xs" label={ch} checked={Array.isArray(r.value) && r.value.includes(ch)}
              onChange={e => {
                const v = new Set(Array.isArray(r.value) ? (r.value as string[]) : []);
                if (e.currentTarget.checked) v.add(ch); else v.delete(ch);
                r.value = (p.choices || []).filter(x => v.has(x)); changed();
              }} />))}</Group>
        : p.kind === 'number'
          ? <NumberBox w={90} value={r.value == null ? '' : String(r.value)} onText={() => {}} aria-label="value"
              onCommit={t => { if (t === (r.value == null ? '' : String(r.value))) return; r.value = t === '' ? undefined : Number(t); changed(); }} />
          : <TextBox w={160} value={r.value == null ? '' : String(r.value)} onText={() => {}} aria-label="value"
              onCommit={t => { if (t === (r.value == null ? '' : String(r.value))) return; r.value = t; changed(); }} />)}
      <Checkbox size="xs" label="not" title="the row holds where its sentence does not" checked={!!r.not}
        onChange={e => { if (e.currentTarget.checked) r.not = true; else delete r.not; changed(); }} />
      <Tooltip label="Remove the row"><ActionIcon size="sm" variant="subtle" color="red" onClick={remove} aria-label="Remove the row"><IconMinus size={14} /></ActionIcon></Tooltip>
    </Group>
  );
}
