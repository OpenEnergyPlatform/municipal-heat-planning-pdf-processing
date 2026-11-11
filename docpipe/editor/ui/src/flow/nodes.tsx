/* How a step, a loop, round or branching, the head of a branch and an arrow look on the canvas. */
import { createContext, useContext, type ReactNode } from 'react';
import { BaseEdge, EdgeLabelRenderer, getStraightPath, Handle, Position, type EdgeProps, type NodeProps } from '@xyflow/react';
import { ActionIcon, Badge, Box, Group, Text, Tooltip } from '@mantine/core';
import {
  IconArrowsSort, IconBookmark, IconChecks, IconChevronDown, IconChevronRight, IconFileText, IconFlag, IconGitBranch,
  IconMessageQuestion, IconPlayerPlay, IconPlus, IconRefresh, IconRepeat, IconScissors, IconFlagCheck,
} from '@tabler/icons-react';
import type { EdgeData, StepData } from './layout';
import type { Library } from './model';
import { libBox } from './model';
import { num, t, tn, tr, useLang } from '../lib/i18n';

/* the groups of the library: their colour and sign (their word is groupWord) */
export const GROUPS: Record<string, { color: string; icon: (p: { size?: number }) => ReactNode }> = {
  start: { color: 'teal', icon: p => <IconPlayerPlay {...p} /> },
  prepare: { color: 'cyan', icon: p => <IconScissors {...p} /> },
  order: { color: 'blue', icon: p => <IconArrowsSort {...p} /> },
  ask: { color: 'indigo', icon: p => <IconMessageQuestion {...p} /> },
  check: { color: 'grape', icon: p => <IconChecks {...p} /> },
  remember: { color: 'violet', icon: p => <IconBookmark {...p} /> },
  state: { color: 'orange', icon: p => <IconFlag {...p} /> },
  end: { color: 'green', icon: p => <IconFlagCheck {...p} /> },
};
/* the word of a group of the library; a group the page does not know is shown by its key */
export const groupWord = (key: string): string => ({
  start: t('Start'), prepare: t('Prepare'), order: t('Search'), ask: t('Ask the model'), check: t('Check'),
  remember: t('Remember'), state: t('State'), end: t('End'),
} as Record<string, string>)[key] || key;
/* loops, rounds and branchings: their colour and sign (their word is frameWord) */
export const FRAMES: Record<string, { color: string; icon: (p: { size?: number }) => ReactNode }> = {
  each: { color: 'gray', icon: p => <IconRepeat {...p} /> },
  round: { color: 'yellow', icon: p => <IconRefresh {...p} /> },
  if: { color: 'pink', icon: p => <IconGitBranch {...p} /> },
};
export const frameWord = (kind: string): string => ({ each: t('Loop'), round: t('Round'), if: t('Branching') } as Record<string, string>)[kind] || kind;

export interface FlowCtx {
  lib: Library;
  never: Record<string, string>;
  toggle(id: string): void;
  add(list: string, at: number): void;
}
export const Ctx = createContext<FlowCtx | null>(null);
const useCtx = () => useContext(Ctx)!;

const hidden = { opacity: 0, pointerEvents: 'none' as const, width: 1, height: 1, minWidth: 1, minHeight: 1, border: 0 };
const Handles = () => (
  <>
    <Handle type="target" position={Position.Top} isConnectable={false} style={hidden} />
    <Handle type="source" position={Position.Bottom} isConnectable={false} style={hidden} />
  </>
);

function lookOf(c: FlowCtx, d: StepData) {
  if (d.kind === 'box') {
    const b = libBox(c.lib, d.step.box);
    const g = GROUPS[b ? b.group : ''] || { color: 'gray', icon: (p: { size?: number }) => <IconFileText {...p} /> };
    const word = b ? groupWord(b.group) : '';
    return { ...g, sub: b && b.asks ? t('prompt: {prompt}', { prompt: b.asks }) : (b ? word : t('unknown step')), never: tr(c.never[d.step.box] || '') };
  }
  const f = FRAMES[d.kind] || FRAMES.each;
  return { ...f, sub: t('{n} inside', { n: d.inside ?? 0 }), never: '' };
}

function Counts({ d }: { d: StepData }) {
  return (
    <Group gap={4} wrap="nowrap">
      {d.measured != null && <Tooltip label={t('requests of this step in the recorded runs')}><Badge size="xs" variant="light" color="gray">{t('{n} last run', { n: num(d.measured) })}</Badge></Tooltip>}
      {d.tried != null && <Tooltip label={t('requests of this step in the dry run')}><Badge size="xs" variant="filled" color="orange">{t('{n} in dry run', { n: d.tried })}</Badge></Tooltip>}
    </Group>
  );
}

/* a step, or a loop, round or branching drawn closed */
export function StepNode({ id, data, selected }: NodeProps) {
  useLang();
  const c = useCtx();
  const d = data as StepData;
  const look = lookOf(c, d);
  const off = !!d.step.off || !!look.never;
  const frame = d.kind !== 'box';
  const heat = d.tried != null ? Math.min(1, 0.15 + 0.85 * d.triedShare) : 0;
  return (
    <Box className={'fl-card' + (frame ? ' fl-closed' : '') + (selected ? ' fl-sel' : '') + (d.problems.length ? ' fl-bad' : '') + (off ? ' fl-off' : '')}
      data-color={look.color} data-id={id}
      style={{ ['--fl-c' as string]: `var(--mantine-color-${look.color}-6)`, ['--fl-heat' as string]: String(heat) }}
      onDoubleClick={() => frame && c.toggle(id)}>
      <Handles />
      <Group gap={8} wrap="nowrap" h="100%" px={10}>
        <Box className="fl-icon">{look.icon({ size: 18 })}</Box>
        <Box style={{ minWidth: 0, flex: 1 }}>
          <Text fw={600} size="sm" lineClamp={1} title={d.label}>{d.label}</Text>
          <Group gap={6} wrap="nowrap">
            <Text size="xs" c="dimmed" lineClamp={1}>{off ? (d.step.off ? t('switched off') : t('never taken here')) : look.sub}</Text>
            <Counts d={d} />
          </Group>
        </Box>
        {d.problems.length > 0 && <Tooltip label={d.problems.join('\n')} multiline w={320}><Badge color="red" size="sm" circle>{d.problems.length}</Badge></Tooltip>}
        {frame && (
          <Tooltip label={t('Open')}>
            <ActionIcon variant="subtle" size="sm" aria-label={t('Open')} onClick={e => { e.stopPropagation(); c.toggle(id); }}>
              <IconChevronRight size={16} />
            </ActionIcon>
          </Tooltip>
        )}
      </Group>
    </Box>
  );
}

/* a loop, round or branching drawn open: a coloured area with its head; its steps are nodes of their own inside it */
export function FrameNode({ id, data, selected }: NodeProps) {
  useLang();
  const c = useCtx();
  const d = data as StepData;
  const f = FRAMES[d.kind] || FRAMES.each;
  return (
    <Box className={'fl-frame' + (selected ? ' fl-sel' : '') + (d.problems.length ? ' fl-bad' : '') + (d.step.off ? ' fl-off' : '')}
      style={{ ['--fl-c' as string]: `var(--mantine-color-${f.color}-6)` }} data-id={id}>
      <Handles />
      <Group className="fl-frame-head" gap={8} wrap="nowrap" px={12}>
        <ActionIcon variant="subtle" size="sm" aria-label={t('Close')} onClick={e => { e.stopPropagation(); c.toggle(id); }}>
          <IconChevronDown size={16} />
        </ActionIcon>
        <Box className="fl-icon">{f.icon({ size: 18 })}</Box>
        <Box style={{ minWidth: 0, flex: 1 }}>
          <Text fw={650} size="sm" lineClamp={1}>{d.label}</Text>
          <Text size="xs" c="dimmed" lineClamp={1}>{frameSays(d, c.lib)}</Text>
        </Box>
        {d.problems.length > 0 && <Tooltip label={d.problems.join('\n')} multiline w={320}><Badge color="red" size="sm" circle>{d.problems.length}</Badge></Tooltip>}
      </Group>
    </Box>
  );
}
function frameSays(d: StepData, lib: Library): string {
  const n = d.step, bits: string[] = [];
  if (d.kind === 'each' && n.together) bits.push(t('side by side'));
  if (d.kind === 'each' && n.order) bits.push(t('order: {order}', { order: tr((lib.order_words || {})[n.order] || String(n.order).replace('_', ' ')) }));
  if (d.kind === 'round' && n.stop) bits.push(t('stops when its condition is met'));
  if (n.when) bits.push(t('only under a condition'));
  if (n.off) bits.push(t('switched off'));
  return bits.join(' · ') || tn(d.inside ?? 0, '{n} step inside', '{n} steps inside');
}

export function WayNode({ data }: NodeProps) {
  useLang();
  const label = String((data as { label: string }).label);
  return (
    <Box className="fl-way" title={label}>
      <Handles />
      <Text size="xs" fw={600} lineClamp={2}>{label}</Text>
    </Box>
  );
}
export function DotNode() { return <Box className="fl-dot"><Handles /></Box>; }

/* an arrow: what it carries, the condition of the step it leads to, and "+" to put a step, loop, round or branching there */
export function StepEdge({ id, sourceX, sourceY, targetX, targetY, data, markerEnd }: EdgeProps) {
  useLang();
  const c = useCtx();
  const d = data as EdgeData;
  const [path, lx, ly] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  const text = [d.gives, d.when].filter(Boolean).join(' · ');
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} className="fl-edge" />
      <EdgeLabelRenderer>
        <Group gap={6} wrap="nowrap" className="fl-edge-label nodrag nopan" data-edge={id}
          style={{ transform: `translate(-11px, -50%) translate(${lx}px, ${ly}px)` }}>
          <Tooltip label={t('Put a step, loop, round or branching here')}>
            <ActionIcon size="sm" radius="xl" variant="default" aria-label={t('Put a step, loop, round or branching here')} onClick={() => c.add(d.list, d.at)}>
              <IconPlus size={14} />
            </ActionIcon>
          </Tooltip>
          {text && <Text size="xs" c="dimmed" className="fl-edge-text" title={text}>{text}</Text>}
        </Group>
      </EdgeLabelRenderer>
    </>
  );
}
