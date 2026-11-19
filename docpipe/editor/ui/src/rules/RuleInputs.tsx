/* The input of one rule of the profile's rules file, its row and the rules grouped; the rules drawer and the Graph tab
   both draw them. Every keystroke goes on through onChange as the value the rules file holds. */
import { useEffect, useState, type ReactNode } from 'react';
import { Accordion, Badge, Box, Button, Group, NativeSelect, Paper, Stack, Switch, Text, TextInput, Tooltip } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { DF, type Kind } from '../lib/forms';
import { FormNode, useFormState } from '../components/FormNode';
import { AreaBox, NumberBox, TextBox } from '../components/Inputs';
import { Help, Named } from '../components/Bits';
import { OwnAt } from './OwnAt';
import { clone, same } from '../lib/util';
import { rich, t, tr } from '../lib/i18n';

export type Rule = Record<string, any>;
/* onChange(value, reset): reset = true draws the input anew from the value (use the default, discard) */
export type RuleChange = (v: any, reset?: boolean) => void;

export const ruleChanged = (r: Rule, cur: unknown) => !same(cur, r.value);

/* map, table and range: forms of forms.js, an emptied map sends {}, an emptied table [] */
function RuleForm({ r, spec, cur, onChange, epoch }: { r: Rule; spec: Kind; cur: unknown; onChange: RuleChange; epoch: number }) {
  const empty = r.kind === 'map' ? {} : r.kind === 'table' ? [] : null;
  // the form state stays while the rule is edited: a range with one bound typed is kept as typed, not as "odd"
  const { root, api } = useFormState(spec, cur, [r.name, epoch], v => onChange(v === undefined ? empty : v));
  return <FormNode spec={spec} st={root} api={api} path={[]} />;
}

export function RuleInput({ r, cur, onChange, epoch }: { r: Rule; cur: any; onChange: RuleChange; epoch: number }) {
  const kind = r.kind;
  if (kind === 'switch') {
    return <Switch checked={!!cur} label={cur ? t('on') : t('off')} onChange={e => onChange(e.currentTarget.checked)} />;
  }
  if (kind === 'choice') {
    const opts: string[] = (r.choices || []).slice();
    const v = cur == null ? '' : String(cur);
    /* a rule with one way only is no choice: it says how the run does it (owner request 2026-11-19, A4) */
    if (opts.length === 1 && (v === '' || v === opts[0])) {
      return <Text size="sm">{rich(t('The only way there is: `{choice}`', { choice: opts[0] }))}</Text>;
    }
    if (v !== '' && !opts.includes(v)) opts.push(v);
    return <NativeSelect w={260} value={v} data={opts} onChange={e => onChange(e.currentTarget.value)} />;
  }
  if (kind === 'whole' || kind === 'number') {
    return <NumberBox value={cur == null ? '' : String(cur)} step={kind === 'whole' ? '1' : 'any'} min={r.least} max={r.most}
      onText={text => { const s = text.trim(); onChange(s === '' ? null : (isNaN(Number(s)) ? s : Number(s))); }} />;
  }
  if (kind === 'text' || kind === 'chars') {
    return <TextBox mono value={cur == null ? '' : String(cur)} onText={onChange} />;
  }
  if (kind === 'texts') {
    const n = Array.isArray(cur) ? cur.length : 0;
    return <AreaBox mono minRows={Math.min(8, Math.max(2, n + 1))} maxRows={12} value={Array.isArray(cur) ? cur.join('\n') : ''}
      onText={text => onChange(text.split('\n').map(s => s.trim()).filter(Boolean))} />;
  }
  const spec = DF().ruleSpec(r as { kind: string });
  if (!spec) return <Text size="sm" c="red">{t('No form for a rule of kind {kind}.', { kind: String(kind) })}</Text>;
  return <RuleForm r={r} spec={spec} cur={cur} onChange={onChange} epoch={epoch} />;
}

export function RuleRow({ r, cur, onChange, epoch, extra }: { r: Rule; cur: any; onChange: RuleChange; epoch: number; extra?: (r: Rule) => ReactNode }) {
  const changed = ruleChanged(r, cur);
  const wins = r.setting_set || (r.in_effect !== undefined && !same(r.in_effect, r.value));
  return (
    <Paper withBorder radius="md" p="sm" data-rule={r.name}
      style={changed ? { borderLeft: '4px solid var(--mantine-color-orange-5)' } : undefined}>
      <Stack gap={6}>
        <Group gap={6}>
          <Named title={r.title} k={r.name} />
          {r.own || r.declared_here ? <Badge color="teal" variant="light">{t('set in this profile')}</Badge>
            : <Badge color="gray" variant="light">{r.set_in ? t('set in profile {name}', { name: r.set_in }) : t('default')}</Badge>}
          {r.setting ? <Badge color={wins ? 'orange' : 'gray'} variant="light">
            {wins ? t('setting {setting} is set and takes precedence', { setting: r.setting }) : t('setting {setting} takes precedence where it is set', { setting: r.setting })}</Badge> : null}
          {changed ? <Badge color="orange" variant="filled">{t('edited')}</Badge> : null}
        </Group>
        <Help text={tr(r.help || '')} />
        {r.own_at && r.own_at.length ? <OwnAt steps={r.own_at} /> : null}
        {r.secret ? <Text size="sm" c="dimmed">{t('A key: it is never shown and never set on this page. Set it in .env or in the environment.')}</Text>
          : r.machine ? <Box>
              <Text size="sm" className="dp-mono">{JSON.stringify(r.in_effect === undefined ? r.value : r.in_effect)}</Text>
              <Text size="xs" c="dimmed">{t('A value of this machine: it is set in the project file docpipe.toml, in the Run section of the Flow tab.')}</Text>
            </Box> : null}
        {r.secret || r.machine ? null : <Group align="flex-start" gap="sm" wrap="nowrap">
          <Box style={{ flex: 1, minWidth: 0 }}><RuleInput r={r} cur={cur} onChange={onChange} epoch={epoch} /></Box>
          {r.has_inherited && !same(cur, r.inherited)
            ? <Tooltip label={JSON.stringify(r.inherited)} multiline maw={420}>
                <Button size="xs" variant="default" onClick={() => onChange(clone(r.inherited), true)}>{t('use default')}</Button>
              </Tooltip>
            : null}
        </Group>}
        {extra ? extra(r) : null}
        {r.where ? <Text size="xs" c="dimmed" className="dp-mono">{t('used in {where}', { where: r.where })}</Text> : null}
      </Stack>
    </Paper>
  );
}

export function GroupedRules({ rules, curOf, onChange, epoch, extra, focus }: {
  rules: Rule[]; curOf: (name: string) => any; onChange: (name: string, v: any, reset?: boolean) => void; epoch: number;
  extra?: (r: Rule) => ReactNode;
  /* a rule to show: its group opens, and it is scrolled to and marked; n tells one request from the next */
  focus?: { name: string; n: number } | null;
}) {
  /* the groups start closed; a search over name, title, help and group opens every group with a rule it finds
     (owner request 2026-11-19, A8) */
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<string[]>([]);
  useEffect(() => {
    if (!focus) return;
    const r = rules.find(one => one.name === focus.name);
    if (!r) return;
    setQuery('');
    setOpen(was => (was.includes(r.group) ? was : [...was, r.group]));
    const timer = setTimeout(() => {
      const el = document.querySelector('[data-rule="' + focus.name + '"]');
      if (el) { el.scrollIntoView({ block: 'center' }); el.classList.add('dp-flag'); setTimeout(() => el.classList.remove('dp-flag'), 2500); }
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus && focus.n]);
  const q = query.trim().toLowerCase();
  const found = (r: Rule) => !q || [r.name, r.title, r.title ? tr(r.title) : '', r.help, tr(r.help || ''), tr(r.group || '')]
    .some(s => typeof s === 'string' && s.toLowerCase().includes(q));
  const groups = new Map<string, Rule[]>();
  for (const r of rules.filter(found)) { if (!groups.has(r.group)) groups.set(r.group, []); groups.get(r.group)!.push(r); }
  const names = [...groups.keys()];
  return (
    <Stack gap="sm">
      <TextInput leftSection={<IconSearch size={16} />} placeholder={t('Search the rules by name or help')} value={query}
        onChange={e => setQuery(e.currentTarget.value)} />
      {q && !names.length ? <Text size="sm" c="dimmed">{t('No rule matches the search.')}</Text> : null}
      <Accordion multiple variant="separated" radius="md" value={q ? names : open} onChange={v => { if (!q) setOpen(v); }}>
        {[...groups.entries()].map(([g, rs]) => (
          <Accordion.Item key={g} value={g}>
            <Accordion.Control>{rich(tr(g))} ({rs.length})</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                {rs.map(r => <RuleRow key={r.name} r={r} cur={curOf(r.name)} epoch={epoch} extra={extra}
                  onChange={(v, reset) => onChange(r.name, v, reset)} />)}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </Stack>
  );
}
