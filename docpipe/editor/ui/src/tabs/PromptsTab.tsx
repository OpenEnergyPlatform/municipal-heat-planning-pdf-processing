/* The Prompts tab: the list of prompts and sentences on the left, the editor in the middle, the recorded requests of a
   trace with the chat and Try on the right. State and requests are in ../prompts/store.ts. */
import { useEffect } from 'react';
import { Alert, Badge, Group, Loader, NavLink, Stack, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { setDirty, useRequests, useStore, useTabActions } from '../lib/nav';
import { PhrasesEditor, PromptEditor } from '../prompts/Editors';
import { RightColumn } from '../prompts/Requests';
import { edDirty, phDirty, stageOrder } from '../prompts/logic';
import { P, actCheck, actSave, bump, currentX, loadPrompts, promptsDirty, selectModule, selectPrompt, tick } from '../prompts/store';
import '../prompts/prompts.css';

function ListColumn() {
  const L = P.list;
  if (P.loadErr) return <Alert color="red">{P.loadErr}</Alert>;
  if (!L) return <Group gap="xs"><Loader size="xs" /><Text size="sm" c="dimmed">Loading…</Text></Group>;
  const words = P.filter.toLowerCase().split(/\s+/).filter(Boolean);
  const match = (...t: string[]) => { const hay = t.join('\n').toLowerCase(); return words.every(w => hay.includes(w)); };
  const prompts: any[] = (L.prompts || []).filter((p: any) => match(p.id, p.owner || ''));
  const stages = [...new Set(prompts.map(p => p.stage as string))].sort(stageOrder);
  const sel = P.sel;
  return (
    <Stack gap={2}>
      <TextInput placeholder="Filter" leftSection={<IconSearch size={16} />} spellCheck={false} value={P.filter}
        onChange={e => { P.filter = e.currentTarget.value; bump(); }} mb="xs" />
      <Text fw={700}>Prompts ({prompts.length})</Text>
      {!prompts.length && <Text size="sm" c="dimmed">{(L.prompts || []).length ? 'No prompt matches the filter.' : 'This profile has no prompt files.'}</Text>}
      {stages.map(st => (
        <div key={st}>
          <div className="pr-stage">{st}</div>
          {prompts.filter(p => p.stage === st).map(p => {
            const E = P.eds.get(p.id);
            return (
              <NavLink key={p.id} component="button" type="button" active={!!sel && sel.t === 'prompt' && sel.id === p.id}
                label={p.name} description={p.own ? undefined : 'inherited from ' + p.owner} onClick={() => selectPrompt(p.id)}
                rightSection={
                  <Group gap={4} wrap="nowrap">
                    {(p.kinds || []).length > 0 && <Badge size="xs" variant="light" color="teal" title="Recorded requests can be shown for this prompt">requests</Badge>}
                    {E && edDirty(E) && <Badge size="xs" variant="light" color="orange">unsaved</Badge>}
                  </Group>} />
            );
          })}
        </div>
      ))}
      <div className="pr-stage">Sentences</div>
      {(L.modules || []).filter((m: string) => match(m, 'sentences')).map((m: string) => {
        const X = P.phs.get(m);
        return (
          <NavLink key={m} component="button" type="button" active={!!sel && sel.t === 'phrases' && sel.module === m} label={m} onClick={() => selectModule(m)}
            rightSection={X && phDirty(X) ? <Badge size="xs" variant="light" color="orange">unsaved</Badge> : null} />
        );
      })}
    </Stack>
  );
}

function MainColumn() {
  if (!P.list) return null;
  if (!P.sel) return <Text c="dimmed">Pick a prompt or the sentences of a module on the left.</Text>;
  const X = currentX();
  if (!X) return P.selErr ? <Alert color="red">{P.selErr}</Alert> : <Group gap="xs"><Loader size="xs" /><Text size="sm" c="dimmed">Loading…</Text></Group>;
  return X.kind === 'prompt' ? <PromptEditor key={X.id} E={X} /> : <PhrasesEditor key={X.module} X={X} redraw={bump} />;
}

export function PromptsTab() {
  const t = useStore(tick);
  useEffect(() => { loadPrompts(); }, []);
  const dirty = promptsDirty();
  useEffect(() => { setDirty('prompts', dirty); }, [t, dirty]);
  useTabActions('prompts', { check: () => actCheck(currentX()), save: () => actSave(currentX(), false) });
  useRequests('prompts', P.loaded, ({ id }) => selectPrompt(id));
  return (
    <div className="pr-cols">
      <div className="pr-col pr-left"><ListColumn /></div>
      <div className="pr-col pr-main"><MainColumn /></div>
      <div className="pr-col pr-right"><RightColumn /></div>
    </div>
  );
}
