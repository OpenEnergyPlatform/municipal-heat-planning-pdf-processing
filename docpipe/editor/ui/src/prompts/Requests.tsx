/* The right column: the recorded requests of a trace, the chosen one drawn as a chat, and Try
   (old renderRight, renderFilters, renderReqList, renderChat, renderTry, tryNodes). */
import type { ReactNode } from 'react';
import { Alert, Anchor, Badge, Button, Code, Collapse, Group, Loader, NativeSelect, SimpleGrid, Stack, Switch, Text, TextInput } from '@mantine/core';
import { IconChevronDown, IconChevronRight, IconPlayerPlay } from '@tabler/icons-react';
import { Muted } from '../components/Bits';
import { plural } from '../lib/util';
import { addrs, lineKey, prettyAnswer, reqLabel, reqSub } from './logic';
import { P, doTry, page, selectRequest, setFilter, setText, bump } from './store';
import { TraceSelect } from './Editors';
import './prompts.css';

export function RightColumn() {
  const note = (t: string) => <Muted>{t}</Muted>;
  if (!P.list) return null;
  if (!P.sel) return note('Pick a prompt to see the recorded requests it has a say in.');
  if (P.sel.t === 'phrases') return note('Recorded requests are shown beside a prompt. For a sentence, choose a trace in its editor and press "Recorded requests with this sentence".');
  const kinds = ((P.list.prompts || []).find((x: any) => x.id === (P.sel as any).id) || {}).kinds || [];
  if (!kinds.length) return note('No request of a harvest is recorded with this prompt alone, so there is no preview.');
  if (!P.req) return note(P.list.traces_note || 'There is no recorded request to show.');
  return (
    <Stack gap="md">
      <Group><Text fw={600}>Recorded requests</Text><TraceSelect /></Group>
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
      data={[{ value: '', label: label + ': any' }, ...opts.map(x => ({ value: x, label: x }))]} />
  );
  return (
    <Stack gap="xs">
      <SimpleGrid cols={3} spacing="xs">
        {sel('kind', o.kinds, R.kind, 'kind')}
        {sel('field', o.fields, R.field, 'field')}
        {sel('message carries', o.carried, R.carries, 'carries')}
      </SimpleGrid>
      <TextInput placeholder="text anywhere in the request or its answer" spellCheck={false} value={R.text} onChange={e => setText(e.currentTarget.value)} />
    </Stack>
  );
}

function ReqList() {
  const R = P.req!;
  const L = R.listing;
  if (R.listErr) return <Alert color="red">{R.listErr}</Alert>;
  if (!L) return <Group gap="xs"><Loader size="xs" /><Muted>Reading the trace. The first time this takes several seconds…</Muted></Group>;
  const reqs: any[] = L.requests || [];
  const m = L.matching == null ? reqs.length : L.matching;
  return (
    <Stack gap="xs">
      <Muted>{m + ' of ' + L.total + ' requests' + (R.listLoading ? ' · updating…' : '')}</Muted>
      <div className="pr-reqlist">
        {reqs.map(r => (
          <button key={r.index} type="button" className={'pr-req' + (R.sel === r.index ? ' sel' : '')} onClick={() => selectRequest(r.index)}>
            <b>{reqLabel(r)}</b><small>{reqSub(r)}</small><small>{r.check || ''}</small>
          </button>
        ))}
        {!reqs.length && <Text size="sm" c="dimmed" p="sm">No request matches.</Text>}
      </div>
      <Group gap="xs">
        <Button size="xs" variant="default" disabled={R.offset <= 0 || R.listLoading} onClick={() => page(Math.max(0, R.offset - 100))}>Previous</Button>
        <Text size="sm" c="dimmed">{m ? (R.offset + 1) + '–' + (R.offset + reqs.length) + ' of ' + m : ''}</Text>
        <Button size="xs" variant="default" disabled={R.offset + 100 >= m || R.listLoading} onClick={() => page(R.offset + 100)}>Next</Button>
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
  if (R.sel == null) return <Muted>Pick a request to see it as a chat, with your unsaved changes in it.</Muted>;
  if (!R.pv) return R.pvErr ? <Alert color="red">{R.pvErr}</Alert> : <Group gap="xs"><Loader size="xs" /><Muted>Loading request #{R.sel}…</Muted></Group>;
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
      <Muted>{'#' + pv.index + (notes.doc != null ? ' · doc ' + notes.doc : '') + ' · ' + reqSub(notes) + (R.pvLoading ? ' · updating…' : '')}</Muted>
      {R.pvErr && <Alert color="red">{R.pvErr}</Alert>}
      {Array.isArray(pv.chain) && pv.chain.length > 1 && (
        <Text size="sm" c="dimmed">Requests of the same value: {pv.chain.map((i: number) => (
          <span key={i}>{i === pv.index ? <b>#{i}</b> : <Anchor component="button" type="button" size="sm" onClick={() => selectRequest(i)}>#{i}</Anchor>}{' '}</span>))}</Text>
      )}
      {p && p.why && <Alert color="yellow">{p.why} The request is shown as it was sent.</Alert>}
      {p && !p.why && p.same_as_recorded && <Muted>The files on disk give this request character for character.</Muted>}
      {p && !p.why && !p.same_as_recorded && p.example === 'lines' && <Muted>This request was sent with other words of this prompt; its example reply is taken from the record.</Muted>}
      {p && !p.why && p.changed === false && R.pvEdited && <Alert color="yellow">Your change does not reach this request.</Alert>}
      {usable && <Switch label="Show the instruction as it was sent" checked={R.showSent} onChange={e => { R.showSent = e.currentTarget.checked; bump(); }} />}

      <div className="pr-msg system">
        <Anchor component="button" type="button" className="pr-role" c="dimmed" onClick={() => { R.sysOpen = !R.sysOpen; bump(); }} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {R.sysOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />} instruction
        </Anchor>
        <Collapse expanded={R.sysOpen}>
          <div>{instruction}</div>
          {gone && (
            <div className="pr-gonebox">
              <div className="pr-role">removed by your change</div>
              {p.gone.map((s: string, i: number) => <div key={i} className="dp-gone">{s}</div>)}
            </div>
          )}
        </Collapse>
      </div>
      <Bubble role="request" cls="user"><UserNodes text={userText} hit={hit} /></Bubble>
      {msgs.slice(1).map((m, i) => <Bubble key={i} role={m[0] + ' (this attempt)'} cls={m[0] === 'assistant' ? 'assistant' : 'user'}>{String(m[1] == null ? '' : m[1])}</Bubble>)}
      <Bubble role={'answer' + (rec.finish ? ' · ' + rec.finish : '')} cls="assistant">{rec.answer == null ? (rec.error || 'no answer') : prettyAnswer(rec)}</Bubble>
      <Bubble role="result" cls="check">{rec.check || ''}</Bubble>
    </Stack>
  );
}

/* ---------- Try: the only place that sends anything to a model, one click each ---------- */

const addrWhy: Record<string, string> = { not_an_address: 'names no shown line', words_not_in_line: 'its words do not stand in the line it names' };

function TryBox() {
  const R = P.req!;
  const T = (P.list && P.list.try) || {};
  const listed: any[] = R.listing && R.listing.requests ? R.listing.requests : [];
  const n = Math.min(T.limit || 3, listed.length);
  const tr = P.tryRes;
  const off = !T.configured || !!(tr && tr.running);
  const why = T.configured ? (T.model ? 'Model ' + T.model + (T.host ? ' on ' + T.host : '') : '') : 'Not available: ' + (T.why || 'no model is configured.');
  return (
    <Stack gap="xs">
      <Text fw={600}>Try</Text>
      <Group gap="xs">
        <Button size="xs" leftSection={<IconPlayerPlay size={16} />} disabled={off || R.sel == null} onClick={() => doTry([R.sel!])}>Try on this request (sends 1 request)</Button>
        <Button size="xs" leftSection={<IconPlayerPlay size={16} />} disabled={off || n < 1} onClick={() => doTry(listed.slice(0, n).map(r => r.index))}>
          {'Try on the first ' + n + ' listed (sends ' + plural(n, 'request') + ')'}
        </Button>
      </Group>
      {why && (T.configured ? <Muted>{why}</Muted> : <Alert color="yellow">{why}</Alert>)}
      {tr && tr.running && <Alert color="gray" icon={<Loader size="xs" />}>Sending {plural(tr.n, 'request')} to {T.host || 'the model'}…</Alert>}
      {tr && !tr.running && tr.err && <Alert color="red">{tr.err}</Alert>}
      {tr && !tr.running && tr.res && <TryResults res={tr.res} listed={listed} />}
    </Stack>
  );
}

function TryResults({ res, listed }: { res: any; listed: any[] }) {
  const c = res.counts || {};
  const q = (v: any) => v == null ? '?' : v;
  return (
    <Stack gap="xs">
      <Muted>{'Named ' + q(c.named) + ', sent ' + q(c.sent) + ', failed ' + q(c.failed) + '; the same answer ' + q(c.same) + ', a different answer ' + q(c.different) +
        ', not in the reply\'s form ' + q(c.out_of_form) + '; addresses that hold ' + q(c.addresses_hold) + ', that fail ' + q(c.addresses_fail) + '.'}</Muted>
      {(res.results || []).map((r: any, i: number) => {
        const found = listed.find(x => x.index === r.index);
        const head = <Text><b>#{r.index}</b>{found ? ' ' + reqLabel(found) : ''}</Text>;
        if (!r.sent) return <div key={i} className="pr-pair">{head}<Alert color="yellow">Not sent: {r.why || 'no reason given.'}</Alert></div>;
        const o = r.old || {}, nw = r.new || {};
        const stats: string[] = [];
        if (nw.ms != null) stats.push(Math.round(nw.ms) + ' ms');
        if (nw.prompt_tokens != null || nw.completion_tokens != null) stats.push((nw.prompt_tokens == null ? '?' : nw.prompt_tokens) + '/' + (nw.completion_tokens == null ? '?' : nw.completion_tokens) + ' tok' + (nw.max_tokens != null ? ' (max ' + nw.max_tokens + ')' : ''));
        if (nw.finish) stats.push(nw.finish);
        return (
          <div key={i} className="pr-pair">
            {head}
            <Group gap={6}>
              {r.same === true && <Badge color="teal" variant="light">the same answer</Badge>}
              {r.same === false && <Badge color="yellow" variant="light">a different answer</Badge>}
              {nw.in_form === true && <Badge color="teal" variant="light">in the reply's form</Badge>}
              {nw.in_form === false && <Badge color="red" variant="light">{'not in the reply\'s form' + (nw.fault ? ' (' + nw.fault + ')' : '')}</Badge>}
              {r.changed_request === false && <Badge color="gray" variant="light">the edit did not change what was sent</Badge>}
              {r.holds === true ? <Badge color="teal" variant="light">every address holds</Badge>
                : r.holds === false ? <Badge color="red" variant="light">an address fails</Badge>
                : <Badge color="gray" variant="light">names no address</Badge>}
            </Group>
            <SimpleGrid cols={2} spacing="xs" mt={6}>
              <div><Text size="sm" fw={600}>recorded</Text><pre className="pr-out">{prettyAnswer(o) || '(no answer)'}</pre>{o.check && <Muted>{o.check}</Muted>}</div>
              <div><Text size="sm" fw={600}>new</Text><pre className="pr-out">{nw.error ? nw.error : (prettyAnswer(nw) || '(no answer)')}</pre>{nw.error && <Muted>The server gave an error.</Muted>}</div>
            </SimpleGrid>
            {(r.addresses || []).length > 0 && (
              <Stack gap={2} mt={6}>
                <Text size="sm" fw={600}>addresses of the new answer</Text>
                {r.addresses.map((a: any, j: number) => (
                  <Text key={j} size="sm"><Code>{String(a.at)}</Code>{a.words ? ' “' + a.words + '” ' : ' '}
                    {a.holds === true ? <Badge color="teal" variant="light">holds</Badge>
                      : a.holds === false ? <Badge color="red" variant="light">{a.why ? (addrWhy[a.why] || a.why) : 'does not hold'}</Badge>
                      : <Badge color="gray" variant="light">says that no shown line holds it</Badge>}
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
