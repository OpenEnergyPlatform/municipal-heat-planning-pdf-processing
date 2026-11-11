/* The library a "+" opens: the loops, rounds, branchings and every kind of step, each with the sentence of what it does, a search over all. */
import { useMemo, useState } from 'react';
import { Badge, Box, Group, Modal, ScrollArea, Stack, Text, TextInput, UnstyledButton } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { FRAMES, GROUPS, frameWord, groupWord } from './nodes';
import { t, tr, useLang } from '../lib/i18n';
import type { Library } from './model';

export type Pick = { kind: 'box'; arg: string } | { kind: 'each'; arg: string } | { kind: 'round' } | { kind: 'if' };
interface Item { label: string; says: string; pick: Pick; color: string; icon: React.ReactNode; group: string }

export function LibraryModal({ lib, opened, after, onClose, onPick }: {
  lib: Library; opened: boolean; after: string | null; onClose: () => void; onPick: (p: Pick) => void;
}) {
  const lang = useLang();
  const [q, setQ] = useState('');
  const items = useMemo(() => {
    const out: Item[] = [];
    const frames = t('Loops, rounds and branchings');
    for (const [what, says] of Object.entries(lib.each)) out.push({ label: tr((lib.each_titles || {})[what]) || t('For each {name}', { name: what }), says: tr(says), pick: { kind: 'each', arg: what }, color: FRAMES.each.color, icon: FRAMES.each.icon({ size: 18 }), group: frames });
    out.push({ label: frameWord('round'), says: t('Runs the steps inside it again and again. To change it: set "at most N times" or "until the search hits are used up" under "repeats", and add a condition under "stop when" that ends the rounds early.'), pick: { kind: 'round' }, color: FRAMES.round.color, icon: FRAMES.round.icon({ size: 18 }), group: frames });
    out.push({ label: frameWord('if'), says: t('Runs only the first branch whose condition is met. To change it: give each branch its condition, and the last branch, without a condition, runs when no other branch does. All branches join again below.'), pick: { kind: 'if' }, color: FRAMES.if.color, icon: FRAMES.if.icon({ size: 18 }), group: frames });
    for (const b of lib.boxes) {
      const g = GROUPS[b.group] || { color: 'gray', icon: () => null };
      out.push({ label: tr(b.label), says: tr(b.says), pick: { kind: 'box', arg: b.type }, color: g.color, icon: g.icon({ size: 18 }), group: groupWord(b.group) });
    }
    return out;
  }, [lib, lang]);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = items.filter(it => words.every(w => (it.label + ' ' + it.says + ' ' + it.group).toLowerCase().includes(w)));
  const groups = [...new Set(shown.map(it => it.group))];
  return (
    <Modal opened={opened} onClose={() => { setQ(''); onClose(); }} size="xl" title={<Text fw={650}>{after ? t('Put a step, loop, round or branching after {step}', { step: after }) : t('Put a step, loop, round or branching here')}</Text>}>
      <Stack gap="sm">
        <TextInput leftSection={<IconSearch size={16} />} placeholder={t('Search the library')} value={q} data-autofocus
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
            {!shown.length && <Text c="dimmed">{t('Nothing in the library matches your search. Try fewer or other words.')}</Text>}
          </Stack>
        </ScrollArea.Autosize>
      </Stack>
    </Modal>
  );
}
