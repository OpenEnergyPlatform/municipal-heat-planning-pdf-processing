/* The Stages tab (owner request 2026-11-19, A1): the stages before the harvest as a picture, from the documents through stages
   1 to 6 to the harvest (GET /api/stages). Each stage says what it does and which command runs it, links to its prompts and
   to its rules (the rules drawer of the tab, opened at its group), and for a stage that writes request logs (4 and 5) how
   many it left and, on demand, what they say (POST /api/stages/measured). */
import { useEffect, useReducer, useRef } from 'react';
import { Alert, Anchor, Badge, Box, Button, Code, Group, Loader, Paper, ScrollArea, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { IconAdjustments, IconArrowDown, IconChartBar } from '@tabler/icons-react';
import { api } from '../lib/api';
import { openPrompt, openRules, request, setTab } from '../lib/nav';
import { rich, t, tn, tr } from '../lib/i18n';
import { Muted } from '../components/Bits';

interface Measured { running?: boolean; res?: any; err?: string }

export function StagesTab() {
  const R = useRef({ data: null as any, err: null as string | null, measured: {} as Record<string, Measured> });
  const [, touch] = useReducer((x: number) => x + 1, 0);
  const S = R.current;

  async function load() {
    try { S.data = await api('GET', '/api/stages'); S.err = null; }
    catch (e) { S.err = (e as Error).message; }
    touch();
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function measure(key: string) {
    S.measured[key] = { running: true }; touch();
    try { S.measured[key] = { res: await api('POST', '/api/stages/measured', { stage: key }) }; }
    catch (e) { S.measured[key] = { err: (e as Error).message }; }
    touch();
  }

  /* the rules drawer of the tab, opened at the first rule of the stage's group */
  const rulesOf = (stage: any) => { openRules('stages'); if (stage.first_rule) request('rules', { name: stage.first_rule }); };

  if (S.err) return <Alert color="red" m="md">{S.err}</Alert>;
  if (!S.data) return <Group justify="center" p="xl"><Loader /></Group>;
  const d = S.data;
  return (
    <ScrollArea style={{ flex: 1 }} type="auto">
      <Stack p="md" gap={4} maw={980} mx="auto">
        <Title order={3}>{t('The stages before the harvest')}</Title>
        <Muted>{t('Each stage reads what the stage before it wrote for every document and writes its own beside it. A changed rule of a stage takes effect when that stage runs again; what it wrote before stays until then.')}</Muted>
        <Ends one={d.before} />
        {(d.stages || []).map((stage: any) => (
          <Stack key={stage.key} gap={4}>
            <Arrow />
            <Paper withBorder radius="md" p="md" className="dp-stage">
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <Stack gap={4} style={{ minWidth: 0 }}>
                  <Group gap="xs">
                    <Badge size="lg" variant="filled" circle>{stage.n}</Badge>
                    <Text fw={700} size="lg">{rich(tr(stage.name))}</Text>
                    <Code>{'docpipe ' + stage.command}</Code>
                  </Group>
                  <Text size="sm">{rich(tr(stage.says))}</Text>
                </Stack>
                <Button variant="default" leftSection={<IconAdjustments size={16} />} onClick={() => rulesOf(stage)} disabled={!stage.rules} style={{ flexShrink: 0 }}>
                  {tn(stage.rules, '{n} rule', '{n} rules')}
                </Button>
              </Group>
              <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" mt="sm">
                <Stack gap={4}>
                  <Text size="sm" fw={600}>{t('Prompts')}</Text>
                  {stage.prompts.length
                    ? <Group gap={6}>{stage.prompts.map((id: string) => <Anchor key={id} component="button" type="button" size="sm" onClick={() => openPrompt(id)}><Code>{id}</Code></Anchor>)}</Group>
                    : <Muted>{t('This stage asks no model.')}</Muted>}
                  {stage.own_rules > 0 && <Muted>{tn(stage.own_rules, 'The profile sets {n} of its rules itself.', 'The profile sets {n} of its rules itself.')}</Muted>}
                </Stack>
                {stage.log && <LogBox stage={stage} m={S.measured[stage.key]} onMeasure={() => measure(stage.key)} />}
              </SimpleGrid>
            </Paper>
          </Stack>
        ))}
        <Arrow />
        <Ends one={d.after} link={() => setTab('flow')} />
      </Stack>
    </ScrollArea>
  );
}

function Arrow() {
  return <Group justify="center" c="dimmed"><IconArrowDown size={20} /></Group>;
}

function Ends({ one, link }: { one: any; link?: () => void }) {
  return (
    <Paper withBorder radius="md" p="sm" bg="var(--mantine-color-default-hover)">
      <Group gap="xs">
        <Text fw={700}>{rich(tr(one.name))}</Text>
        <Code>{'docpipe ' + one.command}</Code>
        {link && <Anchor component="button" type="button" size="sm" onClick={link}>{t('Open the Flow tab')}</Anchor>}
      </Group>
      <Text size="sm">{rich(tr(one.says))}</Text>
    </Paper>
  );
}

/* the request logs a stage left, and what they say once counted */
function LogBox({ stage, m, onMeasure }: { stage: any; m?: Measured; onMeasure: () => void }) {
  return (
    <Stack gap={4}>
      <Text size="sm" fw={600}>{t('Request logs')}</Text>
      {stage.logs
        ? <Muted>{tn(stage.logs, 'One document has a request log of this stage; its requests are shown with the prompts.', '{n} documents have a request log of this stage; their requests are shown with the prompts.')}</Muted>
        : <Muted>{t('The folders of the documents hold no request log of this stage yet. A run of the stage writes one beside what it writes for each document.')}</Muted>}
      {stage.logs > 0 && (
        <Box>
          <Button size="xs" variant="light" leftSection={<IconChartBar size={14} />} loading={!!(m && m.running)} onClick={onMeasure}>
            {t('Count what the logs say')}
          </Button>
        </Box>
      )}
      {m && m.err && <Alert color="red">{m.err}</Alert>}
      {m && m.res && (
        <Stack gap={2}>
          <Muted>{tn(m.res.requests, '{n} request in {logs} logs.', '{n} requests in {logs} logs.', { logs: m.res.logs })}</Muted>
          {(m.res.says || []).map((s: string, i: number) => <Text key={i} size="sm">{rich(tr(s))}</Text>)}
        </Stack>
      )}
    </Stack>
  );
}
