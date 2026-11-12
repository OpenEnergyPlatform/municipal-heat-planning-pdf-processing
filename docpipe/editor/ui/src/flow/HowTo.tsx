/* What the Flow tab is and how to use it, step by step, on the example of a second search for a year. */
import { Accordion, List, ScrollArea, Text } from '@mantine/core';
import { IconHelp } from '@tabler/icons-react';
import { rich, t, useLang } from '../lib/i18n';

const KEY = 'docpipe-edit-flow-howto';

/* closed until it is opened once; then it stays as it was left */
function wasOpen(): string | null {
  try { return localStorage.getItem(KEY) || null; } catch { return null; }
}

export function HowTo() {
  useLang();
  return (
    <Accordion variant="contained" defaultValue={wasOpen()} chevronPosition="left"
      onChange={v => { try { localStorage.setItem(KEY, v || ''); } catch { /* the page works without it */ } }}>
      <Accordion.Item value="how">
        <Accordion.Control icon={<IconHelp size={18} />}><Text fw={600}>{t('How to use this tab')}</Text></Accordion.Control>
        <Accordion.Panel>
          <ScrollArea.Autosize mah="26vh" type="auto">
          <List type="ordered" spacing={6} size="sm">
            <List.Item>{t('The run reads a document exactly as this flow shows it, from the top down. A step sends one kind of request or does one thing. A loop (For each ...) repeats the steps inside it for every item, a round repeats them until its limit or its condition stops it, and a branching (if / else) chooses which branch runs. The arrows show what goes on to the next step.')}</List.Item>
            <List.Item>{t('Click a step, loop, round or branching to see its description and change its settings on the right. Click the empty canvas to see the numbers of the flow, which several steps share. A loop, round or branching opens and closes with its arrow or with a double click.')}</List.Item>
            <List.Item>{rich(t('Click **+** on an arrow to put a step, loop, round or branching from the library at that place. Right-click a step to move it up or down, duplicate it, wrap it in a loop, round or branching, switch it off or delete it.'))}</List.Item>
            <List.Item>{rich(t('Example, a second search for a year: open the loops down to "Write a search sentence". Click it, Shift+click "Find the best chunks for a question" and the round with "Ask a dimension over the search hits" after it, right-click, **Wrap in → Round**. In the settings of the round choose "at most N times", 2, and "stop when": the dimension · is a year, and a second row: the dimension · state · is one of · read. Then click "Write a search sentence" and switch on "a new sentence from round 2, written knowing the earlier ones", so each round searches with a new sentence.'))}</List.Item>
            <List.Item>{rich(t('**Check** asks the server whether the run can carry out this flow. A problem is marked red at its step and listed above the flow, and a click on it goes to that step. **Save** writes the flow file of the profile. Ctrl+Z undoes an edit and Ctrl+Y does it again, until the next save.'))}</List.Item>
            <List.Item>{rich(t('**Dry run** runs the flow on one document with placeholder answers and sends nothing to a model. Afterwards every step shows how many requests it would send, and the steps with the most requests have the strongest colour.'))}</List.Item>
          </List>
          </ScrollArea.Autosize>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}
