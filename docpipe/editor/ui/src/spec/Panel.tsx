/* What an edit costs: the result of the last check or save, above the form. */
import { useState } from 'react';
import { Alert, Anchor, Badge, Box, Button, Code, Collapse, Group, List, Paper, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconChevronDown, IconChevronRight, IconCircleCheck } from '@tabler/icons-react';
import { Diff, Help } from '../components/Bits';
import { useStore } from '../lib/nav';
import { rich, t, tn, tr } from '../lib/i18n';
import { doGenerate, doSave, goToError, meta, reload, S } from './state';

const ids = new WeakMap<object, number>();
let nextId = 0;
const resultId = (R: object) => { if (!ids.has(R)) ids.set(R, ++nextId); return ids.get(R); };

const STATE_COLOR: Record<string, string> = { changed: 'yellow', new: 'teal', gone: 'red' };
const stateWord = (s: string) => ({ changed: t('changed'), new: t('new'), gone: t('gone') } as Record<string, string>)[s] || s;

export function summary(): { color: string; text: string } | null {
  const R = S.result;
  if (!R) return null;
  const r = R.r;
  if (R.source === 'save' && r.saved) return { color: 'teal', text: t('saved') };
  if (R.source === 'save') return { color: 'red', text: t('not saved: {reason}', { reason: r.reason || '' }) };
  return r.ok ? { color: 'teal', text: t('ok') } : { color: 'red', text: t('refused') };
}

const Removed = ({ r }: { r: any }) => <List size="sm">{(r.removed || []).map((x: string, i: number) => <List.Item key={i}>{x}</List.Item>)}</List>;

function Docs({ docs }: { docs: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Box>
      <Anchor component="button" type="button" size="sm" onClick={() => setOpen(!open)}>{tn(docs.length, '{n} document', '{n} documents')}</Anchor>
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
  if (S.stale) out.push(<Alert key="stale" color="yellow" icon={<IconAlertTriangle />}>{t('The data was edited after this result.')}</Alert>);

  if (R.source === 'save') {
    if (r.saved) {
      out.push(
        <Alert key="saved" color="teal" icon={<IconCircleCheck />}>
          <Group gap="sm">{t('Saved.')}<Button size="xs" variant="white" color="teal" disabled={S.busy} onClick={doGenerate}>{t('Regenerate schema and docs')}</Button></Group>
        </Alert>);
      if (S.generate) {
        const g = S.generate;
        out.push(
          <Alert key="gen" color={g.ok ? 'teal' : 'red'}>
            {g.ok ? t('Regenerated.') : t('Regeneration failed.')} {t('Changed files:')} {(g.changed || []).length ? (g.changed as string[]).map(f => <Code key={f} mr={6}>{f}</Code>) : t('none')}
            {g.output ? <Box component="pre" m={0} mt={6} style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{g.output}</Box> : null}
          </Alert>);
      }
    } else if (r.reason === 'moved') {
      out.push(
        <Alert key="moved" color="red" icon={<IconAlertTriangle />} title={t('The file changed on disk')}>
          <Stack gap="xs"><Text size="sm">{r.message || t('The file on disk is not the one this page loaded.')}</Text>
            <Box><Button size="xs" variant="white" color="red" onClick={() => reload()}>{t('Reload from disk')}</Button></Box></Stack>
        </Alert>);
      return <Stack gap="xs">{out}</Stack>;
    } else if (r.reason === 'confirm') {
      out.push(
        <Alert key="confirm" color="orange" icon={<IconAlertTriangle />} title={t('This edit removes something. Nothing is written yet.')}>
          <Stack gap="xs"><Removed r={r} /><Text size="sm">{t('What the change costs is shown below, in the questions that it changes.')}</Text>
            <Box><Button color="red" disabled={S.busy} onClick={() => doSave(true)}>{t('Remove and save')}</Button></Box></Stack>
        </Alert>);
    } else if (r.reason === 'check') {
      out.push(<Alert key="notsaved" color="red">{t('Not saved: the program that reads the spec refused it.')}</Alert>);
    }
  }
  if (r.error) {
    out.push(
      <Alert key="err" color="red" icon={<IconAlertTriangle />} title={t('The program that reads the spec refuses it')}>
        {r.error.message || ''} {r.error.where ? <Anchor component="button" type="button" onClick={() => goToError(r.error)}>{r.error.where}</Anchor> : null}
      </Alert>);
  } else if (R.source === 'check') {
    out.push(<Alert key="ok" color="teal" icon={<IconCircleCheck />}>{t('The program that reads the spec accepts it.')}</Alert>);
  }
  if (!(R.source === 'save' && r.reason === 'confirm') && r.removed && r.removed.length) {
    out.push(<Alert key="removed" color="orange" title={t('Removed by this edit')}><Removed r={r} /></Alert>);
  }
  out.push(
    <Box key="ch">
      <Anchor component="button" type="button" fw={600} onClick={() => setShowCh(!showCh)}>
        {showCh ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />} {t('Changed questions ({n})', { n: ch.length })}
      </Anchor>
      <Collapse expanded={showCh}>
        <Stack gap="xs" mt={6}>
          {r.documents_note ? <Help text={tr(r.documents_note)} /> : null}
          {ch.length ? null : <Text size="sm" c="dimmed">{r.error ? t('The changed questions are not shown, because the Spec in this state is refused. Fix the problem named above, then check again.') : t('No question of the run changes, so no document has to be read again.')}</Text>}
          {ch.map((c, i) => (
            <Paper key={i} withBorder p="xs">
              <Group gap={6}><Badge color={STATE_COLOR[c.state] || 'gray'}>{stateWord(c.state)}</Badge><Code>{c.key}</Code><Text size="sm" c="dimmed">{rich(tr(c.effect))}</Text></Group>
              <Text size="sm">{c.text}</Text>
              {c.documents ? <Docs docs={c.documents} /> : null}
            </Paper>
          ))}
        </Stack>
      </Collapse>
    </Box>,
    <Box key="diff">
      <Anchor component="button" type="button" fw={600} onClick={() => setShowDiff(!showDiff)}>
        {showDiff ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />} {t('Diff')}{' '}
        <Badge color="teal" variant="light">{tn(ln.added || 0, '+{n} line', '+{n} lines')}</Badge>{' '}<Badge color="red" variant="light">{tn(ln.removed || 0, '-{n} line', '-{n} lines')}</Badge>
      </Anchor>
      <Collapse expanded={showDiff}><Box mt={6}>{diff ? <Diff text={diff} /> : <Text size="sm" c="dimmed">{t('The file does not change.')}</Text>}</Box></Collapse>
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
        <Text fw={600}>{R ? (R.source === 'save' ? t('Result of the last save') : t('Result of the last check')) : t('Check result')}</Text>
        {sm ? <Badge color={sm.color}>{sm.text}</Badge> : <Text size="sm" c="dimmed">{t('Press Check (Ctrl+Enter) to see which questions your edits change and which documents would have to be read again.')}</Text>}
        {R && S.stale ? <Badge color="yellow" variant="light">{t('edited since')}</Badge> : null}
        {R && R.r.changes ? <Text size="sm" c="dimmed">{R.r.removed && R.r.removed.length
          ? t('{n} changed questions, {removed} removed', { n: R.r.changes.length, removed: R.r.removed.length })
          : tn(R.r.changes.length, '{n} changed question', '{n} changed questions')}</Text> : null}
      </Group>
      {S.panelOpen && R ? <Box className="dp-spec-panel" mt="xs"><Body key={resultId(R)} /></Box> : null}
    </Paper>
  );
}
