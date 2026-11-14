/* Dry run of the chat: one question asked of the drawing on the page (POST /api/chat/try). Every request is answered with
   a made-up answer of its own form and nothing of the plan or the question is sent: no model, no embedder, no reranker,
   no sandbox. Shows each step that ran with what it gave, each request with the step that asked it, and the answer the
   chat page would show. */
import { Accordion, Alert, Anchor, Button, Group, NativeSelect, Stack, Switch, Table, Text, TextInput, Title } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';
import { rich, t, trCheck, useLang } from '../lib/i18n';

export interface ChatTryState { question: string; route: string; as_json: boolean; mode: string; doc: string }

/* a route of the chat in words; a route of the drawing's own is called by its name */
const routeWord = (r: string): string => ({
  auto: t('automatic (as the drawing decides)'), harvest: t('the harvest'), graph: t('the graph'), documents: t('the documents'),
} as Record<string, string>)[r] || r;

export function ChatTryPane({ st, set, routes, db, docs, loadDocs, trying, trial, run, onStep }: {
  st: ChatTryState; set: (s: Partial<ChatTryState>) => void; routes: string[]; db: boolean;
  docs: { id: number | string; title: string }[] | null; loadDocs: () => void; trying: boolean; trial: any; run: () => void;
  onStep: (id: string) => void;
}) {
  useLang();
  const shown = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v));
  return (
    <Stack gap="md">
      <Title order={4}>{t('Dry run')}</Title>
      <Text size="sm" c="dimmed">{t('A dry run asks the drawing as it stands here one question. Every request gets a made-up answer of its own form, and nothing of the plan or the question is sent: no model, no embedder, no reranker and no sandbox is asked. The search gives the passages of the document in their order. Afterwards each step that ran shows how many requests it asked; a step you choose shows what it gave and its requests.')}</Text>
      <TextInput label={t('question')} placeholder={t('the question, as a user asks it in the chat')} value={st.question}
        onChange={e => set({ question: e.currentTarget.value })} />
      <NativeSelect label={t('route')} value={st.route} onChange={e => set({ route: e.currentTarget.value })}
        data={['auto', ...routes].map(r => ({ value: r, label: routeWord(r) }))} />
      <Switch label={t('answer as JSON')} checked={st.as_json} onChange={e => set({ as_json: e.currentTarget.checked })} />
      {db && (
        <NativeSelect label={t('document')} value={st.doc} onFocus={loadDocs} onMouseDown={loadDocs}
          data={[{ value: '', label: t("the document made up from the spec's examples") },
            ...((docs || []).map(d => ({ value: String(d.id), label: d.id + ' ' + d.title })))]}
          onChange={e => set({ doc: e.currentTarget.value })} />
      )}
      <NativeSelect label={t('answers')} value={st.mode} onChange={e => set({ mode: e.currentTarget.value })}
        data={[{ value: 'nothing', label: t('nothing (every answer of its form, each part empty)') },
          { value: 'example', label: t('example (every answer the example of its form)') }]} />
      <Group><Button leftSection={<IconPlayerPlay size={16} />} loading={trying} disabled={!st.question.trim()} onClick={run}>{t('Dry run')}</Button></Group>
      {trial && trial.error && <Alert color="red">{rich(trCheck(String(trial.error)))}</Alert>}
      {trial && trial.steps && (
        <Stack gap="xs">
          <Text size="sm">{t('{steps} steps ran and asked {requests} requests; nothing was sent. The search had {passages} passages.', { steps: trial.steps.length, requests: (trial.requests || []).length, passages: trial.passages })}</Text>
          {trial.message && (
            <Stack gap={4}>
              <Text size="sm" fw={600}>{t('What the chat page would show')}</Text>
              <pre className="fl-pre">{shown(trial.message.content) || t('(no text)')}</pre>
              {(trial.message.extra || []).map((x: { name: string; value: unknown }, i: number) => (
                <pre key={i} className="fl-pre">{x.name + ': ' + JSON.stringify(x.value, null, 2)}</pre>
              ))}
            </Stack>
          )}
          <Table withTableBorder>
            <Table.Thead><Table.Tr><Table.Th>{t('step')}</Table.Th><Table.Th>{t('requests')}</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {(trial.steps as { id: string }[]).map((s, i) => (
                <Table.Tr key={s.id + i}>
                  <Table.Td><Anchor component="button" type="button" className="dp-mono" onClick={() => onStep(s.id)}>{s.id}</Anchor></Table.Td>
                  <Table.Td>{(trial.boxes && trial.boxes[s.id] ? trial.boxes[s.id].requests : 0)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {(trial.requests || []).length > 0 && (
            <Accordion variant="contained">
              {(trial.requests as { step: string; request: string; prompt: string; reply: unknown }[]).map((r, i) => (
                <Accordion.Item key={i} value={'r' + i}>
                  <Accordion.Control>{t('{step}: {kind}', { step: r.step || '?', kind: r.request })}</Accordion.Control>
                  <Accordion.Panel>
                    <Text size="xs" fw={600}>{t('message')}</Text>
                    <pre className="fl-pre">{r.prompt}</pre>
                    <Text size="xs" fw={600}>{t('made-up answer')}</Text>
                    <pre className="fl-pre">{JSON.stringify(r.reply, null, 2)}</pre>
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          )}
        </Stack>
      )}
    </Stack>
  );
}
