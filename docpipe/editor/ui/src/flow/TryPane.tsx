/* Dry run: the flow run on one document with placeholder answers (POST /api/flow/try); nothing is sent to a model. */
import { Alert, Button, Group, NativeSelect, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';
import { rich, t, tr, useLang } from '../lib/i18n';
import type { Subject } from './model';

export interface TryState { doc: string; pages: string; mode: string }

export function TryPane({ st, set, docs, loadDocs, trying, trial, run, subjects }: {
  st: TryState; set: (s: Partial<TryState>) => void; docs: { id: number | string; title: string }[] | null;
  loadDocs: () => void; trying: boolean; trial: any; run: () => void; subjects: Subject[];
}) {
  useLang();
  /* the words of the states of a dimension: the condition property "state" of the subject "coordinate" */
  const stateProp = (subjects.find(x => x.name === 'coordinate')?.props || []).find(p => p.name === 'state');
  const stateWord = (code: string) => tr((stateProp?.words || {})[code] || code);
  return (
    <Stack gap="md">
      <Title order={4}>{t('Dry run')}</Title>
      <Text size="sm" c="dimmed">{t('A dry run goes through the flow as it stands here on one document and answers every request with a placeholder. Nothing is sent to a model. Afterwards each step shows how many requests it would send. To change it: choose the document, its pages and the kind of placeholder answers below.')}</Text>
      <NativeSelect label={t('document')} value={st.doc} onFocus={loadDocs} onMouseDown={loadDocs}
        data={[{ value: '', label: t("the document made up from the spec's examples") },
          ...((docs || []).map(d => ({ value: String(d.id), label: d.id + ' ' + d.title })))]}
        onChange={e => set({ doc: e.currentTarget.value })} />
      <TextInput label={t('pages')} placeholder={t('e.g. 1-12')} w={160} value={st.pages} onChange={e => set({ pages: e.currentTarget.value })}
        description={t('only with a document')} />
      <NativeSelect label={t('answers')} value={st.mode} onChange={e => set({ mode: e.currentTarget.value })}
        data={[{ value: 'nothing', label: t("nothing found (a find names its chunk's first number, or first word for a field of words; every other answer is empty)") },
          { value: 'first_line', label: t('first line (every answer names the first line shown)') }]} />
      <Group><Button leftSection={<IconPlayerPlay size={16} />} loading={trying} onClick={run}>{t('Dry run')}</Button></Group>
      {trial && trial.error && <Alert color="red">{trial.error}</Alert>}
      {trial && !trial.error && (
        <Stack gap="xs">
          <Text size="sm" c="dimmed">{rich(tr(trial.said))}</Text>
          <Text size="sm">{trial.groups
            ? t('The dry run would send {requests} requests and nothing was sent. It found {values} values in {chunks} chunks, and {groups} of these chunks span several sections, tables or figures. Each step shows its own count, and a step you choose shows its first request.', { requests: trial.requests, values: trial.values, chunks: trial.pieces, groups: trial.groups })
            : t('The dry run would send {requests} requests and nothing was sent. It found {values} values in {chunks} chunks. Each step shows its own count, and a step you choose shows its first request.', { requests: trial.requests, values: trial.values, chunks: trial.pieces })}</Text>
          {Object.keys(trial.states || {}).length > 0 && (
            <Table withTableBorder>
              <Table.Thead><Table.Tr><Table.Th>{t('dimension')}</Table.Th><Table.Th>{t('states')}</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {Object.entries(trial.states as Record<string, Record<string, number>>).map(([c, s]) => (
                  <Table.Tr key={c}><Table.Td className="dp-mono">{c}</Table.Td><Table.Td>{Object.entries(s).map(([k, v]) => stateWord(k) + ' ' + v).join(', ')}</Table.Td></Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      )}
    </Stack>
  );
}
