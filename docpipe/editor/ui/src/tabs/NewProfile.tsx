/* A new profile from the head of the page (owner request 2026-11-14, wish 5): its name; empty, extending the profile docpipe
   brings, or a copy of a profile the installation finds; the addresses of an ontology, shapes and a graph, which the
   server fetches before it writes anything; a draft of its spec from those shapes or from the small shape docpipe brings.
   It says what was written and what the draft still lacks, and switches to the new profile. Nothing is deleted here. */
import { useEffect, useState } from 'react';
import { ActionIcon, Alert, Box, Button, Code, Group, Modal, SegmentedControl, Select, Stack, Text, TextInput, Tooltip } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { errText, post } from '../lib/api';
import { t } from '../lib/i18n';
import { Store, useStore, type PageState } from '../lib/nav';

const ADDRESS = 'https://…'; // i18n-ignore: what an address starts with

/* asked from the head's choice of the profile ("New profile …"): opens the dialog */
const asked = new Store(0);
export const askNewProfile = () => asked.set(asked.get() + 1);

interface Made { profile: string; written: string[]; missing: string[]; fetched: string[]; switch: boolean }

export function NewProfile({ st, onSwitch }: { st: PageState; onSwitch: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [start, setStart] = useState<'empty' | 'copy'>('empty');
  const [from, setFrom] = useState<string | null>(st.profile);
  const [addr, setAddr] = useState({ ontology: '', shapes: '', graph: '' });
  const [draft, setDraft] = useState<'none' | 'shapes' | 'bundled'>('bundled');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<Made | null>(null);
  const names = st.profiles || [st.profile];
  const wanted = useStore(asked);
  useEffect(() => { if (wanted) setOpen(true); }, [wanted]);
  const close = () => { setOpen(false); setMade(null); setError(null); };
  const make = async () => {
    setBusy(true); setError(null);
    try {
      const r = await post<Made>('/api/profile/new', {
        name: name.trim(), start, from: start === 'copy' ? from : null, addresses: addr, draft: start === 'empty' ? draft : 'none',
      });
      setMade(r);
    } catch (e) { setError(e instanceof Error ? e.message : errText(e)); }
    setBusy(false);
  };
  return (
    <>
      {names.length < 2 ? (
        <Tooltip label={t('Make a new profile in the profile folder of the project')} openDelay={500}>
          <ActionIcon size="lg" variant="default" aria-label={t('New profile')} style={{ flexShrink: 0 }} onClick={() => setOpen(true)}><IconPlus size={18} /></ActionIcon>
        </Tooltip>
      ) : null}
      <Modal opened={open} onClose={close} title={t('New profile')} size="lg" centered>
        {made ? (
          <Stack gap="sm">
            <Alert color="teal">{t('The profile {name} is made.', { name: made.profile })}</Alert>
            <Text size="sm" fw={600}>{t('Files written')}</Text>
            <Box component="ul" my={0}>{made.written.map(w => <li key={w}><Code>{w}</Code></li>)}</Box>
            {made.fetched.length ? <Text size="sm">{t('Fetched: {sources}', { sources: made.fetched.join(', ') })}</Text> : null}
            {made.missing.length ? (
              <>
                <Text size="sm" fw={600}>{t('What the draft still lacks before the strict check takes it')}</Text>
                <Box component="ul" my={0}>{made.missing.map((m, i) => <li key={i}><Text size="sm">{m}</Text></li>)}</Box>
              </>
            ) : null}
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>{t('Close')}</Button>
              {made.switch ? <Button onClick={() => { close(); onSwitch(made.profile); }}>{t('Switch to {name}', { name: made.profile })}</Button> : null}
            </Group>
          </Stack>
        ) : (
          <Stack gap="sm">
            <TextInput label={t('Name')} description={t('Lower-case letters, digits and _, starting with a letter.')} value={name}
              onChange={e => setName(e.currentTarget.value)} data-autofocus />
            <SegmentedControl value={start} onChange={v => setStart(v as 'empty' | 'copy')}
              data={[{ value: 'empty', label: t('Empty') }, { value: 'copy', label: t('Copy of …') }]} />
            {start === 'copy' ? (
              <Select label={t('Copy of')} description={t('The new profile extends it and gets its own copy of its spec, flow, graph, chat, rules and sources.')}
                data={names} value={from} onChange={setFrom} allowDeselect={false} />
            ) : (
              <Text size="sm" c="dimmed">{t('The new profile extends the profile docpipe brings itself.')}</Text>
            )}
            <Text size="sm" fw={600}>{t('Addresses')}</Text>
            <Text size="xs" c="dimmed">{t('Optional: the address of a file of the ontology, of the shapes and of the graph. They become the sources of the profile and are fetched before anything is written; the Sources tab changes them later.')}</Text>
            {(['ontology', 'shapes', 'graph'] as const).map(k => (
              <TextInput key={k} label={{ ontology: t('Ontology'), shapes: t('Shapes'), graph: t('Graph') }[k]} placeholder={ADDRESS}
                value={addr[k]} onChange={e => { const v = e.currentTarget.value; setAddr(a => ({ ...a, [k]: v })); }} />
            ))}
            {start === 'empty' ? (
              <Select label={t('Draft of the spec')} value={draft} onChange={v => setDraft((v || 'none') as 'none' | 'shapes' | 'bundled')} allowDeselect={false}
                data={[{ value: 'shapes', label: t('From the shapes at the address') }, { value: 'bundled', label: t('From the small shape docpipe brings (title, author, date, …)') }, { value: 'none', label: t('None') }]} />
            ) : null}
            {error ? <Alert color="red">{error}</Alert> : null}
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>{t('Cancel')}</Button>
              <Button loading={busy} disabled={!name.trim()} onClick={() => void make()}>{t('Make the profile')}</Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}
