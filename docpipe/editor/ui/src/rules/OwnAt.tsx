/* "N steps have an own value for this rule": a click selects the step in the Flow tab, or with several offers a list to
   choose from, one after another. The count is that of the flow as saved on disk. */
import { Anchor, Menu } from '@mantine/core';
import { openStep } from '../lib/nav';
import { t, tn, useLang } from '../lib/i18n';

export function OwnAt({ steps }: { steps: { id: string; kind: string }[] }) {
  useLang();
  if (!steps.length) return null;
  if (steps.length === 1) {
    return <Anchor component="button" type="button" size="xs" onClick={() => openStep(steps[0].id)}>{t('1 step has a value of its own: {id}', { id: steps[0].id })}</Anchor>;
  }
  return (
    <Menu withinPortal position="bottom-start" shadow="md">
      <Menu.Target>
        <Anchor component="button" type="button" size="xs">{tn(steps.length, '{n} step has a value of its own', '{n} steps have a value of their own')}</Anchor>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{t('Choose a step to show in the Flow tab')}</Menu.Label>
        {steps.map(s => <Menu.Item key={s.id} onClick={() => openStep(s.id)}>{s.id} ({s.kind})</Menu.Item>)}
      </Menu.Dropdown>
    </Menu>
  );
}
