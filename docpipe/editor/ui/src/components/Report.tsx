/* The answer of a check or a save of the rules, sources, graph and flow files: what the server refuses, what changes,
   what a save writes, the diff and the sentences the server adds. */
import { Accordion, Alert, Anchor, Button, Code, List, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconCircleCheck } from '@tabler/icons-react';
import { Diff } from './Bits';
import { shown } from '../lib/util';
import { rich, t, tr } from '../lib/i18n';

export interface Reported { source: 'check' | 'save' | string; r?: any; error?: string }

export const writesText = (w: string, file?: string) => {
  const f = file || t('the file');
  switch (w) {
    case 'created': return t('Saving creates {file}.', { file: f });
    case 'changed': return t('Saving changes {file}.', { file: f });
    case 'removed': return t('Saving removes {file} (nothing would differ from the default values any more).', { file: f });
    case 'unchanged': return t('Saving writes nothing to {file}.', { file: f });
    default: return t('Saving: {what} {file}.', { what: w, file: f });
  }
};

export function Report({ R, onName, onReload }: { R: Reported | null; onName?: (name: string) => void; onReload?: () => void }) {
  if (!R) return null;
  if (R.error) return <Alert color="red" icon={<IconAlertTriangle />}>{R.error}</Alert>;
  const r = R.r || {};
  if (R.source === 'save' && r.reason === 'moved') {
    return (
      <Alert color="red" icon={<IconAlertTriangle />} title={t('The file changed on disk')}>
        <Stack gap="xs">
          <Text size="sm">{r.message || t('The file changed on disk since the page loaded it. Nothing was written.')}</Text>
          {onReload && <Button size="xs" variant="white" color="red" onClick={onReload}>{t('Reload from disk')}</Button>}
        </Stack>
      </Alert>
    );
  }
  const errs: { name?: string; id?: string; message: string }[] = r.errors || [];
  return (
    <Stack gap="xs">
      {R.source === 'save' && !r.saved && <Alert color="red" icon={<IconAlertTriangle />}>{t('Not saved: {reason}', { reason: r.message || r.reason || t('the server refused it.') })}</Alert>}
      {errs.length > 0 && (
        <Alert color="red" icon={<IconAlertTriangle />} title={t('The server refuses')}>
          <List size="sm" spacing={4}>
            {errs.map((e, i) => (
              <List.Item key={i}>
                {e.name ? (onName ? <><Anchor component="button" type="button" onClick={() => onName(e.name!)}>{e.name}</Anchor>: </> : <><Code>{e.name}</Code>: </>) : null}
                {e.message}
              </List.Item>
            ))}
          </List>
        </Alert>
      )}
      {!errs.length && r.ok && <Alert color="teal" icon={<IconCircleCheck />}>{t('Accepted.')}</Alert>}
      {!errs.length && Array.isArray(r.changed) && (
        <Alert color="gray" title={t('Changes ({n})', { n: r.changed.length })}>
          {r.changed.length
            ? <List size="sm" spacing={2}>{r.changed.map((c: any, i: number) => <List.Item key={i}><Code>{c.name}</Code>: {shown(c.from)} → {shown(c.to)}</List.Item>)}</List>
            : <Text size="sm" c="dimmed">{t('Nothing differs from the files on disk.')}</Text>}
        </Alert>
      )}
      {!errs.length && r.writes && <Text size="sm" c="dimmed">{writesText(r.writes, r.file)}</Text>}
      {(r.diff || []).length > 0 && (
        <Accordion variant="contained" defaultValue="diff">
          <Accordion.Item value="diff">
            <Accordion.Control>{t('Diff of {file}', { file: r.file || t('the file') })}</Accordion.Control>
            <Accordion.Panel><Diff text={Array.isArray(r.diff) ? r.diff : String(r.diff)} /></Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      )}
      {(r.says || []).map((s: string, i: number) => <Text key={i} size="sm" c="dimmed">{rich(tr(s))}</Text>)}
    </Stack>
  );
}
