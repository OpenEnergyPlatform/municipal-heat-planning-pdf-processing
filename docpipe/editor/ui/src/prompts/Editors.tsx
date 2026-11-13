/* The middle column: the editor of a prompt in its parts and the editor of a module's text blocks
   (old renderPromptEditor, renderPhrasesEditor, sentenceRow, shownNodes). */
import { Alert, Badge, Button, Code, Group, Loader, NativeSelect, Paper, Stack, Text, Textarea, Title } from '@mantine/core';
import { IconAlertTriangle, IconArrowBackUp, IconCheck, IconDeviceFloppy, IconHistory, IconInfoCircle, IconSearch } from '@tabler/icons-react';
import { AreaBox, TextBox } from '../components/Inputs';
import { Muted } from '../components/Bits';
import { clone, mb, own } from '../lib/util';
import { t, tr, rich } from '../lib/i18n';
import { diffSegs, inheritedOf, isDirty, settingRest, textOf, withSetting, type Ed, type Ph, type ShownCell, type X } from './logic';
import { P, actCheck, actDiscard, actSave, edited, fetchShown, setTrace } from './store';
import { Put, Reports } from './Reports';
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
      <Button leftSection={<IconCheck size={18} />} variant="default" disabled={x.busy} onClick={() => actCheck(x)} title={t('Ctrl+Enter')}>{t('Check')}</Button>
      <Button leftSection={<IconDeviceFloppy size={18} />} disabled={x.busy} onClick={() => actSave(x, false)} title={t('Ctrl+S')}>{t('Save')}</Button>
      <Button leftSection={<IconArrowBackUp size={18} />} variant="default" disabled={x.busy || !dirty} onClick={() => actDiscard(x)}>{t('Discard changes')}</Button>
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
        {d.own ? <Badge color="teal" variant="light">{t('own file')}</Badge> : <Badge color="gray" variant="light">{t('default from profile {name}', { name: d.owner })}</Badge>}
        {isDirty(E) && <Badge color="orange" variant="light">{t('unsaved changes')}</Badge>}
      </Group>
      <Muted>{rich(t('File: `{path}`', { path: d.path || '' }))}</Muted>
      {!d.own && <Alert color="yellow" icon={<IconInfoCircle />}>{t('This profile runs with the file of {owner}. Saving does not change that file: it writes a file of its own for this profile, {file}.', { owner: d.owner, file: d.target || '' })}</Alert>}

      {keys.length > 0 && (
        <Paper withBorder radius="md" p="md">
          <Text fw={600} mb="xs">{t('Settings')}</Text>
          <Group align="flex-end">{keys.map(k => <Setting key={k} E={E} k={k} />)}</Group>
        </Paper>
      )}

      {E.single ? (
        <Paper withBorder radius="md" p="md">
          <Stack gap="xs">
            <Text fw={600}>{d.composed ? t('The file, after its settings') : t('What every request is told')}</Text>
            <Area value={E.body} onText={v => { E.body = v; edited(E); }} />
            {d.composed && (
              <>
                <Muted>{t('The text of this file is combined with a template of the program before it is sent. The text that is sent to the model is:')}</Muted>
                <Area readOnly value={d.sent == null ? '' : d.sent} />
                <Muted>{t('This is the text that the file on disk gives. It does not change while you edit; save to see the effect of your edit.')}</Muted>
              </>
            )}
          </Stack>
        </Paper>
      ) : (
        <>
          <Paper withBorder radius="md" p="md">
            <Stack gap="xs">
              <Text fw={600}>{t('What every request is told')}</Text>
              <Area value={E.cut.common} onText={v => { E.cut.common = v; edited(E); }} />
            </Stack>
          </Paper>
          {E.cut.parts.map((p, i) => (
            <Paper key={i} withBorder radius="md" p="md">
              <Stack gap="xs">
                <Text fw={600}>
                  {p.kind === 'follow-up' ? t('The words of a follow-up message that carries:') : t('Only told to a request whose message carries:')}{' '}
                  <Code>{(p.keys || []).join(', ')}</Code>
                </Text>
                <Muted><Put text={t('Starts at the line {mark} (not editable)')} slots={{ mark: <Code>{String(p.mark).replace(/\n+$/, '')}</Code> }} /></Muted>
                <Area value={p.text} onText={v => { p.text = v; edited(E); }} />
              </Stack>
            </Paper>
          ))}
        </>
      )}
      {(d.placeholders || []).length > 0 && <Muted>{t('Places the code fills in:')} {d.placeholders.map((x: string) => <Code key={x} mr={6}>{'{{' + x + '}}'}</Code>)}</Muted>}

      <Actions x={E} />
      <Reports x={E} />
    </Stack>
  );
}

/* ---------- the text blocks of a module ---------- */

function Seg({ seg, cls }: { seg: [string, string, string]; cls: string }) {
  return <>{seg[0]}{seg[1] ? <span className={cls}>{seg[1]}</span> : null}{seg[2]}</>;
}

function ShownList({ cell, redraw }: { cell: ShownCell; redraw: () => void }) {
  if (cell.loading) return <Group gap="xs"><Loader size="xs" /><Muted>{t('Looking through the request log. The first time this takes several seconds.')}</Muted></Group>;
  if (cell.err) return <Alert color="red" icon={<IconAlertTriangle />}>{cell.err}</Alert>;
  const r = cell.res || {};
  const all: any[] = r.shown || [];
  const limit = cell.all ? all.length : 50;
  return (
    <Stack gap={4}>
      <Muted>{t('Found in {found} of {searched} requests.', { found: r.found == null ? all.length : r.found, searched: r.searched == null ? '?' : r.searched })}{r.why ? ' ' + tr(r.why) : ''}</Muted>
      {all.slice(0, limit).map((it, i) => {
        const segs = it.after == null ? null : diffSegs(it.before, it.after);
        return (
          <div key={i} className="pr-pair">
            <div><Code>#{it.index}</Code> {it.kind || ''}{it.asked ? ' ' + t('(asks again: {asked})', { asked: it.asked }) : ''}{it.parameter ? ' · ' + it.parameter : ''}</div>
            <div>{t('before:')} {segs ? <Seg seg={segs.a} cls="pr-lost" /> : textOf(it.before)}</div>
            {segs && <div>{t('after:')} <Seg seg={segs.b} cls="pr-hit" /></div>}
            {it.why && <Muted>{rich(tr(it.why))}</Muted>}
          </div>
        );
      })}
      {all.length > limit && <Button size="xs" variant="default" w="fit-content" onClick={() => { cell.all = true; redraw(); }}>{t('Show all {n}', { n: all.length })}</Button>}
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
  /* what the request log showed belongs to the wording it was looked up with: it is hidden once the text block reads differently */
  const fresh = !!cell && (!!cell.loading || cell.text === firstText());
  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="xs">
        {s.note && <Muted>{rich(tr(s.note))}</Muted>}
        <Group gap="xs">
          <Code>{key}</Code>
          {s.required && <Badge variant="light" color="gray">{t('required')}</Badge>}
          {mine ? <Badge variant="light" color="teal">{t('this profile')}</Badge> : <Badge variant="light" color="gray">{t('from {source}', { source: s.from || t('default') })}</Badge>}
        </Group>
        {items.map((item, i) => mine
          ? <Area key={i} value={item == null ? '' : String(item)} onText={v => { if (Array.isArray(X.table[key])) X.table[key][i] = v; else X.table[key] = v; edited(X); }} />
          : <Area key={i} readOnly value={item == null ? '' : String(item)} />)}
        <Muted>{s.names == null ? t('Takes no names in braces.') : s.names.length ? t('Names the code fills in: {names}', { names: s.names.map((n: string) => '{' + n + '}').join(' ') }) : t('Names the code fills in: none')}</Muted>
        <Group gap="xs">
          {mine && s.inherited != null && <Button size="xs" variant="default" leftSection={<IconHistory size={16} />} onClick={() => { delete X.table[key]; edited(X); }}>{t('Use the default wording again')}</Button>}
          {!mine && <Button size="xs" variant="default" onClick={() => { X.table[key] = clone(inheritedOf(s)); edited(X); }}>{t('Write its own wording for this profile')}</Button>}
          {P.trace && <Button size="xs" variant="default" leftSection={<IconSearch size={16} />} disabled={!!(cell && cell.loading)} onClick={() => fetchShown(X, key, firstText())}>{t('Requests with this text block')}</Button>}
        </Group>
        {cell && fresh && <ShownList cell={cell} redraw={redraw} />}
      </Stack>
    </Paper>
  );
}

function TraceSelect() {
  const logs: any[] = (P.list && P.list.traces) || [];
  if (!logs.length) return <Muted>{(P.list && P.list.traces_note) ? tr(P.list.traces_note) : t('There is no request log.')}</Muted>;
  if (logs.length === 1) return <Text size="sm">{t('Request log')} <Code>{logs[0].name}</Code> <Muted>{mb(logs[0].bytes || 0)}</Muted></Text>;
  return <NativeSelect w="auto" value={P.trace || ''} onChange={e => setTrace(e.currentTarget.value)} data={logs.map(l => ({ value: l.name, label: l.name + ' (' + mb(l.bytes || 0) + ')' }))} />;
}
export { TraceSelect };

export function PhrasesEditor({ X, redraw }: { X: Ph; redraw: () => void }) {
  const d = X.detail;
  return (
    <Stack gap="md">
      <Group gap="sm">
        <Title order={3}>{t('Text blocks of {module}', { module: X.module })}</Title>
        {isDirty(X) && <Badge color="orange" variant="light">{t('unsaved changes')}</Badge>}
      </Group>
      <Muted>{rich(t('File: `{path}`', { path: d.path || '' }))}</Muted>
      {!d.own_file && <Alert color="yellow" icon={<IconInfoCircle />}>{t('This profile has no file of its own for this module yet and uses the text blocks of the profile it builds on. Saving a text block writes a file of its own, and the profile uses that file from then on.')}</Alert>}
      <Group><Text fw={600}>{t('Request log')}</Text><TraceSelect /></Group>
      {(d.sentences || []).map((s: any) => <SentenceRow key={s.key} X={X} s={s} redraw={redraw} />)}
      <Actions x={X} />
      <Reports x={X} />
    </Stack>
  );
}
