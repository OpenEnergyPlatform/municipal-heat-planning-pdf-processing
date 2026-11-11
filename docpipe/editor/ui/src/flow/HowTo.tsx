/* What the Flow tab is and how to use it, step by step, on the example of a second search for a year. */
import { Accordion, Kbd, List, ScrollArea, Text } from '@mantine/core';
import { IconHelp } from '@tabler/icons-react';

const KEY = 'docpipe-edit-flow-howto';

/* closed until it is opened once; then it stays as it was left */
function wasOpen(): string | null {
  try { return localStorage.getItem(KEY) || null; } catch { return null; }
}

export function HowTo() {
  return (
    <Accordion variant="contained" defaultValue={wasOpen()} chevronPosition="left"
      onChange={v => { try { localStorage.setItem(KEY, v || ''); } catch { /* the page works without it */ } }}>
      <Accordion.Item value="how">
        <Accordion.Control icon={<IconHelp size={18} />}><Text fw={600}>How to use this tab</Text></Accordion.Control>
        <Accordion.Panel>
          <ScrollArea.Autosize mah="26vh" type="auto">
          <List type="ordered" spacing={6} size="sm">
            <List.Item>The run reads a document exactly as drawn here, from the top down. A box asks one kind of request or does one step; a frame (For each, Round, If / else) repeats or chooses what stands inside it. The arrows say what goes on to the next step.</List.Item>
            <List.Item>Click a box or a frame to see and change its settings on the right; click the empty canvas for the numbers of the flow. A frame opens and closes with its arrow (or a double click).</List.Item>
            <List.Item>Click <b>+</b> on an arrow to put a box or a frame from the library there. Right-click a box for Move up, Move down, Duplicate, Wrap in, Switch off and Delete.</List.Item>
            <List.Item>Example, a second search for a year: open the frames down to "Write the search sentence". Click it, Shift+click "Order the pieces" and the "Ask over the supply" round after it, right-click, <b>Wrap in → Round</b>. In the round's settings choose "at most N times", 2, and "stop when": the coordinate · is a year, and a second row: the coordinate · state · is one of · read. Then click "Write the search sentence" and switch on "a new sentence from round 2", so each round searches with a new sentence.</List.Item>
            <List.Item><b>Check</b> asks the server whether the run can do the drawing: a problem is marked red at its box and listed above, a click on it goes there. <b>Save</b> writes the profile's flow file. <Kbd>Ctrl</Kbd>+<Kbd>Z</Kbd> undoes an edit, <Kbd>Ctrl</Kbd>+<Kbd>Y</Kbd> does it again, until the next save.</List.Item>
            <List.Item><b>Try</b> runs the drawing on one document with made-up answers and sends nothing to a model; every box then shows how many requests it would ask, the busiest ones in the strongest colour.</List.Item>
          </List>
          </ScrollArea.Autosize>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}
