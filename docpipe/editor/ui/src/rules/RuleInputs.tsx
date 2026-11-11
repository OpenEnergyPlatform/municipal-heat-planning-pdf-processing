/* The input of one rule of the profile's rules file, its row and the rules grouped; the rules drawer and the Graph tab
   both draw them. Every keystroke goes on through onChange as the value the rules file holds. */
import { Accordion, Badge, Box, Button, Code, Group, NativeSelect, Paper, Stack, Switch, Text, Tooltip } from '@mantine/core';
import { DF, type Kind } from '../lib/forms';
import { FormNode, useFormState } from '../components/FormNode';
import { AreaBox, NumberBox, TextBox } from '../components/Inputs';
import { Help } from '../components/Bits';
import { clone, same } from '../lib/util';

export type Rule = Record<string, any>;
/* onChange(value, reset): reset = true draws the input anew from the value (use inherited, discard) */
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
    return <Switch checked={!!cur} label={cur ? 'on' : 'off'} onChange={e => onChange(e.currentTarget.checked)} />;
  }
  if (kind === 'choice') {
    const opts: string[] = (r.choices || []).slice();
    const v = cur == null ? '' : String(cur);
    if (v !== '' && !opts.includes(v)) opts.push(v);
    return <NativeSelect w={260} value={v} data={opts} onChange={e => onChange(e.currentTarget.value)} />;
  }
  if (kind === 'whole' || kind === 'number') {
    return <NumberBox value={cur == null ? '' : String(cur)} step={kind === 'whole' ? '1' : 'any'} min={r.least} max={r.most}
      onText={t => { const s = t.trim(); onChange(s === '' ? null : (isNaN(Number(s)) ? s : Number(s))); }} />;
  }
  if (kind === 'text' || kind === 'chars') {
    return <TextBox mono value={cur == null ? '' : String(cur)} onText={onChange} />;
  }
  if (kind === 'texts') {
    const n = Array.isArray(cur) ? cur.length : 0;
    return <AreaBox mono minRows={Math.min(8, Math.max(2, n + 1))} maxRows={12} value={Array.isArray(cur) ? cur.join('\n') : ''}
      onText={t => onChange(t.split('\n').map(s => s.trim()).filter(Boolean))} />;
  }
  const spec = DF().ruleSpec(r as { kind: string });
  if (!spec) return <Text size="sm" c="red">No form for a rule of kind {String(kind)}.</Text>;
  return <RuleForm r={r} spec={spec} cur={cur} onChange={onChange} epoch={epoch} />;
}

export function RuleRow({ r, cur, onChange, epoch }: { r: Rule; cur: any; onChange: RuleChange; epoch: number }) {
  const changed = ruleChanged(r, cur);
  const wins = r.setting_set || (r.in_effect !== undefined && !same(r.in_effect, r.value));
  return (
    <Paper withBorder radius="md" p="sm" data-rule={r.name}
      style={changed ? { borderLeft: '4px solid var(--mantine-color-orange-5)' } : undefined}>
      <Stack gap={6}>
        <Group gap={6}>
          <Code fw={600}>{r.name}</Code>
          {r.own || r.declared_here ? <Badge color="teal" variant="light">{r.owner || 'set by this profile'}</Badge>
            : <Badge color="gray" variant="light">{r.owner || 'inherited'}</Badge>}
          {r.decided ? <Badge color="gray" variant="outline">decided {r.decided}</Badge> : null}
          {r.setting ? <Badge color={wins ? 'orange' : 'gray'} variant="light">
            setting {r.setting}{wins ? ' is set and wins' : ' wins where set'}</Badge> : null}
          {changed ? <Badge color="orange" variant="filled">edited</Badge> : null}
        </Group>
        <Help text={r.help || ''} />
        <Group align="flex-start" gap="sm" wrap="nowrap">
          <Box style={{ flex: 1, minWidth: 0 }}><RuleInput r={r} cur={cur} onChange={onChange} epoch={epoch} /></Box>
          {r.has_inherited && !same(cur, r.inherited)
            ? <Tooltip label={JSON.stringify(r.inherited)} multiline maw={420}>
                <Button size="xs" variant="default" onClick={() => onChange(clone(r.inherited), true)}>use inherited</Button>
              </Tooltip>
            : null}
        </Group>
        {r.where ? <Text size="xs" c="dimmed" className="dp-mono">applied in {r.where}</Text> : null}
      </Stack>
    </Paper>
  );
}

export function GroupedRules({ rules, curOf, onChange, epoch }: {
  rules: Rule[]; curOf: (name: string) => any; onChange: (name: string, v: any, reset?: boolean) => void; epoch: number;
}) {
  const groups = new Map<string, Rule[]>();
  for (const r of rules) { if (!groups.has(r.group)) groups.set(r.group, []); groups.get(r.group)!.push(r); }
  const names = [...groups.keys()];
  return (
    <Accordion multiple variant="separated" radius="md" defaultValue={names} key={names.join('|')}>
      {[...groups.entries()].map(([g, rs]) => (
        <Accordion.Item key={g} value={g}>
          <Accordion.Control>{g} ({rs.length})</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              {rs.map(r => <RuleRow key={r.name} r={r} cur={curOf(r.name)} epoch={epoch}
                onChange={(v, reset) => onChange(r.name, v, reset)} />)}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
}
