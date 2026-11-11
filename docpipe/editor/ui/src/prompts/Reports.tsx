/* The answers of check and save for a prompt or a module's text blocks, and the review that follows a save
   (old repNodes, promptReport, phrasesReport, reviewNodes). */
import { Fragment, type ReactNode } from 'react';
import { Accordion, Alert, Badge, Button, Code, Group, List, Loader, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconCircleCheck, IconInfoCircle } from '@tabler/icons-react';
import { Diff, Muted } from '../components/Bits';
import { isObj } from '../lib/util';
import { rich, t, tn, tr } from '../lib/i18n';
import { textOf, stampOf, type X } from './logic';
import { actSave, reloadFromDisk } from './store';

/* a translated text with {names} left in it, each filled with a node: Put text={t('{key} now: {text}')} slots={{ key: <Code>..</Code>, text }} */
export function Put({ text, slots }: { text: string; slots: Record<string, ReactNode> }) {
  return <>{text.split(/(\{\w+\})/).map((p, i) => {
    const m = /^\{(\w+)\}$/.exec(p);
    return <Fragment key={i}>{m && m[1] in slots ? slots[m[1]] : p}</Fragment>;
  })}</>;
}

/* the state words of a changed text block */
const stateWord = (s: string) => s === 'added' ? t('added') : s === 'removed' ? t('removed') : s === 'changed' ? t('changed') : s;

function LinesBadges({ r }: { r: any }) {
  const ln = r.lines || {};
  return <Group gap={6} component="span" display="inline-flex"><Badge color="green" variant="light">{tn(ln.added || 0, '+{n} line', '+{n} lines')}</Badge><Badge color="red" variant="light">{tn(ln.removed || 0, '-{n} line', '-{n} lines')}</Badge></Group>;
}

function FileDiff({ r }: { r: any }) {
  if (!r.diff) return null;
  return (
    <Accordion variant="contained">
      <Accordion.Item value="d">
        <Accordion.Control>{t('Changes to the file')} <LinesBadges r={r} /></Accordion.Control>
        <Accordion.Panel><Diff text={String(r.diff)} /></Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}

function PromptReport({ r }: { r: any }) {
  const meta = r.meta && isObj(r.meta.before) && isObj(r.meta.after)
    ? [...new Set(Object.keys(r.meta.before).concat(Object.keys(r.meta.after)))].filter(k => JSON.stringify(r.meta.before[k]) !== JSON.stringify(r.meta.after[k]))
    : [];
  return (
    <Stack gap="xs">
      {r.ok
        ? <Alert color="teal" icon={<IconCircleCheck />}>{t('A run would load this text.')}</Alert>
        : <Alert color="red" icon={<IconAlertTriangle />} title={t('The check refuses this text')}>{r.error || ''}</Alert>}
      {r.creates && <Alert color="yellow" icon={<IconInfoCircle />}>{t('Saving writes a new file of this profile: {file}', { file: r.creates })}</Alert>}
      {r.changed === false && <Muted>{t('The text is the same as the file on disk.')}</Muted>}
      {r.size && <Muted>{t('The text that is sent: {before} → {after} characters.', { before: r.size.before, after: r.size.after })}</Muted>}
      {meta.map(k => <Muted key={k}><Put text={t('Setting {key}: {before} → {after}')} slots={{ key: <Code>{k}</Code>, before: textOf(r.meta.before[k]), after: textOf(r.meta.after[k]) }} /></Muted>)}
      {r.sentences && (
        <Accordion variant="contained" defaultValue="s">
          <Accordion.Item value="s"><Accordion.Control>{t('Changes by text block')}</Accordion.Control><Accordion.Panel><Diff text={String(r.sentences)} /></Accordion.Panel></Accordion.Item>
        </Accordion>
      )}
      <FileDiff r={r} />
      {r.note && <Muted>{rich(tr(r.note))}</Muted>}
    </Stack>
  );
}

function PhrasesReport({ r, skipRemoved }: { r: any; skipRemoved: boolean }) {
  const ch: any[] = r.changes || [];
  return (
    <Stack gap="xs">
      {r.ok
        ? <Alert color="teal" icon={<IconCircleCheck />}>{t('A run would load these text blocks.')}</Alert>
        : <Alert color="red" icon={<IconAlertTriangle />} title={t('The check refuses these text blocks')}>{(r.error || '') + (r.where ? ' (' + r.where + ')' : '')}</Alert>}
      {r.creates && <Alert color="yellow" icon={<IconInfoCircle />}>{t('Saving writes a new file of this profile: {file}', { file: r.creates })}</Alert>}
      {r.changed === false && <Muted>{t('The text blocks are the same as in the file on disk.')}</Muted>}
      {ch.length > 0 && (
        <Accordion variant="contained" defaultValue="c">
          <Accordion.Item value="c">
            <Accordion.Control>{t('Changed text blocks ({n})', { n: ch.length })}</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                {ch.map((c, i) => (
                  <div key={i} className="pr-pair" style={{ borderTop: 0, padding: 0 }}>
                    <Badge color={c.state === 'added' ? 'green' : c.state === 'removed' ? 'red' : 'yellow'} variant="light">{stateWord(c.state)}</Badge>{' '}<Code>{c.key}</Code>
                    {c.state !== 'added' && <div>{t('before:')} {textOf(c.before)}</div>}
                    {c.state !== 'removed' && <div>{t('after:')} {textOf(c.after)}</div>}
                  </div>
                ))}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      )}
      <FileDiff r={r} />
      {!skipRemoved && (r.removed || []).length > 0 &&
        <Alert color="yellow" icon={<IconInfoCircle />}>{t('This change removes text blocks of the profile\'s own ({keys}). Saving asks for confirmation first.', { keys: r.removed.map((c: any) => c.key).join(', ') })}</Alert>}
      {r.note && <Muted>{rich(tr(r.note))}</Muted>}
    </Stack>
  );
}

function RepNodes({ x }: { x: X }) {
  const R = x.rep!;
  if (R.error) return <Alert color="red" icon={<IconAlertTriangle />}>{R.error}</Alert>;
  const r = R.r || {};
  const out: ReactNode[] = [];
  if (R.source === 'save') {
    if (r.saved) out.push(<Alert key="s" color="teal" icon={<IconCircleCheck />}>{t('Saved {file}.', { file: r.path || '' })}</Alert>);
    else if (r.reason === 'moved') {
      return (
        <Alert color="red" icon={<IconAlertTriangle />} title={t('The file changed on disk')}>
          <Stack gap="xs">
            <Text size="sm">{t('The file a run loads changed on disk since this page loaded it. Nothing was written.')}</Text>
            <Button size="xs" variant="white" color="red" w="fit-content" onClick={() => reloadFromDisk(x)}>{t('Reload from disk')}</Button>
          </Stack>
        </Alert>
      );
    } else if (r.reason === 'same') out.push(<Alert key="s" color="gray">{t('Nothing changed. Nothing was written.')}</Alert>);
    else if (r.reason === 'confirm') {
      out.push(
        <Alert key="s" color="yellow" icon={<IconAlertTriangle />} title={t('This save removes text blocks of the profile\'s own. Nothing is written yet.')}>
          <Stack gap="xs">
            <List size="sm" spacing={4}>
              {(r.removed || []).map((c: any, i: number) => <List.Item key={i}><Put text={t('{key} now: {before} — then the profile runs with: {after}')} slots={{ key: <Code>{c.key}</Code>, before: textOf(c.before), after: textOf(c.after) }} /></List.Item>)}
            </List>
            <Button color="red" size="xs" w="fit-content" onClick={() => actSave(x, true)}>{t('Remove and save')}</Button>
          </Stack>
        </Alert>);
    } else if (r.reason === 'check') out.push(<Alert key="s" color="red" icon={<IconAlertTriangle />}>{t('Not saved: the check refuses this text.')}</Alert>);
  }
  out.push(x.kind === 'prompt' ? <PromptReport key="r" r={r} /> : <PhrasesReport key="r" r={r} skipRemoved={R.source === 'save'} />);
  return <Stack gap="xs">{out}</Stack>;
}

function ReviewNodes({ rv }: { rv: any }) {
  if (rv.running) return <Alert color="gray" icon={<Loader size="xs" />}>{t('Running the profile check and the before/after comparison…')}</Alert>;
  if (rv.err) return <Alert color="red" icon={<IconAlertTriangle />}>{t('The review could not run: {error}', { error: rv.err })}</Alert>;
  const res = rv.res || {};
  return (
    <Stack gap="xs">
      <Alert color={res.ok ? 'teal' : 'red'} icon={res.ok ? <IconCircleCheck /> : <IconAlertTriangle />}>
        {res.ok ? t('The profile check and the before/after comparison passed.') : t('The profile check or the before/after comparison failed.')}
      </Alert>
      {(res.steps || []).map((st: any, i: number) => (
        <Accordion key={i} variant="contained" defaultValue={st.ok ? null : 's'}>
          <Accordion.Item value="s">
            <Accordion.Control>
              <Group gap="xs"><Badge color={st.ok ? 'teal' : 'red'} variant="light">{st.ok ? t('ok') : t('failed')}</Badge><Text span>{st.name || ''}</Text><Code>{st.command || ''}</Code></Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                {st.output ? <pre className="pr-out">{st.output}</pre> : <Muted>{t('No output.')}</Muted>}
                {st.summary && <><Text fw={600}>{t('Summary')}</Text><pre className="pr-out">{st.summary}</pre></>}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      ))}
    </Stack>
  );
}

export function Reports({ x }: { x: X }) {
  return (
    <Stack gap="xs">
      {x.rep && x.rep.stamp !== stampOf(x) && <Alert color="yellow" icon={<IconInfoCircle />}>{t('The text was edited after this result.')}</Alert>}
      {x.rep && <RepNodes x={x} />}
      {x.review && <ReviewNodes rv={x.review} />}
    </Stack>
  );
}
