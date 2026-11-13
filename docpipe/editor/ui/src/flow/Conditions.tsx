/* A condition as rows of [what][property][comparison][value][not], joined by "and" or "or", read back as a sentence.
   Every change writes into the condition object the step holds and calls changed(). */
import { ActionIcon, Autocomplete, Box, Button, Checkbox, Group, NativeSelect, Paper, Stack, Text, Tooltip } from '@mantine/core';
import { IconMinus, IconPlus } from '@tabler/icons-react';
import { TextBox, NumberBox } from '../components/Inputs';
import { t, tr, useLang } from '../lib/i18n';
import { choiceWord, firstProp, freshRow, normRow, opWord, propOf, rowsOf, sentence, subjectOf, type Cond, type Row, type Subject } from './model';

export function CondEditor({ subjects, get, set, only, vars }: {
  subjects: Subject[]; get: () => Cond | null; set: (c: Cond | null) => void; only?: string | null;
  /* the variables there at the step, which a row about a variable offers */
  vars?: string[];
}) {
  useLang();
  const c = get();
  if (!c) {
    return <Box><Button size="xs" variant="light" leftSection={<IconPlus size={14} />}
      onClick={() => set({ all: [freshRow(subjects, only || 'coordinate')] })}>{t('condition')}</Button></Box>;
  }
  const joiner = 'all' in c ? 'all' : 'any';
  const rows = rowsOf(c);
  const changed = () => set(c);
  return (
    <Paper withBorder p="xs" radius="md">
      <Stack gap={6}>
        <Group gap="xs" justify="space-between">
          <NativeSelect size="xs" value={joiner} aria-label={t('how the rows join')}
            data={[{ value: 'all', label: t('all rows are met (and)') }, { value: 'any', label: t('one row is met (or)') }]}
            onChange={e => { const o = { [e.currentTarget.value]: rows } as Cond; set(o); }} />
          <Button size="compact-xs" variant="subtle" color="red" onClick={() => set(null)}>{t('remove condition')}</Button>
        </Group>
        {rows.map((r, i) => (
          <RowEditor key={i} subjects={subjects} r={r} only={only} changed={changed} vars={vars}
            remove={() => { rows.splice(i, 1); if (!rows.length) set(null); else set(c); }} />
        ))}
        <Group gap="xs">
          <Button size="compact-xs" variant="light" leftSection={<IconPlus size={12} />}
            onClick={() => { rows.push(freshRow(subjects, only || 'coordinate')); set(c); }}>{t('row')}</Button>
        </Group>
        <Text size="sm" c="dimmed" fs="italic">{sentence(subjects, c)}</Text>
      </Stack>
    </Paper>
  );
}

function RowEditor({ subjects, r, only, changed, remove, vars }: {
  subjects: Subject[]; r: Row; only?: string | null; changed: () => void; remove: () => void; vars?: string[];
}) {
  useLang();
  const offered = subjects.filter(s => (only ? s.name === only : s.name !== 'line'));
  const s = subjectOf(subjects, r.of);
  const p = propOf(subjects, r);
  if (s && s.variable) return <VarRow subjects={offered} r={r} changed={changed} remove={remove} vars={vars || []} />;
  return (
    <Group gap={6} wrap="wrap" align="center">
      <NativeSelect size="xs" value={r.of} aria-label={t('what')} data={offered.map(x => ({ value: x.name, label: tr(x.label) }))}
        onChange={e => { r.of = e.currentTarget.value; r.is = firstProp(subjects, r.of); delete r.op; delete r.value; normRow(subjects, r); changed(); }} />
      <NativeSelect size="xs" value={r.is} aria-label={t('property')} data={(s ? s.props : []).map(x => ({ value: x.name, label: tr(x.label) }))}
        onChange={e => { r.is = e.currentTarget.value; delete r.op; delete r.value; normRow(subjects, r); changed(); }} />
      {p && p.kind !== 'yes' && (
        <NativeSelect size="xs" value={r.op || p.ops[0]} aria-label={t('comparison')} data={p.ops.map(o => ({ value: o, label: opWord(o) }))}
          onChange={e => { r.op = e.currentTarget.value; if (r.op === 'empty') delete r.value; changed(); }} />
      )}
      {p && p.kind !== 'yes' && r.op !== 'empty' && (p.kind === 'choice'
        ? <Group gap={8}>{(p.choices || []).map(ch => (
            <Checkbox key={ch} size="xs" label={choiceWord(p, ch)} checked={Array.isArray(r.value) && r.value.includes(ch)}
              onChange={e => {
                const v = new Set(Array.isArray(r.value) ? (r.value as string[]) : []);
                if (e.currentTarget.checked) v.add(ch); else v.delete(ch);
                r.value = (p.choices || []).filter(x => v.has(x)); changed();
              }} />))}</Group>
        : p.kind === 'number'
          ? <NumberBox w={90} value={r.value == null ? '' : String(r.value)} onText={() => {}} aria-label={t('value')}
              onCommit={v => { if (v === (r.value == null ? '' : String(r.value))) return; r.value = v === '' ? undefined : Number(v); changed(); }} />
          : <TextBox w={160} value={r.value == null ? '' : String(r.value)} onText={() => {}} aria-label={t('value')}
              onCommit={v => { if (v === (r.value == null ? '' : String(r.value))) return; r.value = v; changed(); }} />)}
      <Checkbox size="xs" label={t('not')} title={t('the row is met when its statement is false')} checked={!!r.not}
        onChange={e => { if (e.currentTarget.checked) r.not = true; else delete r.not; changed(); }} />
      <Tooltip label={t('Remove the row')}><ActionIcon size="sm" variant="subtle" color="red" onClick={remove} aria-label={t('Remove the row')}><IconMinus size={14} /></ActionIcon></Tooltip>
    </Group>
  );
}

/* a row about any variable (owner decision 2026-11-12): its path, such as "answer.finds" or "item.kind", a comparison or
   none ("is there"), and a value: a number for less and more, several values for "is one of", else a text */
function VarRow({ subjects, r, changed, remove, vars }: {
  subjects: Subject[]; r: Row; changed: () => void; remove: () => void; vars: string[];
}) {
  useLang();
  const s = subjectOf(subjects, r.of);
  const ops = (s && s.ops) || [];
  const numeric = ['less', 'more', 'at_least', 'at_most'].includes(r.op || '');
  const shown = r.value == null ? '' : Array.isArray(r.value) ? r.value.join(', ') : String(r.value);
  const commit = (v: string) => {
    if (v === shown) return;
    if (v === '') delete r.value;
    else if (r.op === 'one_of') r.value = v.split(',').map(x => x.trim()).filter(Boolean);
    else if (numeric || (/^-?\d+(\.\d+)?$/.test(v.trim()) && r.op !== 'contains')) r.value = Number(v);
    else r.value = v;
    changed();
  };
  return (
    <Group gap={6} wrap="wrap" align="center">
      <NativeSelect size="xs" value={r.of} aria-label={t('what')} data={subjects.map(x => ({ value: x.name, label: tr(x.label) }))}
        onChange={e => { r.of = e.currentTarget.value; r.is = firstProp(subjects, r.of); delete r.op; delete r.value; normRow(subjects, r); changed(); }} />
      <Autocomplete size="xs" w={170} value={r.is} data={vars} aria-label={t('variable')} placeholder={t('variable, e.g. answer.finds')}
        onChange={v => { r.is = v; changed(); }} />
      <NativeSelect size="xs" value={r.op || ''} aria-label={t('comparison')}
        data={[{ value: '', label: t('is there') }, ...ops.map(o => ({ value: o, label: opWord(o) }))]}
        onChange={e => { const v = e.currentTarget.value; if (v) r.op = v; else { delete r.op; delete r.value; } if (r.op === 'empty') delete r.value; changed(); }} />
      {r.op && r.op !== 'empty' && (numeric
        ? <NumberBox w={90} value={shown} onText={() => {}} aria-label={t('value')} onCommit={commit} />
        : <TextBox w={160} value={shown} onText={() => {}} aria-label={t('value')} onCommit={commit}
            placeholder={r.op === 'one_of' ? t('values, separated by commas') : undefined} />)}
      <Checkbox size="xs" label={t('not')} title={t('the row is met when its statement is false')} checked={!!r.not}
        onChange={e => { if (e.currentTarget.checked) r.not = true; else delete r.not; changed(); }} />
      <Tooltip label={t('Remove the row')}><ActionIcon size="sm" variant="subtle" color="red" onClick={remove} aria-label={t('Remove the row')}><IconMinus size={14} /></ActionIcon></Tooltip>
    </Group>
  );
}
