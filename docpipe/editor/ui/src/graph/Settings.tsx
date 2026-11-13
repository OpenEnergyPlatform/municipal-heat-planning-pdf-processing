/* The settings that open on the right of the canvas: of a box (how many nodes, of which field, its address, what is
   admitted, what the shapes require of its properties), of an arrow (the property, the brick with its settings, one
   reading, a condition) and of the document. Every control changes the drawing in place. */
import { Accordion, ActionIcon, Alert, Badge, Box, Button, Divider, Group, NativeSelect, Select, SegmentedControl, Stack, TagsInput, Text, Tooltip } from '@mantine/core';
import { IconTrash } from '@tabler/icons-react';
import { AreaBox, NumberBox, TextBox } from '../components/Inputs';
import { Help } from '../components/Bits';
import { rich, t, tr } from '../lib/i18n';
import {
  BrickAbout, BrickList, BrickRefEditor, BrickSelect, Flag, FieldSelect, FieldsSelect, PairsEditor, SettingsEditor, bricksOf, type Kit,
} from './inputs';
import {
  COUNT_WORDS, arrowKey, boxTitle, fieldsOfBox, kindOfArrow, localName, rowsOf, subjectOf, takesFields, type Cur, type GraphData, type Obj,
} from './model';

export interface Panel {
  d: GraphData; cur: Cur; kit: Kit; remove(arrow: Obj): void; removeBox(id: string): void; select(kind: 'box' | 'arrow', id: string): void;
}

const SPECIAL_TOKENS = ['@name', '@key'];

/* ---- a box ---- */
export function BoxSettings({ P, box }: { P: Panel; box: Obj }) {
  const { d, cur, kit } = P;
  const { edit } = kit;
  const map = cur.map;
  const words = COUNT_WORDS();
  const rows = rowsOf(d, box);
  const fieldNames = d.fields.map(f => f.name);
  const boxOptions = (map.boxes || []).filter((b: Obj) => b.id !== box.id).map((b: Obj) => ({ value: b.id, label: String(b.id) }));
  const set = (key: string, v: unknown, typing?: string) => edit(() => {
    if (v === undefined || v === null || v === '' || v === false) delete box[key]; else box[key] = v;
  }, typing);
  const address: Obj = box.address || {};
  const mode = 'brick' in address ? 'brick' : 'name' in address ? 'name' : 'from';
  const setAddress = (next: Obj | null, typing?: string) => edit(() => { if (next && Object.keys(next).length) box.address = next; else delete box.address; }, typing);
  const classOptions = d.classes.filter(c => c.curie).map(c => ({ value: c.curie as string, label: (c.label || c.id) }));
  if (box.class && !classOptions.some(c => c.value === box.class)) classOptions.push({ value: box.class, label: box.class });
  const usedBy = (map.arrows || []).filter((a: Obj) => subjectOf(map, a) === box.id).length;
  const constraintRows = rows.filter(r => r.prop && r.prop.constraints.length);

  return (
    <Stack gap="md" data-settings="box">
      <Box>
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Text fw={700} size="lg">{boxTitle(d, box)}</Text>
          <Tooltip label={t('Remove the box')}><ActionIcon color="red" variant="light" aria-label={t('Remove the box')} onClick={() => P.removeBox(String(box.id))}><IconTrash size={18} /></ActionIcon></Tooltip>
        </Group>
        <Text size="sm" c="dimmed">{t('{n} arrows write on this box.', { n: usedBy })}</Text>
      </Box>

      <Accordion multiple variant="separated" radius="md" defaultValue={['nodes', 'address']}>
        <Accordion.Item value="nodes">
          <Accordion.Control>{t('Its nodes')}</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Select label={t('Class')} description={t('The class of the shapes or the ontology each node is written as.')} searchable clearable data={classOptions}
                value={box.class || null} onChange={v => set('class', v)} nothingFoundMessage={t('No class matches.')} />
              <Select label={t('How many nodes')} description={words[box.count] ? words[box.count].says : undefined} allowDeselect={false}
                data={Object.entries(words).map(([value, w]) => ({ value, label: w.label }))} value={box.count} onChange={v => v && set('count', v)} />
              {box.count === 'per_answer'
                ? <FieldSelect k={kit} label={t('Of which dimension')} value={typeof box.of === 'string' ? box.of : null} onChange={v => set('of', v)} />
                : takesFields(box.count)
                  ? <FieldsSelect k={kit} label={t('Of which fields')} description={t('Every reading of these fields makes or joins a node.')} value={fieldsOfBox(box)} onChange={v => set('of', v.length ? v : undefined)} />
                  : null}
              {box.count === 'per_object' && <Text size="sm" c="dimmed">{t('Its nodes are the objects of the arrows that start at {boxes}.', { boxes: ((box.of || []) as Obj[]).map(x => x.box).join(', ') })}</Text>}
              <Select label={t('Among the nodes of')} description={t('Takes the readings of the nodes of another box instead of the whole document.')} clearable data={boxOptions}
                value={box.among || null} onChange={v => set('among', v)} />
              {box.among && <FieldSelect k={kit} label={t('Which reading names a node')} value={box.value} onChange={v => set('value', v)} />}
              <Flag label={t('Written into the graph')} help={t('Off: the box and every triple that names its nodes are left out.')} checked={box.written !== false}
                onChange={v => edit(() => { if (v) delete box.written; else box.written = false; })} />
              <Flag label={t('Required')} help={t('A document without a node of this box is not written at all.')} checked={!!box.required} onChange={v => set('required', v)} />
              <Flag label={t('Once per file')} help={t('A node that several documents of one file name is written once, with the first of them.')} checked={box.once === 'per_file'}
                onChange={v => edit(() => { if (v) box.once = 'per_file'; else delete box.once; })} />
              {box.count === 'per_document' && (
                <Select label={t('The same node in two documents')} description={t('What happens when a second document makes the address of a node an earlier one made.')}
                  data={[{ value: '', label: t('Nothing') }, { value: 'warn', label: t('Say so in the log') }, { value: 'refuse', label: t('Refuse the second document whole') }]}
                  value={box.same_node || ''} allowDeselect={false} onChange={v => set('same_node', v)} />
              )}
              <Select label={t('Also write its own number under')} description={t('The property that carries the number the address ends in.')} clearable searchable
                data={[...rows.map(r => ({ value: r.curie, label: r.label })), ...(box.uuid && !rows.some(r => r.curie === box.uuid) ? [{ value: box.uuid, label: box.uuid }] : [])]}
                value={box.uuid || null} onChange={v => set('uuid', v)} />
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="address">
          <Accordion.Control>{t('Its address')}</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <SegmentedControl fullWidth size="xs" value={mode} data={[
                { value: 'from', label: t('Made from fields') }, { value: 'name', label: t('A name template') }, { value: 'brick', label: t('A brick') }]}
                onChange={v => setAddress(v === 'name' ? { folder: address.folder || '', name: address.name || '' } : v === 'brick' ? { brick: (bricksOf(d, 'address')[0] || { name: '' }).name } : { folder: address.folder || '', key: address.key || String(box.id), from: address.from || [] })} />
              {mode !== 'brick' && <TextBox label={t('Folder')} description={t('The folder of the address; empty for none.')} mono value={address.folder == null ? '' : String(address.folder)}
                onText={v => setAddress({ ...address, folder: v }, 'folder')} />}
              {mode === 'from' && (
                <>
                  <TextBox label={t('Key of the number')} description={t('Names what the number below is made of, so two boxes never share one.')} mono value={address.key == null ? '' : String(address.key)}
                    onText={v => setAddress({ ...address, key: v }, 'key')} />
                  <TagsInput label={t('Made of')} description={t('The fields, in order, whose readings make the number of the address: a field, @name for the name of the node, @key for its key, @fact:name for a fact of the document.')}
                    data={[...fieldNames, ...SPECIAL_TOKENS]} value={address.from || []} onChange={v => setAddress({ ...address, from: v })} />
                  <Flag label={t('The first one that is present')} help={t('Use only the first of the fields that has a reading.')} checked={!!address.first_present}
                    onChange={v => setAddress({ ...address, first_present: v || undefined })} />
                  <Flag label={t('Fold the words')} help={t('Spell the same name the same way (capitals, accents, legal forms).')} checked={!!address.fold}
                    onChange={v => setAddress({ ...address, fold: v || undefined })} />
                </>
              )}
              {mode === 'name' && <TextBox label={t('Name template')} description={t('Words and {names} of what the harvest knows of the document.')} mono value={address.name == null ? '' : String(address.name)}
                onText={v => setAddress({ ...address, name: v }, 'name')} />}
              {mode === 'brick' && (
                <BrickRefEditor k={kit} kind="address" refer={address} onChange={next => setAddress(next)} />
              )}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="admit">
          <Accordion.Control>{t('What is admitted')}</Accordion.Control>
          <Accordion.Panel>
            <BrickList k={kit} kind="condition" list={box.admit || []} label={t('A reading is taken only if all of these let it through')}
              onChange={next => set('admit', next.length ? next : undefined)} />
          </Accordion.Panel>
        </Accordion.Item>

        {box.count === 'per_answer' && (
          <Accordion.Item value="table">
            <Accordion.Control>{t('The table of answers')}</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                <Text size="sm" c="dimmed">{t('Each answer of the dimension that is a row here makes a node, with the class, the folder and the words of its row.')}</Text>
                <PairsEditor value={box.table || {}} onChange={v => edit(() => { if (Object.keys(v).length) box.table = v; else delete box.table; }, 'table')} />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        )}

        {constraintRows.length > 0 && (
          <Accordion.Item value="constraints">
            <Accordion.Control>{t('What the shapes ask of its properties')}</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                {constraintRows.map(r => (
                  <Box key={r.curie}>
                    <Text size="sm" fw={600}>{r.label}</Text>
                    {r.prop!.constraints.map(c => (
                      <Group key={c.key} gap="xs" wrap="nowrap" justify="space-between" title={c.key}>
                        <Text size="sm">{c.component + ' ' + (Array.isArray(c.says) ? c.says.join(', ') : String(c.says))}</Text>
                        <NativeSelect size="xs" value={cur.constraints[c.key] || 'report'} data={d.effects.map(e => ({ value: e, label: effectWord(e) }))}
                          onChange={e => { const v = e.currentTarget.value; edit(() => { if (v === 'report') delete cur.constraints[c.key]; else cur.constraints[c.key] = v; }); }} />
                      </Group>
                    ))}
                  </Box>
                ))}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        )}

        <Accordion.Item value="details">
          <Accordion.Control>{t('Details')}</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Text size="sm">{t('Name in the drawing: {id}', { id: String(box.id) })}</Text>
              <AreaBox label={t('Note')} minRows={2} value={box.note || ''} onText={v => set('note', v, 'note')} />
              <Select label={t('Order of the nodes')} data={[{ value: '', label: t('As the harvest has them') }, { value: 'sorted', label: t('Sorted') }]} value={box.order || ''}
                allowDeselect={false} onChange={v => set('order', v)} />
              <Select label={t('Which name stands when a node has several')} data={[{ value: '', label: t('The first') }, { value: 'last', label: t('The last') }]} value={box.name || ''}
                allowDeselect={false} onChange={v => set('name', v)} />
              <OptionalBrick k={kit} kind="nodes" label={t('Brick that finds the names')} value={box.names} onChange={v => set('names', v)} />
              <OptionalBrick k={kit} kind="name" label={t('Brick that spells the name of a node')} value={box.name_brick} onChange={v => set('name_brick', v)} />
              <OptionalBrick k={kit} kind="class" label={t('Brick that chooses the class of a node')} value={box.class_brick} onChange={v => set('class_brick', v)} />
              <OptionalBrick k={kit} kind="evidence" label={t('Brick that writes the passages above a node')} value={box.evidence} onChange={v => set('evidence', v)} />
              <BrickList k={kit} kind="condition" list={box.when || []} label={t('Readings that make a node of this box (all must pass)')}
                onChange={next => set('when', next.length ? next : undefined)} />
              {['settle', 'strict', 'class_by'].filter(key => box[key] !== undefined).map(key => (
                <Box key={key}>
                  <Text size="sm" fw={500}>{key === 'settle' ? t('How the numbers of one address are settled') : key === 'strict' ? t('What the strict graph requires') : t('Class by field')}</Text>
                  <PairsEditor value={box[key] && typeof box[key] === 'object' ? box[key] : {}} onChange={v => edit(() => { box[key] = v; }, 'k:' + key)} />
                </Box>
              ))}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}

const effectWord = (e: string) => ({
  report: t('report'), leave_out_value: t('leave out the value'), leave_out_paper: t('leave out the paper'), stop: t('stop the run'),
} as Record<string, string>)[e] || e;

function OptionalBrick({ k, kind, label, value, onChange }: { k: Kit; kind: string; label: string; value: Obj | undefined; onChange: (v: Obj | undefined) => void }) {
  if (!value) {
    return (
      <Box>
        <Text size="sm" fw={500}>{label}</Text>
        <Select placeholder={t('None')} data={bricksOf(k.d, kind).map(b => ({ value: b.name, label: tr(b.does) }))} value={null} onChange={v => v && onChange({ brick: v })}
          comboboxProps={{ width: 460 }} />
      </Box>
    );
  }
  return (
    <Box>
      <Group justify="space-between"><Text size="sm" fw={500}>{label}</Text><Button size="compact-xs" variant="subtle" color="red" onClick={() => onChange(undefined)}>{t('Remove')}</Button></Group>
      <BrickRefEditor k={k} kind={kind} refer={value} onChange={v => onChange(v)} />
    </Box>
  );
}

/* ---- an arrow ---- */
export function ArrowSettings({ P, arrow }: { P: Panel; arrow: Obj }) {
  const { d, cur, kit } = P;
  const { edit } = kit;
  const map = cur.map;
  const kind = kindOfArrow(map, arrow);
  const subject = (map.boxes || []).find((b: Obj) => b.id === subjectOf(map, arrow)) || {};
  const rows = rowsOf(d, subject);
  const brickName: string = arrow.brick ? (typeof arrow.brick === 'string' ? arrow.brick : arrow.brick.brick) : '';
  const brick = d.bricks.find(b => b.name === brickName);
  const field = d.fields.find(f => f.name === arrow.from);
  const fromBox = (map.boxes || []).find((b: Obj) => b.id === arrow.from);
  const set = (key: string, v: unknown, typing?: string) => edit(() => {
    if (v === undefined || v === null || v === '' || v === false) delete arrow[key]; else arrow[key] = v;
  }, typing);
  const propOptions = rows.map(r => ({ value: r.curie, label: r.label }));
  if (!propOptions.some(o => o.value === arrow.property)) propOptions.push({ value: arrow.property, label: arrow.property });
  const when: Obj = arrow.when || {};
  const setWhen = (next: Obj, typing?: string) => edit(() => {
    const clean = Object.fromEntries(Object.entries(next).filter(([, v]) => v !== '' && v !== undefined));
    if (Object.keys(clean).length) arrow.when = clean; else delete arrow.when;
  }, typing);
  const propLabel = rows.find(r => r.curie === arrow.property)?.label || localName(arrow.property);
  const toBox = (map.boxes || []).find((x: Obj) => x.id === arrow.to);
  const title = kind === 'field'
    ? t('{field} → {property}', { field: field ? field.label : String(arrow.from), property: propLabel })
    : kind === 'link'
      ? t('{from} → {to}', { from: fromBox ? boxTitle(d, fromBox) : String(arrow.from), to: toBox ? boxTitle(d, toBox) : String(arrow.to) })
      : t('{property} from the node itself', { property: propLabel });
  const where = kind === 'link' ? t('over {property}', { property: propLabel }) : t('on {box}', { box: subject.id ? boxTitle(d, subject) : String(arrow.to) });
  return (
    <Stack gap="md" data-settings="arrow">
      <Box>
        <Group gap="xs" justify="space-between" wrap="nowrap" align="flex-start">
          <Text fw={700} size="lg">{title}</Text>
          <Tooltip label={t('Remove the arrow')}><ActionIcon color="red" variant="light" aria-label={t('Remove the arrow')} onClick={() => P.remove(arrow)}><IconTrash size={18} /></ActionIcon></Tooltip>
        </Group>
        <Text size="sm" c="dimmed">{where}</Text>
        {kind === 'field' && field && field.example && <Text size="sm" c="dimmed">{t('For example: {value}', { value: field.example.value })}</Text>}
        {kind === 'link' && fromBox && <Text size="sm" c="dimmed">{t('The nodes of {to} are the objects of this property on the nodes of {from}.', { to: toBox ? boxTitle(d, toBox) : String(arrow.to), from: boxTitle(d, fromBox) })}</Text>}
      </Box>

      <Select label={t('Property')} description={t('What the shapes give the class of the node this arrow writes on.')} searchable data={propOptions} value={arrow.property} allowDeselect={false}
        onChange={v => v && edit(() => { arrow.property = v; })} />

      {kind !== 'link' && (
        <Stack gap="xs">
          <BrickSelect k={kit} kind="object" label={t('Brick: how the reading becomes the object')} none={t('None: write the reading as it is')} value={brickName || null}
            onChange={v => edit(() => { if (!v) { delete arrow.brick; delete arrow.settings; } else { if (v !== brickName) delete arrow.settings; arrow.brick = v; } })} />
          {brick ? <BrickAbout brick={brick} /> : <Text size="sm" c="dimmed">{t('Without a brick the reading is written as a text.')}</Text>}
          {brick && <SettingsEditor k={kit} brick={brick} settings={arrow.settings || {}} onChange={s => { if (Object.keys(s).length) arrow.settings = s; else delete arrow.settings; }} />}
        </Stack>
      )}

      <Divider />
      <Select label={t('Objects')} allowDeselect={false} value={arrow.objects || ''} onChange={v => set('objects', v)}
        description={t('When one node has several objects: one statement for each, or all in one statement.')}
        data={[{ value: '', label: t('As the program does') }, { value: 'each', label: t('One statement for each object') }, { value: 'joined', label: t('All objects in one statement') }]} />
      {kind === 'field' && (
        <>
          <Flag label={t('One reading')} help={t('Take one reading of the field: the shapes allow one value.')} checked={arrow.pick === 'one_reading'} onChange={v => set('pick', v ? 'one_reading' : undefined)} />
          <Flag label={t('Only one value')} help={t('The shapes allow this property once on a node.')} checked={!!arrow.single} onChange={v => set('single', v)} />
        </>
      )}
      <Select label={t('The first value of the file')} allowDeselect={false} value={arrow.first_in_file || ''} onChange={v => set('first_in_file', v)}
        description={t('Several documents of one file may name the same node: which value stands.')}
        data={[{ value: '', label: t('Every document writes its own') }, { value: 'skip_other', label: t('The first stands, a different later one is left out') }, { value: 'keep_first', label: t('The first stands in place of a later one') }]} />
      <Flag label={t('Write the passages')} help={t('Write the passages that back the reading as comment lines above the triple.')} checked={!!arrow.evidence} onChange={v => set('evidence', v)} />
      <Flag label={t('Name each passage once')} help={t('A passage that backs several values of the node is written once.')} checked={!!arrow.cite_once} onChange={v => set('cite_once', v)} />
      <Select label={t('Order of the values')} allowDeselect={false} value={arrow.order || ''} onChange={v => set('order', v)}
        data={[{ value: '', label: t('As the harvest has them') }, { value: 'sorted', label: t('Sorted') }]} />

      <Box>
        <Text size="sm" fw={500}>{t('Only when')}</Text>
        <Text size="xs" c="dimmed" mb={4}>{t('The arrow writes only where a document read this dimension of this field as this answer.')}</Text>
        <Stack gap="xs">
          <FieldSelect k={kit} label={t('Field')} value={when.field} onChange={v => setWhen({ ...when, field: v || '' })} />
          <TextBox label={t('Dimension')} mono value={when.coordinate || ''} onText={v => setWhen({ ...when, coordinate: v }, 'when-c')} />
          <TextBox label={t('Is the answer')} mono value={when.is || ''} onText={v => setWhen({ ...when, is: v }, 'when-i')} />
        </Stack>
      </Box>

      <TextBox label={t('Label')} description={t('Words shown beside the arrow on the canvas.')} value={arrow.label || ''} onText={v => set('label', v, 'label')} />
      <AreaBox label={t('Note')} minRows={2} value={arrow.note || ''} onText={v => set('note', v, 'note')} />
      <Text size="xs" c="dimmed">{rich(t('In the drawing: `{key}`', { key: arrowKey(arrow) }))}</Text>
    </Stack>
  );
}

/* ---- the document ---- */
export function DocumentSettings({ P }: { P: Panel }) {
  const { cur, kit } = P;
  const { edit } = kit;
  const map = cur.map;
  const doc: Obj = map.document || (map.document = {});
  const setDoc = (key: string, v: unknown, typing?: string) => edit(() => {
    const m = cur.map.document || (cur.map.document = {});
    if (v === undefined || v === null || v === '' || v === false || (Array.isArray(v) && !v.length)) delete m[key]; else m[key] = v;
    if (!Object.keys(m).length) delete cur.map.document;
  }, typing);
  const boxOptions = (map.boxes || []).map((b: Obj) => ({ value: b.id, label: String(b.id) }));
  return (
    <Stack gap="md" data-settings="document">
      <Box>
        <Text fw={700} size="lg">{t('The document')}</Text>
        <Text size="sm" c="dimmed">{t('What holds for every document before and after its boxes are made. Click a box or an arrow to change it.')}</Text>
      </Box>
      <Accordion multiple variant="separated" radius="md" defaultValue={['document']}>
        <Accordion.Item value="document">
          <Accordion.Control>{t('Every document')}</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <FieldSelect k={kit} label={t('Field of the front pages')} description={t('The readings of this field on the front pages of a document are looked at first.')} value={doc.front_pages}
                onChange={v => setDoc('front_pages', v)} />
              <Flag label={t('Strict graph')} help={t('Hold the strict graph to what its bricks and boxes mark as strict.')} checked={!!doc.strict} onChange={v => setDoc('strict', v)} />
              <Flag label={t('Decisions of people')} help={t('Apply the decisions people made on rows of the harvest.')} checked={!!doc.decisions} onChange={v => setDoc('decisions', v)} />
              <OptionalBrick k={kit} kind="facts" label={t('Brick that finds what is known of the document')} value={doc.facts} onChange={v => setDoc('facts', v)} />
              <BrickList k={kit} kind="condition" list={doc.admit || []} label={t('Readings the document takes')} onChange={v => setDoc('admit', v)} />
              <BrickList k={kit} kind="check" list={doc.check || []} label={t('Checks over what was chosen')} onChange={v => setDoc('check', v)} />
              {doc.claims && (
                <Box>
                  <Group justify="space-between"><Text size="sm" fw={500}>{t('What the provenance file records')}</Text><Button size="compact-xs" variant="subtle" color="red" onClick={() => setDoc('claims', undefined)}>{t('Remove')}</Button></Group>
                  <Stack gap="xs">
                    <Select label={t('Box of the document')} data={boxOptions} value={doc.claims.document || null} onChange={v => edit(() => { doc.claims.document = v; })} />
                    <Select label={t('Box of the values')} data={boxOptions} value={doc.claims.box || null} onChange={v => edit(() => { doc.claims.box = v; })} />
                    <BrickRefEditor k={kit} kind="claims" refer={doc.claims} onChange={next => edit(() => { doc.claims = { ...doc.claims, ...next }; })} />
                  </Stack>
                </Box>
              )}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
        <Accordion.Item value="names">
          <Accordion.Control>{t('Names and words of the graph')}</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Box>
                <Text size="sm" fw={500}>{t('Prefixes')}</Text>
                <Text size="xs" c="dimmed">{t('Each prefix and the address it stands for; the address ends in / or #.')}</Text>
                <PairsEditor value={map.prefixes || {}} onChange={v => edit(() => { map.prefixes = v; }, 'prefixes')} />
              </Box>
              <NumberBox label={t('Width of the prefix column')} w="100%" value={map.prefix_width == null ? '' : String(map.prefix_width)}
                onText={v => edit(() => { if (v === '') delete map.prefix_width; else map.prefix_width = Number(v); }, 'pw')} />
              <TextBox label={t('Legal forms')} description={t('A pattern of the legal forms that fold away from a name.')} mono value={map.legal_forms || ''}
                onText={v => edit(() => { if (v) map.legal_forms = v; else delete map.legal_forms; }, 'lf')} />
              <Box>
                <Text size="sm" fw={500}>{t('Evidence')}</Text>
                <Text size="xs" c="dimmed">{t('The words the passages are written with, how they are joined and where evidence nodes go.')}</Text>
                <PairsEditor value={map.evidence || {}} onChange={v => edit(() => { if (Object.keys(v).length) map.evidence = v; else delete map.evidence; }, 'evidence')} />
              </Box>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
      {!(map.boxes || []).length && <Alert color="blue">{t('The drawing has no box yet. Add one from the classes of the shapes.')}</Alert>}
      <Help text={t('Positions are not stored: the page lays the drawing out again.')} />
      <Badge variant="light" color="gray" tt="none">{t('{n} boxes, {m} arrows', { n: (map.boxes || []).length, m: (map.arrows || []).length })}</Badge>
    </Stack>
  );
}
