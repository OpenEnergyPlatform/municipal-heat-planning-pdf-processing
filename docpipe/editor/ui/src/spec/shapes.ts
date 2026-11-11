/* The names the graph shapes know (classes, predicates), offered by the inputs of a kg form; the inputs stay free text and
   stay plain where the shapes are missing (GET /api/graph fails). */
import { useEffect } from 'react';
import { get } from '../lib/api';
import { Store, useStore } from '../lib/nav';

const XSD_TYPES = ['xsd:string', 'xsd:integer', 'xsd:float', 'xsd:decimal', 'xsd:boolean', 'xsd:date', 'xsd:dateTime', 'xsd:gYear'];
let lists: Record<string, string[]> = {
  classes: [], predicates: [], prefixes: ['oeo', 'obo', 'mhpo', 'rdfs', 'dc', 'schema'], datatypes: XSD_TYPES,
};
let started = false;
const changed = new Store(0);

async function loadShapes() {
  if (started) return;
  started = true;
  try {
    const d = await get('/api/graph');
    const classes = new Set<string>(), preds = new Set<string>();
    for (const c of d.classes || []) {
      classes.add(c.id);
      for (const p of c.properties || []) preds.add(String(p.path).replace(/^[^:]*:/, ''));
    }
    lists = { ...lists, classes: [...classes], predicates: [...preds] };
    changed.set(changed.get() + 1);
  } catch { /* no shapes: the inputs stay plain text */ }
}

export function useShapes(): Record<string, string[]> {
  useStore(changed);
  useEffect(() => { void loadShapes(); }, []);
  return lists;
}
