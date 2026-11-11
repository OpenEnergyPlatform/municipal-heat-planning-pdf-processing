/* Messages and the two questions a page asks: a yes or no, and one line of text. */
import { useState } from 'react';
import { Button, Group, Stack, Text, TextInput } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';

export function showError(e: unknown) {
  const message = e instanceof Error ? e.message : String(e);
  notifications.show({ color: 'red', title: 'Not done', message, autoClose: false, withCloseButton: true });
}
export function showInfo(text: string) {
  notifications.show({ color: 'teal', message: text, autoClose: 7000, withCloseButton: true });
}

export function askConfirm(title: string, text: string, okText = 'OK'): Promise<boolean> {
  return new Promise(resolve => {
    let done = false;
    const fin = (v: boolean) => { if (!done) { done = true; resolve(v); } };
    modals.openConfirmModal({
      title, centered: true,
      children: <Text style={{ whiteSpace: 'pre-wrap' }}>{text}</Text>,
      labels: { confirm: okText, cancel: 'Cancel' },
      onConfirm: () => fin(true), onCancel: () => fin(false), onClose: () => fin(false),
    });
  });
}

function AskText({ label, initial, done }: { label: string; initial: string; done: (v: string | null) => void }) {
  const [v, setV] = useState(initial);
  return (
    <Stack>
      <TextInput label={label} value={v} data-autofocus spellCheck={false}
        onChange={e => setV(e.currentTarget.value)}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); done(v.trim()); } }} />
      <Group justify="flex-end">
        <Button variant="default" onClick={() => done(null)}>Cancel</Button>
        <Button onClick={() => done(v.trim())}>OK</Button>
      </Group>
    </Stack>
  );
}

export function askText(title: string, label: string, initial = ''): Promise<string | null> {
  return new Promise(resolve => {
    let done = false;
    let id = '';
    const fin = (v: string | null) => { if (!done) { done = true; resolve(v); modals.close(id); } };
    id = modals.open({ title, centered: true, onClose: () => fin(null), children: <AskText label={label} initial={initial} done={fin} /> });
  });
}
