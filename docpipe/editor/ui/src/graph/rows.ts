/* The rows of a box of the Graph tab and what the shapes demand of them. A row is a property the shapes give the class of
   the box, or one an arrow writes that the shapes do not give. The shapes demand a property on its own (at least once,
   sh:minCount), or as one of a group (an sh:or on the node: at least one of these properties): a group is met when an
   arrow, or the box's own number, leads to one of its properties. Pure, so that node runs it in
   tests/test_editor_graph_demands.py. */

export type Obj = Record<string, any>;

export interface Constraint { key: string; component: string; says: unknown; effect: string }
export interface PropInfo {
  path: string; iri: string; curie: string; label: string; min: number | null; max: number | null; constraints: Constraint[];
}
/* `one_of`: the groups of properties (curies) one of which the shapes demand of a node; `constraints`: what the shapes ask
   of the node as a whole (the sh:or), each with its effect */
export interface ClassInfo {
  id: string; shape: string | null; iri: string | null; curie: string | null; label: string | null; properties: PropInfo[];
  one_of?: string[][]; constraints?: Constraint[];
}

export const localName = (name: string) => String(name).split(/[:/#]/).pop() || '';
export const boxIds = (map: Obj): Set<string> => new Set((map.boxes || []).map((b: Obj) => b.id));
export const kindOfArrow = (map: Obj, a: Obj): 'field' | 'link' | 'node' => {
  const ids = boxIds(map);
  return ids.has(a.from) ? (a.from === a.to ? 'node' : 'link') : 'field';
};
/* the box whose nodes an arrow writes on */
export const subjectOf = (map: Obj, a: Obj): string => (kindOfArrow(map, a) === 'link' ? a.from : a.to);

export function classOf(d: { classes: ClassInfo[] }, box: Obj): ClassInfo | null {
  if (!box.class) return null;
  return d.classes.find(c => c.curie === box.class) || d.classes.find(c => c.shape !== null && c.id === localName(box.class)) || null;
}
export function propOf(c: ClassInfo | null, curie: string): PropInfo | null {
  if (!c) return null;
  return c.properties.find(p => p.curie === curie) || c.properties.find(p => p.path === localName(curie)) || null;
}

/* the arrows that write a property on a box */
export const arrowsTo = (map: Obj, boxId: string, curie: string): Obj[] =>
  (map.arrows || []).filter((a: Obj) => subjectOf(map, a) === boxId && localName(a.property) === localName(curie));

/* a group of properties one of which the shapes demand: its number in the class, the names of its properties, and whether
   a way leads to one of them */
export interface OneOf { id: number; labels: string[]; met: boolean }
/* the properties of a box: those the shapes give its class, then those an arrow writes that the shapes do not give */
export interface Row {
  curie: string; label: string; prop: PropInfo | null; required: boolean; oneOf: OneOf[]; used: Obj[]; outside: boolean; uuid: boolean;
}
/* a way to a property: an arrow, or the box's own number (`uuid`) */
const hasWay = (r: Row) => r.used.length > 0 || r.uuid;
/* a row the shapes demand, on its own or as one of a group */
export const demanded = (r: Row) => r.required || r.oneOf.length > 0;
/* red: a required property no way leads to, and every property of a group no way leads to any of */
export const isRed = (r: Row) => (r.required && !hasWay(r)) || r.oneOf.some(g => !g.met);
/* how many demands of the shapes no way meets: each required property, and each group once */
export function missingOf(rows: Row[]): number {
  const groups = new Set<number>();
  let n = 0;
  for (const r of rows) {
    if (r.required && !hasWay(r)) n++;
    for (const g of r.oneOf) if (!g.met) groups.add(g.id);
  }
  return n + groups.size;
}

/* the rows of *box* in *map*, the drawing as it is edited (not as it was loaded), with the classes the server sent */
export function rowsOf(d: { classes: ClassInfo[] }, map: Obj, box: Obj): Row[] {
  const c = classOf(d, box);
  const out: Row[] = [];
  const seen = new Set<string>();
  for (const p of c ? c.properties : []) {
    seen.add(localName(p.curie));
    const used = arrowsTo(map, box.id, p.curie);
    out.push({ curie: p.curie, label: p.label || localName(p.curie), prop: p, required: (p.min || 0) >= 1, oneOf: [], used, outside: false, uuid: !!box.uuid && localName(box.uuid) === localName(p.curie) });
  }
  for (const a of map.arrows || []) {
    if (subjectOf(map, a) !== box.id || seen.has(localName(a.property))) continue;
    seen.add(localName(a.property));
    out.push({ curie: a.property, label: a.label || localName(a.property), prop: null, required: false, oneOf: [], used: arrowsTo(map, box.id, a.property), outside: !!c, uuid: !!box.uuid && localName(box.uuid) === localName(a.property) });
  }
  /* each row of a property of a group knows the group, and the group knows whether a way leads to one of them */
  (c && c.one_of ? c.one_of : []).forEach((group, id) => {
    const names = group.map(localName);
    const members = out.filter(r => names.includes(localName(r.curie)));
    const labels = names.map(name => (members.find(r => localName(r.curie) === name) || { label: name }).label);
    const g: OneOf = { id, labels, met: members.some(hasWay) };
    for (const r of members) r.oneOf.push(g);
  });
  return out;
}
