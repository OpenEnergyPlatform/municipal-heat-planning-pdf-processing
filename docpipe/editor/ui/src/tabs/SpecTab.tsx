/* The Spec tab of `docpipe edit`: the tree of the spec on the left, the form of the chosen node on the right, and above it
   what the last check says an edit costs. The parts are in ../spec. */
import { useEffect, useState } from 'react';
import { Alert, Box, Button, Center, Group, Loader } from '@mantine/core';
import { IconDeviceFloppy, IconListCheck, IconRefresh } from '@tabler/icons-react';
import { showError } from '../lib/dialogs';
import { t } from '../lib/i18n';
import { useStore, useTabActions, useRequests } from '../lib/nav';
import { doCheck, doSave, loadAll, meta, reload, S, select, takeData } from '../spec/state';
import { Tree } from '../spec/Tree';
import { Main } from '../spec/Main';
import { ResultPanel } from '../spec/Panel';
import '../spec/spec.css';

function Toolbar() {
  useStore(meta);
  return (
    <Group gap="xs" px="md" pt="xs" justify="space-between">
      <Group gap="xs">
        <Button variant="default" leftSection={<IconRefresh size={16} />} disabled={S.busy} onClick={() => reload()}>{t('Reload from disk')}</Button>
      </Group>
      <Group gap="xs">
        <Button variant="default" leftSection={<IconListCheck size={16} />} disabled={S.busy} title={t('Ctrl+Enter')} onClick={() => doCheck()}>{t('Check')}</Button>
        <Button leftSection={<IconDeviceFloppy size={16} />} disabled={S.busy} loading={S.busy} title={t('Ctrl+S')} onClick={() => doSave(false)}>{t('Save')}</Button>
      </Group>
    </Group>
  );
}

export function SpecTab() {
  const [phase, setPhase] = useState<'loading' | 'ready' | string>(S.loaded ? 'ready' : 'loading');
  useEffect(() => {
    if (S.loaded) return;
    loadAll().then(() => setPhase('ready'), e => { showError(e); setPhase(e instanceof Error ? e.message : String(e)); });
  }, []);
  useTabActions('spec', { check: () => { void doCheck(); }, save: () => { void doSave(false); } });
  useRequests('spec', phase === 'ready', (p: { node?: any; flag?: any; taken?: any }) => {
    if (p.taken) takeData(p.taken);
    else if (p.node) select(p.node, p.flag);
  });
  if (phase === 'loading') return <Center style={{ flex: 1 }}><Loader /></Center>;
  if (phase !== 'ready') return <Alert color="red" m="md" title={t('The spec could not be loaded')}>{phase}</Alert>;
  return (
    <Box style={{ display: 'flex', flex: 1, minHeight: 0 }}>
      <Tree />
      <Box style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Toolbar />
        <ResultPanel />
        <Main />
      </Box>
    </Box>
  );
}
