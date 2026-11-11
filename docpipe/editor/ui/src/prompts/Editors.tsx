/* The middle column: the editor of a prompt in its parts and the editor of a module's sentences
   (old renderPromptEditor, renderPhrasesEditor, sentenceRow, shownNodes). */
import { Alert, Badge, Button, Code, Group, Loader, NativeSelect, Paper, Stack, Text, Textarea, Title } from '@mantine/core';
import { IconAlertTriangle, IconArrowBackUp, IconCheck, IconDeviceFloppy, IconHistory, IconInfoCircle, IconSearch } from '@tabler/icons-react';
import { AreaBox, TextBox } from '../components/Inputs';
import { Muted } from '../components/Bits';
import { clone, mb, own } from '../lib/util';
import { diffSegs, inheritedOf, isDirty, settingRest, textOf, withSetting, type Ed, type Ph, type ShownCell, type X } from './logic';
import { P, actCheck, actDiscard, actSave, edited, fetchShown, setTrace } from './store';
import { Reports } from './Reports';
import './prompts.css';

function Area({ value, onText, readOnly }: { value: string; onText?: (t: string) => void; readOnly?: boolean }) {
  if (readOnly) {
    return <Textarea className="pr-area" readOnly autosize minRows={3} maxRows={40} value={value} spellCheck={false} />;
  }
  return <div className="pr-area"><AreaBox value={value} onText={onText!} minRows={3} maxRows={40} mono fontSize={14} /></div>;
}

function Actions({ x }: { x: X }) {
  const dirty = isDirty(x);
  return (
    <Group>
      <Button leftSection={<IconCheck size={18} />} variant="default" disabled={x.busy} onClick={() => actCheck(x)} title="Ctrl+Enter">Check</Button>
      <Button leftSection={<IconDeviceFloppy size={18} />} disabled={x.busy} onClick={() => actSave(x, false)} title="Ctrl+S">Save</Button>
      <Button leftSection={<IconArrowBackUp size={18} />} variant="default" disabled={x.busy || !dirty} onClick={() => actDiscard(x)}>Discard changes</Button>
      {x.busy && <Loader size="sm" />}
    </Group>
  );
}

function Setting({ E, k }: { E: Ed; k: string }) {
  const rest = settingRest(E.cut.front, k) ?? '';
  const lead = /^[ \t]*/.exec(settingRest(E.detail.cut.front, k) ?? rest)![0];
  return (
    <TextBox mono w={160} label={<Code>{k}</Code>} value={rest.slice(lead.length)}
      onText={v => { E.cut.front = withSetting(E.cut.front, k, lead, v); edited(E); }} />
  );
}

export function PromptEditor({ E }: { E: Ed }) {
  const d = E.detail;
  const keys = ['temperature', 'max_tokens'].filter(k => settingRest(E.cut.front, k) !== null);
  return (
    <Stack gap="md">
      <Group gap="sm" align="center">
        <Title order={3}>{d.id}</Title>
        {d.own ? <Badge color="teal" variant="light">own file</Badge> : <Badge color="gray" variant="light">inherited from {d.owner}</Badge>}
        {isDirty(E) && <Badge color="orange" variant="light">unsaved changes</Badge>}
      </Group>
      <Muted>File: <Code>{d.path || ''}</Code></Muted>
      {!d.own && <Alert color="yellow" icon={<IconInfoCircle />}>This profile runs with the file of {d.owner}. Saving writes a file of its own: {d.target || ''}.</Alert>}

      {keys.length > 0 && (
        <Paper withBorder radius="md" p="md">
          <Text fw={600} mb="xs">Settings</Text>
          <Group align="flex-end">{keys.map(k => <Setting key={k} E={E} k={k} />)}</Group>
        </Paper>
      )}

      {E.single ? (
        <Paper withBorder radius="md" p="md">
          <Stack gap="xs">
            <Text fw={600}>{d.composed ? 'The file, after its settings' : 'What every request is told'}</Text>
            <Area value={E.body} onText={v => { E.body = v; edited(E); }} />
            {d.composed && (
              <>
                <Muted>This file is put together with a template of the core. The text that is sent:</Muted>
                <Area readOnly value={d.sent == null ? '' : d.sent} />
                <Muted>This is the text sent with the file on disk; it does not change while you edit.</Muted>
              </>
            )}
          </Stack>
        </Paper>
      ) : (
        <>
          <Paper withBorder radius="md" p="md">
            <Stack gap="xs">
              <Text fw={600}>What every request is told</Text>
              <Area value={E.cut.common} onText={v => { E.cut.common = v; edited(E); }} />
            </Stack>
          </Paper>
          {E.cut.parts.map((p, i) => (
            <Paper key={i} withBorder radius="md" p="md">
              <Stack gap="xs">
                <Text fw={600}>
                  {p.kind === 'follow-up' ? 'The words of a follow-up message that carries: ' : 'Only told to a request whose message carries: '}
                  <Code>{(p.keys || []).join(', ')}</Code>
                </Text>
                <Muted>Opened by the line <Code>{String(p.mark).replace(/\n+$/, '')}</Code> (not editable)</Muted>
                <Area value={p.text} onText={v => { p.text = v; edited(E); }} />
              </Stack>
            </Paper>
          ))}
        </>
      )}
      {(d.placeholders || []).length > 0 && <Muted>Places the code fills: {d.placeholders.map((x: string) => <Code key={x} mr={6}>{'{{' + x + '}}'}</Code>)}</Muted>}

      <Actions x={E} />
      <Reports x={E} />
    </Stack>
  );
}

/* ---------- the sentences of a module ---------- */

function Seg({ seg, cls }: { seg: [string, string, string]; cls: string }) {
  return <>{seg[0]}{seg[1] ? <span className={cls}>{seg[1]}</span> : null}{seg[2]}</>;
}

function ShownList({ cell, redraw }: { cell: ShownCell; redraw: () => void }) {
  if (cell.loading) return <Group gap="xs"><Loader size="xs" /><Muted>Looking through the trace… the first time this takes several seconds.</Muted></Group>;
  if (cell.err) return <Alert color="red" icon={<IconAlertTriangle />}>{cell.err}</Alert>;
  const r = cell.res || {};
  const all: any[] = r.shown || [];
  const limit = cell.all ? all.length : 50;
  return (
    <Stack gap={4}>
      <Muted>Found in {r.found == null ? all.length : r.found} of {r.searched == null ? '?' : r.searched} requests.{r.why ? ' ' + r.why : ''}</Muted>
      {all.slice(0, limit).map((it, i) => {
        const segs = it.after == null ? null : diffSegs(it.before, it.after);
        return (
          <div key={i} className="pr-pair">
            <div><Code>#{it.index}</Code> {it.kind || ''}{it.asked ? ' (asks again: ' + it.asked + ')' : ''}{it.parameter ? ' · ' + it.parameter : ''}</div>
            <div>before: {segs ? <Seg seg={segs.a} cls="pr-lost" /> : textOf(it.before)}</div>
            {segs && <div>after: <Seg seg={segs.b} cls="pr-hit" /></div>}
            {it.why && <Muted>{it.why}</Muted>}
          </div>
        );
      })}
      {all.length > limit && <Button size="xs" variant="default" w="fit-content" onClick={() => { cell.all = true; redraw(); }}>Show all {all.length}</Button>}
    </Stack>
  );
}

function SentenceRow({ X, s, redraw }: { X: Ph; s: any; redraw: () => void }) {
  const key: string = s.key;
  const mine = own(X.table, key);
  const cur = mine ? X.table[key] : inheritedOf(s);
  const isList = Array.isArray(cur);
  const items: any[] = isList ? cur : [cur];
  const firstText = () => { const c = own(X.table, key) ? X.table[key] : inheritedOf(s); return Array.isArray(c) ? (c[0] == null ? '' : String(c[0])) : String(c == null ? '' : c); };
  const cell = X.shown[key];
  /* what the trace showed belongs to the wording it was looked up with: it is hidden once the sentence reads differently */
  const fresh = !!cell && (!!cell.loading || cell.text === firstText());
  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="xs">
        {s.note && <Muted>{s.note}</Muted>}
        <Group gap="xs">
          <Code>{key}</Code>
          {s.required && <Badge variant="light" color="gray">required</Badge>}
          {mine ? <Badge variant="light" color="teal">this profile</Badge> : <Badge variant="light" color="gray">from {s.from || 'default'}</Badge>}
        </Group>
        {items.map((t, i) => mine
          ? <Area key={i} value={t == null ? '' : String(t)} onText={v => { if (Array.isArray(X.table[key])) X.table[key][i] = v; else X.table[key] = v; edited(X); }} />
          : <Area key={i} readOnly value={t == null ? '' : String(t)} />)}
        <Muted>{s.names == null ? 'Takes no name in braces.' : 'Names the code fills: ' + (s.names.length ? s.names.map((n: string) => '{' + n + '}').join(' ') : 'none')}</Muted>
        <Group gap="xs">
          {mine && s.inherited != null && <Button size="xs" variant="default" leftSection={<IconHistory size={16} />} onClick={() => { delete X.table[key]; edited(X); }}>Take the inherited wording again</Button>}
          {!mine && <Button size="xs" variant="default" onClick={() => { X.table[key] = clone(inheritedOf(s)); edited(X); }}>Word it for this profile</Button>}
          {P.trace && <Button size="xs" variant="default" leftSection={<IconSearch size={16} />} disabled={!!(cell && cell.loading)} onClick={() => fetchShown(X, key, firstText())}>Recorded requests with this sentence</Button>}
        </Group>
        {cell && fresh && <ShownList cell={cell} redraw={redraw} />}
      </Stack>
    </Paper>
  );
}

function TraceSelect() {
  const tr: any[] = (P.list && P.list.traces) || [];
  if (!tr.length) return <Muted>{(P.list && P.list.traces_note) || 'There is no recorded request.'}</Muted>;
  if (tr.length === 1) return <Text size="sm">Trace <Code>{tr[0].name}</Code> <Muted>{mb(tr[0].bytes || 0)}</Muted></Text>;
  return <NativeSelect w="auto" value={P.trace || ''} onChange={e => setTrace(e.currentTarget.value)} data={tr.map(t => ({ value: t.name, label: t.name + ' (' + mb(t.bytes || 0) + ')' }))} />;
}
export { TraceSelect };

export function PhrasesEditor({ X, redraw }: { X: Ph; redraw: () => void }) {
  const d = X.detail;
  return (
    <Stack gap="md">
      <Group gap="sm">
        <Title order={3}>Sentences of {X.module}</Title>
        {isDirty(X) && <Badge color="orange" variant="light">unsaved changes</Badge>}
      </Group>
      <Muted>File: <Code>{d.path || ''}</Code></Muted>
      {!d.own_file && <Alert color="yellow" icon={<IconInfoCircle />}>This profile has no file of its own for this module yet. Saving a sentence writes one.</Alert>}
      <Group><Text fw={600}>Recorded requests</Text><TraceSelect /></Group>
      {(d.sentences || []).map((s: any) => <SentenceRow key={s.key} X={X} s={s} redraw={redraw} />)}
      <Actions x={X} />
      <Reports x={X} />
    </Stack>
  );
}
