/* The right column of the Flow tab: the settings of the chosen box or frame, or, with nothing chosen, the numbers of the
   flow. Every control writes into the step it shows; a setting set back to its default is removed. */
import type { ReactNode } from 'react';
import {
  Accordion, Alert, Anchor, Badge, Box, Button, Checkbox, Code, Divider, Group, NativeSelect, Stack, Switch, Text,
  Title,
} from '@mantine/core';
import { IconArrowLeft, IconPlus, IconTrash } from '@tabler/icons-react';
import { NumberBox, TextBox } from '../components/Inputs';
import { openPrompt, openRules, openSpec } from '../lib/nav';
import { own, type Obj } from '../lib/util';
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
    <Text size="sm" fw={600} mb={4}>{label}</Text>
    {children}
    {help ? <Text size="xs" c="dimmed" mt={4}>{help}</Text> : null}
  </Box>
);

export function StepSettings({ P, n }: { P: Panel; n: Step }) {
  const k = kindOf(n);
  const lib = P.data.library;
  const subjects = P.data.conditions;
  const b = k === 'box' ? libBox(lib, n.box) : null;
  const out: ReactNode[] = [];
  if (b) {
    out.push(<Text key="says" size="sm">{b.says}</Text>);
    out.push(<Text key="takes" size="xs" c="dimmed">takes {b.takes || 'nothing'}, gives {b.gives} · in the code: <Code>{b.code}</Code>{b.decided ? ' · decided ' + b.decided : ''}</Text>);
    if (b.fixed) out.push(<Alert key="fixed" color="gray" variant="light" p="xs"><Text size="sm">Fixed: {b.fixed}</Text></Alert>);
    if (b.marks && b.marks.length) out.push(<Group key="marks" gap={4}>{b.marks.map(m => <Badge key={m} variant="outline" color="gray" title="fixed checks, cannot be removed">{m}</Badge>)}</Group>);
    if (b.asks && P.data.prompts[b.asks]) {
      const pr = P.data.prompts[b.asks];
      out.push(<Field key="prompt" label="prompt">{pr.written
        ? <Anchor component="button" type="button" onClick={() => openPrompt(pr.id)}>{pr.id}</Anchor>
        : <Text size="sm" c="dimmed">{pr.id} (not written)</Text>}</Field>);
    }
    if (b.spec && P.data.switches[b.spec]) {
      const sw = P.data.switches[b.spec];
      out.push(<Field key="switch" label={sw.label}>{sw.items.length
        ? <Group gap={6}>{sw.items.map((it, i) => it.to
            ? <Anchor key={i} component="button" type="button" size="sm" onClick={() => openSpec(it.to)}>{it.label}</Anchor>
            : <Text key={i} size="sm">{it.label}</Text>)}</Group>
        : <Text size="sm" c="dimmed">{sw.none}</Text>}</Field>);
    }
    for (const s of b.settings) out.push(<SettingField key={'s:' + s.key} P={P} n={n} s={s} />);
  }
  if (k === 'each') {
    if (n.each === 'field') {
      out.push(<Field key="which" label="which"><NativeSelect value={n.which || 'all'}
        data={Object.entries(lib.which).map(([v, t]) => ({ value: v, label: t }))}
        onChange={e => { n.which = e.currentTarget.value; P.edited(); }} /></Field>);
    }
    const orders = (lib.orders || {})[n.each] || [];
    if (orders.length > 1) {
      out.push(<Field key="order" label="order"><NativeSelect value={n.order || orders[0]}
        data={orders.map(v => ({ value: v, label: v.replace('_', ' ') }))}
        onChange={e => { n.order = e.currentTarget.value; P.edited(); }} /></Field>);
    }
    out.push(<Field key="together" label="side by side" help="Its items are asked at the same time.">
      <Switch checked={!!n.together} onChange={e => { if (e.currentTarget.checked) n.together = true; else delete n.together; P.edited(); }} /></Field>);
  }
  if (k === 'round') {
    const supply = !!(n.round && n.round.supply);
    const most = (n.round && n.round.most) || 1;
    out.push(<Field key="runs" label="runs">
      <Group gap="xs">
        <NativeSelect value={supply ? 'supply' : 'most'} data={[{ value: 'most', label: 'at most N times' }, { value: 'supply', label: 'until the supply is used up' }]}
          onChange={e => { n.round = e.currentTarget.value === 'supply' ? { supply: true } : { most: Number(most) || 1 }; P.edited(); }} />
        {!supply && <NumberBox w={90} min={1} value={String(most)} onText={() => {}} aria-label="at most"
          onCommit={t => { const v = Number(t) || 1; if (n.round && n.round.most === v) return; n.round = { most: v }; P.edited(); }} />}
      </Group></Field>);
    out.push(<Field key="stop" label="stop when"><CondEditor subjects={subjects} get={() => (n.stop as Cond) || null}
      set={c => { if (c) n.stop = c; else delete n.stop; P.edited(); }} /></Field>);
  }
  if (k === 'if') {
    (n.if as { when?: Cond }[]).forEach((w, i) => out.push(
      <Field key={'way' + i} label={'way ' + (i + 1) + ' when'}>
        <Stack gap={4}>
          <CondEditor subjects={subjects} get={() => w.when || null}
            set={c => { w.when = c || { all: [normRow(subjects, { of: 'coordinate', is: 'year' })] }; P.edited(); }} />
          {n.if.length > 1 && <Box><Button size="compact-xs" variant="subtle" color="red" onClick={() => { n.if.splice(i, 1); P.edited(); }}>remove this way</Button></Box>}
        </Stack>
      </Field>));
    out.push(<Box key="addway"><Button size="xs" variant="light" leftSection={<IconPlus size={14} />}
      onClick={() => { n.if.push({ when: { all: [normRow(subjects, { of: 'coordinate', is: 'year' })] }, steps: [] }); P.edited(); }}>way</Button></Box>);
    out.push(<Field key="else" label="else way"><Switch checked={own(n, 'else')}
      onChange={e => { if (e.currentTarget.checked) n.else = n.else || []; else delete n.else; P.edited(); }} /></Field>);
  }
  if (k !== 'if' && !(b && b.type === 'check')) {
    out.push(<Field key="when" label="only when"><CondEditor subjects={subjects} get={() => (n.when as Cond) || null}
      set={c => { if (c) n.when = c; else delete n.when; P.edited(); }} /></Field>);
  }
  if (!(b && (b.fixed || !b.switch))) {
    out.push(<Field key="on" label="on"><Switch checked={!n.off} label={n.off ? 'switched off: no run takes this' : 'the run takes this'}
      onChange={e => { if (e.currentTarget.checked) delete n.off; else n.off = true; P.edited(); }} /></Field>);
  }
  const never = b && P.data.never ? P.data.never[n.box] : null;
  const bad = P.problemsOf(n.id);
  const t = P.trial && P.trial.boxes && P.trial.boxes[n.id];
  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Box style={{ minWidth: 0 }}>
          <Title order={4}>{labelOf(lib, n)}</Title>
          <Text size="xs" c="dimmed" className="dp-mono">{n.id}</Text>
        </Box>
        <Button size="xs" variant="subtle" leftSection={<IconArrowLeft size={14} />} onClick={() => P.select(null)}>numbers</Button>
      </Group>
      {never && <Alert color="gray" p="xs">Never taken by this profile: {never}</Alert>}
      {bad.map((p, i) => <Alert key={i} color="red" p="xs">{p.message}</Alert>)}
      {out}
      {t && t.first && (
        <Accordion variant="contained">
          <Accordion.Item value="first">
            <Accordion.Control>First request of the try ({t.first.kind})</Accordion.Control>
            <Accordion.Panel>
              <Text size="xs" fw={600}>instruction</Text>
              <pre className="fl-pre">{t.first.system}</pre>
              <Text size="xs" fw={600}>message</Text>
              <pre className="fl-pre">{t.first.message}</pre>
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
    return (
      <Field label={s.label} help={(has ? 'own value; ' : 'the named number ') + s.number
        + (named && named.setting ? ' (a run setting ' + named.setting + ' wins over the named number, never over an own value)' : '')}>
        <Group gap="sm">
          <NumberBox w={100} min={named ? named.least : 0} value={shown} disabled={!has} onText={() => {}} aria-label={s.label}
            onCommit={t => { if (!has || Number(t) === ownVals[s.key]) return; n.own[s.key] = Number(t); P.edited(); }} />
          <Checkbox label="only here" title={'a value of its own instead of the named number ' + s.number} checked={has}
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
      <Field label={s.label} help={s.help}>
        <Anchor component="button" type="button" size="sm" onClick={() => (s.number ? P.select(null) : openRules('flow'))}>
          {(s.number ? s.number + ' = ' + P.cur[s.number] : 'rule ' + s.key) + ' →'}
        </Anchor>
      </Field>
    );
  }
  if (s.kind === 'switch') {
    const on = own(sets, s.key) ? !!sets[s.key] : !!s.default;
    return <Field label={s.label} help={s.help}><Switch checked={on}
      onChange={e => put(s.key, e.currentTarget.checked === !!s.default ? undefined : e.currentTarget.checked)} /></Field>;
  }
  if (s.kind === 'choice') {
    return <Field label={s.label} help={s.help}><NativeSelect value={String(own(sets, s.key) ? sets[s.key] : s.default)}
      data={(s.choices || []).map(v => ({ value: v, label: v.replace(/_/g, ' ') }))}
      onChange={e => put(s.key, e.currentTarget.value === s.default ? undefined : e.currentTarget.value)} /></Field>;
  }
  if (s.kind === 'text') {
    return <Field label={s.label} help={s.help}><TextBox value={sets[s.key] || ''} onText={() => {}}
      onCommit={t => { if (t === (sets[s.key] || '')) return; put(s.key, t || undefined); }} /></Field>;
  }
  if (s.kind === 'condition') {
    return <Field label={s.label} help={s.help}><CondEditor subjects={P.data.conditions} only={n.box === 'split' ? 'line' : null}
      get={() => (sets[s.key] as Cond) || null} set={c => put(s.key, c || undefined)} /></Field>;
  }
  return null;
}

export function NumbersPane({ P }: { P: Panel }) {
  const meas = P.meas;
  return (
    <Stack gap="md">
      <Box>
        <Title order={4}>Numbers of the flow</Title>
        <Text size="sm" c="dimmed">Every box that takes a number takes the named one, unless it has its own value (only here). A setting of the run wins over the named number.</Text>
      </Box>
      {P.data.numbers.map(n => {
        const v = P.cur[n.name];
        const wins = n.setting && (n.in_effect !== n.value || !String(n.origin || '').startsWith('flow.json'));
        const said: string[] = (meas && meas.says && meas.says[n.name]) || [];
        return (
          <Box key={n.name} data-number={n.name}>
            <Group gap="xs" align="center" wrap="nowrap">
              <NumberBox w={96} min={n.least} value={v == null ? '' : String(v)} aria-label={n.name} title={n.help}
                className={v !== n.value ? 'fl-edited' : undefined} onText={() => {}}
                onCommit={t => { const nv = /^-?\d+$/.test(t.trim()) ? Number(t) : t; if (nv === P.cur[n.name]) return; P.numberSet(n.name, nv); }} />
              <Text fw={600} size="sm" className="dp-mono" style={{ minWidth: 0 }}>{n.name}</Text>
            </Group>
            <Group gap={4} mt={4}>
              {n.own && <Badge size="sm" color="teal" variant="light">set by this profile</Badge>}
              {wins && <Badge size="sm" color="orange" variant="light">{n.setting} = {n.in_effect} wins ({n.origin})</Badge>}
            </Group>
            <Text size="xs" c="dimmed" mt={2}>{n.help}</Text>
            {said.map((s, i) => <Text key={i} size="xs" c="indigo" mt={2} title="what the last run measured, at the value in the field">{s}</Text>)}
          </Box>
        );
      })}
      <Divider />
      {meas && meas.why && <Text size="sm" c="dimmed">Nothing measured: {meas.why}.</Text>}
      {((meas && meas.notes) || []).map((note: string, i: number) => <Text key={'m' + i} size="sm" c="dimmed">{note}</Text>)}
      {(P.data.notes || []).map((note, i) => (
        <Text key={'n' + i} size="sm" c="dimmed">{note.says}{note.to ? <> <Anchor component="button" type="button" size="sm" onClick={() => openSpec(note.to)}>open in Spec</Anchor></> : null}</Text>
      ))}
    </Stack>
  );
}

export const DeleteButton = ({ onClick }: { onClick: () => void }) =>
  <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />} onClick={onClick}>Delete</Button>;
