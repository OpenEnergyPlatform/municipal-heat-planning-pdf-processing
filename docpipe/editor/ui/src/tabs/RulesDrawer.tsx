/* The rules of one tab (GET /api/rules?tab=): a drawer on the right with Check, Save and Discard. Closing keeps unsaved
   edits; opening it for another tab with unsaved edits asks first. */
import { useEffect, useReducer, useRef } from 'react';
import { Button, Code, Drawer, Group, Loader, Stack, Text } from '@mantine/core';
import { api, apiR } from '../lib/api';
import { askConfirm, showError, showInfo } from '../lib/dialogs';
import { closeRules, loadState, openRules, setDirty, tabLabel, useTabActions } from '../lib/nav';
import { rich, t, tr } from '../lib/i18n';
import { clone, wrote } from '../lib/util';
import { Report, type Reported } from '../components/Report';
import { GroupedRules, ruleChanged } from '../rules/RuleInputs';

interface State {
  tab: string | null; data: any; cur: Record<string, any>; report: Reported | null; busy: boolean; epoch: number; loading: boolean;
  error: string | null;
}

export function RulesDrawer({ tab }: { tab: string | null }) {
  const ref = useRef<State>({ tab: null, data: null, cur: {}, report: null, busy: false, epoch: 0, loading: false, error: null });
  const [, touch] = useReducer((x: number) => x + 1, 0);
  const RU = ref.current;
  const dirty = () => !!RU.data && RU.data.rules.some((r: any) => ruleChanged(r, RU.cur[r.name]));

  async function load(t: string) {
    RU.tab = t; RU.report = null; RU.data = null; RU.loading = true; RU.error = null; touch();
    try {
      const data = await api('GET', '/api/rules?tab=' + encodeURIComponent(t));
      RU.cur = {};
      for (const r of data.rules) RU.cur[r.name] = clone(r.value);
      RU.data = data; RU.epoch++;
    } catch (e) { RU.error = (e as Error).message; }
    RU.loading = false; touch();
  }

  useEffect(() => {
    if (tab == null) return;
    (async () => {
      if (RU.data && dirty()) {
        if (RU.tab === tab) return;                       // reopened: the edits are still there
        if (!await askConfirm(t('Rules'), t('The rules of the {tab} tab have unsaved edits. Drop them?', { tab: tabLabel(RU.tab!) }), t('Drop'))) {
          openRules(RU.tab!); return;
        }
      }
      await load(tab);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const isDirty = dirty();
  useEffect(() => { setDirty('rules', isDirty); });

  async function send(what: 'check' | 'save') {
    if (RU.busy || !RU.data) return;
    if (what === 'save' && !dirty()) return;
    const values: Record<string, any> = {};
    for (const r of RU.data.rules) if (ruleChanged(r, RU.cur[r.name])) values[r.name] = RU.cur[r.name];
    RU.busy = true; touch();
    try {
      const r = await apiR('/api/rules/' + what, what === 'save' ? { values, base: RU.data.base } : { values });
      if (what === 'save' && r.saved) {
        showInfo(t('Saved {file} ({writes}).', { file: r.file, writes: wrote(r.writes) }));
        RU.busy = false;
        loadState().catch(showError);
        await load(RU.tab!);
        return;
      }
      RU.report = { source: what, r };
    } catch (e) { RU.report = { source: what, error: (e as Error).message }; }
    RU.busy = false; touch();
  }
  useTabActions('rules', { check: () => send('check'), save: () => send('save') });

  const discard = () => {
    for (const r of RU.data.rules) RU.cur[r.name] = clone(r.value);
    RU.report = null; RU.epoch++; touch();
  };
  const onName = (name: string) => {
    const el = document.querySelector('[data-rule="' + name + '"]');
    if (el) { el.scrollIntoView({ block: 'center' }); el.classList.add('dp-flag'); setTimeout(() => el.classList.remove('dp-flag'), 2500); }
  };

  const d = RU.data;
  return (
    <Drawer opened={tab != null} onClose={closeRules} position="right" size={720} padding="md"
      title={<Text fw={700} size="lg">{t('Rules of the {tab} tab', { tab: tabLabel((RU.tab ?? tab) as string) })}</Text>}>
      {RU.loading && <Group justify="center" p="xl"><Loader /></Group>}
      {RU.error && <Text c="red">{RU.error}</Text>}
      {d && (
        <Stack gap="md">
          <Group justify="space-between" wrap="nowrap" align="flex-start">
            <Stack gap={2}>
              <Code>{d.file}</Code>
              {!d.exists && <Text size="sm" c="dimmed">{t('No file is written yet, so every rule has its default value. Saving a changed rule writes the file.')}</Text>}
            </Stack>
            <Group gap="xs" wrap="nowrap">
              <Button variant="default" disabled={RU.busy} loading={RU.busy} onClick={() => send('check')}>{t('Check')}</Button>
              <Button disabled={RU.busy || !isDirty} onClick={() => send('save')}>{t('Save')}</Button>
              <Button variant="subtle" disabled={!isDirty} onClick={discard}>{t('Discard')}</Button>
            </Group>
          </Group>
          {d.cost && <Text size="sm" c="dimmed">{rich(tr(d.cost))}</Text>}
          <Report R={RU.report} onName={onName} onReload={() => load(RU.tab!)} />
          {d.rules.length
            ? <GroupedRules rules={d.rules} epoch={RU.epoch} curOf={n => RU.cur[n]}
                onChange={(n, v, reset) => { RU.cur[n] = v; RU.report = null; if (reset) RU.epoch++; touch(); }} />
            : <Text c="dimmed">{t('This profile has no rule for this tab, so there is nothing to set here.')}</Text>}
        </Stack>
      )}
    </Drawer>
  );
}
