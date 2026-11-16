/* The help beside every place where Python can be written: what the code receives, what it must give back, which names
   are at hand and a few short examples, each of which can be put in (that is an edit like any other). The examples are
   the ones the shipped drawings use, cut down to what they show. */
import { Accordion, Box, Button, Code, Stack, Text } from '@mantine/core';
import { IconBulb } from '@tabler/icons-react';
import { t, useLang } from '../lib/i18n';

/* where the code stands: a kind of block of the Graph tab, a step inside steps, or the Python block of the flow */
export type PyWhere = string;
export interface PyExample { title: string; code: string; per?: 'node' }
interface Guide { gets: string; gives: string; examples: PyExample[] }

const NAMES_GRAPH = () => t('Beside call stand literal(text) (a text as a Turtle string), in_graph(answer), is_class(answer, family), ttl_string(text), NOT_IN_GRAPH, re, log and, where the profile has one, kg (its own module of the graph). Anything else is imported at the top.');
const NAMES_FLOW = () => t('Only Python and its standard library are at hand; import what else you need at the top.');
const CALL = () => t('call.doc is the document being written (call.doc.name, call.doc.facts, call.doc.prefixes, call.doc.fold(text)), call.settings the settings of this block, call.node the node, call.row the reading as a dictionary, call.value what the arrow reads of it, call.label, call.source and call.rows.');

function guide(where: PyWhere): Guide {
  switch (where) {
    case 'condition': return {
      gets: t('A reading: call.row (a dictionary of its keys, e.g. call.row["year"]), call.doc and call.settings.'),
      gives: t('None where the reading is taken, else a short text, the reason it is left out. The reasons are counted in the log.'),
      examples: [
        { title: t('Take a reading only where it has a unit'), code: 'def run(call):\n    if not call.row.get("unit"):\n        return "no_unit"\n    return None\n' },
        { title: t('Take a reading only where its year is plausible'), code: 'def run(call):\n    year = call.row.get("year")\n    if isinstance(year, int) and 1990 <= year <= 2100:\n        return None\n    return f"year:{year}"\n' },
        { title: t('Take a reading by a setting (add the setting "scenario" below)'), code: 'def run(call):\n    wanted = call.settings.get("scenario", "target")\n    have = call.row.get("scenario")\n    if have == wanted:\n        return None\n    return f"scenario:{have}"\n' },
      ],
    };
    case 'object': return {
      gets: t('The reading and the value the arrow reads of it: call.value (called once per reading), or the whole node, call.node and call.rows (called once per node, set below), and call.settings.'),
      gives: t('A list of pairs (Turtle term, value): the term is what is written as the object, the value what a later document and the API body see. An empty list writes nothing.'),
      examples: [
        { title: t('Write the reading as a text'), code: 'def run(call):\n    if call.value is None:\n        return []\n    return [(literal(call.value), call.value)]\n' },
        { title: t('Write the number as a decimal'), code: 'def run(call):\n    if call.value is None:\n        return []\n    number = float(call.value)\n    return [(f\'"{number!r}"^^xsd:float\', number)]\n' },
        { title: t('Write the class the answer names, with a prefix from a setting'), code: 'def run(call):\n    answer = call.value\n    if not is_class(answer):\n        return []\n    prefix = call.settings.get("prefix") or "oeo"\n    return [(f"{prefix}:{answer}", call.doc.prefixes.get(prefix, "") + answer)]\n' },
        { title: t('Write the name of the node (once per node)'), code: 'def run(call):\n    name = call.node.name\n    if not name:\n        return []\n    return [(literal(name), name)]\n', per: 'node' },
      ],
    };
    case 'name': return {
      gets: t('The first spelling of the node: call.value, and call.doc.'),
      gives: t('The name of the node, as a text.'),
      examples: [
        { title: t('Name the node as the document spells it, without spaces at its ends'), code: 'def run(call):\n    return str(call.value).strip()\n' },
        { title: t('Name the node without its legal form'), code: 'def run(call):\n    text = re.sub(r"\\s+", " ", str(call.value)).strip()\n    legal = call.doc.legal_forms\n    if not legal:\n        return text\n    return re.sub(rf"[\\s,]+{legal}\\.?$", "", text, flags=re.I).strip(" ,")\n' },
      ],
    };
    case 'value': return {
      gets: t('The value the step before gave: call.value, and call.doc and call.settings.'),
      gives: t('The value this step passes on, a text or a number. None passes nothing on.'),
      examples: [
        { title: t('Write the value in capitals'), code: 'def run(call):\n    if call.value is None:\n        return None\n    return str(call.value).upper()\n' },
        { title: t('Take out what a pattern finds (add the setting "pattern" below)'), code: 'def run(call):\n    if call.value is None:\n        return None\n    text = re.sub(call.settings.get("pattern", ""), "", str(call.value))\n    return text.strip(" ,")\n' },
        { title: t('Look the value up in a table (add the setting "table" below)'), code: 'def run(call):\n    table = call.settings.get("table") or {}\n    return table.get(str(call.value), call.value)\n' },
      ],
    };
    case 'step': return {
      gets: t('The value the step before gave, as call.value (the first step gets the reading\'s value), and call.doc, call.node, call.row and call.settings.'),
      gives: t('A step in the middle gives the value the next step takes, a text or a number. The last step of an arrow gives a list of pairs (Turtle term, value); the last step of a name gives the name.'),
      examples: [
        { title: t('A step in the middle: cut the value at the first comma'), code: 'def run(call):\n    return str(call.value).split(",")[0].strip()\n' },
        { title: t('The last step of an arrow: write the value as a text'), code: 'def run(call):\n    if call.value in (None, ""):\n        return []\n    return [(literal(call.value), call.value)]\n' },
        { title: t('The last step of a name: the name in one line'), code: 'def run(call):\n    return re.sub(r"\\s+", " ", str(call.value)).strip()\n' },
      ],
    };
    case 'facts': return {
      gets: t('The document: call.doc (call.doc.name, call.doc.writer.db_path for the database) and call.settings.'),
      gives: t('A dictionary of what is known of the document beyond its harvest; a condition or a part of an address asks it as a fact. None writes nothing for the document.'),
      examples: [
        { title: t('Two facts: the name of the document and a fixed year'), code: 'def run(call):\n    return {"place": call.doc.name, "year": 2024}\n' },
        { title: t('Write nothing where the document is not in the register'), code: 'def run(call):\n    doc = call.doc\n    if doc.writer.db_path is None:\n        log.warning("graph: %s: no database", doc.name)\n        return None\n    return {"place": doc.name}\n' },
      ],
    };
    case 'nodes': return {
      gets: t('One reading: call.row, with call.source, the field it belongs to, and call.doc.'),
      gives: t('A list of names (texts), one for each node the reading makes; an empty list makes none.'),
      examples: [
        { title: t('One name for each reading'), code: 'def run(call):\n    name = call.row.get("value")\n    return [name] if name else []\n' },
        { title: t('Several names in one reading, split at semicolons'), code: 'def run(call):\n    words = str(call.row.get("value") or "")\n    return [part.strip() for part in words.split(";") if part.strip()]\n' },
      ],
    };
    case 'address': return {
      gets: t('One reading: call.row, call.label (the words a number\'s address is split by) and call.doc.'),
      gives: t('The address of the node as a text, its IRI; None where the reading has no address, and it is counted as held back.'),
      examples: [
        { title: t('Mint an address from the name of the reading'), code: 'def run(call):\n    name = call.row.get("value")\n    if not name:\n        return None\n    return call.doc.mint("scenario", "scenario", call.doc.fold(name))\n' },
        { title: t('Mint an address from the year and the quantity'), code: 'def run(call):\n    year, quantity = call.row.get("year"), call.row.get("quantity")\n    if not year or not quantity:\n        return None\n    return call.doc.mint("value", "value", f"{year}|{quantity}")\n' },
      ],
    };
    case 'class': return {
      gets: t('The node: call.node (call.node.row, call.node.name, call.node.iri) and call.doc.'),
      gives: t('The class the node is written as, a text such as oeo:OEO_00000128; None writes the class of the box.'),
      examples: [
        { title: t('The class of the quantity the node was read as'), code: 'def run(call):\n    quantity = call.node.row.get("quantity")\n    return f"oeo:{quantity}" if quantity else None\n' },
        { title: t('A class from a setting'), code: 'def run(call):\n    return call.settings.get("class")\n' },
      ],
    };
    case 'evidence': return {
      gets: t('The node: call.node (call.node.row is its reading) and call.doc.'),
      gives: t('A list of lines, each a comment starting with #, written above the node.'),
      examples: [
        { title: t('Where the value was read'), code: 'def run(call):\n    row = call.node.row\n    page = (row.get("provenance") or {}).get("page")\n    return [f"# {call.doc.name}.pdf, page {page}"]\n' },
        { title: t('The quote the number was read from'), code: 'def run(call):\n    quote = call.node.row.get("quote")\n    return [f\'# "{quote}"\'] if quote else []\n' },
      ],
    };
    case 'check': return {
      gets: t('The document with what was chosen: call.doc (call.doc.picked(field), call.doc.nodes) and call.settings.'),
      gives: t('Nothing. A check says something in the log with log.warning(...) and stops nothing.'),
      examples: [
        { title: t('Say so where a box has no node'), code: 'def run(call):\n    if not call.doc.nodes.get("municipality"):\n        log.warning("graph: %s: no municipality was chosen", call.doc.name)\n' },
        { title: t('Say so where two readings disagree'), code: 'def run(call):\n    got = call.doc.picked("title")\n    want = call.settings.get("title")\n    if got and want and call.doc.fold(got) != call.doc.fold(want):\n        log.warning("graph: %s: the title is %r, not %r", call.doc.name, got, want)\n' },
      ],
    };
    case 'claims': return {
      gets: t('The node: call.node (call.node.row is its reading) and call.doc.'),
      gives: t('A dictionary: what each dimension of the number became, by its name, as the IRI of a node or a class. It is what the provenance file records.'),
      examples: [
        { title: t('The class of the quantity'), code: 'def run(call):\n    quantity = call.node.row.get("quantity")\n    if not quantity:\n        return {}\n    return {"quantity": call.doc.prefixes.get("oeo", "") + quantity}\n' },
        { title: t('Nothing recorded'), code: 'def run(call):\n    return {}\n' },
      ],
    };
    case 'flow': return {
      gets: t('run(inputs): a dictionary with the variables you choose as inputs, each under the last word of its name (the input "answer.finds" is inputs["finds"]).'),
      gives: t('A dictionary whose keys are the outputs; each output you name becomes a variable for the steps after it.'),
      examples: [
        { title: t('A share from two numbers read before (inputs: part, whole; output: share)'), code: 'def run(inputs):\n    part, whole = inputs.get("part"), inputs.get("whole")\n    if not part or not whole:\n        return {"share": None}\n    return {"share": part / whole}\n' },
        { title: t('Keep only the years of a list (input: finds; output: years)'), code: 'def run(inputs):\n    years = [str(one) for one in inputs.get("finds") or [] if str(one).isdigit()]\n    return {"years": years}\n' },
        { title: t('Join two texts (inputs: title, place; output: heading)'), code: 'def run(inputs):\n    words = [inputs.get("title"), inputs.get("place")]\n    return {"heading": " · ".join(str(one) for one in words if one)}\n' },
      ],
    };
    default: return {
      gets: t('A call with doc, node, row, value, settings, label, source and rows.'),
      gives: t('What a block of this place gives.'),
      examples: [{ title: t('A block that gives nothing'), code: 'def run(call):\n    return None\n' }],
    };
  }
}

/* closed until opened: the explanation, then the examples with a button each */
export function PythonHelp({ where, onPut }: { where: PyWhere; onPut: (example: PyExample) => void }) {
  useLang();
  const g = guide(where);
  const inFlow = where === 'flow';
  return (
    <Accordion variant="contained" chevronPosition="left">
      <Accordion.Item value="how">
        <Accordion.Control icon={<IconBulb size={16} />}><Text size="sm" fw={500}>{t('How to write this, with examples')}</Text></Accordion.Control>
        <Accordion.Panel>
          <Stack gap="xs">
            <Box><Text size="xs" fw={600}>{t('What the code receives')}</Text><Text size="xs" c="dimmed">{g.gets}</Text>
              {!inFlow && <Text size="xs" c="dimmed" mt={4}>{CALL()}</Text>}</Box>
            <Box><Text size="xs" fw={600}>{t('What it gives back')}</Text><Text size="xs" c="dimmed">{g.gives}</Text></Box>
            <Box><Text size="xs" fw={600}>{t('Names at hand')}</Text><Text size="xs" c="dimmed">{inFlow ? NAMES_FLOW() : NAMES_GRAPH()}</Text></Box>
            <Text size="xs" fw={600}>{t('Examples')}</Text>
            {g.examples.map((ex, i) => (
              <Box key={i}>
                <Text size="xs">{ex.title}</Text>
                <Code block fz={11}>{ex.code}</Code>
                <Button mt={4} size="compact-xs" variant="light" onClick={() => onPut(ex)}>{t('Put in this example')}</Button>
              </Box>
            ))}
          </Stack>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}
