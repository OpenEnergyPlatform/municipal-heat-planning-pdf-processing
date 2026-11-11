/* The answers of check and save for a prompt or a module's sentences, and the review that follows a save
   (old repNodes, promptReport, phrasesReport, reviewNodes). */
import type { ReactNode } from 'react';
import { Accordion, Alert, Badge, Button, Code, Group, List, Loader, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconCircleCheck, IconInfoCircle } from '@tabler/icons-react';
import { Diff, Muted } from '../components/Bits';
import { isObj } from '../lib/util';
import { textOf, stampOf, type X } from './logic';
import { actSave, reloadFromDisk } from './store';

function LinesBadges({ r }: { r: any }) {
  const ln = r.lines || {};
  return <Group gap={6} component="span" display="inline-flex"><Badge color="green" variant="light">{'+' + (ln.added || 0) + ' lines'}</Badge><Badge color="red" variant="light">{'-' + (ln.removed || 0) + ' lines'}</Badge></Group>;
}

function FileDiff({ r }: { r: any }) {
  if (!r.diff) return null;
  return (
    <Accordion variant="contained">
      <Accordion.Item value="d">
        <Accordion.Control>Diff of the file <LinesBadges r={r} /></Accordion.Control>
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
        ? <Alert color="teal" icon={<IconCircleCheck />}>A run would load this text.</Alert>
        : <Alert color="red" icon={<IconAlertTriangle />} title="The check refuses this text">{r.error || ''}</Alert>}
      {r.creates && <Alert color="yellow" icon={<IconInfoCircle />}>Saving writes a new file of this profile: {r.creates}</Alert>}
      {r.changed === false && <Muted>The text is the file on disk.</Muted>}
      {r.size && <Muted>The text that is sent: {r.size.before} → {r.size.after} characters.</Muted>}
      {meta.map(k => <Muted key={k}>Setting <Code>{k}</Code>: {textOf(r.meta.before[k])} → {textOf(r.meta.after[k])}</Muted>)}
      {r.sentences && (
        <Accordion variant="contained" defaultValue="s">
          <Accordion.Item value="s"><Accordion.Control>Changes by sentence</Accordion.Control><Accordion.Panel><Diff text={String(r.sentences)} /></Accordion.Panel></Accordion.Item>
        </Accordion>
      )}
      <FileDiff r={r} />
      {r.note && <Muted>{r.note}</Muted>}
    </Stack>
  );
}

function PhrasesReport({ r, skipRemoved }: { r: any; skipRemoved: boolean }) {
  const ch: any[] = r.changes || [];
  return (
    <Stack gap="xs">
      {r.ok
        ? <Alert color="teal" icon={<IconCircleCheck />}>A run would load these sentences.</Alert>
        : <Alert color="red" icon={<IconAlertTriangle />} title="The check refuses these sentences">{(r.error || '') + (r.where ? ' (' + r.where + ')' : '')}</Alert>}
      {r.creates && <Alert color="yellow" icon={<IconInfoCircle />}>Saving writes a new file of this profile: {r.creates}</Alert>}
      {r.changed === false && <Muted>The sentences are those of the file on disk.</Muted>}
      {ch.length > 0 && (
        <Accordion variant="contained" defaultValue="c">
          <Accordion.Item value="c">
            <Accordion.Control>Changed sentences ({ch.length})</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                {ch.map((c, i) => (
                  <div key={i} className="pr-pair" style={{ borderTop: 0, padding: 0 }}>
                    <Badge color={c.state === 'added' ? 'green' : c.state === 'removed' ? 'red' : 'yellow'} variant="light">{c.state}</Badge>{' '}<Code>{c.key}</Code>
                    {c.state !== 'added' && <div>before: {textOf(c.before)}</div>}
                    {c.state !== 'removed' && <div>after: {textOf(c.after)}</div>}
                  </div>
                ))}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      )}
      <FileDiff r={r} />
      {!skipRemoved && (r.removed || []).length > 0 &&
        <Alert color="yellow" icon={<IconInfoCircle />}>This text takes own sentences away ({r.removed.map((c: any) => c.key).join(', ')}). Saving asks for a confirmation.</Alert>}
      {r.note && <Muted>{r.note}</Muted>}
    </Stack>
  );
}

function RepNodes({ x }: { x: X }) {
  const R = x.rep!;
  if (R.error) return <Alert color="red" icon={<IconAlertTriangle />}>{R.error}</Alert>;
  const r = R.r || {};
  const out: ReactNode[] = [];
  if (R.source === 'save') {
    if (r.saved) out.push(<Alert key="s" color="teal" icon={<IconCircleCheck />}>Saved {r.path || ''}.</Alert>);
    else if (r.reason === 'moved') {
      return (
        <Alert color="red" icon={<IconAlertTriangle />} title="The file changed on disk">
          <Stack gap="xs">
            <Text size="sm">The file a run loads changed on disk since this page loaded it. Nothing was written.</Text>
            <Button size="xs" variant="white" color="red" w="fit-content" onClick={() => reloadFromDisk(x)}>Reload from disk</Button>
          </Stack>
        </Alert>
      );
    } else if (r.reason === 'same') out.push(<Alert key="s" color="gray">Nothing changed. Nothing was written.</Alert>);
    else if (r.reason === 'confirm') {
      out.push(
        <Alert key="s" color="yellow" icon={<IconAlertTriangle />} title="This save takes own sentences away. Nothing is written yet.">
          <Stack gap="xs">
            <List size="sm" spacing={4}>
              {(r.removed || []).map((c: any, i: number) => <List.Item key={i}><Code>{c.key}</Code> now: {textOf(c.before)} — then the profile runs with: {textOf(c.after)}</List.Item>)}
            </List>
            <Button color="red" size="xs" w="fit-content" onClick={() => actSave(x, true)}>Remove and save</Button>
          </Stack>
        </Alert>);
    } else if (r.reason === 'check') out.push(<Alert key="s" color="red" icon={<IconAlertTriangle />}>Not saved: the check refuses this text.</Alert>);
  }
  out.push(x.kind === 'prompt' ? <PromptReport key="r" r={r} /> : <PhrasesReport key="r" r={r} skipRemoved={R.source === 'save'} />);
  return <Stack gap="xs">{out}</Stack>;
}

function ReviewNodes({ rv }: { rv: any }) {
  if (rv.running) return <Alert color="gray" icon={<Loader size="xs" />}>Running the profile check and the before/after comparison…</Alert>;
  if (rv.err) return <Alert color="red" icon={<IconAlertTriangle />}>The review could not run: {rv.err}</Alert>;
  const res = rv.res || {};
  return (
    <Stack gap="xs">
      <Alert color={res.ok ? 'teal' : 'red'} icon={res.ok ? <IconCircleCheck /> : <IconAlertTriangle />}>
        {res.ok ? 'The profile check and the before/after comparison passed.' : 'The profile check or the before/after comparison failed.'}
      </Alert>
      {(res.steps || []).map((st: any, i: number) => (
        <Accordion key={i} variant="contained" defaultValue={st.ok ? null : 's'}>
          <Accordion.Item value="s">
            <Accordion.Control>
              <Group gap="xs"><Badge color={st.ok ? 'teal' : 'red'} variant="light">{st.ok ? 'ok' : 'failed'}</Badge><Text span>{st.name || ''}</Text><Code>{st.command || ''}</Code></Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                {st.output ? <pre className="pr-out">{st.output}</pre> : <Muted>No output.</Muted>}
                {st.summary && <><Text fw={600}>Summary</Text><pre className="pr-out">{st.summary}</pre></>}
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
      {x.rep && x.rep.stamp !== stampOf(x) && <Alert color="yellow" icon={<IconInfoCircle />}>The text was edited after this result.</Alert>}
      {x.rep && <RepNodes x={x} />}
      {x.review && <ReviewNodes rv={x.review} />}
    </Stack>
  );
}
