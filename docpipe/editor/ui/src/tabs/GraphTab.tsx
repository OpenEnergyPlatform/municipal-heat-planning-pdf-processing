/* The Graph tab: what the written graph keeps (GET /api/graph): the rules of the program that writes it, and one card per class of the
   shapes with its name, its properties, the fields that write each property and what each constraint does. The tab
   is one file on purpose; the cards read and change `cur` in place, and Check and Save send it whole. */
import { useEffect, useReducer, useRef } from 'react';
import {
  Accordion, ActionIcon, Alert, Anchor, Badge, Button, Code, Group, Loader, NativeSelect, Paper, ScrollArea, Stack, Switch, Table,
  Text, Tooltip,
} from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconCheck, IconDeviceFloppy, IconPencil, IconX } from '@tabler/icons-react';
import { api, apiR } from '../lib/api';
import { showError, showInfo } from '../lib/dialogs';
import { loadState, openSpec, setDirty, useTabActions } from '../lib/nav';
import { clone, isObj, same, wrote } from '../lib/util';
import { rich, t, tr } from '../lib/i18n';
import { Report, type Reported } from '../components/Report';
import { TextBox } from '../components/Inputs';
import { GroupedRules } from '../rules/RuleInputs';
import { Put } from '../prompts/Reports';

const graphData = (d: any) => ({
  classes: clone(d.set.classes || {}) as Record<string, any>,
  constraints: clone(d.set.constraints || {}) as Record<string, string>,
  rules: Object.fromEntries(d.rules.map((r: any) => [r.name, clone(r.value)])) as Record<string, any>,
});
type Cur = ReturnType<typeof graphData>;
interface Ctx { data: any; cur: Cur; probe: any; changed: (redraw?: boolean) => void }

export function GraphTab() {
  const R = useRef({
    data: null as any, cur: null as Cur | null, report: null as Reported | null, probe: null as any,
    busy: false as boolean | string, db: '', epoch: 0, error: null as string | null,
  });
  const [, touch] = useReducer((x: number) => x + 1, 0);
  const GR = R.current;
  const isDirty = !!GR.data && !same(GR.cur, graphData(GR.data));

  async function load() {
    try { GR.data = await api('GET', '/api/graph'); GR.cur = graphData(GR.data); GR.error = null; GR.epoch++; }
    catch (e) { GR.error = (e as Error).message; }
    touch();
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setDirty('graph', isDirty); });

  const changed = () => { GR.report = null; touch(); };

  async function send(what: 'check' | 'save') {
    if (GR.busy || !GR.data) return;
    if (what === 'save' && !isDirty) return;
    GR.busy = true; touch();
    try {
      const r = await apiR('/api/graph/' + what, what === 'save' ? { data: GR.cur, base: GR.data.base } : { data: GR.cur });
      if (what === 'save' && r.saved) {
        showInfo(t('Saved {file} ({writes}).', { file: r.file, writes: wrote(r.writes) }));
        GR.busy = false;
        loadState().catch(showError);
        await load();
        return;
      }
      GR.report = { source: what, r: Object.assign({}, r, { errors: (r.errors || []).map((e: any) => typeof e === 'string' ? { name: null, message: e } : e) }) };
    } catch (e) { GR.report = { source: what, error: (e as Error).message }; }
    GR.busy = false; touch();
  }
  useTabActions('graph', { check: () => send('check'), save: () => send('save') });

  async function probe() {
    if (GR.busy) return;
    GR.busy = 'probe'; touch();
    try { GR.probe = await api('POST', '/api/graph/probe', { data: GR.cur, db: GR.db || null }); }
    catch (e) { showError(e); }
    GR.busy = false; touch();
  }

  if (GR.error) return <Alert color="red" m="md">{GR.error}</Alert>;
  if (!GR.data || !GR.cur) return <Group justify="center" p="xl"><Loader /></Group>;
  const d = GR.data, cur = GR.cur;
  const ctx: Ctx = { data: d, cur, probe: GR.probe, changed };
  const P = GR.probe && GR.probe.differs;
  const known = new Set((d.classes || []).map((c: any) => c.id));
  const extra = GR.probe ? Object.keys(GR.probe.saved.classes || {}).filter(k => !known.has(k)) : [];

  return (
    <Stack gap={0} style={{ flex: 1, minHeight: 0 }}>
      <Group px="md" py="sm" justify="space-between" wrap="nowrap" style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
        <Group gap="sm">
          <Code>{d.file}</Code>
          {!d.exists && <Text size="sm" c="dimmed">{t('not written yet')}</Text>}
        </Group>
        <Group gap="xs" wrap="nowrap">
          <TextBox w={300} placeholder={t('corpus database (default: the profile\'s)')} mono value={GR.db}
            onText={text => { GR.db = text; }} />
          <Tooltip label={t('Writes the graph of the harvest of this page twice into the temp directory, once with the saved file and once with your edits, and compares the two. Nothing in the profile changes.')}>
            <Button variant="light" loading={GR.busy === 'probe'} disabled={!!GR.busy} onClick={probe}>{t('Test write')}</Button>
          </Tooltip>
          <Button variant="default" leftSection={<IconCheck size={16} />} disabled={!!GR.busy} onClick={() => send('check')}>{t('Check')}</Button>
          <Button leftSection={<IconDeviceFloppy size={16} />} disabled={!!GR.busy || !isDirty} onClick={() => send('save')}>{t('Save')}</Button>
          <Button variant="subtle" disabled={!isDirty} onClick={() => { GR.cur = graphData(d); GR.report = null; GR.epoch++; touch(); }}>{t('Discard')}</Button>
        </Group>
      </Group>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Stack p="md" gap="md">
          <Text size="sm" c="dimmed">{rich(tr(d.cost) + ' ' + tr(d.gate))}</Text>
          <Report R={GR.report} onReload={load} />
          {P ? (
            <Paper withBorder radius="md" p="md">
              <Stack gap="xs">
                <Text fw={700}>{rich(t('Test write in `{folder}`', { folder: GR.probe.folder }))}</Text>
                <Text size="sm">{P.also
                  ? t('triples {before} → {after}, nodes given a new name: {renamed}; also written under another property of the spec: {also}', { before: P.triples.before, after: P.triples.after, renamed: P.readdressed, also: P.also })
                  : t('triples {before} → {after}, nodes given a new name: {renamed}', { before: P.triples.before, after: P.triples.after, renamed: P.readdressed })}</Text>
                <Accordion variant="contained">
                  <Accordion.Item value="docs">
                    <Accordion.Control>{t('documents that differ ({n})', { n: P.documents.length })}</Accordion.Control>
                    <Accordion.Panel>
                      <Stack gap={2}>
                        {P.documents.map((x: any) => (
                          <Text size="sm" key={x.document}>{x.after.left_out && x.after.left_out.length
                            ? <Put text={t('{doc}: nodes {nb} → {na}, violations {vb} → {va}, left out: {left}')} slots={{ doc: <Code>{x.document}</Code>, nb: x.before.kept || 0, na: x.after.kept || 0, vb: x.before.violations || 0, va: x.after.violations || 0, left: x.after.left_out.map((l: any) => l.constraint).join('; ') }} />
                            : <Put text={t('{doc}: nodes {nb} → {na}, violations {vb} → {va}')} slots={{ doc: <Code>{x.document}</Code>, nb: x.before.kept || 0, na: x.after.kept || 0, vb: x.before.violations || 0, va: x.after.violations || 0 }} />}</Text>
                        ))}
                      </Stack>
                    </Accordion.Panel>
                  </Accordion.Item>
                  <Accordion.Item value="viol">
                    <Accordion.Control>{t('violations by constraint')}</Accordion.Control>
                    <Accordion.Panel>
                      <Stack gap={2}>
                        {(P.violations || []).map((v: any) => <Text size="sm" key={v.key}><Code>{v.key}</Code>: {v.before} → {v.after}</Text>)}
                      </Stack>
                    </Accordion.Panel>
                  </Accordion.Item>
                </Accordion>
              </Stack>
            </Paper>
          ) : null}

          <Text fw={700} size="lg">{t('Rules of the program that writes the graph')}</Text>
          <GroupedRules rules={d.rules} epoch={GR.epoch} curOf={n => cur.rules[n]}
            onChange={(n, v, reset) => { cur.rules[n] = v; if (reset) GR.epoch++; changed(); }} />

          <Text fw={700} size="lg">{t('Classes of the shapes, the fields that write each property, and what each constraint does')}</Text>
          {d.skipped ? <Text size="sm" c="dimmed">{rich(tr(d.skipped))}</Text>
            : (d.classes || []).map((c: any) => <ClassCard key={c.id} c={c} ctx={ctx} />)}

          <Text fw={700} size="lg">{t('Classes the program writes that no shape names')}</Text>
          {extra.length
            ? extra.map(k => <ClassCard key={k} c={{ id: k, shape: null, label: null, properties: [] }} ctx={ctx} />)
            : <Text size="sm" c="dimmed">{GR.probe ? t('none') : t('They are listed once a test write has been run.')}</Text>}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}

function ConstraintChip({ c, ctx }: { c: any; ctx: Ctx }) {
  const { cur, data, probe, changed } = ctx;
  const P = probe && probe.differs;
  const said = P ? (P.violations || []).find((v: any) => v.key === c.key) : null;
  const says = Array.isArray(c.says) ? c.says.join(', ') : String(c.says);
  return (
    <Group gap={6} wrap="nowrap" title={c.key}>
      <Text size="sm" c={said && said.after ? 'red' : undefined}>{c.component + ' ' + says}</Text>
      <NativeSelect size="xs" value={cur.constraints[c.key] || 'report'} data={data.effects || []}
        onChange={e => {
          const v = e.currentTarget.value;
          if (v === 'report') delete cur.constraints[c.key]; else cur.constraints[c.key] = v;
          changed();
        }} />
      {said ? <Text size="sm" c="dimmed">{t('violations {before} → {after}', { before: said.before, after: said.after })}</Text> : null}
    </Group>
  );
}

function ClassCard({ c, ctx }: { c: any; ctx: Ctx }) {
  const { cur, probe, changed } = ctx;
  const set = cur.classes[c.id] || {};
  const written = set.written !== false;
  const addr = set.address || null;
  const folder: string = addr && addr.folder != null ? String(addr.folder) : '';
  const keys: string[] = addr && Array.isArray(addr.key) ? addr.key.slice() : [];
  const offered: { value: string; label: string }[] = (c.properties || []).map((p: any) => ({ value: p.path, label: p.path + (p.label ? ' (' + p.label + ')' : '') }));

  const setWritten = (on: boolean) => {
    const s = cur.classes[c.id] = Object.assign({}, cur.classes[c.id]);
    if (on) delete s.written; else s.written = false;
    if (!Object.keys(s).length) delete cur.classes[c.id];
    changed();
  };
  const setAddr = (folderText: string, ks: string[]) => {
    const s = cur.classes[c.id] = Object.assign({}, cur.classes[c.id]);
    const was = s.address && isObj(s.address) ? s.address : {};
    if (!folderText.trim() && !ks.length) delete s.address;
    else s.address = Object.assign({}, was, { folder: folderText.trim(), key: ks.slice() });   // a base the file says stays
    if (!Object.keys(s).length) delete cur.classes[c.id];
    changed();
  };
  const keyChoice = (value: string, onPick: (v: string) => void, none: string, w = 260) => {
    const opts = offered.slice();
    if (value && !opts.some(o => o.value === value)) opts.push({ value, label: value });
    return <NativeSelect w={w} size="xs" value={value} onChange={e => onPick(e.currentTarget.value)}
      data={[{ value: '', label: none }, ...opts]} />;
  };
  const P = probe && probe.differs;
  const n = P && P.classes ? P.classes[c.id] : null;

  return (
    <Paper withBorder radius="md" p="md" style={written ? undefined : { opacity: 0.6 }}>
      <Stack gap="sm">
        <Group gap="sm" wrap="wrap">
          <Switch checked={written} label={t('written')} onChange={e => setWritten(e.currentTarget.checked)} />
          <Text fw={700}>{c.label || c.id}</Text>
          <Code>{c.id}</Code>
          {c.shape ? <Text size="sm" c="dimmed">{t('shape {shape}', { shape: c.shape })}</Text> : null}
          {n ? <Badge variant="light">{t('{before} → {after} nodes', { before: n.before, after: n.after })}</Badge> : null}
        </Group>
        <Group gap="xs" align="center">
          <Text size="sm">{t('node name: folder')}</Text>
          <TextBox w={220} size="xs" mono placeholder={t('as the program names it')} value={folder} onText={text => setAddr(text, keys)} />
          <Text size="sm">{t('made of the values of')}</Text>
          {keys.map((k, i) => (
            <Group key={i} gap={2} wrap="nowrap">
              {keyChoice(k, v => { const ks = keys.slice(); if (v) ks[i] = v; else ks.splice(i, 1); setAddr(folder, ks); }, t('(remove)'))}
              <ActionIcon variant="subtle" size="sm" disabled={i === 0} aria-label={t('Earlier')}
                onClick={() => { const ks = keys.slice(); [ks[i - 1], ks[i]] = [ks[i], ks[i - 1]]; setAddr(folder, ks); }}><IconArrowUp size={14} /></ActionIcon>
              <ActionIcon variant="subtle" size="sm" disabled={i === keys.length - 1} aria-label={t('Later')}
                onClick={() => { const ks = keys.slice(); [ks[i + 1], ks[i]] = [ks[i], ks[i + 1]]; setAddr(folder, ks); }}><IconArrowDown size={14} /></ActionIcon>
              <ActionIcon variant="subtle" size="sm" color="red" aria-label={t('Remove')}
                onClick={() => { const ks = keys.slice(); ks.splice(i, 1); setAddr(folder, ks); }}><IconX size={14} /></ActionIcon>
            </Group>
          ))}
          {offered.length || keys.length
            ? keyChoice('', v => { if (v) setAddr(folder, keys.concat([v])); }, t('+ property'), 200)
            : <Text size="sm" c="dimmed">{t('no properties in the shapes')}</Text>}
        </Group>
        {(c.properties || []).length > 0 && (
          <Table withTableBorder className="dp-formtable">
            <Table.Tbody>
              {c.properties.map((p: any) => (
                <Table.Tr key={p.path}>
                  <Table.Td w="30%"><Code>{p.path}</Code>{p.label ? <Text size="sm" c="dimmed">{p.label}</Text> : null}</Table.Td>
                  <Table.Td w="30%">
                    {p.fields.length
                      ? <Stack gap={2}>{p.fields.map((f: string) => (
                          <Tooltip key={f} label={t('Open the field in the Spec tab')}>
                            <Anchor component="button" type="button" size="sm" ta="left" onClick={() => openSpec({ t: 'param', uri: f })}>
                              <IconPencil size={12} style={{ verticalAlign: -1 }} /> ← {f}
                            </Anchor>
                          </Tooltip>))}</Stack>
                      : <Text size="sm" c="dimmed">{t('no field')}</Text>}
                  </Table.Td>
                  <Table.Td><Stack gap={4}>{(p.constraints || []).map((k: any) => <ConstraintChip key={k.key} c={k} ctx={ctx} />)}</Stack></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Paper>
  );
}
