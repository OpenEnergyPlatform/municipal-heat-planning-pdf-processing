/* The frame of the page: the head with the profile, its files and the tabs, the tabs themselves (each loaded the first
   time it opens and kept while the page is open, so switching never loses an edit), the rules drawer, the keyboard and
   the question before leaving the page with unsaved edits. */
import { useEffect, useState, type ReactNode } from 'react';
import {
  ActionIcon, AppShell, Badge, Box, Button, Center, Code, Group, Loader, Tabs, Text, Tooltip, useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core';
import { IconAdjustments, IconFileText, IconGitBranch, IconMoon, IconSun } from '@tabler/icons-react';
import {
  anyDirty, dirtyStore, loadState, openRules, RULE_TABS, runAction, setTab, stateStore, TAB_LABELS, tabStore, useStore,
  type TabName,
} from './lib/nav';
import { showError } from './lib/dialogs';
import { SpecTab } from './tabs/SpecTab';
import { PromptsTab } from './tabs/PromptsTab';
import { FlowTab } from './flow/FlowTab';
import { SourcesTab } from './tabs/SourcesTab';
import { GraphTab } from './tabs/GraphTab';
import { RulesDrawer } from './tabs/RulesDrawer';

const PANES: Record<TabName, () => ReactNode> = {
  spec: () => <SpecTab />, prompts: () => <PromptsTab />, flow: () => <FlowTab />,
  sources: () => <SourcesTab />, graph: () => <GraphTab />,
};

function SchemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme('light');
  return (
    <Tooltip label={scheme === 'dark' ? 'Light colours' : 'Dark colours'}>
      <ActionIcon variant="default" size="lg" aria-label="Switch colours"
        onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}>
        {scheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
      </ActionIcon>
    </Tooltip>
  );
}

function Head() {
  const st = useStore(stateStore);
  const { tab } = useStore(tabStore);
  const dirty = useStore(dirtyStore);
  const unsaved = Object.values(dirty).some(Boolean);
  if (!st) return null;
  return (
    <Group h="100%" px="md" gap="md" wrap="nowrap" justify="space-between">
      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        <Text fw={700} size="lg" style={{ whiteSpace: 'nowrap' }}>docpipe edit</Text>
        <Badge size="lg" variant="light" tt="none" style={{ flexShrink: 0, maxWidth: 'none' }}>{st.profile}</Badge>
        <Tooltip label="The spec file of this profile">
          <Group gap={4} wrap="nowrap" visibleFrom="xl"><IconFileText size={16} /><Code>{st.spec}</Code></Group>
        </Tooltip>
        {st.branch && <Group gap={4} wrap="nowrap" visibleFrom="md"><IconGitBranch size={16} /><Text size="sm">{st.branch}</Text></Group>}
        {st.harvest && (
          <Tooltip label={st.harvest}>
            <Text size="sm" c="dimmed" visibleFrom="xl" style={{ whiteSpace: 'nowrap' }}>harvest: {st.harvest_documents == null ? '' : st.harvest_documents + ' documents'}</Text>
          </Tooltip>
        )}
        {st.changed && st.changed.length > 0 && (
          <Tooltip label={<Box style={{ whiteSpace: 'pre' }}>{st.changed.join('\n')}</Box>}>
            <Badge color="orange" variant="light" tt="none" style={{ flexShrink: 0 }}>{st.changed.length} uncommitted</Badge>
          </Tooltip>
        )}
      </Group>
      <Tabs value={tab} onChange={v => v && setTab(v as TabName)} variant="pills" radius="xl" style={{ flexShrink: 0 }}>
        <Tabs.List style={{ flexWrap: 'nowrap' }}>
          {(st.tabs || ['spec']).map(t => (
            <Tabs.Tab key={t} value={t} rightSection={dirty[t] ? <Box className="dp-dot" title="unsaved edits" /> : null}>
              {TAB_LABELS[t] || t}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <Group gap="sm" wrap="nowrap">
        {unsaved ? <Badge color="orange" variant="filled" tt="none" size="lg" style={{ flexShrink: 0 }}>Unsaved edits</Badge> : <Badge color="gray" variant="light" tt="none" size="lg" style={{ flexShrink: 0 }}>All saved</Badge>}
        {RULE_TABS.includes(tab) && (
          <Button variant="default" style={{ flexShrink: 0 }} leftSection={<IconAdjustments size={16} />} onClick={() => openRules(tab)}>Rules</Button>
        )}
        <SchemeToggle />
      </Group>
    </Group>
  );
}

export function App() {
  const st = useStore(stateStore);
  const { tab, rules } = useStore(tabStore);
  const dirty = useStore(dirtyStore);
  const [seen, setSeen] = useState<Set<string>>(new Set(['spec']));
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => { loadState().catch(e => { setFailed(e.message); showError(e); }); }, []);
  useEffect(() => { setSeen(s => (s.has(tab) ? s : new Set([...s, tab]))); }, [tab]);
  useEffect(() => {
    document.title = (Object.values(dirty).some(Boolean) ? '* ' : '') + 'docpipe edit ' + (st ? st.profile : '');
  }, [dirty, st]);
  useEffect(() => {
    const leave = (ev: BeforeUnloadEvent) => { if (anyDirty()) { ev.preventDefault(); ev.returnValue = ''; } };
    const keys = (ev: KeyboardEvent) => {
      if (!(ev.ctrlKey || ev.metaKey)) return;
      const which = ev.key === 's' || ev.key === 'S' ? 'save' : ev.key === 'Enter' ? 'check' : null;
      if (!which) return;
      ev.preventDefault();
      const cur = tabStore.get();
      runAction(cur.rules ? 'rules' : cur.tab, which);
    };
    window.addEventListener('beforeunload', leave);
    window.addEventListener('keydown', keys);
    return () => { window.removeEventListener('beforeunload', leave); window.removeEventListener('keydown', keys); };
  }, []);

  if (!st) {
    return <Center h="100vh">{failed ? <Text c="red">{failed}</Text> : <Loader />}</Center>;
  }
  const tabs = (st.tabs || ['spec']) as TabName[];
  return (
    <AppShell header={{ height: 64 }} padding={0}>
      <AppShell.Header><Head /></AppShell.Header>
      <AppShell.Main className="dp-main">
        {tabs.filter(t => seen.has(t) && PANES[t]).map(t => (
          <Box key={t} className="dp-pane" style={{ display: t === tab ? undefined : 'none' }} data-tab={t}>{PANES[t]()}</Box>
        ))}
      </AppShell.Main>
      <RulesDrawer tab={rules} />
    </AppShell>
  );
}
