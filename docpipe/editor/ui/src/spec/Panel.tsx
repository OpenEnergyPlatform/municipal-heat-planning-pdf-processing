/* What an edit costs: the result of the last check or save, above the form. */
import { useState } from 'react';
import { Alert, Anchor, Badge, Box, Button, Code, Collapse, Group, List, Paper, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconChevronDown, IconChevronRight, IconCircleCheck } from '@tabler/icons-react';
import { Diff, Help } from '../components/Bits';
import { useStore } from '../lib/nav';
import { doGenerate, doSave, goToError, meta, reload, S } from './state';

const ids = new WeakMap<object, number>();
let nextId = 0;
const resultId = (R: object) => { if (!ids.has(R)) ids.set(R, ++nextId); return ids.get(R); };

const STATE_COLOR: Record<string, string> = { changed: 'yellow', new: 'teal', gone: 'red' };

export function summary(): { color: string; text: string } | null {
  const R = S.result;
  if (!R) return null;
  const r = R.r;
  if (R.source === 'save' && r.saved) return { color: 'teal', text: 'saved' };
  if (R.source === 'save') return { color: 'red', text: 'not saved: ' + (r.reason || '') };
  return r.ok ? { color: 'teal', text: 'ok' } : { color: 'red', text: 'refused' };
}

const Removed = ({ r }: { r: any }) => <List size="sm">{(r.removed || []).map((x: string, i: number) => <List.Item key={i}>{x}</List.Item>)}</List>;

function Docs({ docs }: { docs: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Box>
      <Anchor component="button" type="button" size="sm" onClick={() => setOpen(!open)}>{docs.length + ' documents'}</Anchor>
      <Collapse expanded={open}><Box mah={140} style={{ overflow: 'auto' }}>{docs.map((d, i) => <Text key={i} size="sm" ff="monospace">{d}</Text>)}</Box></Collapse>
    </Box>
  );
}

function Body() {
  const R = S.result!;
  const r = R.r;
  const ch: any[] = r.changes || [];
  const ln = r.lines || {};
  const diff: string = r.diff || '';
  const [showDiff, setShowDiff] = useState(!!diff);
  const [showCh, setShowCh] = useState(ch.length > 0);
  const out = [];
  if (S.stale) out.push(<Alert key="stale" color="yellow" icon={<IconAlertTriangle />}>The data was edited after this result.</Alert>);

  if (R.source === 'save') {
    if (r.saved) {
      out.push(
        <Alert key="saved" color="teal" icon={<IconCircleCheck />}>
          <Group gap="sm">Saved.<Button size="xs" variant="white" color="teal" disabled={S.busy} onClick={doGenerate}>Regenerate schema and docs</Button></Group>
        </Alert>);
      if (S.generate) {
        const g = S.generate;
        out.push(
          <Alert key="gen" color={g.ok ? 'teal' : 'red'}>
            {g.ok ? 'Regenerated.' : 'Regeneration failed.'} Changed files: {(g.changed || []).length ? (g.changed as string[]).map(f => <Code key={f} mr={6}>{f}</Code>) : 'none'}
            {g.output ? <Box component="pre" m={0} mt={6} style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{g.output}</Box> : null}
          </Alert>);
      }
    } else if (r.reason === 'moved') {
      out.push(
        <Alert key="moved" color="red" icon={<IconAlertTriangle />} title="The file changed on disk">
          <Stack gap="xs"><Text size="sm">{r.message || 'The file on disk is not the one this page loaded.'}</Text>
            <Box><Button size="xs" variant="white" color="red" onClick={() => reload()}>Reload from disk</Button></Box></Stack>
        </Alert>);
      return <Stack gap="xs">{out}</Stack>;
    } else if (r.reason === 'confirm') {
      out.push(
        <Alert key="confirm" color="orange" icon={<IconAlertTriangle />} title="This edit removes something. Nothing is written yet.">
          <Stack gap="xs"><Removed r={r} /><Text size="sm">What it costs: see the changed questions below.</Text>
            <Box><Button color="red" disabled={S.busy} onClick={() => doSave(true)}>Remove and save</Button></Box></Stack>
        </Alert>);
    } else if (r.reason === 'check') {
      out.push(<Alert key="notsaved" color="red">Not saved: the loader refused the spec.</Alert>);
    }
  }
  if (r.error) {
    out.push(
      <Alert key="err" color="red" icon={<IconAlertTriangle />} title="The loader refuses the spec">
        {r.error.message || ''} {r.error.where ? <Anchor component="button" type="button" onClick={() => goToError(r.error)}>{r.error.where}</Anchor> : null}
      </Alert>);
  } else if (R.source === 'check') {
    out.push(<Alert key="ok" color="teal" icon={<IconCircleCheck />}>The loader accepts the spec.</Alert>);
  }
  if (!(R.source === 'save' && r.reason === 'confirm') && r.removed && r.removed.length) {
    out.push(<Alert key="removed" color="orange" title="Removed by this edit"><Removed r={r} /></Alert>);
  }
  out.push(
    <Box key="ch">
      <Anchor component="button" type="button" fw={600} onClick={() => setShowCh(!showCh)}>
        {showCh ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />} Changed questions ({ch.length})
      </Anchor>
      <Collapse expanded={showCh}>
        <Stack gap="xs" mt={6}>
          {r.documents_note ? <Help text={r.documents_note} /> : null}
          {ch.length ? null : <Text size="sm" c="dimmed">{r.error ? 'Not said while the loader refuses the spec.' : 'No question of the run changes.'}</Text>}
          {ch.map((c, i) => (
            <Paper key={i} withBorder p="xs">
              <Group gap={6}><Badge color={STATE_COLOR[c.state] || 'gray'}>{c.state}</Badge><Code>{c.key}</Code><Text size="sm" c="dimmed">{c.effect}</Text></Group>
              <Text size="sm">{c.text}</Text>
              {c.documents ? <Docs docs={c.documents} /> : null}
            </Paper>
          ))}
        </Stack>
      </Collapse>
    </Box>,
    <Box key="diff">
      <Anchor component="button" type="button" fw={600} onClick={() => setShowDiff(!showDiff)}>
        {showDiff ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />} Diff{' '}
        <Badge color="teal" variant="light">{'+' + (ln.added || 0) + ' lines'}</Badge>{' '}<Badge color="red" variant="light">{'-' + (ln.removed || 0) + ' lines'}</Badge>
      </Anchor>
      <Collapse expanded={showDiff}><Box mt={6}>{diff ? <Diff text={diff} /> : <Text size="sm" c="dimmed">The file does not change.</Text>}</Box></Collapse>
    </Box>,
  );
  return <Stack gap="xs">{out}</Stack>;
}

export function ResultPanel() {
  useStore(meta);
  const [, redraw] = useState(0);
  const R = S.result;
  const sm = summary();
  const toggle = () => { S.panelOpen = !S.panelOpen; redraw(x => x + 1); };
  return (
    <Paper withBorder radius="md" mx="md" mt="xs" p="xs">
      <Group gap="xs" style={{ cursor: 'pointer' }} onClick={toggle}>
        {S.panelOpen ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
        <Text fw={600}>{R ? (R.source === 'save' ? 'Result of the last save' : 'Result of the last check') : 'Check result'}</Text>
        {sm ? <Badge color={sm.color}>{sm.text}</Badge> : <Text size="sm" c="dimmed">Press Check (Ctrl+Enter) to see what an edit costs.</Text>}
        {R && S.stale ? <Badge color="yellow" variant="light">edited since</Badge> : null}
        {R && R.r.changes ? <Text size="sm" c="dimmed">{R.r.changes.length + ' changed questions' + (R.r.removed && R.r.removed.length ? ', ' + R.r.removed.length + ' removed' : '')}</Text> : null}
      </Group>
      {S.panelOpen && R ? <Box className="dp-spec-panel" mt="xs"><Body key={resultId(R)} /></Box> : null}
    </Paper>
  );
}
