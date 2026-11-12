/* The rules and numbers a step reads, at the step (the right column of the Flow tab, below its settings): in groups, each
   with the input of its kind, "only here" for a value of the step's own, where the value in effect comes from and a link
   to the rule in its tab. A frame has the same panel: what it sets holds for everything in it. */
import { useState } from 'react';
import { Accordion, Anchor, Badge, Box, Group, Stack, Switch, Text, Title } from '@mantine/core';
import { Help } from '../components/Bits';
import { openRule, tabLabel } from '../lib/nav';
import { clone, own, same } from '../lib/util';
import { rich, t, tn, tr, useLang } from '../lib/i18n';
import { RuleInput } from '../rules/RuleInputs';
import { ancestors, find, kindOf, labelOf, libBox, stepKind, walk, type Step, type StepRule } from './model';
import type { Panel } from './Settings';

/* the rules and numbers a box or frame is offered: those read by its own kind of step, and for a frame those read by any
   step in it (the run takes a value of a frame to everything in it) */
export function offered(P: Panel, n: Step): StepRule[] {
  const kinds = new Set([...walk([n])].map(([x]) => stepKind(x)));
  const names = new Set<string>();
  for (const k of kinds) for (const name of P.data.step_rules.kinds[k] || []) names.add(name);
  const lib = P.data.library;
  const b = kindOf(n) === 'box' ? libBox(lib, n.box) : null;
  // a number the box shows as a setting of its own ("only here") is not offered twice
  const shown = new Set((b ? b.settings : []).filter(s => s.kind === 'number' && s.number).map(s => s.number));
  return P.data.step_rules.rules.filter(r => names.has(r.name) && !r.secret && !r.machine && !shown.has(r.name));
}

/* where the value in effect at a step comes from, in words */
export function originOf(P: Panel, n: Step, r: StepRule): { value: unknown; from: 'own' | 'frame' | 'start' | 'standard'; words: string } {
  const mine = n.rules && own(n.rules, r.name);
  if (mine) return { value: n.rules[r.name], from: 'own', words: t('own value') };
  const frames = ancestors(P.tree, n.id).map(id => find(P.tree, id)).filter(Boolean).map(x => x!.n);
  for (const f of frames.reverse()) {
    if (f.rules && own(f.rules, r.name)) {
      return { value: f.rules[r.name], from: 'frame', words: t('from the frame "{title}"', { title: labelOf(P.data.library, f) }) };
    }
  }
  if (!/^(rules|flow)\.json of /.test(r.origin || '')) {
    return { value: r.in_effect, from: 'start', words: t('from the start: {setting}', { setting: r.setting || r.origin }) };
  }
  return { value: r.in_effect, from: 'standard', words: t('standard in {file}', { file: r.origin }) };
}

export function StepRules({ P, n }: { P: Panel; n: Step }) {
  useLang();
  const rows = offered(P, n);
  if (!rows.length) return null;
  const isFrame = kindOf(n) !== 'box';
  const groups = new Map<string, StepRule[]>();
  for (const r of rows) { if (!groups.has(r.group)) groups.set(r.group, []); groups.get(r.group)!.push(r); }
  const hasOwn = (r: StepRule) => !!(n.rules && own(n.rules, r.name));
  const opened = [...groups.entries()].filter(([, rs]) => rs.some(hasOwn)).map(([g]) => g);
  const ownCount = rows.filter(hasOwn).length;
  return (
    <Stack gap="xs">
      <Box>
        <Title order={5}>{isFrame ? t('Rules and numbers for everything in this frame') : t('Rules and numbers this step reads')}</Title>
        <Text size="xs" c="dimmed">
          {isFrame
            ? t('A value set here holds for every step in this frame, unless a step in it has a value of its own.')
            : t('Each one has the value of the flow, a frame around this step or the standard. "Only here" gives this step a value of its own.')}
          {' '}{tn(ownCount, '{n} of {total} has a value of its own here.', '{n} of {total} have a value of their own here.', { total: rows.length })}
        </Text>
      </Box>
      <Accordion multiple variant="separated" radius="md" defaultValue={opened} key={n.id + '|' + opened.join('|')}>
        {[...groups.entries()].map(([g, rs]) => (
          <Accordion.Item key={g} value={g}>
            <Accordion.Control>
              <Group gap={6} wrap="nowrap">
                <Text size="sm" fw={600}>{rich(tr(g))}</Text>
                <Badge size="sm" variant="light" color="gray">{rs.length}</Badge>
                {rs.some(hasOwn) && <Badge size="sm" variant="light" color="teal">{rs.filter(hasOwn).length}</Badge>}
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="md">{rs.map(r => <StepRuleRow key={r.name} P={P} n={n} r={r} />)}</Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </Stack>
  );
}

function StepRuleRow({ P, n, r }: { P: Panel; n: Step; r: StepRule }) {
  const [bump, setBump] = useState(0);
  const mine = !!(n.rules && own(n.rules, r.name));
  const where = originOf(P, n, r);
  const inherited = mine ? undefined : where.value;
  const cur = mine ? n.rules[r.name] : inherited;
  const put = (v: unknown) => { n.rules = n.rules || {}; n.rules[r.name] = v; P.edited(); };
  const only = (on: boolean) => {
    if (on) { n.rules = n.rules || {}; n.rules[r.name] = clone(where.value); }
    else { delete n.rules[r.name]; if (!Object.keys(n.rules).length) delete n.rules; }
    setBump(x => x + 1);
    P.edited();
  };
  const toTab = () => {
    if (r.source === 'number') { P.focusNumber(r.name); return; }
    openRule(P.data.step_rules.tabs[r.name] || r.tab);
  };
  const differs = !!r.decided && r.standard !== null && r.standard !== undefined && !same(cur, r.standard);
  return (
    <Stack gap={6} data-step-rule={r.name}>
      <Group gap={6} justify="space-between" wrap="nowrap" align="flex-start">
        <Text fw={600} size="sm" className="dp-mono" style={{ minWidth: 0, wordBreak: 'break-word' }}>{r.name}</Text>
        <Switch size="sm" label={t('only here')} checked={mine} onChange={e => only(e.currentTarget.checked)}
          title={t('a value of its own for this step, instead of the value in effect')} />
      </Group>
      <Help text={tr(r.help)} size="xs" />
      <Box key={mine ? 'own:' + P.epoch + ':' + bump : 'inherited:' + JSON.stringify(cur)}
        style={mine ? undefined : { opacity: 0.6, pointerEvents: 'none' }} aria-disabled={!mine}>
        <RuleInput r={{ ...r, value: cur }} cur={cur} epoch={P.epoch * 1000 + bump} onChange={v => put(v)} />
      </Box>
      <Group gap={6}>
        <Badge size="sm" variant="light" color={where.from === 'own' ? 'teal' : where.from === 'frame' ? 'indigo' : where.from === 'start' ? 'orange' : 'gray'}>{where.words}</Badge>
        {r.decided ? <Badge size="sm" variant="outline" color="gray">{t('Standard: your decision of {date}', { date: r.decided })}</Badge> : null}
      </Group>
      {differs && <Text size="xs" c="orange">{t('The value here differs from that standard. This locks nothing.')}</Text>}
      <Anchor component="button" type="button" size="xs" style={{ alignSelf: 'flex-start' }} onClick={toTab}>
        {r.source === 'number' ? t('open the number in the list of numbers') : t('open the rule in the {tab} tab', { tab: tabLabel(P.data.step_rules.tabs[r.name] || r.tab) })}
      </Anchor>
    </Stack>
  );
}
