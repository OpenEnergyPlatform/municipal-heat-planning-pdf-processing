/* The right column: the requests of a request log, the chosen one drawn as a chat, and Try
   (old renderRight, renderFilters, renderReqList, renderChat, renderTry, tryNodes). */
import type { ReactNode } from 'react';
import { Alert, Anchor, Badge, Button, Code, Collapse, Group, Loader, NativeSelect, SimpleGrid, Stack, Switch, Text, TextInput } from '@mantine/core';
import { IconChevronDown, IconChevronRight, IconPlayerPlay } from '@tabler/icons-react';
import { Muted } from '../components/Bits';
import { rich, t, tn, tr } from '../lib/i18n';
import { addrs, lineKey, prettyAnswer, reqLabel, reqSub } from './logic';
import { P, doTry, page, selectRequest, setFilter, setText, bump } from './store';
import { TraceSelect } from './Editors';
import './prompts.css';

export function RightColumn() {
  const note = (text: string) => <Muted>{text}</Muted>;
  if (!P.list) return null;
  if (!P.sel) return note(t('Pick a prompt to see the requests of the request log that use it.'));
  if (P.sel.t === 'phrases') return note(t('Requests are shown beside a prompt. To see the requests that use a text block, choose a request log in the editor of the text block and press "Requests with this text block".'));
  const kinds = ((P.list.prompts || []).find((x: any) => x.id === (P.sel as any).id) || {}).kinds || [];
  if (!kinds.length) return note(t('No request in the request log uses this prompt on its own, so there is no request to preview. Choose another request log or another prompt.'));
  if (!P.req) return note(P.list.traces_note ? tr(P.list.traces_note) : t('There is no request to show.'));
  return (
    <Stack gap="md">
      <Group><Text fw={600}>{t('Request log')}</Text><TraceSelect /></Group>
      <Filters />
      <ReqList />
      <TryBox />
      <Chat />
    </Stack>
  );
}

function Filters() {
  const R = P.req!;
  const o = R.opts || { kinds: [], fields: [], carried: [] };
  const sel = (label: string, opts: string[], value: string, k: 'kind' | 'field' | 'carries') => (
    <NativeSelect aria-label={label} title={label} value={opts.includes(value) ? value : ''} onChange={e => setFilter(k, e.currentTarget.value)}
      data={[{ value: '', label: t('{label}: any', { label }) }, ...opts.map(x => ({ value: x, label: x }))]} />
  );
  return (
    <Stack gap="xs">
      <SimpleGrid cols={3} spacing="xs">
        {sel(t('kind'), o.kinds, R.kind, 'kind')}
        {sel(t('field'), o.fields, R.field, 'field')}
        {sel(t('message carries'), o.carried, R.carries, 'carries')}
      </SimpleGrid>
      <TextInput placeholder={t('text anywhere in the request or its answer')} spellCheck={false} value={R.text} onChange={e => setText(e.currentTarget.value)} />
    </Stack>
  );
}

function ReqList() {
  const R = P.req!;
  const L = R.listing;
  if (R.listErr) return <Alert color="red">{R.listErr}</Alert>;
  if (!L) return <Group gap="xs"><Loader size="xs" /><Muted>{t('Reading the request log. The first time this takes several seconds…')}</Muted></Group>;
  const reqs: any[] = L.requests || [];
  const m = L.matching == null ? reqs.length : L.matching;
  return (
    <Stack gap="xs">
      <Muted>{R.listLoading ? t('{m} of {total} requests · updating…', { m, total: L.total }) : t('{m} of {total} requests', { m, total: L.total })}</Muted>
      <div className="pr-reqlist">
        {reqs.map(r => (
          <button key={r.index} type="button" className={'pr-req' + (R.sel === r.index ? ' sel' : '')} onClick={() => selectRequest(r.index)}>
            <b>{reqLabel(r)}</b><small>{reqSub(r)}</small><small>{r.check || ''}</small>
          </button>
        ))}
        {!reqs.length && <Text size="sm" c="dimmed" p="sm">{t('No request matches.')}</Text>}
      </div>
      <Group gap="xs">
        <Button size="xs" variant="default" disabled={R.offset <= 0 || R.listLoading} onClick={() => page(Math.max(0, R.offset - 100))}>{t('Previous')}</Button>
        <Text size="sm" c="dimmed">{m ? t('{from}–{to} of {m}', { from: R.offset + 1, to: R.offset + reqs.length, m }) : ''}</Text>
        <Button size="xs" variant="default" disabled={R.offset + 100 >= m || R.listLoading} onClick={() => page(R.offset + 100)}>{t('Next')}</Button>
      </Group>
    </Stack>
  );
}

/* ---------- the chat ---------- */

function ValNodes({ v, hit, ind }: { v: any; hit: Set<string>; ind: number }): ReactNode {
  const pad = '  '.repeat(ind);
  if (Array.isArray(v)) {
    if (v.length && v.every(x => typeof x === 'string')) {
      return <>{v.map((s, i) => { const k = lineKey(s); return <span key={i} className={'pr-ln' + (k && hit.has(k) ? ' hit' : '')}>{s}</span>; })}</>;
    }
    return <>{v.map((x, i) => <ValNodes key={i} v={x} hit={hit} ind={ind} />)}</>;
  }
  if (v && typeof v === 'object') {
    return <>{Object.entries(v).map(([k, x]) => {
      const sub = !!x && typeof x === 'object';
      return (
        <span key={k}>
          <span className="pr-ln"><span className="pr-key">{pad + k + ':'}</span>{sub ? null : ' ' + x}</span>
          {sub && <ValNodes v={x} hit={hit} ind={ind + 1} />}
        </span>
      );
    })}</>;
  }
  return <span className="pr-ln">{pad + v}</span>;
}
function UserNodes({ text, hit }: { text: string; hit: Set<string> }) {
  let o: any = null;
  try { o = JSON.parse(text); } catch { o = null; }
  if (o && typeof o === 'object') return <ValNodes v={o} hit={hit} ind={0} />;
  return <>{String(text).split('\n').map((line, i) => { const k = lineKey(line); return <span key={i} className={'pr-ln' + (k && hit.has(k) ? ' hit' : '')}>{line}</span>; })}</>;
}

function Bubble({ role, cls, children }: { role: string; cls: string; children: ReactNode }) {
  return <div className={'pr-msg ' + cls}><div className="pr-role">{role}</div>{children}</div>;
}

function Chat() {
  const R = P.req!;
  if (R.sel == null) return <Muted>{t('Pick a request to see it as a chat. Your unsaved changes are already in the text shown.')}</Muted>;
  if (!R.pv) return R.pvErr ? <Alert color="red">{R.pvErr}</Alert> : <Group gap="xs"><Loader size="xs" /><Muted>{t('Loading request #{n}…', { n: String(R.sel) })}</Muted></Group>;
  const pv = R.pv, rec = pv.recorded || {}, p = pv.preview || null, notes = pv.notes || {};
  const hit = addrs(rec.answer_json);
  const msgs: any[] = Array.isArray(rec.messages) ? rec.messages : [];
  const usable = !!p && !p.why && !!p.edit;
  let instruction: ReactNode;
  if (!usable || R.showSent) instruction = rec.system || '';
  else if ((p.lines || []).length) {
    instruction = p.lines.map((line: any, i: number) => (
      <span key={i} className="pr-ln">{(line || []).map((pair: any, j: number) => <span key={j} className={pair && pair[1] ? 'dp-changed' : undefined}>{pair ? pair[0] : ''}</span>)}</span>));
  } else instruction = (p.edit && p.edit.system) || '';
  const gone = usable && !R.showSent && (p.gone || []).length > 0;
  const first = msgs[0] ? String(msgs[0][1] == null ? '' : msgs[0][1]) : '';
  const userText = pv.kind === 'follow' && usable && typeof p.edit.user === 'string' ? p.edit.user : first;
  return (
    <Stack gap="xs">
      <Text fw={600}>{reqLabel({ kind: pv.kind, parameter: notes.parameter, coordinate: notes.coordinate, asked: pv.asked })}</Text>
      <Muted>{'#' + pv.index + (notes.doc != null ? ' · ' + t('document {n}', { n: String(notes.doc) }) : '') + ' · ' + reqSub(notes) + (R.pvLoading ? ' · ' + t('updating…') : '')}</Muted>
      {R.pvErr && <Alert color="red">{R.pvErr}</Alert>}
      {Array.isArray(pv.chain) && pv.chain.length > 1 && (
        <Text size="sm" c="dimmed">{t('Requests of the same value:')} {pv.chain.map((i: number) => (
          <span key={i}>{i === pv.index ? <b>#{i}</b> : <Anchor component="button" type="button" size="sm" onClick={() => selectRequest(i)}>#{i}</Anchor>}{' '}</span>))}</Text>
      )}
      {p && p.why && <Alert color="yellow">{rich(tr(p.why))} {t('The request is shown as it was sent.')}</Alert>}
      {p && !p.why && p.same_as_recorded && <Muted>{t('The files on disk give this request character for character.')}</Muted>}
      {p && !p.why && !p.same_as_recorded && p.example === 'lines' && <Muted>{t('The run sent this request with other wording of this prompt, so its example answer is taken from the request log and not from the prompt.')}</Muted>}
      {p && !p.why && p.changed === false && R.pvEdited && <Alert color="yellow">{t('Your change does not reach this request.')}</Alert>}
      {usable && <Switch label={t('Show the instruction as it was sent')} checked={R.showSent} onChange={e => { R.showSent = e.currentTarget.checked; bump(); }} />}

      <div className="pr-msg system">
        <Anchor component="button" type="button" className="pr-role" c="dimmed" onClick={() => { R.sysOpen = !R.sysOpen; bump(); }} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {R.sysOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />} {t('instruction')}
        </Anchor>
        <Collapse expanded={R.sysOpen}>
          <div>{instruction}</div>
          {gone && (
            <div className="pr-gonebox">
              <div className="pr-role">{t('removed by your change')}</div>
              {p.gone.map((s: string, i: number) => <div key={i} className="dp-gone">{s}</div>)}
            </div>
          )}
        </Collapse>
      </div>
      <Bubble role={t('request')} cls="user"><UserNodes text={userText} hit={hit} /></Bubble>
      {msgs.slice(1).map((m, i) => <Bubble key={i} role={t('{role} (this attempt)', { role: m[0] })} cls={m[0] === 'assistant' ? 'assistant' : 'user'}>{String(m[1] == null ? '' : m[1])}</Bubble>)}
      <Bubble role={rec.finish ? t('answer · {finish}', { finish: rec.finish }) : t('answer')} cls="assistant">{rec.answer == null ? (rec.error || t('no answer')) : prettyAnswer(rec)}</Bubble>
      <Bubble role={t('result')} cls="check">{rec.check || ''}</Bubble>
    </Stack>
  );
}

/* ---------- Try: the only place that sends anything to a model, one click each ---------- */

const lineWhy = (why: string): string => why === 'not_an_address' ? t('names no shown line') : why === 'words_not_in_line' ? t('its words do not stand in the line it names') : why;

function TryBox() {
  const R = P.req!;
  const T = (P.list && P.list.try) || {};
  const listed: any[] = R.listing && R.listing.requests ? R.listing.requests : [];
  const n = Math.min(T.limit || 3, listed.length);
  const run = P.tryRes;
  const off = !T.configured || !!(run && run.running);
  const why = T.configured ? (T.model ? (T.host ? t('Model {model} on {host}', { model: T.model, host: T.host }) : t('Model {model}', { model: T.model })) : '') : t('Not available: {why}', { why: T.why ? tr(T.why) : t('no model is configured.') });
  return (
    <Stack gap="xs">
      <Text fw={600}>{t('Try')}</Text>
      <Group gap="xs">
        <Button size="xs" leftSection={<IconPlayerPlay size={16} />} disabled={off || R.sel == null} onClick={() => doTry([R.sel!])}>{t('Try on this request (sends 1 request)')}</Button>
        <Button size="xs" leftSection={<IconPlayerPlay size={16} />} disabled={off || n < 1} onClick={() => doTry(listed.slice(0, n).map(r => r.index))}>
          {tn(n, 'Try on the first request listed (sends {n} request)', 'Try on the first {n} requests listed (sends {n} requests)')}
        </Button>
      </Group>
      {why && (T.configured ? <Muted>{why}</Muted> : <Alert color="yellow">{why}</Alert>)}
      {run && run.running && <Alert color="gray" icon={<Loader size="xs" />}>{tn(run.n, 'Sending {n} request to {host}…', 'Sending {n} requests to {host}…', { host: T.host || t('the model') })}</Alert>}
      {run && !run.running && run.err && <Alert color="red">{run.err}</Alert>}
      {run && !run.running && run.res && <TryResults res={run.res} listed={listed} />}
    </Stack>
  );
}

function TryResults({ res, listed }: { res: any; listed: any[] }) {
  const c = res.counts || {};
  const q = (v: any) => v == null ? '?' : v;
  return (
    <Stack gap="xs">
      <Muted>{t('You chose {named} requests and {sent} were sent, {failed} of them failed. The model gave the same answer {same} times, a different answer {different} times and an answer not in the required form {out_of_form} times. In {pass} requests every line number passes the checks, and in {fail} requests a line number fails.', {
        named: q(c.named), sent: q(c.sent), failed: q(c.failed), same: q(c.same), different: q(c.different), out_of_form: q(c.out_of_form), pass: q(c.addresses_hold), fail: q(c.addresses_fail) })}</Muted>
      {(res.results || []).map((r: any, i: number) => {
        const found = listed.find(x => x.index === r.index);
        const head = <Text><b>#{r.index}</b>{found ? ' ' + reqLabel(found) : ''}</Text>;
        if (!r.sent) return <div key={i} className="pr-pair">{head}<Alert color="yellow">{t('Not sent: {why}', { why: r.why ? tr(r.why) : t('no reason given.') })}</Alert></div>;
        const o = r.old || {}, nw = r.new || {};
        const stats: string[] = [];
        if (nw.ms != null) stats.push(Math.round(nw.ms) + ' ms');
        if (nw.prompt_tokens != null || nw.completion_tokens != null) stats.push((nw.prompt_tokens == null ? '?' : nw.prompt_tokens) + '/' + (nw.completion_tokens == null ? '?' : nw.completion_tokens) + ' tok' + (nw.max_tokens != null ? ' (max ' + nw.max_tokens + ')' : ''));
        if (nw.finish) stats.push(nw.finish);
        return (
          <div key={i} className="pr-pair">
            {head}
            <Group gap={6}>
              {r.same === true && <Badge color="teal" variant="light">{t('the same answer')}</Badge>}
              {r.same === false && <Badge color="yellow" variant="light">{t('a different answer')}</Badge>}
              {nw.in_form === true && <Badge color="teal" variant="light">{t('in the required form')}</Badge>}
              {nw.in_form === false && <Badge color="red" variant="light">{nw.fault ? t('not in the required form ({fault})', { fault: nw.fault }) : t('not in the required form')}</Badge>}
              {r.changed_request === false && <Badge color="gray" variant="light">{t('the edit did not change what was sent')}</Badge>}
              {r.holds === true ? <Badge color="teal" variant="light">{t('every line number passes the checks')}</Badge>
                : r.holds === false ? <Badge color="red" variant="light">{t('a line number fails a check')}</Badge>
                : <Badge color="gray" variant="light">{t('names no line number')}</Badge>}
            </Group>
            <SimpleGrid cols={2} spacing="xs" mt={6}>
              <div><Text size="sm" fw={600}>{t('recorded')}</Text><pre className="pr-out">{prettyAnswer(o) || t('(no answer)')}</pre>{o.check && <Muted>{o.check}</Muted>}</div>
              <div><Text size="sm" fw={600}>{t('new')}</Text><pre className="pr-out">{nw.error ? nw.error : (prettyAnswer(nw) || t('(no answer)'))}</pre>{nw.error && <Muted>{t('The server gave an error.')}</Muted>}</div>
            </SimpleGrid>
            {(r.addresses || []).length > 0 && (
              <Stack gap={2} mt={6}>
                <Text size="sm" fw={600}>{t('line numbers of the new answer')}</Text>
                {r.addresses.map((a: any, j: number) => (
                  <Text key={j} size="sm"><Code>{String(a.at)}</Code>{a.words ? ' “' + a.words + '” ' : ' '}
                    {a.holds === true ? <Badge color="teal" variant="light">{t('passes the checks')}</Badge>
                      : a.holds === false ? <Badge color="red" variant="light">{a.why ? lineWhy(a.why) : t('fails the checks')}</Badge>
                      : <Badge color="gray" variant="light">{t('says that no shown line supports it')}</Badge>}
                  </Text>))}
              </Stack>
            )}
            {stats.length > 0 && <Muted>{stats.join(' · ')}</Muted>}
          </div>
        );
      })}
    </Stack>
  );
}
