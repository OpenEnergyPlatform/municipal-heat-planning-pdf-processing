/* The Sources tab: where the shapes and the ontology come from (GET /api/sources), the lists the answers are chosen from,
   Fetch and Apply, and what the fetched shapes and ontology say otherwise than the spec, which Take puts into the spec. */
import { useEffect, useReducer, useRef, useState } from 'react';
import {
  Accordion, ActionIcon, Alert, Badge, Button, Checkbox, Code, Grid, Group, Loader, NativeSelect, Paper, ScrollArea, Stack, Table,
  Text, Tooltip,
} from '@mantine/core';
import { IconCheck, IconCloudDownload, IconDeviceFloppy, IconPlus, IconTrash } from '@tabler/icons-react';
import { api, apiR } from '../lib/api';
import { askConfirm, askText, showError, showInfo } from '../lib/dialogs';
import { dirtyStore, loadState, openRules, request, setDirty, setTab, useTabActions } from '../lib/nav';
import { clone, same, wrote } from '../lib/util';
import { rich, t, tn, tr } from '../lib/i18n';
import { shortId } from '../lib/spec';
import { AreaBox, TextBox } from '../components/Inputs';
import { Report, type Reported } from '../components/Report';
import { Put } from '../prompts/Reports';

const sourcesData = (d: any) => ({
  sources: clone(Object.fromEntries(d.sources.map((s: any) => [s.name, Object.assign({ kind: s.kind }, s.source)]))) as Record<string, any>,
  lists: clone(Object.fromEntries(d.lists.map((l: any) => [l.name, { kind: l.kind, root: l.root }]))) as Record<string, any>,
  axis_lists: clone(d.axis_lists || {}) as Record<string, string>,
});
type Cur = ReturnType<typeof sourcesData>;
type Pick = { id: string; action: string; into?: string };

export function SourcesTab() {
  const R = useRef({
    data: null as any, cur: null as Cur | null, report: null as Reported | null, fetch: null as any,
    picks: new Map<string, Pick>(), busy: false as boolean | string, error: null as string | null,
  });
  const [, touch] = useReducer((x: number) => x + 1, 0);
  const SR = R.current;
  const isDirty = !!SR.data && !same(SR.cur, sourcesData(SR.data));

  async function load() {
    try { SR.data = await api('GET', '/api/sources'); SR.cur = sourcesData(SR.data); SR.error = null; }
    catch (e) { SR.error = (e as Error).message; }
    touch();
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setDirty('sources', isDirty); });

  const changed = () => { SR.report = null; touch(); };

  async function send(what: 'check' | 'save') {
    if (SR.busy || !SR.data) return;
    if (what === 'save' && !isDirty) return;
    SR.busy = true; touch();
    try {
      const r = await apiR('/api/sources/' + what, what === 'save' ? { data: SR.cur, base: SR.data.base } : { data: SR.cur });
      if (what === 'save' && r.saved) {
        showInfo(t('Saved {file} ({writes}).', { file: r.file, writes: wrote(r.writes) }));
        SR.busy = false;
        loadState().catch(showError);
        await load();
        return;
      }
      SR.report = { source: what, r: Object.assign({}, r, { errors: (r.errors || []).map((e: any) => typeof e === 'string' ? { name: null, message: e } : e) }) };
    } catch (e) { SR.report = { source: what, error: (e as Error).message }; }
    SR.busy = false; touch();
  }
  useTabActions('sources', { check: () => send('check'), save: () => send('save') });

  async function doFetch() {
    if (SR.busy) return;
    SR.busy = 'fetch'; touch();
    try { SR.fetch = await api('POST', '/api/sources/fetch', {}); SR.picks.clear(); }
    catch (e) { showError(e); }
    SR.busy = false; touch();
  }
  async function doApply() {
    if (!SR.fetch || SR.busy) return;
    if (!await askConfirm(t('Apply the fetch'), t('Write the lists of {id} into the profile and its lock into the cache? The spec stays as it is.', { id: SR.fetch.id }), t('Apply'))) return;
    SR.busy = true; touch();
    try {
      const r = await api('POST', '/api/sources/apply', { fetch: SR.fetch.id });
      showInfo(t('Applied {applied}: {profile} of the profile, {cache} into the cache, lock {lock}.', { applied: r.applied, profile: tn(r.profile_files.length, '{n} file', '{n} files'), cache: tn(r.cache_files, '{n} file', '{n} files'), lock: r.lock }));
      SR.fetch = null;
      loadState().catch(showError);
    } catch (e) { showError(e); }
    SR.busy = false; await load();
  }
  async function doTake() {
    if (!SR.picks.size) return;
    if (dirtyStore.get().spec && !await askConfirm(t('Take into the spec'), t('The Spec tab has unsaved edits; the rows you take are applied to the spec as saved on disk and replace them.'), t('Replace my edits'))) return;
    try {
      const r = await api('POST', '/api/sources/take', { chosen: [...SR.picks.values()], fetch: SR.fetch ? SR.fetch.id : null });
      SR.picks.clear(); touch();
      setTab('spec');
      // the Spec tab puts r.data in place of its spec, marks it as edited and clears its last answer
      request('spec', { taken: r.data });
      showInfo(r.refused.length
        ? tn(r.done.length, '{n} change taken into the spec, {refused} refused ({why}). Check and save it in the Spec tab.', '{n} changes taken into the spec, {refused} refused ({why}). Check and save them in the Spec tab.',
          { refused: r.refused.length, why: r.refused.map((x: any) => tr(x.why)).join('; ') })
        : tn(r.done.length, '{n} change taken into the spec. Check and save it in the Spec tab.', '{n} changes taken into the spec. Check and save them in the Spec tab.'));
    } catch (e) { showError(e); }
  }
  const pick = (id: string, action: string | null, into?: string) => {
    if (action) SR.picks.set(id, { id, action, into }); else SR.picks.delete(id);
    touch();
  };

  if (SR.error) return <Alert color="red" m="md">{SR.error}</Alert>;
  if (!SR.data || !SR.cur) return <Group justify="center" p="xl"><Loader /></Group>;
  const d = SR.data, cur = SR.cur;
  const kinds = d.kinds || {};
  const D = SR.fetch ? SR.fetch.differences : d.differences;

  return (
    <Stack gap={0} style={{ flex: 1, minHeight: 0 }}>
      <Group px="md" py="sm" justify="space-between" wrap="nowrap" className="dp-bar" style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
        <Group gap="sm" wrap="wrap">
          <Code>{d.file}</Code>
          {!d.exists && <Text size="sm" c="dimmed">{d.inherited_from ? t('default from profile {name}', { name: d.inherited_from }) : t('not written yet')}</Text>}
          <Text size="sm" c="dimmed">{d.lock.fetched_at ? t('lock: {file}, fetched {at}', { file: d.lock.file, at: d.lock.fetched_at }) : t('lock: {file}, never fetched', { file: d.lock.file })}</Text>
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Button variant="default" onClick={() => openRules('sources')}>{t('Rules')}</Button>
          <Button variant="default" leftSection={<IconCheck size={16} />} disabled={!!SR.busy} onClick={() => send('check')}>{t('Check')}</Button>
          <Button leftSection={<IconDeviceFloppy size={16} />} disabled={!!SR.busy || !isDirty} onClick={() => send('save')}>{t('Save')}</Button>
          <Tooltip label={isDirty ? t('Save the sources first, because a fetch reads the saved file and not your edits.') : t('Downloads every source into a folder of the temp directory and shows what changed against the lists of the profile. Nothing is written to the profile until you press Apply.')}>
            <Button variant="light" leftSection={<IconCloudDownload size={16} />} loading={SR.busy === 'fetch'}
              disabled={!!SR.busy || !d.fetches || isDirty} onClick={doFetch}>{t('Fetch')}</Button>
          </Tooltip>
        </Group>
      </Group>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Stack p="md" gap="md">
          {d.cost && <Text size="sm" c="dimmed">{rich(tr(d.cost))}</Text>}
          <Report R={SR.report} onReload={load} />
          <Grid gap="lg">
            <Grid.Col span={{ base: 12, xl: 7 }}>
              <Stack gap="md">
                <Text fw={700} size="lg">{t('Sources')}</Text>
                {Object.entries(cur.sources).map(([name, src]) => {
                  const shown = d.sources.find((s: any) => s.name === name);
                  const k = kinds[src.kind] || { needs: [], may: [] };
                  return (
                    <Paper key={name} withBorder radius="md" p="md">
                      <Stack gap="xs">
                        <Group justify="space-between" wrap="nowrap" align="flex-start">
                          <Group gap="xs">
                            <Code fw={700}>{name}</Code>
                            <NativeSelect w={150} value={src.kind} data={Object.keys(kinds)}
                              onChange={e => { cur.sources[name] = { kind: e.currentTarget.value }; changed(); }} />
                            {(kinds[src.kind] || {}).stands ? <Badge variant="light" color="gray">{rich(tr(kinds[src.kind].stands))}</Badge> : null}
                            {shown && shown.locked ? <Badge color="teal" variant="light">{t('locked {version}', { version: shown.locked.version || shown.locked.note || '?' })}</Badge>
                              : <Badge color="orange" variant="light">{t('not in the lock')}</Badge>}
                            {shown && shown.token ? <Badge color={shown.token.set ? 'teal' : 'orange'} variant="light">
                              {shown.token.set ? t('{env} is set', { env: shown.token.env }) : t('{env} is not set', { env: shown.token.env })}</Badge> : null}
                          </Group>
                          <Tooltip label={t('Remove this source')}>
                            <ActionIcon variant="subtle" color="red" aria-label={t('Remove this source')}
                              onClick={() => { delete cur.sources[name]; changed(); }}><IconTrash size={18} /></ActionIcon>
                          </Tooltip>
                        </Group>
                        {shown ? <Text size="sm" c="dimmed">{shown.address}</Text> : null}
                        <Table withTableBorder className="dp-formtable">
                          <Table.Tbody>
                            {[...k.needs, ...k.may].map((key: string) => (
                              <Table.Tr key={key}>
                                <Table.Td w="22%"><Code>{key}{k.needs.includes(key) ? ' *' : ''}</Code></Table.Td>
                                <Table.Td><SourceField obj={src} field={key} onChange={changed} /></Table.Td>
                              </Table.Tr>
                            ))}
                          </Table.Tbody>
                        </Table>
                        {shown && shown.locked && (shown.locked.changed_since_reviewed || []).length
                          ? <Alert color="yellow">{t('changed since reviewed: {what}', { what: shown.locked.changed_since_reviewed.join(', ') })}</Alert> : null}
                      </Stack>
                    </Paper>
                  );
                })}

                <Text fw={700} size="lg" mt="sm">{t('Lists')}</Text>
                <Table withTableBorder className="dp-formtable">
                  <Table.Thead><Table.Tr><Table.Th>{t('list')}</Table.Th><Table.Th>{t('kind')}</Table.Th><Table.Th>{t('root')}</Table.Th><Table.Th>{t('entries now')}</Table.Th><Table.Th /></Table.Tr></Table.Thead>
                  <Table.Tbody>
                    {Object.entries(cur.lists).map(([name, l]) => {
                      const now = d.lists.find((x: any) => x.name === name);
                      return (
                        <Table.Tr key={name}>
                          <Table.Td><Code>{name}</Code></Table.Td>
                          <Table.Td><NativeSelect value={l.kind} data={d.list_kinds || ['class', 'individual']}
                            onChange={e => { l.kind = e.currentTarget.value; changed(); }} /></Table.Td>
                          <Table.Td><TextBox mono value={l.root} onText={text => { l.root = text; changed(); }} /></Table.Td>
                          <Table.Td>{now && now.members != null ? String(now.members) : ''}</Table.Td>
                          <Table.Td>
                            <ActionIcon variant="subtle" color="red" aria-label={t('Remove this list')} onClick={() => {
                              delete cur.lists[name];
                              for (const [a, n] of Object.entries(cur.axis_lists)) if (n === name) delete cur.axis_lists[a];
                              changed();
                            }}><IconTrash size={18} /></ActionIcon>
                          </Table.Td>
                        </Table.Tr>
                      );
                    })}
                  </Table.Tbody>
                </Table>

                <Text fw={700} size="lg" mt="sm">{t('Which dimension answers from which list')}</Text>
                <Table withTableBorder className="dp-formtable">
                  <Table.Thead><Table.Tr><Table.Th>{t('dimension')}</Table.Th><Table.Th>{t('answers from the list')}</Table.Th><Table.Th /></Table.Tr></Table.Thead>
                  <Table.Tbody>
                    {Object.entries(cur.axis_lists).map(([axis, name]) => (
                      <Table.Tr key={axis}>
                        <Table.Td><Code>{axis}</Code></Table.Td>
                        <Table.Td><NativeSelect value={name} data={Object.keys(cur.lists)}
                          onChange={e => { cur.axis_lists[axis] = e.currentTarget.value; changed(); }} /></Table.Td>
                        <Table.Td>
                          <ActionIcon variant="subtle" color="red" aria-label={t('Remove this dimension')}
                            onClick={() => { delete cur.axis_lists[axis]; changed(); }}><IconTrash size={18} /></ActionIcon>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>

                <Group gap="xs">
                  <Button variant="default" leftSection={<IconPlus size={16} />} onClick={async () => {
                    const n = await askText(t('Add a source'), t('Name of the source'), '');
                    if (n && !cur.sources[n]) { cur.sources[n] = { kind: 'url' }; changed(); }
                  }}>{t('Add a source')}</Button>
                  <Button variant="default" leftSection={<IconPlus size={16} />} onClick={async () => {
                    const n = await askText(t('Add a list'), t('Name of the list'), '');
                    if (n && !cur.lists[n]) { cur.lists[n] = { kind: 'class', root: '' }; changed(); }
                  }}>{t('Add a list')}</Button>
                  <Button variant="default" leftSection={<IconPlus size={16} />} onClick={async () => {
                    const n = await askText(t('A dimension that answers from a list'), t('Name of the dimension'), '');
                    if (n && Object.keys(cur.lists).length) { cur.axis_lists[n] = Object.keys(cur.lists)[0]; changed(); }
                  }}>{t('Add a dimension')}</Button>
                </Group>
              </Stack>
            </Grid.Col>

            <Grid.Col span={{ base: 12, xl: 5 }}>
              <Stack gap="md">
                {SR.fetch ? <FetchBox f={SR.fetch} busy={!!SR.busy} onApply={doApply}
                  onDrop={() => { SR.fetch = null; SR.picks.clear(); touch(); }} /> : null}
                <Text fw={700} size="lg">{SR.fetch ? t('Where the fetched shapes and ontology differ from the spec')
                  : t('Where the shapes and the ontology differ from the spec')}</Text>
                <Differences key={SR.fetch ? SR.fetch.id : 'saved'} D={D} picks={SR.picks} pick={pick} onTake={doTake} />
              </Stack>
            </Grid.Col>
          </Grid>
        </Stack>
      </ScrollArea>
    </Stack>
  );
}

/* one field of a source: an empty text removes the key, lists are one line each */
function SourceField({ obj, field, onChange }: { obj: Record<string, any>; field: string; onChange: () => void }) {
  if (field === 'until_released') {
    return <Checkbox checked={!!obj[field]} label={t('until released')}
      onChange={e => { if (e.currentTarget.checked) obj[field] = true; else delete obj[field]; onChange(); }} />;
  }
  if (field === 'files' || field === 'paths' || field === 'query') {
    return <AreaBox mono minRows={field === 'query' ? 6 : 3} value={field === 'query' ? (obj[field] || '') : (obj[field] || []).join('\n')}
      onText={t => { obj[field] = field === 'query' ? t : t.split('\n').map(s => s.trim()).filter(Boolean); onChange(); }} />;
  }
  return <TextBox mono value={obj[field] == null ? '' : String(obj[field])}
    onText={t => { if (t === '') delete obj[field]; else obj[field] = t; onChange(); }} />;
}

function FetchBox({ f, busy, onApply, onDrop }: { f: any; busy: boolean; onApply: () => void; onDrop: () => void }) {
  const moved = (f.sources || []).filter((s: any) => s.moved);
  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="xs">
        <Text fw={700}>{rich(t('Fetched into `{id}`', { id: f.id }))}</Text>
        {moved.length
          ? moved.map((s: any) => <Text key={s.name} size="sm"><Code>{s.name}</Code>: {s.before || t('(none)')} → {s.after || s.note || t('(none)')}</Text>)
          : <Text size="sm" c="dimmed">{t('No source changed.')}</Text>}
        {(f.lists || []).length > 0 && (
          <Accordion variant="contained" multiple>
            {(f.lists || []).map((l: any) => (
              <Accordion.Item key={l.list} value={l.list}>
                <Accordion.Control>{t('{list}: {before} → {after} entries ({added} new, {gone} gone, {renamed} renamed, {redefined} with a new definition)', { list: l.list, before: l.before, after: l.after, added: l.added.length, gone: l.gone.length, renamed: l.renamed.length, redefined: l.redefined.length })}</Accordion.Control>
                <Accordion.Panel>
                  <Stack gap={2}>
                    {l.added.map((x: any) => <Text size="sm" key={'a' + x.id}>+ <Code>{x.id}</Code> {x.label || ''}</Text>)}
                    {l.gone.map((x: any) => <Text size="sm" key={'g' + x.id}>− <Code>{x.id}</Code> {x.label || ''}</Text>)}
                    {l.renamed.map((x: any) => <Text size="sm" key={'r' + x.id}><Code>{x.id}</Code>: {x.from} → {x.to}</Text>)}
                    {l.redefined.map((x: any) => <Text size="sm" key={'d' + x.id}><Put text={t('{id} ({label}) has a new definition')} slots={{ id: <Code>{x.id}</Code>, label: x.label || '' }} /></Text>)}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            ))}
          </Accordion>
        )}
        {(f.files || []).filter((x: any) => x.changed).map((x: any) => (
          <Text size="sm" key={x.file}><Put text={x.entries ? t('{file}: {before} → {after} entries') : t('{file}: changed')} slots={{ file: <Code>{x.file}</Code>, before: x.entries ? x.entries.before : '', after: x.entries ? x.entries.after : '' }} /></Text>
        ))}
        <Group gap="xs">
          <Tooltip label={t('Writes the lists of this fetch into the profile and its lock into the cache. The Spec stays as it is.')}>
            <Button disabled={busy} onClick={onApply}>{t('Apply')}</Button>
          </Tooltip>
          <Button variant="default" onClick={onDrop}>{t('Drop this fetch')}</Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function Differences({ D, picks, pick, onTake }: {
  D: any; picks: Map<string, Pick>; pick: (id: string, action: string | null, into?: string) => void; onTake: () => void;
}) {
  if (!D) return <Text size="sm" c="dimmed">{t('No spec to compare.')}</Text>;
  if (D.skipped) return <Text size="sm" c="dimmed">{t('Not compared: {why}', { why: tr(D.skipped) })}</Text>;
  const targets: { into: string; label: string }[] = D.targets || [];
  const openFields = D.fields.filter((f: any) => f.rows.some((r: any) => (r.actions || []).length)).map((f: any) => f.field);
  return (
    <Stack gap="sm">
      <Accordion multiple variant="separated" radius="md" defaultValue={[...openFields, ...(D.unasked.length ? ['__unasked'] : [])]}>
        {D.fields.map((f: any) => (
          <Accordion.Item key={f.field} value={f.field}>
            <Accordion.Control><Code>{f.field}</Code> {tn(f.rows.length, '{n} difference', '{n} differences')}</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">{f.rows.map((r: any, i: number) => <DiffRow key={i} r={r} picks={picks} pick={pick} />)}</Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
        {D.unasked.length ? (
          <Accordion.Item value="__unasked">
            <Accordion.Control>{t('Properties of the shapes that no field asks for ({n})', { n: D.unasked.length })}</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">{D.unasked.map((r: any) => <UnaskedRow key={r.id} r={r} targets={targets} pick={pick} />)}</Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ) : null}
      </Accordion>
      <Group gap="sm">
        <Button disabled={!picks.size} onClick={onTake}>{t('Take into the spec')}</Button>
        <Text size="sm" c="dimmed">{t('The Spec is not changed here. Rows you take over are applied in the Spec tab, where they are checked and saved and where the cost of the change is shown.')}</Text>
      </Group>
    </Stack>
  );
}

function DiffRow({ r, picks, pick }: { r: any; picks: Map<string, Pick>; pick: (id: string, action: string | null, into?: string) => void }) {
  return (
    <Stack gap={4}>
      <Group gap={6}>
        <Badge variant="light" color="gray">{r.kind}</Badge>
        {r.axis ? <Badge variant="light" color="gray">{r.axis}</Badge> : null}
        <Code>{r.path || ''}</Code>
        <Text size="sm">{rich(tr(r.detail))}</Text>
      </Group>
      {(r.entries || []).length > 0 && (
        <Stack gap={4} pl="md">
          {r.entries.map((e: any) => (
            <Tooltip key={e.id} label={e.definition || (e.why ? tr(e.why) : '')} disabled={!(e.definition || e.why)} multiline maw={420}>
              <Checkbox disabled={!e.takes} checked={picks.has(e.id)} onChange={c => pick(e.id, c.currentTarget.checked ? 'add' : null)}
                label={<><Code>{shortId(e.iri)}</Code> {e.label || t('(not in the pinned ontology)')}</>} />
            </Tooltip>
          ))}
        </Stack>
      )}
      {r.kind && r.kind.startsWith('definition_') && (
        <Stack gap={4} pl="md">
          <Checkbox checked={picks.has(r.id)} onChange={c => pick(r.id, c.currentTarget.checked ? 'replace' : null)} label={t('take the ontology\'s definition')} />
          <Text size="sm" c="dimmed">{t('spec: {text}', { text: r.spec || t('(none)') })}</Text>
          <Text size="sm" c="dimmed">{t('ontology: {text}', { text: r.ontology || '' })}</Text>
        </Stack>
      )}
    </Stack>
  );
}

function UnaskedRow({ r, targets, pick }: { r: any; targets: { into: string; label: string }[]; pick: (id: string, action: string | null, into?: string) => void }) {
  const [act, setAct] = useState('');
  const [into, setInto] = useState(targets.length ? targets[0].into : '');
  const set = (a: string, i: string) => pick(r.id, a || null, a === 'merge' ? i : undefined);
  return (
    <Stack gap={4}>
      <Group gap={6}><Code>{r.shape + '.' + r.path}</Code><Text size="sm" c="dimmed">{rich(tr(r.detail))}</Text></Group>
      <Group gap="xs">
        <NativeSelect value={act} onChange={e => { setAct(e.currentTarget.value); set(e.currentTarget.value, into); }}
          data={[{ value: '', label: '—' }, { value: 'new_field', label: t('new field (draft)') }, { value: 'merge', label: t('also write a field under it') }]} />
        {act === 'merge' && (
          <NativeSelect value={into} title={t('Chooses what is also written under this property: a field, the unit of a field or a dimension of a field.')}
            onChange={e => { setInto(e.currentTarget.value); set(act, e.currentTarget.value); }}
            data={targets.map(x => ({ value: x.into, label: x.label }))} />
        )}
      </Group>
    </Stack>
  );
}
