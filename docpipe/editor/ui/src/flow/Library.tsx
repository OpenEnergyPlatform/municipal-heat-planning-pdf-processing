/* The library a "+" opens: the frames and every kind of box, each with the sentence of what it does, a search over both. */
import { useMemo, useState } from 'react';
import { Badge, Box, Group, Modal, ScrollArea, Stack, Text, TextInput, UnstyledButton } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { FRAMES, GROUPS } from './nodes';
import type { Library } from './model';

export type Pick = { kind: 'box'; arg: string } | { kind: 'each'; arg: string } | { kind: 'round' } | { kind: 'if' };
interface Item { label: string; says: string; pick: Pick; color: string; icon: React.ReactNode; group: string }

export function LibraryModal({ lib, opened, where, onClose, onPick }: {
  lib: Library; opened: boolean; where: string; onClose: () => void; onPick: (p: Pick) => void;
}) {
  const [q, setQ] = useState('');
  const items = useMemo(() => {
    const out: Item[] = [];
    for (const [what, says] of Object.entries(lib.each)) out.push({ label: 'For each ' + what, says, pick: { kind: 'each', arg: what }, color: FRAMES.each.color, icon: FRAMES.each.icon({ size: 18 }), group: 'Frames' });
    out.push({ label: 'Round', says: 'Its boxes again: at most N times, or until the supply is used up; stops where a condition holds.', pick: { kind: 'round' }, color: FRAMES.round.color, icon: FRAMES.round.icon({ size: 18 }), group: 'Frames' });
    out.push({ label: 'If / else', says: 'Ways side by side, each under its condition, the last without one; they join again below.', pick: { kind: 'if' }, color: FRAMES.if.color, icon: FRAMES.if.icon({ size: 18 }), group: 'Frames' });
    for (const b of lib.boxes) {
      const g = GROUPS[b.group] || { word: b.group, color: 'gray', icon: () => null };
      out.push({ label: b.label, says: b.says, pick: { kind: 'box', arg: b.type }, color: g.color, icon: g.icon({ size: 18 }), group: g.word || b.group });
    }
    return out;
  }, [lib]);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = items.filter(it => words.every(w => (it.label + ' ' + it.says + ' ' + it.group).toLowerCase().includes(w)));
  const groups = [...new Set(shown.map(it => it.group))];
  return (
    <Modal opened={opened} onClose={() => { setQ(''); onClose(); }} size="xl" title={<Text fw={650}>Put a box or a frame {where}</Text>}>
      <Stack gap="sm">
        <TextInput leftSection={<IconSearch size={16} />} placeholder="Search the library" value={q} data-autofocus
          onChange={e => setQ(e.currentTarget.value)} />
        <ScrollArea.Autosize mah="60vh">
          <Stack gap="md">
            {groups.map(g => (
              <Box key={g}>
                <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>{g}</Text>
                <Stack gap={4}>
                  {shown.filter(it => it.group === g).map(it => (
                    <UnstyledButton key={it.label} className="fl-lib" onClick={() => { setQ(''); onPick(it.pick); }}
                      style={{ ['--fl-c' as string]: `var(--mantine-color-${it.color}-6)` }}>
                      <Group gap="sm" wrap="nowrap" align="flex-start">
                        <Box className="fl-icon" mt={2}>{it.icon}</Box>
                        <Box style={{ minWidth: 0 }}>
                          <Group gap={6}><Text fw={600} size="sm">{it.label}</Text>{it.pick.kind === 'box' && <Badge size="xs" variant="light" color={it.color}>{it.group}</Badge>}</Group>
                          <Text size="sm" c="dimmed">{it.says}</Text>
                        </Box>
                      </Group>
                    </UnstyledButton>
                  ))}
                </Stack>
              </Box>
            ))}
            {!shown.length && <Text c="dimmed">Nothing in the library matches.</Text>}
          </Stack>
        </ScrollArea.Autosize>
      </Stack>
    </Modal>
  );
}
