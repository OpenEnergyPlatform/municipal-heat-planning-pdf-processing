/* The inputs of the settings of a box, an arrow and the document: a field, a brick with its settings, a table of
   words. They change the drawing in place and say so through `edit`; none takes JSON. */
import { Box, Button, Code, Group, MultiSelect, NumberInput, Select, Stack, Switch, TagsInput, Text, ActionIcon, Tooltip } from '@mantine/core';
import { IconPlus, IconX } from '@tabler/icons-react';
import { TextBox } from '../components/Inputs';
import { Help } from '../components/Bits';
import { rich, t, tr } from '../lib/i18n';
import type { BrickInfo, GraphData, Obj } from './model';

export type Edit = (fn: () => void, key?: string) => void;

export interface Kit { d: GraphData; edit: Edit }

/* the fields of the harvest, grouped by what they are; the code name stands in the details only */
export function fieldOptions(d: GraphData, extra: string[] = []) {
  const groups = [
    { group: t('Fields of the harvest'), items: d.fields.filter(f => f.kind === 'field').map(f => ({ value: f.name, label: f.label })) },
    { group: t('What a number says (its dimensions)'), items: d.fields.filter(f => f.kind === 'dimension').map(f => ({ value: f.name, label: f.label })) },
    { group: t('What a reading carries of itself'), items: d.fields.filter(f => f.kind === 'reading').map(f => ({ value: f.name, label: f.label })) },
  ].filter(g => g.items.length);
  const known = new Set(d.fields.map(f => f.name));
  const more = extra.filter(x => x && !known.has(x));
  if (more.length) groups.push({ group: t('Others'), items: more.map(x => ({ value: x, label: x })) });
  return groups;
}

export function FieldSelect({ k, label, value, onChange, clearable = true, description, placeholder }: {
  k: Kit; label?: string; value: string | null | undefined; onChange: (v: string | null) => void; clearable?: boolean;
  description?: string; placeholder?: string;
}) {
  return <Select label={label} description={description} searchable clearable={clearable} placeholder={placeholder || t('Choose a field')}
    data={fieldOptions(k.d, value ? [value] : [])} value={value || null} onChange={v => onChange(v)} nothingFoundMessage={t('No field matches.')} />;
}

export function FieldsSelect({ k, label, value, onChange, description }: {
  k: Kit; label?: string; value: string[]; onChange: (v: string[]) => void; description?: string;
}) {
  return <MultiSelect label={label} description={description} searchable placeholder={t('Choose fields')} data={fieldOptions(k.d, value)} value={value}
    onChange={onChange} nothingFoundMessage={t('No field matches.')} />;
}

export function Flag({ label, help, checked, onChange }: { label: string; help?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <Switch label={label} description={help} checked={checked} onChange={e => onChange(e.currentTarget.checked)} />;
}

/* ---- bricks ---- */
export const bricksOf = (d: GraphData, kind: string) => d.bricks.filter(b => b.kind === kind);

export function BrickSelect({ k, kind, value, onChange, label, none }: {
  k: Kit; kind: string; value: string | null | undefined; onChange: (v: string | null) => void; label?: string; none?: string;
}) {
  const list = bricksOf(k.d, kind);
  const data = list.map(b => ({ value: b.name, label: tr(b.does) }));
  if (value && !list.some(b => b.name === value)) data.push({ value, label: value });
  return (
    <Select label={label} searchable clearable={!!none} placeholder={none || t('Choose a brick')} data={data} value={value || null} onChange={onChange}
      comboboxProps={{ width: 460, position: 'bottom-start' }} nothingFoundMessage={t('No brick matches.')}
      renderOption={({ option }) => (
        <Box>
          <Text size="sm">{option.label}</Text>
          <Code>{option.value}</Code>
        </Box>
      )} />
  );
}

/* a brick: its sentence, what it takes and gives, its name for those who want it */
export function BrickAbout({ brick }: { brick: BrickInfo | undefined }) {
  if (!brick) return null;
  return (
    <Stack gap={2}>
      <Text size="sm">{rich(tr(brick.does))}</Text>
      <Text size="xs" c="dimmed">{t('Takes {takes}, gives {gives}.', { takes: tr(brick.takes), gives: tr(brick.gives) })}</Text>
      <Text size="xs" c="dimmed">{t('Name in the code: {name}', { name: brick.name })}{brick.own ? ' · ' + t('only this profile has it') : ''}</Text>
    </Stack>
  );
}

/* the settings of a brick: one input for each setting it declares, and the ones the file has that it does not declare */
export function SettingsEditor({ k, brick, settings, onChange }: { k: Kit; brick: BrickInfo | undefined; settings: Obj; onChange: (next: Obj) => void }) {
  const declared = brick ? brick.settings : [];
  const names = new Set(declared.map(s => s.key));
  const put = (key: string, v: unknown, typing?: boolean) => {
    k.edit(() => {
      const next = { ...settings };
      if (v === undefined || v === '' || (Array.isArray(v) && !v.length) || (v && typeof v === 'object' && !Array.isArray(v) && !Object.keys(v as object).length)) delete next[key];
      else next[key] = v;
      onChange(next);
    }, typing ? 'setting:' + key : undefined);
  };
  return (
    <Stack gap="xs">
      {declared.map(s => (
        <Box key={s.key}>
          <SettingInput k={k} kind={s.kind} label={s.key.replace(/_/g, ' ')} help={s.help} value={settings[s.key]} onChange={(v, typing) => put(s.key, v, typing)} />
        </Box>
      ))}
      {Object.keys(settings).filter(key => !names.has(key)).map(key => (
        <Box key={key}>
          <SettingInput k={k} kind={typeof settings[key] === 'string' ? 'text' : 'labels'} label={key.replace(/_/g, ' ')} help={t('Kept as the file has it.')} value={settings[key]}
            onChange={(v, typing) => put(key, v, typing)} />
        </Box>
      ))}
    </Stack>
  );
}

function SettingInput({ k, kind, label, help, value, onChange }: {
  k: Kit; kind: string; label: string; help: string; value: any; onChange: (v: unknown, typing?: boolean) => void;
}) {
  const about = <Help text={tr(help)} size="xs" />;
  switch (kind) {
    case 'flag':
      return <Flag label={label} help={tr(help)} checked={!!value} onChange={v => onChange(v)} />;
    case 'number':
      return <NumberInput label={label} description={tr(help)} value={value ?? ''} onChange={v => onChange(v === '' ? undefined : v)} />;
    case 'texts':
      return <TagsInput label={label} description={tr(help)} value={Array.isArray(value) ? value : []} onChange={v => onChange(v)} />;
    case 'fields':
      return <FieldsSelect k={k} label={label} description={tr(help)} value={Array.isArray(value) ? value : []} onChange={v => onChange(v)} />;
    case 'rule': {
      const names = k.d.rules.map(r => r.name);
      return <Select label={label} description={tr(help)} searchable clearable data={value && !names.includes(value) ? [...names, value] : names} value={value || null}
        onChange={v => onChange(v)} />;
    }
    case 'class':
      return <TextBox label={label} description={tr(help)} mono value={value == null ? '' : String(value)} list={k.d.classes.map(c => c.curie || '').filter(Boolean)}
        onText={v => onChange(v, true)} />;
    case 'labels': case 'table': case 'prose':
      return (
        <Stack gap={4}>
          <Text size="sm" fw={500}>{label}</Text>
          {about}
          <PairsEditor value={value && typeof value === 'object' && !Array.isArray(value) ? value : {}} onChange={v => onChange(v, true)} />
        </Stack>
      );
    default:
      return <TextBox label={label} description={tr(help)} value={value == null ? '' : String(value)} onText={v => onChange(v, true)} />;
  }
}

/* words under words: a map of texts, and maps of maps; what is no text (a number, a list) stays as it is and is shown */
export function PairsEditor({ value, onChange }: { value: Obj; onChange: (next: Obj) => void }) {
  const keys = Object.keys(value);
  const rebuild = (fn: (pairs: [string, unknown][]) => [string, unknown][]) => onChange(Object.fromEntries(fn(Object.entries(value))));
  return (
    <Stack gap={4} pl="xs" style={{ borderLeft: '2px solid var(--mantine-color-default-border)' }}>
      {keys.map((key, i) => {
        const v = value[key];
        return (
          <Box key={i}>
            <Group gap={4} wrap="nowrap" align="flex-start">
              <TextBox w={130} size="xs" mono value={key} placeholder={t('word')}
                onText={nk => rebuild(p => p.map((pair, j) => (j === i ? [nk, pair[1]] : pair)))} />
              {typeof v === 'string' || v == null
                ? <TextBox style={{ flex: 1 }} size="xs" value={v == null ? '' : String(v)} onText={nv => rebuild(p => p.map((pair, j) => (j === i ? [pair[0], nv] : pair)))} />
                : typeof v === 'object' && !Array.isArray(v)
                  ? <Box style={{ flex: 1 }}><PairsEditor value={v as Obj} onChange={nv => rebuild(p => p.map((pair, j) => (j === i ? [pair[0], nv] : pair)))} /></Box>
                  : <Text size="xs" c="dimmed" style={{ flex: 1 }}>{t('Kept as the file has it: {value}', { value: JSON.stringify(v) })}</Text>}
              <Tooltip label={t('Remove')}><ActionIcon variant="subtle" color="red" size="sm" aria-label={t('Remove')} onClick={() => rebuild(p => p.filter((_, j) => j !== i))}><IconX size={14} /></ActionIcon></Tooltip>
            </Group>
          </Box>
        );
      })}
      <Box><Button size="compact-xs" variant="subtle" leftSection={<IconPlus size={12} />} onClick={() => rebuild(p => [...p, ['', '']])}>{t('Add')}</Button></Box>
    </Stack>
  );
}

/* a list of bricks of one kind, each with its settings (the bricks a box admits, the checks of a document) */
export function BrickList({ k, kind, list, onChange, label, help }: {
  k: Kit; kind: string; list: Obj[]; onChange: (next: Obj[]) => void; label: string; help?: string;
}) {
  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>{label}</Text>
      {help && <Text size="xs" c="dimmed">{help}</Text>}
      {list.map((ref, i) => (
        <Box key={i} p="xs" style={{ border: '1px solid var(--mantine-color-default-border)', borderRadius: 8 }}>
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Box style={{ flex: 1, minWidth: 0 }}>
              <BrickRefEditor k={k} kind={kind} refer={ref} onChange={next => onChange(list.map((x, j) => (j === i ? next : x)))} withGraph />
            </Box>
            <Tooltip label={t('Remove')}><ActionIcon variant="subtle" color="red" aria-label={t('Remove')} onClick={() => k.edit(() => onChange(list.filter((_, j) => j !== i)))}><IconX size={16} /></ActionIcon></Tooltip>
          </Group>
        </Box>
      ))}
      <Box><Button size="xs" variant="light" leftSection={<IconPlus size={14} />}
        onClick={() => k.edit(() => { const first = bricksOf(k.d, kind)[0]; if (first) onChange([...list, { brick: first.name }]); })}>{t('Add a brick')}</Button></Box>
    </Stack>
  );
}

/* {brick, settings, graph}: one brick of a box or of the document, with what it takes and its settings */
export function BrickRefEditor({ k, kind, refer, onChange, label, withGraph }: {
  k: Kit; kind: string; refer: Obj; onChange: (next: Obj) => void; label?: string; withGraph?: boolean;
}) {
  const brick = k.d.bricks.find(b => b.name === refer.brick);
  return (
    <Stack gap="xs">
      <BrickSelect k={k} kind={kind} label={label} value={refer.brick} onChange={v => k.edit(() => {
        if (!v) return;
        const next: Obj = { ...refer, brick: v };
        if (v !== refer.brick) delete next.settings;
        onChange(next);
      })} />
      <BrickAbout brick={brick} />
      <SettingsEditor k={k} brick={brick} settings={refer.settings || {}} onChange={s => {
        const next = { ...refer };
        if (Object.keys(s).length) next.settings = s; else delete next.settings;
        onChange(next);
      }} />
      {withGraph && (
        <Select label={t('Which graph')} data={[{ value: 'both', label: t('Both the full and the strict graph') }, { value: 'strict', label: t('Only the strict graph') }, { value: 'full', label: t('Only the full graph') }]}
          value={refer.graph || 'both'} onChange={v => k.edit(() => { const next = { ...refer }; if (!v || v === 'both') delete next.graph; else next.graph = v; onChange(next); })} />
      )}
    </Stack>
  );
}
