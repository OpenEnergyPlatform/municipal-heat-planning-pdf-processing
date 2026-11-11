/* How a field of the harvest, a box and an arrow look on the canvas of the Graph tab. A box shows the properties its
   class has in the shapes that an arrow writes or that are required; the rest open with "more". A required property no
   arrow leads to is red. */
import { createContext, useContext } from 'react';
import { BaseEdge, EdgeLabelRenderer, getBezierPath, Handle, Position, type EdgeProps, type NodeProps } from '@xyflow/react';
import { ActionIcon, Badge, Box, Group, Menu, Text, Tooltip } from '@mantine/core';
import {
  IconAlertTriangle, IconChevronDown, IconChevronUp, IconDots, IconEyeOff, IconFunction, IconPlus, IconSettings, IconTrash,
} from '@tabler/icons-react';
import { t, tn, tr, useLang } from '../lib/i18n';
import { boxTitle, isRed, type BoxData, type EdgeData, type FieldData, type GraphData, type Row } from './model';

export interface GraphCtx {
  selectBox(id: string): void;
  selectArrow(key: string): void;
  toggleRows(id: string): void;
  addNodeArrow(boxId: string, curie: string): void;
  removeBox(id: string): void;
  does(brick: string): string;
  d: GraphData;
}
export const Ctx = createContext<GraphCtx | null>(null);
const useCtx = () => useContext(Ctx)!;

const KIND_COLOR: Record<string, string> = { field: 'teal', dimension: 'indigo', reading: 'gray' };
const dot = { width: 10, height: 10, minWidth: 10, minHeight: 10, border: '2px solid var(--mantine-color-body)' };

export function LabelNode({ data }: NodeProps) {
  return <Text size="xs" fw={700} tt="uppercase" c="dimmed" pt={10}>{String((data as { text: string }).text)}</Text>;
}

export function FieldNode({ data, selected }: NodeProps) {
  useLang();
  const f = (data as FieldData).f;
  const color = KIND_COLOR[f.kind] || 'gray';
  const sub = f.example
    ? <Text size="xs" c="dimmed" lineClamp={1} fs="italic" title={f.example.value}>{f.example.value}</Text>
    : f.kind === 'dimension' && f.of && f.of.length
      ? <Text size="xs" c="dimmed" lineClamp={1}>{t('of {parameters}', { parameters: f.of.join(', ') })}</Text>
      : null;
  return (
    <Box className={'gr-field' + (selected ? ' gr-sel' : '')} style={{ ['--gr-c' as string]: `var(--mantine-color-${color}-6)` }} data-field={f.name}
      title={f.help || undefined}>
      <Text fw={600} size="sm" lineClamp={1}>{f.label}</Text>
      {sub}
      <Handle id="out" type="source" position={Position.Right} style={{ ...dot, background: `var(--mantine-color-${color}-6)` }} />
    </Box>
  );
}

function RowView({ r, box, bad }: { r: Row; box: BoxData['box']; bad: boolean }) {
  const c = useCtx();
  const red = isRed(r);
  const own = r.used.find(a => a.from === a.to);
  const effects = (r.prop ? r.prop.constraints : []).filter(k => k.effect && k.effect !== 'report');
  return (
    <Box className={'gr-row' + (red ? ' gr-red' : '') + (r.outside ? ' gr-outside' : '')} data-row={r.curie}>
      <Handle id={'t:' + r.curie} type="target" position={Position.Left} className="gr-h" style={dot} />
      <Group gap={6} wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
        <Text size="sm" lineClamp={1} fw={r.used.length ? 600 : 400} c={red ? 'red' : r.used.length ? undefined : 'dimmed'} title={r.curie}>{r.label}</Text>
        {r.required && <Tooltip label={red ? t('Required by the shapes, and no arrow leads to it yet') : t('Required by the shapes')}><Badge size="xs" color={red ? 'red' : 'gray'} variant={red ? 'filled' : 'light'}>{t('required')}</Badge></Tooltip>}
        {r.outside && <Tooltip label={t('The shapes do not give this class this property.')}><IconAlertTriangle size={14} color="var(--mantine-color-orange-6)" /></Tooltip>}
        {effects.length > 0 && <Tooltip label={effects.map(k => k.component + ': ' + tr(k.effect)).join('\n')} multiline><Badge size="xs" variant="outline" color="orange">{effects.length}</Badge></Tooltip>}
      </Group>
      {r.uuid && <Tooltip label={t('Written from the number of the address of the node.')}><Badge size="sm" variant="light" color="violet">{t('own number')}</Badge></Tooltip>}
      {own && (
        <Tooltip label={c.does(typeof own.brick === 'string' ? own.brick : own.brick ? own.brick.brick : '') || t('Written from the node itself.')} multiline w={280}>
          <Badge size="sm" variant="light" color={bad ? 'red' : 'violet'} leftSection={<IconFunction size={12} />} style={{ cursor: 'pointer' }}
            onClick={e => { e.stopPropagation(); c.selectArrow(`${own.from}>${own.to} ${own.property}`); }}>{t('from the node')}</Badge>
        </Tooltip>
      )}
      {!own && !r.used.length && !r.uuid && (
        <Tooltip label={t('Write this property from the node itself, with a brick')}>
          <ActionIcon className="gr-row-add nodrag" size="xs" variant="subtle" aria-label={t('Write this property from the node itself, with a brick')}
            onClick={e => { e.stopPropagation(); c.addNodeArrow(String(box.id), r.curie); }}><IconPlus size={14} /></ActionIcon>
        </Tooltip>
      )}
      <Handle id={'s:' + r.curie} type="source" position={Position.Right} className="gr-h" style={dot} />
    </Box>
  );
}

export function BoxNode({ data, selected }: NodeProps) {
  useLang();
  const c = useCtx();
  const d = data as BoxData;
  const b = d.box;
  const off = b.written === false;
  const title = boxTitle(c.d, b);
  return (
    <Box className={'gr-box' + (selected || d.selected ? ' gr-sel' : '') + (d.bad ? ' gr-bad' : '') + (off ? ' gr-off' : '')} data-box={b.id}>
      <Box className="gr-head" onClick={() => c.selectBox(String(b.id))}>
        <Handle id="in" type="target" position={Position.Left} className="gr-h" style={dot} />
        <Group gap={8} wrap="nowrap" justify="space-between">
          <Box style={{ minWidth: 0 }}>
            <Text fw={650} size="md" lineClamp={1}>{title}</Text>
            <Text size="xs" c="dimmed" lineClamp={2} title={d.sub}>{d.sub}</Text>
          </Box>
          <Group gap={4} wrap="nowrap">
            {off && <Tooltip label={t('This box is not written into the graph')}><IconEyeOff size={16} /></Tooltip>}
            {d.missing > 0 && <Tooltip label={tn(d.missing, '{n} required property has no arrow', '{n} required properties have no arrow')}><Badge color="red" size="sm" circle>{d.missing}</Badge></Tooltip>}
            {(d.bad || d.badArrows.length > 0) && <Tooltip label={t('The check found a problem here')}><IconAlertTriangle size={16} color="var(--mantine-color-red-6)" /></Tooltip>}
            <Menu withinPortal shadow="md" position="bottom-end">
              <Menu.Target>
                <ActionIcon variant="subtle" size="sm" className="nodrag" aria-label={t('Menu of the box')} onClick={e => e.stopPropagation()}><IconDots size={16} /></ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item leftSection={<IconSettings size={16} />} onClick={() => c.selectBox(String(b.id))}>{t('Settings of the box')}</Menu.Item>
                <Menu.Item color="red" leftSection={<IconTrash size={16} />} onClick={() => c.removeBox(String(b.id))}>{t('Remove the box')}</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </Box>
      {d.shown.map(r => <RowView key={r.curie} r={r} box={b} bad={d.badArrows.some(k => r.used.some(a => `${a.from}>${a.to} ${a.property}` === k))} />)}
      {d.foldable && (
        <Box className="gr-more nodrag" onClick={() => c.toggleRows(String(b.id))}>
          <Group gap={6} justify="center">
            {d.expanded ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />}
            <Text size="xs" c="dimmed">{d.expanded ? t('Show only the properties in use') : tn(d.hidden, 'Show {n} more property of the class', 'Show {n} more properties of the class')}</Text>
          </Group>
        </Box>
      )}
    </Box>
  );
}

export function ArrowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected, markerEnd }: EdgeProps) {
  useLang();
  const c = useCtx();
  const d = data as EdgeData;
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const cls = 'gr-edge gr-edge-' + d.kind + (selected ? ' gr-edge-sel' : '') + (d.bad ? ' gr-edge-bad' : '');
  const hint = d.brick ? c.does(d.brick) : '';
  return (
    <>
      <BaseEdge id={id} path={path} className={cls} interactionWidth={22} markerEnd={d.kind === 'of' ? undefined : markerEnd} />
      {(d.text || d.brick) && (
        <EdgeLabelRenderer>
          <Group gap={4} wrap="nowrap" className="gr-edge-label nodrag nopan" style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
            onClick={() => d.key && c.selectArrow(d.key)}>
            {d.brick && <Tooltip label={hint} multiline w={280} disabled={!hint}><IconFunction size={14} /></Tooltip>}
            {d.text && <Text size="xs" lineClamp={1}>{d.text}</Text>}
          </Group>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
