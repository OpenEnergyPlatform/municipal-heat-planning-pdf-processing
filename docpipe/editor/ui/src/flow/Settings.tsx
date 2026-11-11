/* The right column of the Flow tab: the settings of the chosen step, loop, round or branching, or, with nothing chosen,
   the numbers of the flow. Every control writes into the step it shows; a setting set back to its default is removed. */
import type { ReactNode } from 'react';
import {
  Accordion, Alert, Anchor, Badge, Box, Button, Checkbox, Divider, Group, NativeSelect, Stack, Switch, Text,
  Title,
} from '@mantine/core';
import { IconArrowLeft, IconPlus, IconTrash } from '@tabler/icons-react';
import { NumberBox, TextBox } from '../components/Inputs';
import { openPrompt, openRules, openSpec } from '../lib/nav';
import { own, type Obj } from '../lib/util';
import { rich, t, tr, useLang } from '../lib/i18n';
import { CondEditor } from './Conditions';
import { kindOf, labelOf, libBox, normRow, type Cond, type FlowData, type LibSetting, type Step } from './model';

export interface Panel {
  data: FlowData;
  cur: Record<string, number | string>;
  meas: any;
  trial: any;
  problemsOf(id: string): { message: string }[];
  edited(): void;
  numberSet(name: string, v: number | string): void;
  select(id: string | null): void;
}

const Field = ({ label, children, help }: { label: string; children: ReactNode; help?: string }) => (
  <Box>
    <Text size="sm" fw={600} mb={4}>{rich(label)}</Text>
    {children}
    {help ? <Text size="xs" c="dimmed" mt={4}>{rich(help)}</Text> : null}
  </Box>
);

export function StepSettings({ P, n }: { P: Panel; n: Step }) {
  useLang();
  const k = kindOf(n);
  const lib = P.data.library;
  const subjects = P.data.conditions;
  const b = k === 'box' ? libBox(lib, n.box) : null;
  const out: ReactNode[] = [];
  if (b) {
    const arrows = lib.arrows || {};
    const arrow = (key: string) => tr(arrows[key] || key);
    out.push(<Text key="says" size="sm">{rich(tr(b.says))}</Text>);
    out.push(<Text key="takes" size="xs" c="dimmed">{rich(t('takes {takes}, gives {gives} · in the code: `{code}`', { takes: b.takes ? arrow(b.takes) : t('nothing'), gives: arrow(b.gives), code: b.code }))}{b.decided ? t(' · decided on {date}', { date: b.decided }) : ''}</Text>);
    if (b.fixed) out.push(<Alert key="fixed" color="gray" variant="light" p="xs"><Text size="sm">{t('Fixed: {fixed}', { fixed: tr(b.fixed) })}</Text></Alert>);
    if (b.marks && b.marks.length) out.push(<Group key="marks" gap={4}>{b.marks.map(m => <Badge key={m} variant="outline" color="gray" title={t('fixed checks, cannot be removed')}>{rich(tr(m))}</Badge>)}</Group>);
    if (b.asks && P.data.prompts[b.asks]) {
      const pr = P.data.prompts[b.asks];
      out.push(<Field key="prompt" label={t('prompt')}>{pr.written
        ? <Anchor component="button" type="button" onClick={() => openPrompt(pr.id)}>{pr.id}</Anchor>
        : <Text size="sm" c="dimmed">{t('{id} (not written)', { id: pr.id })}</Text>}</Field>);
    }
    if (b.spec && P.data.switches[b.spec]) {
      const sw = P.data.switches[b.spec];
      out.push(<Field key="switch" label={tr(sw.label)}>{sw.items.length
        ? <Group gap={6}>{sw.items.map((it, i) => it.to
            ? <Anchor key={i} component="button" type="button" size="sm" onClick={() => openSpec(it.to)}>{it.label}</Anchor>
            : <Text key={i} size="sm">{it.label}</Text>)}</Group>
        : <Text size="sm" c="dimmed">{rich(tr(sw.none))}</Text>}</Field>);
    }
    for (const s of b.settings) out.push(<SettingField key={'s:' + s.key} P={P} n={n} s={s} />);
  }
  if (k === 'each') {
    if (n.each === 'field') {
      out.push(<Field key="which" label={t('which')}><NativeSelect value={n.which || 'all'}
        data={Object.entries(lib.which).map(([v, words]) => ({ value: v, label: tr(words) }))}
        onChange={e => { n.which = e.currentTarget.value; P.edited(); }} /></Field>);
    }
    const orders = (lib.orders || {})[n.each] || [];
    if (orders.length > 1) {
      out.push(<Field key="order" label={t('order')}><NativeSelect value={n.order || orders[0]}
        data={orders.map(v => ({ value: v, label: tr((lib.order_words || {})[v] || v.replace('_', ' ')) }))}
        onChange={e => { n.order = e.currentTarget.value; P.edited(); }} /></Field>);
    }
    out.push(<Field key="together" label={t('side by side')} help={t('On: the items of this loop are read at the same time. Off: they are read one after another.')}>
      <Switch checked={!!n.together} onChange={e => { if (e.currentTarget.checked) n.together = true; else delete n.together; P.edited(); }} /></Field>);
  }
  if (k === 'round') {
    const supply = !!(n.round && n.round.supply);
    const most = (n.round && n.round.most) || 1;
    out.push(<Field key="runs" label={t('repeats')}>
      <Group gap="xs">
        <NativeSelect value={supply ? 'supply' : 'most'} data={[{ value: 'most', label: t('at most N times') }, { value: 'supply', label: t('until the search hits are used up') }]}
          onChange={e => { n.round = e.currentTarget.value === 'supply' ? { supply: true } : { most: Number(most) || 1 }; P.edited(); }} />
        {!supply && <NumberBox w={90} min={1} value={String(most)} onText={() => {}} aria-label={t('at most')}
          onCommit={x => { const v = Number(x) || 1; if (n.round && n.round.most === v) return; n.round = { most: v }; P.edited(); }} />}
      </Group></Field>);
    out.push(<Field key="stop" label={t('stop when')}><CondEditor subjects={subjects} get={() => (n.stop as Cond) || null}
      set={c => { if (c) n.stop = c; else delete n.stop; P.edited(); }} /></Field>);
  }
  if (k === 'if') {
    (n.if as { when?: Cond }[]).forEach((w, i) => out.push(
      <Field key={'way' + i} label={t('branch {n} when', { n: i + 1 })}>
        <Stack gap={4}>
          <CondEditor subjects={subjects} get={() => w.when || null}
            set={c => { w.when = c || { all: [normRow(subjects, { of: 'coordinate', is: 'year' })] }; P.edited(); }} />
          {n.if.length > 1 && <Box><Button size="compact-xs" variant="subtle" color="red" onClick={() => { n.if.splice(i, 1); P.edited(); }}>{t('remove this branch')}</Button></Box>}
        </Stack>
      </Field>));
    out.push(<Box key="addway"><Button size="xs" variant="light" leftSection={<IconPlus size={14} />}
      onClick={() => { n.if.push({ when: { all: [normRow(subjects, { of: 'coordinate', is: 'year' })] }, steps: [] }); P.edited(); }}>{t('branch')}</Button></Box>);
    out.push(<Field key="else" label={t('else branch')}><Switch checked={own(n, 'else')}
      onChange={e => { if (e.currentTarget.checked) n.else = n.else || []; else delete n.else; P.edited(); }} /></Field>);
  }
  if (k !== 'if' && !(b && b.type === 'check')) {
    out.push(<Field key="when" label={t('only when')}><CondEditor subjects={subjects} get={() => (n.when as Cond) || null}
      set={c => { if (c) n.when = c; else delete n.when; P.edited(); }} /></Field>);
  }
  if (!(b && (b.fixed || !b.switch))) {
    out.push(<Field key="on" label={t('on')}><Switch checked={!n.off} label={n.off ? t('switched off: no run takes this') : t('the run takes this')}
      onChange={e => { if (e.currentTarget.checked) delete n.off; else n.off = true; P.edited(); }} /></Field>);
  }
  const never = b && P.data.never ? P.data.never[n.box] : null;
  const bad = P.problemsOf(n.id);
  const tried = P.trial && P.trial.boxes && P.trial.boxes[n.id];
  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Box style={{ minWidth: 0 }}>
          <Title order={4}>{labelOf(lib, n)}</Title>
          <Text size="xs" c="dimmed" className="dp-mono">{n.id}</Text>
        </Box>
        <Button size="xs" variant="subtle" leftSection={<IconArrowLeft size={14} />} onClick={() => P.select(null)}>{t('numbers')}</Button>
      </Group>
      {never && <Alert color="gray" p="xs">{t('Never taken by this profile: {reason}', { reason: tr(never) })}</Alert>}
      {bad.map((p, i) => <Alert key={i} color="red" p="xs">{p.message}</Alert>)}
      {out}
      {tried && tried.first && (
        <Accordion variant="contained">
          <Accordion.Item value="first">
            <Accordion.Control>{t('First request of the dry run ({kind})', { kind: tried.first.kind })}</Accordion.Control>
            <Accordion.Panel>
              <Text size="xs" fw={600}>{t('instruction')}</Text>
              <pre className="fl-pre">{tried.first.system}</pre>
              <Text size="xs" fw={600}>{t('message')}</Text>
              <pre className="fl-pre">{tried.first.message}</pre>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      )}
    </Stack>
  );
}

function SettingField({ P, n, s }: { P: Panel; n: Step; s: LibSetting }) {
  const sets: Obj = n.set || {};
  const ownVals: Obj = n.own || {};
  const put = (key: string, v: unknown) => {
    n.set = n.set || {};
    if (v === undefined) delete n.set[key]; else n.set[key] = v;
    if (!Object.keys(n.set).length) delete n.set;
    P.edited();
  };
  if (s.kind === 'number') {
    const named = P.data.numbers.find(x => x.name === s.number);
    const has = own(ownVals, s.key);
    const shown = has ? String(ownVals[s.key]) : (named ? String(P.cur[named.name]) : '');
    const wins = named && named.setting;
    const number = s.number || '';
    const help = has
      ? (wins ? t('This step uses its own value instead of the number {number} of the flow. The run setting {setting} overrides the number of the flow, but it does not override an own value.', { number, setting: named!.setting! }) : t('This step uses its own value instead of the number {number} of the flow. To use the number of the flow again, uncheck "only here".', { number }))
      : (wins ? t('This step takes the number {number} of the flow. The run setting {setting} overrides that number. To give this step a value of its own, check "only here".', { number, setting: named!.setting! }) : t('This step takes the number {number} of the flow. To give this step a value of its own, check "only here".', { number }));
    return (
      <Field label={tr(s.label)} help={help}>
        <Group gap="sm">
          <NumberBox w={100} min={named ? named.least : 0} value={shown} disabled={!has} onText={() => {}} aria-label={tr(s.label)}
            onCommit={v => { if (!has || Number(v) === ownVals[s.key]) return; n.own[s.key] = Number(v); P.edited(); }} />
          <Checkbox label={t('only here')} title={t('a value of its own instead of the number {number} of the flow', { number })} checked={has}
            onChange={e => {
              n.own = n.own || {};
              if (e.currentTarget.checked) n.own[s.key] = Number(shown); else delete n.own[s.key];
              if (!Object.keys(n.own).length) delete n.own;
              P.edited();
            }} />
        </Group>
      </Field>
    );
  }
  if (s.kind === 'rule') {
    return (
      <Field label={tr(s.label)} help={tr(s.help)}>
        <Anchor component="button" type="button" size="sm" onClick={() => (s.number ? P.select(null) : openRules('flow'))}>
          {s.number ? t('{name} = {value} →', { name: s.number, value: String(P.cur[s.number]) }) : t('rule {key} →', { key: s.key })}
        </Anchor>
      </Field>
    );
  }
  if (s.kind === 'switch') {
    const on = own(sets, s.key) ? !!sets[s.key] : !!s.default;
    return <Field label={tr(s.label)} help={tr(s.help)}><Switch checked={on}
      onChange={e => put(s.key, e.currentTarget.checked === !!s.default ? undefined : e.currentTarget.checked)} /></Field>;
  }
  if (s.kind === 'choice') {
    return <Field label={tr(s.label)} help={tr(s.help)}><NativeSelect value={String(own(sets, s.key) ? sets[s.key] : s.default)}
      data={(s.choices || []).map(v => ({ value: v, label: tr((s.words || {})[v] || v.replace(/_/g, ' ')) }))}
      onChange={e => put(s.key, e.currentTarget.value === s.default ? undefined : e.currentTarget.value)} /></Field>;
  }
  if (s.kind === 'text') {
    return <Field label={tr(s.label)} help={tr(s.help)}><TextBox value={sets[s.key] || ''} onText={() => {}}
      onCommit={v => { if (v === (sets[s.key] || '')) return; put(s.key, v || undefined); }} /></Field>;
  }
  if (s.kind === 'condition') {
    return <Field label={tr(s.label)} help={tr(s.help)}><CondEditor subjects={P.data.conditions} only={n.box === 'split' ? 'line' : null}
      get={() => (sets[s.key] as Cond) || null} set={c => put(s.key, c || undefined)} /></Field>;
  }
  return null;
}

export function NumbersPane({ P }: { P: Panel }) {
  useLang();
  const meas = P.meas;
  return (
    <Stack gap="md">
      <Box>
        <Title order={4}>{t('Numbers of the flow')}</Title>
        <Text size="sm" c="dimmed">{t('A step that needs a number takes it from here, unless the step has a value of its own ("only here" in its settings). A setting of the run overrides the number of the flow, but not an own value.')}</Text>
      </Box>
      {P.data.numbers.map(n => {
        const v = P.cur[n.name];
        const wins = n.setting && (n.in_effect !== n.value || !String(n.origin || '').startsWith('flow.json'));
        const said: string[] = (meas && meas.says && meas.says[n.name]) || [];
        return (
          <Box key={n.name} data-number={n.name}>
            <Group gap="xs" align="center" wrap="nowrap">
              <NumberBox w={96} min={n.least} value={v == null ? '' : String(v)} aria-label={n.name} title={tr(n.help)}
                className={v !== n.value ? 'fl-edited' : undefined} onText={() => {}}
                onCommit={v => { const nv = /^-?\d+$/.test(v.trim()) ? Number(v) : v; if (nv === P.cur[n.name]) return; P.numberSet(n.name, nv); }} />
              <Text fw={600} size="sm" className="dp-mono" style={{ minWidth: 0 }}>{n.name}</Text>
            </Group>
            <Group gap={4} mt={4}>
              {n.own && <Badge size="sm" color="teal" variant="light">{t('set in profile {name}', { name: n.owner })}</Badge>}
              {wins && <Badge size="sm" color="orange" variant="light">{t('{setting} = {value} overrides it ({origin})', { setting: n.setting!, value: n.in_effect, origin: tr(n.origin) })}</Badge>}
            </Group>
            <Text size="xs" c="dimmed" mt={2}>{rich(tr(n.help))}</Text>
            {said.map((s, i) => <Text key={i} size="xs" c="indigo" mt={2} title={t('what the last run measured, at the value in the field')}>{rich(tr(s))}</Text>)}
          </Box>
        );
      })}
      <Divider />
      {meas && meas.why && <Text size="sm" c="dimmed">{t('Nothing was measured. {why}', { why: tr(String(meas.why)) })}</Text>}
      {((meas && meas.notes) || []).map((note: string, i: number) => <Text key={'m' + i} size="sm" c="dimmed">{rich(tr(note))}</Text>)}
      {(P.data.notes || []).map((note, i) => (
        <Text key={'n' + i} size="sm" c="dimmed">{rich(tr(note.says))}{note.to ? <> <Anchor component="button" type="button" size="sm" onClick={() => openSpec(note.to)}>{t('open in Spec')}</Anchor></> : null}</Text>
      ))}
    </Stack>
  );
}

export const DeleteButton = ({ onClick }: { onClick: () => void }) =>
  <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />} onClick={onClick}>{t('Delete')}</Button>;
