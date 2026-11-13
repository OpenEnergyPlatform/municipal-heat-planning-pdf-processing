/* The section "Run" of the Flow tab (collapsed): what holds for the whole run and no step reads, with its value and where
   it comes from, set as in the rules drawer (the rules file of the profile); and the values of this machine, written
   only into the project file docpipe.toml that git does not track. A key is never shown and never written here. */
import { useEffect, useRef, useState } from 'react';
import { Accordion, Alert, Button, Group, Loader, Paper, Stack, Text } from '@mantine/core';
import { api, apiR } from '../lib/api';
import { showError, showInfo } from '../lib/dialogs';
import { clone, same, wrote } from '../lib/util';
import { rich, t, tr, useLang } from '../lib/i18n';
import { GroupedRules, RuleInput, type Rule } from '../rules/RuleInputs';
import { Help } from '../components/Bits';
import type { Panel } from './Settings';

interface Loaded { rules: Rule[]; base: string | null; file: string }

/* where a value in effect comes from, in words (the rules file, a setting of the start, the environment) */
const fromWords = (origin: string) => origin
  ? (/^(rules|flow)\.json of /.test(origin) ? t('standard in {file}', { file: origin }) : t('from the start: {origin}', { origin }))
  : '';

export function RunSection({ P }: { P: Panel }) {
  useLang();
  const [opened, setOpened] = useState<string | null>(null);
  return (
    <Accordion variant="contained" value={opened} onChange={setOpened}>
      <Accordion.Item value="run">
        <Accordion.Control>{t('Run')}</Accordion.Control>
        <Accordion.Panel>{opened === 'run' ? <RunBody P={P} /> : null}</Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}

function RunBody({ P }: { P: Panel }) {
  const ref = useRef<{ data: Loaded | null; cur: Record<string, any>; epoch: number; error: string | null; busy: boolean; report: any }>(
    { data: null, cur: {}, epoch: 0, error: null, busy: false, report: null }).current;
  const [, setV] = useState(0);
  const touch = () => setV(x => x + 1);
  const load = async () => {
    try {
      const d = await api('GET', '/api/rules?tab=flow');
      // the rules of the Flow tab that no step reads: the run's own
      ref.data = { rules: d.rules.filter((r: Rule) => !(r.steps || []).length && !r.machine && !r.secret), base: d.base, file: d.file };
      ref.cur = {};
      for (const r of ref.data.rules) ref.cur[r.name] = clone(r.value);
      ref.epoch++; ref.error = null;
    } catch (e) { ref.error = (e as Error).message; }
    touch();
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = !!ref.data && ref.data.rules.some(r => !same(ref.cur[r.name], r.value));
  const save = async () => {
    if (!ref.data || ref.busy) return;
    const values: Record<string, any> = {};
    for (const r of ref.data.rules) if (!same(ref.cur[r.name], r.value)) values[r.name] = ref.cur[r.name];
    ref.busy = true; touch();
    try {
      const r = await apiR('/api/rules/save', { values, base: ref.data.base });
      if (r.saved) { showInfo(t('Saved {file} ({writes}).', { file: r.file, writes: wrote(r.writes) })); ref.report = null; await load(); P.reload(); }
      else ref.report = r;
    } catch (e) { showError(e); }
    ref.busy = false; touch();
  };
  const run = ref.data;
  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">{t('What holds for the whole run: no step reads it, so it is set here and not at a step.')}</Text>
      {ref.error && <Alert color="red">{ref.error}</Alert>}
      {!run && !ref.error && <Group justify="center"><Loader size="sm" /></Group>}
      {run && (
        <>
          {run.rules.length
            ? <GroupedRules rules={run.rules} epoch={ref.epoch} curOf={n => ref.cur[n]}
                extra={r => <Text size="xs" c="dimmed">{t('In effect: {value} ({from})', { value: JSON.stringify(r.in_effect), from: fromWords(r.origin) || r.origin })}</Text>}
                onChange={(n, v, reset) => { ref.cur[n] = v; ref.report = null; if (reset) ref.epoch++; touch(); }} />
            : <Text size="sm" c="dimmed">{t('Every rule of the Flow tab is read by a step.')}</Text>}
          {ref.report && !ref.report.saved && <Alert color="red">{rich(tr(ref.report.message || ''))}</Alert>}
          {run.rules.length > 0 && (
            <Group gap="xs">
              <Button size="xs" disabled={ref.busy || !dirty} loading={ref.busy} onClick={save}>{t('Save')}</Button>
              <Button size="xs" variant="subtle" disabled={!dirty} onClick={() => { for (const r of run.rules) ref.cur[r.name] = clone(r.value); ref.report = null; ref.epoch++; touch(); }}>{t('Discard')}</Button>
              <Text size="xs" c="dimmed">{t('Saved in {file}', { file: run.file })}</Text>
            </Group>
          )}
        </>
      )}
      <Machine P={P} />
    </Stack>
  );
}

/* the values of this machine: written into the project file only, and only where git does not track it */
function Machine({ P }: { P: Panel }) {
  const rows = P.data.run.machine;
  const project = P.data.run.project;
  const ref = useRef<{ cur: Record<string, any>; epoch: number; busy: boolean; report: any }>({ cur: {}, epoch: 0, busy: false, report: null }).current;
  const [, setV] = useState(0);
  const touch = () => setV(x => x + 1);
  const curOf = (n: string, v: any) => (Object.prototype.hasOwnProperty.call(ref.cur, n) ? ref.cur[n] : v);
  const dirty = rows.some(r => Object.prototype.hasOwnProperty.call(ref.cur, r.name) && !same(ref.cur[r.name], r.in_effect));
  const save = async () => {
    const values: Record<string, any> = {};
    for (const r of rows) if (Object.prototype.hasOwnProperty.call(ref.cur, r.name) && !same(ref.cur[r.name], r.in_effect)) values[r.name] = ref.cur[r.name];
    ref.busy = true; touch();
    try {
      const r = await apiR('/api/machine/save', { values });
      if (r.saved) { showInfo(t('Saved {file} ({writes}).', { file: r.file, writes: wrote(r.writes) })); ref.cur = {}; ref.report = null; ref.epoch++; P.reload(); }
      else ref.report = r;
    } catch (e) { showError(e); }
    ref.busy = false; touch();
  };
  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>{t('Values of this machine')}</Text>
      <Text size="xs" c="dimmed">{t('A value of this machine (an address, a folder) is written only into the project file, which git does not track, never into a file of the repository. A key is never shown and never written here: set it in .env or in the environment.')}</Text>
      {project && <Text size="xs" c="dimmed">{t('Project file: {file}', { file: project.file })}{project.exists ? '' : ' ' + t('(not written yet)')}</Text>}
      {project && project.refused && <Alert color="red" p="xs"><Text size="sm">{rich(tr(project.refused))}</Text></Alert>}
      {!rows.length && <Text size="sm" c="dimmed">{t('No rule of this profile is a value of the machine.')}</Text>}
      {rows.map(r => (
        <Paper key={r.name} withBorder radius="md" p="sm" data-machine={r.name}>
          <Stack gap={6}>
            <Text fw={600} size="sm" className="dp-mono">{r.name}</Text>
            <Help text={tr(r.help)} size="xs" />
            <RuleInput r={{ ...r, value: r.in_effect }} cur={curOf(r.name, r.in_effect)} epoch={ref.epoch}
              onChange={v => { ref.cur[r.name] = v; ref.report = null; touch(); }} />
            <Text size="xs" c="dimmed">{t('In effect: {value} ({from})', { value: JSON.stringify(r.in_effect), from: fromWords(r.origin) || r.origin })}{r.key ? ' · ' + t('key in the project file: {key}', { key: r.key }) : ''}</Text>
          </Stack>
        </Paper>
      ))}
      {ref.report && !ref.report.saved && <Alert color="red"><Text size="sm">{rich(tr(ref.report.message || ''))}</Text></Alert>}
      {rows.length > 0 && (
        <Group gap="xs">
          <Button size="xs" disabled={ref.busy || !dirty || !!(project && project.refused)} loading={ref.busy} onClick={save}>{t('Save in the project file')}</Button>
          <Button size="xs" variant="subtle" disabled={!dirty} onClick={() => { ref.cur = {}; ref.report = null; ref.epoch++; touch(); }}>{t('Discard')}</Button>
        </Group>
      )}
    </Stack>
  );
}
