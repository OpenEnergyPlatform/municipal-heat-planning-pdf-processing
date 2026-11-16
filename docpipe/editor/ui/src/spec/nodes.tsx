/* The boxes and arrows of a field's drawing (layout.ts places them): a list of the ontology a dimension takes its entries
   from, the field's units, the field with a row for each thing it asks, and the entries of the dimension chosen with the
   words of the plans each one gathers. A word is dragged onto another entry to move it there. */
import { BaseEdge, EdgeLabelRenderer, getBezierPath, Handle, Position, type EdgeProps, type NodeProps } from '@xyflow/react';
import { Badge, Button, Code, Group, Text, Tooltip } from '@mantine/core';
import { t, tn } from '../lib/i18n';
import { isObj } from '../lib/util';
import { termOf, VALUE, type Special } from './model';
import { nameOf, named } from './names';
import type { ArrowData, EntryData, FieldData, FrameData, LabelData, MoreData, RootData, Row, UnitData } from './layout';
import { ROW_H, HEAD_H } from './layout';
import { pickList, S, select, toggleOpen, wordMoved } from './state';

export const WORD = 'application/x-docpipe-spec-word';
const hidden = { opacity: 0, width: 1, height: 1, minWidth: 1, minHeight: 1, border: 0 };

export function LabelNode({ data }: NodeProps) {
  const d = data as LabelData;
  const text = d.kind === 'ontology' ? t('From the ontology') : d.kind === 'field' ? t('What the field asks of each value') : t('The entries the model chooses from');
  return <Text size="sm" fw={700} c="dimmed" tt="uppercase" className="sp-label">{text}</Text>;
}

export function RootNode({ data }: NodeProps) {
  const d = data as RootData;
  const o = d.origin;
  return (
    <div className={'sp-box sp-root' + (d.selected ? ' is-sel' : '')} onClick={() => select({ t: 'root', set: d.set })}>
      <Group gap={6} wrap="nowrap" justify="space-between">
        <Text fw={650} size="sm" lineClamp={1}>{o.root.label || o.root.root}</Text>
        <Code>{o.root.root}</Code>
      </Group>
      <Text size="xs" c="dimmed">{tn(o.root.members.length, '{n} term of the ontology under it', '{n} terms of the ontology under it')}</Text>
      <Text size="xs">{t('Gives {names} {under} of its entries', { names: d.feeds.map(nameOf).join(', '), under: o.under.length })}</Text>
      <Handle id="out" type="source" position={Position.Right} style={hidden} />
    </div>
  );
}

const nf = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 6 });

export function UnitsNode({ data }: NodeProps) {
  const d = data as UnitData;
  const shown = d.units.slice(0, 6);
  const perPeriod = d.units.filter(u => u.perPeriod).map(u => u.unit);
  const label = (S.pin[d.target] && S.pin[d.target].label) || d.target;
  return (
    <div className={'sp-box sp-units' + (d.selected ? ' is-sel' : '')} onClick={() => select({ t: 'units', uri: d.uri })}>
      <Text fw={650} size="sm">{t('Units')}</Text>
      <Text size="xs" c="dimmed" lineClamp={1}>{t('Every number is converted into {unit}.', { unit: label })}</Text>
      <Text size="xs" lineClamp={2}>{shown.map(u => u.factor == null ? u.unit : `${u.unit} × ${nf(u.factor)}`).join(' · ')}{d.units.length > shown.length ? ' · …' : ''}</Text>
      {perPeriod.length ? <Text size="xs" c="dimmed" lineClamp={1}>{t('Per year: {units}', { units: perPeriod.slice(0, 4).join(', ') })}</Text> : null}
      <Handle id="out" type="source" position={Position.Right} style={hidden} />
    </div>
  );
}

const SPECIAL_WORDS = (): Record<Special, string> => ({
  own_passage: t('only where the value stands'), own_value: t('once with the number'), frame: t('frame of the plan'),
});
function rowSays(r: Row): string {
  if (r.kind === 'unit') return tn(r.count, '{n} unit', '{n} units');
  if (r.kind === 'list') return r.origin
    ? t('{n} entries, {under} of them from the ontology', { n: r.count, under: r.origin.under.length })
    : tn(r.count, '{n} entry of the spec\'s own', '{n} entries of the spec\'s own');
  if (r.kind === 'per_document') return t('a list for each document');
  if (r.kind === 'number') return t('a number');
  if (r.kind === 'words') return t('the words of the plan');
  if (r.kind === 'choice') return tn(r.count, 'one of {n} words', 'one of {n} words');
  return '';
}

export function FieldNode({ data }: NodeProps) {
  const d = data as FieldData;
  const f = d.field;
  const head = (
    <div className={'sp-field-head' + (d.selected === 'field' ? ' is-sel' : '')} style={{ height: HEAD_H }} onClick={() => select({ t: 'param', uri: d.uri })}>
      <Group gap={6} wrap="nowrap" justify="space-between">
        <Text fw={700} lineClamp={1}>{f.label || d.uri}</Text>
        <Badge variant="light" tt="none">{String(f.value_type || 'float')}</Badge>
      </Group>
      <Code>{d.uri}</Code>
      <Text size="xs" c="dimmed" lineClamp={2}>{typeof f.brief === 'string' ? f.brief : typeof f.description === 'string' ? f.description : ''}</Text>
    </div>
  );
  return (
    <div className="sp-box sp-field">
      {head}
      {d.rows.map(r => {
        const sel = d.selected === 'row:' + r.name;
        const about = named(r.name).about;
        return (
          <div key={r.name} className={'sp-row' + (d.pick === r.name ? ' is-pick' : '') + (sel ? ' is-sel' : '')} style={{ height: ROW_H }}
            onClick={e => {
              e.stopPropagation();
              if (r.kind === 'unit') select({ t: 'units', uri: d.uri });
              else if (r.name === VALUE) { pickList(d.uri, r.name); select({ t: 'param', uri: d.uri }); }
              else { if (r.kind === 'list') pickList(d.uri, r.name); select({ t: 'axis', uri: d.uri, name: r.name }); }
            }}>
            <Handle id={'r:' + r.name} type="target" position={Position.Left} style={hidden} />
            <Tooltip label={about} disabled={!about} multiline w={320} openDelay={400}>
              <div className="sp-row-text">
                <Group gap={6} wrap="nowrap">
                  <Text size="sm" fw={600} lineClamp={1}>{nameOf(r.name)}</Text>
                  {r.shared ? <Badge size="xs" variant="light" color="indigo" tt="none">{t('shared')}</Badge> : null}
                  {r.derived ? <Badge size="xs" variant="light" color="orange" tt="none">{r.derived.byUnit ? t('from the unit') : t('under a condition')}</Badge> : null}
                  {r.specials.map(s => <Badge key={s} size="xs" variant="outline" color="gray" tt="none">{SPECIAL_WORDS()[s]}</Badge>)}
                </Group>
                <Text size="xs" c="dimmed" lineClamp={1}>{rowSays(r)}</Text>
              </div>
            </Tooltip>
            <Handle id={'s:' + r.name} type="source" position={Position.Right} style={hidden} />
          </div>
        );
      })}
    </div>
  );
}

export function FrameNode({ data }: NodeProps) {
  const d = data as FrameData;
  return (
    <div className="sp-frame">
      <Handle id="in" type="target" position={Position.Left} style={hidden} />
      <Text fw={650} size="sm">{t('Entries of {name}', { name: nameOf(d.name) })}</Text>
      <Text size="xs" c="dimmed">{d.shown < d.count ? t('{shown} of {count} shown: those the plans have words for', { shown: d.shown, count: d.count }) : tn(d.count, '{n} entry', '{n} entries')}</Text>
    </div>
  );
}

export function EntryNode({ data }: NodeProps) {
  const d = data as EntryData;
  const e = d.entry;
  const term = S.pin[e.id];
  return (
    <div className={'sp-box sp-entry' + (d.selected ? ' is-sel' : '')}
      onClick={() => select({ t: 'entry', uri: d.where.uri, name: d.where.name, key: d.where.key, id: e.id })}
      onDragOver={ev => { if (ev.dataTransfer.types.includes(WORD)) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'move'; } }}
      onDrop={ev => {
        const raw = ev.dataTransfer.getData(WORD);
        if (!raw) return;
        ev.preventDefault(); ev.stopPropagation();
        const w = JSON.parse(raw);
        wordMoved(d.where, w.from, w.word, e.id);
      }}>
      <Group gap={6} wrap="nowrap" justify="space-between">
        <Text fw={650} size="sm" lineClamp={1}>{e.label || e.id}</Text>
        {d.own ? <Badge size="xs" variant="light" color="gray" tt="none">{t('own entry')}</Badge>
          : <Text size="xs" c="dimmed" lineClamp={1}>{(isObj(term) && term.label ? term.label + ' · ' : '') + termOf(e.id)}</Text>}
      </Group>
      {e.words.length ? (
        <div className="sp-words">
          {e.words.map(w => (
            <span key={w} className="sp-word nodrag" draggable title={t('Drag onto another entry to move the word there.')}
              onDragStart={ev => { ev.stopPropagation(); ev.dataTransfer.setData(WORD, JSON.stringify({ from: e.id, word: w })); ev.dataTransfer.effectAllowed = 'move'; }}>{w}</span>
          ))}
        </div>
      ) : <Text size="xs" c="dimmed">{t('No word of the plans')}</Text>}
    </div>
  );
}

export function MoreNode({ data }: NodeProps) {
  const d = data as MoreData;
  return (
    <div className="sp-box sp-more">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm">{d.open ? t('Shown with the others: entries without a word of the plans') : tn(d.count, '{n} more entry without a word of the plans', '{n} more entries without a word of the plans')}</Text>
        <Button size="compact-xs" variant="light" onClick={e => { e.stopPropagation(); toggleOpen(); }}>{d.open ? t('Fold') : t('Show')}</Button>
      </Group>
    </div>
  );
}

export function SpecEdge(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd } = props;
  const d = props.data as ArrowData;
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  let text = '';
  if (d.kind === 'root') text = t('gives the entries');
  else if (d.kind === 'derive' && d.derived) text = t('without an answer: {entry}', { entry: d.label });
  return (
    <>
      <BaseEdge path={path} markerEnd={markerEnd} className={'sp-edge sp-edge-' + d.kind} />
      {text ? (
        <EdgeLabelRenderer>
          <div className={'sp-edge-label sp-edge-label-' + d.kind} style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}>{text}</div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

export const NODE_TYPES = { label: LabelNode, root: RootNode, units: UnitsNode, field: FieldNode, frame: FrameNode, entry: EntryNode, more: MoreNode };
export const EDGE_TYPES = { spec: SpecEdge };
