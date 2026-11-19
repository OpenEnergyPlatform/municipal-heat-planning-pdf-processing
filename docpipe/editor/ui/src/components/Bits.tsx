/* Small pieces every tab draws: a help text that folds, a diff, a key in code type, a muted line. */
import { useState, type ReactNode } from 'react';
import { Anchor, Box, Code, Text } from '@mantine/core';
import { diffClass } from '../lib/util';
import { rich, t, tr } from '../lib/i18n';

/* the help of a form field; a long one is folded to three lines with "more" */
export function Help({ text, size = 'sm' }: { text?: string | null; size?: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  const long = text.length > 150;
  return (
    <Box>
      <Text size={size} c="dimmed" lineClamp={long && !open ? 3 : undefined} style={{ whiteSpace: 'pre-wrap' }}>{rich(text)}</Text>
      {long && <Anchor component="button" type="button" size="sm" onClick={() => setOpen(!open)}>{open ? t('less') : t('more')}</Anchor>}
    </Box>
  );
}

/* a unified diff, line by line coloured: added, removed, hunk heads, file heads */
export function Diff({ text }: { text: string | string[] }) {
  const lines = Array.isArray(text) ? text : String(text || '').split('\n');
  return (
    <pre className="dp-diff">
      {lines.map((l, i) => <div key={i} className={'dp-diff-' + (diffClass(l) || 'same')}>{l || ' '}</div>)}
    </pre>
  );
}

export const K = ({ children }: { children: ReactNode }) => <Code className="dp-key">{children}</Code>;

/* a setting by its name in words, its key small beside it (owner request 2026-11-19, A5); a setting the server gives
   no name shows its key alone */
export function Named({ title, k, size = 'sm' }: { title?: string | null; k: string; size?: string }) {
  if (!title) return <Code fw={600}>{k}</Code>;
  return (
    <Text span size={size} fw={600} style={{ minWidth: 0, wordBreak: 'break-word' }}>
      {rich(tr(title))} <Code fz={11} c="dimmed" fw={400}>{k}</Code>
    </Text>
  );
}
export const Muted = ({ children, size = 'sm' }: { children: ReactNode; size?: string }) => <Text size={size} c="dimmed">{children}</Text>;
