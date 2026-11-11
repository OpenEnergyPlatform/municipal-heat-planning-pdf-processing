/* The frame of the page: the head with the profile, its files and the tabs, the tabs themselves (each loaded the first
   time it opens and kept while the page is open, so switching never loses an edit), the rules drawer, the keyboard and
   the question before leaving the page with unsaved edits. */
import { useEffect, useState, type ReactNode } from 'react';
import {
  ActionIcon, AppShell, Badge, Box, Button, Center, Code, Group, Loader, SegmentedControl, Tabs, Text, Tooltip,
  useComputedColorScheme, useMantineColorScheme,
} from '@mantine/core';
import { LANGS, setLang, t, tn, useLang, type Lang } from './lib/i18n';
import { IconAdjustments, IconFileText, IconGitBranch, IconMoon, IconSun } from '@tabler/icons-react';
import {
  anyDirty, dirtyStore, loadState, openRules, RULE_TABS, runAction, setTab, stateStore, tabLabel, tabStore, useStore,
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
    <Tooltip label={scheme === 'dark' ? t('Light colours') : t('Dark colours')}>
      <ActionIcon variant="default" size="lg" aria-label={t('Switch colours')}
        onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}>
        {scheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
      </ActionIcon>
    </Tooltip>
  );
}

/* "Deutsch | English": the language of every text the page writes and of every explanation the server sends */
function LangSwitch() {
  const lang = useLang();
  return (
    <Tooltip label={t('Language of the page')}>
      <SegmentedControl size="xs" value={lang} data={LANGS} aria-label={t('Language of the page')}
        onChange={v => setLang(v as Lang)} />
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
        <Text fw={700} size="lg" style={{ whiteSpace: 'nowrap' }}>docpipe edit</Text>{/* i18n-ignore: the program's name */}
        <Badge size="lg" variant="light" tt="none" style={{ flexShrink: 0, maxWidth: 'none' }}>{st.profile}</Badge>
        <Tooltip label={t('The spec file of this profile')}>
          <Group gap={4} wrap="nowrap" visibleFrom="xl"><IconFileText size={16} /><Code>{st.spec}</Code></Group>
        </Tooltip>
        {st.branch && <Group gap={4} wrap="nowrap" visibleFrom="md"><IconGitBranch size={16} /><Text size="sm">{st.branch}</Text></Group>}
        {st.harvest && (
          <Tooltip label={st.harvest}>
            <Text size="sm" c="dimmed" visibleFrom="xl" style={{ whiteSpace: 'nowrap' }}>{st.harvest_documents == null ? t('harvest') : t('harvest: {documents}', { documents: tn(st.harvest_documents, '{n} document', '{n} documents') })}</Text>
          </Tooltip>
        )}
        {st.changed && st.changed.length > 0 && (
          <Tooltip label={<Box style={{ whiteSpace: 'pre' }}>{st.changed.join('\n')}</Box>}>
            <Badge color="orange" variant="light" tt="none" style={{ flexShrink: 0 }}>{t('{n} uncommitted', { n: st.changed.length })}</Badge>
          </Tooltip>
        )}
      </Group>
      <Tabs value={tab} onChange={v => v && setTab(v as TabName)} variant="pills" radius="xl" style={{ flexShrink: 0 }}>
        <Tabs.List style={{ flexWrap: 'nowrap' }}>
          {(st.tabs || ['spec']).map(name => (
            <Tabs.Tab key={name} value={name} rightSection={dirty[name] ? <Box className="dp-dot" title={t('Unsaved edits')} /> : null}>
              {tabLabel(name)}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <Group gap="sm" wrap="nowrap">
        {unsaved ? <Badge color="orange" variant="filled" tt="none" size="lg" style={{ flexShrink: 0 }}>{t('Unsaved edits')}</Badge> : <Badge color="gray" variant="light" tt="none" size="lg" style={{ flexShrink: 0 }}>{t('All saved')}</Badge>}
        {RULE_TABS.includes(tab) && (
          <Button variant="default" style={{ flexShrink: 0 }} leftSection={<IconAdjustments size={16} />} onClick={() => openRules(tab)}>{t('Rules')}</Button>
        )}
        <LangSwitch />
        <SchemeToggle />
      </Group>
    </Group>
  );
}

export function App() {
  useLang();   // the whole page draws anew in the other language; what is being edited stays
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
        {tabs.filter(name => seen.has(name) && PANES[name]).map(name => (
          <Box key={name} className="dp-pane" style={{ display: name === tab ? undefined : 'none' }} data-tab={name}>{PANES[name]()}</Box>
        ))}
      </AppShell.Main>
      <RulesDrawer tab={rules} />
    </AppShell>
  );
}
