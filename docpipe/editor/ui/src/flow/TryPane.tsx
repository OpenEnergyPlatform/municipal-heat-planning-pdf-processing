/* Try: the drawing run on one document with made-up answers (POST /api/flow/try); nothing is sent to a model. */
import { Alert, Button, Group, NativeSelect, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';

export interface TryState { doc: string; pages: string; mode: string }

export function TryPane({ st, set, docs, loadDocs, trying, trial, run }: {
  st: TryState; set: (s: Partial<TryState>) => void; docs: { id: number | string; title: string }[] | null;
  loadDocs: () => void; trying: boolean; trial: any; run: () => void;
}) {
  return (
    <Stack gap="md">
      <Title order={4}>Try</Title>
      <Text size="sm" c="dimmed">Runs the drawing as it stands here on one document, with made-up answers. Nothing is sent to a model; each box then shows how many requests it would ask.</Text>
      <NativeSelect label="document" value={st.doc} onFocus={loadDocs} onMouseDown={loadDocs}
        data={[{ value: '', label: "the plan made up from the spec's examples" },
          ...((docs || []).map(d => ({ value: String(d.id), label: d.id + ' ' + d.title })))]}
        onChange={e => set({ doc: e.currentTarget.value })} />
      <TextInput label="pages" placeholder="e.g. 1-12" w={160} value={st.pages} onChange={e => set({ pages: e.currentTarget.value })}
        description="only with a document" />
      <NativeSelect label="answers" value={st.mode} onChange={e => set({ mode: e.currentTarget.value })}
        data={[{ value: 'nothing', label: "nothing found (a find names its piece's first number, or first word for a field of words; every other answer is empty)" },
          { value: 'first_line', label: 'first line (every answer names the first line shown)' }]} />
      <Group><Button leftSection={<IconPlayerPlay size={16} />} loading={trying} onClick={run}>Try</Button></Group>
      {trial && trial.error && <Alert color="red">{trial.error}</Alert>}
      {trial && !trial.error && (
        <Stack gap="xs">
          <Text size="sm" c="dimmed">{trial.said}</Text>
          <Text size="sm">{trial.requests} requests, nothing sent; {trial.values} values; {trial.pieces} pieces{trial.groups ? ' (' + trial.groups + ' over several passages)' : ''}. Each box shows its count; choose one for its first request.</Text>
          {Object.keys(trial.states || {}).length > 0 && (
            <Table withTableBorder>
              <Table.Thead><Table.Tr><Table.Th>coordinate</Table.Th><Table.Th>states</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {Object.entries(trial.states as Record<string, Record<string, number>>).map(([c, s]) => (
                  <Table.Tr key={c}><Table.Td className="dp-mono">{c}</Table.Td><Table.Td>{Object.entries(s).map(([k, v]) => k + ' ' + v).join(', ')}</Table.Td></Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      )}
    </Stack>
  );
}
