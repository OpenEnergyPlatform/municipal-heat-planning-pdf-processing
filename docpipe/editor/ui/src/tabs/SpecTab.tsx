/* The Spec tab of `docpipe edit`. On the left what the spec has: its fields, the dimensions several fields share, the order
   of the questions, the fields of the whole document, the value types. In the middle the one chosen: a field as a drawing
   of where its lists come from in the ontology, what it asks of each value and the entries the model chooses from; a
   shared dimension as a dictionary of its entries with the words of the plans. On the right the settings of what is
   selected. Above them the toolbar and what the last check says. The parts are in ../spec. */
import { useEffect, useState } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { ActionIcon, Alert, Badge, Box, Button, Center, Code, Group, Loader, Text, Tooltip } from '@mantine/core';
import { IconArrowBackUp, IconArrowForwardUp, IconArrowsShuffle, IconCheck, IconDeviceFloppy, IconFocusCentered, IconX } from '@tabler/icons-react';
import { showError } from '../lib/dialogs';
import { t } from '../lib/i18n';
import { stateStore, tabStore, useStore, useTabActions, useRequests } from '../lib/nav';
import { discard, doCheck, doSave, H, loadAll, meta, redo, reveal, S, takeData, touch, undo, view } from '../spec/state';
import { FieldCanvas, untangleField } from '../spec/Canvas';
import { Dictionary } from '../spec/Dictionary';
import { Nav, OrderPage, PlanPage, SpecPage, TypesPage } from '../spec/Pages';
import { ListModal, Main } from '../spec/Main';
import { ResultPanel } from '../spec/Panel';
import '../spec/spec.css';

/* a profile with only a draft of its spec: what it still lacks, said above the drawing */
function DraftNote() {
  useStore(meta);
  if (!S.draft) return null;
  return (
    <Alert color="yellow" mx="md" mt="xs" title={t('A draft of the spec')}>
      {t('This profile has a draft of its spec and no spec yet. Saving keeps the draft; once it lacks nothing, saving also writes the spec.')}
      {S.missing.length ? (
        <Box component="ul" my={4}>{S.missing.map((m, i) => <li key={i}>{m}</li>)}</Box>
      ) : <Box mt={4}>{t('It lacks nothing: save to write the spec.')}</Box>}
    </Alert>
  );
}

function Toolbar() {
  useStore(meta);
  const page = useStore(stateStore);
  const field = S.view.t === 'field' ? S.view.uri : null;
  return (
    <Group px="md" py={8} gap="sm" justify="space-between" className="gr-bar" wrap="nowrap">
      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        {page ? <Code>{page.spec}</Code> : null}
        {S.dirty ? <Badge color="yellow" variant="light" tt="none">{t('edited, not saved')}</Badge> : null}
      </Group>
      <Group gap={6} wrap="nowrap">
        <Tooltip label={t('Undo (Ctrl+Z)')}><ActionIcon variant="default" size="lg" disabled={!H.undo.length || S.busy} onClick={undo} aria-label={t('Undo')}><IconArrowBackUp size={18} /></ActionIcon></Tooltip>
        <Tooltip label={t('Redo (Ctrl+Y)')}><ActionIcon variant="default" size="lg" disabled={!H.redo.length || S.busy} onClick={redo} aria-label={t('Redo')}><IconArrowForwardUp size={18} /></ActionIcon></Tooltip>
        {field ? (
          <>
            <Tooltip label={t('Show the whole drawing')}><ActionIcon variant="default" size="lg" onClick={() => { S.fit++; touch(); }} aria-label={t('Show the whole drawing')}><IconFocusCentered size={18} /></ActionIcon></Tooltip>
            <Tooltip label={t('Order the lists of the ontology so that as few arrows cross as possible')} multiline w={260}>
              <Button variant="default" leftSection={<IconArrowsShuffle size={16} />} onClick={() => untangleField(field)}>{t('Untangle arrows')}</Button>
            </Tooltip>
          </>
        ) : null}
        <Button variant="default" leftSection={<IconCheck size={16} />} loading={S.busy} title={t('Ctrl+Enter')} onClick={() => doCheck()}>{t('Check')}</Button>
        <Button leftSection={<IconDeviceFloppy size={16} />} disabled={S.busy || !S.dirty} title={t('Ctrl+S')} onClick={() => doSave(false)}>{t('Save')}</Button>
        <Button variant="default" leftSection={<IconX size={16} />} disabled={S.busy || !S.dirty} onClick={() => void discard()}>{t('Discard')}</Button>
      </Group>
    </Group>
  );
}

/* Ctrl+Z and Ctrl+Y while the Spec tab is open and no text is being typed */
function useUndoKeys() {
  useEffect(() => {
    const keys = (ev: KeyboardEvent) => {
      const cur = tabStore.get();
      if (cur.tab !== 'spec' || cur.rules || !(ev.ctrlKey || ev.metaKey)) return;
      const el = ev.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
      const k = ev.key.toLowerCase();
      if (k === 'z' && !ev.shiftKey) { ev.preventDefault(); undo(); }
      else if (k === 'y' || (k === 'z' && ev.shiftKey)) { ev.preventDefault(); redo(); }
    };
    window.addEventListener('keydown', keys);
    return () => window.removeEventListener('keydown', keys);
  }, []);
}

/* what the middle shows */
function Center_() {
  useStore(view);
  const v = S.view;
  if (v.t === 'field') return <ReactFlowProvider><FieldCanvas uri={v.uri} /></ReactFlowProvider>;
  if (v.t === 'shared') return <Dictionary name={v.name} />;
  if (v.t === 'order') return <OrderPage />;
  if (v.t === 'plan') return <PlanPage />;
  if (v.t === 'types') return <TypesPage />;
  return <SpecPage />;
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
    else if (p.node) reveal(p.node, p.flag);
  });
  useUndoKeys();
  if (phase === 'loading') return <Center style={{ flex: 1 }}><Loader /></Center>;
  if (phase !== 'ready') return <Alert color="red" m="md" title={t('The spec could not be loaded')}>{phase}</Alert>;
  return (
    <Box style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <Toolbar />
      <DraftNote />
      <ResultPanel />
      <Box className="sp-body">
        <Nav />
        <Box className="sp-center"><Center_ /></Box>
        <Box className="sp-panel"><Main /></Box>
      </Box>
      <ListModal />
      <Text size="xs" c="dimmed" px="md" py={4} className="sp-hint">{t('Choose a field on the left to see where its lists come from and what it asks of each value. Click a box for its settings on the right.')}</Text>
    </Box>
  );
}
